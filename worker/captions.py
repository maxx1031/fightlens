"""Bounded, in-memory live windows -> Cosmos exchange notes.

No video or model reply is written to disk. The existing Cosmos prompts/parser
are shared with the offline branch; live transport uses temporal video_frames.
"""

import asyncio
import base64
import io
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cosmos_branch.asks import EXCHANGE_SYSTEM, exchange_prompt, read_exchange
from cosmos_branch.cosmos import CosmosError
from cosmos_branch.windows import Window


class CaptionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never expose endpoint replies, URLs or credentials.


def setting(name, default, low, high):
    try:
        value = float(os.getenv(name, str(default)))
        return min(high, max(low, value)) if math.isfinite(value) else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Sample:
    t: float
    jpeg: bytes


def encode_frame(frame, position):
    """Downsize before retaining a frame; stamp receiver time, never clip time."""
    from livekit import rtc

    rgb = frame if frame.type == rtc.VideoBufferType.RGB24 else frame.convert(rtc.VideoBufferType.RGB24)
    image = Image.frombytes("RGB", (rgb.width, rgb.height), bytes(rgb.data))
    image.thumbnail((640, 480))
    tagged = Image.new("RGB", (image.width, image.height + 24), "black")
    tagged.paste(image)
    ImageDraw.Draw(tagged).text((8, image.height + 5), f"Receiver time: {position:.2f} s", fill="white")
    out = io.BytesIO()
    tagged.save(out, "JPEG", quality=75)
    return out.getvalue()


class LiveCosmos:
    def __init__(self, http):
        self.http = http
        self.url = (os.getenv("COSMOS3_REASON_URL") or os.getenv("COSMOS_API_BASE") or "").strip().rstrip("/")
        if self.url.endswith("/v1"):
            self.url = self.url[:-3]
        self.model = (os.getenv("COSMOS3_REASON_MODEL") or os.getenv("COSMOS_MODEL") or "").strip()
        self.key = os.getenv("GPU_BEARER_TOKEN") or os.getenv("COSMOS_API_KEY") or ""
        self.timeout = setting("COSMOS_TIMEOUT_S", 30, 1, 120)
        # One GPU request across this daemon; frames and control leases keep moving.
        self.limit = asyncio.Semaphore(1)

    async def request(self, method, path, payload=None):
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            async with self.http.request(
                method, self.url + path, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status >= 400:
                    raise CaptionError("endpoint_unavailable")
                data = await response.json()
                if not isinstance(data, dict):
                    raise CaptionError("invalid_response")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise CaptionError("endpoint_unavailable") from None
        except (ValueError, UnicodeError):
            raise CaptionError("invalid_response") from None

    async def review(self, samples, fighters):
        async with self.limit:
            if not self.model:
                models = await self.request("GET", "/v1/models")
                try:
                    self.model = models["data"][0]["id"]
                    if not isinstance(self.model, str) or not self.model or len(self.model) > 200:
                        raise ValueError()
                except (KeyError, IndexError, TypeError, ValueError):
                    raise CaptionError("invalid_response") from None
            window = Window(samples[0].t, samples[-1].t, "exchange", "live:grid", 4)
            clip = SimpleNamespace(t0=window.t0, t1=window.t1, speed=1, cropped=False, tagged=False)
            prompt = exchange_prompt(clip, fighters)
            prompt += (
                "\nThese are ordered live-camera frames, with receiver time printed beneath each frame. "
                "The appearance descriptions fix A/B across the whole window. If attribution is uncertain, "
                "say so in the note and do not guess. The note will appear directly below the live video: "
                "write one short sentence, at most 60 words. Report only visible actions and contact; "
                "do not infer injury, pain, fatigue, strength, win probability or unseen effects. "
                "If there is no visible exchange, describe that plainly."
            )
            result = await self.request("POST", "/v1/chat/completions", {
                "model": self.model, "temperature": 0, "max_tokens": 4096,
                "messages": [
                    {"role": "system", "content": EXCHANGE_SYSTEM},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "video_frames", "video_frames": [
                            "data:image/jpeg;base64," + base64.b64encode(s.jpeg).decode("ascii") for s in samples
                        ]},
                    ]},
                ],
            })
            try:
                text = result["choices"][0]["message"]["content"]
                if not isinstance(text, str):
                    raise ValueError()
                note = read_exchange(text, window)["note"]
                if not note or len(note) > 800:
                    raise ValueError()
                return note, self.model
            except (KeyError, IndexError, TypeError, ValueError, CosmosError):
                raise CaptionError("invalid_response") from None


