# Live exchange advantage

The Next.js live viewer can show typed exchange judgments from `cloudflare/clef-flash` through OpenRouter Decisions. The stepped curve has three categorical levels: A advantage, balanced, B advantage. Its height is a direction label, not advantage strength, win probability, damage, or judging score. Engagement remains available under **Engagement diagnostics**. The separate Demo/local-file curve stays simulated.

## Enable

Set server-only values in `.env.local` or the receiver's environment, then restart the receiver:

```dotenv
OPENROUTER_API_KEY=your-key
FIGHTLENS_JUDGMENTS_ENABLED=1
FIGHTLENS_DECISION_MODEL=cloudflare/clef-flash
FIGHTLENS_DECISIONS_URL=https://openrouter.ai/api/alpha/decisions
FIGHTLENS_DECISION_TIMEOUT_S=15
```

Start the normal live stack and confirm distinct A/B appearance descriptions below the received video. These descriptions are shared with Cosmos. No predictions start without explicit enablement, a provider key, and confirmed identities. Captions need not be configured. Changing descriptions clears judgments and cancels pending work, while preserving the YOLO diagnostics.

Frames leave the device through LiveKit and selected JPEGs are sent to OpenRouter. Short evidence buffers are in memory; this path does not save video or raw provider replies. Provider retention is separate from app buffering.

## Evidence and questions

The worker samples processed pose frames at up to 4 FPS, with a one-second preceding buffer. A stable-identity engagement starts an exchange window. The window closes after at least 0.75 seconds of sampled non-engagement following the last engaged sample. This is **in addition to** the existing engagement rule's hold. Actual first/last sample times are retained.

The collecting window is limited to 8 seconds and 40 resized JPEGs. Exchanges exceeding that limit become gaps and require a new idle-to-engaged transition. A sample gap exceeding one second, unknown geometry, or uncertain/lost tracking invalidates the current exchange and cancels outstanding work. The pose identity heuristic does not guarantee semantic A/B identity; confirm descriptions and review the video.

One model request runs at a time. Only one complete window waits behind it; newer waiting windows replace older ones, with an explicit skipped count and gap. The report outbox holds at most 60 events and retries only delivery to the internal API. Model failures expose safe error codes, create a gap, and do not retry the provider call; the next exchange can recover. Provider timeout is bounded to 1–30 seconds. Video reception, YOLO, captions, and provider requests run in separate tasks.

Two independent Choice questions share the same ordered image evidence:

- Direction: `favors_A`, `favors_B`, `no_clear_advantage`, `insufficient_evidence`.
- Evidence: `contact_only`, `observable_reaction`, `sustained_change`, `no_confirmed_effect`, `insufficient_evidence`.

No prior judgment is included in the request. Instructions exclude odds, records, broadcast names, commentary, known outcomes, inferred injury/force, and unsupported ground/submission action. Ground/legality/occluded-counter limits are model instructions, not separate validated detectors. Full distributions and reported confidence are kept in the result; confidence is not converted to curve strength. Either insufficient-evidence answer suppresses the curve value. A balanced judgment is distinct from unavailable evidence.

## Delivery and timing

`POST /api/internal/sessions/:id/judgments` uses the existing worker bearer credential and daemon lease. `fightlens.judgment.v1` packets carry session/source/worker/segment generations, analysis and identity revisions, and an increasing transport sequence. Old generations, identity changes, paused work, and ended sessions reject results. Result IDs and revisions deduplicate transport repeats and replace revised ledger entries. The in-memory ledger retains at most 120 events covering the most recent 60 seconds of result availability.

Each result records its evidence interval, model/prompt version, worker ready time, receiver-relative availability, server acceptance time, distributions, and reported confidence. The viewer separately records the first displayed time and receiver position. A delayed answer or revision adds a new displayed step at that position; it does not backfill an earlier live step. When rendered YOLO frame metadata is available, results wait until that receiver position is displayed. Otherwise the clock is explicitly receiver-relative and unaligned. These are not camera capture-to-display measurements.

Missing coverage, pending exchange assessment, errors, pauses, and insufficient evidence produce gaps. Results expire after 10 seconds without a new assessment, instead of being held indefinitely. Pause/resume preserves prior history and inserts a break. Segment/worker changes and identity edits reset the applicable history. Evidence intervals and uncertainty are accessible from **Exchange evidence and uncertainty**; live evidence video replay is not implemented. First-display history is local to the current viewer mount and is not a durable audit log.

## Verification

```sh
pnpm judgments:test
pnpm typecheck
# Against a dedicated test service, without a competing receiver:
FIGHTLENS_TEST_URL=http://127.0.0.1:4393 pnpm judgments:check
```

Tests cover evidence boundaries, bounded backlog, cancellation on identity/source/analysis changes, expired leases, safe HTTP failures, malformed distributions, deduplication, revisions, gaps, and late-result timing. No calibrated numeric momentum policy is included.

### October 9, 2026 local runtime checks

A recorded-footage camera fixture exercised the actual browser → LiveKit → YOLO
→ JPEG window → local Decisions HTTP fixture → authenticated internal API →
live curve path. A controlled eight-second loop retained moving footage at the
start and froze its final frame to allow short exchanges to close; this is an
edited integration fixture, not natural-fight quality validation. Over 39.2
seconds the returned video advanced, 579 additional frames were analyzed, and
six judgments displayed A advantage, B advantage, and balanced states.

Pausing during assessment advanced video while adding zero analyzed frames or
new judgments; resume accepted fresh results in a new analysis revision.
Changing appearance descriptions cleared judgments/history while YOLO kept
processing. Ending the test released video and the single live-session slot.
An uncontrolled footage loop with unstable identities correctly withheld
provider requests.

A separate, single real OpenRouter request used the shipped `LiveDecisions`
client with ten timestamped JPEGs from the recorded test footage and
`cloudflare/clef-flash`. HTTP 200 returned valid typed distributions for both
questions in 2,562 ms including the local test proxy. Both answers selected
`insufficient_evidence`. This confirms one multimodal provider request and
strict response parsing, not real-provider browser-to-curve acceptance,
predictive accuracy, or a latency percentile. The user's live camera was not
used for this provider check. Physical-camera startup/video return is recorded
in [LIVE_VERIFICATION.md](LIVE_VERIFICATION.md).
