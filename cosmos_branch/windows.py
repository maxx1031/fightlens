"""When Cosmos should look.

The YOLO branch decides when, and nothing else: it hands over stretches of bout time, never what happened in
them. Two kinds of window come out of here:

    exchange   the fighters are trading: a close look (slow motion, every strike listed)
    context    the time between exchanges: a glance (who is pressing, anything notable)

Where the stretches come from:

    <clip>/windows.jsonl    engage.py's FAR / RANGE / ENGAGE windows:  ENGAGE -> exchange, RANGE -> context, FAR -> skipped
    <clip>/exchange.jsonl   engage.py's per-frame `engaged` 0/1:        runs of 1 -> exchange, the rest -> context
    grid()                  no YOLO at all: the whole video in equal pieces, every one of them an exchange

A row of windows.jsonl as engage.py writes it:

    {"clip_id": "...", "window_id": "w007", "start": 12.0, "end": 13.4, "state": "ENGAGE",
     "sample_fps": 30.0, "reason": "d_min=1.20 w_peak=9.1", "camera_cuts_s": []}

What is taken from it: start, end, state; sample_fps as the sampling rate (an ENGAGE row names the source frame
rate, which clips.MAX_FRAMES then caps); window_id, kept in the memory entry so the two branches' files can be
joined; camera_cuts_s, which the question mentions. `reason` (the pose signals) is not read: Cosmos is not
told what the tracker measured. Other spellings of start / end / state are accepted too (_T0 / _T1 / _STATE);
a row that fits none stops the run and prints its keys.

Bout time not covered by any row is treated like RANGE.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

EXCHANGE, CONTEXT = "exchange", "context"

# How closely to look. Sampling rates are frames per second of bout time, not of the clip (see clips.py).
EXCHANGE_MAX_S = 3.0     # a longer engagement is watched in pieces of at most this, one clip each
EXCHANGE_MIN_S = 1.0     # a shorter one is widened to this, so the approach and the recoil are in the clip
EXCHANGE_FPS = 12.0      # a jab is over in a quarter of a second: this leaves three frames of it
CONTEXT_MAX_S = 10.0
CONTEXT_MIN_S = 2.0      # a shorter gap between exchanges gets no glance of its own
CONTEXT_FPS = 2.0

_T0 = ("t0", "start", "t_start", "start_t", "start_s", "begin", "from")
_T1 = ("t1", "end", "t_end", "end_t", "end_s", "stop", "to")
_F0 = ("f0", "start_frame", "frame_start", "first_frame")
_F1 = ("f1", "end_frame", "frame_end", "last_frame")
_PAIR = ("window", "span", "range", "interval")
_STATE = ("state", "label", "kind", "mode", "phase", "type")
_RATE = ("fps", "sample_fps", "sampling_fps", "rate")
_EPS = 1e-6


@dataclass(frozen=True)
class Span:
    """One stretch of bout time as the YOLO branch reported it."""
    t0: float
    t1: float
    state: str = "ENGAGE"
    fps: Optional[float] = None        # the sampling rate the row asks for, when it names one
    ref: str = ""                      # the row's own id (window_id), when it has one
    cuts: tuple = ()                   # bout times of camera cuts inside it


@dataclass(frozen=True)
class Window:
    """One clip's worth of bout time for Cosmos to watch."""
    t0: float
    t1: float
    kind: str                          # EXCHANGE | CONTEXT
    source: str                        # what triggered it: "yolo:ENGAGE", "yolo:RANGE", "gap", "grid", "hand"
    fps: float                         # frames per second of bout time to sample
    ref: str = ""                      # the YOLO branch's id for the row this came from
    cuts: tuple = ()                   # bout times of camera cuts inside it

    @property
    def id(self) -> str:
        """Stable across runs: the kind and the start time. It names the memory entry and the clip file."""
        return f"{'x' if self.kind == EXCHANGE else 'c'}{self.t0:.2f}"

    @property
    def seconds(self) -> float:
        return self.t1 - self.t0


def kind_of(state: str) -> Optional[str]:
    """What a state of the YOLO branch asks of Cosmos. None = do not look."""
    word = str(state).strip().upper()
    if not word or word.startswith("ENG") or word in ("EXCHANGE", "CLINCH", "ATTACK", "ACTIVE", "1", "TRUE"):
        return EXCHANGE                # a file of bare windows has no state: every row is something to look at
    if word.startswith("FAR") or word in ("IDLE", "SKIP", "NONE", "OFF"):
        return None
    return CONTEXT                     # RANGE, and anything else that is not clearly one of the two above


# ───────────────────────── Reading the YOLO branch's files ─────────────────────────

def find_file(clip_dir: Path) -> Optional[Path]:
    for name in ("windows.jsonl", "exchange.jsonl"):
        if (Path(clip_dir) / name).is_file():
            return Path(clip_dir) / name
    return None


def read_spans(path: Path, video_fps: Optional[float] = None) -> list[Span]:
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{Path(path).name}, line {number}: not JSON ({exc})") from exc
    if not rows:
        return []
    per_frame = "engaged" in rows[0] and _first(rows[0], _T0 + _F0 + _PAIR) is None
    spans = _runs(rows) if per_frame else [span_of(row, video_fps, Path(path).name) for row in rows]
    return sorted(spans, key=lambda s: s.t0)


