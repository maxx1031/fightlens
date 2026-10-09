"""Causal, receiver-timed engagement rules. No interpolation or future padding."""

from collections import deque
import math
import numpy as np


def finite(value):
    return float(value) if value is not None and math.isfinite(value) else None


class Engagement:
    def __init__(self):
        self.scales = deque()
        self.smoothing = deque()
        self.previous = None
        self.last_attack = None
        self.state = "FAR"

    def unknown(self):
        self.__init__()
        return {
            "distance": None,
            "reach_a": None,
            "reach_b": None,
            "extension_a": None,
            "extension_b": None,
            "limb_speed": None,
            "engaged": None,
            "state": "UNKNOWN",
        }

    def update(self, t, fighters, identity):
        if identity != "stable" or not fighters.get("A") or not fighters.get("B"):
            return self.unknown()
        k = np.array([fighters[f]["kpts"] for f in ("A", "B")], dtype=float)
        xy = k[..., :2].copy()
        xy[k[..., 2] < 0.3] = np.nan
        # Both shoulders/hips are required to establish a reliable image scale.
        if not np.isfinite(xy[:, [5, 6, 11, 12]]).all():
            return self.unknown()
        hips = xy[:, [11, 12]].mean(axis=1)
        shoulders = xy[:, [5, 6]].mean(axis=1)
        torso = float(np.linalg.norm(shoulders - hips, axis=1).mean())
        if torso <= 1:
            return self.unknown()
        self.scales.append((t, torso))
        while self.scales and self.scales[0][0] < t - 1:
            self.scales.popleft()
        scale = float(np.median([v for _, v in self.scales]))
        distance = float(np.linalg.norm(hips[0] - hips[1]) / scale)
        extension, reach = [], []
        for me in range(2):
            arm = []
            for s, e, w in ((5, 7, 9), (6, 8, 10)):
                if np.isfinite(xy[me, [s, e, w]]).all():
                    length = np.linalg.norm(xy[me, s] - xy[me, e]) + np.linalg.norm(
                        xy[me, e] - xy[me, w]
                    )
                    if length > 1:
                        arm.append(
                            float(np.linalg.norm(xy[me, s] - xy[me, w]) / length)
                        )
            extension.append(max(arm) if arm else None)
            targets = [((shoulders + hips) / 2)[1 - me]]
            if np.isfinite(xy[1 - me, 0]).all():
                targets.append(xy[1 - me, 0])
            distances = [
                float(np.linalg.norm(xy[me, w] - target) / scale)
                for w in (9, 10)
                if np.isfinite(xy[me, w]).all()
                for target in targets
            ]
            reach.append(min(distances) if distances else None)
        relative = xy[:, [9, 10, 15, 16]] - hips[:, None, :]
        speed, approach = None, 0.0
        if self.previous:
            old_t, old_relative, old_distance = self.previous
            dt = t - old_t
            if 0 < dt <= 0.5:
                velocities = (
                    np.linalg.norm(relative - old_relative, axis=-1) / dt / scale
                )
                valid = velocities[np.isfinite(velocities)]
                speed = float(valid.max()) if valid.size else None
                approach = (distance - old_distance) / dt
        self.previous = (t, relative.copy(), distance)
        values = [distance, *reach, *extension, speed, approach]
        self.smoothing.append((t, values))
        while self.smoothing and self.smoothing[0][0] < t - 0.15:
            self.smoothing.popleft()
        smooth = []
        for i in range(len(values)):
            known = [v[i] for _, v in self.smoothing if v[i] is not None]
            smooth.append(float(np.mean(known)) if known else None)
        d, ra, rb, ea, eb, speed, approach = smooth
        ext = max((v for v in (ea, eb) if v is not None), default=0)
        attack = d < 0.9 or (
            d < 2.2 and (ext >= 0.85 or (speed is not None and speed >= 6.5))
        )
        if attack:
            self.last_attack = t
        engaged = self.last_attack is not None and t - self.last_attack <= 1.0
        if engaged:
            self.state = "ENGAGE"
        elif d < (3.1 if self.state in ("RANGE", "ENGAGE") else 2.6) or approach < (
            -0.7 if self.state in ("RANGE", "ENGAGE") else -1.5
        ):
            self.state = "RANGE"
        else:
            self.state = "FAR"
        return {
            "distance": finite(d),
            "reach_a": finite(ra),
            "reach_b": finite(rb),
            "extension_a": finite(ea),
            "extension_b": finite(eb),
            "limb_speed": finite(speed),
            "engaged": int(engaged),
            "state": self.state,
        }
