"""Strike contact candidates by body zone, for the received-strike heatmap.

    python hits.py outputs/0_realhuman

From track.py keypoints and measure.py arm extension:
  punch  an arm-extension episode (ext >= EXT_PUNCH); at the frame where the
         wrist is closest to the opponent, the nearer of head / body is the zone
  kick   a peak of ankle speed relative to the kicker's own hips (>= W_KICK);
         within +-KICK_WINDOW_S the nearest of leg / body / head is the zone
A strike counts as a contact candidate when that distance is below CONTACT
torso lengths. This is 2D image geometry: overlap on screen does not prove
contact, and nothing here is verified by a video model.

Writes <clip>/hits.jsonl, one strike per line (contact true or false).
"""
from pathlib import Path
import argparse
import json
import warnings

import numpy as np

from engage import find_cuts, guard, interp_short, load, torso_scale, trailing_mean

warnings.filterwarnings("ignore", "Mean of empty slice")
warnings.filterwarnings("ignore", "All-NaN slice")

EXT_PUNCH = 0.85       # arm extension that starts a punch episode
W_KICK = 7.0           # ankle speed peak (torso lengths / s) that counts as a kick
KICK_WINDOW_S = 0.2    # search window around a kick peak for the closest approach
KICK_DEDUP_S = 0.5     # kick peaks closer than this from the same fighter are one kick
CONTACT = 0.6          # limb-to-zone distance (torso lengths) that counts as contact

HEAD, SHOULDERS, HIPS, KNEES = (0, 1, 2, 3, 4), (5, 6), (11, 12), (13, 14)
WRISTS, ANKLES = (9, 10), (15, 16)


def point_mean(x, idx):
    return np.nanmean(x[..., list(idx), :], axis=-2)


def nearest(points, target, scale):
    """Per frame: smallest distance from any of `points` to `target`, in torso lengths."""
    d = np.linalg.norm(points - target[:, None], axis=-1)
    return np.nanmin(np.where(np.isnan(d), np.inf, d), axis=1) / scale


def strikes(t, kp, ext, scale, fps, cuts, me, opp):
    zones = {"head": point_mean(kp[:, opp], HEAD),
             "body": (point_mean(kp[:, opp], SHOULDERS) + point_mean(kp[:, opp], HIPS)) / 2,
             "leg": (point_mean(kp[:, opp], HIPS) + point_mean(kp[:, opp], KNEES)) / 2}
    wrist = {z: nearest(kp[:, me, list(WRISTS)], zones[z], scale) for z in ("head", "body")}
    ankle = {z: nearest(kp[:, me, list(ANKLES)], zones[z], scale) for z in ("leg", "body", "head")}
    out = []

    on = np.nan_to_num(ext) >= EXT_PUNCH
    i = 0
    while i < len(t):
        if not on[i]:
            i += 1
            continue
        j = i
        while j < len(t) and on[j]:
            j += 1
        k = min(range(i, j), key=lambda q: min(wrist["head"][q], wrist["body"][q]))
        zone = min(wrist, key=lambda z: wrist[z][k])
        out.append((k, "punch", zone, wrist[zone][k]))
        i = j

    hips = point_mean(kp[:, me], HIPS)
    rel = kp[:, me, list(ANKLES)] - hips[:, None]
    speed = np.full(len(t), np.nan)
    speed[1:] = np.nanmax(np.linalg.norm(np.diff(rel, axis=0), axis=-1), axis=1) * fps / scale[1:]
    speed = trailing_mean(interp_short(guard(speed, cuts), fps), 3)
    half = max(1, int(KICK_WINDOW_S * fps))
    kicks = []
    for q in range(1, len(t) - 1):
        if not (speed[q] >= W_KICK and speed[q] >= speed[q - 1] and speed[q] >= speed[q + 1]):
            continue
        k = min(range(max(0, q - half), min(len(t), q + half + 1)), key=lambda r: min(a[r] for a in ankle.values()))
        zone = min(ankle, key=lambda z: ankle[z][k])
        if kicks and t[k] - t[kicks[-1][0]] < KICK_DEDUP_S:  # same kick: keep the closer approach
            if ankle[zone][k] < kicks[-1][3]:
                kicks[-1] = (k, "kick", zone, ankle[zone][k])
            continue
        kicks.append((k, "kick", zone, ankle[zone][k]))
    return sorted(out + kicks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    args = ap.parse_args()
    clip_dir = Path(args.clip_dir)
    t, kp = load(clip_dir / "keypoints.jsonl")
    summary = json.loads((clip_dir / "summary.json").read_text())
    fps = summary["source_fps"]
    cuts = find_cuts(summary["video"], len(t))
    torso = np.nanmean(np.linalg.norm(point_mean(kp, SHOULDERS) - point_mean(kp, HIPS), axis=-1), axis=1)
    scale = torso_scale(torso, fps, cuts)
    m = [json.loads(line) for line in (clip_dir / "measure.jsonl").open()]

    rows = []
    for me, opp, a, b in ((0, 1, "A", "B"), (1, 0, "B", "A")):
        ext = np.array([np.nan if r[f"ext_{a}"] is None else r[f"ext_{a}"] for r in m])
        for k, limb, zone, dist in strikes(t, kp, ext, scale, fps, cuts, me, opp):
            if np.isfinite(dist):
                rows.append({"t": round(float(t[k]), 3), "attacker": a, "defender": b, "limb": limb,
                             "zone": zone, "dist": round(float(dist), 3), "contact": bool(dist < CONTACT)})
    rows.sort(key=lambda r: r["t"])
    with (clip_dir / "hits.jsonl").open("w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    hit = [r for r in rows if r["contact"]]
    print(f"{clip_dir.name}: {len(rows)} strikes, {len(hit)} contact candidates")
    for r in rows:
        print(f"  {r['t']:6.2f}s {r['attacker']}->{r['defender']} {r['limb']:5s} {r['zone']:4s} "
              f"{r['dist']:.2f} {'CONTACT' if r['contact'] else 'miss'}")


if __name__ == "__main__":
    main()
