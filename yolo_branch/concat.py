"""Join analysed clips (each one a round) into one demo clip for viewer.py.

    python concat.py outputs/demo_ufc_local \
        "outputs/pereira_rountree_45s:0:10:UFC 300 replay:PEREIRA:ROUNTREE" \
        "outputs/0_realhuman:0:15:Local arena:BLACK KIT:WHITE KIT"

Segment spec: clip_dir:start:end:title:A name:B name. A single segment
simply trims that clip.

Each segment is analysed on its own (track.py, measure.py, engage.py) so A/B
identity and the torso scale restart at every boundary. This script trims
each segment's measure.mp4, joins them at a common frame rate, resamples the
per-frame data onto the joined timeline, and writes measure.mp4,
measure.jsonl, exchange.jsonl, summary.json, segments.json and (when the
segments have them) labels_eyeball.json into the output folder.

If a segment has win_prob.jsonl (win_prob.py), each frame gets win_A: the
latest probability for A whose one-second window had ended by that frame,
null before the round's first result. Decision times go to win_points.json.
Strikes from hits.jsonl (hits.py) are shifted onto the joined timeline in hits.json.
"""
from pathlib import Path
import argparse
import json
import subprocess

import numpy as np

from engage import find_cuts

FPS = 30.0
SIZE = (1280, 720)


def parse(spec):
    path, start, end, title, a, b = spec.split(":", 5)
    return Path(path), float(start), float(end), {"title": title, "A": a, "B": b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("segments", nargs="+", help="clip_dir:start:end:title:A name:B name")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    segs = [parse(s) for s in args.segments]

    # Video: trim, normalise size and frame rate, join.
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for clip, start, end, _ in segs:
        cmd += ["-ss", str(start), "-t", str(end - start), "-i", str(clip / "measure.mp4")]
    w, h = SIZE
    chains = [f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
              f"fps={FPS},setsar=1[v{i}]" for i in range(len(segs))]
    joined = "".join(f"[v{i}]" for i in range(len(segs)))
    cmd += ["-filter_complex", ";".join(chains) + f";{joined}concat=n={len(segs)}:v=1:a=0[v]",
            "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out / "measure.mp4")]
    subprocess.run(cmd, check=True)

    # Data: resample each segment onto the joined 30 fps grid (nearest frame).
    measure_rows, exchange_rows, segments, cuts, labels, label_ranges = [], [], [], [], [], []
    win_points, hits = [], []
    offset = 0.0
    for clip, start, end, names in segs:
        m = [json.loads(line) for line in (clip / "measure.jsonl").open()]
        x = [json.loads(line) for line in (clip / "exchange.jsonl").open()]
        src_t = np.array([r["t"] for r in m])
        n = int(round((end - start) * FPS))
        hit_file = clip / "hits.jsonl"
        if hit_file.exists():
            for line in hit_file.open():
                h = json.loads(line)
                if start <= h["t"] < end:
                    hits.append({**h, "t": round(offset + h["t"] - start, 3)})
        wp_file = clip / "win_prob.jsonl"
        wins = [json.loads(line) for line in wp_file.open()] if wp_file.exists() else []
        wins = [w for w in wins if w.get("probabilities") and start < w["end_s"] <= end]
        for w in wins:
            if w["status"] == "ok":
                win_points.append({"t": round(offset + w["end_s"] - start, 3), "A": w["probabilities"]["A"]})
        for k in range(n):
            j = int(np.argmin(np.abs(src_t - (start + k / FPS))))
            t = round(offset + k / FPS, 3)
            measure_rows.append({**m[j], "t": t})
            ready = [w for w in wins if w["end_s"] <= start + k / FPS + 1e-6]
            win_a = ready[-1]["probabilities"]["A"] if ready else None
            exchange_rows.append({"t": t, "engaged": x[j]["engaged"], "win_A": win_a})
        summary = json.loads((clip / "summary.json").read_text())
        fps = summary["source_fps"]
        cuts += [round(offset + c / fps - start, 3) for c in find_cuts(summary["video"], len(m))
                 if start < c / fps < end]
        if segments:
            cuts.append(round(offset, 3))  # the join itself is a cut
        segments.append({"start": round(offset, 3), "end": round(offset + n / FPS, 3), **names,
                         "source": clip.name, "source_start": start})
        lab = clip / "labels_eyeball.json"
        if lab.exists():
            for a, b in json.loads(lab.read_text())["engaged"]:
                if b > start and a < end:
                    labels.append([round(offset + max(a, start) - start, 3), round(offset + min(b, end) - start, 3)])
            label_ranges.append([round(offset, 3), round(offset + n / FPS, 3)])
        offset += n / FPS

    with (out / "measure.jsonl").open("w") as f:
        f.writelines(json.dumps(r) + "\n" for r in measure_rows)
    with (out / "exchange.jsonl").open("w") as f:
        f.writelines(json.dumps(r) + "\n" for r in exchange_rows)
    (out / "win_points.json").write_text(json.dumps(win_points))
    (out / "hits.json").write_text(json.dumps(hits))
    (out / "segments.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    (out / "summary.json").write_text(json.dumps(
        {"source_fps": FPS, "video": str((out / "measure.mp4").resolve()), "cuts_s": sorted(cuts)}, indent=2))
    if labels:
        (out / "labels_eyeball.json").write_text(json.dumps(
            {"source": "copied from segment labels_eyeball.json files", "engaged": labels,
             "ranges": label_ranges}, ensure_ascii=False))

    eng = np.array([r["engaged"] for r in exchange_rows])
    print(f"{out}: {len(exchange_rows)} frames, {offset:.2f}s, cuts at {sorted(cuts)}")
    for s in segments:
        m = (np.arange(len(eng)) / FPS >= s["start"]) & (np.arange(len(eng)) / FPS < s["end"])
        print(f"  {s['start']:5.2f}-{s['end']:5.2f}s  {s['title']} ({s['A']} vs {s['B']}): engaged {eng[m].mean() * 100:.0f}% of frames")


if __name__ == "__main__":
    main()
