"""Track the first N seconds (default 10): python track.py [--seconds 25] video.mp4 [video2.mp4]."""
from pathlib import Path
import argparse
import itertools
import json
import math
import os
import shutil
import subprocess
import time

MAX_SECONDS = 10
SELECT_SECONDS = 3
DETECTION_CONF = 0.25
NMS_IOU = 0.7
KEYPOINT_DRAW_CONF = 0.3
IMAGE_SIZE = 640
PERSISTENCE_TOLERANCE = 0.1  # Pairs within 10% of longest presence compete by proximity.
MIN_COPRESENCE_SECONDS = 0.3
MIN_PAIR_AREA_RATIO = 0.3  # Tracks smaller than this fraction of the largest are bystanders.
RECONNECT_MAX_DIAGONAL = 0.20
RECONNECT_MAX_GAP_SECONDS = 1.0
RECONNECT_MIN_AREA_RATIO = 0.4
RECONNECT_MAX_AREA_RATIO = 6.0
TRACK_HIGH_THRESH = 0.25
TRACK_LOW_THRESH = 0.1
NEW_TRACK_THRESH = 0.25
TRACK_BUFFER = 30
MATCH_THRESH = 0.8
ENCODE_CRF = 18
REVIEW_INTERVAL_SECONDS = 0.5
MODEL_NAME = "yolo26n-pose.pt"
FALLBACK_MODEL_NAME = "yolo11n-pose.pt"
ROOT = Path(__file__).resolve().parent
COLORS = {"A": (0, 180, 255), "B": (255, 160, 30)}
EDGES = [(0,1),(0,2),(1,3),(2,4),(5,6),(5,7),(7,9),(6,8),(8,10),
         (5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16)]
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".config"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import cv2
import numpy as np
import torch
from ultralytics import YOLO


def select_pair(frames, fps, diagonal):
    history, areas = {}, {}
    for i, tracks in enumerate(frames):
        if i / fps >= SELECT_SECONDS:
            break
        for ident, tr in tracks.items():
            history.setdefault(ident, {})[i] = tr["center"]
            box = tr["box"]
            areas.setdefault(ident, []).append((box[2]-box[0])*(box[3]-box[1]))
    median_area = {ident: float(np.median(v)) for ident, v in areas.items()}
    largest = max(median_area.values(), default=0.0)
    history = {ident: h for ident, h in history.items()
               if median_area[ident] >= MIN_PAIR_AREA_RATIO*largest}
    candidates = []
    for a, b in itertools.combinations(history, 2):
        common = sorted(set(history[a]) & set(history[b]))
        if len(common) < math.ceil(MIN_COPRESENCE_SECONDS * fps):
            continue
        distance = float(np.mean([np.linalg.norm(np.array(history[a][i]) - history[b][i])
                                  for i in common])) / diagonal
        presence = min(len(history[a]), len(history[b]))
        candidates.append((a, b, presence, distance, common[0]))
    if not candidates:
        raise RuntimeError("No pair with sufficient co-presence in first three seconds.")
    best_presence = max(c[2] for c in candidates)
    eligible = [c for c in candidates if c[2] >= best_presence * (1-PERSISTENCE_TOLERANCE)]
    a, b, _, _, first = min(eligible, key=lambda c: (c[3], -c[2], c[0], c[1]))
    if history[a][first][0] > history[b][first][0]:
        a, b = b, a
    return {"A": a, "B": b}, candidates


