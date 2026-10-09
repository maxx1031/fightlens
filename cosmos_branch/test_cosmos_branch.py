"""Tests for the Cosmos branch. Run from anywhere: python -m pytest cosmos_branch

Nothing here needs the real endpoint, the YOLO branch or a GPU. The clip folder is made up in the shape
yolo_branch/track.py writes (summary.json, keypoints.jsonl), with a video whose frames carry their own number.
"""
from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

import asks
import clips
import fake_cosmos
import narrate
import review
from cosmos import Cosmos, CosmosError, extract_json
from memory import Memory
from windows import CONTEXT, EXCHANGE, Planner, Span, Window, grid, kind_of, plan, read_spans

WIDTH, HEIGHT, FPS, SECONDS = 640, 360, 30.0, 12
A_X, B_X = 220, 400


def _skeleton(x: int) -> list[list[float]]:
    """17 keypoints in COCO order for a figure standing at x: head at y 105-110, ankles at 320."""
    dx = [0, -4, 4, -8, 8, -15, 15, -20, 20, -18, 18, -10, 10, -10, 10, -10, 10]
    ys = [110, 105, 105, 108, 108, 150, 150, 190, 190, 225, 225, 230, 230, 280, 280, 320, 320]
    return [[float(x + d), float(y)] for d, y in zip(dx, ys)]


MISSING = {"track_id": None, "xy": [[None, None]] * 17, "conf": [0.0] * 17, "status": "missing"}


@pytest.fixture(scope="session")
def source(tmp_path_factory) -> Path:
    """One video for all tests. The grey of its top-left block is the frame number (modulo 16), in steps wide
    enough to survive two rounds of video compression."""
    path = tmp_path_factory.mktemp("video") / "bout.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    for index in range(int(SECONDS * FPS)):
        image = np.full((HEIGHT, WIDTH, 3), 90, np.uint8)
        image[0:48, 0:48] = (index % 16) * 16 + 8
        cv2.rectangle(image, (A_X - 20, 100), (A_X + 20, 320), (40, 40, 200), -1)
        cv2.rectangle(image, (B_X - 20, 100), (B_X + 20, 320), (200, 90, 40), -1)
        writer.write(image)
    writer.release()
    return path


@pytest.fixture
def clip_dir(tmp_path, source) -> Path:
    """What track.py leaves behind for that video. B is lost from 4.0 to 4.5 s, both fighters from 8 to 9 s."""
    folder = tmp_path / "outputs" / "bout"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps({"video": str(source), "source_fps": FPS}))
    with (folder / "keypoints.jsonl").open("w") as log:
        for index in range(int(SECONDS * FPS)):
            t = index / FPS
            nobody = 8.0 <= t < 9.0
            row = {"t": t,
                   "A": MISSING if nobody else {"track_id": 1, "xy": _skeleton(A_X), "conf": [0.9] * 17, "status": "tracked"},
                   "B": MISSING if nobody or 4.0 <= t < 4.5 else
                   {"track_id": 2, "xy": _skeleton(B_X), "conf": [0.9] * 17, "status": "tracked"}}
            log.write(json.dumps(row) + "\n")
    return folder


