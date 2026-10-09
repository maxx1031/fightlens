import asyncio
import contextlib
import uuid

import aiohttp
import pytest
from aiohttp import web
from captions import CaptionError, Sample
from judgments import JudgmentPipeline, LiveDecisions, parse_answers


def state(**changes):
    return {
        "id": str(uuid.uuid4()),
        "sourceGeneration": 1,
        "workerGeneration": 1,
        "segmentId": str(uuid.uuid4()),
        "analysisRevision": 0,
        "captionRevision": 0,
        "paused": False,
        "captionFighters": {"A": "red trunks", "B": "blue trunks"},
        **changes,
    }


def reply(direction="favors_A", evidence="contact_only"):
    return {
        "answers": {
            "direction": {
                "type": "choice",
                "choice": direction,
                "confidence": 0.8,
                "probabilities": {
                    key: float(key == direction)
                    for key in (
                        "favors_A",
                        "favors_B",
                        "no_clear_advantage",
                        "insufficient_evidence",
                    )
                },
            },
            "evidence": {
                "type": "choice",
                "choice": evidence,
                "confidence": 0.8,
                "probabilities": {
                    key: float(key == evidence)
                    for key in (
                        "contact_only",
                        "observable_reaction",
                        "sustained_change",
                        "no_confirmed_effect",
                        "insufficient_evidence",
                    )
                },
            },
        }
    }


class Client:
    url = ""
    enabled = True
    model = "fake/clef"

    def __init__(self):
        self.seen = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def review(self, samples, fighters):
        self.seen.append((samples, fighters))
        self.started.set()
        await self.release.wait()
        return parse_answers(reply())


def offer_exchange(pipeline, start=0):
    for k in range(13):
        pipeline.offer(b"jpeg", start + k / 4, int(4 <= k <= 8), "stable")


async def stop(pipeline, task):
    pipeline.close()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def test_window_includes_pre_and_post_frames_and_only_complete_exchanges():
    pipeline = JudgmentPipeline(Client(), state())
    for k in range(12):
        pipeline.offer(b"jpeg", k / 4, int(4 <= k <= 8), "stable")
        if k < 11:
            assert pipeline.queue.empty()
    _, _, samples = pipeline.queue.get_nowait()
    assert samples[0].t == 0 and samples[-1].t == 2.75
    assert len(samples) == 12
    assert len(pipeline.pre) <= 5
    assert pipeline.outbox[0]["gap_reason"] == "reviewing"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["answers"]["direction"]["probabilities"].update(favors_A=0.2),
        lambda data: data["answers"]["direction"].update(confidence=float("nan")),
        lambda data: data["answers"]["direction"]["probabilities"].update(
            favors_A=True
        ),
        lambda data: data["answers"]["direction"].update(choice="favors_B"),
        lambda data: data["answers"].pop("evidence"),
    ],
)
def test_malformed_distributions_are_rejected(mutation):
    data = reply()
    mutation(data)
    with pytest.raises(CaptionError, match="invalid_response"):
        parse_answers(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"analysisRevision": 1, "paused": True},
        {"captionRevision": 1},
        {"segmentId": str(uuid.uuid4())},
        {"workerGeneration": 2},
    ],
)
def test_control_change_cancels_old_reply(changes):
    async def check():
        client, session = Client(), state()
        pipeline = JudgmentPipeline(client, session)
        task = asyncio.create_task(pipeline.run())
        try:
            offer_exchange(pipeline)
            await asyncio.wait_for(client.started.wait(), 1)
            pipeline.configure({**session, **changes})
            client.release.set()
            await asyncio.sleep(0.01)
            assert not pipeline.outbox and pipeline.queue.empty() and not pipeline.pre
            if changes.get("paused"):
                assert not pipeline.wants_frame(10)
        finally:
            await stop(pipeline, task)

    asyncio.run(check())


def test_slow_requests_bound_backlog_and_do_not_block_sampling():
    async def check():
        client = Client()
        pipeline = JudgmentPipeline(client, state())
        task = asyncio.create_task(pipeline.run())
        try:
            offer_exchange(pipeline)
            await asyncio.wait_for(client.started.wait(), 1)
            # Fill idle intervals so these represent continuous reception.
            for k in range(13, 61):
                t = k / 4
                pipeline.offer(
                    b"jpeg",
                    t,
                    int(5 <= t <= 6 or 9 <= t <= 10 or 13 <= t <= 14),
                    "stable",
                )
            assert len(client.seen) == 1 and pipeline.queue.qsize() == 1
            assert pipeline.skipped == 2 and len(pipeline.pre) <= 5
            client.release.set()
            await asyncio.sleep(0.01)
            assert any(entry["kind"] == "direction" for entry in pipeline.outbox)
        finally:
            await stop(pipeline, task)

    asyncio.run(check())


def test_uncertain_identity_and_missing_coverage_abandon_exchange():
    pipeline = JudgmentPipeline(Client(), state())
    pipeline.offer(b"jpeg", 0, 0, "stable")
    pipeline.offer(b"jpeg", 0.25, 1, "stable")
    pipeline.offer(b"jpeg", 0.5, None, "uncertain")
    for k in range(3, 12):
        pipeline.offer(b"jpeg", k / 4, 0, "stable")
    assert pipeline.queue.empty() and any(
        e["gap_reason"] == "identity_uncertain" for e in pipeline.outbox
    )
    pipeline.offer(b"jpeg", 5, 1, "stable")
    assert pipeline.samples is None and pipeline.queue.empty()
    assert pipeline.outbox[-1]["gap_reason"] == "coverage_gap"


