"""Video-only diagnostic receiver. No model, recording, or pixel logging."""

import asyncio
import contextlib
import json
import logging
import os
import resource
import signal
import sys
import time
import uuid
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from livekit import rtc

load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")
logging.basicConfig(level=logging.WARNING)
# RTC connection exceptions can include URLs; print only application status codes.
logging.getLogger("livekit").setLevel(logging.CRITICAL)
INSTANCE = str(uuid.uuid4())
BASE = os.getenv("FIGHTLENS_CONTROL_URL", "http://127.0.0.1:4173").rstrip("/")
KEY = os.getenv("FIGHTLENS_WORKER_SECRET", "")


class Receiver:
    def __init__(self, session, http):
        self.session = session
        self.http = http
        self.room = rtc.Room()
        self.lease = time.monotonic()
        # One SDK waiting frame + one application waiting frame; no history.
        self.frames = asyncio.Queue(maxsize=1)
        self.stream = None
        self.reader = None
        self.consumer = None
        self.reporter = None
        self.subscriber = None
        self.track_id = None
        self.seq = 0
        self.reset_metrics()

    def reset_metrics(self):
        self.started = None
        self.last_frame = None
        self.count = 0
        self.drops = 0
        self.width = self.height = 0
        self.processed = 0
        self.processing_ms = 0
        self.fps_started = time.monotonic()
        self.fps_count = 0
        self.fps = 0
        self.last_timestamp = None

    async def new_segment(self, track_id):
        async with self.http.post(
            f"{BASE}/api/internal/sessions/{self.session['id']}/segment",
            json={
                "workerGeneration": self.session["workerGeneration"],
                "trackId": track_id,
            },
        ) as response:
            if response.status != 200:
                return False
            self.session.update(await response.json())
        self.seq = 0
        self.reset_metrics()
        while not self.frames.empty():
            self.frames.get_nowait()
        return True

    def valid(self):
        return time.monotonic() - self.lease < 5

    async def start(self):
        @self.room.on("track_subscribed")
        def subscribed(track, publication, participant):
            if (
                participant.identity != self.session["publisherIdentity"]
                or track.kind != rtc.TrackKind.KIND_VIDEO
            ):
                return
            if publication.source != rtc.TrackSource.SOURCE_CAMERA:
                return
            if self.subscriber and not self.subscriber.done():
                self.subscriber.cancel()
            self.subscriber = asyncio.create_task(self.attach(track, publication.sid))

        await self.room.connect(
            self.session["url"],
            self.session["token"],
            options=rtc.RoomOptions(auto_subscribe=False),
        )

        # Explicitly subscribe only to the admitted camera source.
        def admit(publication, participant):
            if (
                participant.identity == self.session["publisherIdentity"]
                and publication.source == rtc.TrackSource.SOURCE_CAMERA
            ):
                publication.set_subscribed(True)
                if publication.simulcasted:
                    publication.set_video_quality(rtc.VideoQuality.VIDEO_QUALITY_HIGH)

        self.room.on("track_published", admit)
        for participant in self.room.remote_participants.values():
            for publication in participant.track_publications.values():
                admit(publication, participant)
        self.consumer = asyncio.create_task(self.consume())
        self.reporter = asyncio.create_task(self.report())

    async def attach(self, track, track_id):
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        if self.stream:
            await self.stream.aclose()
        # Allocate a new segment for every actual publication, including reconnect.
        if not await self.new_segment(track_id):
            return
        self.track_id = track_id
        self.stream = rtc.VideoStream.from_track(track=track, capacity=1)
        self.reader = asyncio.create_task(self.receive())

    async def receive(self):
        async for event in self.stream:
            if not self.valid():
                continue
            now = time.monotonic()
            if self.last_timestamp is not None and (
                event.timestamp_us < self.last_timestamp
                or event.timestamp_us - self.last_timestamp > 2_000_000
                or (self.last_frame and now - self.last_frame > 2)
            ):
                try:
                    if not await self.new_segment(self.track_id):
                        continue
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    continue
                now = time.monotonic()
            self.last_timestamp = event.timestamp_us
            if self.started is None:
                self.started = now
            self.last_frame = now
            self.count += 1
            self.fps_count += 1
            self.width, self.height = event.frame.width, event.frame.height
            if now - self.fps_started >= 1:
                self.fps = self.fps_count / (now - self.fps_started)
                self.fps_count = 0
                self.fps_started = now
            if self.frames.full():
                self.frames.get_nowait()
                self.drops += 1
            self.frames.put_nowait(
                (event.frame, (now - self.started) * 1000, self.session["segmentId"])
            )

    async def consume(self):
        while True:
            frame, position, segment = await self.frames.get()
            if (
                not self.valid()
                or segment != self.session["segmentId"]
                or self.session["paused"]
            ):
                del frame
                continue
            start = time.monotonic()
            # Diagnostic adapter: inspect dimensions only. Pixels are never saved.
            _ = (frame.width, frame.height)
            self.processed = position
            self.processing_ms = (time.monotonic() - start) * 1000
            del frame

    async def report(self):
        while True:
            await asyncio.sleep(1)
            if not self.valid() or self.started is None or not self.track_id:
                continue
            self.seq += 1
            now = time.monotonic()
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            memory_mb = rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
            packet = {
                "schema_version": "fightlens.live.v1",
                "session_id": self.session["id"],
                "source_generation": self.session["sourceGeneration"],
                "segment_id": self.session["segmentId"],
                "track_id": self.track_id,
                "worker_generation": self.session["workerGeneration"],
                "seq": self.seq,
                "kind": "receiver_status",
                "provenance": "live_camera",
                "timing": {
                    "basis": "receiver_monotonic",
                    "received_position_ms": (self.last_frame - self.started) * 1000,
                    "processed_position_ms": self.processed,
                    "capture_wall_time_us": None,
                    "clock_mapping_id": None,
                },
                "frame_ref": {
                    "publisher_frame_id": None,
                    "receiver_frame_seq": self.count,
                },
                "analysis": {
                    "mode": "paused" if self.session["paused"] else "diagnostic_only",
                    "momentum": None,
                    "model_version": None,
                },
                "metrics": {
                    "received_fps": round(self.fps, 1)
                    if now - self.last_frame < 2
                    else 0,
                    "width": self.width,
                    "height": self.height,
                    "queue_depth": self.frames.qsize(),
                    "dropped_frames": self.drops,
                    "frame_count": self.count,
                    "processing_ms": self.processing_ms,
                    "last_frame_age_ms": (now - self.last_frame) * 1000,
                    "memory_mb": round(memory_mb, 1),
                    "codec": None,
                },
            }
            try:
                async with self.http.post(
                    f"{BASE}/api/internal/sessions/{self.session['id']}/updates",
                    json=packet,
                ) as response:
                    result = await response.json()
                    if response.status != 200 or not result.get("accepted"):
                        continue
                if self.valid():
                    await self.room.local_participant.publish_data(
                        json.dumps(packet).encode(),
                        reliable=True,
                        topic="fightlens.receiver",
                    )
            except Exception:
                pass

    async def close(self):
        for task in (self.subscriber, self.reader, self.consumer, self.reporter):
            if task:
                task.cancel()
        for task in (self.subscriber, self.reader, self.consumer, self.reporter):
            if task:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self.stream:
            await self.stream.aclose()
        await self.room.disconnect()
        while not self.frames.empty():
            self.frames.get_nowait()


