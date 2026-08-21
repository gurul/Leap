# The interaction model, and why each part is what it is

> **Describes the cursor-driving tool, which is `--legacy` as of 2026-08-20**
> ([../decisions.md](../decisions.md) ·
> [../learnings/restoring.md](../learnings/restoring.md)). Nothing here is
> retracted — these are dated measurements, and they are the derivations behind
> [../learnings/screen-mapping.md](../learnings/screen-mapping.md) and
> [../learnings/gesture-vocabulary.md](../learnings/gesture-vocabulary.md).
> The pose-classification and transition-shadow sections still describe live
> behaviour.

Every number here came from measurement on this hardware, or from published results.
Nothing is a preference. If you change one, re-measure — several of these look
arbitrary and are not.

## The vocabulary

```
point (1-3 fingers)  cursor moves
pinch                click / drag
fist                 drag
open hand (4-5)      LIFT — cursor parked, reposition freely
hand on the desk     disengaged (the device stops seeing it entirely)
```

Verified by replaying 3639 recorded frames of real use — each pose does exactly
one thing:

| pose | click | grab | lift | cursor moves |
|---|---|---|---|---|
| pinch (443 frames) | 1 | 0 | 0 | 437 |
| fist (444) | 0 | 1 | 0 | 438 |
| open hand (442) | 0 | 0 | 1 | 28 |
| two-finger (554) | 0 | 0 | 0 | 554 |
| roaming (665) | 0 | 0 | 0 | 0 |

### Why lift is 4 fingers, not 2

A deliberate pinch reads as **three extended fingers** on this hardware — 100% of
443 corpus frames. Lifting at 2 parks the cursor at the precise moment of every
click. This is the single least obvious number in the system.

### Why a fist cannot latch while a pinch is held

They are one continuum: closing a pinch passes through both, and both drive the
same physical mouse button. Naive routing posts down/down/up/up and macOS loses
track of whether a drag is in progress. Whichever latched first owns the button.
The driver additionally owns button state idempotently, so no vocabulary change
can reintroduce the double press.

### Why the pinch threshold is loose (50mm, strength 0.5)

Measured separation is 65mm — pinched 17-18mm versus open 83-87mm — so 50mm sits
mid-gap: a light partial pinch registers, an open hand cannot reach it. The low
strength floor is deliberate. Pinch is model-*inferred* precisely where the thumb
and index occlude each other, which is the moment it must be exact; demanding
model confidence there asks for certainty exactly where the model has least.

### Why hysteresis takes two different forms

Continuous signals (pinch distance, palm angle, grab strength) use Schmitt
triggers — two thresholds with a band between them. Finger count is an **integer**,
so there is no band to sit inside and the guard has to be time: a debounce.

It is **asymmetric**: 0.05s to engage, 0.25s to lift. A symmetric 0.08s window
produced ~28 clutch cycles in one 60s session, because finger count naturally
flaps between 1 and 2 while pointing and either direction was equally easy.
Engaging should feel instant; lifting interrupts the user, so it must be
deliberate.

## Gain, and why it fixed tracking

| hand speed | px/mm |
|---|---|
| 10 mm/s | 2.12 |
| 150 mm/s | 9.58 |
| 500 mm/s | 23.32 |

A full-width sweep takes ~65mm of fast travel. The ~11x slow-to-fast ratio is
what buys fine positioning — **not** a low floor. Low control-display gain
measurably *hurts* pointing: more clutching, higher limb speeds, and pointer
acceleration beats constant gain by 3.3-5.6%, most on small targets. `--gain`
scales both ends together so the ratio survives.

**Gain turned out to be the tracking fix.** Measured across sessions:

| | before | after |
|---|---|---|
| frame rate in use | 36 fps | 116 fps |
| hand visible | ~32% | ~100% |

Higher gain means less hand travel, which keeps the hand in the reliable centre of
the cone instead of the edges. Nothing about tracking parameters changed.

