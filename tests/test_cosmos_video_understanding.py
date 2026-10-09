import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.cosmos_video_understanding as cosmos
from scripts.cosmos_video_understanding import (
    DEFAULT_VAST_COSMOS_API_BASE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_SHA256,
    CosmosClient,
    CosmosHTTPError,
    SampledWindow,
    analyze_window,
    api_url,
    build_windows,
    emit_terminal_scene,
    extract_frames,
    frame_payload,
    frame_times_for_window,
    load_resume_prefix,
    load_successful_windows,
    parse_fighter_map,
    parse_json_object,
    parse_scene_state,
    resolve_api_base,
    response_text,
    scene_prompt,
    sha256_file,
    stable_json_sha256,
    video_payload,
)


class CosmosVideoUnderstandingTests(unittest.TestCase):
    def test_frame_times_use_bin_centers(self):
        self.assertEqual(
            frame_times_for_window(12.0, 5),
            (12.1, 12.3, 12.5, 12.7, 12.9),
        )

    def test_api_url_accepts_base_with_or_without_v1(self):
        expected = "http://example.test:8001/v1/models"
        self.assertEqual(api_url("http://example.test:8001", "/v1/models"), expected)
        self.assertEqual(api_url("http://example.test:8001/v1", "/v1/models"), expected)

    def test_api_base_uses_workshop_default_but_allows_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_api_base(), DEFAULT_VAST_COSMOS_API_BASE)
            os.environ["COSMOS3_REASON_URL"] = "http://env.test:9000"
            self.assertEqual(resolve_api_base(), "http://env.test:9000")
            self.assertEqual(
                resolve_api_base("http://cli.test:9001"), "http://cli.test:9001"
            )

    def test_payload_contains_one_temporal_frame_block(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            paths = []
            for index in range(5):
                path = root / f"frame_{index:06d}.jpg"
                path.write_bytes(b"jpeg-" + str(index).encode("ascii"))
                paths.append(path)
            window = SampledWindow(
                index=0,
                start_s=0.0,
                end_s=1.0,
                frame_times_s=frame_times_for_window(0.0),
                frame_paths=tuple(paths),
            )
            fighter_map = {"A": "red shorts", "B": "blue shorts"}
            previous_state = {"change_status": "initial"}
            payload = frame_payload(
                "model-id",
                window,
                256,
                fighter_map=fighter_map,
                previous_state=previous_state,
            )
            self.assertEqual(len(payload["messages"]), 2)
            self.assertEqual(
                payload["messages"][0],
                {"role": "system", "content": SYSTEM_PROMPT},
            )
            content = payload["messages"][1]["content"]
            self.assertEqual(content[0]["type"], "video_frames")
            self.assertEqual(len(content[0]["video_frames"]), 5)
            self.assertTrue(
                all(
                    value.startswith("data:image/jpeg;base64,")
                    for value in content[0]["video_frames"]
                )
            )
            prompt_input = json.loads(content[1]["text"])
            self.assertEqual(prompt_input["fighter_map"], fighter_map)
            self.assertEqual(prompt_input["previous_state"], previous_state)
            self.assertEqual(payload["temperature"], 0)

    def test_video_payload_contains_same_system_prompt(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            video = root / "window.mp4"
            video.write_bytes(b"video")
            window = SampledWindow(
                index=0,
                start_s=0.0,
                end_s=1.0,
                frame_times_s=(0.1, 0.3, 0.5, 0.7, 0.9),
                frame_paths=tuple(
                    root / f"frame_{index:06d}.jpg" for index in range(5)
                ),
            )
            previous_state = {"change_status": "initial"}
            fighter_map = {"A": "fighter a", "B": "fighter b"}
            payload = video_payload(
                "model-id",
                window,
                video,
                256,
                5,
                fighter_map=fighter_map,
                previous_state=previous_state,
            )
            self.assertEqual(len(payload["messages"]), 2)
            self.assertEqual(
                payload["messages"][0],
                {"role": "system", "content": SYSTEM_PROMPT},
            )
            content = payload["messages"][1]["content"]
            self.assertEqual(content[0]["type"], "video_url")
            prompt_input = json.loads(content[1]["text"])
            self.assertEqual(prompt_input["fighter_map"], fighter_map)
            self.assertEqual(prompt_input["previous_state"], previous_state)

    def test_auto_fallback_preserves_system_and_state_inputs(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            frame_paths = []
            for index in range(5):
                path = root / f"frame_{index:06d}.jpg"
                path.write_bytes(b"jpeg")
                frame_paths.append(path)
            window = SampledWindow(
                index=0,
                start_s=0.0,
                end_s=1.0,
                frame_times_s=(0.1, 0.3, 0.5, 0.7, 0.9),
                frame_paths=tuple(frame_paths),
            )
            fighter_map = {"A": "fighter a", "B": "fighter b"}
            previous_state = {"change_status": "initial"}
            client = mock.Mock(spec=CosmosClient)
            client.request_json.side_effect = [
                CosmosHTTPError(
                    400, "video_frames unsupported", "/v1/chat/completions"
                ),
                {"choices": [{"message": {"content": "{}"}}]},
            ]

            def write_fallback(_window, output_path, _fps):
                output_path.write_bytes(b"video")

            with mock.patch.object(
                cosmos, "encode_window_mp4", side_effect=write_fallback
            ):
                _, used_mode, _ = analyze_window(
                    client,
                    "model-id",
                    window,
                    fighter_map=fighter_map,
                    previous_state=previous_state,
                    max_tokens=256,
                    fps=5,
                    media_mode="auto",
                    temp_dir=root,
                )

            self.assertEqual(used_mode, "video_url")
            self.assertEqual(client.request_json.call_count, 2)
            for call in client.request_json.call_args_list:
                payload = call.args[2]
                self.assertEqual(
                    payload["messages"][0],
                    {"role": "system", "content": SYSTEM_PROMPT},
                )
                prompt_input = json.loads(payload["messages"][1]["content"][1]["text"])
                self.assertEqual(prompt_input["fighter_map"], fighter_map)
                self.assertEqual(prompt_input["previous_state"], previous_state)

    def test_system_prompt_is_fixed(self):
        self.assertEqual(PROMPT_VERSION, 2)
        self.assertEqual(
            hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
            "93b93100395fa0a86bede7e2be7eb595ea01eabca86b18b49210f33ce23ae126",
        )

    def test_prompt_serializes_dynamic_inputs(self):
        window = SampledWindow(
            index=0,
            start_s=0.0,
            end_s=1.0,
            frame_times_s=(0.2, 0.5, 0.8),
            frame_paths=(Path("a.jpg"), Path("b.jpg"), Path("c.jpg")),
        )
        fighter_map = {"A": "red shorts", "B": "blue shorts"}
        previous_state = {"change_status": "initial", "events": []}
        prompt_input = json.loads(scene_prompt(window, fighter_map, previous_state))
        self.assertEqual(prompt_input["fighter_map"], fighter_map)
        self.assertEqual(prompt_input["previous_state"], previous_state)
        self.assertEqual(prompt_input["window"]["frame_count"], 3)
        self.assertEqual(prompt_input["window"]["frame_times_s"], [0.2, 0.5, 0.8])

    def test_json_parser_accepts_bare_or_single_json_fence(self):
        self.assertEqual(parse_json_object('{"ok": true}'), {"ok": True})
        self.assertEqual(parse_json_object('```json\n{"ok": true}\n```'), {"ok": True})
        self.assertIsNone(parse_json_object('result: {"ok": true}'))
        self.assertIsNone(parse_json_object('result:\n```json\n{"ok": true}\n```'))
        self.assertIsNone(parse_json_object("not json"))

    def test_scene_state_enforces_fixed_schema(self):
        scene = {
            "change_status": "initial",
            "phase": "站立对抗",
            "position": {"A": "场内游走", "B": "场内游走"},
            "activity": {"A": "相互观察", "B": "相互观察"},
            "threat": {"A": "无明确威胁", "B": "无明确威胁"},
            "events": [],
        }
        encoded = json.dumps(scene, ensure_ascii=False)
        self.assertEqual(parse_scene_state(encoded, None), scene)
        self.assertEqual(parse_scene_state(f"```json\n{encoded}\n```", None), scene)
        with self.assertRaises(cosmos.CosmosInvalidResponseError):
            parse_scene_state(json.dumps({**scene, "extra": True}), None)
        with self.assertRaises(cosmos.CosmosInvalidResponseError):
            parse_scene_state(json.dumps({**scene, "change_status": "no_change"}), None)
        no_change = {**scene, "change_status": "no_change"}
        self.assertEqual(
            parse_scene_state(json.dumps(no_change, ensure_ascii=False), scene),
            no_change,
        )
        with self.assertRaises(cosmos.CosmosInvalidResponseError):
            parse_scene_state(
                json.dumps({**no_change, "events": ["发生转换"]}, ensure_ascii=False),
                scene,
            )
        with self.assertRaises(cosmos.CosmosInvalidResponseError):
            parse_scene_state(
                json.dumps({**no_change, "phase": "贴身缠斗"}, ensure_ascii=False),
                scene,
            )
        with self.assertRaises(cosmos.CosmosInvalidResponseError):
            parse_scene_state(
                json.dumps({**scene, "change_status": "changed"}, ensure_ascii=False),
                scene,
            )

    def test_response_text(self):
        response = {"choices": [{"message": {"content": "scene"}}]}
        self.assertEqual(response_text(response), "scene")

    def test_terminal_scene_is_one_json_line_and_flushed(self):
        scene = {"phase": "站立对抗", "events": []}
        with mock.patch("builtins.print") as print_mock:
            emit_terminal_scene(scene)
        print_mock.assert_called_once_with(
            '{"phase":"站立对抗","events":[]}', flush=True
        )

    def test_socket_timeout_is_retried_on_python_39(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        client = CosmosClient("http://example.test", "token", retries=1)
        timeout_error = socket.timeout("timed out")
        with (
            mock.patch(
                "scripts.cosmos_video_understanding.urllib.request.urlopen",
                side_effect=[timeout_error, response],
            ) as urlopen,
            mock.patch("scripts.cosmos_video_understanding.time.sleep") as sleep,
        ):
            self.assertEqual(client.request_json("GET", "/v1/models"), {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_resume_requires_matching_run_identity(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "results.jsonl"
            identity = {
                "video_sha256": "abc",
                "model": "model-a",
                "fps": 5,
                "prompt_version": PROMPT_VERSION,
            }
            records = [
                {**identity, "status": "ok", "window_index": 0},
                {
                    **identity,
                    "video_sha256": "other",
                    "status": "ok",
                    "window_index": 1,
                },
                {**identity, "model": "model-b", "status": "ok", "window_index": 2},
                {**identity, "fps": 4, "status": "ok", "window_index": 3},
                {**identity, "prompt_version": 0, "status": "ok", "window_index": 4},
                {**identity, "status": "invalid_response", "window_index": 5},
            ]
            output.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            completed = load_successful_windows(
                output,
                video_sha256="abc",
                model="model-a",
                fps=5,
                prompt_version=PROMPT_VERSION,
            )
            self.assertEqual(completed, {0})

    def test_fighter_map_accepts_inline_json_and_file(self):
        expected = {"A": "红色短裤", "B": {"name": "选手 B", "shorts": "蓝色"}}
        self.assertEqual(
            parse_fighter_map(json.dumps(expected, ensure_ascii=False)), expected
        )
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "fighters.json"
            path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(parse_fighter_map(f"@{path}"), expected)
        with self.assertRaises(cosmos.CosmosError):
            parse_fighter_map('{"A":"only one fighter"}')

    def test_resume_only_uses_contiguous_state_prefix_and_fighter_map(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "results.jsonl"
            fighter_map_hash = stable_json_sha256({"A": "red", "B": "blue"})
            sampling_config_hash = stable_json_sha256(
                {
                    "fps": 5,
                    "max_width": 960,
                    "jpeg_quality": 3,
                    "max_tokens": 512,
                    "media_mode": "auto",
                }
            )
            identity = {
                "video_sha256": "abc",
                "model": "model-a",
                "fps": 5,
                "prompt_version": PROMPT_VERSION,
                "fighter_map_sha256": fighter_map_hash,
                "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
                "sampling_config_sha256": sampling_config_hash,
            }
            scene_zero = {
                "change_status": "initial",
                "phase": "站立对抗",
                "position": {"A": "场内游走", "B": "场内游走"},
                "activity": {"A": "相互观察", "B": "相互观察"},
                "threat": {"A": "无明确威胁", "B": "无明确威胁"},
                "events": [],
            }
            scene_one = {
                **scene_zero,
                "change_status": "changed",
                "phase": "贴身缠斗",
                "events": ["A 将 B 压到笼边"],
            }
            stale_scene_two = {**scene_zero, "events": ["旧转换"]}
            records = [
                {
                    **identity,
                    "status": "ok",
                    "window_index": 0,
                    "scene": scene_zero,
                    "previous_state": None,
                    "previous_state_window_index": None,
                },
                {
                    **identity,
                    "status": "error",
                    "window_index": 1,
                    "previous_state": scene_zero,
                    "previous_state_window_index": 0,
                },
                {
                    **identity,
                    "status": "ok",
                    "window_index": 2,
                    "scene": stale_scene_two,
                    "previous_state": None,
                    "previous_state_window_index": None,
                },
                {
                    **identity,
                    "status": "ok",
                    "window_index": 1,
                    "scene": scene_one,
                    "previous_state": scene_zero,
                    "previous_state_window_index": 0,
                },
            ]
            output.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            prefix = load_resume_prefix(
                output,
                video_sha256="abc",
                model="model-a",
                fps=5,
                prompt_version=PROMPT_VERSION,
                fighter_map_sha256=fighter_map_hash,
                system_prompt_sha256=SYSTEM_PROMPT_SHA256,
                sampling_config_sha256=sampling_config_hash,
                start_second=0,
            )
            self.assertEqual(prefix, {0: scene_zero, 1: scene_one})
            mismatched = load_resume_prefix(
                output,
                video_sha256="abc",
                model="model-a",
                fps=5,
                prompt_version=PROMPT_VERSION,
                fighter_map_sha256=stable_json_sha256({"A": "blue", "B": "red"}),
                system_prompt_sha256=SYSTEM_PROMPT_SHA256,
                sampling_config_sha256=sampling_config_hash,
                start_second=0,
            )
            self.assertEqual(mismatched, {})

            malformed_record = {
                **identity,
                "status": "ok",
                "window_index": 0,
                "scene": {"foo": "bar"},
                "previous_state": None,
                "previous_state_window_index": None,
            }
            output.write_text(json.dumps(malformed_record) + "\n", encoding="utf-8")
            malformed = load_resume_prefix(
                output,
                video_sha256="abc",
                model="model-a",
                fps=5,
                prompt_version=PROMPT_VERSION,
                fighter_map_sha256=fighter_map_hash,
                system_prompt_sha256=SYSTEM_PROMPT_SHA256,
                sampling_config_sha256=sampling_config_hash,
                start_second=0,
            )
            self.assertEqual(malformed, {})

    def test_previous_state_flows_to_next_window(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            video = root / "video.mp4"
            output = root / "output.jsonl"
            video.write_bytes(b"video fixture")
            frame_paths = [root / f"frame_{index:06d}.jpg" for index in range(10)]
            scene_zero = {
                "change_status": "initial",
                "phase": "站立对抗",
                "position": {"A": "场内游走", "B": "场内游走"},
                "activity": {"A": "相互观察", "B": "相互观察"},
                "threat": {"A": "无明确威胁", "B": "无明确威胁"},
                "events": [],
            }
            scene_one = {**scene_zero, "change_status": "no_change"}
            responses = [
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(scene_zero, ensure_ascii=False)
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(scene_one, ensure_ascii=False)
                            }
                        }
                    ]
                },
            ]
            environment = {
                "GPU_BEARER_TOKEN": "test-token",
                "COSMOS3_REASON_MODEL": "model-a",
            }
            fighter_map = {"A": "红色短裤", "B": "蓝色短裤"}
            with (
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(cosmos, "load_configuration_files", return_value=[]),
                mock.patch.object(cosmos, "probe_duration", return_value=2.0),
                mock.patch.object(cosmos, "extract_frames", return_value=frame_paths),
                mock.patch.object(
                    cosmos,
                    "analyze_window",
                    side_effect=[
                        (responses[0], "video_frames", 0.1),
                        (responses[1], "video_frames", 0.1),
                    ],
                ) as analyze,
                mock.patch("sys.stdout", new_callable=io.StringIO) as terminal,
            ):
                result = cosmos.main(
                    [
                        str(video),
                        "--output",
                        str(output),
                        "--fighter-map",
                        json.dumps(fighter_map, ensure_ascii=False),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIsNone(analyze.call_args_list[0].kwargs["previous_state"])
            self.assertEqual(
                analyze.call_args_list[1].kwargs["previous_state"], scene_zero
            )
            for call in analyze.call_args_list:
                self.assertEqual(call.kwargs["fighter_map"], fighter_map)
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[0]["schema_version"], 3)
            self.assertIsNone(records[0]["previous_state"])
            self.assertEqual(records[1]["previous_state"], scene_zero)
            terminal_scenes = [
                json.loads(line) for line in terminal.getvalue().splitlines()
            ]
            self.assertEqual(terminal_scenes, [scene_zero, scene_one])

    def test_invalid_model_json_is_recorded_as_invalid_response(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            video = root / "video.mp4"
            output = root / "output.jsonl"
            video.write_bytes(b"video fixture")
            frame_paths = [root / f"frame_{index:06d}.jpg" for index in range(10)]
            response = {"choices": [{"message": {"content": "not json"}}]}
            environment = {
                "GPU_BEARER_TOKEN": "test-token",
                "COSMOS3_REASON_MODEL": "model-a",
            }
            with (
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(cosmos, "load_configuration_files", return_value=[]),
                mock.patch.object(cosmos, "probe_duration", return_value=2.0),
                mock.patch.object(cosmos, "extract_frames", return_value=frame_paths),
                mock.patch.object(
                    cosmos,
                    "analyze_window",
                    return_value=(response, "video_frames", 0.1),
                ) as analyze,
                mock.patch("sys.stdout", new_callable=io.StringIO) as terminal,
            ):
                result = cosmos.main(
                    [
                        str(video),
                        "--output",
                        str(output),
                        "--max-windows",
                        "2",
                        "--fighter-map",
                        '{"A":"red","B":"blue"}',
                    ]
                )
            self.assertEqual(result, 1)
            self.assertEqual(analyze.call_count, 1)
            output_lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(output_lines), 1)
            record = json.loads(output_lines[0])
            self.assertEqual(record["status"], "invalid_response")
            self.assertNotIn("scene", record)
            self.assertEqual(record["raw_response_text"], "not json")
            self.assertEqual(record["video_sha256"], sha256_file(video))
            self.assertEqual(terminal.getvalue(), "")

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_extracts_frames_at_requested_source_pts(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            video = root / "fixture.mkv"
            result = subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        "nullsrc=size=160x120:rate=30:duration=2,"
                        "geq=lum='16+N*3':cb=128:cr=128"
                    ),
                    "-an",
                    "-c:v",
                    "ffv1",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(video),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            frames = extract_frames(
                video,
                root / "frames",
                start_second=0,
                window_count=2,
                max_width=160,
                jpeg_quality=2,
            )
            self.assertEqual(len(frames), 10)
            windows = build_windows(frames, start_second=0)
            self.assertEqual(len(windows), 2)
            self.assertEqual(windows[1].frame_times_s, (1.1, 1.3, 1.5, 1.7, 1.9))

            decoded = subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-start_number",
                    "0",
                    "-i",
                    str(root / "frames" / "frame_%06d.jpg"),
                    "-frames:v",
                    "10",
                    "-pix_fmt",
                    "gray",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                check=False,
                capture_output=True,
            )
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
            frame_size = 160 * 120
            means = [
                round(
                    sum(decoded.stdout[index * frame_size : (index + 1) * frame_size])
                    / frame_size
                )
                for index in range(10)
            ]
            # At 30 FPS, 0.1 + 0.2*n maps exactly to source frames
            # 3, 9, ..., 57. Their encoded luma values prove those PTS,
            # rather than the previously observed 0.167 + 0.2*n, were sampled.
            self.assertEqual(means, [10, 31, 52, 73, 94, 115, 136, 157, 178, 199])


if __name__ == "__main__":
    unittest.main()