async def main():
    if not KEY:
        raise SystemExit("Receiver configuration missing. Run pnpm live:setup.")
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    jobs = {}
    headers = {"Authorization": f"Bearer {KEY}", "X-Worker-Instance": INSTANCE}
    timeout = aiohttp.ClientTimeout(total=3)
    print("FightLens diagnostic receiver running", flush=True)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as http:
        try:
            while not stopped.is_set():
                try:
                    async with http.get(f"{BASE}/api/internal/sessions") as response:
                        if response.status != 200:
                            raise RuntimeError(f"Control status {response.status}")
                        result = await response.json()
                    current = {s["id"]: s for s in result["sessions"]}
                    for session_id in list(jobs):
                        job = jobs[session_id]
                        session = current.get(session_id)
                        if (
                            not session
                            or session["workerGeneration"]
                            != job.session["workerGeneration"]
                        ):
                            await job.close()
                            del jobs[session_id]
                        else:
                            if session["segmentId"] != job.session["segmentId"]:
                                job.seq = 0
                                job.reset_metrics()
                            job.session.update(session)
                            job.lease = time.monotonic()
                    for session_id, session in current.items():
                        if session_id not in jobs:
                            job = Receiver(session, http)
                            try:
                                await job.start()
                                jobs[session_id] = job
                                print(f"Receiver connected: {session_id}", flush=True)
                            except Exception as error:
                                await job.close()
                                print(
                                    f"Receiver connection failed ({type(error).__name__}); retrying",
                                    flush=True,
                                )
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
                    for session_id in list(jobs):
                        if not jobs[session_id].valid():
                            await jobs.pop(session_id).close()
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
        finally:
            for job in jobs.values():
                await job.close()


if __name__ == "__main__":
    asyncio.run(main())