## Edge constraint

Cursor gain fades from full inside 40° off the device axis to zero by 62°:

```
38.7° -> 100%      53.1° -> 40%
46.8° ->  69%      60.0° ->  9%
```

LMC1 palm error is ~8mm in the central volume but **RMS >20mm at the extreme
left, right or bottom**. At 23 px/mm, 20mm of noise is 460px of cursor jump —
that is the mechanism behind "it goes beyond the plane". Normal use here stays
under 45° for 95% of frames, so the guard is invisible in ordinary reach.

## Click stabilisation

The cursor freezes progressively as a pinch closes: full speed at 55mm, frozen by
38mm. Hand pointing fails by **missing** (95.7% spatial targeting failures)
rather than by misfiring (4.3%) — Midas touch is a gaze problem, not a hand one.
So the payoff is in landing the click. Ours drifted for a measured reason:
pinching curls the index, and the index fingertip *is* the tracked point.

## Screen geometry

Bounds come from `CGDisplayBounds` over every active display, never `NSScreen`.
They disagree, and only one matches the space `CGEventPost` uses: CG global space
has its origin at the top-left of the main display with y increasing **downward**;
NSScreen uses bottom-left with y up. Measured here, the second display is at CG
`(-541, -1440)` but NSScreen calls it `(-541, +982)`. Clamping to `(0, 0, w, h)`
also traps the cursor on the main display, since a monitor placed above or left
has negative coordinates.

## The plane

`xz` — the desk plane. Hand left/right moves the cursor horizontally; hand
**forward/back** moves it vertically. Chosen by measurement over 590 frames:

| | xz | xy (upright) |
|---|---|---|
| clutch reachable | 100% of frames | 0% |
| cursor vertical travel | 816px | 410px |

"Up/down" means moving the hand forward and back across the desk, not raising and
lowering it. Over a device lying flat that is the natural gesture, and it is a
*horizontal* plane. Three sign flips failed to fix this because the vertical
screen axis was being read from the wrong hand axis entirely.

The sensor also tracks a flat palm far better than an upright hand: it looks up
from the desk, so an upright hand is nearly edge-on, and the side of the hand is
the hardest part for it to see.

## Dead ends

- **Swipes.** Velocity separation is real (roam peaks 419 mm/s, swipe 803) and
  irrelevant: the swipe motion carries the hand out of the tracking volume and
  trips the dead-man. A live session fired `swipe.right` and `swipe.down`
  unintentionally, with `swipe.down` landing immediately before a disengage.
- **Scroll on a pose.** Index+middle is nearly identical to natural pointing —
  61 scroll events in a single clutch. Then rate-controlled scroll on a fist ran
  at ~7700 px/sec, about seven pages a second. Scroll currently has no home; a
  fist is a drag, and one pose must not carry two meanings.
- **Palm-angle clutch.** Works (18.9° median against a 30° cone) but drifts —
  observed at 66° in another session, freezing the cursor with no recourse.
  Finger count is the more stable signal. Still available via `clutch_mode="palm"`.

## The reach box (2026-08-18): a fixed camera gets a fitted control surface

The phone now lives on a stand, which turns the mapping problem inside out: the
frame no longer moves relative to the user, so the comfortable reach is a fixed,
measurable sub-rectangle of it. Whole-frame mapping (the default since the first
camera build) wastes everything outside that rectangle — reaching the screen
edge meant stretching to the frame edge, which is exactly where tracking is
worst and where the hand leaves view entirely.

`python -m leapinput.reach map` measures it the calibrate way: ~12s of "roam
everywhere comfortable, never stretch", p2..p98 envelope per axis, 10% margin,
stored in `camera_tuning.json` (`Tuning.reach_*`). Guards: an axis roamed under
16% of the frame refuses to fit (a hover is not a reach), and zoom is capped at
4x per axis — past that, 1-3px landmark noise magnified onto the plane rivals
deliberate slow motion.

