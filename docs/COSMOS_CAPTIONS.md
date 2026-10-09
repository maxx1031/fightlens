# Live Cosmos captions

The session viewer displays a Cosmos exchange note directly below its received
video. This is delayed commentary about a short, timestamped window, not a
subtitle synchronized to the currently displayed frame. It does not update
strike counts, heatmaps, momentum, probabilities, or market prices.

## Run locally

Start the normal stack with `pnpm live:setup` and `pnpm live:dev`. The receiver
loads server-only configuration from `.env.local`, then `.env` as a fallback;
shell variables take precedence. Without a URL, it reports that captions are
not configured and continues receiving video.

To use the repository's fake endpoint:

```sh
uv run --project worker --frozen python cosmos_branch/fake_cosmos.py --delay 1 --think
```

In another terminal, run the stack with empty provider credentials:

```sh
GPU_BEARER_TOKEN= COSMOS_API_KEY= COSMOS3_REASON_MODEL= \
COSMOS3_REASON_URL=http://127.0.0.1:9001 pnpm live:dev
```

Create a session, confirm distinct A/B appearance descriptions beneath the
video, and publish a camera. The fake endpoint returns text beginning with
`(fake)` and model `fake/cosmos3-reason`; the UI additionally labels it
**Fake endpoint · demo**. It does not inspect pixels. Fake captions are pipeline
fixtures, not observations of the footage.

For a real endpoint, set `COSMOS3_REASON_URL` and optionally
`COSMOS3_REASON_MODEL`; otherwise the worker discovers the model via
`GET /v1/models`. `GPU_BEARER_TOKEN` takes precedence over `COSMOS_API_KEY`.
`COSMOS_API_BASE` and `COSMOS_MODEL` are accepted aliases. Credentials never
enter browser configuration, caption packets, or error messages. Real endpoint
compatibility and fight-caption quality need separate validation.

## Processing and limits

- LiveKit reception and diagnostics continue independently of model requests.
- The receiver samples at `FIGHTLENS_CAPTION_FPS` (default 4, bounded 1–6) into
  fixed `FIGHTLENS_CAPTION_WINDOW_S` buckets (default 3 seconds, bounded 1–6).
  A window is submitted when its bucket has ended; at least two samples are
  required. Partial windows with fewer samples are counted as skipped. The
  reported interval uses the first and last actual sample.
- Samples are JPEGs at up to 640×480 plus a timestamp strip. A window retains
  at most 36 frames. Each receiver holds one collecting window, one waiting
  window, and one active window. A newer waiting window replaces an older one;
  the UI reports the number skipped.
- One model request runs at a time across the daemon. Requests use temporal
  `video_frames` with ordered JPEG data URIs and the existing Cosmos exchange
  prompt/parser. The note is displayed directly, without a second narrator call.
- `COSMOS_TIMEOUT_S` defaults to 30 seconds and is bounded to 1–120 for live
  calls. Failed calls do not retry the same window; the next window can recover.
  HTTP/decoding failures expose only a safe error code.
- Pixels and raw model replies are not saved. Short samples leave the device
  through LiveKit and are sent to the configured Cosmos endpoint. External
  provider retention is separate from this app's in-memory buffer.
- The model uses owner-confirmed appearance descriptions, not screen-left/right
  identity. Uncertain identity/contact should be stated in the note. No automatic
  identity-verification guarantee is made.

## Delivery contract

The owner sets identities with `POST /api/sessions/:id/caption-settings`, using
the normal owner cookie, origin check, and `requestId`, plus `A` and `B` strings
(2–160 characters, distinct after trimming/case folding). Publisher credentials
cannot change descriptions.

The worker posts `fightlens.caption.v1` to
`POST /api/internal/sessions/:id/captions`, using the existing worker bearer
credential and current `X-Worker-Instance` lease. Packets include:

- `session_id`, `source_generation`, `worker_generation`, `segment_id`,
  `analysis_revision`, and increasing `seq`.
- `status`: `not_configured`, `awaiting_identity`, `buffering`, `reviewing`,
  `ready`, `error`, or `paused`; `skipped_windows` and a safe `error_code`.
- `caption`: null or `{id, t0_s, t1_s, text, model, latency_ms, ready_at, frames}`.

The latest accepted packet is returned in the authorized session snapshot and
rendered by the existing one-second polling path. A previous successful caption
can remain while the next window is reviewing or fails; the UI identifies it as
earlier footage. It labels stale reception rather than presenting old text as
current commentary.

Pause/resume and identity changes advance `analysisRevision`, clear buffers and
the visible result, and cancel in-flight requests. Source/segment/worker changes
also clear captions. Both Python and the API reject old-generation results.
Repeated or lower-sequence packets and regressing result intervals are ignored;
ended sessions reject updates. Receiver time is not a capture/display clock.

## Checks

`pnpm captions:test` exercises bounded backlog, pause/resume and source-change
cancellation, real RTC pixel conversion, fake HTTP transport, and safe errors.
`pnpm captions:check` exercises the authenticated API against a **dedicated**
test Next.js/LiveKit service with no receiver daemon competing for its lease.
Load its service environment and set `FIGHTLENS_TEST_URL` first. The API check
creates and ends a fixture session; it does not call a real provider.

Typechecking and the production build cover the viewer. Browser verification
must additionally establish camera frames → Python samples → fake Cosmos →
authenticated update → visible caption, then pause/stop behavior. These checks
establish integration behavior only; a fake endpoint cannot validate accuracy,
real-provider latency, physical-phone behavior, or subtitle synchronization.
