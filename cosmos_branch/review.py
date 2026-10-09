"""The trigger: windows in, Cosmos's answers into the memory.

    python review.py <clip_dir>                       # the YOLO branch's windows.jsonl (or exchange.jsonl) in that folder
    python review.py <clip_dir> --follow              # the same while windows.jsonl is still growing
    python review.py <clip_dir> --grid 2.5 --video bout.mp4 --a "red trunks" --b "black trunks"     # no YOLO at all
    python review.py <clip_dir> --window 12.2 14.6    # one stretch by hand: prints question, reply and reading, stores nothing
    python review.py <clip_dir> --glance 20 30        # the same for the question about the time between exchanges

<clip_dir> is the YOLO branch's output folder for one video (yolo_branch/outputs/<clip>/). Read from it:

    summary.json       where the video is (or --video)
    keypoints.jsonl    where A and B are: the crop and the A / B tags on the clips (--no-tags leaves both off)
    windows.jsonl      when to look (windows.py)

Written into it (or into --out):

    cosmos/<id>.mp4 .jpg .txt     the clip Cosmos watched, its contact sheet, its raw reply
                                  (cosmos/by_hand/ for --window and --glance)
    memory.jsonl, memory.json     what Cosmos said, and what follows from it (memory.py)

One window is one clip, one question, one memory entry. The YOLO branch's part ends where the window is handed
over: it says when, and its tracking says who is called A. What happened is Cosmos's answer alone.

A run can be repeated: windows that have an answer are skipped, failed ones are asked again. --fresh starts over.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Optional

import asks
import clips
import narrate
from cosmos import Cosmos, CosmosError
from memory import CONTEXT, EXCHANGE, FAILED, Memory
from windows import CONTEXT_FPS, EXCHANGE_FPS, EXCHANGE_MAX_S, Planner, Window, find_file, grid, plan, read_spans, span_of

WORKERS = 2              # clips under review at once (ask about rate limits before raising it)
NOTES_GIVE_UP = 2        # failures in a row after which the notes are left alone for the rest of the run


class Reviewer:
    """One window in, one memory entry out."""

    def __init__(self, video: Path, out_dir: Path, memory: Memory, cosmos: Cosmos, poses: Optional[clips.Poses] = None,
                 fighters: Optional[dict] = None, text: Optional[Cosmos] = None):
        """fighters: {"A": "red trunks", "B": "black trunks"}, for the question. text: the model that writes the
        running notes (None = no notes)."""
        self.video, self.out_dir, self.memory, self.cosmos = Path(video), Path(out_dir), memory, cosmos
        self.poses, self.fighters, self.text = poses, {k: v for k, v in (fighters or {}).items() if v}, text
        self._open: dict[str, float] = {}        # windows handed in and not answered yet: id -> t0
        self._lock = threading.Lock()
        self._notes_failed = 0

    def submit(self, pool: ThreadPoolExecutor, window: Window) -> Optional[Future]:
        """Review this window on the pool. None when the memory has its answer already."""
        if self.memory.has(window.id):
            return None
        with self._lock:
            self._open[window.id] = window.t0
        return pool.submit(self.review, window)

    def review(self, window: Window) -> dict:
        """Watch one window and write what Cosmos said into the memory. A review that fails is written down
        as failed (and asked again on the next run); it never stops the run."""
        started = time.perf_counter()
        entry = {"id": window.id, "t0": window.t0, "t1": window.t1, "source": window.source}
        if window.ref:
            entry["window"] = window.ref           # the YOLO branch's id for the row that made Cosmos look
        if window.cuts:
            entry["camera_cuts"] = list(window.cuts)
        try:
            clip, _, _, said = self.look(window)
            entry.update(kind=window.kind, **said, clip=self._relative(clip.path), sheet=self._relative(clip.sheet),
                         frames=clip.frames, model=self.cosmos.model, latency_s=round(time.perf_counter() - started, 2))
        except (CosmosError, ValueError, OSError) as exc:
            entry.update(kind=FAILED, asked=window.kind, error=str(exc))
        entry = self.memory.add(entry)
        with self._lock:
            self._open.pop(window.id, None)
            frontier = min(self._open.values(), default=None)
        self.notes(frontier)
        return entry

    def look(self, window: Window, strict: bool = True, folder: str = "cosmos") -> tuple[clips.Clip, str, str, dict]:
        """Cut the clip, ask, read the answer: (clip, prompt, raw reply, reading). Stores nothing in the memory.

        strict: refuse a clip in which nothing says who is A and who is B. Across clips "the one on the left"
        does not stay with a fighter, so such an answer cannot go into the memory."""
        clip = clips.cut(self.video, window, self.out_dir / folder, self.poses)
        if strict and not clip.tagged and not self.fighters:
            raise ValueError("Nothing says who is A and who is B in this clip: the tracker did not see the fighters "
                             "in this window, and no descriptions were given (--a / --b)")
        system, prompt = asks.question(window, clip, self.fighters)
        reply = self.cosmos.ask(system, prompt, clip.path)
        clip.path.with_suffix(".txt").write_text(reply, encoding="utf-8")
        return clip, prompt, reply, asks.read(window, reply)

    def notes(self, frontier: Optional[float] = None, force: bool = False) -> None:
        """Rewrite the running notes when enough has been added (narrate.write_notes)."""
        if self.text is None or self._notes_failed >= NOTES_GIVE_UP:
            return
        try:
            if narrate.write_notes(self.memory, self.text, frontier, force):
                self._notes_failed = 0
        except CosmosError as exc:
            self._notes_failed += 1
            print(f"  the notes were not rewritten: {exc}"
                  + ("  (left alone for the rest of this run)" if self._notes_failed >= NOTES_GIVE_UP else ""), file=sys.stderr)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.out_dir).as_posix()


def run(reviewer: Reviewer, windows: Iterable[Window], workers: int = WORKERS,
        report: Callable[[dict], None] = lambda entry: None) -> None:
    """Review these windows, a few at a time, in bout order."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [f for f in (reviewer.submit(pool, window) for window in windows) if f]:
            future.add_done_callback(lambda done: report(done.result()))


