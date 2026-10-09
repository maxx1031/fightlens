"""Single serialized model executor; live transport adapter around the pose branch."""

import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / "output" / "ultralytics"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "output" / "matplotlib"))
Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from engagement import Engagement


class YoloProcessor:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo")
        self.state = "initializing"
        self.error = None
        self.model_name = os.getenv("FIGHTLENS_YOLO_MODEL", "yolo11n-pose.pt")
        self.model_version = self.model_name
        self.key = None

    def load(self):
        try:
            import cv2
            import numpy as np
            import torch
            import ultralytics
            from ultralytics import YOLO
            from yolo_branch.realtime import Identity, parse_people, draw

            self.cv2, self.np, self.Identity, self.parse_people, self.draw = (
                cv2,
                np,
                Identity,
                parse_people,
                draw,
            )
            torch.set_num_threads(2)
            cv2.setNumThreads(1)
            device = os.getenv("FIGHTLENS_YOLO_DEVICE", "auto")
            self.device = (
                ("mps" if torch.backends.mps.is_available() else "cpu")
                if device == "auto"
                else device
            )
            path = Path(self.model_name)
            if not path.is_absolute():
                path = ROOT / "models" / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self.model = YOLO(str(path))
            self.model.predict(
                np.zeros((360, 640, 3), dtype=np.uint8),
                imgsz=640,
                device=self.device,
                verbose=False,
            )
            self.model_version = (
                f"{path.name} / ultralytics {ultralytics.__version__} / {self.device}"
            )
            self.state = "ready"
            print(f"YOLO ready: {path.name} ({self.device})", flush=True)
        except Exception as error:
            self.state = "failed"
            self.error = f"YOLO initialization failed ({type(error).__name__}). Check model/device configuration."
            print(self.error, flush=True)

    def process(self, frame, position_ms, key):
        from livekit import rtc

        started = time.monotonic()
        if key != self.key:
            self.identity, self.engagement = self.Identity(), Engagement()
            if getattr(self.model.predictor, "trackers", None):
                for tracker in self.model.predictor.trackers:
                    tracker.reset()
            self.key = key
        rgba = (
            frame
            if frame.type == rtc.VideoBufferType.RGBA
            else frame.convert(rtc.VideoBufferType.RGBA)
        )
        image = self.cv2.cvtColor(
            self.np.frombuffer(rgba.data, dtype=self.np.uint8).reshape(
                frame.height, frame.width, 4
            ),
            self.cv2.COLOR_RGBA2BGR,
        )
        result = self.model.track(
            image,
            persist=True,
            tracker="bytetrack.yaml",
            imgsz=640,
            device=self.device,
            classes=[0],
            verbose=False,
        )[0]
        people = self.parse_people(result)
        fighters, identity = self.identity.update(people)
        signals = self.engagement.update(position_ms / 1000, fighters, identity)
        inference_ms = (time.monotonic() - started) * 1000
        annotated = self.draw(
            image, fighters, identity, position_ms / 1000, inference_ms
        )
        self.cv2.putText(
            annotated,
            f"YOLO Pose | {signals['state']} | rule engagement (not confirmed hits)",
            (12, frame.height - 18),
            self.cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )
        output = self.cv2.cvtColor(annotated, self.cv2.COLOR_BGR2RGBA)
        return rtc.VideoFrame(
            frame.width, frame.height, rtc.VideoBufferType.RGBA, output.tobytes()
        ), {
            "frame_width": frame.width,
            "frame_height": frame.height,
            "model_version": self.model_version,
            "identity_status": identity,
            "fighters": fighters,
            "signals": signals,
            "inference_ms": inference_ms,
        }

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
