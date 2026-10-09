"""Build a self-contained HTML viewer: video on top, curves drawn live below.

    python viewer.py outputs/0_realhuman            # uses measure.mp4
    python viewer.py outputs/0_realhuman --video annotated.mp4
    python viewer.py outputs/0_realhuman --end 15   # demo cut: first 15 s only

Needs measure.jsonl (measure.py) and exchange.jsonl (engage.py); shows
labels_eyeball.json as a reference strip when present. Writes <clip>/viewer.html next to the
video, so it opens straight from Finder without a web server.
"""
from pathlib import Path
import argparse
import json
import subprocess

from engage import find_cuts

ROOT = Path(__file__).resolve().parent
KEYS = ("com_dist", "reach_A", "reach_B", "ext_A", "ext_B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    ap.add_argument("--video", default="measure.mp4", help="video file inside clip_dir")
    ap.add_argument("--end", type=float, help="show only the first END seconds (trims video and data)")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    clip_dir = Path(args.clip_dir)

    rows = [json.loads(line) for line in (clip_dir / "measure.jsonl").open()]
    summary = json.loads((clip_dir / "summary.json").read_text())
    fps = summary["source_fps"]
    cuts = [round(i / fps, 3) for i in find_cuts(summary["video"], len(rows))]
    data = {"clip": clip_dir.name, "fps": fps, "cuts": cuts, "t": [r["t"] for r in rows],
            **{k: [r[k] for r in rows] for k in KEYS}}

    exchange = clip_dir / "exchange.jsonl"
    if not exchange.exists():
        raise SystemExit(f"{exchange} missing: run engage.py {clip_dir} first")
    data["engaged"] = [json.loads(line)["engaged"] for line in exchange.open()]
    labels = clip_dir / "labels_eyeball.json"
    if labels.exists():
        data["labels"] = json.loads(labels.read_text())["engaged"]

    video, out_name = args.video, "viewer.html"
    if args.end:
        keep = sum(1 for x in data["t"] if x < args.end)
        for k in ("t", "engaged") + KEYS:
            data[k] = data[k][:keep]
        data["cuts"] = [c for c in data["cuts"] if c < args.end]
        if "labels" in data:
            data["labels"] = [[a, min(b, args.end)] for a, b in data["labels"] if a < args.end]
        tag = f"0-{args.end:g}s"
        video = f"{Path(args.video).stem}_{tag}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip_dir / args.video), "-t", str(args.end),
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(clip_dir / video)],
                       check=True)
        out_name = f"viewer_{tag}.html"

    html = (ROOT / "viewer_template.html").read_text()
    html = html.replace("__VIDEO__", video).replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out = clip_dir / out_name
    out.write_text(html)
    print(out)
    if not args.no_open:
        subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()