def follow(reviewer: Reviewer, path: Path, planner: Planner, video_fps: Optional[float] = None, workers: int = WORKERS,
           report: Callable[[dict], None] = lambda entry: None, poll_s: float = 0.5,
           stop: Optional[threading.Event] = None) -> None:
    """Review windows as the YOLO branch appends them to `path`. Ends on a row {"end": true} (optionally with
    "t", the bout time the video ended at), when `stop` is set, or on Ctrl-C; reviews under way are finished."""
    position, ended = 0, False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        try:
            while not ended and not (stop and stop.is_set()):
                rows, position = _new_rows(path, position)
                for row in rows:
                    if row.get("end") or str(row.get("state", "")).upper() == "END":
                        found, ended = planner.finish(row.get("t")), True
                    else:
                        found = planner.feed(span_of(row, video_fps, path.name))
                    for window in found:
                        future = reviewer.submit(pool, window)
                        if future:
                            future.add_done_callback(lambda done: report(done.result()))
                    if ended:
                        break
                if not ended:
                    time.sleep(poll_s)
        except KeyboardInterrupt:
            print("Stopping: the reviews under way are being finished", file=sys.stderr)


def _new_rows(path: Path, position: int) -> tuple[list[dict], int]:
    """The complete lines added to the file since `position`. A line still being written is left for the next look."""
    if not path.exists():
        return [], position
    with path.open("rb") as log:
        log.seek(position)
        data = log.read()
    whole = data[:data.rfind(b"\n") + 1]
    rows = [json.loads(line) for line in whole.decode("utf-8").splitlines() if line.strip()]
    return rows, position + len(whole)


# ───────────────────────── Command line ─────────────────────────

