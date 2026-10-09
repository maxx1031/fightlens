# frontend

Viewer for one clip: video with A/B overlays, one received-strike heatmap per fighter, timestamped event list, and evidence replay.

- **Input:** `data/raw/<clip_id>.mp4`, `outputs/<clip_id>/tracks.jsonl`, `outputs/<clip_id>/events.json`
- **Format:** see [Event JSON contract](../README.md#event-json-contract), sections 1 and 4.

## Notes

- Sync overlays by `t_s` / `frame_idx` against the video's current time.
- Replace events by `event_id`; recompute heatmap totals from `events` (only `accepted` + `landed`).
- Develop against [`examples/contract/`](../examples/contract/) before real outputs exist. The scripted visual style reference is [`examples/index.html`](../examples/index.html).
