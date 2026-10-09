#!/usr/bin/env python3
"""Run per-second scene understanding with NVIDIA Cosmos3 Reason.

For every complete source-video second, this script samples five JPEG frames at
the centers of five equal temporal bins and sends them in one ``video_frames``
content block. The VAST Builders Challenge endpoint is OpenAI-compatible, but
its bearer token must never be committed or printed.
"""

from __future__ import annotations

import argparse
import base64
import glob
import hashlib
import http.client
import json
import math
import os
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_FPS = 5
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_MAX_TOKENS = 512
DEFAULT_VAST_COSMOS_API_BASE = "http://166.19.38.112:8001"
PROMPT_VERSION = 2
SYSTEM_PROMPT = """你是 UFC 实时比赛的场景观察器。

## 任务

分析按时间先后排列的最近 1 秒视频帧，提取当前对抗局面，输出固定格式的 JSON。

## 输入

- `fighter_map`：选手 A、B 的固定身份或稳定外观特征。
- `previous_state`：上一轮输出的完整 JSON；首次调用为 `null`。
- 视频帧：从早到晚排列，全部来自当前 1 秒窗口。

## 只关注四类信息

1. **phase——对抗形态**\u0020\u0020
   只能选择：站立对抗、贴身缠斗、地面缠斗、比赛暂停、无法判断。

2. **position——位置与控制关系**\u0020\u0020
   分别描述 A、B 的位置，例如场内游走、背靠笼网、压制对方于笼边、上位、下位、骑乘、被骑乘、背后控制、被背控；只有确实看清时才使用具体术语。

3. **activity——当前攻防行为**\u0020\u0020
   分别描述 A、B 当前主要行为，例如相互观察、主动进攻、持续防守、尝试抱摔、尝试起身、尝试脱离、尝试反转。

4. **threat——正在施加的进攻威胁**\u0020\u0020
   分别描述 A、B 正在施加的具体威胁，例如连续地面打击、绞技尝试、关节技尝试；充分可见但未观察到明确威胁时填“无明确威胁”，看不清时填“无法判断”。

## 判断规则

- 当前状态以片段末尾为准，前面的帧用于理解动作及本秒内发生的转换。
- A、B 的身份必须全程一致，不能按屏幕左右重新分配；身份无法确认时，不猜测相关归属。
- 分别判断位置控制、当前行为和威胁发起者；不能因为 A 在上位，就认定只有 A 能发起降服。
- 只报告可见事实，不判断伤势、疼痛、体能、心理、裁判比分、胜率或即将发生的结果，也不统计逐拳命中。
- 只描述相对于对手和笼网的位置；镜头移动、缩放、角度变化、措辞变化均不算比赛状态变化。
- 回放不得当作新的比赛进展；遮挡、非比赛镜头或身份不明时，受影响字段填“无法判断”，不能用 previous_state 补成当前事实。
- `events` 仅记录本秒内明确发生的关键转换，例如“B 脱离 A 的笼边压制”“A 尝试抱摔，B 防住后双方恢复站立”；最多两条，每条不超过 35 个汉字。
- 即使末尾状态恢复原样，也要记录本秒内明确发生的关键转换；持续中的同一动作不反复报告为新事件。

## change_status 的取值

- `initial`：previous_state 为 null；仍需记录本秒内明确发生的 events。
- `changed`：存在新的关键事件，或相对 previous_state 可确认至少一项场景状态发生实质变化；其他字段看不清时仍保留 changed。
- `unknown`：没有证实变化，但因遮挡、身份不明、回放或前后状态不可比，无法确认是否无变化。
- `no_change`：存在可比较的 previous_state，四类场景状态均有充分证据表明未变，且没有新的关键事件。

无论 change_status 为何，都输出完整 JSON；没有新事件时 events 为空数组。

## 输出约束

只输出一个合法 JSON 对象，不添加 Markdown、解释或额外字段。

所有描述使用简短中文；position、activity、threat 中每个值不超过 20 个汉字，同一事实使用相同措辞。

下面是固定结构示例，必须根据实际画面替换各字段的值：

```json
{
  "change_status": "initial",
  "phase": "无法判断",
  "position": {
    "A": "无法判断",
    "B": "无法判断"
  },
  "activity": {
    "A": "无法判断",
    "B": "无法判断"
  },
  "threat": {
    "A": "无法判断",
    "B": "无法判断"
  },
  "events": []
}
```"""
SYSTEM_PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
CONFIG_KEYS = {
    "COSMOS3_REASON_URL",
    "COSMOS3_REASON_MODEL",
    "GPU_BEARER_TOKEN",
    "COSMOS_API_BASE",
    "COSMOS_MODEL",
    "COSMOS_API_KEY",
    "COSMOS_TIMEOUT_S",
}


