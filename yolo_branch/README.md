# yolo_branch

Fighter detection, pose, tracking, and attack-candidate generation.

- **Input:** `data/raw/<clip_id>.mp4`
- **Output:** `outputs/<clip_id>/tracks.jsonl`, `outputs/<clip_id>/candidates.jsonl`
- **Format:** see [Event JSON contract](../README.md#event-json-contract), sections 1 and 2.

## Plan

1. `yolo11n-pose` + ByteTrack on the first 10 seconds; render an overlay video to check A/B identity and wrist/ankle tracking.
2. Manual A/B assignment on the first frame; keep the track-ID → A/B mapping through occlusions; set `identity_status` when unsure.
3. Per-limb state machine (ready → approaching → candidate → retracting) to emit candidates.

Model weights (`*.pt`) and outputs stay out of Git.