def assign(frames, fps, initial, diagonal):
    ids = dict(initial)
    last, last_seen, last_area = {}, {}, {}
    gaps = {"A": False, "B": False}
    events, assigned = [], []
    for i, tracks in enumerate(frames):
        t = i / fps
        current = {label: ids[label] if ids[label] in tracks else None for label in ids}
        used = {v for v in current.values() if v is not None}
        missing = [label for label in ids if current[label] is None and label in last
                   and t-last_seen[label] <= RECONNECT_MAX_GAP_SECONDS]
        available = [ident for ident in tracks if ident not in used]
        # Joint nearest assignment avoids assigning the same new track to both fighters.
        options = []
        for label in missing:
            choices = [(None, RECONNECT_MAX_DIAGONAL)]
            for ident in available:
                box = tracks[ident]["box"]
                area = (box[2]-box[0])*(box[3]-box[1])
                if not RECONNECT_MIN_AREA_RATIO <= area/last_area[label] <= RECONNECT_MAX_AREA_RATIO:
                    continue
                distance = float(np.linalg.norm(np.array(tracks[ident]["center"])-last[label]))/diagonal
                if distance <= RECONNECT_MAX_DIAGONAL:
                    choices.append((ident, distance))
            options.append(choices)
        if options:
            valid = [combo for combo in itertools.product(*options)
                     if len([x[0] for x in combo if x[0] is not None]) ==
                     len({x[0] for x in combo if x[0] is not None})]
            best = min(valid, key=lambda combo: sum(x[1] for x in combo))
            for label, (ident, _) in zip(missing, best):
                if ident is not None:
                    events.append({"type": "id_reconnection", "label": label, "t": t,
                                   "old_id": ids[label], "new_id": ident})
                    ids[label] = current[label] = ident
        row = {"t": t}
        for label, ident in current.items():
            if ident is None:
                row[label] = {"track_id": None, "xy": [[None, None] for _ in range(17)],
                              "conf": [0.0]*17, "status": "missing"}
                if not gaps[label]:
                    events.append({"type": "gap_start", "label": label, "t": t})
                gaps[label] = True
            else:
                tr = tracks[ident]
                row[label] = {"track_id": ident, "xy": tr["xy"], "conf": tr["conf"], "status": "tracked"}
                if gaps[label]:
                    events.append({"type": "gap_end", "label": label, "t": t})
                gaps[label] = False
                last[label], last_seen[label] = np.array(tr["center"]), t
                box = tr["box"]
                last_area[label] = max(1.0, (box[2]-box[0])*(box[3]-box[1]))
        assigned.append(row)
    return assigned, events


