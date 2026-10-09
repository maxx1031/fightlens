import base64
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from scripts.cosmos_video_understanding import SampledWindow
from scripts.openrouter_win_probability import (
    OpenRouterDecisionClient,
    OpenRouterDecisionError,
    build_decision_payload,
    emit_result,
    parse_winner_probabilities,
)


class OpenRouterWinProbabilityTests(unittest.TestCase):
    def test_payload_contains_ordered_context_and_five_inline_frames(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            frame_paths = []
            for index in range(5):
                path = root / f"frame_{index:06d}.jpg"
                path.write_bytes(f"jpeg-{index}".encode())
                frame_paths.append(path)
            window = SampledWindow(
                index=3,
                start_s=3.0,
                end_s=4.0,
                frame_times_s=(3.1, 3.3, 3.5, 3.7, 3.9),
                frame_paths=tuple(frame_paths),
            )
            fighter_map = {
                "A": {"name": "Alex Pereira"},
                "B": {"name": "Khalil Rountree Jr."},
            }
            previous_state = {
                "window_index": 2,
                "probabilities": {"A": 0.54, "B": 0.46},
            }

            payload = build_decision_payload(
                "openai/gpt-6-luna-decisions",
                window,
                fighter_map=fighter_map,
                previous_state=previous_state,
                decision_prompt="只依据当前可见比赛证据。",
                image_detail="low",
            )

            self.assertEqual(payload["model"], "openai/gpt-6-luna-decisions")
            self.assertEqual(set(payload), {"model", "state", "questions"})
            self.assertEqual(len(payload["state"]), 6)
            context = json.loads(payload["state"][0])
            self.assertEqual(context["fighter_map"], fighter_map)
            self.assertEqual(context["previous_state"], previous_state)
            self.assertEqual(context["window"]["start_s"], 3.0)
            self.assertEqual(
                context["window"]["frame_times_s"], [3.1, 3.3, 3.5, 3.7, 3.9]
            )

            image_items = payload["state"][1:]
            self.assertTrue(all(item["type"] == "image_url" for item in image_items))
            self.assertTrue(
                all(item["image_url"]["detail"] == "low" for item in image_items)
            )
            decoded_frames = [
                base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
                for item in image_items
            ]
            self.assertEqual(
                decoded_frames, [f"jpeg-{index}".encode() for index in range(5)]
            )

            question = payload["questions"]["winner"]
            self.assertEqual(question["type"], "choice")
            self.assertEqual(question["instructions"], "只依据当前可见比赛证据。")
            self.assertEqual(set(question["criteria"]), {"A", "B"})

    def test_parser_accepts_and_normalizes_choice_probabilities(self):
        parsed = parse_winner_probabilities(
            {
                "answers": {
                    "winner": {
                        "type": "choice",
                        "choice": "A",
                        "probabilities": {"A": 0.6, "B": 0.399},
                        "confidence": 0.82,
                    }
                }
            }
        )

        self.assertEqual(parsed["predicted_winner"], "A")
        self.assertEqual(parsed["confidence"], 0.82)
        self.assertAlmostEqual(sum(parsed["probabilities"].values()), 1.0, places=5)
        self.assertGreater(parsed["probabilities"]["A"], parsed["probabilities"]["B"])

    def test_parser_rejects_invalid_probability_responses(self):
        invalid_responses = (
            {},
            {"answers": {"winner": {"type": "text"}}},
            {
                "answers": {
                    "winner": {
                        "type": "choice",
                        "probabilities": {"A": 0.9, "B": 0.9},
                    }
                }
            },
            {
                "answers": {
                    "winner": {
                        "type": "choice",
                        "probabilities": {"A": -0.1, "B": 1.1},
                    }
                }
            },
        )

        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(OpenRouterDecisionError):
                    parse_winner_probabilities(response)

    def test_terminal_result_is_one_compact_json_line_and_flushed(self):
        result = {
            "window_index": 0,
            "start_s": 0.0,
            "end_s": 1.0,
            "probabilities": {"A": 0.51, "B": 0.49},
            "predicted_winner": "A",
            "confidence": 0.2,
        }
        with mock.patch("builtins.print") as print_mock:
            emit_result(result)

        print_mock.assert_called_once_with(
            '{"window_index":0,"start_s":0.0,"end_s":1.0,'
            '"probabilities":{"A":0.51,"B":0.49},'
            '"predicted_winner":"A","confidence":0.2}',
            flush=True,
        )

    def test_client_keeps_api_key_out_of_request_body(self):
        api_key = "sk-or-v1-unit-test-secret"
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"answers":{}}'
        client = OpenRouterDecisionClient(
            "https://openrouter.test/api/alpha/decisions",
            api_key,
            retries=0,
        )

        with mock.patch(
            "scripts.openrouter_win_probability.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            self.assertEqual(
                client.submit({"model": "model-id", "state": []}), {"answers": {}}
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {api_key}")
        self.assertNotIn(api_key.encode(), request.data)

    def test_client_redacts_api_key_from_http_error(self):
        api_key = "sk-or-v1-unit-test-secret"
        response_body = f'{{"error":"Bearer {api_key}","token":"{api_key}"}}'
        http_error = urllib.error.HTTPError(
            "https://openrouter.test/api/alpha/decisions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(response_body.encode()),
        )
        client = OpenRouterDecisionClient(
            "https://openrouter.test/api/alpha/decisions",
            api_key,
            retries=0,
        )

        with (
            mock.patch(
                "scripts.openrouter_win_probability.urllib.request.urlopen",
                side_effect=http_error,
            ),
            self.assertRaises(OpenRouterDecisionError) as raised,
        ):
            client.submit({"model": "model-id", "state": []})

        message = str(raised.exception)
        self.assertNotIn(api_key, message)
        self.assertIn("<redacted>", message)


if __name__ == "__main__":
    unittest.main()
