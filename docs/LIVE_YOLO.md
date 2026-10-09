# Local YOLO acceptance

Implemented on October 9, 2026: camera → LiveKit → Python YOLO Pose/ByteTrack → annotated LiveKit video → frontend. Structured pose results drive a bounded engagement curve. No full-session recording is performed.

## Run and review

```sh
pnpm install --frozen-lockfile
pnpm live:setup
pnpm build
pnpm live:start
```

Open `http://localhost:4173` in Chrome. Choose **Use this camera**, **Enable camera**, then **Start live**. Keep two people fully visible. The lower **YOLO video** is the worker's returned WebRTC track, independent of the local preview. **Original video** switches to the camera track for comparison. **Live engagement** reports a rule signal, not confirmed hits, damage, win probability, or calibrated momentum.

Setup installs locked Python dependencies and downloads/checks the configured model into ignored `models/`. This version uses `yolo11n-pose.pt`, Ultralytics 8.4.174, Torch 2.14.1, and the pinned LiveKit RTC SDK. The model runs locally. On this Mac, `auto` selects MPS; elsewhere it falls back to CPU. First setup requires network access for dependencies/weights.

Optional server-only settings in `.env.local`:

```dotenv
FIGHTLENS_YOLO_MODEL=yolo11n-pose.pt
FIGHTLENS_YOLO_DEVICE=auto
FIGHTLENS_YOLO_FPS=15
```

Use `cpu` explicitly if MPS initialization fails. Restart the stack after changing settings. The local demo admits one active session to avoid sharing mutable trackers or overcommitting the single inference executor. Leaving a publishing page releases capture and requests session termination; leaving a separate viewer does not stop a paired publisher.

## Acceptance checklist

1. Confirm that moving people produce new YOLO boxes/keypoints and A/B labels on the returned video. The identities are geometric tracker assignments and require visual review.
2. Select **Pause analysis**. The same worker video track continues with new, unannotated frames; analysis count stops, the latest pose clears, and the curve has a gap. An in-flight result from before the command cannot enter the current analysis revision.
3. Resume. The motion/tracker state restarts on fresh frames; skipped footage is not replayed. New results carry the new analysis revision.
4. Switch cameras or rotate the camera. A new segment invalidates old results and resets the live tracker/rule state.
5. Select **Stop live**. Camera and viewer references are released and the session cannot resume. Start a new session for another broadcast.
6. Check **Curve follows rendered YOLO frame IDs**. If browser metadata support is unavailable, the UI labels the curve as receiver-relative and unaligned instead. Physical iOS/Android metadata support remains unverified.

Phone QR pairing continues to use the setup in [LIVE_SETUP.md](LIVE_SETUP.md). The default local media server binds to localhost; physical phones still need trusted HTTPS/WSS and reachable RTC/TURN media.

## Streaming behavior

- The original camera receiver drains independently of inference. One SDK waiting frame and one application waiting frame are retained, alongside the active model request. Old waiting input is replaced; reported queue drops include this intentional analysis sampling.
- A single executor serializes model/tracker operations. Models remain loaded across sessions; tracker and rule state reset by session, video segment, and analysis revision.
- While loading, paused, or failed, the worker passes new frames through its existing output track. Stale annotated frames/results are discarded. Analysis failure is visibly reported.
- Control permissions refresh every 200 ms, with the existing five-second lease. Diagnostics publish every 500 ms; pose results publish independently. Pause/resume is acknowledged from worker status.
- Worker video grants allow camera-source publication without administration/recording privileges. Frontend subscription is restricted to the server-registered output SID and worker identity. The worker subscribes only to the admitted original publisher, preventing a feedback loop.
- Pose messages use the live `fightlens.live.v1` envelope and a distinct `pose_frame` schema; the existing offline event JSON v0.1 contract is unchanged. Both REST snapshots and LiveKit packets validate session, source/segment, worker generation, analysis revision, and output SID. History retains at most 600 points from the latest 60 seconds; no historical pixels are retained.
- The output video's `frame_id` correlates the rendered frame with curve results. Capture wall-clock timestamps remain unavailable; worker timing uses a receiver monotonic clock.

## Causal engagement adapter

The live adapter reuses the pose branch's identity parsing/drawing and implements incremental rules in `worker/engagement.py`. It computes torso-normalized distance, reach, arm extension, and hip-relative limb speed. Derivatives use actual elapsed time, not a presumed processing FPS. Scale uses at most one second of past samples; signal smoothing uses the previous 150 ms.

No future-frame interpolation, centered gradients, or backward exchange padding is used. Missing geometry or uncertain identity produces `UNKNOWN` and a null curve value. An observed attack/clinch starts engagement immediately; a one-second hold merges closely spaced attacks and delays end confirmation. Thresholds are inherited heuristics, not independently validated strike detection. Distances/0–1 states do not establish contact.

## Measurements and verification

Local test environment: macOS 26.2 arm64, Chromium 155.0.8059.12, localhost LiveKit 1.13.9, MPS, 1280×720 test input. No physical camera or cross-network test is claimed.

The display-latency test embedded a 12-bit frame clock in a browser Canvas fed by the repository-linked Pereira/Rountree clip. The Canvas was published through the actual application and processed by the real model. The clock was read from the returned video inside `requestVideoFrameCallback`; sender and receiver used the same browser performance clock. This measures browser source generation → two WebRTC legs + inference → rendered processed video. It excludes physical camera sensor/capture latency and model cold start.

| Observation | Result |
| --- | --- |
| Display latency samples | 285 distinct rendered frames over about 20 seconds |
| Display latency p50 / p95 / max | 244.5 / 316.2 / 449.9 ms |
| Sampled original receive FPS | 23.0–30.6 |
| Sampled processed output FPS | 12.0–15.1 (15 FPS configured ceiling) |
| Sampled model/pose processing time | 18.8–46.3 ms |
| Sampled worker arrival → annotated-frame submission | 28.6–72.9 ms |
| Daemon peak RSS during the sample window | 559.3 MB, unchanged |
| Rendered frame-ID alignment | Observed working in Chromium |
| Observed engagement outputs | 0, 1, and null for uncertain tracking |

An earlier direct-model check measured the first tracking call at about 695 ms and subsequent calls at 14–30 ms on a different fixture. These are limited local observations, not hardware guarantees or inference accuracy results.

Pause verification: worker acknowledgment observed in 314 ms; over the following 2.5 seconds the same output track rendered 75 new frames and analyzed-frame count stayed fixed. Resume changed the analysis revision, restored pose results, and retained a null interval. Original/YOLO switching, camera release, 320/390/844px layouts, and 44px controls passed.

QR pairing was also exercised with separate owner/publisher browser contexts and a mobile viewport. The paired publisher received YOLO video; after owner pause its video advanced by 33 frames in 1.5 seconds. Leaving the publishing page via client navigation ended the owner's session and changed the captured camera track to `ended`. This remains browser emulation, not a physical-phone test.

Build, TypeScript, the API regression script, and five causal-rule tests passed. Tests cover future attacks not rewriting earlier values, correct derivatives across sampling intervals, missing-pose gaps, uncertain identities, and one-second end confirmation. Inference quality, robust referee exclusion/A/B identity, real-phone behavior, WAN/TURN, and physical-camera end-to-end latency require separate validation.

Ignored evidence: `output/playwright/yolo-latency.json`, `yolo-clean-desktop.png`, `yolo-live-mobile.png`, camera fixtures, and model weights. No test-only pixel-clock code is shipped in the application.