class CosmosError(RuntimeError):
    """Base error for Cosmos configuration and requests."""


class CosmosHTTPError(CosmosError):
    """HTTP failure with a safe, truncated response body."""

    def __init__(self, status: int, body: str, path: str) -> None:
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"Cosmos HTTP {status} for {path}: {body}")


class CosmosInvalidResponseError(CosmosError):
    """The model returned text that is not the requested JSON object."""


@dataclass(frozen=True)
class SampledWindow:
    index: int
    start_s: float
    end_s: float
    frame_times_s: tuple[float, ...]
    frame_paths: tuple[Path, ...]


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def emit_terminal_scene(scene: Mapping[str, Any]) -> None:
    """Emit one completed video-second result as one immediately flushed JSON line."""

    print(
        json.dumps(scene, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )


def _parse_env_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        lexer = shlex.shlex(raw, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        values = list(lexer)
    except ValueError:
        return raw.strip("'\"")
    return " ".join(values)


def load_env_file(path: Path, *, override: bool = False) -> bool:
    """Load simple KEY=VALUE entries without executing the file."""

    if not path.is_file():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        if key not in CONFIG_KEYS:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = _parse_env_value(raw_value)
    return True


def load_configuration_files(explicit_path: Path | None) -> list[Path]:
    """Load project .env and the single workshop config, if present."""

    loaded: list[Path] = []
    project_env = Path.cwd() / ".env"
    if load_env_file(project_env):
        loaded.append(project_env)

    if explicit_path:
        if not explicit_path.is_file():
            raise CosmosError(f"Environment file not found: {explicit_path}")
        load_env_file(explicit_path, override=True)
        loaded.append(explicit_path)

    workshop_configs = [Path(value) for value in sorted(glob.glob("/config/*.config"))]
    if len(workshop_configs) == 1:
        if load_env_file(workshop_configs[0]):
            loaded.append(workshop_configs[0])
    elif len(workshop_configs) > 1:
        eprint(
            "Warning: multiple /config/*.config files found; use --env-file explicitly."
        )
    return loaded


def first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def stable_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_fighter_map(raw: str | None) -> dict[str, Any] | None:
    """Parse an inline JSON fighter map or @path/to/map.json."""

    if raw is None:
        return None
    source = raw
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        if not path.is_file():
            raise CosmosError(f"Fighter map file not found: {path}")
        source = path.read_text(encoding="utf-8")
    try:
        fighter_map = json.loads(source)
    except json.JSONDecodeError as exc:
        raise CosmosError(f"Invalid fighter map JSON: {exc}") from exc
    if not isinstance(fighter_map, dict):
        raise CosmosError("Fighter map must be a JSON object with exactly A and B")
    if set(fighter_map) != {"A", "B"}:
        raise CosmosError("Fighter map must contain exactly the keys A and B")
    for fighter_id, identity in fighter_map.items():
        if not isinstance(identity, (str, dict)) or not identity:
            raise CosmosError(
                f"Fighter map value for {fighter_id} must be a non-empty string or object"
            )
    return fighter_map


def resolve_api_base(cli_value: str | None = None) -> str:
    """Resolve the Cosmos endpoint, preferring explicit/local configuration."""

    return (
        first_nonempty(
            cli_value,
            os.environ.get("COSMOS3_REASON_URL"),
            os.environ.get("COSMOS_API_BASE"),
            DEFAULT_VAST_COSMOS_API_BASE,
        )
        or DEFAULT_VAST_COSMOS_API_BASE
    )


def api_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return base + path[3:]
    return base + "/" + path.lstrip("/")


def redact_text(text: str, token: str | None, limit: int = 600) -> str:
    safe = text.replace(token, "<redacted>") if token else text
    safe = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1<redacted>", safe)
    safe = re.sub(
        r"(?i)(api[_-]?key|token|password)(\s*[:=]\s*)[^\s,}\]]+",
        r"\1\2<redacted>",
        safe,
    )
    safe = " ".join(safe.split())
    return safe[:limit]


class CosmosClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self.retries = max(0, retries)

    def _headers(self, has_json_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "FightLens-Cosmos-SmokeTest/1.0",
        }
        if has_json_body:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                api_url(self.base_url, path),
                data=body,
                headers=self._headers(payload is not None),
                method=method.upper(),
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_s
                ) as response:
                    raw = response.read()
                decoded = json.loads(raw.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise CosmosError(f"Expected JSON object from {path}")
                return decoded
            except urllib.error.HTTPError as exc:
                raw_error = exc.read().decode("utf-8", errors="replace")
                safe_body = redact_text(raw_error, self.token)
                http_error = CosmosHTTPError(exc.code, safe_body, path)
                last_error = http_error
                if exc.code not in RETRIABLE_STATUS_CODES or attempt >= self.retries:
                    raise http_error from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = _retry_delay(attempt, retry_after)
                eprint(f"Cosmos returned HTTP {exc.code}; retrying in {delay:.1f}s.")
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
                    raise CosmosError(
                        f"Cosmos request failed for {path}: {redact_text(str(exc), self.token)}"
                    ) from exc
                delay = _retry_delay(attempt, None)
                eprint(f"Cosmos request error; retrying in {delay:.1f}s.")
                time.sleep(delay)
        raise CosmosError(f"Cosmos request failed: {last_error}")

    def discover_model(self) -> str:
        response = self.request_json("GET", "/v1/models")
        models = response.get("data")
        if not isinstance(models, list) or not models:
            raise CosmosError("/v1/models returned no models")
        model_id = models[0].get("id") if isinstance(models[0], dict) else None
        if not isinstance(model_id, str) or not model_id:
            raise CosmosError("/v1/models response is missing data[0].id")
        return model_id

    def health_check(self) -> dict[str, Any]:
        ready = self.request_json("GET", "/v1/health/ready")
        live = self.request_json("GET", "/v1/health/live")
        model = self.discover_model()
        return {"ready": ready, "live": live, "model": model}


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 60.0))
        except ValueError:
            pass
    return min(2.0**attempt, 30.0)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CosmosError(f"Required executable not found: {name}")
    return path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_duration(video_path: Path) -> float:
    ffprobe = require_tool("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CosmosError(f"ffprobe failed: {result.stderr.strip()}")
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise CosmosError("ffprobe returned an invalid video duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise CosmosError(f"Invalid video duration: {duration}")
    return duration


def frame_times_for_window(start_s: float, fps: int = DEFAULT_FPS) -> tuple[float, ...]:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return tuple(round(start_s + (index + 0.5) / fps, 6) for index in range(fps))


def extract_frames(
    video_path: Path,
    output_dir: Path,
    *,
    start_second: int,
    window_count: int,
    fps: int = DEFAULT_FPS,
    max_width: int = 960,
    jpeg_quality: int = 3,
) -> list[Path]:
    """Extract center-bin frames for all requested windows in one ffmpeg pass."""

    if window_count <= 0:
        return []
    ffmpeg = require_tool("ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    total_frames = window_count * fps
    first_sample_s = start_second + 0.5 / fps
    output_pattern = output_dir / "frame_%06d.jpg"
    # Keep source timestamps until selection. The selected_n expression advances the
    # next absolute target only after a frame is emitted, so it selects the first
    # source frame at (or immediately after) every requested center timestamp.
    # The epsilon avoids missing a target such as 0.3 due to floating-point rounding.
    select_filter = (
        "setpts=PTS-STARTPTS,"
        f"select='gte(t+0.000001,{first_sample_s:.6f}+selected_n/{fps})',"
        f"scale=w='min({max_width},iw)':h=-2:flags=lanczos"
    )
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-an",
        "-vf",
        select_filter,
        "-frames:v",
        str(total_frames),
        "-vsync",
        "vfr",
        "-q:v",
        str(jpeg_quality),
        "-start_number",
        "0",
        str(output_pattern),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise CosmosError(f"ffmpeg frame extraction failed: {result.stderr.strip()}")
    frames = sorted(output_dir.glob("frame_*.jpg"))
    if len(frames) != total_frames:
        raise CosmosError(
            f"Expected {total_frames} sampled frames, but ffmpeg produced {len(frames)}"
        )
    return frames


def build_windows(
    frames: Sequence[Path],
    *,
    start_second: int,
    fps: int = DEFAULT_FPS,
) -> list[SampledWindow]:
    if len(frames) % fps:
        raise ValueError("frame count must be divisible by fps")
    windows: list[SampledWindow] = []
    for offset in range(len(frames) // fps):
        start_s = float(start_second + offset)
        group = tuple(frames[offset * fps : (offset + 1) * fps])
        windows.append(
            SampledWindow(
                index=start_second + offset,
                start_s=start_s,
                end_s=start_s + 1.0,
                frame_times_s=frame_times_for_window(start_s, fps),
                frame_paths=group,
            )
        )
    return windows


def data_uri(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def scene_prompt(
    window: SampledWindow,
    fighter_map: Mapping[str, Any] | None = None,
    previous_state: Mapping[str, Any] | None = None,
) -> str:
    """Serialize only the per-window inputs; behavioral rules live in SYSTEM_PROMPT."""

    prompt_input = {
        "fighter_map": fighter_map,
        "previous_state": previous_state,
        "window": {
            "start_s": window.start_s,
            "end_s": window.end_s,
            "frame_count": len(window.frame_paths),
            "frame_times_s": list(window.frame_times_s),
        },
    }
    return json.dumps(prompt_input, ensure_ascii=False, separators=(",", ":"))


def frame_payload(
    model: str,
    window: SampledWindow,
    max_tokens: int,
    *,
    fighter_map: Mapping[str, Any] | None = None,
    previous_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    frames = [data_uri(path, "image/jpeg") for path in window.frame_paths]
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "video_frames", "video_frames": frames},
                    {
                        "type": "text",
                        "text": scene_prompt(window, fighter_map, previous_state),
                    },
                ],
            },
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }


def encode_window_mp4(window: SampledWindow, output_path: Path, fps: int) -> None:
    ffmpeg = require_tool("ffmpeg")
    first_number = int(window.frame_paths[0].stem.split("_")[-1])
    pattern = window.frame_paths[0].parent / "frame_%06d.jpg"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        str(fps),
        "-start_number",
        str(first_number),
        "-i",
        str(pattern),
        "-frames:v",
        str(fps),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise CosmosError(
            f"ffmpeg fallback clip encoding failed: {result.stderr.strip()}"
        )


def video_payload(
    model: str,
    window: SampledWindow,
    video_path: Path,
    max_tokens: int,
    fps: int,
    *,
    fighter_map: Mapping[str, Any] | None = None,
    previous_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": data_uri(video_path, "video/mp4")},
                    },
                    {
                        "type": "text",
                        "text": scene_prompt(window, fighter_map, previous_state),
                    },
                ],
            },
        ],
        "media_io_kwargs": {"video": {"num_frames": fps}},
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }


