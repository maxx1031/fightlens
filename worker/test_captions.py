import asyncio
import contextlib
import io
import uuid

import aiohttp
from aiohttp import web
from PIL import Image

from captions import CaptionError, CaptionPipeline, LiveCosmos, Sample, encode_frame
from cosmos_branch.fake_cosmos import serve


def session(**changes):
    return {"id": str(uuid.uuid4()), "sourceGeneration": 1, "workerGeneration": 1,
            "segmentId": str(uuid.uuid4()), "analysisRevision": 0, "paused": False,
            "captionFighters": {"A": "red trunks", "B": "blue trunks"}, **changes}


class HeldClient:
    url = "http://fake"

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.seen = []

    async def review(self, samples, fighters):
        self.seen.append(samples)
        self.started.set()
        await self.release.wait()
        return "A steps forward; contact is unclear.", "fake/cosmos"


def fill(pipeline, start, end):
    for step in range(int(start * 4), int(end * 4) + 1):
        pipeline.offer(b"bounded-jpeg", step / 4)


async def stop(pipeline, task):
    pipeline.close()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def test_slow_model_keeps_only_one_waiting_window_and_marks_skips():
    async def check():
        client = HeldClient()
        pipeline = CaptionPipeline(client, session())
        task = asyncio.create_task(pipeline.run())
        try:
            fill(pipeline, 0, 3)
            await asyncio.wait_for(client.started.wait(), 1)
            fill(pipeline, 3.25, 15)
            assert pipeline.queue.qsize() == 1
            assert pipeline.skipped == 3
            assert len(pipeline.samples) <= 36
            _, waiting = pipeline.queue.get_nowait()
            assert waiting[0].t == 12
            assert client.seen[0][-1].t == 2.75
            client.release.set()
            await asyncio.sleep(0.01)
            assert pipeline.packet()["caption"]["t1_s"] == 2.75
        finally:
            await stop(pipeline, task)
    asyncio.run(check())


def test_pause_cancels_old_reply_and_resume_requires_new_frames():
    async def check():
        client = HeldClient()
        state = session()
        pipeline = CaptionPipeline(client, state)
        task = asyncio.create_task(pipeline.run())
        try:
            fill(pipeline, 0, 3)
            await asyncio.wait_for(client.started.wait(), 1)
            pipeline.configure({**state, "paused": True, "analysisRevision": 1})
            client.release.set()
            await asyncio.sleep(0.01)
            assert pipeline.packet()["status"] == "paused"
            assert pipeline.caption is None and not pipeline.samples and pipeline.queue.empty()
            pipeline.configure({**state, "analysisRevision": 2})
            assert pipeline.status == "buffering" and pipeline.caption is None
            fill(pipeline, 6, 9)
            await asyncio.sleep(0.01)
            assert pipeline.caption["t0_s"] == 6
        finally:
            await stop(pipeline, task)
    asyncio.run(check())


def test_source_change_cannot_publish_a_reply_from_the_old_segment():
    async def check():
        client = HeldClient()
        state = session()
        pipeline = CaptionPipeline(client, state)
        task = asyncio.create_task(pipeline.run())
        try:
            fill(pipeline, 0, 3)
            await asyncio.wait_for(client.started.wait(), 1)
            new = {**state, "segmentId": str(uuid.uuid4())}
            pipeline.configure(new)
            client.release.set()
            await asyncio.sleep(0.01)
            packet = pipeline.packet()
            assert packet["segment_id"] == new["segmentId"]
            assert packet["caption"] is None and packet["status"] == "buffering"
        finally:
            await stop(pipeline, task)
    asyncio.run(check())


def test_unconfigured_or_unidentified_sessions_do_not_sample():
    client = HeldClient()
    client.url = ""
    pipeline = CaptionPipeline(client, session())
    assert pipeline.status == "not_configured" and not pipeline.wants_frame(1)
    client.url = "http://fake"
    pipeline = CaptionPipeline(client, session(captionFighters=None))
    assert pipeline.status == "awaiting_identity" and not pipeline.wants_frame(1)


def test_expired_control_lease_does_not_start_a_queued_review():
    async def check():
        client = HeldClient()
        pipeline = CaptionPipeline(client, session(), is_active=lambda: False)
        fill(pipeline, 0, 3)
        task = asyncio.create_task(pipeline.run())
        try:
            await asyncio.sleep(0.01)
            assert not client.seen and pipeline.queue.empty()
        finally:
            await stop(pipeline, task)
    asyncio.run(check())


def test_temporal_frames_reach_the_repository_fake_endpoint(monkeypatch):
    server = serve(port=0, think=True)
    monkeypatch.setenv("COSMOS3_REASON_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("COSMOS3_REASON_MODEL", "")
    monkeypatch.setenv("GPU_BEARER_TOKEN", "")
    monkeypatch.setenv("COSMOS_API_KEY", "")
    async def check():
        async with aiohttp.ClientSession() as http:
            note, model = await LiveCosmos(http).review([Sample(0, b"jpeg"), Sample(1, b"jpeg")], session()["captionFighters"])
            assert "(fake)" in note and model.startswith("fake/")
            assert server.asked == [("exchange", True)]
    try:
        asyncio.run(check())
    finally:
        server.shutdown()


def test_bad_provider_reply_is_safe_and_the_next_window_can_recover(monkeypatch):
    async def check():
        seen = []
        async def reply(request):
            seen.append(await request.json())
            if len(seen) == 1:
                return web.Response(status=503, text="Bearer do-not-leak-this")
            return web.json_response({"choices": [{"message": {"content": '{"strikes":[],"note":"No visible exchange."}'}}]})
        app = web.Application()
        app.router.add_post("/v1/chat/completions", reply)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        monkeypatch.setenv("COSMOS3_REASON_URL", f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}")
        monkeypatch.setenv("COSMOS3_REASON_MODEL", "test/model")
        monkeypatch.setenv("GPU_BEARER_TOKEN", "local-test-key")
        try:
            async with aiohttp.ClientSession() as http:
                client = LiveCosmos(http)
                try:
                    await client.review([Sample(0, b"jpeg"), Sample(1, b"jpeg")], session()["captionFighters"])
                    assert False
                except CaptionError as error:
                    assert str(error) == "endpoint_unavailable"
                note, _ = await client.review([Sample(3, b"jpeg"), Sample(4, b"jpeg")], session()["captionFighters"])
                assert note == "No visible exchange."
                assert seen[-1]["messages"][1]["content"][1]["type"] == "video_frames"
        finally:
            await runner.cleanup()
    asyncio.run(check())


def test_frame_buffer_downsizes_and_encodes_real_rtc_pixels():
    from livekit import rtc
    frame = rtc.VideoFrame(1280, 720, rtc.VideoBufferType.RGB24, bytes([40, 70, 90]) * (1280 * 720))
    encoded = encode_frame(frame, 12.5)
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (640, 384)
    assert len(encoded) < 100_000
