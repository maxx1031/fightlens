# FightLens web MVP

The main application is Next.js App Router + React + TypeScript + shadcn/ui + Recharts. The home page now defaults to live camera sessions; see [LIVE_SETUP.md](LIVE_SETUP.md) to run LiveKit and the Python receiver. This guide describes the separate **Explore Demo curve / local video** mode. The previous Chrome extension remains in `extension/` as a reference prototype.

## Run locally

From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://localhost:4173`. The old `/tabs/review.html` preview path redirects to `/`.

For a production build:

```sh
pnpm typecheck
pnpm build
pnpm start
```

The local server binds to `0.0.0.0`, so a phone on the same network can open `http://<computer-lan-ip>:4173`. Localhost on a phone points to the phone itself. No hosted deployment is created by these commands.

## Viewing flow

- Choose **Explore Demo curve / local video** on the home page. With no video selected, use the 60-second demo timeline.
- Choose a local video on desktop or mobile; desktop also supports dropping a video into the player card.
- The curve automatically follows that video's play, pause, and seek state.
- Use the native video controls or the curve's play/pause, timeline, and restart controls.
- Choose **Use demo** to remove the selected video and reset to the demo timeline.
- Light/dark Neutral theme follows the operating system. Desktop uses two columns; smaller viewports stack the video above the curve. Controls have larger touch targets on mobile.

There are no event cards, statistics, floating panels, or Chrome APIs in the main application. Files use browser object URLs and are not uploaded. The curve is still simulated, repeats every 60 seconds on longer videos, and does not describe the actions in the selected footage. A gap at demo time 00:31–00:34 means unable to assess. This is not a calibrated prediction or win probability.

## Implementation

- `app/page.tsx` / `app/layout.tsx`: App Router entry, metadata, and mobile viewport.
- `components/FightLensApp.tsx`: responsive viewer, local file picker/drop target, and controls.
- `components/MomentumChart.tsx`: causal demo curve and observation gap.
- `lib/usePlayback.ts`: one explicit video reference and independent demo clock, without scanning the document.
- `lib/demo.ts` / `lib/types.ts`: existing demo generation and future analysis snapshot contract.
- `components/ui/`: official shadcn components with the retained MIT license.

Demo generation and local-file playback stay in the browser. Live mode additionally uses authorized session APIs, LiveKit, and a Python diagnostic receiver. No model endpoint or prediction service is connected; no full-session video is saved.

## Local verification

- `pnpm build` passed, including Next.js compilation, TypeScript checks, and static page generation.
- Production server and the legacy preview redirect returned HTTP 200.
- Chromium at 1440 × 1000 showed two columns; mobile emulation at 390 × 844 showed stacked cards, no horizontal overflow, and 44px touch buttons.
- Demo play/pause, seeking, restart, and the observation gap were checked.
- A local 12-second MP4 played inline, synchronized the curve clock, sought to the end from the chart slider, and returned to the demo at 00:22.
- Both browser sessions reported no console errors or warnings. Physical iOS/Android devices have not been tested.
