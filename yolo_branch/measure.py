"""Measure the distance between A and B: centre of gravity and arms.

    python measure.py outputs/0_realhuman

Per frame (all lengths divided by the two fighters' mean torso length, so the
numbers do not change when the camera zooms):
  com_dist   distance between the two centres of gravity
             (centre of gravity ~ mean of both shoulders and both hips)
  reach_A    distance from A's closer wrist to B's nearest target (head or torso centre)
  reach_B    the same for B's wrist to A
  ext_A/B    arm extension of the more extended arm: wrist-shoulder distance divided
             by upper-arm + forearm length (1.0 = fully straight)

Writes measure.jsonl, measure.png and measure.mp4 (annotated.mp4 with the
distances drawn on) into the clip folder.
"""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import warnings

import cv2
import numpy as np

warnings.filterwarnings("ignore", "All-NaN slice")

from engage import SMOOTH_FRAMES, find_cuts, interp_short, load, trailing_mean

SHOULDERS, ELBOWS, WRISTS, HIPS, NOSE = (5, 6), (7, 8), (9, 10), (11, 12), 0
COLORS = {"A": (0, 180, 255), "B": (255, 160, 30)}  # BGR, same as track.py
COM_COLOR = (80, 255, 80)


def point_mean(kp, idx):
    with np.errstate(invalid="ignore"):
        return np.nanmean(kp[..., list(idx), :], axis=-2)


def measure(kp, fps, cuts):
    n = len(kp)
    com = point_mean(kp, SHOULDERS + HIPS)                     # (n, 2, 2)
    torso_c = com
    torso_len = np.linalg.norm(point_mean(kp, SHOULDERS) - point_mean(kp, HIPS), axis=-1)
    scale = np.nanmedian(np.where(np.isnan(torso_len), np.nan, torso_len), axis=1)
    scale = trailing_mean(interp_short(scale, fps), int(fps))   # steady scale over ~1 s

    out = {"com_dist": np.linalg.norm(com[:, 0] - com[:, 1], axis=-1) / scale}
    best_pair = np.full((n, 2, 2, 2), np.nan)                   # wrist -> target segment per fighter
    for me, opp, name in ((0, 1, "A"), (1, 0, "B")):
        targets = np.stack([kp[:, opp, NOSE], torso_c[:, opp]], axis=1)          # (n, 2, 2)
        wrists = kp[:, me, list(WRISTS)]                                          # (n, 2, 2)
        dist = np.linalg.norm(wrists[:, :, None] - targets[:, None], axis=-1)   # (n, wrist, target)
        flat = np.where(np.isnan(dist), np.inf, dist).reshape(n, -1)
        k = flat.argmin(axis=1)
        reach = flat[np.arange(n), k]
        reach[np.isinf(reach)] = np.nan
        out[f"reach_{name}"] = reach / scale
        wi, ti = k // 2, k % 2
        best_pair[:, me, 0] = wrists[np.arange(n), wi]
        best_pair[:, me, 1] = targets[np.arange(n), ti]

        arm_len = (np.linalg.norm(kp[:, me, list(SHOULDERS)] - kp[:, me, list(ELBOWS)], axis=-1)
                   + np.linalg.norm(kp[:, me, list(ELBOWS)] - kp[:, me, list(WRISTS)], axis=-1))
        straight = np.linalg.norm(kp[:, me, list(SHOULDERS)] - kp[:, me, list(WRISTS)], axis=-1)
        with np.errstate(invalid="ignore", divide="ignore"):
            ext = np.nanmax(np.where(arm_len > 0, straight / arm_len, np.nan), axis=1)
        out[f"ext_{name}"] = ext

    for key in out:  # same light smoothing as engage.py, no smoothing across cuts
        x = out[key].copy()
        for c in cuts:
            x[max(0, c - 1):c + 1] = np.nan
        out[key] = trailing_mean(interp_short(x, fps), SMOOTH_FRAMES)
    return out, com, best_pair


