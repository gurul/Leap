# Fitting it to your hand

The thresholds ship as guesses; your hand is the ground truth.

## Learn it first

Start in the practice room (works with any camera source):

```bash
.venv/bin/leapinput --source camera --tutorial
```

A guided walkthrough over the live preview: point, click, drag, park, then
the pose commands — each step advancing only when the real pipeline detects
the real gesture. It forces dry-run, so nothing touches your actual cursor
while you learn.

## Calibrate the pose thresholds

```bash
.venv/bin/python -m leapinput.calibrate capture
```

A few prompted rounds of open/point/pinch/fist fit your personal thresholds
into `camera_tuning.json` (gitignored), which the camera sources load
automatically.

## Fixed camera? Fit the reach box

A camera fixed in place (the laptop hinge, a phone on a stand) doesn't
move — so the geometry between your resting hand and the frame is stable,
and measurable. By default the *whole* frame maps to the cursor plane, which
wastes most of it: your comfortable reach covers only part of the view, and
covering the rest means stretching until tracking drops. The reach box fixes
that — roam your hand everywhere *comfortable* for ~12 seconds and the
measured envelope becomes the control surface:

```bash
.venv/bin/python -m leapinput.reach corners   # place hand at 2 corners (direct)
.venv/bin/python -m leapinput.reach map       # or: roam and let it fit
.venv/bin/python -m leapinput.reach test      # check it live (dry run)
.venv/bin/python -m leapinput.reach hand --span-mm 72    # your hand's REAL size
.venv/bin/python -m leapinput.reach show      # or clear
```

(Add `--source phone` to fit against the phone camera instead.)

The box is shaped like your **actual display** (Quartz-queried — here the
14.2″ MacBook Pro's 1512×982 panel), and `reach hand` calibrates your hand's
real knuckle span — the ChArUco-board idea with your hand as the board,
turning every physical readout from an assumption into a measurement (this
setup measured its box at ~28cm: 0.93× the panel's physical 30.4cm glass, a
near-1:1 touch surface).

The fitted box is stored in `camera_tuning.json` and applied automatically:
small comfortable motion now covers the whole screen (the deadzone and
gain-curve knees rescale with the zoom, so it stays anchored to your physical
hand), sensitivity stays constant as you sit nearer or farther (apparent hand
size is the free monocular depth signal), and overreaching **pins the cursor
at the edge** instead of losing it. `reach test` is the proof view — a live
screenshot of your actual screen drawn *inside* the box on the camera feed,
with a crosshair for where the cursor would be, plus dry-run recognition of
the full command vocabulary on both hands. `--no-reach` ignores the box for
one session.

## Touch mapping

With a fitted box, **touch mapping is the camera default** — the screen works
like a touchscreen sheet under your hand. The dynamic box appears centered on
your palm each time your hand shows up (screen-proportioned, sized to your
hand's apparent size so it's the same *physical* box at any distance), and
when you overshoot an edge the box slides with you — natural cadence, not an
error: the cursor rides the screen edge and responds the instant you reverse.
Point at a fixed spot to put the cursor there; pinch to tap. Two 2026-08-19
refinements from live telemetry: a **comfort inset** maps the box to ~25%
more than the screen so edges land inside the comfortable envelope, and a
**frame-edge margin** keeps the box off the camera frame boundary where
tracking degrades (see [the edge-reach research](context/edge-reach-research-2026-08-19.md)).
A third: **speed-adaptive precision** (PRISM, Frees & Kessler) — people
decelerate onto small targets (Fitts), so below ~700 px/s the mapping scales
toward 0.35×, with a bounded offset that bleeds away at speed; macOS
traffic-light buttons become hittable without giving up the 1:1 touch feel.
The trigger insight (an effortless, naturally-occurring signal beats an
explicit mode switch) comes from TiltReduction (Chang, L'Yi, Koh & Seo,
CHI 2015), whose device-tilt trigger also suggests our future explicit
precision trigger: palm tilt is already tracked for the clutch, and their
false-positive rule (threshold beyond normal variation, 35° there) is the
design constraint if we add it. Knobs: `Mapping.precision_*`
(`precision_gain_min=1.0` disables).

**One box per hand — so hands are not comparable in box coordinates.** In
touch mapping each hand carries its own box, centred on its own palm and sized
by its own distance from the camera. `HandFrame.index_tip` is therefore
expressed inside a coordinate system that belongs to that hand alone: it says
where the fingertip is *relative to its own palm*, not where the hand is.
Anything that measures one hand against the other — today only the two-hand
framing rectangle — must read `index_tip_frame`, the whole-frame copy. Getting
this wrong is not subtle-but-tolerable: the framing box inverted, growing as
the hands closed and collapsing as they spread, and a hand leaning toward the
camera swapped the corners outright (fixed 2026-08-20; the regression tests in
`tests/test_camera.py` pin all three symptoms).
`--map relative` restores the mouse-style clutch ratchet (the Leap's
default — its lopsided reachable volume never fit absolute mapping).
