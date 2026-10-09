"""Engagement state machine: decide where Cosmos should look, and how densely.

    python engage.py outputs/pereira_rountree_45s

Reads <clip>/keypoints.jsonl (track.py) and writes, in the same folder:
exchange.jsonl (per frame: engaged 0/1), windows.jsonl (Cosmos frame-sampling
windows) and engage.png (signals with state background, for tuning).

ENGAGE (engaged = 1) means someone is attacking -- an arm extends or a limb
moves fast -- while the two are within striking range, or they are clinched.
Standing close in guard without attacking is RANGE (engaged = 0).
All signals are causal (trailing smoothing) so the same logic can run live.
"""
from pathlib import Path
import argparse
import json
import os

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))

import warnings

import cv2
import numpy as np

warnings.filterwarnings("ignore", "Mean of empty slice")

# Signals. All distances are divided by the two fighters' mean torso length.
SMOOTH_FRAMES = 5           # trailing moving average for d, d_dot, w
KPT_CONF = 0.3              # keypoints below this confidence are ignored
MAX_INTERP_GAP_S = 0.2      # gaps up to this long are interpolated, longer ones stay missing
TORSO_WINDOW_S = 1.0        # trailing median of torso length (stabilises the scale)
CUT_HIST_CORR = 0.8         # consecutive-frame HSV histogram correlation below this = camera cut
CUT_GUARD_FRAMES = 3        # frames on each side of a cut excluded from d and w

# ENGAGE: an attack within striking range. Tuned on 0_realhuman against
# hand labels at 0.5 s resolution; re-check on other footage.
D_ATTACK_RANGE = 2.2        # hip-midpoint distance (torso lengths) within which an attack can land
D_CLINCH = 0.9              # closer than this is engaged even without limb motion
EXT_ATTACK = 0.85           # arm extension: wrist-shoulder / (upper arm + forearm); 1 = straight
W_ATTACK = 6.5              # max wrist/ankle speed rel. to own hips, torso lengths / s
ENGAGE_HOLD_S = 1.0         # attacks closer together than this belong to one exchange
EXCHANGE_PAD_S = 0.25       # engaged = 1 this long before the first / after the last attack

# RANGE / FAR hysteresis: enter / exit.
D_RANGE_IN, D_RANGE_OUT = 2.6, 3.1
DDOT_RANGE_IN, DDOT_RANGE_OUT = -1.5, -0.7  # approach speed, torso lengths / s (negative = closing)
MIN_STATE_S = 0.2           # a state must hold this long before it can be left

# Windows. Cosmos windows extend each exchange by a further ENGAGE_PAD_S,
# i.e. 0.5 s beyond the first and last attack.
ENGAGE_PAD_S = 0.25
ENGAGE_MAX_S = 2.0
SAMPLE_FPS = {"FAR": 0.5, "RANGE": 4.0}     # ENGAGE uses the source frame rate
STATE_COLORS = {"FAR": "#d9e6f2", "RANGE": "#ffe3a3", "ENGAGE": "#ffb3b3", "MISSING": "#dddddd"}
LIMBS = (9, 10, 15, 16)     # wrists, ankles
ARMS = ((5, 7, 9), (6, 8, 10))  # shoulder, elbow, wrist


def load(path):
    rows = [json.loads(line) for line in path.open()]
    t = np.array([r["t"] for r in rows])
    kp = np.full((len(rows), 2, 17, 2), np.nan)
    for i, r in enumerate(rows):
        for j, f in enumerate("AB"):
            d = r.get(f)
            if not d or d.get("status") != "tracked" or d.get("xy") is None:
                continue
            xy, conf = np.array(d["xy"], float), np.array(d["conf"], float)
            xy[conf < KPT_CONF] = np.nan
            kp[i, j] = xy
    return t, kp


def mid(kp, a, b):
    return np.nanmean(np.stack([kp[..., a, :], kp[..., b, :]]), axis=0)


def interp_short(x, fps):
    """Linearly fill NaN runs no longer than MAX_INTERP_GAP_S."""
    x = x.copy()
    bad = np.isnan(x)
    if bad.all():
        return x
    idx = np.arange(len(x))
    filled = np.interp(idx, idx[~bad], x[~bad])
    run_start = None
    for i in range(len(x) + 1):
        if i < len(x) and bad[i]:
            run_start = i if run_start is None else run_start
        elif run_start is not None:
            inner = run_start > 0 and i < len(x)
            if inner and (i - run_start) / fps <= MAX_INTERP_GAP_S:
                x[run_start:i] = filled[run_start:i]
            run_start = None
    return x


