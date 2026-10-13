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
# 3b. Strike candidates, then Cosmos referee + Jev judgment for the engaged clips and for
#     each kick (prompt = task + this clip's YOLO output). Needs COSMOS3_REASON_URL,
#     GPU_BEARER_TOKEN and OPENROUTER_API_KEY in the repository's .env (git-ignored; never commit it).
for c in pereira_rountree_45s 0_realhuman; do .venv/bin/python hits.py outputs/$c; done
.venv/bin/python referee.py outputs/pereira_rountree_45s --max-seconds 30 \
    --fighter-map '{"A":"white shorts","B":"multicolor patterned shorts"}'
.venv/bin/python referee.py outputs/0_realhuman --max-seconds 15 \
    --fighter-map '{"A":"black hoodie and black cap","B":"white jacket and grey pants"}'
# 3c. Win probability (Luna Decisions via OpenRouter), only for engaged seconds: frames only,
#     then frames + the Cosmos verdicts that had arrived by each second.
UFC=outputs/pereira_rountree_45s; FM='{"A":"white shorts","B":"multicolor patterned shorts"}'
.venv/bin/python win_prob.py $UFC --max-seconds 30 --fighter-map "$FM" --no-cosmos
mv $UFC/win_prob.jsonl $UFC/win_prob.frames_only.jsonl
.venv/bin/python win_prob.py $UFC --max-seconds 30 --fighter-map "$FM" --baseline $UFC/win_prob.frames_only.jsonl
.venv/bin/python win_prob.py outputs/0_realhuman --max-seconds 15 \
    --fighter-map '{"A":"black hoodie and black cap","B":"white jacket and grey pants"}'
# 4. Join the rounds: clip_dir:start:end:title:A name:B name
.venv/bin/python concat.py outputs/demo_ufc_local \
    "outputs/pereira_rountree_45s:0:10:UFC 300 replay:PEREIRA:ROUNTREE" \
    "outputs/0_realhuman:0:15:Local arena:BLACK KIT:WHITE KIT"
# 5. Publish to examples/arcade (data.js, analysis.html, measure.mp4) and open it
.venv/bin/python viewer.py outputs/demo_ufc_local
# 6. Side-by-side page examples/arcade/compare.html: frames only vs frames + Cosmos
ffmpeg -t 30 -i ../data/raw/pereira_rountree_45s.mp4 -c:v libx264 -crf 22 -an ../examples/arcade/ufc.mp4
.venv/bin/python compare.py $UFC --end 30 --video ufc.mp4 --names ROUNTREE PEREIRA \
    --title "PEREIRA vs ROUNTREE JR. · R1"
```

| Script | Output |
| --- | --- |
| `measure.py` | `outputs/<clip>/measure.jsonl` (per frame: `com_dist`, `reach_A/B`, `ext_A/B`), `measure.mp4` (overlay) |
| `engage.py` | `outputs/<clip>/exchange.jsonl` (per frame `engaged` 0/1 and `kick` 0/1), `windows.jsonl` (FAR / RANGE / ENGAGE sampling windows for the video model), `engage.png` (tuning plot) |
| `win_prob.py` | `outputs/<clip>/win_prob.jsonl`: per second, `ok` (sampled) or `held` (not engaged, previous value kept), with both raw answers and the `cosmos_referee` evidence sent |
| `hits.py` | `outputs/<clip>/hits.jsonl`: punch/kick contact candidates by zone (2D geometry) |
| `referee.py` | `outputs/<clip>/referee.jsonl`: per engaged clip (≤ 3 s, 4 fps) and per kick clip (0.8 s, 12 fps, 1280 px), the Cosmos verdict (strikes landed / blocked / missed, advantage, note) and the Jev judgment (direction, evidence) |
| `winprob_server.py` | Local endpoint (127.0.0.1:8787) for the live arcade page: Luna win probability for engaged seconds; the key stays server-side |
| `compare.py` | `examples/arcade/compare_data.js`: both win-probability runs and the Cosmos verdicts for `compare.html` |
| `concat.py` | `outputs/<name>/`: joined `measure.mp4`, data resampled to 30 fps, `segments.json` (rounds), camera cuts |
| `viewer.py` | `examples/arcade/data.js`, `analysis.html` (from `viewer_template.html`), `measure.mp4` |

Each source is tracked and measured on its own, so A/B identity and the
torso scale restart at every join. All distances are divided by the
fighters' mean torso length. `engaged = 1` when someone attacks (arm
extension >= 0.85 or a wrist/ankle speed peak) while the two are within 2.2
torso lengths, or when they are clinched; attacks less than 1 s apart form
one exchange, padded by 0.25 s. Kicks count from farther out: an ankle moving
at >= 7 torso lengths/s while the two are within 3.0 torso lengths (a low kick
reaches the lead leg from outside punching range). Without that rule a low kick
at 0:13 of the UFC clip was never sent to Cosmos; `0_realhuman` is unchanged. Camera cuts are detected from frame
histograms; signals and the torso scale reset at each cut.

`win_prob.py` sends a second to `openai/gpt-6-luna-decisions` only when at
least half of its frames are engaged (10 frames per second sent). Luna strongly
favours whichever fighter is listed as A, so each second is asked twice with
A/B swapped and the answers are averaged. The result is an uncalibrated model
estimate; it also anchors on the previous second, and broadcast graphics can
reveal fighter names.

If `referee.jsonl` exists, every request also carries `cosmos_referee`: the
Cosmos verdicts that had arrived by the end of that second (clip end + measured
Cosmos latency), as a landed / blocked / missed tally per fighter, a log of each
strike's move, target and outcome, and the latest notes. Kicks are counted from
the kick clips where those saw one, everything else from the exchange clips, so
nothing is counted twice. `--no-cosmos` gives the frames-only run; `--baseline`
copies it for the seconds before any Cosmos verdict, where the two requests would
be identical, so the two runs only differ once Cosmos has spoken.

`referee.py` sends each kick as its own short clip (0.4 s either side of the
kick's onset, 12 fps, 1280 px wide). In one longer clip at 4 fps, Cosmos missed
the 0:13 low kick at every frame rate tried; in the short clip it reported it
(blocked). It still did not recognise the 0:24 head kick, and repeated identical
requests at temperature 0 do not always return the same verdict.

These thresholds were tuned on `0_realhuman` against rough hand labels at
0.5 s resolution (89% frame agreement over 0-15 s). That is an in-sample
check, not a measured accuracy; re-check on new footage.
