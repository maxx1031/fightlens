"""Live camera -> serialized YOLO -> annotated WebRTC video. No recording."""

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

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")
from captions import CaptionPipeline, LiveCosmos, encode_frame
from yolo_processor import YoloProcessor
from judgments import JudgmentPipeline, LiveDecisions

logging.basicConfig(level=logging.WARNING)
logging.getLogger("livekit").setLevel(logging.CRITICAL)
INSTANCE = str(uuid.uuid4())
BASE = os.getenv("FIGHTLENS_CONTROL_URL", "http://127.0.0.1:4173").rstrip("/")
KEY = os.getenv("FIGHTLENS_WORKER_SECRET", "")
MAX_FPS = max(1, min(30, float(os.getenv("FIGHTLENS_YOLO_FPS", "15"))))


class Receiver:
    def __init__(self, session, http, processor, cosmos, decisions=None):
        self.session, self.http, self.processor = session, http, processor
        self.room = rtc.Room()
        self.lease = time.monotonic()
        self.closed = False
        self.frames = asyncio.Queue(maxsize=1)
        self.results = asyncio.Queue(maxsize=1)
        self.stream = self.source = self.publication = None
        self.reader = self.consumer = self.reporter = self.subscriber = self.sender = (
            None
        )
        self.track_id = None
        self.seq = self.pose_seq = self.output_count = 0
        self.output_fps = 0
        self.output_fps_started = time.monotonic()
        self.output_fps_count = 0
        self.output_size = None
        self.last_result_key = None
        self.captions = CaptionPipeline(cosmos, session, self.valid)
        self.caption_frames = asyncio.Queue(maxsize=1)
        self.caption_sampler = self.caption_runner = self.caption_reporter = None
        self.reset_metrics()
        self.judgments = JudgmentPipeline(decisions or LiveDecisions(None), session, self.valid,
            lambda: (time.monotonic() - self.started) * 1000 if self.started is not None else 0)
        self.judgment_frames = asyncio.Queue(maxsize=1)
        self.judgment_sampler = self.judgment_runner = self.judgment_reporter = None

    def reset_metrics(self):
        self.started = self.last_frame = self.last_timestamp = None
        self.count = self.drops = self.processed_count = 0
        self.width = self.height = 0
        self.processed = self.processing_ms = self.inference_ms = (
            self.worker_latency_ms
        ) = 0
        self.fps_started = time.monotonic()
        self.fps_count = self.fps = 0
        self.inference_error = None
        self.last_result_key = None

    def valid(self):
        return not self.closed and time.monotonic() - self.lease < 5

    def key(self):
        return (
            self.session["id"],
            self.session["segmentId"],
            self.session["analysisRevision"],
        )

    def drain(self):
        for queue in (self.frames, self.results, self.caption_frames, self.judgment_frames):
            while not queue.empty():
                queue.get_nowait()

    def control(self, session):
        if session.get("revision", 0) < self.session.get("revision", 0):
            return
        if session["segmentId"] != self.session["segmentId"]:
            self.reset_metrics()
            self.seq = self.pose_seq = 0
            self.drain()
        elif session["analysisRevision"] != self.session["analysisRevision"]:
            self.pose_seq = 0
            self.drain()
            self.inference_error = None
            self.last_result_key = None
        self.session.update(session)
        self.lease = time.monotonic()
        previous_judgment_key = self.judgments.key
        self.judgments.configure(self.session)
        if self.judgments.key != previous_judgment_key:
            while not self.judgment_frames.empty():
                self.judgment_frames.get_nowait()
        previous_caption_key = self.captions.key
        self.captions.configure(self.session)
        if self.captions.key != previous_caption_key:
            while not self.caption_frames.empty():
                self.caption_frames.get_nowait()

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
            state = await response.json()
        self.control(state)
        return True

    async def start(self):
        @self.room.on("track_subscribed")
        def subscribed(track, publication, participant):
            if (
                participant.identity != self.session["publisherIdentity"]
                or track.kind != rtc.TrackKind.KIND_VIDEO
                or publication.source != rtc.TrackSource.SOURCE_CAMERA
            ):
                return
            if self.subscriber and not self.subscriber.done():
                self.subscriber.cancel()
            self.subscriber = asyncio.create_task(self.attach(track, publication.sid))

        def admit(publication, participant):
            if (
                participant.identity == self.session["publisherIdentity"]
                and publication.source == rtc.TrackSource.SOURCE_CAMERA
            ):
                publication.set_subscribed(True)
                if publication.simulcasted:
                    publication.set_video_quality(rtc.VideoQuality.VIDEO_QUALITY_HIGH)

        self.room.on("track_published", admit)
        await self.room.connect(
            self.session["url"],
            self.session["token"],
            options=rtc.RoomOptions(auto_subscribe=False),
        )
        for participant in self.room.remote_participants.values():
            for publication in participant.track_publications.values():
                admit(publication, participant)
        self.consumer = asyncio.create_task(self.consume())
        self.reporter = asyncio.create_task(self.report())
        self.sender = asyncio.create_task(self.send_results())
        self.caption_sampler = asyncio.create_task(self.sample_captions())
        self.caption_runner = asyncio.create_task(self.captions.run())
        self.caption_reporter = asyncio.create_task(self.report_captions())
        self.judgment_sampler = asyncio.create_task(self.sample_judgments())
        self.judgment_runner = asyncio.create_task(self.judgments.run())
        self.judgment_reporter = asyncio.create_task(self.report_judgments())

    async def attach(self, track, track_id):
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        if self.stream:
            await self.stream.aclose()
        if not await self.new_segment(track_id):
            return
        self.track_id = track_id
        self.stream = rtc.VideoStream.from_track(track=track, capacity=1)
        self.reader = asyncio.create_task(self.receive())

    async def ensure_output(self, frame):
        if self.source and self.output_size == (frame.width, frame.height):
            return
        if self.publication:
            await self.room.local_participant.unpublish_track(self.publication.sid)
        if self.source:
            await self.source.aclose()
        self.source = rtc.VideoSource(frame.width, frame.height)
        self.output_size = (frame.width, frame.height)
        track = rtc.LocalVideoTrack.create_video_track("yolo-annotated", self.source)
        options = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA,
            frame_metadata_features=[rtc.FrameMetadataFeature.FMF_FRAME_ID],
        )
        options.simulcast = False
        self.publication = await self.room.local_participant.publish_track(
            track, options
        )
        async with self.http.post(
            f"{BASE}/api/internal/sessions/{self.session['id']}/output",
            json={
                "workerGeneration": self.session["workerGeneration"],
                "segmentId": self.session["segmentId"],
                "trackId": self.publication.sid,
            },
        ) as response:
            if response.status != 200:
                raise RuntimeError("Output registration rejected")

    def emit(self, frame):
        if not self.valid() or not self.source:
            return None
        self.output_count += 1
        now = time.monotonic()
        self.source.capture_frame(
            frame,
            timestamp_us=int(now * 1_000_000),
            metadata=rtc.FrameMetadata(frame_id=self.output_count),
        )
        self.output_fps_count += 1
        if now - self.output_fps_started >= 1:
            self.output_fps = self.output_fps_count / (now - self.output_fps_started)
            self.output_fps_count = 0
            self.output_fps_started = now
        return self.output_count

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
            position_s = (now - self.started)
            if self.valid() and self.captions.wants_frame(position_s):
                if self.caption_frames.full():
                    self.caption_frames.get_nowait()
                self.caption_frames.put_nowait((event.frame, position_s, self.captions.key))
            await self.ensure_output(event.frame)
            if (
                self.session["paused"]
                or self.processor.state != "ready"
                or self.inference_error
            ):
                self.emit(event.frame)
                continue
            if self.last_result_key != self.key():
                self.emit(event.frame)
            if self.frames.full():
                self.frames.get_nowait()
                self.drops += 1
            self.frames.put_nowait(
                (event.frame, (now - self.started) * 1000, self.key(), now, self.count)
            )

    async def sample_captions(self):
        while True:
            frame, position, key = await self.caption_frames.get()
            if not self.valid() or key != self.captions.key or not self.captions.wants_frame(position):
                continue
            try:
                jpeg = await asyncio.to_thread(encode_frame, frame, position)
                if key == self.captions.key and self.valid():
                    self.captions.offer(jpeg, position)
            except Exception:
                if key == self.captions.key:
                    self.captions.status, self.captions.error = "error", "frame_unavailable"

    async def report_captions(self):
        while True:
            await asyncio.sleep(0.5)
            if not self.valid():
                continue
            packet = self.captions.packet()
            try:
                async with self.http.post(
                    f"{BASE}/api/internal/sessions/{self.session['id']}/captions",
                    json=packet,
                ) as response:
                    await response.read()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass

    async def sample_judgments(self):
        while True:
            frame, position, key, engaged, identity = await self.judgment_frames.get()
            if not self.valid() or key != self.judgments.key or not self.judgments.wants_frame(position):
                continue
            try:
                jpeg = await asyncio.to_thread(encode_frame, frame, position)
                if self.valid() and key == self.judgments.key:
                    self.judgments.offer(jpeg, position, engaged, identity)
            except Exception:
                if self.valid() and key == self.judgments.key:
                    self.judgments.status, self.judgments.error = "error", "frame_unavailable"
                    self.judgments.invalidate("coverage_gap", position)

    async def report_judgments(self):
        while True:
            await asyncio.sleep(0.5)
            if not self.valid():
                continue
            packet = self.judgments.packet()
            try:
                async with self.http.post(
                    f"{BASE}/api/internal/sessions/{self.session['id']}/judgments", json=packet,
                ) as response:
                    if response.status == 200:
                        await response.read()
                        self.judgments.acknowledge(packet["judgment"])
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass

    async def consume(self):
        previous_start = 0
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(
                max(0, 1 / MAX_FPS - (time.monotonic() - previous_start))
            )
            frame, position, key, received_at, input_seq = await self.frames.get()
            if not self.valid() or key != self.key() or self.session["paused"]:
                continue
            previous_start = time.monotonic()
            try:
                output, result = await loop.run_in_executor(
                    self.processor.executor,
                    self.processor.process,
                    frame,
                    position,
                    key,
                )
            except Exception as error:
                self.inference_error = f"YOLO inference failed ({type(error).__name__}). Pause/resume to retry."
                continue
            if not self.valid() or key != self.key() or self.session["paused"]:
                continue
            if self.judgments.wants_frame(position / 1000):
                if self.judgment_frames.full():
                    self.judgment_frames.get_nowait()
                self.judgment_frames.put_nowait((frame, position / 1000, self.judgments.key,
                    result["signals"]["engaged"], result["identity_status"]))
            self.last_result_key = key
            self.inference_ms = result["inference_ms"]
            self.processing_ms = (time.monotonic() - previous_start) * 1000
            self.worker_latency_ms = (time.monotonic() - received_at) * 1000
            self.processed, self.processed_count = position, self.processed_count + 1
            frame_id = self.emit(output)
            if frame_id is None:
                continue
            self.pose_seq += 1
            packet = {
                "schema_version": "fightlens.live.v1",
                "session_id": self.session["id"],
                "source_generation": self.session["sourceGeneration"],
                "segment_id": self.session["segmentId"],
                "track_id": self.track_id,
                "worker_generation": self.session["workerGeneration"],
                "seq": self.pose_seq,
                "kind": "pose_frame",
                "provenance": "live_camera",
                "analysis_revision": self.session["analysisRevision"],
                "output_track_id": self.publication.sid,
                "output_frame_id": frame_id,
                "receiver_frame_seq": input_seq,
                "received_position_ms": position,
                "worker_latency_ms": self.worker_latency_ms,
                **result,
            }
            if self.results.full():
                self.results.get_nowait()
            self.results.put_nowait(packet)

    async def send_results(self):
        while True:
            packet = await self.results.get()
            if (
                not self.valid()
                or packet["segment_id"] != self.session["segmentId"]
                or packet["analysis_revision"] != self.session["analysisRevision"]
                or self.session["paused"]
            ):
                continue
            try:
                async with self.http.post(
                    f"{BASE}/api/internal/sessions/{self.session['id']}/pose",
                    json=packet,
                ) as response:
                    result = await response.json()
                    if response.status != 200 or not result.get("accepted"):
                        continue
                if (
                    self.valid()
                    and packet["analysis_revision"] == self.session["analysisRevision"]
                ):
                    await self.room.local_participant.publish_data(
                        json.dumps(packet).encode(),
                        reliable=True,
                        topic="fightlens.pose",
                    )
            except Exception:
                pass

    def mode(self):
        if self.session["paused"]:
            return "paused"
        if self.processor.state == "failed" or self.inference_error:
            return "failed"
        return (
            "yolo_pose"
            if self.processor.state == "ready" and self.last_result_key == self.key()
            else "initializing"
        )

    async def report(self):
        while True:
            await asyncio.sleep(0.5)
            if not self.valid() or self.started is None or not self.track_id:
                continue
            self.seq += 1
            now = time.monotonic()
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
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
                "analysis_revision": self.session["analysisRevision"],
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
                    "output_frame_id": self.output_count or None,
                },
                "analysis": {
                    "mode": self.mode(),
                    "momentum": None,
                    "model_version": self.processor.model_version,
                    "processed_frames": self.processed_count,
                    "output_frames": self.output_count,
                    "output_fps": round(self.output_fps, 1),
                    "inference_ms": self.inference_ms,
                    "worker_latency_ms": self.worker_latency_ms,
                    "error": self.inference_error or self.processor.error,
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
                    "memory_mb": round(
                        rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1
                    ),
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
        self.closed = True
        self.captions.close()
        self.judgments.close()
        tasks = (
            self.subscriber,
            self.reader,
            self.consumer,
            self.reporter,
            self.sender,
            self.caption_sampler,
            self.caption_runner,
            self.caption_reporter,
            self.judgment_sampler,
            self.judgment_runner,
            self.judgment_reporter,
        )
        for task in tasks:
            if task:
                task.cancel()
        for task in tasks:
            if task:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self.stream:
            await self.stream.aclose()
        await self.room.disconnect()
        if self.source:
            await self.source.aclose()
        self.drain()


async def main():
    if not KEY:
        raise SystemExit("Receiver configuration missing. Run pnpm live:setup.")
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    processor = YoloProcessor()
    loading = loop.run_in_executor(processor.executor, processor.load)
    jobs = {}
    headers = {"Authorization": f"Bearer {KEY}", "X-Worker-Instance": INSTANCE}
    print("FightLens YOLO receiver running", flush=True)
    async with aiohttp.ClientSession(
        headers=headers, timeout=aiohttp.ClientTimeout(total=3)
    ) as http, aiohttp.ClientSession() as cosmos_http:
        cosmos = LiveCosmos(cosmos_http)
        decisions = LiveDecisions(cosmos_http)
        try:
            while not stopped.is_set():
                try:
                    async with http.get(f"{BASE}/api/internal/sessions") as response:
                        if response.status != 200:
                            raise RuntimeError("Control unavailable")
                        current = {
                            s["id"]: s for s in (await response.json())["sessions"]
                        }
                    for session_id in list(jobs):
                        job, session = jobs[session_id], current.get(session_id)
                        if (
                            not session
                            or session["workerGeneration"]
                            != job.session["workerGeneration"]
                        ):
                            await jobs.pop(session_id).close()
                        else:
                            job.control(session)
                    for session_id, session in current.items():
                        if session_id not in jobs:
                            job = Receiver(session, http, processor, cosmos, decisions)
                            try:
                                await job.start()
                                jobs[session_id] = job
                                print(
                                    f"YOLO receiver connected: {session_id}", flush=True
                                )
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
                    await asyncio.wait_for(stopped.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
        finally:
            for job in jobs.values():
                await job.close()
            await loading
            processor.close()


if __name__ == "__main__":
    asyncio.run(main())
