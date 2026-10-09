"""Simulated-live YOLO Pose + ByteTrack over a video file.

Frames are released on the wall clock at the video's own frame rate; if
inference falls behind, frames are skipped rather than queued. Writes
outputs/<clip_id>/tracks.jsonl (README contract section 1), a latency
summary, and optionally an overlay video / live window.

    python realtime.py ../data/raw/holloway_gaethje_20s.mp4 --save-video
    python realtime.py ../data/raw/holloway_gaethje_20s.mp4 --show
    python realtime.py ../data/raw/holloway_gaethje_20s.mp4 --mode offline
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

SCHEMA_VERSION = "0.1"
REPO_ROOT = Path(__file__).resolve().parent.parent
COLORS = {"A": (77, 72, 229), "B": (221, 99, 62)}  # BGR: red, blue
SKELETON = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]
REASSIGN_HOLD = 15  # frames to stay "uncertain" after an A/B track switch


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def center_dist(a, b):
    return np.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


class Identity:
    """Keeps the tracker-ID -> A/B mapping.

    Initial assignment: the two largest people, A = screen-left at that moment
    only. Afterwards identity follows track IDs, never screen side. When a
    fighter's track disappears, the nearest unassigned large person takes it
    over and the frame is marked uncertain.
    """

    def __init__(self):
        self.ids = {"A": None, "B": None}
        self.last_box = {"A": None, "B": None}
        self.hold = 0

    def update(self, people):
        # people: {track_id: {"bbox": [...], ...}}
        if self.ids["A"] is None:
            if len(people) < 2:
                return {"A": None, "B": None}, "lost"
            two = sorted(people, key=lambda t: area(people[t]["bbox"]), reverse=True)[:2]
            two.sort(key=lambda t: people[t]["bbox"][0])
            self.ids = {"A": two[0], "B": two[1]}

        status = "stable"
        out = {}
        for f in ("A", "B"):
            tid = self.ids[f]
            if tid not in people and self.last_box[f] is not None:
                taken = set(self.ids.values())
                big = sorted(people, key=lambda t: area(people[t]["bbox"]), reverse=True)[:3]
                free = [t for t in big if t not in taken]
                if free:
                    tid = min(free, key=lambda t: center_dist(people[t]["bbox"], self.last_box[f]))
                    self.ids[f] = tid
                    self.hold = REASSIGN_HOLD
            if tid in people:
                out[f] = dict(track_id=int(tid), **people[tid])
                self.last_box[f] = people[tid]["bbox"]
            else:
                out[f] = None
                status = "uncertain"
        if out["A"] is None and out["B"] is None:
            status = "lost"
        elif self.hold > 0:
            self.hold -= 1
            status = "uncertain"
        return out, status


def parse_people(result):
    boxes = result.boxes
    if boxes is None or boxes.id is None:
        return {}
    xyxy = boxes.xyxy.cpu().numpy()
    ids = boxes.id.int().cpu().tolist()
    confs = boxes.conf.cpu().numpy()
    kpts = result.keypoints.data.cpu().numpy()  # (n, 17, 3)
    return {
        tid: {
            "bbox": [round(float(v), 1) for v in xyxy[k]],
            "conf": round(float(confs[k]), 3),
            "kpts": [[round(float(x), 1), round(float(y), 1), round(float(c), 3)] for x, y, c in kpts[k]],
        }
        for k, tid in enumerate(ids)
    }


def draw(frame, fighters, status, t_s, infer_ms):
    for f, d in fighters.items():
        if d is None:
            continue
        c = COLORS[f]
        x1, y1, x2, y2 = map(int, d["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), c, 2)
        cv2.putText(frame, f"{f} (id {d['track_id']})", (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, c, 2)
        k = d["kpts"]
        for a, b in SKELETON:
            if k[a][2] > 0.3 and k[b][2] > 0.3:
                cv2.line(frame, (int(k[a][0]), int(k[a][1])), (int(k[b][0]), int(k[b][1])), c, 2)
        for j in (9, 10, 15, 16):  # wrists and ankles
            if k[j][2] > 0.3:
                cv2.circle(frame, (int(k[j][0]), int(k[j][1])), 6, (0, 255, 255), -1)
    hud = f"t={t_s:6.2f}s  {status}  infer={infer_ms:5.1f}ms"
    cv2.putText(frame, hud, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
    cv2.putText(frame, hud, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return frame


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))], 1) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--mode", choices=["live", "offline"], default="live",
                    help="live: wall-clock pacing with frame skipping; offline: every frame")
    ap.add_argument("--model", default="yolo11n-pose.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--tracker", default="bytetrack.yaml")
    ap.add_argument("--show", action="store_true", help="open a live window (Esc to stop)")
    ap.add_argument("--save-video", action="store_true", help="write overlay.mp4")
    args = ap.parse_args()

    video = Path(args.video)
    clip_id = video.stem
    out_dir = REPO_ROOT / "outputs" / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    model = YOLO(str(Path(__file__).parent / args.model) if (Path(__file__).parent / args.model).exists() else args.model)
    ok, first = cap.read()
    t_warm = time.perf_counter()
    for _ in range(3):  # warm-up, reported separately from steady state
        model.predict(first, imgsz=args.imgsz, device=args.device, verbose=False)
    warmup_s = time.perf_counter() - t_warm
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    writer = None
    if args.save_video:
        writer = cv2.VideoWriter(str(out_dir / f"overlay_{args.mode}.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    identity = Identity()
    infer_ms, latency_ms, statuses = [], [], {"stable": 0, "uncertain": 0, "lost": 0}
    skipped, processed, last_vis = 0, 0, None
    tracks_f = open(out_dir / "tracks.jsonl", "w")

    t0 = time.perf_counter()
    i = 0
    while True:
        if args.mode == "live":
            target = int((time.perf_counter() - t0) * fps)
            while i < target:  # behind the live edge: drop frames instead of queueing
                if not cap.grab():
                    break
                if writer is not None and last_vis is not None:
                    writer.write(last_vis)
                i += 1
                skipped += 1
        ok, frame = cap.read()
        if not ok:
            break
        t_s = i / fps

        t_a = time.perf_counter()
        result = model.track(frame, persist=True, tracker=args.tracker, imgsz=args.imgsz,
                             device=args.device, classes=[0], verbose=False)[0]
        fighters, status = identity.update(parse_people(result))
        t_b = time.perf_counter()

        tracks_f.write(json.dumps({
            "schema_version": SCHEMA_VERSION, "clip_id": clip_id, "frame_idx": i,
            "t_s": round(t_s, 3), "identity_status": status, "fighters": fighters,
        }) + "\n")

        infer_ms.append((t_b - t_a) * 1000)
        if args.mode == "live":
            # frame became available at t0 + t_s; result ready at t_b
            latency_ms.append((t_b - (t0 + t_s)) * 1000)
        statuses[status] += 1
        processed += 1

        if writer is not None or args.show:
            last_vis = draw(frame, fighters, status, t_s, infer_ms[-1])
            if writer is not None:
                writer.write(last_vis)
            if args.show:
                cv2.imshow("FightLens live", last_vis)
        i += 1

        # live: ahead of the live edge -> wait until the next frame is due
        wait = t0 + i / fps - time.perf_counter() if args.mode == "live" else 0
        if args.show:
            if cv2.waitKey(max(1, int(wait * 1000))) == 27:
                break
        elif wait > 0:
            time.sleep(wait)

    wall_s = time.perf_counter() - t0
    tracks_f.close()
    cap.release()
    if writer is not None:
        writer.release()
    cv2.destroyAllWindows()

    summary = {
        "clip_id": clip_id, "mode": args.mode, "model": args.model, "imgsz": args.imgsz,
        "device": args.device, "video_fps": round(fps, 3), "video_frames": n_frames,
        "processed_frames": processed, "skipped_frames": skipped,
        "effective_fps": round(processed / wall_s, 1), "wall_s": round(wall_s, 2),
        "video_s": round(n_frames / fps, 2), "warmup_s": round(warmup_s, 2),
        "infer_ms": {"p50": pct(infer_ms, 50), "p95": pct(infer_ms, 95), "max": pct(infer_ms, 100),
                     "mean": round(statistics.mean(infer_ms), 1) if infer_ms else None},
        "frame_to_result_ms": ({"p50": pct(latency_ms, 50), "p95": pct(latency_ms, 95),
                                "max": pct(latency_ms, 100)} if latency_ms else None),
        "identity_status_frames": statuses,
    }
    (out_dir / f"latency_{args.mode}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
