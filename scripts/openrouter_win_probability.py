#!/usr/bin/env python3
"""Estimate per-second UFC win probabilities with OpenRouter Decisions."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import socket
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__:
    from .cosmos_video_understanding import (
        CosmosError,
        SampledWindow,
        build_windows,
        data_uri,
        eprint,
        extract_frames,
        load_env_file,
        parse_fighter_map,
        probe_duration,
        redact_text,
        sha256_file,
    )
else:
    from cosmos_video_understanding import (  # type: ignore[no-redef]
        CosmosError,
        SampledWindow,
        build_windows,
        data_uri,
        eprint,
        extract_frames,
        load_env_file,
        parse_fighter_map,
        probe_duration,
        redact_text,
        sha256_file,
    )


DEFAULT_API_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "cloudflare/clef-flash"
DEFAULT_FPS = 5
DEFAULT_TIMEOUT_S = 120.0
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 524, 529}

DEFAULT_DECISION_PROMPT = """根据 fighter_map、previous_state，以及按时间从早到晚排列的当前 1 秒视频帧，估计选手 A 与选手 B 从当前时点起最终赢得这场 UFC 比赛的相对概率。

判定只参考画面中能够确认的比赛证据：有效进攻及其清晰效果、击倒与后续压制、笼边或地面位置控制、摔跤与起身结果、成型的降服威胁、防守质量，以及画面中可辨识的回合和剩余时间。越靠后的帧越接近当前状态。

A、B 身份必须始终按照 fighter_map 固定，不能按屏幕左右重新分配。禁止使用选手名气、历史战绩、赛前赔率或已知真实赛果，也不要推测不可见的伤势、体能、心理、裁判计分或画面外事件。回放、遮挡、非比赛镜头或身份不明时，不要把它当作新的比赛进展。

当前 1 秒只是新的增量证据：普通单次击打、短暂移动、镜头变化或不明确的局部优势只应小幅改变 previous_state；只有持续且清晰的优势、击倒后的有效跟进、高完成度降服威胁或官方终止才应显著改变概率。previous_state 为 null 时以 A=0.5、B=0.5 为中性基线。

