# 2026-08-19 phantom clicks — live-telemetry diagnosis and the deep-commit gate

First session of the new telemetry layer (phone @60fps quartz + Mac-camera
dry-run observer, ~2 min of real use): 11 recorded clicks on the phone path,
each with a 2s pre / 0.5s post signal window.

## Diagnosis

Classifying every click by descent profile (bottom pinch-distance and
frozen-landmark pairs in the final frames):

- **9 deliberate**: pinch bottoms ≤ 25.6 pseudo-mm — a pinch is a CONTACT
  event, and even slow deliberate pinches reach contact depth (one descended
  at 0.8mm per 5 frames and still bottomed at 13.8, so a VELOCITY gate would
  break real slow clicks — rejected).
- **2 phantoms**: slow rest-band drift, bottoming at 28.2 and 33.9 — the
  relaxed pointing hand parks the thumb 28-45 pseudo-mm from the index, and
  the calibrated `pinch_on` (37.7) sits INSIDE that band. No second signal
  separates the classes: `pinch_strength` is synthesized from the same
  distance, and the extended-finger bits read identically (index-only).
- Edge artifacts exist but are rarer than expected: 1.1% frozen-landmark
  frames overall, the only run ≥2 at cx>1400 where the reach box was pinned
  flush at the camera frame boundary (see the edge-reach note).

## Fix shipped: deep-commit gate

`Config.pinch_commit_mm` — when set, the pinch Schmitt FIRES at this deeper
distance while `pinch_off`, the release assist, and the settle ramp stay put.
`tune_for_camera` sets it to `pinch_on − 10` (27.7 with today's calibration):
the ramp arms at on+8, the cursor freezes fully at on, and the click commits
at on−10 — the whole extra descent happens on an already-frozen cursor, so
the anchor machinery is untouched. The Leap keeps `None` (fire at pinch_on):
its real depth signal never had the rest-band overlap.

Margin honesty: the separation in this corpus is thin (25.6 vs 28.2). If
loose deliberate pinches start getting eaten, the commit offset is the one
knob to revisit — and the telemetry dashboard's PHANTOM button is how the
next fitting pass gets labeled data (0 marks were made this session; the
classification above is by descent profile).

## Instrument note

`motion_scale` recorded flat 1.000 across 1,636 samples — the dynamic box
absorbs the span signal, so ms carries no depth information for diagnostics.
Telemetry now records raw `span` (apparent knuckle span) per sample; that is
the input for the edge-reach note's ρ tilt diagnostic, which this session
could NOT evaluate (the 1.00 it returned was the blind instrument, not a
finding).
