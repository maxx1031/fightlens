# FightLens Arcade

Open index.html locally. Use the top navigation to switch between the audience
HUD and data inspector. Playback position is shared. The inspector links to
analysis.html with the original curves and supports event JSON export.

This is an offline replay of the supplied 0_realhuman measurements, not live
inference or a connected database. Engagement status is reused from the input;
no new hysteresis classifier has been added. Punch candidates use extension
threshold crossings at 0.9, not confirmed hits. Pressure is a visual mapping:
100 × clamp(1 - reach / 1.5, 0, 1) × arm extension. It is not damage or health.

The supplied measure.mp4 has its pose overlays baked in. A clean camera video
can replace it when a matching unannotated source is available.
