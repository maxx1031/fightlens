"""The words: the running notes on the bout, and the caption that goes with the win probability.

    python narrate.py <clip_dir> --p-a 0.63 --t 31                    # one caption, for A at 63% at 0:31
    python narrate.py <clip_dir> --p-a 0.63 --t 31 --prev 0.55 --prev-t 20
    python narrate.py <clip_dir> --predictions predictions.jsonl      # one caption per row ({"t": 31, "p_A": 0.63})
    python narrate.py <clip_dir> --notes                              # what the memory holds right now

    from narrate import caption; from memory import Memory; from cosmos import Cosmos
    row = caption(Memory(clip_dir), p_a=0.63, t=31.0, prev=(20.0, 0.55), cosmos=Cosmos())

Both kinds of text read the memory and nothing else, and neither produces a number: counts come from
memory.tally(), the probability comes from whoever computes it (not from here, and not from Cosmos).

    notes     triggered by the memory itself: every SUMMARY_EVERY new entries, the notes so far and the new
              entries are rewritten into new notes. A caption in minute 20 then reads the notes and the last
              few entries, not three hundred entries.
    caption   triggered by a new probability: two sentences for viewers on what in the record goes with the
              number, with the ids of the entries it rests on

A caption is told to explain with the record only, and to say so when the record does not go with the number.
Beside the model's words it carries two facts counted here: whom the record favours over the span the caption
is about (`record`), and which way the number went (`number`). When the two point at different fighters,
`consistent` is false: show that on the page, do not let fluent text cover it.

When the model cannot be reached or does not answer the question, the caption is a sentence built from the
counts (`by` says "counts").

The text model is the Cosmos endpoint, asked without a video. [UNVERIFIED] Whether that endpoint answers
text-only questions has not been tried. Any OpenAI-compatible endpoint works: --url / --model, or the
NARRATOR_URL / NARRATOR_MODEL / NARRATOR_API_KEY environment variables.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from cosmos import Cosmos, CosmosError, extract_json
from memory import EXCHANGE, SUMMARY, Memory

SUMMARY_EVERY = 6        # new entries before the notes are rewritten
SUMMARY_WORDS = 120
CAPTION_WORDS = 45
RECENT_S = 20.0          # a caption always sees the entries of the last this many seconds in full, whatever the notes cover
SHOWN_MAX = 14           # ... and never more entries than this
MOVE_MIN = 0.02          # a change of the probability smaller than this is no movement

NOTES_SYSTEM = ("You keep the running notes on a combat sports bout for a commentator. You are given the notes so far "
                "and what video review has added since, and you write only what those say. "
                "Reply with a single JSON object and nothing else.")
CAPTION_SYSTEM = ("You write the caption shown under a win probability during a combat sports bout. You are given the "
                  "number and the record of what video review saw, and you explain with that record only. "
                  "Reply with a single JSON object and nothing else.")

_notes_lock = threading.Lock()


def clock(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def line(entry: dict) -> str:
    """One memory entry as one line of a prompt."""
    span = f"[{entry['id']}] {clock(entry['t0'])}-{clock(entry['t1'])}"
    if entry["kind"] == EXCHANGE:
        strikes = "; ".join(
            f"{s['attacker']} {s.get('move') or s.get('limb') or 'strike'} to {s.get('target') or 'unknown target'}: {s['outcome']}"
            + (f" ({s['t']:.1f} s)" if s.get("t") is not None else "")
            for s in entry.get("strikes", ())) or "no strikes"
        return f"{span} exchange. {strikes}. Better of it: {entry.get('advantage', 'unclear')}. Reviewer: \"{entry.get('note', '')}\""
    notable = entry.get("notable") or "nothing"
    return f"{span} between exchanges. Pressing: {entry.get('pressure', 'unclear')}. Notable: {notable}. Reviewer: \"{entry.get('note', '')}\""


def counts(tally: dict) -> str:
    """The tally as two lines of a prompt."""
    lines = []
    for fighter in "AB":
        got, threw = tally["received"][fighter], tally["thrown"][fighter]
        lines.append(f"{fighter} threw {threw['total']} ({threw['landed']} landed, {threw['blocked']} blocked, "
                     f"{threw['missed']} missed, {threw['unclear']} unclear) and took {got['total']} "
                     f"{'hit' if got['total'] == 1 else 'hits'} (head {got['head']}, torso {got['torso']}, legs {got['legs']}"
                     + (f", unplaced {got['other']}" if got["other"] else "") + ").")
    return "\n".join(lines)


# ───────────────────────── The running notes ─────────────────────────

def write_notes(memory: Memory, cosmos: Cosmos, frontier: Optional[float] = None, force: bool = False) -> Optional[dict]:
    """Fold the entries the notes do not cover yet into new notes, when there are enough of them (or `force`).

    frontier: bout time before which every window has been answered. Entries after it wait, so that notes are
    written in bout order even when the answers arrive out of order. Returns the new summary entry, or None when
    it was not time yet. Raises CosmosError when the model gave no usable text.
    """
    if not _notes_lock.acquire(blocking=force):
        return None                                   # another review is writing them right now
    try:
        fresh = [entry for entry in memory.unsummarised() if frontier is None or entry["t1"] <= frontier + 1e-6]
        if not fresh or (len(fresh) < SUMMARY_EVERY and not force):
            return None
        before = memory.summary()
        t = max([entry["t1"] for entry in fresh] + ([before["t"]] if before else []))
        prompt = "\n".join([
            f"Notes so far (start of the bout to {clock(before['t'])}):" if before else "Notes so far:",
            before["text"] if before else "(none: this is the start of the bout)",
            "",
            "Added by video review since, in bout order:",
            *[line(entry) for entry in fresh],
            "",
            f"Counts from the start of the bout to {clock(t)}. They are exact: use them, do not recount.",
            counts(memory.tally(until=t)),
            "",
            f"Rewrite the notes so that they cover the bout from the start to {clock(t)}, in at most {SUMMARY_WORDS} words: "
            "who is landing what and where, who is pressing, how that has changed, anything notable. "
            "Keep the times of turning points (m:ss). Add nothing that is not above.",
            "",
            "Reply with exactly this JSON shape:",
            '{"summary": "<the notes>"}',
        ])
        text = _notes_text(cosmos.ask(NOTES_SYSTEM, prompt))
        return memory.add({"id": f"s{len(memory.entries((SUMMARY,))) + 1}", "kind": SUMMARY, "t": round(t, 2),
                           "covers": [entry["id"] for entry in fresh], "text": text, "model": cosmos.model})
    finally:
        _notes_lock.release()


def _notes_text(reply: str) -> str:
    try:
        data = extract_json(reply)
        text = data.get("summary") or data.get("notes") or ""
    except CosmosError:
        text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S)       # plain prose in place of the JSON is still notes
        if "<think>" in text or len(text) > 2000:
            raise
    text = " ".join(str(text).split())
    if not text:
        raise CosmosError("The reply has no notes in it")
    return text


# ───────────────────────── The caption ─────────────────────────

def caption(memory: Memory, p_a: float, t: Optional[float] = None, prev: Optional[tuple[float, float]] = None,
            cosmos: Optional[Cosmos] = None) -> dict:
    """The caption for "A wins with probability p_a" at bout time t (default: as far as the memory reaches).

    prev: (bout time, probability of A) of the number shown before this one, when there was one. The caption is
    then about the movement since. cosmos=None builds the caption from the counts, without a model.
    """
    p_a = _probability(p_a)
    if t is None:
        t = max((entry["t1"] for entry in memory.entries()), default=0.0)
    since, was = (float(prev[0]), _probability(prev[1])) if prev else (None, None)
    overall, lately = memory.tally(until=t), memory.tally(until=t, since=since)

    recent = [entry for entry in memory.entries(until=t) if entry["t1"] > t - RECENT_S]
    shown = {entry["id"]: entry for entry in memory.unsummarised(until=t) + recent}
    shown = sorted(shown.values(), key=lambda entry: entry["t0"])[-SHOWN_MAX:]
    notes = memory.summary(until=t)

    landed_a, landed_b = lately["received"]["B"]["total"], lately["received"]["A"]["total"]
    record = "A" if landed_a > landed_b else "B" if landed_b > landed_a else "even"
    change = p_a - (was if was is not None else 0.5)       # the first number is read against an even bout
    number = "A" if change > MOVE_MIN else "B" if change < -MOVE_MIN else "flat"
    row = {
        "t": round(t, 2), "p_A": round(p_a, 4), "prev": {"t": since, "p_A": round(was, 4)} if prev else None,
        "record": record, "number": number,
        "consistent": True if (record, number) in (("A", "A"), ("B", "B"), ("even", "flat"))
        else False if {record, number} == {"A", "B"} else None,
    }

    if cosmos is not None:
        prompt = "\n".join([
            f"Bout time now: {clock(t)}.",
            f"Win probability shown to viewers: A {p_a:.0%}, B {1 - p_a:.0%}."
            + (f" At {clock(since)} it was A {was:.0%}, B {1 - was:.0%}." if prev else " It is the first one shown."),
            "The number comes from a separate model. You do not know how it is computed.",
            "",
            "The record, from video review. Counts are exact: use them, do not recount.",
            "Since the start of the bout:",
            counts(overall),
            *([f"Since {clock(since)}:", counts(lately)] if prev else []),
            "",
            f"Notes on the bout up to {clock(notes['t'])}:" if notes else "Notes on the bout:",
            notes["text"] if notes else "(none yet)",
            "",
            "Entries:",
            *([line(entry) for entry in shown] or ["(nothing has been reviewed yet)"]),
            "",
            f"Write the caption that goes under the number: at most two sentences and {CAPTION_WORDS} words, for viewers "
            "watching the bout. Say what in the record goes with where the number is"
            + (" and how it moved." if prev else ".") + " Give times as m:ss. Use nothing that is not in the record above. "
            "If the record does not go with the number, say so plainly and do not look for a reason.",
            'Then list the ids of the entries the caption rests on, and say whether the record goes with the number: '
            '"yes", "partly" or "no".',
            "",
            "Reply with exactly this JSON shape:",
            '{"text": "<the caption>", "evidence": ["<entry id>"], "agrees": "<yes|partly|no>"}',
        ])
        try:
            data = extract_json(cosmos.ask(CAPTION_SYSTEM, prompt))
            text = " ".join(str(data.get("text") or "").split())
            if not text:
                raise CosmosError("The reply has no caption in it")
            cited = [str(item).strip(" []") for item in data.get("evidence") or [] if isinstance(item, (str, int, float))]
            agrees = str(data.get("agrees") or "").strip().lower()
            return {**row, "text": text, "evidence": [i for i in cited if i in {entry["id"] for entry in shown}],
                    "agrees": agrees if agrees in ("yes", "partly", "no") else "", "by": cosmos.model}
        except CosmosError as exc:
            row["error"] = str(exc)                   # and on to the caption from the counts

    hits = [entry["id"] for entry in memory.entries((EXCHANGE,), until=t)
            if (since is None or entry["t1"] > since) and any(s["outcome"] == "landed" for s in entry["strikes"])]
    return {**row, "text": _plain(overall, lately, since), "evidence": hits[-4:], "agrees": "", "by": "counts"}


def _plain(overall: dict, lately: dict, since: Optional[float]) -> str:
    def landed(tally: dict, fighter: str) -> str:
        got = tally["received"]["B" if fighter == "A" else "A"]
        where = ", ".join(f"{got[region]} {region}" for region in ("head", "torso", "legs") if got[region])
        return f"{fighter} landed {got['total']}" + (f" ({where})" if where else "")

    if not overall["thrown"]["A"]["total"] and not overall["thrown"]["B"]["total"]:
        return "No strikes have been logged yet."
    if since is None:
        return f"So far {landed(overall, 'A')} and {landed(overall, 'B')}."
    return (f"Since {clock(since)}: {landed(lately, 'A')}, {landed(lately, 'B')}. "
            f"Over the bout: {landed(overall, 'A')}, {landed(overall, 'B')}.")


def _probability(value) -> float:
    """0.63, 63 and "63%" are all 0.63."""
    number = float(str(value).strip().rstrip("%"))
    if number > 1:
        number /= 100
    if not 0 <= number <= 1:
        raise ValueError(f"Not a probability: {value!r}")
    return number


# ───────────────────────── Command line ─────────────────────────

_T_KEYS = ("t", "time", "ts", "timestamp")
_P_KEYS = ("p_A", "p_a", "prob_A", "prob_a", "pA", "win_prob_A", "win_prob_a", "A")


def _prediction(row: dict) -> tuple[float, float]:
    t = next((row[key] for key in _T_KEYS if key in row), None)
    p = next((row[key] for key in _P_KEYS if key in row), None)
    if t is None or p is None:
        raise ValueError(f"A prediction row needs a time (one of {_T_KEYS}) and A's probability (one of {_P_KEYS}); "
                         f"this one has the keys {sorted(row)}")
    return float(t), _probability(p)


def text_model(url: Optional[str] = None, model: Optional[str] = None) -> Cosmos:
    """The model that writes the words: the Cosmos endpoint, unless another one is named."""
    url = url or os.environ.get("NARRATOR_URL")
    model = model or os.environ.get("NARRATOR_MODEL")
    key = os.environ.get("NARRATOR_API_KEY")
    if url:                    # an endpoint of its own: none of the Cosmos settings apply to it
        return Cosmos(url=url, model=model or "", api_key=key or "")
    return Cosmos(model=model, api_key=key)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="The caption that goes with a win probability, from the memory of the bout")
    parser.add_argument("clip_dir", type=Path, help="the folder with memory.jsonl (the one review.py wrote into)")
    parser.add_argument("--p-a", help="A's win probability: 0.63, 63 or 63%%")
    parser.add_argument("--t", type=float, help="bout time of that number, in seconds (default: as far as the memory reaches)")
    parser.add_argument("--prev", help="the probability shown before this one")
    parser.add_argument("--prev-t", type=float, help="and its bout time")
    parser.add_argument("--predictions", type=Path, help='a .jsonl with one row per number: {"t": 31, "p_A": 0.63}')
    parser.add_argument("--notes", action="store_true", help="print what the memory holds and stop")
    parser.add_argument("--no-model", action="store_true", help="build the captions from the counts, without asking a model")
    parser.add_argument("--url", help="endpoint of the text model (default: NARRATOR_URL, else COSMOS3_REASON_URL)")
    parser.add_argument("--model", help="its model name (default: NARRATOR_MODEL, else asked from the endpoint)")
    args = parser.parse_args(argv)

    memory = Memory(args.clip_dir)
    if args.notes:
        snapshot = memory.snapshot()
        print(f"Memory reaches {clock(snapshot['until'])}: {snapshot['entries']}")
        print(counts(snapshot))
        print("Notes:", snapshot["summary"]["text"] if snapshot["summary"] else "(none yet)")
        return 0

    out = args.clip_dir / "narration.jsonl"
    if args.predictions:
        numbers = [_prediction(json.loads(row)) for row in args.predictions.read_text(encoding="utf-8").splitlines() if row.strip()]
    elif args.p_a is not None:
        numbers = [(args.t if args.t is not None else memory.snapshot()["until"], _probability(args.p_a))]
    else:
        parser.error("give --p-a, --predictions or --notes")
    prev = (args.prev_t if args.prev_t is not None else 0.0, _probability(args.prev)) if args.prev is not None else None
    if prev is None and not args.predictions:
        prev = _last_shown(out, numbers[0][0])

    cosmos = None if args.no_model else text_model(args.url, args.model)
    for t, p_a in sorted(numbers):
        row = caption(memory, p_a, t, prev, cosmos)
        row["written"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with out.open("a", encoding="utf-8") as log:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
        flag = "   [the record points the other way]" if row["consistent"] is False else ""
        print(f"{clock(t)}  A {p_a:.0%}  {row['text']}  {row['evidence']}  (by {row['by']}){flag}")
        if row.get("error"):
            print(f"       the model gave no caption: {row['error']}", file=sys.stderr)
        prev = (t, p_a)
    print(f"-> {out}")
    return 0


def _last_shown(path: Path, before: float) -> Optional[tuple[float, float]]:
    """The number of the latest caption on file for an earlier bout time."""
    if not path.exists():
        return None
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row.strip()]
    earlier = [row for row in rows if row["t"] < before]
    return (earlier[-1]["t"], earlier[-1]["p_A"]) if earlier else None


if __name__ == "__main__":
    sys.exit(main())
