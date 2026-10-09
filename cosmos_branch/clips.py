"""What Cosmos is shown: one window of the video, prepared for the model.

A clip is not a copy of the video. The Cosmos Reason model cards recommend 4 frames per second, and a jab is
over in a quarter of a second, so:

  - the window is sampled densely (Window.fps frames per second of bout time) and encoded at CLIP_FPS:
    an exchange plays about three times slower than the bout, a glance at the time between exchanges plays faster
  - it is cropped to the two fighters, so they fill the picture
  - A and B are written above their heads
  - the bout time is printed under every frame, so the model can say when something happened without
    converting clip time back into bout time

What the YOLO branch contributes here is where the two fighters are (keypoints.jsonl from track.py): the crop
and the A / B tags. It says nothing about what they do. Without that file the whole picture is sent, untagged,
and the question has to describe the fighters in words (review.py --a / --b).

Every clip is kept next to a contact sheet of its frames (x12.25.mp4, x12.25.jpg): the sheet is the quickest
way to compare what Cosmos was shown with what it said.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

CLIP_FPS = 4.0           # the rate the clip is encoded at
MAX_FRAMES = 36          # frames in one clip, at most (3 s of an exchange at 12 a second)
CLIP_HEIGHT = 480        # the picture is scaled to this height, or to CLIP_MAX_WIDTH when that is reached first
CLIP_MAX_WIDTH = 854
STAMP_HEIGHT = 36        # the strip under the picture that carries the bout time
CROP_MARGIN = 0.25       # air around the fighters' keypoints, as a share of their extent (keypoints stop at the eyes and wrists)
CROP_MIN = 0.35          # the crop is never smaller than this share of the picture, in either direction
KP_MIN_CONF = 0.3        # keypoints below this are treated as not seen (the same threshold track.py draws with)
TAG_COLOURS = {"A": (0, 180, 255), "B": (255, 160, 30)}      # BGR, the YOLO branch's colours for A and B
_TAG_W, _TAG_H = 30, 32
_SHEET_FRAMES, _SHEET_COLUMNS, _SHEET_WIDTH = 12, 4, 320


@dataclass(frozen=True)
class Clip:
    path: Path
    sheet: Path
    frames: int
    t0: float            # the window's bounds, in bout time
    t1: float
    speed: float         # bout seconds per clip second: 0.33 = three times slower than the bout, 2 = twice as fast
    cropped: bool
    tagged: bool         # A / B are written on most of the frames


class Poses:
    """Where A and B are, frame by frame: keypoints.jsonl as yolo_branch/track.py writes it.

        {"t": 1.234, "A": {"track_id": 3, "xy": [[x, y] * 17], "conf": [c * 17], "status": "tracked"}, "B": {...}}

    Pixels of the original frame, COCO order, null xy when the fighter is missing in that frame.
    """

    def __init__(self, path: Path):
        times, points = [], []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            times.append(float(row["t"]))
            points.append([_points(row.get(label)) for label in ("A", "B")])
        if not times:
            raise ValueError(f"{path} has no rows")
        self.t = np.asarray(times)
        self.xy = np.asarray(points, dtype=float)            # (frames, 2 fighters, 17 keypoints, 2), NaN = not seen
        self._step = float(np.median(np.diff(self.t))) if len(times) > 1 else 1 / 30

    def at(self, t: float) -> dict[str, np.ndarray]:
        """The keypoints of whoever was seen in the frame nearest to t (nobody when that frame is not near)."""
        i = int(np.argmin(np.abs(self.t - t)))
        if abs(self.t[i] - t) > max(1.5 * self._step, 0.05):
            return {}
        return {label: self.xy[i, k] for k, label in enumerate("AB") if not np.isnan(self.xy[i, k]).all()}

    def extent(self, t0: float, t1: float) -> Optional[tuple[float, float, float, float]]:
        """The box around every keypoint of both fighters between t0 and t1. None when they were not seen."""
        rows = self.xy[(self.t >= t0 - 0.1) & (self.t <= t1 + 0.1)].reshape(-1, 2)
        rows = rows[~np.isnan(rows).any(axis=1)]
        if len(rows) < 6:
            return None
        return float(rows[:, 0].min()), float(rows[:, 1].min()), float(rows[:, 0].max()), float(rows[:, 1].max())


def _points(entry: Optional[dict]) -> np.ndarray:
    points = np.full((17, 2), np.nan)
    if not entry or entry.get("status") == "missing":
        return points
    for i, (xy, conf) in enumerate(zip(entry.get("xy") or [], entry.get("conf") or [])):
        if i < 17 and xy and xy[0] is not None and xy[1] is not None and (conf or 0.0) >= KP_MIN_CONF:
            points[i] = xy
    return points


def video_info(video: Path) -> tuple[float, float]:
    """(frames per second, duration in seconds) of a video file."""
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open the video: {video}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        fps = float(fps) if fps and fps > 1 else 30.0
        return fps, float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
    finally:
        capture.release()


def cut(video: Path, window, out_dir: Path, poses: Optional[Poses] = None) -> Clip:
    """The clip for one window, written to <out_dir>/<window.id>.mp4 with its contact sheet beside it."""
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open the video: {video}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        fps = float(fps) if fps and fps > 1 else 30.0
        last = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0) - 1
        count = int(min(max(round(window.seconds * window.fps), 2), MAX_FRAMES))
        wanted = sorted({_frame_index(window.t0 + (i + 0.5) * window.seconds / count, fps, last) for i in range(count)})
        frames = _read(capture, wanted, fps)
    finally:
        capture.release()
    if len(frames) < 2:
        raise ValueError(f"The video has no frames between {window.t0:.2f} s and {window.t1:.2f} s: {video}")

    height, width = frames[0][1].shape[:2]
    extent = poses.extent(window.t0, window.t1) if poses else None
    crop = _crop(extent, width, height)
    scale = min(CLIP_HEIGHT / (crop[3] - crop[1]), CLIP_MAX_WIDTH / (crop[2] - crop[0]))
    size = (_even((crop[2] - crop[0]) * scale), _even((crop[3] - crop[1]) * scale))

    pictures, tagged = [], 0
    for t, image in frames:
        picture, tags = _prepare(image, crop, scale, size, poses.at(t) if poses else {}, t)
        pictures.append(picture)
        tagged += tags > 0

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{window.id}.mp4"
    _encode(pictures, path)
    sheet = out_dir / f"{window.id}.jpg"
    cv2.imwrite(str(sheet), _contact_sheet(pictures), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return Clip(path=path, sheet=sheet, frames=len(pictures), t0=window.t0, t1=window.t1,
                speed=round(window.seconds / (len(pictures) / CLIP_FPS), 3),
                cropped=extent is not None, tagged=tagged * 2 > len(pictures))


def _frame_index(t: float, fps: float, last: int) -> int:
    index = max(int(round(t * fps)), 0)
    return min(index, last) if last >= 0 else index


def _read(capture, wanted: list[int], fps: float) -> list[tuple[float, np.ndarray]]:
    """The frames with these numbers, each with its bout time (number / fps, as track.py counts time).
    One seek to the first, then straight through: seeking for every frame is slow and lands beside the frame."""
    capture.set(cv2.CAP_PROP_POS_FRAMES, wanted[0])
    at, frames = wanted[0], []
    for index in wanted:
        while at < index:
            if not capture.grab():
                return frames
            at += 1
        ok, image = capture.read()
        at += 1
        if not ok:
            break
        frames.append((index / fps, image))
    return frames


def _crop(extent, width: int, height: int) -> tuple[int, int, int, int]:
    """The part of the picture that holds the fighters with air around them. The whole picture when they were not seen."""
    if extent is None:
        return 0, 0, width, height
    x1, y1, x2, y2 = extent
    pad_x, pad_y = (x2 - x1) * CROP_MARGIN, (y2 - y1) * CROP_MARGIN
    x1, x2 = _widen(x1 - pad_x, x2 + pad_x, CROP_MIN * width, width)
    y1, y2 = _widen(y1 - pad_y, y2 + pad_y, CROP_MIN * height, height)
    return int(x1), int(y1), max(int(round(x2)), int(x1) + 2), max(int(round(y2)), int(y1) + 2)


def _widen(lo: float, hi: float, at_least: float, limit: float) -> tuple[float, float]:
    """Grow [lo, hi] to at least `at_least` around its middle, then push it back inside [0, limit]."""
    if hi - lo < at_least:
        middle = (lo + hi) / 2
        lo, hi = middle - at_least / 2, middle + at_least / 2
    if lo < 0:
        lo, hi = 0.0, hi - lo
    if hi > limit:
        lo, hi = lo - (hi - limit), limit
    return max(lo, 0.0), min(hi, limit)


def _even(value: float) -> int:
    return max(int(round(value / 2)) * 2, 2)                 # H.264 needs even sizes


def _prepare(image: np.ndarray, crop, scale: float, size, seen: dict, t: float) -> tuple[np.ndarray, int]:
    """One frame of the clip: cropped, scaled, A / B written above the heads, the bout time underneath.
    Returns the frame and how many tags were written on it."""
    x1, y1, x2, y2 = crop
    picture = cv2.resize(image[y1:y2, x1:x2], size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)

    tags = {}
    for label, points in seen.items():
        body = points[~np.isnan(points).any(axis=1)]
        if len(body) < 4:
            continue
        head = points[:5][~np.isnan(points[:5]).any(axis=1)]
        cx = head[:, 0].mean() if len(head) else body[:, 0].mean()
        top, tall = body[:, 1].min(), body[:, 1].max() - body[:, 1].min()
        tags[label] = [(cx - x1) * scale, (top - 0.18 * tall - y1) * scale]      # middle of the tag's bottom edge
    if len(tags) == 2 and all(abs(tags["A"][i] - tags["B"][i]) < _TAG_W + 4 for i in (0, 1)):
        left, right = sorted(tags, key=lambda label: tags[label][0])            # in a clinch: side by side, not on top
        middle = (tags["A"][0] + tags["B"][0]) / 2
        tags[left][0], tags[right][0] = middle - _TAG_W / 2 - 2, middle + _TAG_W / 2 + 2
    for label, (x, y) in tags.items():
        x0 = int(min(max(x - _TAG_W / 2, 0), size[0] - _TAG_W))
        y0 = int(min(max(y - _TAG_H, 0), size[1] - _TAG_H))
        cv2.rectangle(picture, (x0, y0), (x0 + _TAG_W, y0 + _TAG_H), (255, 255, 255), -1)
        cv2.rectangle(picture, (x0, y0), (x0 + _TAG_W, y0 + _TAG_H), TAG_COLOURS[label], 3)
        cv2.putText(picture, label, (x0 + 7, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)

    stamp = np.zeros((STAMP_HEIGHT, size[0], 3), dtype=np.uint8)
    cv2.putText(stamp, f"t = {t:.2f} s", (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([picture, stamp]), len(tags)


def _encode(pictures: list[np.ndarray], path: Path) -> None:
    """H.264 through ffmpeg (what every decoder reads); OpenCV's own encoder when ffmpeg is not installed."""
    height, width = pictures[0].shape[:2]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        done = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
             "-r", str(CLIP_FPS), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
             "-movflags", "+faststart", str(path)],
            input=b"".join(picture.tobytes() for picture in pictures), capture_output=True)
        if done.returncode == 0 and path.exists() and path.stat().st_size > 0:
            return
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), CLIP_FPS, (width, height))
    try:
        if not writer.isOpened():
            raise ValueError(f"Could not write the clip: {path}")
        for picture in pictures:
            writer.write(picture)
    finally:
        writer.release()


def _contact_sheet(pictures: list[np.ndarray]) -> np.ndarray:
    """Up to twelve of the clip's frames, evenly spread, on one picture."""
    picks = sorted(set(np.linspace(0, len(pictures) - 1, min(_SHEET_FRAMES, len(pictures))).round().astype(int)))
    height = int(round(pictures[0].shape[0] * _SHEET_WIDTH / pictures[0].shape[1]))
    tiles = [cv2.resize(pictures[i], (_SHEET_WIDTH, height), interpolation=cv2.INTER_AREA) for i in picks]
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % _SHEET_COLUMNS)
    return np.vstack([np.hstack(tiles[i:i + _SHEET_COLUMNS]) for i in range(0, len(tiles), _SHEET_COLUMNS)])
