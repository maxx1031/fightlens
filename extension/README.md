# FightLens extension demo

**Previous prototype.** The main desktop/mobile application now runs from the repository root with Next.js. See [the web MVP](../docs/WEB_MVP.md). This extension is retained for reference.

Plasmo + React + TypeScript + shadcn/ui + Recharts. This MVP shows a minimal momentum curve with **simulated data**, not video understanding or a forecast model.

## Run and load in Chrome

From the repository root:

```sh
npm --prefix extension ci
npm --prefix extension run dev
```

1. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**.
2. Select `extension/build/chrome-mv3-dev`.
3. Open or refresh a regular HTTP/HTTPS page after loading the extension.
4. Click the FightLens extension icon, then **Show on this page**.
5. For a self-contained review, click **Open demo room** in the popup. No video is required.

For the production bundle:

```sh
npm --prefix extension run typecheck
npm --prefix extension run build
```

Load `extension/build/chrome-mv3-prod` the same way. Both builds are local/unpacked; this is not a Web Store release.

## Review the experience

- Play the independent 60-second demo, scrub its timeline, or restart it.
- At 00:31–00:34 the curve has a gap and the caption reads “unable to assess”.
- The overlay contains only the curve and playback/source controls. There are no exchange cards or statistics.
- The standard shadcn Neutral light/dark tokens follow the system color scheme.
- Drag the panel by its header, minimize it, close it, and reopen through the popup.
- On a page containing a video, select **Page video** from **Playback source**. Playback, pause, and seek follow that element's timeline. Choosing the source does not read its pixels.
- The demo room can load a local video using a browser object URL. Nothing is uploaded. Select that video in the overlay after it appears.

The demonstration uses anonymous A/B curve directions and a predefined signal. On videos longer than 60 seconds, the sequence repeats against the video clock; this is explicitly labeled in the panel. It does not correspond to actions in the loaded footage. Source changes reset the demo. Scrubbing backward removes later points, and the graph does not draw future points.

## Permission and compatibility scope

The content script matches HTTP and HTTPS pages so it can offer the overlay across websites. Chrome will show website-access permissions when installing. It mounts in a Shadow DOM and stays visually closed until invoked. `activeTab` lets the popup locate the selected tab. There is no storage, analytics, frame capture, remote inference, or external network request in the production application.

Video discovery currently examines the top document only. Cross-origin iframe players, Chrome internal pages, the Web Store, picture-in-picture, and player fullscreen overlays are not covered. A live video without a finite duration has its seek slider disabled. Some site players may override playback/seek controls. Use the demo room for the supported review path.

## Code map

- `content.tsx`: Plasmo content-script UI, stylesheet isolation, open/close messages.
- `popup.tsx`: page launcher and demo-room shortcut.
- `tabs/review.tsx`: self-contained review environment and local video selection.
- `components/FightLensPanel.tsx`: minimal draggable curve panel and playback controls.
- `components/MomentumChart.tsx`: Recharts curve, neutral reference, and observation gaps.
- `components/ui/`: official shadcn/ui New York registry components (Card, Button, Badge, Slider, Select), with their MIT license. Select supports a ShadowRoot portal container; Slider labels its thumb for accessibility.
- `styles/ui.css`: standard Neutral theme tokens and minimal floating positioning.
- `components.json`, `tailwind.config.js`, `postcss.config.js`: shadcn registry configuration and Plasmo's documented Tailwind 3/PostCSS integration.
- `lib/usePlayback.ts`: selected video synchronization and independent demo clock.
- `lib/demo.ts`: deterministic simulated events, bounded signal, and evidence cutoff.
- `lib/types.ts`: proposed analysis snapshot shape for a future adapter. No adapter is connected yet.

The numerical curve is an illustrative momentum index, not win probability, impact force, injury, confidence, or prediction-market advice. Connecting a real model requires an adapter and separately validated event/score semantics.

## Local verification

The shadcn revision passed production Chrome MV3 build and TypeScript checks, plus browser review with Chrome for Testing 155 and the unpacked extension actually loaded. Checks cover removal of exchange/statistic UI, light/dark themes, observation gaps, keyboard seeking, play/pause, minimize/expand and close/reopen, local video playback synchronization, and a Select menu inside the actual content-script ShadowRoot. A synthetic host page with a 10px root font verifies stable 14px overlay text and a 36px Select trigger. A locally generated 12-second video fixture tests playback only; no actual MMA recognition or provider inference is tested.

## Dependency status

Versions are pinned and the npm lockfile is checked in. On October 9, 2026, `npm audit --omit=dev` reported no known runtime dependency vulnerabilities. The full audit reported 84 findings (79 high, 5 moderate) in the development/build dependency tree. Those have not been remediated by upgrading or replacing the requested framework; this scaffold is intended for local demo review.

The UI components come from the [official shadcn registry](https://ui.shadcn.com/r/styles/new-york/button.json); see [theming](https://ui.shadcn.com/docs/theming) and [Plasmo's Tailwind integration](https://docs.plasmo.com/quickstarts/with-tailwindcss). CSS remains inside the content script's ShadowRoot, including the Select popover. The shadow host is mounted inside `body` for Radix's accessible menu containment. Its rem units are fixed to the default 16px scale to avoid shrinking on sites that change the document root font size.
