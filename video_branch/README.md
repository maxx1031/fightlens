# video_branch

Clip-level verification of attack candidates with a video-understanding model (planned: NVIDIA Cosmos Reason2).

- **Input:** `data/raw/<clip_id>.mp4`, `outputs/<clip_id>/candidates.jsonl` (optionally `tracks.jsonl` for crops and A/B markers)
- **Output:** `outputs/<clip_id>/verdicts.jsonl`
- **Format:** see [Event JSON contract](../README.md#event-json-contract), section 3.

## Plan

1. For each candidate, cut `window_s` (default `t_s - 0.6` to `t_s + 0.3`), 12–20 frames, crop covering both fighters.
2. Ask for structured output: outcome, contact zone, evidence times. Keep the raw response.
3. Measure request latency; confirm the endpoint's real frame sampling rate (default may be 4 FPS).

Until candidates exist, a hand-written `candidates.jsonl` with a few known timestamps is enough to develop against.