def run(video):
    video = video.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    out = ROOT / "outputs" / video.stem
    out.mkdir(parents=True, exist_ok=True)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        model = YOLO(str(ROOT / MODEL_NAME))
        model_name = MODEL_NAME
    except Exception as exc:
        print(f"YOLO26 loading failed: {exc}; falling back to {FALLBACK_MODEL_NAME}", flush=True)
        model = YOLO(str(ROOT / FALLBACK_MODEL_NAME))
        model_name = FALLBACK_MODEL_NAME
    tracker = out / "tracker.yaml"
    tracker.write_text(f"tracker_type: bytetrack\ntrack_high_thresh: {TRACK_HIGH_THRESH}\n"
                       f"track_low_thresh: {TRACK_LOW_THRESH}\nnew_track_thresh: {NEW_TRACK_THRESH}\n"
                       f"track_buffer: {TRACK_BUFFER}\nmatch_thresh: {MATCH_THRESH}\nfuse_score: true\n")
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not cap.isOpened() or fps <= 0 or width <= 0:
        raise RuntimeError(f"Cannot decode {video}")
    frames, elapsed = [], 0.0
    start = time.perf_counter()
    for i in range(math.ceil(MAX_SECONDS*fps)):
        ok, frame = cap.read()
        if not ok:
            break
        before = time.perf_counter()
        result = model.track(frame, persist=True, device=device, conf=DETECTION_CONF,
                             iou=NMS_IOU, imgsz=IMAGE_SIZE, tracker=str(tracker), verbose=False)[0]
        if device == "mps":
            torch.mps.synchronize()
        elapsed += time.perf_counter()-before
        tracks = {}
        if result.boxes.id is not None and result.keypoints is not None:
            for ident, box, xy, conf in zip(result.boxes.id.int().cpu().tolist(),
                                          result.boxes.xyxy.cpu().tolist(),
                                          result.keypoints.xy.cpu().tolist(),
                                          result.keypoints.conf.cpu().tolist()):
                tracks[ident] = {"box": box, "center": [(box[0]+box[2])/2, (box[1]+box[3])/2],
                                 "xy": xy, "conf": conf}
        frames.append(tracks)
        if i % 60 == 0:
            print(f"{video.name}: {i+1} frames, {device}", flush=True)
    cap.release()
    diagonal = math.hypot(width, height)
    initial, candidates = select_pair(frames, fps, diagonal)
    assigned, events = assign(frames, fps, initial, diagonal)
    with (out / "keypoints.jsonl").open("w") as f:
        for row in assigned:
            f.write(json.dumps(row, allow_nan=False)+"\n")
    # Retain all detections for a reproducible referee/identity audit.
    with (out / "detections.jsonl").open("w") as f:
        for i, tr in enumerate(frames):
            f.write(json.dumps({"t": i/fps, "tracks": tr})+"\n")
    cap = cv2.VideoCapture(str(video))
    raw = out / "annotated.intermediate.mp4"
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width,height))
    if not writer.isOpened():
        raise RuntimeError("Video writer failed")
    review = []
    for i, row in enumerate(assigned):
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("Source ended during rendering")
        for label in ("A", "B"):
            entry = row[label]
            if entry["track_id"] is None:
                continue
            xy, conf, color = entry["xy"], entry["conf"], COLORS[label]
            for a,b in EDGES:
                if min(conf[a],conf[b]) >= KEYPOINT_DRAW_CONF:
                    cv2.line(frame, tuple(map(int,xy[a])), tuple(map(int,xy[b])), color, 3)
            for point, score in zip(xy,conf):
                if score >= KEYPOINT_DRAW_CONF:
                    cv2.circle(frame, tuple(map(int,point)), 4, color, -1)
            box = frames[i][entry["track_id"]]["box"]
            cv2.rectangle(frame, (int(box[0]),int(box[1])), (int(box[2]),int(box[3])), color, 2)
            cv2.putText(frame, f"{label}  id={entry['track_id']}",
                        (int(box[0]),max(28,int(box[1])-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8,color,2)
        writer.write(frame)
        if i % max(1,round(fps*REVIEW_INTERVAL_SECONDS)) == 0:
            tile = frame.copy()  # timestamp only on review sheets, not in the video
            cv2.putText(tile, f"{row['t']:.2f}s", (20,35), cv2.FONT_HERSHEY_SIMPLEX,0.8,(255,255,255),2)
            review.append(cv2.resize(tile,(480,270)))
    cap.release()
    writer.release()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        subprocess.run(["brew", "install", "ffmpeg"], check=True)
        ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    subprocess.run([ffmpeg,"-y","-v","error","-i",str(raw),"-an","-c:v","libx264",
                    "-crf",str(ENCODE_CRF),"-pix_fmt","yuv420p","-movflags","+faststart",
                    str(out/"annotated.mp4")],check=True)
    raw.unlink()
    for offset in range(0,len(review),8):
        tiles = review[offset:offset+8]
        tiles += [np.zeros_like(tiles[0])]*(8-len(tiles))
        cv2.imwrite(str(out/f"review_{offset//8:02}.jpg"),
                    np.concatenate([np.concatenate(tiles[j:j+2],axis=1) for j in range(0,8,2)],axis=0))
    observed = {label:[c for row in assigned if row[label]["status"] == "tracked" for c in row[label]["conf"]]
                for label in ("A","B")}
    summary = {"video":str(video),"model":model_name,"device":device,"frames":len(frames),
               "source_fps":fps,"tracking_fps":len(frames)/elapsed,
               "end_to_end_fps":len(frames)/(time.perf_counter()-start),
               "initial_ids":initial,"pair_candidates":candidates,"events":events,
               "mean_conf":{k:float(np.mean(v)) if v else None for k,v in observed.items()},
               "mean_conf_all_observed":float(np.mean(observed["A"]+observed["B"])),
               "referee_excluded":"requires_visual_review", "identity_swaps":"requires_visual_review"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)
    subprocess.run(["open",str(out/"annotated.mp4")],check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos",type=Path,nargs="+")
    parser.add_argument("--seconds",type=float,default=MAX_SECONDS)
    args = parser.parse_args()
    MAX_SECONDS = args.seconds
    for video in args.videos:
        run(video)
