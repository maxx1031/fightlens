# FightLens Arcade

Open index.html locally. Use the top navigation to switch between the audience
HUD and data inspector. Playback position is shared. The inspector links to
analysis.html with the original curves and supports event JSON export.

The replay joins two rounds: 10 s of UFC 300 (Pereira vs Rountree) and 15 s of
the local sparring clip (0_realhuman). Each round is tracked and measured on
its own, so A/B, the clock and punch counts restart at the join.

Regenerate data.js, analysis.html and measure.mp4 from yolo_branch:

    python concat.py outputs/demo_ufc_local \
        "outputs/pereira_rountree_45s:0:10:UFC 300 replay:PEREIRA:ROUNTREE" \
        "outputs/0_realhuman:0:15:Local arena:BLACK KIT:WHITE KIT"
    python viewer.py outputs/demo_ufc_local

The win-probability bar at the top comes from yolo_branch/win_prob.py: Luna
Decisions (via OpenRouter) is asked only for seconds YOLO marks as engaged,
twice with A/B swapped to cancel its preference for the first-listed fighter.
Other seconds hold the previous value. It is an uncalibrated model estimate.

The page opens on the data console: the cascade from YOLO sentinel (every frame) to the
Cosmos referee and Jev judgment (engaged clips only; yolo_branch/referee.py) and the
decision layer, with charts drawn in step with the replay. Cosmos verdicts appear in the
exchange-status callout at clip end + measured Cosmos latency.

This is an offline replay of precomputed YOLO measurements, not live inference
or a connected database. Engagement comes from yolo_branch/engage.py. Punch
candidates use extension threshold crossings at 0.9, not confirmed hits.
Pressure is a visual mapping: 100 × clamp(1 - reach / 1.5, 0, 1) × arm
extension. It is not damage or health.

measure.mp4 has the pose overlays baked in.