def response_text(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise CosmosError("Cosmos response is missing choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise CosmosError("Cosmos response is missing choices[0].message")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if text_parts:
            return "\n".join(text_parts)
    raise CosmosError("Cosmos response message has no text content")


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse one JSON object, optionally wrapped in one JSON Markdown fence."""

    candidate = text.strip()
    fence = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        candidate,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_scene_state(
    text: str, previous_state: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Parse and enforce the fixed scene-state contract from SYSTEM_PROMPT."""

    scene = parse_json_object(text)
    if scene is None:
        raise CosmosInvalidResponseError(
            "Cosmos response was not one valid JSON object"
        )
    return validate_scene_state(scene, previous_state)


def validate_scene_state(
    scene: Mapping[str, Any], previous_state: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Validate one decoded scene and its relationship to the prior state."""

    expected_keys = {
        "change_status",
        "phase",
        "position",
        "activity",
        "threat",
        "events",
    }
    if set(scene) != expected_keys:
        raise CosmosInvalidResponseError(
            "Cosmos response keys did not match the fixed scene schema"
        )

    change_status = scene["change_status"]
    allowed_change_statuses = {"initial", "changed", "unknown", "no_change"}
    if (
        not isinstance(change_status, str)
        or change_status not in allowed_change_statuses
    ):
        raise CosmosInvalidResponseError("Cosmos returned an invalid change_status")
    if previous_state is None and change_status != "initial":
        raise CosmosInvalidResponseError(
            "Cosmos must return change_status=initial when previous_state is null"
        )
    if previous_state is not None and change_status == "initial":
        raise CosmosInvalidResponseError(
            "Cosmos cannot return change_status=initial when previous_state is present"
        )

    allowed_phases = {
        "站立对抗",
        "贴身缠斗",
        "地面缠斗",
        "比赛暂停",
        "无法判断",
    }
    if not isinstance(scene["phase"], str) or scene["phase"] not in allowed_phases:
        raise CosmosInvalidResponseError("Cosmos returned an invalid phase")

    for field in ("position", "activity", "threat"):
        values = scene[field]
        if not isinstance(values, dict) or set(values) != {"A", "B"}:
            raise CosmosInvalidResponseError(
                f"Cosmos response field {field} must contain exactly A and B"
            )
        for value in values.values():
            if not isinstance(value, str) or not value or len(value) > 20:
                raise CosmosInvalidResponseError(
                    f"Cosmos response field {field} values must be 1-20 characters"
                )

    events = scene["events"]
    if not isinstance(events, list) or len(events) > 2:
        raise CosmosInvalidResponseError(
            "Cosmos response events must be an array with at most two entries"
        )
    if any(
        not isinstance(event, str) or not event or len(event) > 35 for event in events
    ):
        raise CosmosInvalidResponseError(
            "Each Cosmos response event must be a 1-35 character string"
        )
    if change_status in {"unknown", "no_change"} and events:
        raise CosmosInvalidResponseError(
            f"Cosmos returned events with change_status={change_status}"
        )
    if previous_state is not None:
        tracked_fields = ("phase", "position", "activity", "threat")
        state_changed = any(
            scene[field] != previous_state.get(field) for field in tracked_fields
        )
        if change_status == "no_change" and state_changed:
            raise CosmosInvalidResponseError(
                "Cosmos returned no_change but scene fields changed"
            )
        if change_status == "changed" and not events and not state_changed:
            raise CosmosInvalidResponseError(
                "Cosmos returned changed without an event or scene-field change"
            )
    return dict(scene)


def should_fallback_to_video(exc: CosmosHTTPError) -> bool:
    if exc.status not in {400, 422}:
        return False
    lowered = exc.body.lower()
    hints = ("video_frames", "unsupported", "validation", "content type", "literal")
    return any(hint in lowered for hint in hints)


def load_successful_windows(
    output_path: Path,
    *,
    video_sha256: str,
    model: str,
    fps: int,
    prompt_version: int,
    fighter_map_sha256: str | None = None,
) -> set:
    """Return successful windows produced with the exact current run identity."""

    completed = set()
    if not output_path.is_file():
        return completed
    for line in output_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        same_run = (
            record.get("video_sha256") == video_sha256
            and record.get("model") == model
            and record.get("fps") == fps
            and record.get("prompt_version") == prompt_version
            and (
                fighter_map_sha256 is None
                or record.get("fighter_map_sha256") == fighter_map_sha256
            )
        )
        if (
            same_run
            and record.get("status") == "ok"
            and isinstance(record.get("window_index"), int)
        ):
            completed.add(record["window_index"])
    return completed


def load_resume_prefix(
    output_path: Path,
    *,
    video_sha256: str,
    model: str,
    fps: int,
    prompt_version: int,
    fighter_map_sha256: str,
    system_prompt_sha256: str,
    sampling_config_sha256: str,
    start_second: int,
) -> dict[int, dict[str, Any]]:
    """Load the contiguous successful state prefix required by stateful prompts."""

    latest_records: dict[int, dict[str, Any]] = {}
    if not output_path.is_file():
        return {}
    for line in output_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        same_run = (
            record.get("video_sha256") == video_sha256
            and record.get("model") == model
            and record.get("fps") == fps
            and record.get("prompt_version") == prompt_version
            and record.get("fighter_map_sha256") == fighter_map_sha256
            and record.get("system_prompt_sha256") == system_prompt_sha256
            and record.get("sampling_config_sha256") == sampling_config_sha256
        )
        window_index = record.get("window_index")
        if not same_run or not isinstance(window_index, int):
            continue
        scene = record.get("scene")
        if record.get("status") == "ok" and isinstance(scene, dict):
            latest_records[window_index] = record
        else:
            latest_records.pop(window_index, None)

    prefix: dict[int, dict[str, Any]] = {}
    window_index = start_second
    previous_scene: dict[str, Any] | None = None
    previous_window_index: int | None = None
    while window_index in latest_records:
        record = latest_records[window_index]
        if record.get("previous_state_window_index") != previous_window_index:
            break
        if record.get("previous_state") != previous_scene:
            break
        try:
            scene = validate_scene_state(record["scene"], previous_scene)
        except CosmosInvalidResponseError:
            break
        prefix[window_index] = scene
        previous_scene = scene
        previous_window_index = window_index
        window_index += 1
    return prefix


def default_output_path(video_path: Path) -> Path:
    return Path("runs") / "cosmos" / f"{video_path.stem}.jsonl"


def analyze_window(
    client: CosmosClient,
    model: str,
    window: SampledWindow,
    *,
    fighter_map: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
    max_tokens: int,
    fps: int,
    media_mode: str,
    temp_dir: Path,
) -> tuple[dict[str, Any], str, float]:
    selected_mode = "video_frames" if media_mode in {"auto", "frames"} else "video_url"
    if selected_mode == "video_frames":
        payload = frame_payload(
            model,
            window,
            max_tokens,
            fighter_map=fighter_map,
            previous_state=previous_state,
        )
        started = time.monotonic()
        try:
            response = client.request_json("POST", "/v1/chat/completions", payload)
            return response, selected_mode, time.monotonic() - started
        except CosmosHTTPError as exc:
            if media_mode != "auto" or not should_fallback_to_video(exc):
                raise
            eprint(
                f"Endpoint rejected video_frames; retrying this window as a {fps} FPS MP4."
            )

    fallback_path = temp_dir / f"window_{window.index:06d}.mp4"
    encode_window_mp4(window, fallback_path, fps)
    payload = video_payload(
        model,
        window,
        fallback_path,
        max_tokens,
        fps,
        fighter_map=fighter_map,
        previous_state=previous_state,
    )
    started = time.monotonic()
    response = client.request_json("POST", "/v1/chat/completions", payload)
    return response, "video_url", time.monotonic() - started


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sample five frames per video second and call Cosmos3 Reason once per second."
    )
    parser.add_argument("video", nargs="?", type=Path, help="Input video path")
    parser.add_argument(
        "--check", action="store_true", help="Check Cosmos health/model and exit"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Sample frames without network calls"
    )
    parser.add_argument("--env-file", type=Path, help="Explicit env/config file")
    parser.add_argument("--api-base", help="Override COSMOS3_REASON_URL")
    parser.add_argument(
        "--model", help="Override model id; otherwise discover via /v1/models"
    )
    parser.add_argument(
        "--fighter-map",
        help=(
            "JSON object mapping A/B to fixed identities or appearances; "
            "prefix with @ to read UTF-8 JSON from a file"
        ),
    )
    parser.add_argument("--output", type=Path, help="JSONL output path")
    parser.add_argument(
        "--start-second", type=int, default=0, help="First whole second to process"
    )
    parser.add_argument(
        "--max-windows", type=int, help="Maximum one-second windows to process"
    )
    parser.add_argument(
        "--fps", type=int, default=DEFAULT_FPS, help="Frames sampled per second"
    )
    parser.add_argument(
        "--max-width", type=int, default=960, help="Maximum JPEG frame width"
    )
    parser.add_argument(
        "--jpeg-quality", type=int, default=3, help="ffmpeg JPEG q:v (2-31)"
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--timeout", type=float, help="Per-request timeout in seconds")
    parser.add_argument(
        "--retries", type=int, default=3, help="Retries for 429/5xx/network errors"
    )
    parser.add_argument(
        "--media-mode",
        choices=("auto", "frames", "video"),
        default="auto",
        help="Use video_frames, MP4 video_url, or automatic fallback",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Pace request starts at one per source second when inference is fast enough",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing JSONL output"
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Compatibility flag; stateful runs always stop after the first failed window",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if not args.check and args.video is None:
        raise CosmosError("A video path is required unless --check is used")
    if args.start_second < 0:
        raise CosmosError("--start-second must be non-negative")
    if args.max_windows is not None and args.max_windows <= 0:
        raise CosmosError("--max-windows must be positive")
    if args.fps <= 0:
        raise CosmosError("--fps must be positive")
    if args.max_width < 64:
        raise CosmosError("--max-width must be at least 64")
    if not 2 <= args.jpeg_quality <= 31:
        raise CosmosError("--jpeg-quality must be between 2 and 31")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
        loaded_files = load_configuration_files(args.env_file)
        for path in loaded_files:
            eprint(f"Loaded configuration from {path} (values hidden).")
        fighter_map = parse_fighter_map(args.fighter_map)
        if (
            args.video is not None
            and not args.check
            and not args.dry_run
            and fighter_map is None
        ):
            raise CosmosError(
                "--fighter-map is required for inference so A/B identities remain stable"
            )

        base_url = resolve_api_base(args.api_base)
        token = first_nonempty(
            os.environ.get("GPU_BEARER_TOKEN"),
            os.environ.get("COSMOS_API_KEY"),
        )
        timeout_s = args.timeout
        if timeout_s is None:
            timeout_raw = os.environ.get("COSMOS_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))
            try:
                timeout_s = float(timeout_raw)
            except ValueError as exc:
                raise CosmosError("COSMOS_TIMEOUT_S must be numeric") from exc

        client: CosmosClient | None = None
        model = first_nonempty(
            args.model,
            os.environ.get("COSMOS3_REASON_MODEL"),
            os.environ.get("COSMOS_MODEL"),
        )
        if not args.dry_run:
            if not base_url:
                raise CosmosError(
                    "Missing COSMOS3_REASON_URL. Run inside the workshop VM or set it in .env."
                )
            if not token:
                raise CosmosError(
                    "Missing GPU_BEARER_TOKEN. Use the workshop VM's /config/<team>.config; "
                    "do not commit or print the token."
                )
            client = CosmosClient(
                base_url, token, timeout_s=timeout_s, retries=args.retries
            )
            if not model:
                model = client.discover_model()
            eprint(f"Cosmos model: {model}")

        if args.check:
            if client is None:
                raise CosmosError("--check requires Cosmos endpoint credentials")
            result = client.health_check()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        assert args.video is not None
        video_path = args.video.expanduser().resolve()
        if not video_path.is_file():
            raise CosmosError(f"Video not found: {video_path}")
        duration_s = probe_duration(video_path)
        full_seconds = math.floor(duration_s + 1e-6)
        if args.start_second >= full_seconds:
            raise CosmosError(
                f"--start-second {args.start_second} is beyond {full_seconds} complete seconds"
            )
        window_count = full_seconds - args.start_second
        if args.max_windows is not None:
            window_count = min(window_count, args.max_windows)

        with tempfile.TemporaryDirectory(prefix="fightlens-cosmos-") as temp_name:
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
                f"Sampled {len(frames)} frames across {len(windows)} one-second windows "
                f"from {video_path.name}."
            )
            if args.dry_run:
                preview = {
                    "video": str(video_path),
                    "duration_s": duration_s,
                    "window_count": len(windows),
                    "frames_per_window": args.fps,
                    "first_window_frame_times_s": list(windows[0].frame_times_s),
                    "last_window_frame_times_s": list(windows[-1].frame_times_s),
                }
                print(json.dumps(preview, ensure_ascii=False, indent=2))
                return 0

            assert client is not None and model is not None
            video_sha256 = sha256_file(video_path)
            fighter_map_sha256 = stable_json_sha256(fighter_map)
            sampling_config_sha256 = stable_json_sha256(
                {
                    "fps": args.fps,
                    "max_width": args.max_width,
                    "jpeg_quality": args.jpeg_quality,
                    "max_tokens": args.max_tokens,
                    "media_mode": args.media_mode,
                }
            )
            output_path = (args.output or default_output_path(video_path)).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if args.overwrite:
                output_path.write_text("", encoding="utf-8")
            completed_scenes = load_resume_prefix(
                output_path,
                video_sha256=video_sha256,
                model=model,
                fps=args.fps,
                prompt_version=PROMPT_VERSION,
                fighter_map_sha256=fighter_map_sha256,
                system_prompt_sha256=SYSTEM_PROMPT_SHA256,
                sampling_config_sha256=sampling_config_sha256,
                start_second=args.start_second,
            )
            if completed_scenes:
                eprint(
                    f"Resuming {output_path}; {len(completed_scenes)} contiguous "
                    "successful windows will be skipped."
                )

            run_started = time.monotonic()
            attempted = 0
            failures = 0
            previous_state: dict[str, Any] | None = None
            previous_state_window_index: int | None = None
            with output_path.open("a", encoding="utf-8") as output:
                for window in windows:
                    if window.index in completed_scenes:
                        previous_state = completed_scenes[window.index]
                        previous_state_window_index = window.index
                        continue
                    if args.realtime:
                        target_time = run_started + attempted
                        delay = target_time - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
                    attempted += 1
                    eprint(
                        f"[{window.index}] analyzing {window.start_s:.1f}-{window.end_s:.1f}s "
                        f"({len(window.frame_paths)} frames)"
                    )
                    record: dict[str, Any] = {
                        "schema_version": 3,
                        "status": "error",
                        "video": str(video_path),
                        "video_sha256": video_sha256,
                        "window_index": window.index,
                        "start_s": window.start_s,
                        "end_s": window.end_s,
                        "frame_times_s": list(window.frame_times_s),
                        "sampled_frame_count": len(window.frame_paths),
                        "fps": args.fps,
                        "model": model,
                        "prompt_version": PROMPT_VERSION,
                        "fighter_map": fighter_map,
                        "fighter_map_sha256": fighter_map_sha256,
                        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
                        "sampling_config_sha256": sampling_config_sha256,
                        "previous_state": previous_state,
                        "previous_state_window_index": previous_state_window_index,
                    }
                    try:
                        response, used_mode, latency_s = analyze_window(
                            client,
                            model,
                            window,
                            fighter_map=fighter_map,
                            previous_state=previous_state,
                            max_tokens=args.max_tokens,
                            fps=args.fps,
                            media_mode=args.media_mode,
                            temp_dir=temp_dir,
                        )
                        raw_text = response_text(response)
                        record.update(
                            {
                                "media_mode": used_mode,
                                "latency_s": round(latency_s, 6),
                                "raw_response_text": raw_text,
                                "usage": response.get("usage"),
                                "request_id": response.get("id"),
                            }
                        )
                        scene = parse_scene_state(raw_text, previous_state)
                        record.update({"status": "ok", "scene": scene})
                        previous_state = scene
                        previous_state_window_index = window.index
                    except CosmosInvalidResponseError as exc:
                        failures += 1
                        record["status"] = "invalid_response"
                        record["error"] = str(exc)
                        record["error_type"] = type(exc).__name__
                        previous_state = None
                        previous_state_window_index = None
                    except Exception as exc:  # noqa: BLE001 - keep later windows observable
                        failures += 1
                        record["error"] = redact_text(str(exc), token)
                        record["error_type"] = type(exc).__name__
                        previous_state = None
                        previous_state_window_index = None
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                    output.flush()
                    if record["status"] == "ok":
                        emit_terminal_scene(record["scene"])
                        eprint(f"[{window.index}] ok in {record['latency_s']:.2f}s")
                    else:
                        eprint(f"[{window.index}] failed: {record['error']}")
                        eprint(
                            "Stopping to preserve the previous_state chain; rerun to "
                            "resume from this window."
                        )
                        break

            eprint(
                f"Finished: attempted={attempted}, failed={failures}, output={output_path}"
            )
            return 1 if failures else 0
    except (CosmosError, OSError, ValueError) as exc:
        eprint(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