def test_overlong_exchange_is_bounded_and_becomes_a_gap():
    pipeline = JudgmentPipeline(Client(), state())
    for k in range(100):
        pipeline.offer(b"jpeg", k / 4, 1, "stable")
        assert pipeline.samples is None or len(pipeline.samples) <= 40
    assert pipeline.queue.empty() and pipeline.skipped == 1
    assert pipeline.outbox[-1]["gap_reason"] == "too_long"


def test_identity_loss_cancels_a_pending_model_answer():
    async def check():
        client = Client()
        pipeline = JudgmentPipeline(client, state())
        task = asyncio.create_task(pipeline.run())
        try:
            offer_exchange(pipeline)
            await asyncio.wait_for(client.started.wait(), 1)
            pipeline.offer(b"jpeg", 3.25, None, "lost")
            client.release.set()
            await asyncio.sleep(0.01)
            assert not any(e["kind"] == "direction" for e in pipeline.outbox)
        finally:
            await stop(pipeline, task)

    asyncio.run(check())


def test_expired_lease_never_starts_model_request():
    async def check():
        client = Client()
        active = True
        pipeline = JudgmentPipeline(client, state(), lambda: active)
        offer_exchange(pipeline)
        active = False
        task = asyncio.create_task(pipeline.run())
        try:
            await asyncio.sleep(0.01)
            assert not client.seen
        finally:
            await stop(pipeline, task)

    asyncio.run(check())


def test_transport_sends_two_questions_frames_and_no_previous_answers(monkeypatch):
    async def check():
        seen = []

        async def respond(request):
            seen.append(await request.json())
            if len(seen) == 1:
                return web.Response(status=503, text="secret must never escape")
            return web.json_response(reply())

        app = web.Application()
        app.router.add_post("/decisions", respond)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        monkeypatch.setenv(
            "FIGHTLENS_DECISIONS_URL",
            f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/decisions",
        )
        monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key")
        monkeypatch.setenv("FIGHTLENS_JUDGMENTS_ENABLED", "1")
        try:
            async with aiohttp.ClientSession() as http:
                client = LiveDecisions(http)
                samples = [Sample(1, b"jpeg"), Sample(2, b"jpeg")]
                with pytest.raises(CaptionError, match="^endpoint_unavailable$"):
                    await client.review(samples, state()["captionFighters"])
                answers = await client.review(samples, state()["captionFighters"])
                assert answers["direction"]["choice"] == "favors_A"
                assert set(seen[-1]["questions"]) == {"direction", "evidence"}
                assert isinstance(seen[-1]["state"][0], str)
                assert seen[-1]["state"][1]["type"] == "image_url"
                assert "previous" not in str(seen[-1]["state"])
                assert len(seen) == 2  # Failure wasn't retried.
        finally:
            await runner.cleanup()

    asyncio.run(check())


def test_explicit_opt_in_and_identity_are_required(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key")
    monkeypatch.delenv("FIGHTLENS_JUDGMENTS_ENABLED", raising=False)
    pipeline = JudgmentPipeline(LiveDecisions(None), state())
    assert pipeline.status == "not_configured" and not pipeline.wants_frame(2)
    pipeline = JudgmentPipeline(Client(), state(captionFighters=None))
    assert pipeline.status == "awaiting_identity" and not pipeline.wants_frame(2)


def test_receiver_samples_real_pixels_without_consuming_the_yolo_queue():
    async def check():
        import io

        from livekit import rtc
        from PIL import Image
        from receiver import Receiver

        client = Client()
        client.release.set()
        receiver = Receiver(state(), None, None, Client(), client)
        receiver.frames.put_nowait(("pending-yolo-frame",))
        receiver.judgment_sampler = asyncio.create_task(receiver.sample_judgments())
        receiver.judgment_runner = asyncio.create_task(receiver.judgments.run())
        frame = rtc.VideoFrame(
            640, 360, rtc.VideoBufferType.RGB24, bytes([40, 70, 90]) * (640 * 360)
        )
        try:
            for k in range(13):
                position = k / 4
                receiver.judgment_frames.put_nowait(
                    (
                        frame,
                        position,
                        receiver.judgments.key,
                        int(4 <= k <= 8),
                        "stable",
                    )
                )
                async with asyncio.timeout(2):
                    while receiver.judgments.last_position != position:
                        await asyncio.sleep(0.001)
            async with asyncio.timeout(2):
                while not any(
                    e["kind"] == "direction" for e in receiver.judgments.outbox
                ):
                    await asyncio.sleep(0.001)
            assert receiver.frames.qsize() == 1
            assert client.seen[0][0][-1].t == 2.75
            with Image.open(io.BytesIO(client.seen[0][0][0].jpeg)) as image:
                assert image.size == (640, 384)
        finally:
            await receiver.close()

    asyncio.run(check())
