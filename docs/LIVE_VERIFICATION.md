# Local live MVP verification

October 9, 2026. This is transport/diagnostic evidence, not model validation or physical-phone acceptance.

## Environment

macOS 26.2 arm64; Chromium 155.0.8059.12 with a synthetic 1280×720, 30 FPS camera fixture. Next.js 16.4.0, React 19.3.0, LiveKit server 1.13.9, browser SDK 2.22.4, server SDK 2.19.1, Python 3.12.12, Python RTC SDK 1.1.20. Media ran directly on localhost. No real camera footage was used or saved.

## Measured receive run

The desktop publisher and independent viewer connections were exercised with the Python receiver. After a deliberately expired worker lease recovered into generation 2 and a new segment, 25 status samples were collected over 120.144 seconds:

| Measurement | Observed |
| --- | --- |
| Backend frame rate | 29.0–30.1 FPS |
| Backend resolution | 1280×720 in every sample |
| Backend frame count | 1,591 → 5,206 |
| Application queue depth | 0 at sample times |
| Application-queue dropped frames | 0 reported |
| Worker daemon peak RSS | 112.8 MB throughout the sample window |
| Most recent frame age | At most 36.5 ms at sample times |
| Viewer decoded resolution / codec | 1280×720 / VP8 |
| Segment / worker generation | Unchanged during the measured window |

One desktop connection attempt reached both acknowledgments in about 3.2 seconds. This is a single setup observation, not a latency percentile or capture-to-display measurement. The memory value is peak RSS for the complete daemon, including earlier sessions. Periodic samples cannot establish zero network/SDK frame drops or absence of every transient queue/gap. No claim is made about phone/network performance or inference suitability beyond this fixture.

An earlier run with the browser's default degradation policy stabilized at 960×540. The final publisher prefers retaining capture resolution, uses one video layer, and retains codec negotiation. Actual FPS/resolution remain visible; lower quality is not hidden.

Ignored local artifacts: `output/playwright/desktop-receive-samples.json`, desktop/mobile screenshots, and browser session logs. The synthetic fixture and artifacts stay outside Git.

## Behavior checks

- Actual remote video rendering and Python decoded frames independently reached their receiving states. Reliable LiveKit status messages and REST snapshots both supplied UI diagnostics.
- Pause left frames advancing while diagnostic processing time stayed fixed; resume advanced processing again.
- Changing camera facing released the previous MediaStreamTrack and started a different segment. Viewer retry rejoined without ending the publisher.
- Owner stop released the publisher track, cleared both local and remote video stream references, and ended the session. Publisher stop and repeated terminal API calls also passed.
- A simulated worker outage showed **Backend frames stale** while the viewer kept receiving video. After lease expiry, recovery changed worker generation 1 → 2 and allocated a different segment before accepting new results.
- Restarting the control service invalidated the old session. The publishing page displayed an expired-session message, released its still-live camera track, and cleared both video stream references. Terminal sessions stop polling once media cleanup is complete.
- Pairing was tested with independent browser contexts: owner-generated invitation, publisher redemption, fragment removal, remote viewing, backend receipt, and owner-initiated camera release. This used a Chromium mobile viewport and synthetic camera; it was not an iPhone/Android device test.
- At 320px portrait and 844px landscape, the publisher page had no horizontal overflow and buttons were at least 44px high. A 390×844 capture also rendered successfully. Desktop used two columns.
- Live mode contained no numeric momentum or Demo curve. The separate Demo/local-file flow remains available from home.

## Build and API checks

`pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm build`, Python compilation, and `git diff --check` passed. The production live stack served the pages and APIs.

`pnpm live:check` passed against the running stack. It covers unauthenticated session/internal access, incorrect origins, oversized/invalid requests, session-create retry, pairing-command retry, simultaneous invitation claims, rejected owner publication after phone pairing, rejected publisher analysis/pairing commands, explicit viewer/publisher JWT grants, repeated stop, and denied joins after stop. Tokens and pairing secrets are excluded from test output.

## Remaining acceptance

Physical iOS Safari and Android Chrome, denied/occupied real camera permissions, screen locking/backgrounding, cellular-to-desktop media, forced TURN relay, cross-device clock mapping, and hosting-specific cached-token revocation remain unverified. The local server configuration does not expose media to phones. Use the HTTPS/WSS/network setup in [LIVE_SETUP.md](LIVE_SETUP.md) before those tests.

Tracking, strike/contact verification, Jev, calibrated numeric momentum, model latency/accuracy, and evidence replay are delivery C or later. No analysis model or full-session recording was added.
