# FightLens

A real-time MMA viewing assistant that shows who struck whom, where contact occurred, and how the exchange unfolded.

Built for the Real-Time Video Agents Hack — NYC, October 9, 2026.

**Status: live camera transport and diagnostic receiver implemented; video analysis remains planned.** The Next.js application uses React, TypeScript, shadcn/ui, Recharts, and LiveKit. A desktop or paired phone publishes a camera track to the viewer and Python receiver. The live UI reports actual receiver frames and explicitly leaves numeric momentum unavailable. There is no connected strike classifier or measured inference performance result yet.

For the live MVP, run `pnpm install --frozen-lockfile`, `pnpm live:setup`, and `pnpm live:dev`, then open `http://localhost:4173`. See [live setup and deployment boundaries](docs/LIVE_SETUP.md) for prerequisites and phone access. [The web MVP guide](docs/WEB_MVP.md) covers the separate Demo/local-file mode. All Demo curve values are simulated. The earlier Chrome prototype remains in [extension/](extension/README.md) for reference.

## First milestone

Use a 30–60 second standing-exchange video with both fighters clearly visible to evaluate:

- Stable fighter identity: A and B remain correctly assigned throughout the clip.
- Attack direction: who attacked whom.
- Contact location: head, torso, or leg.
- Outcome: landed, blocked, missed, unknown, or not a strike.
- End-to-end latency when frames are processed at the video's original playback speed.

The web MVP implements the viewing interaction with a simulated momentum curve using shadcn/ui's Neutral theme. Fighter tracking overlays, received-strike heatmaps, and actual evidence replay remain planned.

## Proposed pipeline

```mermaid
flowchart TD
    A[Timestamped video and rolling frame buffer] --> B[YOLO Pose and fighter tracking]
    B --> C[Live identity and skeleton overlays]
    B --> D[Motion-based strike candidates]
    A --> E[Short contact-centered clips]
    D --> E
    E --> F[Asynchronous Cosmos event verification]
    F --> G[Deduplicated event log]
    G --> H[Received-strike heatmaps and evidence replay]
```

See [the pipeline and validation plan](docs/PIPELINE.md) for model choices, event definitions, latency budgets, and acceptance criteria.

See [the product requirements](docs/PRD.md) for the proposed exchange-impact classification, Jev context contract, and subsequent market-response observation experiment.

See [the live camera and WebRTC specification](docs/LIVE_CAPTURE_SPEC.md) for the draft capture, pairing, media transport, Python receiver, result timing, and desktop/mobile acceptance requirements.

## Planned tools

| Tool | Proposed role | Status |
| --- | --- | --- |
| Ultralytics YOLO Pose + ByteTrack / BoT-SORT | Fighter tracking, pose estimation, and candidate generation | Planned |
| NVIDIA Cosmos video-understanding endpoint | Review short candidate clips | Planned; event endpoint and model version to confirm |
| VAST | Store video evidence and event metadata | Planned; access to confirm |
| Weights & Biases / Weave | Record experiments, model calls, and latency | Planned; access to confirm |

These entries describe intended integrations, not completed integrations or confirmed sponsor eligibility.

## Scope and evidence

- A heatmap represents detected received strikes, not a medical injury assessment or impact-force measurement.
- A blocked strike is recorded separately from a direct hit to the intended body region.
- Unclear contact stays unknown rather than being forced into a binary answer.
- Win-probability prediction is a later research task requiring historical evaluation and calibration. No validated win-probability model is included.
- Single-clip results will establish limited feasibility, not general reliability across MMA broadcasts.

## Next actions

- [ ] Select a continuous 30–60 second test video and keep it outside Git.
- [ ] Annotate attacks, outcomes, body regions, and uncertain events.
- [ ] Run pose and identity tracking on the first 10 seconds.
- [ ] Add candidate generation and event deduplication.
- [ ] Benchmark the available Cosmos endpoint on short clips.
- [ ] Compare geometry-only and Cosmos-assisted decisions on held-out footage.
- [ ] Build the heatmap, event list, and evidence replay interface.
- [ ] Record a three-minute project demo and make the repository accessible to reviewers.

## References

- [Hackathon page](https://tokensand.com/vastnyc)
- [Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/)
- [Ultralytics tracking](https://docs.ultralytics.com/modes/track/)
- [Cosmos Reason2 NIM API](https://docs.nvidia.com/nim/vision-language-models/1.6.0/examples/cosmos-reason2/api.html)
- [TapStats product preview](https://www.tapstats.live/app-tour) — a reference for spectator interaction; its preview describes manual crowd-sourced strike input.