Consequences threaded through the stack:

- `camera._to_plane` maps the box, not the frame, to the virtual plane, and
  CLAMPS outside it: overreach pins the pointer at the screen edge instead of
  losing it. Plane dimensions are unchanged, so the eccentricity/engage guards
  keep their meaning.
- `tune_for_camera` scales `deadzone_mm` and the gain-curve speed knees by the
  geometric-mean zoom, so both stay anchored to the PHYSICAL hand. The one
  intended effect is zoom× more cursor per centimetre of reach.
- **Absolute mapping** (`--map absolute`) becomes viable for the first time.
  It was tried and abandoned on the Leap because the reachable volume was a
  lopsided slab; a fitted reach box is by construction one comfortable
  screen-shaped region, so hand position can simply BE cursor position. The
  settle ramp lerps toward the target (freeze-as-the-pinch-forms, absolute
  flavour); filtering stays in plane-mm where the 1€ seeds were tuned.
- `python -m leapinput.reach test` is the proof view: a live screenshot warped
  into the box on the camera feed — the screen literally floating in hand
  space — plus a crosshair for the mapped cursor and dry-run recognition of
  the full command vocabulary on both hands.

## Transition shadows (2026-08-18): poses you pass through are not poses

Two live failures, one mechanism. Releasing a click-pinch into an open palm
extends middle/ring/pinky while thumb and index are still close — which IS the
OK pose, so Mission Control armed on every pinch release. And a fist opens
thumb-first, passing through a perfect thumbs-up. The fix in `commands.py`:
a button posture (click-pinch or fist) casts a 0.4s shadow in which the
matching cursor-hand hold refuses to arm. Deliberate poses formed from rest
never cast one (their back fingers are extended), so they arm on schedule.
The shadows are tracked separately per posture because a thumbs-up can read
pinch-distance ≤ 50mm (curled index near the thumb base) — one shared shadow
would have suppressed dictation forever.

Related: `CommandEngine.busy` is now gated on ring PROGRESS, not on `armed`.
Armed is true from the first pattern-matching frame, and the CLI answers busy
by feeding the cursor engine an empty snapshot — which force-releases held
buttons. One transitional frame was enough to blank the cursor mid-gesture.
The arm dwell exists to absorb exactly those frames; busy now waits for it.

And the V sign joined ILY in the label-trust exception (`camera.v_shaped`):
a lone V-shaped detection routes by the handedness label, because V is paste
and exists ONLY on the free hand — adopting it as the cursor hand (the
continuity rule for flappy fists) made every lone left-hand paste silently
inert.

## The kinematic pinch gate (2026-08-18): clicks only latch on a slow hand

Measured in the first live reach-test session on the phone-on-stand setup: of
28 button presses, 1 was a true click (<12px held travel) and 24 latched
MID-FLIGHT (median 550px of travel while held). A relaxed, foreshortened hand
travelling across the fitted box reads pinch-shaped for long enough to beat
the 2-frame dwell — the calibrated image-space thresholds were fitted at a
different camera geometry.

The literature says selection has a kinematic signature: people decelerate to
near-stillness before committing (RIDS, UIST 2022, detects the selection FROM
those dynamics; the ISS 2022 haptic-selection study found velocity-only tap
detection false-positives precisely during cursor positioning; arXiv
2602.01061 shows intent is clearest BEFORE the confirmation and cuts
bare-hand error 22%→7.5% by weighting pre-confirmation history — the same
principle as our click-anchor backdating).

So `Config.pinch_arm_max_speed` (150 mm/s, scaled by the reach-box zoom):
a pinch may only LATCH below it. Onset-only — a latched drag moves at full
speed and a release is never gated (a stuck button is worse than any missed
click). Corollary: the settle freeze is skipped above the same speed, since
no click can form there — a pinch-shaped read at speed used to freeze the
cursor mid-motion, which read as lag and made the user tense the hand.