class CaptionPipeline:
    def __init__(self, client, session, is_active=lambda: True):
        self.client = client
        self.is_active = is_active
        self.window_s = setting("FIGHTLENS_CAPTION_WINDOW_S", 3, 1, 6)
        self.fps = setting("FIGHTLENS_CAPTION_FPS", 4, 1, 6)
        self.queue = asyncio.Queue(maxsize=1)
        self.active_request = None
        self.closed = False
        self.key = None
        self.configure(session)

    def configure(self, session):
        key = (session["id"], session["sourceGeneration"], session["workerGeneration"],
               session["segmentId"], session["analysisRevision"], session["captionRevision"])
        if self.key == key:
            return
        self.key = key
        self.session = dict(session)
        self.samples = []
        self.bucket = None
        self.next_sample = 0
        self.seq = 0
        self.skipped = 0
        self.caption = None
        self.error = None
        if self.active_request:
            self.active_request.cancel()
        while not self.queue.empty():
            self.queue.get_nowait()
        self.status = "paused" if session["paused"] else (
            "not_configured" if not self.client.url else
            "awaiting_identity" if not session.get("captionFighters") else "buffering")

    def wants_frame(self, position):
        return (not self.closed and self.status not in ("paused", "not_configured", "awaiting_identity")
                and position >= self.next_sample)

    def offer(self, jpeg, position):
        if not self.wants_frame(position):
            return
        self.next_sample = position + 1 / self.fps
        bucket = int(position / self.window_s)
        if self.bucket is not None and bucket != self.bucket:
            if len(self.samples) >= 2:
                if self.queue.full():
                    self.queue.get_nowait()  # Prefer recent footage; record the skipped window.
                    self.skipped += 1
                self.queue.put_nowait((self.key, tuple(self.samples)))
            else:
                self.skipped += 1
            self.samples = []
        self.bucket = bucket
        # At most 36 bounded JPEGs in the buffer, one waiting window, one active.
        if len(self.samples) < 36:
            self.samples.append(Sample(round(position, 3), jpeg))

    async def run(self):
        while True:
            key, samples = await self.queue.get()
            if key != self.key or not self.is_active():
                continue
            self.status, self.error = "reviewing", None
            started = time.monotonic()
            self.active_request = asyncio.create_task(self.client.review(samples, self.session["captionFighters"]))
            try:
                note, model = await self.active_request
            except asyncio.CancelledError:
                if self.closed:
                    raise
                continue
            except CaptionError as error:
                if key == self.key:
                    self.status, self.error = "error", error.code
                continue
            finally:
                self.active_request = None
            if key != self.key or self.closed:
                continue
            self.caption = {
                "id": f"{key[3]}:{key[4]}:{key[5]}:{samples[0].t:.3f}",
                "t0_s": samples[0].t, "t1_s": samples[-1].t,
                "text": note, "model": model, "frames": len(samples),
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "ready_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            self.status, self.error = "ready", None

    def packet(self):
        self.seq += 1
        session, source, worker, segment, revision, caption_revision = self.key
        return {
            "schema_version": "fightlens.caption.v1", "session_id": session,
            "source_generation": source, "worker_generation": worker, "segment_id": segment,
            "analysis_revision": revision, "caption_revision": caption_revision, "seq": self.seq, "status": self.status,
            "skipped_windows": self.skipped, "caption": self.caption, "error_code": self.error,
        }

    def close(self):
        self.closed = True
        if self.active_request:
            self.active_request.cancel()
        self.samples.clear()
        while not self.queue.empty():
            self.queue.get_nowait()