def span_of(row: dict, video_fps: Optional[float] = None, where: str = "windows.jsonl") -> Span:
    """One row of windows.jsonl. Raises ValueError, naming the row's keys, when its start and end cannot be found."""
    pair = _first(row, _PAIR)
    t0, t1 = _first(row, _T0), _first(row, _T1)
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        t0, t1 = pair
    elif t0 is None or t1 is None:
        f0, f1 = _first(row, _F0), _first(row, _F1)
        if f0 is not None and f1 is not None and video_fps:
            t0, t1 = float(f0) / video_fps, (float(f1) + 1) / video_fps
    if t0 is None or t1 is None:
        raise ValueError(
            f"{where}: cannot find where a window starts and ends in a row with the keys {sorted(row)}. "
            f"Expected one of {_T0} with one of {_T1} (seconds). Add the spelling to _T0 / _T1 in windows.py")
    rate = _first(row, _RATE)
    state = _first(row, _STATE)
    cuts = row.get("camera_cuts_s")
    return Span(float(t0), float(t1), "" if state is None else str(state),
                float(rate) if isinstance(rate, (int, float)) and rate > 0 else None,
                ref=str(row.get("window_id") or ""),
                cuts=tuple(float(c) for c in cuts) if isinstance(cuts, (list, tuple)) else ())


def _first(row: dict, keys: Iterable[str]):
    return next((row[key] for key in keys if row.get(key) is not None), None)


def _runs(rows: list[dict]) -> list[Span]:
    """exchange.jsonl: one row per frame with `t` and `engaged`. Every run of engaged frames is one stretch."""
    times = [float(row["t"]) for row in rows]
    step = statistics.median(b - a for a, b in zip(times, times[1:])) if len(times) > 1 else 1 / 30
    spans, start = [], None
    for t, row in zip(times, rows):
        if row.get("engaged") and start is None:
            start = t
        elif not row.get("engaged") and start is not None:
            spans.append(Span(start, t, "ENGAGE"))
            start = None
    if start is not None:
        spans.append(Span(start, times[-1] + step, "ENGAGE"))
    return spans


# ───────────────────────── Stretches -> windows ─────────────────────────

class Planner:
    """Stretches in, windows out, in bout order. It is fed one stretch at a time, so the same code plans a
    finished file and a file that is still growing."""

    def __init__(self, context: bool = True):
        self._context = context
        self._cursor = 0.0             # bout time up to which windows have been planned
        self._watched = 0.0            # ... and up to which it has been watched closely (the end of the last exchange)

    def feed(self, span: Span) -> list[Window]:
        kind = kind_of(span.state)
        t0, t1 = max(span.t0, self._cursor), span.t1
        if t1 - t0 <= _EPS:
            return []                  # it lies inside time that has been planned already
        source = f"yolo:{span.state.upper()}" if span.state else "yolo"
        if kind == EXCHANGE:
            if t1 - t0 < EXCHANGE_MIN_S:       # widened around its middle: back into time that was only glanced at,
                t0 = max((t0 + t1 - EXCHANGE_MIN_S) / 2, self._watched)       # never into another exchange
                t1 = t0 + EXCHANGE_MIN_S
            out = self._glance(self._cursor, t0, "gap")
            out += _pieces(t0, t1, EXCHANGE_MAX_S, EXCHANGE, source, span.fps or EXCHANGE_FPS, span)
            self._watched = t1
        else:
            out = self._glance(self._cursor, t0, "gap")
            if kind == CONTEXT:
                out += self._glance(t0, t1, source, span.fps, span)
        self._cursor = t1
        return out

    def finish(self, duration: Optional[float]) -> list[Window]:
        """The video ended at `duration`: what is left after the last stretch."""
        if duration is None or duration <= self._cursor:
            return []
        out = self._glance(self._cursor, duration, "gap")
        self._cursor = duration
        return out

    def _glance(self, t0: float, t1: float, source: str, fps: Optional[float] = None,
                span: Optional[Span] = None) -> list[Window]:
        if not self._context or t1 - t0 < CONTEXT_MIN_S:
            return []
        return _pieces(t0, t1, CONTEXT_MAX_S, CONTEXT, source, fps or CONTEXT_FPS, span)


def _pieces(t0: float, t1: float, longest: float, kind: str, source: str, fps: float,
            span: Optional[Span] = None) -> list[Window]:
    count = max(1, math.ceil((t1 - t0) / longest - 1e-9))
    step = (t1 - t0) / count
    edges = [round(t0 + i * step, 3) for i in range(count + 1)]
    return [Window(a, b, kind, source, fps, span.ref if span else "",
                   tuple(c for c in span.cuts if a <= c < b) if span else ())
            for a, b in zip(edges, edges[1:])]


def plan(spans: Iterable[Span], duration: Optional[float] = None, context: bool = True) -> list[Window]:
    planner = Planner(context)
    windows = [window for span in sorted(spans, key=lambda s: s.t0) for window in planner.feed(span)]
    return windows + planner.finish(duration)


def grid(duration: float, step: float = 2.5) -> list[Window]:
    """No YOLO: the whole video in equal pieces of about `step` seconds, every one of them an exchange."""
    return _pieces(0.0, duration, step, EXCHANGE, "grid", EXCHANGE_FPS)
