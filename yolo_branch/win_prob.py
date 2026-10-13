"""Per-second win probability, sampled only while YOLO says the fighters are engaged.

    python win_prob.py outputs/0_realhuman --fighter-map '{"A":"black hoodie and cap","B":"white jacket"}'
    python win_prob.py outputs/0_realhuman --fighter-map ... --max-seconds 1   # one-call smoke test
    python win_prob.py outputs/0_realhuman --fighter-map ... --plan            # which seconds would be sent

For each one-second window of the source video, reads YOLO's engaged 0/1 from
<clip>/exchange.jsonl. Windows where at least --min-engaged of the frames are
engaged get --fps frames sent to OpenRouter Decisions (scripts/openrouter_win_probability.py);
other windows are not sampled and carry the previous probability forward.
Each sampled second is asked twice, with A/B listed in both orders, and the two
answers are averaged: the model strongly prefers whichever fighter is listed
first, and averaging cancels that preference. Raw answers are kept in the record.
If <clip>/referee.jsonl (referee.py) exists, every request also carries
cosmos_referee: the NVIDIA Cosmos Reason verdicts that had arrived by the end of
that second (clip end + Cosmos latency), as a per-fighter tally of landed / blocked /
missed strikes, each strike's move / target / outcome and the latest one-sentence notes.
--no-cosmos turns this off. With --baseline (a frames-only win_prob file of the same
clip), seconds before any Cosmos verdict has arrived are copied from it instead of asked
again: the request would be identical, so the two runs only differ once Cosmos speaks.
Writes <clip>/win_prob.jsonl, one line per second. Needs OPENROUTER_API_KEY in
the repository's .env or the shell. The probabilities are uncalibrated model estimates.
"""
from pathlib import Path
import argparse
import json
import math
import os
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from cosmos_video_understanding import build_windows, extract_frames, parse_fighter_map  # noqa: E402
from openrouter_win_probability import (  # noqa: E402
    DEFAULT_API_URL, DEFAULT_DECISION_PROMPT, OpenRouterDecisionClient,
    build_decision_payload, parse_winner_probabilities,
)

DEFAULT_MODEL = "openai/gpt-6-luna-decisions"
MIN_ENGAGED = 0.5   # fraction of engaged frames in a second that triggers a decision
DENSE_FPS = 10      # frames sent per engaged second
RECENT_NOTES = 3    # latest Cosmos notes passed along with the tally
RECENT_STRIKES = 12 # latest individual strikes (move, target, outcome)
COSMOS_PROMPT = DEFAULT_DECISION_PROMPT + """

cosmos_referee 是 NVIDIA Cosmos Reason 对此前已结束交锋片段的逐击判定（出手方、动作、目标、击中/被挡/落空），
只包含当前时刻之前已经返回的结果。strike_log 给出每一击的动作与目标：不同技术的效果不同，例如击中腿部的低扫会累积伤害并影响移动，
推踢主要用于控制距离、伤害有限，击中头部比击中身体更危险。它比单帧画面更可靠：被挡或落空的出手不算有效进攻，确认击中才算；
画面与 cosmos_referee 冲突时以 cosmos_referee 为准。cosmos_referee 为 null 时只依据画面判断。"""