def trailing_mean(x, n):
    out = np.full_like(x, np.nan)
    for i in range(len(x)):
        seg = x[max(0, i - n + 1):i + 1]
        if not np.isnan(seg).all():
            out[i] = np.nanmean(seg)
    return out


def find_cuts(video, n):
    """Frame indices where a new shot starts (broadcast camera cuts)."""
    cap = cv2.VideoCapture(str(video))
    cuts, prev = [], None
    for i in range(n):
        ok, frame = cap.read()
        if not ok:
            break
        hsv = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev is not None and cv2.compareHist(prev, hist, cv2.HISTCMP_CORREL) < CUT_HIST_CORR:
            cuts.append(i)
        prev = hist
    return cuts


def guard(x, cuts):
    x = x.copy()
    for c in cuts:
        x[max(0, c - CUT_GUARD_FRAMES):c + CUT_GUARD_FRAMES] = np.nan
    return x


def torso_scale(torso, fps, cuts):
    """Trailing median of torso length within the current shot (zoom changes at cuts)."""
    k = max(1, int(TORSO_WINDOW_S * fps))
    n = len(torso)
    shot_start = np.maximum.accumulate(np.isin(np.arange(n), cuts) * np.arange(n))
    scale = np.full(n, np.nan)
    for i in range(n):
        seg = torso[max(shot_start[i], i - k + 1):i + 1]
        if not np.isnan(seg).all():
            scale[i] = np.nanmedian(seg)
    return scale


def signals(t, kp, fps, cuts):
    hips = mid(kp, 11, 12)                         # (n, 2, 2)
    shoulders = mid(kp, 5, 6)
    torso = np.linalg.norm(shoulders - hips, axis=-1)          # (n, 2)
    torso = np.nanmean(torso, axis=1)
    scale = torso_scale(torso, fps, cuts)

    d = np.linalg.norm(hips[:, 0] - hips[:, 1], axis=-1) / scale
    d = trailing_mean(interp_short(guard(d, cuts), fps), SMOOTH_FRAMES)
    d_dot = trailing_mean(np.gradient(d) * fps, SMOOTH_FRAMES)

    # Limb speed relative to the fighter's own hips, so camera pans do not count.
    rel = kp[:, :, LIMBS, :] - hips[:, :, None, :]
    speed = np.linalg.norm(np.diff(rel, axis=0), axis=-1) * fps / scale[1:, None, None]
    w = np.full(len(t), np.nan)
    w[1:] = np.where(np.isnan(speed).all(axis=(1, 2)), np.nan,
                     np.nanmax(np.where(np.isnan(speed), -np.inf, speed), axis=(1, 2)))
    w = trailing_mean(interp_short(guard(w, cuts), fps), SMOOTH_FRAMES)

    # Arm extension of the most extended arm of either fighter.
    exts = []
    for s_, e_, w_ in ARMS:
        arm_len = (np.linalg.norm(kp[:, :, s_] - kp[:, :, e_], axis=-1)
                   + np.linalg.norm(kp[:, :, e_] - kp[:, :, w_], axis=-1))
        with np.errstate(invalid="ignore", divide="ignore"):
            exts.append(np.linalg.norm(kp[:, :, s_] - kp[:, :, w_], axis=-1) / arm_len)
    exts = np.stack(exts, axis=-1).reshape(len(t), -1)
    ext = np.where(np.isnan(exts).all(axis=1), np.nan,
                   np.nanmax(np.where(np.isnan(exts), -np.inf, exts), axis=1))
    ext = trailing_mean(interp_short(guard(ext, cuts), fps), SMOOTH_FRAMES)
    return d, d_dot, w, ext


def exchange_mask(t, d, w, ext):
    """engaged 0/1 per frame: attack frames merged within ENGAGE_HOLD_S, padded by EXCHANGE_PAD_S."""
    with np.errstate(invalid="ignore"):
        in_range = d < D_ATTACK_RANGE
        attack = in_range & ((np.nan_to_num(w) >= W_ATTACK) | (np.nan_to_num(ext) >= EXT_ATTACK))
        attack |= d < D_CLINCH
    segs = []
    for i in np.where(attack)[0]:
        if segs and t[i] - segs[-1][1] <= ENGAGE_HOLD_S:
            segs[-1][1] = t[i]
        else:
            segs.append([t[i], t[i]])
    engaged = np.zeros(len(t), bool)
    for a, b in segs:
        engaged[(t >= a - EXCHANGE_PAD_S) & (t <= b + EXCHANGE_PAD_S)] = True
    return engaged


