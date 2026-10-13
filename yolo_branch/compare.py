"""Data for the side-by-side win-probability page (examples/arcade/compare.html).

    python compare.py outputs/0_realhuman --end 15 --video measure.mp4 --offset 10 \
        --names "BLACK KIT" "WHITE KIT" --title "SPARRING · ROUND 1"

Left: win_prob.frames_only.jsonl (Luna sees frames only). Right: win_prob.jsonl
(Luna sees the same frames plus the NVIDIA Cosmos verdicts, win_prob.py). Both are
step functions that change only when an engaged second ends. Cosmos verdicts from
referee.jsonl appear at clip end + Cosmos latency, as they would live; a kick clip shows
only its kicks and is left out when it saw none, as win_prob.py counts them. --video and
--offset point the page at a video already in examples/arcade (the joined demo,
where this clip starts at --offset seconds).
"""
from pathlib import Path
import argparse
import json

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "examples" / "arcade" / "compare_data.js"


def steps(path, start, end):
    rows = [json.loads(line) for line in path.open()]
    return [{"t": round(r["end_s"] - start, 3), "A": r["probabilities"]["A"]}
            for r in rows if r["status"] == "ok" and start < r["end_s"] <= end]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--video", required=True, help="video file name inside examples/arcade")
    ap.add_argument("--offset", type=float, default=0.0, help="where --start sits in that video")
    ap.add_argument("--names", nargs=2, default=["FIGHTER A", "FIGHTER B"])
    ap.add_argument("--title", default="", help="header line, e.g. the bout and round")
    args = ap.parse_args()
    clip = Path(args.clip_dir)

    verdicts = []
    for line in (clip / "referee.jsonl").open():
        r = json.loads(line)
        if r.get("kind") == "kick" and r.get("cosmos"):  # as win_prob.py counts them: only the kicks
            r["cosmos"]["strikes"] = [st for st in r["cosmos"].get("strikes", []) if "kick" in (st.get("move") or "").lower()]
            if not r["cosmos"]["strikes"]:
                continue
        if r.get("cosmos") and args.start <= r["t0"] < args.end:
            ready = min(r["t1"], args.end) + (r["cosmos"].get("latency_s") or 0) - args.start
            verdicts.append({"t0": round(r["t0"] - args.start, 3), "t1": round(min(r["t1"], args.end) - args.start, 3),
                             "kind": r.get("kind", "exchange"),
                             "available": round(ready, 3), "note": r["cosmos"].get("note", ""),
                             "strikes": [{k: s.get(k) for k in ("attacker", "move", "target", "outcome")}
                                         for s in r["cosmos"].get("strikes", [])]})
    data = {"video": args.video, "offset": args.offset, "duration": args.end - args.start,
            "names": {"A": args.names[0], "B": args.names[1]}, "title": args.title,
            "frames_only": steps(clip / "win_prob.frames_only.jsonl", args.start, args.end),
            "with_cosmos": steps(clip / "win_prob.jsonl", args.start, args.end),
            "verdicts": verdicts}
    OUT.write_text("const CMP = " + json.dumps(data, ensure_ascii=False) + ";\n")
    print(f"{OUT}: {len(data['frames_only'])} / {len(data['with_cosmos'])} updates, {len(verdicts)} Cosmos verdicts")


if __name__ == "__main__":
    main()