class Scripted:
    """Stands in for the Cosmos client: answers from a function and keeps what it was asked."""
    model = "scripted"

    def __init__(self, answer=lambda prompt: fake_cosmos.answer(prompt)[1]):
        self.answer, self.asked = answer, []

    def ask(self, system, prompt, video=None):
        self.asked.append((prompt, video))
        reply = self.answer(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _reviewer(clip_dir, source, cosmos, **more) -> review.Reviewer:
    more.setdefault("poses", clips.Poses(clip_dir / "keypoints.jsonl"))
    return review.Reviewer(source, clip_dir, Memory(clip_dir), cosmos, **more)


def _exchange(*strikes, advantage="even", note="n") -> str:
    keys = ("t", "attacker", "limb", "target", "outcome")
    return json.dumps({"strikes": [dict(zip(keys, strike)) for strike in strikes], "advantage": advantage, "note": note})


def _engage(t0: float, t1: float) -> Window:
    return Window(t0, t1, EXCHANGE, "yolo:ENGAGE", 12.0)


# ───────────────────────── When to look ─────────────────────────

def test_the_states_of_the_yolo_branch_decide_how_closely_cosmos_looks(tmp_path):
    rows = [("FAR", 0, 3), ("RANGE", 3, 4), ("ENGAGE", 4, 6), ("RANGE", 6, 11), ("ENGAGE", 11, 12.5), ("FAR", 12.5, 20)]
    path = tmp_path / "windows.jsonl"
    path.write_text("".join(json.dumps({"state": s, "t0": a, "t1": b}) + "\n" for s, a, b in rows))
    windows = plan(read_spans(path), duration=20.0)
    assert [(w.kind, w.t0, w.t1, w.source) for w in windows] == [
        (EXCHANGE, 4, 6, "yolo:ENGAGE"),
        (CONTEXT, 6, 11, "yolo:RANGE"),             # RANGE long enough for a glance; the one-second RANGE before is not
        (EXCHANGE, 11, 12.5, "yolo:ENGAGE"),
    ]                                               # and nobody looks at FAR
    assert windows[0].fps > windows[1].fps          # an exchange is sampled more densely than a glance


def test_a_long_engagement_is_watched_in_pieces_and_a_short_one_is_widened():
    pieces = plan([Span(10.0, 17.0, "ENGAGE")], context=False)
    assert [(w.t0, w.t1) for w in pieces] == [(10.0, 12.333), (12.333, 14.667), (14.667, 17.0)]
    short, = plan([Span(5.0, 5.4, "ENGAGE")], context=False)
    assert (short.t0, short.t1) == (4.7, 5.7)       # one second around its middle
    first, second = plan([Span(5.0, 6.5, "ENGAGE"), Span(6.6, 6.8, "ENGAGE")], context=False)
    assert second.t0 == first.t1 == 6.5 and second.t1 == 7.5     # widened forwards only: 5.0-6.5 has been watched


def test_time_no_row_covers_is_glanced_at():
    windows = plan([Span(4.0, 6.0, "ENGAGE"), Span(12.0, 13.0, "ENGAGE")], duration=30.0)
    assert [(w.kind, w.t0, w.t1, w.source) for w in windows] == [
        (CONTEXT, 0.0, 4.0, "gap"), (EXCHANGE, 4.0, 6.0, "yolo:ENGAGE"), (CONTEXT, 6.0, 12.0, "gap"),
        (EXCHANGE, 12.0, 13.0, "yolo:ENGAGE"),
        (CONTEXT, 13.0, 21.5, "gap"), (CONTEXT, 21.5, 30.0, "gap"),      # 17 s left: two glances of at most 10 s
    ]
    assert not [w for w in plan([Span(4.0, 6.0, "ENGAGE")], duration=30.0, context=False) if w.kind == CONTEXT]


def test_rows_that_overlap_are_not_watched_twice():
    windows = plan([Span(4.0, 6.0, "ENGAGE"), Span(5.0, 7.5, "ENGAGE"), Span(5.5, 6.5, "ENGAGE")], context=False)
    assert [(w.t0, w.t1) for w in windows] == [(4.0, 6.0), (6.0, 7.5)]


@pytest.mark.parametrize("row, expected", [
    ({"start": 1.5, "end": 3.0, "label": "engage"}, (1.5, 3.0, EXCHANGE)),
    ({"t_start": 1.5, "t_end": 3.0, "state": "RANGE", "fps": 1}, (1.5, 3.0, CONTEXT)),
    ({"window": [1.5, 3.0]}, (1.5, 3.0, EXCHANGE)),                         # no state: something to look at
    ({"start_frame": 45, "end_frame": 89, "state": "ENGAGE"}, (1.5, 3.0, EXCHANGE)),
])
def test_other_spellings_of_a_window_row(tmp_path, row, expected):
    path = tmp_path / "windows.jsonl"
    path.write_text(json.dumps(row) + "\n")
    span, = read_spans(path, video_fps=30.0)
    assert (span.t0, span.t1, kind_of(span.state)) == expected
    if "fps" in row:
        assert plan([Span(0.0, 4.0, "RANGE", fps=1.0)])[0].fps == 1.0       # a rate named by the row is the rate used


def test_rows_as_engage_py_writes_them(tmp_path, clip_dir, source):
    rows = [
        {"clip_id": "bout", "window_id": "w000", "start": 0.0, "end": 1.483, "state": "RANGE", "sample_fps": 4.0,
         "reason": "d_min=1.57 d_dot_min=-0.16", "camera_cuts_s": []},
        {"clip_id": "bout", "window_id": "w001", "start": 1.483, "end": 2.783, "state": "ENGAGE", "sample_fps": 30.0,
         "reason": "d_min=1.43 w_peak=4.9", "camera_cuts_s": [2.1]},
        {"clip_id": "bout", "window_id": "w002", "start": 2.783, "end": 9.0, "state": "RANGE", "sample_fps": 4.0,
         "reason": "tracking_gap: sample conservatively", "camera_cuts_s": []},
        {"clip_id": "bout", "window_id": "w003", "start": 9.0, "end": 12.0, "state": "FAR", "sample_fps": 0.5,
         "reason": "d_min=3.40", "camera_cuts_s": []},
    ]
    path = tmp_path / "windows.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    windows = plan(read_spans(path), duration=12.0)
    assert [(w.id, w.kind, w.fps, w.ref, w.cuts) for w in windows] == [
        ("x1.48", EXCHANGE, 30.0, "w001", (2.1,)), ("c2.78", CONTEXT, 4.0, "w002", ())]
    cosmos = Scripted()
    entry = _reviewer(clip_dir, source, cosmos).review(windows[0])
    assert (entry["window"], entry["camera_cuts"], entry["frames"]) == ("w001", [2.1], clips.MAX_FRAMES)   # 39 frames asked, capped
    prompt = cosmos.asked[0][0]
    assert "cuts to another camera at 2.10 s" in prompt and "d_min" not in prompt and "w_peak" not in prompt


def test_a_row_that_cannot_be_read_stops_the_run_and_names_its_keys(tmp_path):
    path = tmp_path / "windows.jsonl"
    path.write_text(json.dumps({"state": "ENGAGE", "at": 3.0, "length": 2.0}) + "\n")
    with pytest.raises(ValueError, match=r"\['at', 'length', 'state'\]"):
        read_spans(path)


def test_the_per_frame_file_gives_one_stretch_per_run_of_engaged_frames(tmp_path):
    path = tmp_path / "exchange.jsonl"
    engaged = [0] * 30 + [1] * 45 + [0] * 30 + [1] * 15
    path.write_text("".join(json.dumps({"t": i / 30, "engaged": e}) + "\n" for i, e in enumerate(engaged)))
    spans = read_spans(path)
    assert [(round(s.t0, 3), round(s.t1, 3), s.state) for s in spans] == [(1.0, 2.5, "ENGAGE"), (3.5, 4.0, "ENGAGE")]


def test_without_yolo_the_whole_video_is_cut_into_equal_exchanges():
    windows = grid(11.0, 2.5)
    assert len(windows) == 5 and windows[0].t0 == 0.0 and windows[-1].t1 == 11.0
    assert all(w.kind == EXCHANGE and w.source == "grid" and abs(w.seconds - 2.2) < 1e-6 for w in windows)
    assert [w.id for w in windows][:2] == ["x0.00", "x2.20"]                # the id is the kind and the start time


# ───────────────────────── What Cosmos is shown ─────────────────────────

def _frames_of(path: Path) -> list[np.ndarray]:
    capture, frames = cv2.VideoCapture(str(path)), []
    while True:
        ok, image = capture.read()
        if not ok:
            break
        frames.append(image)
    capture.release()
    return frames


def test_the_clip_holds_the_frames_of_the_window_in_slow_motion(tmp_path, source):
    clip = clips.cut(source, _engage(2.0, 3.0), tmp_path)
    assert (clip.frames, clip.speed, clip.cropped, clip.tagged) == (12, 0.333, False, False)
    capture = cv2.VideoCapture(str(clip.path))
    assert capture.get(cv2.CAP_PROP_FPS) == clips.CLIP_FPS
    capture.release()
    frames = _frames_of(clip.path)
    assert len(frames) == 12 and frames[0].shape[:2] == (clips.CLIP_HEIGHT + clips.STAMP_HEIGHT, 854)
    wanted = [round((2.0 + (i + 0.5) / 12) * FPS) for i in range(12)]       # 61, 64, 66, 69, ... of the video
    found = [round((float(frame[10:50, 10:50].mean()) - 8) / 16) for frame in frames]
    assert found == [index % 16 for index in wanted]                        # these very frames, not their neighbours
    assert clip.sheet.is_file() and cv2.imread(str(clip.sheet)) is not None


def test_with_tracking_the_clip_is_cropped_to_the_fighters_and_tagged(tmp_path, clip_dir, source):
    poses = clips.Poses(clip_dir / "keypoints.jsonl")
    clip = clips.cut(source, _engage(2.0, 3.0), tmp_path, poses)
    assert clip.cropped and clip.tagged
    picture = _frames_of(clip.path)[0][:clips.CLIP_HEIGHT]
    assert picture.shape[1] < 854                                           # narrower than the whole picture would be
    white = (picture.min(axis=2) > 235).sum()
    assert white > 2 * 20 * 20                                              # two tags; the scene itself has no white in it
    untagged = _frames_of(clips.cut(source, _engage(2.0, 3.0), tmp_path / "plain").path)[0][:clips.CLIP_HEIGHT]
    assert (untagged.min(axis=2) > 235).sum() == 0


def test_keypoints_are_read_as_track_py_writes_them(clip_dir):
    poses = clips.Poses(clip_dir / "keypoints.jsonl")
    assert set(poses.at(2.0)) == {"A", "B"} and poses.at(2.0)["A"].shape == (17, 2)
    assert set(poses.at(4.2)) == {"A"}                                      # B's row says missing, with null coordinates
    assert poses.at(8.5) == {} and poses.at(99.0) == {}
    x1, y1, x2, y2 = poses.extent(2.0, 3.0)
    assert (x1, x2, y1, y2) == (A_X - 20, B_X + 20, 105, 320)
    assert poses.extent(8.2, 8.8) is None

    guessed = {"track_id": 1, "xy": _skeleton(A_X), "conf": [0.9] * 17, "status": "tracked"}
    guessed["xy"][9], guessed["conf"][9] = [0.0, 0.0], 0.05                 # a wrist the model did not see: parked in the corner
    (clip_dir / "one_row.jsonl").write_text(json.dumps({"t": 0.0, "A": guessed, "B": MISSING}) + "\n")
    one = clips.Poses(clip_dir / "one_row.jsonl")
    assert np.isnan(one.at(0.0)["A"][9]).all() and one.extent(0.0, 0.1)[:2] == (A_X - 20, 105)


def test_a_window_the_tracker_did_not_see_is_sent_whole_and_untagged(tmp_path, clip_dir, source):
    clip = clips.cut(source, _engage(8.2, 8.8), tmp_path, clips.Poses(clip_dir / "keypoints.jsonl"))
    assert not clip.cropped and not clip.tagged


def test_a_window_past_the_end_of_the_video_is_an_error(tmp_path, source):
    with pytest.raises(ValueError, match="no frames between"):
        clips.cut(source, _engage(SECONDS + 5.0, SECONDS + 6.0), tmp_path)


# ───────────────────────── What Cosmos is asked, and how its answer is read ─────────────────────────

def test_the_question_says_how_the_fighters_are_told_apart(tmp_path, clip_dir, source):
    window = _engage(2.0, 3.0)
    tagged = clips.cut(source, window, tmp_path, clips.Poses(clip_dir / "keypoints.jsonl"))
    plain = clips.cut(source, window, tmp_path / "plain")
    described = {"A": "red trunks", "B": "black trunks"}
    assert "tagged A and B above their heads" in asks.exchange_prompt(tagged)
    both = asks.exchange_prompt(tagged, described)
    assert "A: red trunks." in both and "go by the description" in both
    assert "A is red trunks. B is black trunks." in asks.exchange_prompt(plain, described)
    assert "tagged" not in asks.exchange_prompt(plain, described)
    for prompt in (asks.exchange_prompt(tagged), asks.context_prompt(tagged)):
        assert "runs from 2.00 s to 3.00 s" in prompt and "about 3 times slower" in prompt


def test_an_exchange_answer_is_read_strictly_where_it_counts():
    reply = "<think>B's hand goes out {first}</think>\nHere it is:\n```json\n" + json.dumps({"strikes": [
        {"t": "t = 12.90 s", "attacker": "Fighter A", "limb": "punch", "move": "Jab", "target": "face", "outcome": "connected"},
        {"t": 13.4, "attacker": "b", "limb": "kick", "target": "lead leg", "outcome": "checked"},
        {"t": 2.1, "attacker": "A", "limb": "knee", "target": "body", "outcome": "not landed"},
        {"t": 13.0, "attacker": "the referee", "limb": "hand", "target": "head", "outcome": "landed"},
        {"t": 12.5, "attacker": "B", "limb": "tentacle", "target": "aura", "outcome": "glancing"},
    ], "advantage": "A", "note": "A  jabs;\nB checks."}) + "\n```"
    said = asks.read_exchange(reply, _engage(12.25, 14.6))
    assert said["strikes"] == [
        {"t": 12.5, "attacker": "B", "limb": None, "move": "", "target": None, "outcome": "unclear"},
        {"t": 12.9, "attacker": "A", "limb": "hand", "move": "jab", "target": "head", "outcome": "landed"},
        {"t": 13.4, "attacker": "B", "limb": "foot", "move": "", "target": "legs", "outcome": "blocked"},
        # 2.1 s is not in this window (time into the clip, most likely): the strike stays, its time does not
        {"t": None, "attacker": "A", "limb": "knee", "move": "", "target": "torso", "outcome": "unclear"},
    ]
    assert (said["dropped"], said["advantage"], said["note"]) == (1, "A", "A jabs; B checks.")


def test_no_list_of_strikes_is_not_an_answer_but_an_empty_list_is():
    window = _engage(1.0, 2.0)
    assert asks.read_exchange('{"strikes": [], "advantage": "neither", "note": "They circle."}', window) == {
        "strikes": [], "advantage": "even", "note": "They circle.", "dropped": 0}
    with pytest.raises(CosmosError, match="no list of strikes"):
        asks.read_exchange('{"note": "A lands a jab."}', window)
    with pytest.raises(CosmosError, match="no JSON object"):
        asks.read_exchange("A lands a jab.", window)
    with pytest.raises(CosmosError, match="MAX_TOKENS"):
        asks.read_exchange("<think>A's hand goes out and then", window)


def test_a_context_answer_is_read():
    assert asks.read_context('{"pressure": "fighter b", "notable": "None", "note": "B walks A down."}') == {
        "pressure": "B", "notable": "", "note": "B walks A down."}
    assert asks.read_context('{"pressure": "both", "notable": "A is cut over the eye", "note": ""}')["pressure"] == "neither"
    with pytest.raises(CosmosError):
        asks.read_context('{"strikes": []}')


def test_the_one_json_object_is_found_among_chatter():
    assert extract_json('Sure {see below}. <answer>{"a": {"b": 1}}</answer> Done.') == {"a": {"b": 1}}
    assert extract_json('I looked {closely}. {"a": 1} and that is all {really}') == {"a": 1}


# ───────────────────────── What is remembered ─────────────────────────

def _remember(memory: Memory, t0: float, t1: float, *strikes, kind=EXCHANGE, **more) -> dict:
    keys = ("t", "attacker", "target", "outcome")
    return memory.add({"id": f"{'x' if kind == EXCHANGE else 'c'}{t0:.2f}", "kind": kind, "t0": t0, "t1": t1,
                       "strikes": [dict(zip(keys, strike)) for strike in strikes], **more})


def test_hits_taken_are_counted_from_the_landed_strikes(tmp_path):
    memory = Memory(tmp_path)
    _remember(memory, 1.0, 3.0, (1.5, "A", "head", "landed"), (2.0, "A", "head", "blocked"), (2.5, "B", "legs", "landed"))
    _remember(memory, 5.0, 7.0, (5.5, "A", "torso", "landed"), (None, "A", None, "landed"), (6.0, "B", "head", "missed"))
    tally = memory.tally()
    assert tally["received"]["B"] == {"head": 1, "torso": 1, "legs": 0, "other": 1, "total": 3}
    assert tally["received"]["A"] == {"head": 0, "torso": 0, "legs": 1, "other": 0, "total": 1}
    assert tally["thrown"]["A"] == {"landed": 3, "blocked": 1, "missed": 0, "unclear": 0, "total": 4}
    assert memory.tally(until=4.0)["received"]["B"]["total"] == 1           # as it stood at 4 s
    assert memory.tally(since=4.0)["received"]["B"]["total"] == 2           # what was added after 4 s
    assert json.loads((tmp_path / "memory.json").read_text())["received"] == tally["received"]


def test_the_same_blow_reported_by_two_neighbouring_clips_counts_once(tmp_path):
    memory = Memory(tmp_path)
    _remember(memory, 1.0, 3.0, (2.95, "A", "head", "landed"))
    _remember(memory, 3.0, 5.0, (3.05, "A", "head", "landed"), (3.2, "A", "head", "landed"), (3.1, "B", "head", "landed"))
    assert memory.tally()["received"]["B"]["head"] == 2                     # 2.95 and 3.05 are one blow, 3.2 is the next
    assert memory.tally()["received"]["A"]["head"] == 1
    memory = Memory(tmp_path / "one_clip")
    _remember(memory, 1.0, 3.0, (2.0, "A", "head", "landed"), (2.1, "A", "head", "landed"))
    assert memory.tally()["received"]["B"]["head"] == 2                     # one clip saying two is two


def test_the_log_is_append_only_and_survives_a_run_cut_off_mid_line(tmp_path):
    memory = Memory(tmp_path)
    _remember(memory, 1.0, 3.0, (1.5, "A", "head", "landed"))
    with memory.path.open("a") as log:
        log.write('{"id": "x5.00", "kind": "exch')                          # the process died here
    memory = Memory(tmp_path)
    assert [entry["id"] for entry in memory.entries()] == ["x1.00"]
    _remember(memory, 5.0, 7.0, (5.5, "B", "head", "landed"))
    assert [entry["id"] for entry in Memory(tmp_path).entries()] == ["x1.00", "x5.00"]
    assert len(memory.path.read_text().splitlines()) == 3                   # nothing was rewritten: the torn line is still there


def test_the_latest_answer_counts_and_a_failure_never_displaces_one(tmp_path):
    memory = Memory(tmp_path)
    memory.add({"id": "x1.00", "kind": "failed", "t0": 1.0, "t1": 3.0, "error": "timeout"})
    assert not memory.has("x1.00") and memory.entries() == [] and memory.snapshot()["entries"]["failed"] == 1
    _remember(memory, 1.0, 3.0, (1.5, "A", "head", "landed"))
    assert memory.has("x1.00") and memory.snapshot()["entries"] == {"exchange": 1, "context": 0, "failed": 0}
    memory.add({"id": "x1.00", "kind": "failed", "t0": 1.0, "t1": 3.0, "error": "timeout"})
    assert memory.has("x1.00") and memory.tally()["received"]["B"]["head"] == 1
    _remember(memory, 1.0, 3.0, (1.5, "A", "head", "blocked"))               # reviewed again: this one counts now
    assert memory.tally()["received"]["B"]["head"] == 0 and len(memory.entries()) == 1


# ───────────────────────── The trigger: a window in, a memory entry out ─────────────────────────

def test_one_window_becomes_one_entry_holding_what_cosmos_said(clip_dir, source):
    cosmos = Scripted(lambda prompt: _exchange((2.4, "A", "hand", "head", "landed"), advantage="A", note="A lands a jab."))
    reviewer = _reviewer(clip_dir, source, cosmos)
    entry = reviewer.review(_engage(2.0, 3.0))
    assert {key: entry[key] for key in ("id", "kind", "t0", "t1", "source", "advantage", "note", "model", "frames")} == {
        "id": "x2.00", "kind": EXCHANGE, "t0": 2.0, "t1": 3.0, "source": "yolo:ENGAGE", "advantage": "A",
        "note": "A lands a jab.", "model": "scripted", "frames": 12}
    assert entry["strikes"] == [{"t": 2.4, "attacker": "A", "limb": "hand", "move": "", "target": "head", "outcome": "landed"}]
    (prompt, video), = cosmos.asked
    assert video == clip_dir / "cosmos" / "x2.00.mp4" and video.is_file()
    assert (clip_dir / entry["clip"]).is_file() and (clip_dir / entry["sheet"]).is_file()
    assert json.loads((clip_dir / "cosmos" / "x2.00.txt").read_text())["note"] == "A lands a jab."     # the raw reply is kept
    assert Memory(clip_dir).tally()["received"]["B"]["head"] == 1
    # The YOLO branch said when to look and who is called A. The question carries nothing else of it.
    assert "tagged A and B" in prompt and not any(word in prompt.lower() for word in ("suspect", "tracker", "engage"))


def test_a_failed_review_is_written_down_and_asked_again_on_the_next_run(clip_dir, source):
    replies = [CosmosError("HTTP 503"), "I could not tell.", _exchange()]
    cosmos = Scripted(lambda prompt: replies.pop(0))
    reviewer = _reviewer(clip_dir, source, cosmos)
    for expected in ("HTTP 503", "no JSON object"):
        review.run(reviewer, [_engage(2.0, 3.0)])
        failed, = Memory(clip_dir).entries(None)
        assert failed["kind"] == "failed" and expected in failed["error"] and failed["asked"] == EXCHANGE
    assert (clip_dir / "cosmos" / "x2.00.txt").read_text() == "I could not tell."       # what it did say can be looked at
    review.run(reviewer, [_engage(2.0, 3.0)])
    review.run(reviewer, [_engage(2.0, 3.0)])                                           # answered: not asked a fourth time
    assert len(cosmos.asked) == 3 and Memory(clip_dir).snapshot()["entries"] == {"exchange": 1, "context": 0, "failed": 0}


def test_nothing_goes_into_the_memory_when_nothing_says_who_is_who(clip_dir, source):
    cosmos = Scripted()
    entry = _reviewer(clip_dir, source, cosmos).review(_engage(8.2, 8.8))                # the tracker saw nobody here
    assert entry["kind"] == "failed" and "who is A and who is B" in entry["error"] and not cosmos.asked
    described = _reviewer(clip_dir, source, cosmos, fighters={"A": "red trunks", "B": "black trunks"})
    assert described.review(_engage(8.2, 8.8))["kind"] == EXCHANGE
    assert "A is red trunks" in cosmos.asked[0][0]
    by_hand = _reviewer(clip_dir, source, cosmos, poses=None)
    _, prompt, _, _ = by_hand.look(_engage(2.0, 3.0), strict=False, folder="cosmos/by_hand")   # one clip looked at by hand may
    assert "on the left in the first frame" in prompt and len(Memory(clip_dir).entries()) == 1


def test_the_notes_are_rewritten_every_few_entries_in_bout_order(clip_dir, source):
    def slow(prompt):
        time.sleep(random.Random(prompt).uniform(0.0, 0.05))                 # answers arrive out of order
        return fake_cosmos.answer(prompt)[1]

    cosmos = Scripted(slow)
    reviewer = _reviewer(clip_dir, source, cosmos, text=cosmos)
    windows = [_engage(t / 2, t / 2 + 0.5) for t in range(0, 15)]            # 15 windows, 0.0 to 7.5 s
    review.run(reviewer, windows, workers=4)
    reviewer.notes(force=True)
    memory = Memory(clip_dir)
    notes = memory.entries(("summary",))
    assert len(notes) >= 2 and [n["id"] for n in notes] == [f"s{i + 1}" for i in range(len(notes))]
    assert sorted(i for n in notes for i in n["covers"]) == sorted(w.id for w in windows)      # everything once
    covered: set[str] = set()
    for n in notes:
        covered |= set(n["covers"])
        assert covered == {e["id"] for e in memory.entries(until=n["t"])}    # nothing after the notes' time, nothing before it left out
    assert all(len(n["covers"]) >= narrate.SUMMARY_EVERY for n in notes[:-1])
    assert memory.snapshot()["summary"] == {"t": notes[-1]["t"], "text": notes[-1]["text"]}


def test_windows_are_reviewed_as_the_yolo_branch_appends_them(clip_dir, source):
    path = clip_dir / "windows.jsonl"
    path.write_text("")
    reviewer, seen = _reviewer(clip_dir, source, Scripted()), []
    thread = threading.Thread(target=review.follow, args=(reviewer, path, Planner(), FPS, 2, seen.append, 0.02))
    thread.start()
    with path.open("a") as log:
        log.write('{"state": "ENGAGE", "t0": 1.0, "t1": 2.5}\n{"state": "ENG')         # the second row is still being written
    deadline = time.time() + 10
    while not reviewer.memory.has("x1.00") and time.time() < deadline:
        time.sleep(0.02)
    assert [entry["id"] for entry in reviewer.memory.entries()] == ["x1.00"]
    with path.open("a") as log:
        log.write('AGE", "t0": 6.0, "t1": 7.5}\n{"end": true, "t": 12.0}\n')
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert [entry["id"] for entry in reviewer.memory.entries()] == ["x1.00", "c2.50", "x6.00", "c7.50"]
    assert len(seen) == 4


# ───────────────────────── The words ─────────────────────────

def _bout(tmp_path) -> Memory:
    memory = Memory(tmp_path)
    _remember(memory, 2.0, 4.0, (2.5, "A", "head", "landed"), (3.0, "B", "legs", "landed"), advantage="even", note="They trade.")
    _remember(memory, 10.0, 12.0, (10.5, "A", "head", "landed"), (11.0, "A", "torso", "landed"), advantage="A", note="A doubles up.")
    memory.add({"id": "c12.00", "kind": CONTEXT, "t0": 12.0, "t1": 20.0, "pressure": "A", "notable": "", "note": "A walks B down."})
    _remember(memory, 30.0, 32.0, (30.5, "B", "head", "landed"), advantage="B", note="B counters.")
    return memory


def test_the_caption_is_asked_with_the_number_and_the_exact_counts(tmp_path):
    cosmos = Scripted(lambda prompt: json.dumps({"text": "A doubled up at 0:10.", "evidence": ["[x10.00]", "x99.00", "c12.00"], "agrees": "Yes"}))
    row = narrate.caption(_bout(tmp_path), "63%", t=25.0, prev=(5.0, 0.5), cosmos=cosmos)
    prompt = cosmos.asked[0][0]
    assert "A 63%, B 37%. At 0:05 it was A 50%, B 50%." in prompt and cosmos.asked[0][1] is None      # no video
    assert "B threw 1 (1 landed, 0 blocked, 0 missed, 0 unclear) and took 3 hits (head 2, torso 1, legs 0)." in prompt
    assert "Since 0:05:\nA threw 2 (2 landed" in prompt
    assert "[x10.00] 0:10-0:12 exchange. A strike to head: landed (10.5 s); A strike to torso: landed (11.0 s). Better of it: A." in prompt
    assert "x30.00" not in prompt                                            # the bout has not got there at 0:25
    assert row == {"t": 25.0, "p_A": 0.63, "prev": {"t": 5.0, "p_A": 0.5}, "record": "A", "number": "A", "consistent": True,
                   "text": "A doubled up at 0:10.", "evidence": ["x10.00", "c12.00"], "agrees": "yes", "by": "scripted"}


def test_the_caption_says_when_record_and_number_point_at_different_fighters(tmp_path):
    memory = _bout(tmp_path)
    assert narrate.caption(memory, 0.70, t=35.0, prev=(25.0, 0.63))["consistent"] is False       # B landed, the number went to A
    assert narrate.caption(memory, 0.55, t=35.0, prev=(25.0, 0.63))["consistent"] is True
    assert narrate.caption(memory, 0.63, t=25.0, prev=(21.0, 0.50))["consistent"] is None        # nothing landed since 0:21
    first = narrate.caption(memory, 0.40, t=25.0)                                                # no number before it: read against 50%
    assert (first["record"], first["number"], first["consistent"], first["prev"]) == ("A", "B", False, None)


def test_without_a_usable_reply_the_caption_is_built_from_the_counts(tmp_path):
    memory = _bout(tmp_path)
    for reply in (CosmosError("HTTP 503"), "The fight is close.", '{"evidence": []}'):
        row = narrate.caption(memory, 0.6, t=35.0, prev=(25.0, 0.63), cosmos=Scripted(lambda prompt: reply))
        assert row["by"] == "counts" and row["error"] and row["evidence"] == ["x30.00"]
        assert row["text"] == "Since 0:25: A landed 0, B landed 1 (1 head). Over the bout: A landed 3 (2 head, 1 torso), B landed 2 (1 head, 1 legs)."
    assert narrate.caption(memory, 0.6, t=25.0)["text"] == "So far A landed 3 (2 head, 1 torso) and B landed 1 (1 legs)."
    assert narrate.caption(Memory(tmp_path / "empty"), 0.5)["text"] == "No strikes have been logged yet."
    with pytest.raises(ValueError):
        narrate.caption(memory, 163)


def test_notes_fold_the_new_entries_into_the_old_notes(tmp_path):
    memory, cosmos = _bout(tmp_path), Scripted(lambda prompt: '{"summary": "A leads on volume;  B counters late."}')
    assert narrate.write_notes(memory, cosmos) is None                       # four entries: not time yet
    first = narrate.write_notes(memory, cosmos, frontier=25.0, force=True)
    assert (first["id"], first["t"], first["covers"], first["text"]) == ("s1", 20.0, ["x2.00", "x10.00", "c12.00"], "A leads on volume; B counters late.")
    assert "(none: this is the start of the bout)" in cosmos.asked[0][0]
    second = narrate.write_notes(memory, Scripted(lambda prompt: "<think>hm</think>B is back in it."), force=True)
    assert (second["id"], second["t"], second["covers"], second["text"]) == ("s2", 32.0, ["x30.00"], "B is back in it.")
    assert memory.summary(until=25.0)["id"] == "s1" and memory.unsummarised() == []
    assert [entry["id"] for entry in memory.unsummarised(until=25.0)] == []
    with pytest.raises(CosmosError):
        _remember(memory, 40.0, 41.0)
        narrate.write_notes(memory, Scripted(lambda prompt: "<think>cut off"), force=True)


# ───────────────────────── How Cosmos is reached ─────────────────────────

class Http:
    """A stand-in for `requests`: answers from a list and keeps what was sent."""

    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.sent.append((method, url, json, headers))
        status, body = self.replies.pop(0)
        return type("Reply", (), {"status_code": status, "text": str(body), "json": lambda self: body})()


def _said(text: str) -> tuple[int, dict]:
    return 200, {"choices": [{"message": {"content": text}}]}


def test_the_request_is_the_one_the_endpoint_expects(tmp_path, monkeypatch):
    monkeypatch.delenv("COSMOS3_REASON_MODEL", raising=False)
    monkeypatch.delenv("COSMOS_API_KEY", raising=False)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not really a video")
    http = Http((200, {"data": [{"id": "nvidia/cosmos3-reason"}]}), _said("one"), _said("two"))
    cosmos = Cosmos(url="http://host:8000/v1/", http=http)
    assert cosmos.ask("system", "about a video", video) == "one" and cosmos.ask("system", "words only") == "two"
    (_, models_url, _, _), (method, url, with_video, headers), (_, _, words_only, _) = http.sent
    assert models_url == "http://host:8000/v1/models" and (method, url) == ("post", "http://host:8000/v1/chat/completions")
    assert with_video["model"] == "nvidia/cosmos3-reason" and with_video["temperature"] == 0 and headers == {}
    system, user = with_video["messages"]
    assert system == {"role": "system", "content": "system"} and user["content"][0] == {"type": "text", "text": "about a video"}
    assert user["content"][1]["video_url"]["url"] == "data:video/mp4;base64,bm90IHJlYWxseSBhIHZpZGVv"
    assert words_only["messages"][1] == {"role": "user", "content": "words only"}


def test_a_busy_endpoint_is_asked_again_and_a_refused_request_is_not(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    http = Http((503, "busy"), (429, "slow down"), _said("at last"))
    assert Cosmos(url="http://host", model="m", http=http).ask("s", "p") == "at last" and len(http.sent) == 3
    http = Http((400, "video too long"), _said("never reached"))
    with pytest.raises(CosmosError, match="HTTP 400: video too long"):
        Cosmos(url="http://host", model="m", http=http).ask("s", "p")
    assert len(http.sent) == 1
    with pytest.raises(CosmosError, match="COSMOS3_REASON_URL"):
        monkeypatch.delenv("COSMOS3_REASON_URL", raising=False)
        Cosmos()


# ───────────────────────── The whole way, over HTTP ─────────────────────────

def test_from_the_yolo_branchs_folder_to_a_caption(clip_dir, capsys, monkeypatch):
    for name in ("COSMOS3_REASON_MODEL", "COSMOS_API_KEY", "NARRATOR_URL", "NARRATOR_MODEL", "NARRATOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    (clip_dir / "windows.jsonl").write_text("".join(json.dumps({"state": s, "t0": a, "t1": b}) + "\n" for s, a, b in [
        ("FAR", 0, 1), ("ENGAGE", 1, 5), ("RANGE", 5, 9.5), ("ENGAGE", 9.5, 10.2), ("RANGE", 10.2, 12)]))
    server = fake_cosmos.serve(port=0, think=True)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert review.main([str(clip_dir), "--url", url]) == 0
        entries = Memory(clip_dir).entries()
        assert [entry["id"] for entry in entries] == ["x1.00", "x3.00", "c5.00", "x9.35"]      # 4 s in two clips; 0.7 s widened to 1
        assert all(entry["model"] == fake_cosmos.MODEL and (clip_dir / entry["clip"]).is_file() for entry in entries)
        assert sorted(set(server.asked)) == [("context", True), ("exchange", True), ("notes", False)]
        asked = len(server.asked)
        assert review.main([str(clip_dir), "--url", url]) == 0 and len(server.asked) == asked  # a second run asks nothing
        assert "4 of them answered already" in capsys.readouterr().out

        assert narrate.main([str(clip_dir), "--p-a", "0.6", "--t", "8", "--url", url]) == 0
        assert narrate.main([str(clip_dir), "--p-a", "0.7", "--url", url]) == 0
        first, second = [json.loads(row) for row in (clip_dir / "narration.jsonl").read_text().splitlines()]
        assert first["by"] == fake_cosmos.MODEL and first["prev"] is None and server.asked[-1] == ("caption", False)
        # no --t: as far as the memory reaches (the last RANGE is too short for a glance); the number before it is found on file
        assert (second["t"], second["prev"]) == (10.35, {"t": 8.0, "p_A": 0.6})

        assert review.main([str(clip_dir), "--url", url, "--window", "2", "3.5"]) == 0
        printed = capsys.readouterr().out
        assert "== The question" in printed and "== The raw reply ==" in printed and (clip_dir / "cosmos/by_hand/x2.00.mp4").is_file()
        assert len(Memory(clip_dir).entries()) == 4                                      # looking by hand stores nothing
    finally:
        server.shutdown()