def run_states(t, d, d_dot, engaged):
    states, state, since = [], "FAR", 0.0
    for i in range(len(t)):
        if engaged[i]:
            nxt = "ENGAGE"
        elif np.isnan(d[i]):
            nxt = "MISSING"
        else:
            ddi = 0.0 if np.isnan(d_dot[i]) else d_dot[i]
            range_in = d[i] < D_RANGE_IN or ddi < DDOT_RANGE_IN
            range_hold = d[i] < D_RANGE_OUT or ddi < DDOT_RANGE_OUT
            if range_in or (state in ("RANGE", "ENGAGE") and range_hold):
                nxt = "RANGE"
            else:
                nxt = "FAR"
            # Dwell time: do not step down out of a state that just started.
            rank = {"MISSING": 0, "FAR": 1, "RANGE": 2, "ENGAGE": 3}
            if state not in ("MISSING", "ENGAGE") and rank[nxt] < rank[state] and t[i] - since < MIN_STATE_S:
                nxt = state
        if nxt != state:
            state, since = nxt, t[i]
        states.append(state)
    return states


def segments(t, states, fps):
    segs, start = [], 0
    for i in range(1, len(states) + 1):
        if i == len(states) or states[i] != states[start]:
            segs.append([t[start], t[i - 1] + 1 / fps, states[start], start, i])
            start = i
    return segs


def split_long(s, e, t, w):
    """Cut [s, e] at w minima so no piece exceeds ENGAGE_MAX_S."""
    pieces = []
    while e - s > ENGAGE_MAX_S:
        lo, hi = s + ENGAGE_MAX_S / 2, s + ENGAGE_MAX_S
        m = (t >= lo) & (t <= hi) & ~np.isnan(w)
        cut = t[m][np.argmin(w[m])] if m.any() else hi
        pieces.append((s, cut, "split_at_w_min"))
        s = cut
    pieces.append((s, e, None))
    return pieces


def build_windows(t, states, d, d_dot, w, fps, duration):
    segs = segments(t, states, fps)
    # ENGAGE: pad, merge overlaps, split long ones.
    eng = []
    for s, e, st, a, b in segs:
        if st != "ENGAGE":
            continue
        s, e = max(0.0, s - ENGAGE_PAD_S), min(duration, e + ENGAGE_PAD_S)
        if eng and s <= eng[-1][1]:
            eng[-1][1] = max(eng[-1][1], e)
        else:
            eng.append([s, e])
    windows = []
    for s, e in eng:
        for ps, pe, note in split_long(s, e, t, w):
            pm = (t >= ps) & (t < pe)
            reason = f"d_min={np.nanmin(d[pm]):.2f} w_peak={np.nanmax(w[pm]):.1f}" if pm.any() and not np.isnan(d[pm]).all() else "padding"
            windows.append({"start": round(ps, 3), "end": round(pe, 3), "state": "ENGAGE",
                            "sample_fps": round(fps, 3), "reason": reason + (f" {note}" if note else "")})
    # RANGE / FAR / MISSING: whatever ENGAGE windows do not cover.
    for s, e, st, a, b in segs:
        if st == "ENGAGE":
            continue
        pieces = [(s, e)]
        for es, ee in eng:
            pieces = [p for ps, pe in pieces for p in ((ps, min(pe, es)), (max(ps, ee), pe)) if p[1] - p[0] > 1e-6]
        for ps, pe in pieces:
            pm = (t >= ps) & (t < pe)
            if st == "MISSING":
                state, fps_out, reason = "RANGE", SAMPLE_FPS["RANGE"], "tracking_gap: sample conservatively"
            elif st == "RANGE":
                state, fps_out = "RANGE", SAMPLE_FPS["RANGE"]
                reason = f"d_min={np.nanmin(d[pm]):.2f} d_dot_min={np.nanmin(d_dot[pm]):.2f}" if pm.any() else ""
            else:
                state, fps_out = "FAR", SAMPLE_FPS["FAR"]
                reason = f"d_min={np.nanmin(d[pm]):.2f}" if pm.any() else ""
            windows.append({"start": round(ps, 3), "end": round(pe, 3), "state": state,
                            "sample_fps": fps_out, "reason": reason})
    windows.sort(key=lambda x: x["start"])
    return windows


