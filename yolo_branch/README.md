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

## Runnable ten-second pose branch

```bash
python3 -m venv yolo_branch/.venv
yolo_branch/.venv/bin/python -m pip install ultralytics lap
yolo_branch/.venv/bin/python yolo_branch/track.py data/raw/pereira_rountree_45s.mp4 data/raw/holloway_gaethje_20s.mp4
```

`track.py` uses `yolo26n-pose.pt` (YOLO11 nano pose fallback if loading fails),
MPS when available, and persistent ByteTrack. All tunable thresholds are at the
top. In the first three seconds, candidate pairs must co-occur for 0.3 seconds;
pairs within 10% of the longest minimum individual presence compete by mean
center distance. Tracks whose median box area is below 30% of the largest
track's are excluded first, so background bystanders cannot be paired. A is leftmost at the selected pair's first shared frame.
Missing IDs reconnect by nearest previous center with one-to-one assignment,
a 20% image-diagonal gate, a 0.4–6.0 bounding-box area ratio gate, and a one-second gap limit. This geometric heuristic
does not establish semantic identity; referee exclusion and identity switches
must be reviewed visually.

Each clip writes to `outputs/<video-stem>/`: H.264/yuv420p `annotated.mp4`,
`keypoints.jsonl`, all-person `detections.jsonl`, review contact sheets, and
`summary.json`. Keypoints use original-frame pixel coordinates and COCO's
17-point order; missing people have null xy, zero confidence, and missing
status. Mean confidence covers all 17 points of observed people, with missing
frames excluded. `tracking_fps` includes model calls and MPS synchronization,
including first-call warmup; `end_to_end_fps` also includes decoding, rendering,
and encoding, but excludes model download/loading. ID reconnections are logged
separately from missing intervals and do not by themselves prove identity swaps.
The output video is silent and opens with macOS `open` after encoding.

## Demo: UFC round + local round in the arcade HUD

```bash
cd yolo_branch
# 1. Track each source on its own (default 10 s)
.venv/bin/python track.py ../data/raw/pereira_rountree_45s.mp4
.venv/bin/python track.py --seconds 25 ../examples/0_realhuman.mp4
# 2. Distances and 3. engagement 0/1, per source
for c in pereira_rountree_45s 0_realhuman; do
  .venv/bin/python measure.py outputs/$c && .venv/bin/python engage.py outputs/$c
done
# 3b. Win probability (Luna Decisions via OpenRouter), only for engaged seconds.
#     Needs OPENROUTER_API_KEY in the repository's .env (git-ignored; never commit it).
.venv/bin/python win_prob.py outputs/pereira_rountree_45s --max-seconds 10 \
    --fighter-map '{"A":"white shorts","B":"multicolor patterned shorts"}'
.venv/bin/python win_prob.py outputs/0_realhuman --max-seconds 15 \
    --fighter-map '{"A":"black hoodie and black cap","B":"white jacket and grey pants"}'
# 4. Join the rounds: clip_dir:start:end:title:A name:B name
.venv/bin/python concat.py outputs/demo_ufc_local \
    "outputs/pereira_rountree_45s:0:10:UFC 300 replay:PEREIRA:ROUNTREE" \
    "outputs/0_realhuman:0:15:Local arena:BLACK KIT:WHITE KIT"
# 5. Publish to examples/arcade (data.js, analysis.html, measure.mp4) and open it
.venv/bin/python viewer.py outputs/demo_ufc_local
```

| Script | Output |
| --- | --- |
| `measure.py` | `outputs/<clip>/measure.jsonl` (per frame: `com_dist`, `reach_A/B`, `ext_A/B`), `measure.mp4` (overlay) |
| `engage.py` | `outputs/<clip>/exchange.jsonl` (per frame `engaged` 0/1), `windows.jsonl` (FAR / RANGE / ENGAGE sampling windows for the video model), `engage.png` (tuning plot) |
| `win_prob.py` | `outputs/<clip>/win_prob.jsonl`: per second, `ok` (sampled) or `held` (not engaged, previous value kept), with both raw answers |
| `concat.py` | `outputs/<name>/`: joined `measure.mp4`, data resampled to 30 fps, `segments.json` (rounds), camera cuts |
| `viewer.py` | `examples/arcade/data.js`, `analysis.html` (from `viewer_template.html`), `measure.mp4` |

Each source is tracked and measured on its own, so A/B identity and the
torso scale restart at every join. All distances are divided by the
fighters' mean torso length. `engaged = 1` when someone attacks (arm
extension >= 0.85 or a wrist/ankle speed peak) while the two are within 2.2
torso lengths, or when they are clinched; attacks less than 1 s apart form
one exchange, padded by 0.25 s. Camera cuts are detected from frame
histograms; signals and the torso scale reset at each cut.

`win_prob.py` sends a second to `openai/gpt-6-luna-decisions` only when at
least half of its frames are engaged (10 frames per second sent). Luna strongly
favours whichever fighter is listed as A, so each second is asked twice with
A/B swapped and the answers are averaged. The result is an uncalibrated model
estimate; it also anchors on the previous second, and broadcast graphics can
reveal fighter names.

These thresholds were tuned on `0_realhuman` against rough hand labels at
0.5 s resolution (89% frame agreement over 0-15 s). That is an in-sample
check, not a measured accuracy; re-check on new footage.