def report_line(entry: dict) -> None:
    span = f"{entry['id']:<8} {narrate.clock(entry['t0'])}-{narrate.clock(entry['t1'])}"
    if entry["kind"] == FAILED:
        print(f"{span}  FAILED  {entry['error']}", flush=True)
    elif entry["kind"] == EXCHANGE:
        landed = sum(strike["outcome"] == "landed" for strike in entry["strikes"])
        print(f"{span}  {entry['latency_s']:5.1f} s  {len(entry['strikes'])} strikes, {landed} landed  "
              f"better of it: {entry['advantage']}  \"{entry['note']}\"", flush=True)
    else:
        print(f"{span}  {entry['latency_s']:5.1f} s  pressing: {entry['pressure']}"
              + (f"  notable: {entry['notable']}" if entry["notable"] else "") + f"  \"{entry['note']}\"", flush=True)


def _find_video(clip_dir: Path, given: Optional[Path]) -> Path:
    if given:
        if not given.is_file():
            raise SystemExit(f"No such video: {given}")
        return given
    summary = clip_dir / "summary.json"
    if not summary.is_file():
        raise SystemExit(f"{summary} is not there, so nothing says which video this is: pass --video")
    video = Path(json.loads(summary.read_text(encoding="utf-8")).get("video", ""))
    if not video.is_file():
        raise SystemExit(f"summary.json names {video}, which is not on this machine: pass --video")
    return video


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Have Cosmos watch the windows the YOLO branch points at, and remember what it says")
    parser.add_argument("clip_dir", type=Path, help="the YOLO branch's output folder for one video")
    parser.add_argument("--video", type=Path, help="the video (default: the one summary.json names)")
    parser.add_argument("--out", type=Path, help="where to write (default: the clip folder)")
    parser.add_argument("--windows", type=Path, help="the windows file (default: windows.jsonl, else exchange.jsonl, in the clip folder)")
    parser.add_argument("--follow", action="store_true", help="keep reading the windows file as it grows")
    parser.add_argument("--grid", type=float, metavar="SECONDS", help="no windows file: the whole video in pieces of this length")
    parser.add_argument("--window", type=float, nargs=2, metavar=("T0", "T1"), help="ask about one stretch and print everything; stores nothing")
    parser.add_argument("--glance", type=float, nargs=2, metavar=("T0", "T1"), help="the same, with the question for the time between exchanges")
    parser.add_argument("--a", help='what fighter A looks like, e.g. "red trunks, shaved head"')
    parser.add_argument("--b", help="what fighter B looks like")
    parser.add_argument("--no-tags", action="store_true", help="do not use keypoints.jsonl: no crop, no A / B tags (then --a and --b are needed)")
    parser.add_argument("--no-context", action="store_true", help="exchanges only: no glances at the time between them")
    parser.add_argument("--no-notes", action="store_true", help="do not write the running notes")
    parser.add_argument("--workers", type=int, default=WORKERS, help=f"clips under review at once (default {WORKERS})")
    parser.add_argument("--fresh", action="store_true", help="forget what is in the memory and start over")
    parser.add_argument("--url", help="the Cosmos endpoint (default: COSMOS3_REASON_URL)")
    parser.add_argument("--model", help="the model name (default: COSMOS3_REASON_MODEL, else asked from the endpoint)")
    args = parser.parse_args(argv)

    clip_dir, out_dir = args.clip_dir, args.out or args.clip_dir
    video = _find_video(clip_dir, args.video)
    video_fps, duration = clips.video_info(video)
    keypoints = clip_dir / "keypoints.jsonl"
    poses = clips.Poses(keypoints) if keypoints.is_file() and not args.no_tags else None
    fighters = {"A": args.a, "B": args.b}
    try:
        cosmos = Cosmos(url=args.url, model=args.model)
        cosmos.model                   # reach the endpoint now, before any clip is cut
    except CosmosError as exc:
        raise SystemExit(str(exc))
    text = None if args.no_notes else (
        narrate.text_model() if os.environ.get("NARRATOR_URL") or os.environ.get("NARRATOR_MODEL") else cosmos)
    memory = Memory(out_dir)
    reviewer = Reviewer(video, out_dir, memory, cosmos, poses, fighters, text)

    by_hand = args.window or args.glance
    if by_hand:
        kind = EXCHANGE if args.window else CONTEXT
        window = Window(by_hand[0], by_hand[1], kind, "hand", EXCHANGE_FPS if args.window else CONTEXT_FPS)
        if kind == EXCHANGE and window.seconds > EXCHANGE_MAX_S:
            print(f"Note: {window.seconds:.1f} s is longer than one exchange clip ({EXCHANGE_MAX_S:.0f} s), so it is sampled "
                  "more thinly than a real run would sample it")
        started = time.perf_counter()
        try:
            clip, prompt, reply, said = reviewer.look(window, strict=False, folder="cosmos/by_hand")
        except (CosmosError, ValueError, OSError) as exc:
            print(f"No answer: {exc}\nThe raw reply, if there was one: {out_dir / 'cosmos' / 'by_hand' / (window.id + '.txt')}")
            return 1
        print(f"== The question ({cosmos.model}) ==\n{prompt}\n\n== The raw reply ==\n{reply}\n\n== As read ==")
        print(json.dumps(said, indent=2, ensure_ascii=False))
        print(f"\n{time.perf_counter() - started:.1f} s, {clip.frames} frames. The clip: {clip.path}   Its frames: {clip.sheet}")
        return 0

    if poses is None and not (args.a and args.b):
        raise SystemExit("Nothing says who is A and who is B: there is no keypoints.jsonl to tag the fighters from "
                         "(or --no-tags was given), so describe them with --a and --b")
    if args.fresh:
        memory.clear()

    print(f"{video.name}: {narrate.clock(duration)}, Cosmos at {cosmos.url} ({cosmos.model}), "
          f"{'tags from keypoints.jsonl' if poses else 'no tags'}", flush=True)
    if args.follow:
        source = args.windows or clip_dir / "windows.jsonl"
        print(f"Following {source} (Ctrl-C to stop)", flush=True)
        follow(reviewer, source, Planner(context=not args.no_context), video_fps, args.workers, report_line)
    else:
        if args.grid:
            windows = grid(duration, args.grid)
        else:
            source = args.windows or find_file(clip_dir)
            if source is None:
                raise SystemExit(f"No windows.jsonl or exchange.jsonl in {clip_dir}: run the YOLO branch's engage.py first, "
                                 "or scan the whole video with --grid SECONDS")
            try:
                windows = plan(read_spans(source, video_fps), duration, context=not args.no_context)
            except ValueError as exc:
                raise SystemExit(str(exc))
            print(f"{source.name}: ", end="")
        todo = [window for window in windows if not memory.has(window.id)]
        print(f"{sum(w.kind == EXCHANGE for w in windows)} exchange clips, {sum(w.kind == CONTEXT for w in windows)} "
              f"glances, {len(windows) - len(todo)} of them answered already", flush=True)
        run(reviewer, todo, args.workers, report_line)
    reviewer.notes(force=True)

    snapshot = memory.snapshot()
    print()
    for fighter in "AB":
        got = snapshot["received"][fighter]
        print(f"Hits taken by {fighter}: {got['total']}  (head {got['head']}, torso {got['torso']}, legs {got['legs']}"
              + (f", unplaced {got['other']}" if got["other"] else "") + ")")
    if snapshot["summary"]:
        print(f"Notes: {snapshot['summary']['text']}")
    print(f"-> {memory.path}  ({snapshot['entries'][EXCHANGE]} exchanges, {snapshot['entries'][CONTEXT]} glances, "
          f"{snapshot['entries'][FAILED]} failed)")
    answered = snapshot["entries"][EXCHANGE] + snapshot["entries"][CONTEXT]
    return 0 if answered or not snapshot["entries"][FAILED] else 1


if __name__ == "__main__":
    sys.exit(main())
