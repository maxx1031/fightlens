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
    if args.plan:
        print(" ".join(f"{k}s:{'SEND' if k in sent else 'hold'}" for k in range(seconds)))
        print(f"{len(sent)} of {seconds} seconds sent, {len(sent) * args.fps} frames")
        return

    api_key = read_api_key()
    if not api_key:
        raise SystemExit(f"OPENROUTER_API_KEY missing: add it to {REPO / '.env'}")

    client = OpenRouterDecisionClient(DEFAULT_API_URL, api_key)
    swapped_map = {"A": fighter_map["B"], "B": fighter_map["A"]}

    def ask(window, fmap, prev):
        payload = build_decision_payload(args.model, window, fighter_map=fmap, previous_state=prev,
                                         decision_prompt=DEFAULT_DECISION_PROMPT, image_detail="low")
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
                started = time.monotonic()
                try:
                    listed = ask(window, fighter_map, previous)
                    swapped = ask(window, swapped_map, prev_swapped)
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