def read_api_key():
    """OPENROUTER_API_KEY from the shell, else from the repository's .env.

    scripts/cosmos_video_understanding.load_env_file only loads Cosmos keys, so read it here.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    env = REPO / ".env"
    if not key and env.is_file():
        for line in env.read_text().splitlines():
            name, _, value = line.strip().removeprefix("export ").partition("=")
            if name.strip() == "OPENROUTER_API_KEY":
                key = value.strip().strip("'\"")
    return key


def load_reviews(clip_dir):
    path = clip_dir / "referee.jsonl"
    return [json.loads(line) for line in path.open()] if path.is_file() else []


def cosmos_evidence(reviews, now, swap=False):
    """Cosmos verdicts available at time `now`, with A/B swapped when the fighters are listed swapped."""
    flip = {"A": "B", "B": "A"} if swap else {"A": "A", "B": "B"}
    done = [r for r in reviews if r.get("cosmos") and r["t1"] + r["cosmos"].get("latency_s", 0) <= now]
    if not done:
        return None
    tally = {f: {"landed": 0, "blocked": 0, "missed": 0} for f in ("A", "B")}
    log = []  # what was thrown and where, not just how many: a landed kick to the leg is not a blocked jab
    # Kick clips (referee.py) cover a kick densely inside a longer exchange clip: count kicks from
    # the kick clip and everything else from the exchange clip, so nothing is counted twice. A kick
    # clip that saw no kick replaces nothing.
    is_kick = lambda st: "kick" in (st.get("move") or "").lower()
    kick_spans = [(r["t0"], r["t1"]) for r in done
                  if r.get("kind") == "kick" and any(is_kick(st) for st in r["cosmos"].get("strikes", []))]
    for r in done:
        kick_clip = r.get("kind") == "kick"
        has_kick_clip = any(a < r["t1"] and r["t0"] < b for a, b in kick_spans)
        for st in r["cosmos"].get("strikes", []):
            kick = is_kick(st)
            if (kick_clip and not kick) or (not kick_clip and kick and has_kick_clip):
                continue
            if st.get("attacker") in flip and st.get("outcome") in tally["A"]:
                tally[flip[st["attacker"]]][st["outcome"]] += 1
                log.append({"t": st.get("t"), "attacker": flip[st["attacker"]], "move": st.get("move"),
                            "target": st.get("target"), "outcome": st["outcome"]})
    notes = [{"start_s": r["t0"], "end_s": r["t1"], "note": r["cosmos"].get("note", "")} for r in done[-RECENT_NOTES:]]
    if swap:  # notes say "fighter A"/"fighter B" in prose; mark the relabelling instead of rewriting text
        notes = [{**n, "labels_in_note": "A means B and B means A"} for n in notes]
    return {"source": "NVIDIA Cosmos Reason", "clips_reviewed": len(done), "strikes": tally,
            "strike_log": log[-RECENT_STRIKES:], "recent_notes": notes}


def engaged_fractions(clip_dir, seconds):
    rows = [json.loads(line) for line in (clip_dir / "exchange.jsonl").open()]
    out = []
    for k in range(seconds):
        inside = [r["engaged"] for r in rows if k <= r["t"] < k + 1]
        out.append(sum(inside) / len(inside) if inside else 0.0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    ap.add_argument("--fighter-map", required=True, help="JSON with keys A and B (appearance, not names)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-engaged", type=float, default=MIN_ENGAGED)
    ap.add_argument("--fps", type=int, default=DENSE_FPS)
    ap.add_argument("--max-seconds", type=int, help="only look at the first N seconds")
    ap.add_argument("--no-cosmos", action="store_true", help="do not pass Cosmos verdicts to the model")
    ap.add_argument("--baseline", help="frames-only win_prob.jsonl to reuse before the first Cosmos verdict")
    ap.add_argument("--plan", action="store_true", help="print which seconds would be sent, without calling")
    args = ap.parse_args()
    clip_dir = Path(args.clip_dir)

    fighter_map = parse_fighter_map(args.fighter_map)
    summary = json.loads((clip_dir / "summary.json").read_text())
    video = Path(summary["video"])
    n_rows = sum(1 for _ in (clip_dir / "exchange.jsonl").open())
    seconds = math.floor(n_rows / summary["source_fps"] + 1e-6)
    if args.max_seconds:
        seconds = min(seconds, args.max_seconds)
    fractions = engaged_fractions(clip_dir, seconds)
    sent = [k for k in range(seconds) if fractions[k] >= args.min_engaged]
    reviews = [] if args.no_cosmos else load_reviews(clip_dir)
    if args.plan:
        print(" ".join(f"{k}s:{'SEND' if k in sent else 'hold'}"
                       + (f"+cosmos{cosmos_evidence(reviews, k + 1)['clips_reviewed']}" if k in sent and cosmos_evidence(reviews, k + 1) else "")
                       for k in range(seconds)))
        print(f"{len(sent)} of {seconds} seconds sent, {len(sent) * args.fps} frames")
        return

    api_key = read_api_key()
    if not api_key:
        raise SystemExit(f"OPENROUTER_API_KEY missing: add it to {REPO / '.env'}")

    client = OpenRouterDecisionClient(DEFAULT_API_URL, api_key)
    baseline = {}
    if args.baseline:
        baseline = {int(r["start_s"]): r for r in map(json.loads, Path(args.baseline).open()) if r["status"] == "ok"}
    swapped_map = {"A": fighter_map["B"], "B": fighter_map["A"]}

    def ask(window, fmap, prev, cosmos):
        payload = build_decision_payload(args.model, window, fighter_map=fmap, previous_state=prev,
                                         decision_prompt=COSMOS_PROMPT if reviews else DEFAULT_DECISION_PROMPT,
                                         image_detail="low")
        if reviews:  # state[0] is the JSON context; add the Cosmos verdicts next to previous_state
            payload["state"][0] = json.dumps({**json.loads(payload["state"][0]), "cosmos_referee": cosmos},
                                             ensure_ascii=False, separators=(",", ":"))
        return parse_winner_probabilities(client.submit(payload))

    previous, calls, out_path = None, 0, clip_dir / "win_prob.jsonl"
    with out_path.open("w") as out, tempfile.TemporaryDirectory(prefix="fightlens-winprob-") as tmp:
        for k in range(seconds):
            record = {"start_s": float(k), "end_s": float(k + 1), "engaged_frac": round(fractions[k], 3),
                      "model": args.model, "fighter_map": fighter_map}
            if fractions[k] < args.min_engaged:
                record.update(status="held", probabilities=previous and previous["probabilities"])
            else:
                frames = extract_frames(video, Path(tmp) / f"s{k}", start_second=k, window_count=1,
                                        fps=args.fps, max_width=768, jpeg_quality=3)
                window = build_windows(frames, start_second=k, fps=args.fps)[0]
                # Ask twice with A/B swapped and average: cancels the model's preference for the
                # first-listed label. Both calls see the same debiased previous state.
                prev_swapped = previous and {**previous, "probabilities": {
                    "A": previous["probabilities"]["B"], "B": previous["probabilities"]["A"]}}
                cosmos = cosmos_evidence(reviews, k + 1)
                if cosmos:
                    record["cosmos_referee"] = cosmos
                elif k in baseline:  # same frames, no Cosmos yet: identical request, reuse the answer
                    probs = baseline[k]["probabilities"]
                    previous = {"window_index": k, "start_s": float(k), "end_s": float(k + 1), "probabilities": probs}
                    record.update(status="ok", source="baseline (no Cosmos verdict yet)", probabilities=probs)
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(f"{k:3d}s engaged {fractions[k]:.2f}  reuse  A {probs['A']:.2f} / B {probs['B']:.2f}", flush=True)
                    continue
                started = time.monotonic()
                try:
                    listed = ask(window, fighter_map, previous, cosmos)
                    swapped = ask(window, swapped_map, prev_swapped, cosmos_evidence(reviews, k + 1, swap=True))
                except Exception as exc:  # keep going; a failed second carries the previous value
                    record.update(status="error", error=str(exc).replace(api_key, "***"),
                                  probabilities=previous and previous["probabilities"])
                else:
                    pa = round((listed["probabilities"]["A"] + swapped["probabilities"]["B"]) / 2, 4)
                    probs = {"A": pa, "B": round(1 - pa, 4)}
                    previous = {"window_index": k, "start_s": float(k), "end_s": float(k + 1), "probabilities": probs}
                    record.update(status="ok", latency_s=round(time.monotonic() - started, 3), frames=args.fps,
                                  probabilities=probs, raw_as_listed=listed["probabilities"],
                                  raw_swapped=swapped["probabilities"],
                                  first_label_bias=round((listed["probabilities"]["A"] + swapped["probabilities"]["A"]) / 2 - 0.5, 4))
                calls += 2
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            p = record.get("probabilities")
            shown = f"A {p['A']:.2f} / B {p['B']:.2f}" if p else "—"
            extra = (f"  raw A-first {record['raw_as_listed']['A']:.2f}, swapped A-first {record['raw_swapped']['A']:.2f}"
                     if "raw_as_listed" in record else "")
            print(f"{k:3d}s engaged {fractions[k]:.2f}  {record['status']:5s}  {shown}{extra}"
                  + (f"  {record['error']}" if "error" in record else ""), flush=True)
    print(f"{out_path}: {calls} calls over {seconds} seconds ({args.model})")

if __name__ == "__main__":
    main()
