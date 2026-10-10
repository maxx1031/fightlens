# FightLens Arcade Live (test page)

The arcade audience HUD driven by a live session of the Next.js app (PR #9 branch).
It joins the session as an extra viewer, shows the worker's YOLO video, and computes
in the browser: engagement status, attack pressure, per-arm punch detection, and the
strikes-taken heatmap (a live port of `yolo_branch/hits.py`). The win-probability bar
asks Luna Decisions about engaged seconds through `yolo_branch/winprob_server.py`, so
the OpenRouter key never reaches the browser.

Setup, in the Next.js checkout:

```sh
mkdir -p public/arcade-live
cp <this folder>/{index.html,live.js,style.css} public/arcade-live/
cp node_modules/livekit-client/dist/livekit-client.umd.js public/arcade-live/
pnpm live:dev
# in this repository, for the win-probability bar (needs OPENROUTER_API_KEY in .env):
yolo_branch/.venv/bin/python yolo_branch/winprob_server.py
```

Start a session from the app, confirm A/B descriptions, keep the session page open, then open
`http://localhost:4173/arcade-live/index.html?session=<session id>` in the same browser.
Contact candidates and punches are 2D pose geometry, not verified hits; win probability
is an uncalibrated model estimate.