输出表示在忽略平局与无结果的条件下，A 或 B 最终获胜的相对概率。"""


class OpenRouterDecisionError(RuntimeError):
    """OpenRouter Decisions request or response failure."""


class OpenRouterDecisionClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        retries: int = 3,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.retries = max(0, retries)

    def submit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                self.api_url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "FightLens-OpenRouter-Decisions/1.0",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_s
                ) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise OpenRouterDecisionError(
                        "OpenRouter returned a non-object JSON response"
                    )
                return decoded
            except urllib.error.HTTPError as exc:
                body_text = exc.read().decode("utf-8", errors="replace")
                safe_body = redact_text(body_text, self.api_key)
                last_error = OpenRouterDecisionError(
                    f"OpenRouter HTTP {exc.code}: {safe_body}"
                )
                if exc.code not in RETRIABLE_STATUS_CODES or attempt >= self.retries:
                    raise last_error from exc
                delay = retry_delay(attempt, exc.headers.get("Retry-After"))
                eprint(
                    f"OpenRouter returned HTTP {exc.code}; retrying in {delay:.1f}s."
                )
                time.sleep(delay)
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                ConnectionError,
                http.client.HTTPException,
                ssl.SSLError,
                json.JSONDecodeError,
                UnicodeError,
            ) as exc:
                last_error = exc
                if attempt >= self.retries:
                    safe_error = redact_text(str(exc), self.api_key)
                    raise OpenRouterDecisionError(
                        f"OpenRouter request failed: {safe_error}"
                    ) from exc
                delay = retry_delay(attempt, None)
                eprint(f"OpenRouter request error; retrying in {delay:.1f}s.")
                time.sleep(delay)
        raise OpenRouterDecisionError(f"OpenRouter request failed: {last_error}")


def retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 60.0))
        except ValueError:
            pass
    return min(2.0**attempt, 30.0)


def resolve_prompt(inline_prompt: str | None, prompt_file: Path | None) -> str:
    if inline_prompt is not None:
        prompt = inline_prompt.strip()
    elif prompt_file is not None:
        if not prompt_file.is_file():
            raise OpenRouterDecisionError(f"Prompt file not found: {prompt_file}")
        prompt = prompt_file.read_text(encoding="utf-8").strip()
    else:
        prompt = DEFAULT_DECISION_PROMPT
    if not prompt:
        raise OpenRouterDecisionError("Decision prompt must not be empty")
    return prompt


def build_decision_payload(
    model: str,
    window: SampledWindow,
    *,
    fighter_map: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None,
    decision_prompt: str,
    image_detail: str,
) -> dict[str, Any]:
    context = {
        "fighter_map": fighter_map,
        "previous_state": previous_state,
        "window": {
            "start_s": window.start_s,
            "end_s": window.end_s,
            "frame_times_s": list(window.frame_times_s),
            "frame_order": "从早到晚",
        },
    }
    state: list[Any] = [json.dumps(context, ensure_ascii=False, separators=(",", ":"))]
    state.extend(
        {
            "type": "image_url",
            "image_url": {
                "url": data_uri(frame_path, "image/jpeg"),
                "detail": image_detail,
            },
        }
        for frame_path in window.frame_paths
    )
    return {
        "model": model,
        "state": state,
        "questions": {
            "winner": {
                "type": "choice",
                "instructions": decision_prompt,
                "criteria": {
                    "A": "选手 A 最终通过判定、KO/TKO 或降服获胜",
                    "B": "选手 B 最终通过判定、KO/TKO 或降服获胜",
                },
            }
        },
    }


def parse_winner_probabilities(response: Mapping[str, Any]) -> dict[str, Any]:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise OpenRouterDecisionError("OpenRouter response is missing answers")
    winner = answers.get("winner")
    if not isinstance(winner, dict) or winner.get("type") != "choice":
        raise OpenRouterDecisionError(
            "OpenRouter response is missing the winner choice answer"
        )
    probabilities = winner.get("probabilities")
    if not isinstance(probabilities, dict):
        raise OpenRouterDecisionError("Winner answer is missing probabilities")
    try:
        probability_a = float(probabilities["A"])
        probability_b = float(probabilities["B"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenRouterDecisionError(
            "Winner probabilities must contain numeric A and B values"
        ) from exc
    if not all(
        math.isfinite(value) and 0.0 <= value <= 1.0
        for value in (probability_a, probability_b)
    ):
        raise OpenRouterDecisionError("Winner probabilities must be within [0, 1]")
    total = probability_a + probability_b
    if not math.isclose(total, 1.0, abs_tol=0.02):
        raise OpenRouterDecisionError(
            f"Winner probabilities must sum to 1, received {total:.6f}"
        )
    probability_a /= total
    probability_b /= total

    choice = winner.get("choice")
    if choice not in {"A", "B"}:
        choice = "A" if probability_a >= probability_b else "B"
    confidence = winner.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise OpenRouterDecisionError("Winner confidence must be numeric") from exc
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise OpenRouterDecisionError("Winner confidence must be within [0, 1]")

    return {
        "probabilities": {
            "A": round(probability_a, 6),
            "B": round(probability_b, 6),
        },
        "predicted_winner": choice,
        "confidence": confidence,
    }


def emit_result(result: Mapping[str, Any]) -> None:
    print(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )


def default_output_path(video_path: Path) -> Path:
    return Path("runs") / "openrouter" / f"{video_path.stem}_win_probability.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sample ordered video frames each second and request A/B UFC win "
            "probabilities from OpenRouter Decisions."
        )
    )
    parser.add_argument("video", type=Path, help="Input video path")
    parser.add_argument(
        "--fighter-map",
        required=True,
        help="JSON object mapping A/B identities, or @path/to/map.json",
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", help="Override the probability instructions")
    prompt_group.add_argument(
        "--prompt-file", type=Path, help="Read probability instructions from UTF-8 file"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start-second", type=int, default=0)
    parser.add_argument("--max-windows", type=int)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--max-width", type=int, default=768)
    parser.add_argument("--jpeg-quality", type=int, default=3)
    parser.add_argument(
        "--image-detail", choices=("low", "auto", "high"), default="low"
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--realtime",
        action="store_true",
        help=(
            "Pace source windows at one-second intervals when requests are fast enough; "
            "requests remain serial"
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sample frames and validate configuration without calling OpenRouter",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    parsed_api_url = urllib.parse.urlparse(args.api_url)
    if parsed_api_url.scheme != "https" or not parsed_api_url.netloc:
        raise OpenRouterDecisionError("--api-url must be an absolute HTTPS URL")
    if args.start_second < 0:
        raise OpenRouterDecisionError("--start-second must be non-negative")
    if args.max_windows is not None and args.max_windows <= 0:
        raise OpenRouterDecisionError("--max-windows must be positive")
    if args.fps <= 0 or args.fps > 128:
        raise OpenRouterDecisionError("--fps must be between 1 and 128")
    if args.max_width < 64:
        raise OpenRouterDecisionError("--max-width must be at least 64")
    if not 2 <= args.jpeg_quality <= 31:
        raise OpenRouterDecisionError("--jpeg-quality must be between 2 and 31")
    if args.timeout <= 0:
        raise OpenRouterDecisionError("--timeout must be positive")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_args(args)
        fighter_map = parse_fighter_map(args.fighter_map)
        if fighter_map is None:
            raise OpenRouterDecisionError("--fighter-map is required")
        decision_prompt = resolve_prompt(args.prompt, args.prompt_file)
        video_path = args.video.expanduser().resolve()
        if not video_path.is_file():
            raise OpenRouterDecisionError(f"Video not found: {video_path}")

        if not args.dry_run:
            load_env_file(Path.cwd() / ".env")
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not args.dry_run and not api_key:
            raise OpenRouterDecisionError(
                "Missing OPENROUTER_API_KEY; export it in the current shell"
            )

        duration_s = probe_duration(video_path)
        full_seconds = math.floor(duration_s + 1e-6)
        if args.start_second >= full_seconds:
            raise OpenRouterDecisionError(
                f"--start-second {args.start_second} is beyond "
                f"{full_seconds} complete seconds"
            )
        window_count = full_seconds - args.start_second
        if args.max_windows is not None:
            window_count = min(window_count, args.max_windows)

        with tempfile.TemporaryDirectory(prefix="fightlens-openrouter-") as temp_name:
            temp_dir = Path(temp_name)
            frames = extract_frames(
                video_path,
                temp_dir / "frames",
                start_second=args.start_second,
                window_count=window_count,
                fps=args.fps,
                max_width=args.max_width,
                jpeg_quality=args.jpeg_quality,
            )
            windows = build_windows(
                frames, start_second=args.start_second, fps=args.fps
            )
            eprint(
                f"Sampled {len(frames)} frames across {len(windows)} one-second "
                f"windows from {video_path.name}."
            )
            if args.dry_run:
                print(
                    json.dumps(
                        {
                            "video": str(video_path),
                            "model": args.model,
                            "window_count": len(windows),
                            "frames_per_window": args.fps,
                            "first_window_frame_times_s": list(
                                windows[0].frame_times_s
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0

            client = OpenRouterDecisionClient(
                args.api_url,
                api_key,
                timeout_s=args.timeout,
                retries=args.retries,
            )
            output_path = (args.output or default_output_path(video_path)).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists() and not args.overwrite:
                raise OpenRouterDecisionError(
                    f"Output already exists: {output_path}; pass --overwrite"
                )
            output_path.write_text("", encoding="utf-8")

            previous_state: dict[str, Any] | None = None
            attempted = 0
            failures = 0
            run_started = time.monotonic()
            video_sha256 = sha256_file(video_path)
            prompt_sha256 = hashlib.sha256(decision_prompt.encode("utf-8")).hexdigest()

            with output_path.open("a", encoding="utf-8") as output:
                for window in windows:
                    if args.realtime:
                        target_time = run_started + attempted
                        delay = target_time - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
                    attempted += 1
                    eprint(
                        f"[{window.index}] deciding {window.start_s:.1f}-"
                        f"{window.end_s:.1f}s ({len(window.frame_paths)} frames)"
                    )
                    record: dict[str, Any] = {
                        "schema_version": 1,
                        "status": "error",
                        "video": str(video_path),
                        "video_sha256": video_sha256,
                        "window_index": window.index,
                        "start_s": window.start_s,
                        "end_s": window.end_s,
                        "frame_times_s": list(window.frame_times_s),
                        "model": args.model,
                        "fighter_map": fighter_map,
                        "prompt_sha256": prompt_sha256,
                    }
                    try:
                        payload = build_decision_payload(
                            args.model,
                            window,
                            fighter_map=fighter_map,
                            previous_state=previous_state,
                            decision_prompt=decision_prompt,
                            image_detail=args.image_detail,
                        )
                        started = time.monotonic()
                        response = client.submit(payload)
                        latency_s = time.monotonic() - started
                        decision = parse_winner_probabilities(response)
                        result = {
                            "window_index": window.index,
                            "start_s": window.start_s,
                            "end_s": window.end_s,
                            **decision,
                        }
                        record.update(
                            {
                                "status": "ok",
                                "latency_s": round(latency_s, 6),
                                "result": result,
                                "request_id": response.get("id"),
                                "provider": response.get("provider"),
                                "usage": response.get("usage"),
                            }
                        )
                        previous_state = result
                    except Exception as exc:  # noqa: BLE001 - persist safe failure
                        failures += 1
                        record["error"] = redact_text(str(exc), api_key)
                        record["error_type"] = type(exc).__name__
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                    output.flush()
                    if record["status"] == "ok":
                        emit_result(record["result"])
                        eprint(f"[{window.index}] ok in {record['latency_s']:.2f}s")
                    else:
                        eprint(f"[{window.index}] failed: {record['error']}")
                        break

            eprint(
                f"Finished: attempted={attempted}, failed={failures}, "
                f"output={output_path}"
            )
            return 1 if failures else 0
    except (CosmosError, OpenRouterDecisionError, OSError, ValueError) as exc:
        eprint(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