def plot(t, m, cuts, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    a_col, b_col = "#ffb400", "#1ea0ff"
    fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(t, m["com_dist"], color="#2a9d2a", lw=1.5)
    axes[0].set_ylabel("centre of gravity\ndistance (torso)")
    axes[1].plot(t, m["reach_A"], color=a_col, lw=1.3, label="A wrist → B")
    axes[1].plot(t, m["reach_B"], color=b_col, lw=1.3, label="B wrist → A")
    axes[1].set_ylabel("wrist to opponent\nhead/torso (torso)")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[2].plot(t, m["ext_A"], color=a_col, lw=1.3, label="A")
    axes[2].plot(t, m["ext_B"], color=b_col, lw=1.3, label="B")
    axes[2].axhline(0.9, color="#666", ls="--", lw=0.8)
    axes[2].set_ylabel("arm extension\n(1 = straight)")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("video time (s)")
    for ax in axes:
        for c in cuts:
            ax.axvline(t[c], color="#7a3cff", lw=1)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def overlay(clip_dir, m, com, pairs):
    src = clip_dir / "annotated.mp4"
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = clip_dir / "measure.mp4"
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    proc = subprocess.Popen([ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
                             "-pix_fmt", "yuv420p", "-crf", "20", str(out)], stdin=subprocess.PIPE)
    pt = lambda p: (int(p[0]), int(p[1]))
    for i in range(len(com)):
        ok, frame = cap.read()
        if not ok:
            break
        ca, cb = com[i, 0], com[i, 1]
        if not (np.isnan(ca).any() or np.isnan(cb).any()):
            cv2.line(frame, pt(ca), pt(cb), COM_COLOR, 2)
            for c in (ca, cb):
                cv2.circle(frame, pt(c), 9, COM_COLOR, -1)
                cv2.circle(frame, pt(c), 9, (0, 0, 0), 2)
            mid = (ca + cb) / 2
            cv2.putText(frame, f"{m['com_dist'][i]:.2f}", (int(mid[0]) - 25, int(mid[1]) - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(frame, f"{m['com_dist'][i]:.2f}", (int(mid[0]) - 25, int(mid[1]) - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, COM_COLOR, 2)
        for f, idx in (("A", 0), ("B", 1)):
            w, tgt = pairs[i, idx]
            if not (np.isnan(w).any() or np.isnan(tgt).any()):
                cv2.line(frame, pt(w), pt(tgt), COLORS[f], 2, cv2.LINE_AA)
                cv2.circle(frame, pt(w), 7, COLORS[f], -1)
        lines = [("COG dist", m["com_dist"][i], COM_COLOR),
                 ("A reach", m["reach_A"][i], COLORS["A"]), ("B reach", m["reach_B"][i], COLORS["B"]),
                 ("A arm ext", m["ext_A"][i], COLORS["A"]), ("B arm ext", m["ext_B"][i], COLORS["B"])]
        cv2.rectangle(frame, (W - 270, 10), (W - 10, 20 + 32 * len(lines)), (0, 0, 0), -1)
        for j, (label, v, col) in enumerate(lines):
            text = f"{label:10s} {v:5.2f}" if not np.isnan(v) else f"{label:10s}   -"
            cv2.putText(frame, text, (W - 260, 42 + 32 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    clip_dir = Path(args.clip_dir)
    t, kp = load(clip_dir / "keypoints.jsonl")
    summary = json.loads((clip_dir / "summary.json").read_text())
    fps = summary.get("source_fps", 1 / np.median(np.diff(t)))
    cuts = find_cuts(summary["video"], len(t))

    m, com, pairs = measure(kp, fps, cuts)
    with (clip_dir / "measure.jsonl").open("w") as f:
        for i in range(len(t)):
            f.write(json.dumps({"t": round(float(t[i]), 3),
                                **{k: (None if np.isnan(v[i]) else round(float(v[i]), 3)) for k, v in m.items()}}) + "\n")
    plot(t, m, cuts, clip_dir / "measure.png")
    video = overlay(clip_dir, m, com, pairs)

    def stat(k):
        x = m[k][~np.isnan(m[k])]
        return f"min {x.min():.2f} / median {np.median(x):.2f} / max {x.max():.2f}"
    print(f"{clip_dir.name}: {len(t)} frames, camera cuts: {len(cuts)}")
    for k in m:
        print(f"  {k:9s} {stat(k)}")
    if not args.no_open:
        subprocess.run(["open", str(clip_dir / "measure.png"), str(video)])


if __name__ == "__main__":
    main()