def plot(t, d, d_dot, w, ext, engaged, states, cuts, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(5, 1, figsize=(12, 9), sharex=True,
                             gridspec_kw={"height_ratios": [3, 3, 3, 3, 1.2]})
    series = [(d, "d (hip distance / torso)", [D_CLINCH, D_ATTACK_RANGE, D_RANGE_IN]),
              (d_dot, "d_dot (/s, negative = closing)", [DDOT_RANGE_IN]),
              (w, "w (max limb speed, torso/s)", [W_ATTACK]),
              (ext, "arm extension (1 = straight)", [EXT_ATTACK])]
    ax01 = axes[-1]
    ax01.fill_between(t, engaged.astype(int), step="post", color="#e5484d", lw=0)
    ax01.set_ylim(0, 1.05)
    ax01.set_yticks([0, 1])
    ax01.set_ylabel("engaged", fontsize=9)
    for ax, (y, label, lines) in zip(axes, series):
        for s, e, st, *_ in segments(t, states, 1 / np.median(np.diff(t))):
            ax.axvspan(s, e, color=STATE_COLORS[st], lw=0)
        ax.plot(t, y, color="#222", lw=1.2)
        for c in cuts:
            ax.axvline(t[c], color="#7a3cff", lw=1)
        for v in lines:
            ax.axhline(v, color="#666", ls="--", lw=0.8)
        ax.set_ylabel(label, fontsize=9)
    axes[-1].set_xlabel("video time (s)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in STATE_COLORS.values()]
    handles.append(plt.Line2D([], [], color="#7a3cff"))
    axes[0].legend(handles, list(STATE_COLORS) + ["camera cut"], loc="upper right", ncol=4, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", help="e.g. outputs/pereira_rountree_45s")
    args = ap.parse_args()
    clip_dir = Path(args.clip_dir)
    if not clip_dir.is_absolute() and not clip_dir.exists():
        clip_dir = ROOT / clip_dir

    t, kp = load(clip_dir / "keypoints.jsonl")
    fps = 1 / np.median(np.diff(t))
    summary_path = clip_dir / "summary.json"
    if summary_path.exists():
        fps = json.loads(summary_path.read_text()).get("source_fps", fps)
    duration = len(t) / fps

    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    cuts = find_cuts(summary["video"], len(t)) if summary.get("video") else []
    d, d_dot, w, ext = signals(t, kp, fps, cuts)
    engaged = exchange_mask(t, d, w, ext)
    states = run_states(t, d, d_dot, engaged)
    windows = build_windows(t, states, d, d_dot, w, fps, duration)

    with (clip_dir / "windows.jsonl").open("w") as f:
        for i, win in enumerate(windows):
            win_cuts = [round(t[c], 3) for c in cuts if win["start"] <= t[c] < win["end"]]
            f.write(json.dumps({"clip_id": clip_dir.name, "window_id": f"w{i:03d}", **win,
                                "camera_cuts_s": win_cuts}) + "\n")
    with (clip_dir / "exchange.jsonl").open("w") as f:
        for i in range(len(t)):
            f.write(json.dumps({"t": round(float(t[i]), 3), "engaged": int(engaged[i])}) + "\n")
    plot(t, d, d_dot, w, ext, engaged, states, cuts, clip_dir / "engage.png")

    seconds = {s: round(sum(win["end"] - win["start"] for win in windows if win["state"] == s), 2)
               for s in ("FAR", "RANGE", "ENGAGE")}
    eng = [(win["start"], win["end"]) for win in windows if win["state"] == "ENGAGE"]
    cosmos_frames = sum((win["end"] - win["start"]) * win["sample_fps"] for win in windows)
    print(f"{clip_dir.name}: {duration:.1f}s analysed. State seconds: "
          + ", ".join(f"{k} {v}s" for k, v in seconds.items())
          + f" (raw tracking gaps sampled as RANGE: {states.count('MISSING')} frames)")
    on = [(t[i], t[j - 1] + 1 / fps) for i, j in
          ((s_[3], s_[4]) for s_ in segments(t, ["1" if e else "0" for e in engaged], fps) if s_[2] == "1")]
    print(f"engaged = 1: {len(on)} segments, {engaged.mean() * 100:.0f}% of frames — "
          + ", ".join(f"{a:.2f}-{b:.2f}" for a, b in on))
    print("Camera cuts at: " + ", ".join(f"{t[c]:.2f}s" for c in cuts))
    print(f"ENGAGE windows: {len(eng)} — " + ", ".join(f"{s:.2f}-{e:.2f}" for s, e in eng))
    print(f"Cosmos frames: {cosmos_frames:.0f} of {len(t)} ({100 * cosmos_frames / len(t):.1f}% of all frames)")


if __name__ == "__main__":
    main()