Note on ILY orientation: every pose predicate reads finger-extension flags
only, so back-of-hand poses are legal by construction — the "palm facing the
camera" phrasing in the docs was instructional, not enforced. If back-of-hand
thumb reads prove flaky, that is a tuning issue (thumb_ratio from the
occluded side), not a design constraint.

## Distance-invariant sensitivity (2026-08-18): span is the free depth signal

"When I am far away I have to do very exaggerated motions": image motion per
physical centimetre scales with 1/distance, so a monocular mapping gets slower
the farther the hand sits from the camera. The fix needs a distance signal,
and the camera already computes one every frame — apparent knuckle span
(`span_img`), which scales with 1/distance while the physical span stays
hand-sized. This is the zero-cost version of what a Depth Anything
integration (TouchDesigner's TDDepthAnything) would buy with a model.

`leapinput.reach map`/`corners` now also record the median span at the
calibrated working distance (`Tuning.ref_span_img`). Per frame,
`HandFrame.motion_scale = ref/current` (clamped 0.5..3.0, EMA-blended):

- the driver's RELATIVE path multiplies deltas and the gain-curve speed by
  it — one physical centimetre moves the cursor the same amount at any
  distance. Applied AFTER the deadzone check: image noise does not grow with
  distance, so the noise floor must not be magnified with the motion.
- the kinematic pinch gate multiplies its measured speed by it — the gate
  judges the physical hand, not its image.
- POSITIONS are never scaled: the reach box is a frame region, and absolute
  mapping stays position-faithful.
- Leap frames carry motion_scale=1.0 (real depth, nothing to compensate).

## The dynamic palm box + camera DPI boost (2026-08-18)

Fixed-position boxes died in first contact: the user had to return the hand
to one spot in space ("I want to say where my hands should be" became "center
it on my palm every time"). The box is now DYNAMIC by default
(Tuning.reach_center = "palm"): screen-proportioned (16:10 through the 4:3
frame), width = calibrated width x (current span / ref span) so its PHYSICAL
size is constant at any distance (floor ~6x zoom), centred on the palm at
each (re)appearance, pinned while the hand stays tracked. Calibration
(corners/map) now supplies SIZE and working distance, not position. Delta
distance-scaling (motion_scale) is disabled in palm mode — the box itself
compensates, and scaling both would double it. `reach anchor fixed` restores
the placed rectangle.

DPI: tune_for_camera multiplies BOTH gain ends by CAMERA_GAIN_BOOST (2.0) on
the Leap path's own measured lesson — low CD gain hurts pointing, raising it
kept the hand in the well-tracked core, and the slow/fast RATIO (~11x) is
what carries precision, so both ends move together. Net camera sensitivity =
boost x gain curve x box zoom (~14-154 px per physical mm at a 3.3x box).

## Touch, not mouse (2026-08-18, evening): the interaction framework settles

Live use settled the model debate: "it should work like a touchscreen —
that's the interaction framework here, not a mouse. We are used to
interacting with screens as fixed points. But it needs to be dynamic."
So `--map touch` (absolute into the dynamic palm box) is now the camera
default; the Leap keeps relative (its reachable volume never fit absolute).

The box became a TOUCH SHEET (CameraSource._resolve_reach): built fresh on
each hand appearance (screen-proportioned, span-sized, palm-centred), and
while tracked it FOLLOWS an overshooting hand — minimal translation keeping
the hand on the edge. Overshoot is natural human cadence, not an error: the
cursor rides the screen edge while the sheet slides, and reversal responds
on the first millimetre with no overshoot debt. A three-agent audit of the
alternative (slack coordinates beyond the box) found it required disabling
the eccentricity edge guard (slack corners reach 82 deg vs the 62 deg
freeze), created a disengage foot-gun under --plane xz, and let phantom
overshoot accumulate in the absolute filter state — all structurally absent
under the drag, because positions never leave the proven [0,1] plane.

## The jitter post-mortem (2026-08-18, audited)

The unusable shiver after the first DPI pass had ONE root cause and one
amplifier, quantified by the audit swarm:

- ROOT CAUSE: pointer_beta was never scaled by the reach-box zoom while
  every other speed-denominated knob was. The 1-euro adaptive term saw
  zoom-amplified derivatives — rest landmark noise alone (~45 virtual mm/s
  at 3.3x) opened the cutoff from 1.5Hz to ~3-4.5Hz, so the filter was
  effectively OPEN while the hand was still. Fix: pointer_beta /= zoom.
  Audited result: ~1-2px residual shimmer, gated by the scaled deadzone.
- AMPLIFIER: CAMERA_GAIN_BOOST stacked multiplicatively on the box zoom
  (14 px/physical-mm at REST). Fix: boost = max(1, BOOST/zoom) — the zoom
  IS the DPI at a fitted box (unboosted flick crosses 1512px in ~19.5mm,
  under the 3cm target; aim quantum stays ~4px not 8.5px). Boxless cameras
  keep the full boost.
- Kept: min_cutoff 1.5 (lowering it is pure final-approach latency — the
  documented syrup trap — once beta is fixed); deadzone 0.6 x zoom;
  d_cutoff 2.0. Known approximations: shared beta across axes (geometric
  mean vs a ~20% hotter y axis), stored-box zoom vs the dynamic box's live
  zoom (~1.8x drift far from the calibrated distance).

## Metric grounding (2026-08-18): the laptop's glass, the hand as ChArUco board

Two real-world dimensions entered the loop:

- **The display**: the dynamic box is shaped by the ACTUAL display
  (Quartz-queried; this machine: 1512x982 — the 14.2-inch MacBook Pro panel,
  ~1.54:1), not a 16:10 guess. Side effect: less y-axis noise excess.
  *Amended 2026-08-21: "the main display" here became "the display the cursor
  is on at startup" — see [learnings/screen-mapping.md](../learnings/screen-mapping.md).*
- **The hand**: `reach hand` calibrates the user's REAL knuckle span — the
  ChArUco-board idea with the hand as the board: a rigid, known-size object
  in every frame that converts image measurements to metric. Ruler entry
  (--span-mm) beats the MediaPipe world-landmark median. Deliberately NOT
  used to renormalize pose pseudo-mm (calibrated pinch thresholds live
  there); it powers the physical readouts — measured on this setup, the
  corner-placed box is ~28cm wide, 0.93x the panel's physical 30.4cm glass:
  the user unknowingly calibrated a near-1:1 touch surface.

## Phone sensors beyond the camera (2026-08-18, iPhone 17 Pro)

What Safari's no-install page can and cannot reach:

- **IMU: reachable, now used.** DeviceMotion (permission piggybacked on the
  Start tap) rides a WebRTC datachannel at 5Hz. The Mac EMA-tracks gravity;
  a >1.5 m/s^2 deviation = the STAND WAS BUMPED — the assumption every
  fixed-camera calibration rests on, now actively checked. Slow drift is
  absorbed into the gravity estimate; a knock prints a re-calibrate hint
  (throttled). Gravity is exposed (PhoneSource.imu_gravity) for future
  keystone correction.
- **Ultra-wide lens: reachable, future.** Rear ultra-wide is enumerable via
  getUserMedia — a wider interaction volume at the same distance.
- **LiDAR / TrueDepth: NOT reachable from the web.** Real depth needs a
  native ARKit companion — the roadmap unlock that would retire every
  monocular workaround (span-as-depth, world-scale jitter), at the cost of
  the no-install principle.

Bug pinned in the same pass: `reach hand` initially fell through main()'s
subcommand chain into `clear`, silently WIPING the calibration — the
fallthrough now asserts cmd == "clear".
