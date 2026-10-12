# FightLens frontend

Local review prototype built with Next.js, React, Three.js, and the default shadcn/ui neutral theme. Dark and light themes share the stock shadcn tokens; fighter colors and impact effects are local semantic accents.

## Run

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:3000. `predev` and `prebuild` copy the tracked replay from `examples/arcade/measure.mp4` into the ignored `public/demo/` directory. The viewer uses only the local-sparring segment, source-video seconds 10–25. No additional media download or API credentials are needed.

For a production preview, run `npm run build`, then `npm start`.

## Review interactions

- Play, pause, restart, change playback speed, or drag the replay slider.
- Select a timestamp marker or exchange row to seek and inspect the event. Landed events flash the receiving body zone; blocked events animate a shield and do not add heat.
- Select a mannequin zone or its labeled region button to filter the exchange list. Select the same region again or clear the filter to restore all events.
- Replay the selected exchange from just before its timestamp.
- Click the market chart or focus it and use arrow keys to move the shared replay cursor. Switch between the full clip and the preceding five seconds.
- Use the header theme button to inspect both default shadcn themes. The question-mark menu explains data sources.

## Data and scope

The video is recorded footage with precomputed pose overlays baked in. **Contact events and market quotes are independent, scripted fixtures**, not observations of this footage, classifier output, live market prices, or model win-probability estimates. The interface labels both fixture sources. The sample video has no audio.

`lib/replay.ts` owns the review fixtures and replay calculations. Counts are reconstructed up to the selected time, using the highest revision for each event ID. Only `accepted` + `landed` records contribute to the defender's head/body/leg heat; blocks are tallied separately. Both fighters use the same 0–4+ contact-count scale. No health, injury, or impact-force measurement is implemented.

The market panel renders discrete sample YES-share prices and market-implied percentages. It uses no future quote snapshots and does not mechanically update prices when a strike lands. No market API or order execution is connected.

The 3D mannequins support coarse region selection. Browsers without WebGL receive an SVG fallback. Reduced-motion settings suppress expanding hit rings and shield rotation. Region buttons provide keyboard access independent of canvas picking. Mobile layout retains both mirrors and event details.

This prototype does not yet connect `tracks.jsonl` / `events.json`, cameras, WebRTC, live inference, or a prediction-market feed. The producer contract remains in the root README; this review introduces no changes to that contract.

## Checks

```sh
npm run typecheck
npm test
npm run build
```

Tests cover backward replay, non-contact exclusions, event revision deduplication/withdrawal, and quote timing independence. Browser QA covers actual video playback, contact/block feedback, region filters, the shared chart cursor, theme switching, and a 320px layout.
