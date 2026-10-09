"""What is remembered about the bout. Only Cosmos's answers are in here.

    memory.jsonl   the log: one line per answer, appended as it arrives, never edited
    memory.json    what follows from the log right now: hits taken, strikes thrown, the latest notes
                   (rewritten after every line, for the page and for anyone who wants the numbers)

The kinds of line:

    exchange  {"id": "x12.25", "kind": "exchange", "t0": 12.25, "t1": 14.6, "source": "yolo:ENGAGE",
               "strikes": [{"t": 12.9, "attacker": "A", "limb": "hand", "move": "jab", "target": "head", "outcome": "landed"}],
               "advantage": "A", "note": "...", "dropped": 0,
               "clip": "cosmos/x12.25.mp4", "sheet": "cosmos/x12.25.jpg", "frames": 28,
               "model": "nvidia/cosmos3-reason", "latency_s": 3.1, "written": "2026-10-09T14:02:11"}
    context   {"id": "c14.60", "kind": "context", "t0": 14.6, "t1": 24.6, "source": "yolo:RANGE",
               "pressure": "A", "notable": "", "note": "...", ...}
    summary   {"id": "s2", "kind": "summary", "t": 31.2, "covers": ["x24.60", "c27.00"], "text": "...", "model": "..."}
    failed    {"id": "x12.25", "kind": "failed", "t0": 12.25, "t1": 14.6, "source": "...", "error": "..."}

`source` says what made Cosmos look (a window of the YOLO branch, the time between two of them, a grid).
It is the only trace the YOLO branch leaves here: when, never what.

The rules:

  1. Append only. A window reviewed again is a new line under the same id, and the latest line for an id is
     the one that counts (a failure never displaces an answer). Nothing is edited, so the file can be read
     while it grows.
  2. Hits taken are not stored. They are counted from the landed strikes every time, so a second review of a
     window leaves nothing stale.
  3. The same blow reported by two neighbouring clips is counted once.
  4. A failed review counts for nothing, and the window is asked about again on the next run.
  5. The notes (summary) are words only. Every number shown anywhere is counted here, never taken from a model.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

EXCHANGE, CONTEXT, SUMMARY, FAILED = "exchange", "context", "summary", "failed"
REGIONS = ("head", "torso", "legs", "other")          # other = landed, but the reply did not say where
OUTCOMES = ("landed", "blocked", "missed", "unclear")
DUPLICATE_S = 0.25       # two reports of the same attacker hitting the same target this close together, from two clips, are one blow
_SLACK_S = 1e-6


def other(fighter: str) -> str:
    return "B" if fighter == "A" else "A"


class Memory:
    """Thread-safe: several reviews finish at once."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.path = self.dir / "memory.jsonl"
        self._lock = threading.RLock()
        self._rows: list[dict] = []
        self._mend = False
        if self.path.exists():
            text = self.path.read_text(encoding="utf-8")
            self._mend = bool(text) and not text.endswith("\n")       # a run was cut off in the middle of a line
            for line in text.splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and "id" in row and "kind" in row:
                    self._rows.append(row)

    # ── writing: one way in ──

    def add(self, entry: dict) -> dict:
        entry = {**entry, "written": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log:
                log.write(("\n" if self._mend else "") + json.dumps(entry, ensure_ascii=False) + "\n")
            self._mend = False
            self._rows.append(entry)
            self._write_snapshot()
        return entry

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            for path in (self.path, self.dir / "memory.json"):
                path.unlink(missing_ok=True)

    # ── reading ──

    def entries(self, kinds: Optional[Iterable[str]] = (EXCHANGE, CONTEXT), until: Optional[float] = None) -> list[dict]:
        """The entries that count, in bout order: the latest line per id, of these kinds (None = all),
        whose window had ended by bout time `until`."""
        rows = [row for row in self._latest().values()
                if (kinds is None or row["kind"] in kinds) and (until is None or _end(row) <= until + _SLACK_S)]
        return sorted(rows, key=lambda row: (row.get("t0", row.get("t", 0.0)), row["id"]))

    def has(self, entry_id: str) -> bool:
        """This window has an answer already (a failed review is not one)."""
        return self._latest().get(entry_id, {}).get("kind", FAILED) != FAILED

    def _latest(self) -> dict[str, dict]:
        """The line that counts for every id: the latest one, except that a failure never displaces an answer."""
        latest: dict[str, dict] = {}
        with self._lock:
            for row in self._rows:
                if row["kind"] == FAILED and latest.get(row["id"], row)["kind"] != FAILED:
                    continue
                latest[row["id"]] = row
        return latest

    def summary(self, until: Optional[float] = None) -> Optional[dict]:
        """The latest notes that cover nothing after bout time `until`."""
        notes = self.entries((SUMMARY,), until)
        return notes[-1] if notes else None

    def unsummarised(self, until: Optional[float] = None) -> list[dict]:
        """The entries the notes of that moment do not cover yet."""
        covered = {entry_id for notes in self.entries((SUMMARY,), until) for entry_id in notes.get("covers", ())}
        return [entry for entry in self.entries(until=until) if entry["id"] not in covered]

    def tally(self, until: Optional[float] = None, since: Optional[float] = None) -> dict:
        """Hits taken per fighter and region, strikes thrown per fighter and outcome, from the exchanges whose
        window ended after `since` and by `until`.

            {"received": {"A": {"head": 1, "torso": 0, "legs": 2, "other": 0, "total": 3}, "B": {...}},
             "thrown":   {"A": {"landed": 4, "blocked": 2, "missed": 1, "unclear": 0, "total": 7}, "B": {...}}}
        """
        reported = sorted(
            ((strike["t"] if strike.get("t") is not None else entry["t1"], entry, strike)
             for entry in self.entries((EXCHANGE,), until) for strike in entry.get("strikes", ())),
            key=lambda item: item[0])
        received = {fighter: dict.fromkeys(REGIONS, 0) for fighter in "AB"}
        thrown = {fighter: dict.fromkeys(OUTCOMES, 0) for fighter in "AB"}
        counted: list[tuple[float, dict, dict]] = []
        for t, entry, strike in reported:
            if any(seen_in["id"] != entry["id"] and seen["attacker"] == strike["attacker"]
                   and seen["target"] == strike["target"] and t - seen_t < DUPLICATE_S
                   for seen_t, seen_in, seen in counted[-4:]):
                continue                           # the neighbouring clip reported this blow already
            counted.append((t, entry, strike))
            if since is not None and entry["t1"] <= since + _SLACK_S:
                continue
            thrown[strike["attacker"]][strike["outcome"]] += 1
            if strike["outcome"] == "landed":
                received[other(strike["attacker"])][strike.get("target") or "other"] += 1
        for table in (received, thrown):
            for row in table.values():
                row["total"] = sum(row.values())
        return {"received": received, "thrown": thrown}

    def snapshot(self) -> dict:
        everything = self.entries(None)
        ends = [_end(row) for row in everything if row["kind"] in (EXCHANGE, CONTEXT)]
        notes = self.summary()
        return {
            "until": max(ends) if ends else 0.0,       # bout time the memory reaches
            **self.tally(),
            "summary": {"t": notes["t"], "text": notes["text"]} if notes else None,
            "entries": {kind: sum(row["kind"] == kind for row in everything) for kind in (EXCHANGE, CONTEXT, FAILED)},
        }

    def _write_snapshot(self) -> None:
        scratch = self.dir / "memory.json.tmp"
        scratch.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(scratch, self.dir / "memory.json")


def _end(row: dict) -> float:
    return float(row.get("t1", row.get("t", 0.0)))
