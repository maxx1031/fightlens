# Local caption integration verification

October 9, 2026. This is a synthetic-camera and fake-endpoint integration check.
No real Cosmos inference, real fight classification, physical phone, or TURN
acceptance is claimed.

## Complete path

The production Next.js build was served on localhost with a dedicated LiveKit
server and the Python receiver. Chromium 155 used a synthetic 1280×720 camera
at 20 FPS. The repository's `fake_cosmos.py` ran with a one-second reply delay
and `<think>` wrapping; provider credentials were empty in the fixture process.

The browser created a session, confirmed A/B appearance descriptions, enabled
the synthetic camera, and started publication. The viewer independently rendered
received video; the Python receiver decoded its frames and submitted sampled
temporal `video_frames` windows. The fake note appeared directly underneath the
received video with **Fake endpoint · demo**, its reviewed interval, and request
duration. Backend sample status showed 20.0 FPS, 1280×720, and zero application
queue drops at the inspected moments. These samples are not a sustained latency
benchmark or evidence that the fake model watched the footage.

- Pause cleared caption text while video and frame counts continued.
- Resume produced a caption using fresh post-resume samples.
- Switching camera facing allocated a different segment, reset receiver-time
  progress, and produced captions for the new segment.
- End session cleared caption text and both browser video `srcObject` values.
- At 390px, document width and scroll width were both 390px. Caption text wrapped
  within the video card. No browser console errors or warnings were observed.

Ignored screenshots: `output/playwright/cosmos-caption-desktop.png` and
`output/playwright/cosmos-caption-mobile.png`. All synthetic media artifacts and
dedicated service settings stay outside Git.

## Automated checks

- Eight live-caption tests: bounded backlog/skip accounting, pause/resume,
  source-change cancellation, expired-lease suppression, unconfigured identity
  states, repository fake HTTP transport, safe provider failure/recovery, and RTC
  pixel conversion/downscaling.
- The 63 existing Cosmos and smoke-script tests passed after making the offline
  Cosmos modules importable by the worker.
- Caption API checks passed for worker authentication, identity requirements,
  schema validation, duplicate/regressing updates, source generations,
  pause/resume revisions, and terminal sessions.
- Existing live API checks include publisher denial for caption identity edits.
- Typechecking, the production build, Python compilation, and diff whitespace
  checks passed.
- Local setup was checked with an environment file containing only a fixture
  Cosmos token: it preserved that token, appended missing service settings, and
  retained file mode 0600.

See [the integration contract and configuration](COSMOS_CAPTIONS.md). Remaining
acceptance includes the real endpoint's `video_frames` behavior, accuracy and
uncertainty on fight footage, real throughput/latency, and cross-device timing.

## Combined YOLO and caption pipeline — local acceptance

October 9, 2026, after merging PR #7 into the local `codex/english-prd` checkout.
The active camera stream now feeds two independent consumers: YOLO inference
with annotated WebRTC return video, and bounded JPEG sampling with asynchronous
Cosmos review. Caption identity edits use `captionRevision`; they do not reset
YOLO's `analysisRevision`, pose sequence, output track, or engagement history.

Verified against the production build with a file-backed Chromium camera using
recorded fight footage and the repository fake Cosmos endpoint (one-second
response delay):

- A caption appeared below the received YOLO video with its actual sampled
  receiver-time interval and **Fake endpoint · demo** label. Recorded images are
  real YOLO input; fake captions do not analyze them.
- Both 1440px desktop and 390px mobile layouts rendered without horizontal
  overflow. Dark mode remained the default.
- Editing descriptions cleared the old caption and advanced only the caption
  revision while the existing YOLO pose sequence and output track continued.
- Pause cleared commentary; returned video continued decoding. Resume produced
  a new caption from later footage with the current analysis revision.
- Changing camera facing changed the segment and cleared old text; the next
  caption carried the new segment. This checks camera reacquisition using a
  synthetic device, not switching physical phone lenses.
- End cleared captions and released the returned video element's `srcObject`.
- An inspected sample reported YOLO output at 14.9 FPS, a 12-frame caption
  window, and 1003.4ms fake review duration. This is not a sustained benchmark
  or real Cosmos latency measurement.
- No browser errors were recorded. Next.js emitted unused CSS-preload warnings
  during route prefetching.

Automated validation: production build, TypeScript checking, three replay tests,
and 72 Python tests covering the live caption/engagement modules, existing
Cosmos branch, and video-understanding script. Caption API checks on an isolated
control server additionally verified caption-revision rejection and preservation
of YOLO pose/history during identity edits. Live API checks passed against the
combined stack. Local credentials were not changed.

Ignored review screenshots: `output/playwright/pr7-caption-desktop.png` and
`output/playwright/pr7-caption-mobile.png`.

For local review, run `pnpm build` followed by `pnpm live:demo`, open the camera
page, confirm fighter descriptions, enable the camera, and select **Start live**.
The demo launcher overrides provider settings only in child processes and
starts its own fake endpoint. Normal `pnpm live:start` uses configured Cosmos
settings; neither `.env.local`, `.env`, nor shell environment had a real Cosmos
URL or token configured during this acceptance run. Real endpoint compatibility,
caption accuracy, physical phones, and TURN remain unverified.
