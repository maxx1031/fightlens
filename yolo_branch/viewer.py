"""Publish an analysed clip to the arcade demo (examples/arcade).

    python viewer.py outputs/demo_ufc_local

Writes into the arcade folder:
  data.js        per-frame data shared by index.html (audience HUD) and analysis.html
  analysis.html  curves drawn live under the video (from viewer_template.html)
  measure.mp4    the clip's video with pose overlays

Needs measure.mp4, measure.jsonl and exchange.jsonl in the clip folder
(concat.py produces them), plus summary.json for the frame rate and cuts.
segments.json, labels_eyeball.json, win_points.json and hits.json are used when present;
win_A comes from exchange.jsonl (null where no win probability exists).
"""
from pathlib import Path
import argparse
import json
import shutil
import subprocess

from engage import find_cuts

ROOT = Path(__file__).resolve().parent
ARCADE = ROOT.parent / "examples" / "arcade"
KEYS = ("com_dist", "reach_A", "reach_B", "ext_A", "ext_B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    ap.add_argument("--out", default=str(ARCADE), help="arcade folder to write into")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    clip_dir, out = Path(args.clip_dir), Path(args.out)

    rows = [json.loads(line) for line in (clip_dir / "measure.jsonl").open()]
    summary = json.loads((clip_dir / "summary.json").read_text())
    fps = summary["source_fps"]
    end = rows[-1]["t"] + 1 / fps
    data = {"clip": clip_dir.name, "fps": fps,
            "cuts": summary.get("cuts_s") or [round(i / fps, 3) for i in find_cuts(summary["video"], len(rows))],
            "t": [r["t"] for r in rows], **{k: [r[k] for r in rows] for k in KEYS},
            "engaged": [], "win_A": []}
    for line in (clip_dir / "exchange.jsonl").open():
        r = json.loads(line)
        data["engaged"].append(r["engaged"])
        data["win_A"].append(r.get("win_A"))
    points = clip_dir / "win_points.json"
    data["win_points"] = json.loads(points.read_text()) if points.exists() else []
    hits = clip_dir / "hits.json"
    data["hits"] = json.loads(hits.read_text()) if hits.exists() else []

    seg_file = clip_dir / "segments.json"
    data["segments"] = (json.loads(seg_file.read_text()) if seg_file.exists()
                        else [{"start": 0, "end": end, "title": clip_dir.name, "A": "A", "B": "B"}])
    labels = clip_dir / "labels_eyeball.json"
    if labels.exists():
        lab = json.loads(labels.read_text())
        data["labels"] = lab["engaged"]
        data["label_ranges"] = lab.get("ranges") or [[0, end]]

    out.mkdir(parents=True, exist_ok=True)
    (out / "data.js").write_text("const DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    shutil.copyfile(ROOT / "viewer_template.html", out / "analysis.html")
    shutil.copyfile(clip_dir / "measure.mp4", out / "measure.mp4")
    print(f"{out}: data.js, analysis.html, measure.mp4 ({len(rows)} frames, {end:.2f}s)")
    if not args.no_open and (out / "index.html").exists():
        subprocess.run(["open", str(out / "index.html")])


if __name__ == "__main__":
    main()
