# Screen mapping and geometric projection

> **All of this is shelved.** The hand has not driven the cursor since
> 2026-08-20; the whole mapping stack is behind `--legacy`
> ([restoring.md](restoring.md)). It is also the richest body of measured
> knowledge in the repo — four reversals, one refuted hypothesis, and three
> defects that are confirmed real and still unfixed. Anyone re-wiring the
> cursor inherits all of it.

Restore the cursor: `leapinput --legacy`.

---

## The reversals, in one table

Each of these was landed on evidence and then moved on better evidence. The
evidence is what matters; the settings are downstream.

| Decision | First answer | Final answer | What decided it |
|---|---|---|---|
| interaction plane (Leap) | `xy` guessed | `xz`, then `xy` default, then reverted, then re-landed | 590-frame measurement, then a clutch that had to move with the plane |
| mapping mode | absolute | relative + clutch (Leap), touch/absolute (camera) | 5 tracking losses in one 60 s run; a *fitted* box made absolute viable |
| reach box anchor | fixed rectangle in space | dynamic, palm-centred, drag-along | died in first contact; then measured as unlearnable |
| gain | 1 → 30 px/mm | 2.12 → 23.32 px/mm | four tuning passes; the ratio, not the floor, is what buys precision |

---

## The plane was settled by measurement, after three sign flips each failed

`leapinput.doctor` over **590 tracked frames**:

| | `xz` (desk plane) | `xy` (upright) |
|---|---|---|
| clutch reachable | 100% of frames (palm 18.9° off down) | 0% (palm 85.4° off forward) |
| cursor travel | 1313 px horizontal / 816 px vertical | 1318 / 410 |

The misconception it settled: "up/down" over a device lying flat means moving
the hand **forward and back across the desk** (z span 178 mm), not raising and
lowering it (y span 76 mm). No amount of `invert_*` flipping could have fixed
it, because the vertical screen axis was being read from the wrong hand axis
entirely — which is exactly why three sign flips in a row each failed.
(52f3863, 2e198cf, [interaction.md:118-136](../context/interaction.md))

**Then the `xy` default was landed, reverted, and re-landed.** Making the
upright plane the default stopped the cursor moving *entirely*: held flat out
of habit, the palm sits 90° off the palm-forward clutch reference, and the
clutch gates all pointer motion. It re-landed only once three things moved
per-plane **together**:

| | `xy` | `xz` |
|---|---|---|
| clutch reference | palm-forward | palm-down |
| clutch cone | 50/70° | 30/45° |
| engagement floor | 40 mm | 115 mm |

The wider cone in `xy` is not taste: an upright hand is nearly edge-on to a
device that looks *up* from the desk, so its palm normal is noisier. Changing
the plane without the clutch reference reproduces the freeze.
(1b3fb9e → 230cca2 → 863d39d)

Camera sources use `xy` because a webcam sees the image plane and has no
usable depth axis. Its virtual plane is isotropic by construction:
`PLANE_X_MM = 320`, `PLANE_Y_MM = 320 × 480/640 = 240`. The previous 320×300
pair made vertical motion ~25% hotter and noisier than horizontal for the same
real movement. Worst-corner eccentricity is 38.7°, just under the 40° edge
guard, so the Leap-specific guard never damps camera motion. (`camera.py:48-66`)

---

## Absolute mapping died on the Leap and came back on the camera

The measured Leap envelope across 3,639 frames: **x −24..+214 mm, z +15..+84 mm**
— wide, shallow, right-shifted. The symmetric ±110 box that had been assumed
would have been unusable: z never went negative once, so the entire top half of
the screen was unreachable. Absolute mapping pushes the hand to the edge of
tracking to reach the screen edge; one 60 s live run **lost tracking five
times**. (09aa4e5, a2059a7, `driver.py:25-45`)

Recorded honestly at the time: z is under-sampled (the roam step spanned only
39 mm at p5–p95), and 69 mm mapped onto 982 px is ~14 px/mm vertically versus
~6 px/mm horizontally, so vertical control was twice as twitchy.

Relative control with a **clutch ratchet** decoupled the two — move, release
the clutch, reposition anywhere comfortable, re-engage. Exactly what lifting a
mouse does. `--map relative` is still the Leap default.

Absolute (`touch`) mapping only became viable once a **fitted reach box** gave
the camera one comfortable, screen-shaped region.
([interaction.md:176-181](../context/interaction.md))

---

## Gain: the ratio buys precision, and it fixed tracking

Four tuning passes: 1→30 px/mm (a 50 mm movement swept the whole screen), then
0.25→5, 0.5→10, 0.9→10, 2.0→22, finally **2.12→23.32**. Both ends always move
together so the ~11× slow-to-fast ratio survives.

| hand speed | px/mm |
|---|---|
| 10 mm/s | 2.12 |
| 150 mm/s | 9.58 |
| 500 mm/s | 23.32 |

A full-width sweep takes ~65 mm of fast travel (was 151 mm). Grounded in
published results: low control-display gain measurably **hurts** pointing —
more clutching, higher limb speeds — and pointer acceleration beats constant
gain by 3.3–5.6%, most on small targets. *A low floor is not precision, it is
just slow.* (02a08a1, 7e6a831, a0d07da, 59ca20a, 1c9faf0,
[interaction.md:62-84](../context/interaction.md))

**And raising gain fixed tracking** — the strongest counter-intuitive result
in the repo. Measured across sessions with **no tracking parameter changed at
all**:

| | before | after |
|---|---|---|
| frame rate in use | 36 fps | 116 fps |
| hand visible | ~32% | ~100% |

One direct comparison: 6,935 frames in 60 s versus 2,136 in the previous run.
Higher gain means less hand travel, which keeps the hand in the reliable
centre of the cone instead of at the edges where error is worst. (6fc79da)

This is the stated justification for `CAMERA_GAIN_BOOST = 2.0` on the camera
path — with a correction, below.

---

## The reach box

A camera fixed in place (a laptop hinge, a phone on a stand) does not move, so
the comfortable reach is a fixed, measurable sub-rectangle of the frame.
Whole-frame mapping wastes everything outside it: reaching the screen edge
meant stretching to the frame edge, which is exactly where tracking is worst.

`reach map` measures it the calibrate way: ~12 s of "roam everywhere
comfortable, never stretch", p2..p98 envelope per axis, 10% margin. Two guards
that matter:

- an axis roamed under **16%** of the frame **refuses to fit** — a hover is
  not a reach, and refitting beats silently saving garbage;
- zoom is capped at **4×** per axis — past that, 1–3 px landmark noise
  magnified onto the plane rivals deliberate slow motion.

Overreach **clamps** (pins the cursor at the screen edge) instead of losing it.
(`reach.py:42-142`, [interaction.md:151-172](../context/interaction.md))

### Fixed boxes died in first contact — the box is a touch sheet

*"I want to say where my hands should be"* became *"center it on my palm every
time."* The box is dynamic by default (`Tuning.reach_center = "palm"`):

- screen-proportioned by the **actual Quartz-queried display** (1512×982 here,
  ~1.54:1 — not a 16:10 guess; the change also reduced y-axis noise excess);
- width = calibrated width × (current span / ref span), so its **physical** size
  is constant at any distance (floor ~6× zoom, looser than the stored-box 4×
  cap, because a distant hand *needs* the shrink);
- centred on the palm at each reappearance, pinned while tracked;
- and while tracked it **follows** an overshooting hand by the minimal
  translation that keeps the hand on the edge.

Overshoot is natural human cadence, not an error: the cursor rides the screen
edge while the sheet slides, and reversal responds on the first millimetre with
no overshoot debt.

A three-agent audit of the alternative — slack coordinates beyond the box —
found it required disabling the eccentricity edge guard (slack corners reach
82° against the 62° freeze), created a disengage foot-gun under `--plane xz`,
and let phantom overshoot accumulate in the absolute filter state. All three
are structurally absent under the drag, because positions never leave the
proven [0,1] plane. (f819df5,
[interaction.md:266-304](../context/interaction.md))

### But a palm-anchored box is a different projection per engagement

Measured across **65 recorded clicks** with the default palm-anchored box:

| | range across clicks |
|---|---|
| box origin x | 0.202 → 0.749 of the frame |
| box origin y | 0.275 → 0.669 |
| box width | 0.211 → 0.693 (zoom **1.4× → 4.7×**) |

That is not one projection with noise. It is a different origin and a **3.3×
spread in scale** every time the hand appears. Absolute mapping promises that a
point in the air is a point on the screen — and that promise holds only
*within* a single engagement, which is why aim stopped being learnable.
`--reach-center fixed` trades the come-to-your-hand convenience for a
projection you can learn. ([troubleshooting.md:94-110](../troubleshooting.md))

The comparison that motivated the shared-frame fix:
[mediapipe-touchdesigner](https://github.com/torinmb/mediapipe-touchdesigner)
hands MediaPipe's landmarks to the host **unchanged** — normalized whole-image
0–1 coordinates, one space shared by both hands, no per-hand ROI, recentring or
gain. Interactions built on it inherit a single static projection. This is the
strongest argument on record for `--reach-center fixed` if pointing returns.

### One box per hand — so hands are not comparable in box coordinates

`frame_rect` had been unchanged since the pane feature landed (38091ac), back
when there were no reach boxes and `index_tip` was simply a position in the
camera frame. f819df5 then gave **each hand its own box** — centred on that
palm, sized by that hand's apparent span — while `frame_rect` kept comparing
the two tips as if they shared a frame. So it measured each tip's offset from
*its own palm*: lean a hand toward the camera, its box grows, its normalized
tip slides toward centre, it crosses the other hand's value, and the corners
**swap**.

Measured on the old code: closing the hands made the rect **wider** (1.00 of
the screen) than spreading them (0.67) — the response was literally inverted.
Fix: `HandFrame.index_tip_frame`, a whole-frame copy with no box applied.
Verified live at 12 consecutive pane rects, 0 inverted, and 92% mean IoU on
the bench against a drawn target. Three regression tests in
`tests/test_camera.py` pin the corner swap, the approach-the-camera case and
the shrink-as-hands-close case. (0fe1de8,
[calibration.md:91-101](../calibration.md))

**This one is not shelved** — the two-hand frame shot is the flagship shipped
gesture and depends on it.

Second-order lesson: making the rect correct **exposed noise a bug had been
accidentally suppressing.** The box-relative version measured a tip relative
to its own palm, so whole-hand shake cancelled as common mode. Removing the
accidental differential required explicit 1-euro smoothing of the framing
fingertips (`TIP_MIN_CUTOFF = 1.5`, whole-frame units, not zoom-scaled).
(0b19969)

---

## Edge reach

Live telemetry found the actual wall: in 255 right-edge samples the drag-along
box sat at `box_x1 = 1.000`, so reaching the screen edge demanded knuckles at
the image border — fingers out of frame, extrapolated landmarks, cursor
topping out ~14 px short. Two fixes shipped:

- **`FRAME_EDGE_MARGIN = 0.04`** keeps the box clear of the frame boundary.
- **`reach_inset = 0.10`** shrinks the box 10% per side, so it maps to ~25%
  *more* than the screen (effective zoom ×1.25) — the cursor reaches the screen
  edge while the hand is still comfortably inside. This is the classic
  webcam-mouse active-region trick (`frameR = 100` on 640×480 ⇒ 16–21% per
  side) and Kinect's ergonomic PhIZ patents. The 1.25 is folded into **every**
  zoom-anchored knob.

**Explicitly rejected: (D) edge-zone gain boost.** Nonlinear stretch breaks the
touch model's position-faithfulness and puts maximum noise gain exactly where
MediaPipe is worst; Vogel & Balakrishnan's absolute ray-casting was abandoned
at 22% error. Once edges are reachable the existing clamp makes edge targets
effectively infinite.
([edge-reach-research-2026-08-19.md](../context/edge-reach-research-2026-08-19.md))

**The unshipped next step is spec'd and cheap** — and has never actually been
run, because the instrument was blind. (C-lite) span-gradient perspective
correction: regress apparent span against box-relative position,
ρ = span(far edge)/span(near edge). ρ ≥ ~0.9 means tilt is not the mechanism;
ρ ≤ ~0.8 means apply a Möbius unwarp per axis after box normalization and
before the [0,1] clamp:

```
s = ρ·n / (1 − (1−ρ)·n)        (n = box-normalized coord; ρ=1 ⇒ identity)
```

~20 lines in `_to_plane`. The diagnostic previously read `motion_scale`, which
the dynamic box absorbs to a flat 1.000 — telemetry now records raw span,
which is the input it actually needs.

Held in reserve: (C-full) a gravity-vector homography from the phone's IMU,
worth doing only if C-lite residuals show a rolled or oblique tilt axis; and
(B) a 4-corner DLT homography, whose right role is a *validation harness* for
C, not the shipped mapping.

---

## The jitter post-mortem: scale every plane-unit knob by the box zoom

The unusable shiver after the first DPI pass had **one root cause and one
amplifier**, both quantified by an audit swarm.

**Root cause.** `pointer_beta` was never scaled by the reach-box zoom while
every other speed-denominated knob was. The 1-euro adaptive term therefore saw
zoom-amplified derivatives: rest landmark noise alone (~45 virtual mm/s at 3.3×
zoom) opened the cutoff from 1.5 Hz to ~3–4.5 Hz, so the filter was effectively
**open while the hand was still**. Fix: `pointer_beta /= zoom`. Audited result
~1–2 px residual shimmer, gated by the scaled deadzone.

**Amplifier.** `CAMERA_GAIN_BOOST` stacked multiplicatively on the box zoom —
14 px per *physical* mm at rest. Fix: `boost = max(1, BOOST/zoom)`. The zoom
**is** the DPI at a fitted box; boxless cameras keep the full 2×.

Kept deliberately: `min_cutoff = 1.5` (lowering it is pure final-approach
latency once beta is fixed), deadzone 0.6 × zoom, `d_cutoff = 2.0`.
(f819df5, [interaction.md:306-327](../context/interaction.md))

**Known approximations, both still open:** beta is shared across axes
(geometric mean against a ~20% hotter y axis), and the **stored** box's zoom is
used where the **live** dynamic box's zoom applies, drifting up to ~1.8× far
from the calibrated distance. That is deferred finding **MD-4**; the code's own
NOTE names the fix (expose live zoom on `HandFrame`) and it spans three
modules.

---

## PRISM speed-adaptive precision — and the hypothesis it refuted

Below `precision_full_speed` (700 px/s of the mapped target) the mapping scales
toward `precision_gain_min` (0.35×), accumulating a **bounded** offset (60 px
max) that bleeds away at 0.10 per full-speed frame, so the touch sheet stays
position-faithful. macOS traffic-light buttons (7 px radius on the bench
ladder) become hittable without giving up 1:1 feel.

Speed and offset accrual are read off the **raw** target, not the filtered one
— measuring the filtered target would read the 1-euro convergence tail after a
flick as a slow hand and park the cursor short of a corner the hand already
reached. The touch deadband scales with the gain (`max(0.8, 1.5·g)`), because a
fixed band would eat exactly the slow deliberate crawl precision mode exists
for.

The trigger insight comes from TiltReduction (Chang, L'Yi, Koh & Seo, CHI
2015): an effortless, naturally-occurring signal beats an explicit mode
switch. People decelerate on final approach (Fitts), so speed *is* the mode
switch. (`driver.py:82-96, 367-434`)

**Then it was accused, and cleared.** The PRISM offset was the leading
hypothesis for a measured **+9.8 px x-bias** on the bench. An adversarial
verifier's finding: *"the stated mechanism is arithmetically false; the claimed
numbers do not reproduce; and the proposed fix would CREATE the exact symptom
under investigation."* **Do not disable PRISM on the strength of that theory.**
Off switch, if you need one: `precision_gain_min = 1.0`, or `--no-precision`.
([decisions.md:153-157](../decisions.md))

---

## Slow motion was being eaten twice over

**Deadzone order.** The deadzone advanced its anchor *before* the threshold
check, permanently eating any motion under ~18 mm/s — precisely the speed of
final target approach. Any hand moving slower than deadzone-per-frame produced
zero cursor motion forever; precise aiming was structurally impossible. Fixed
by accumulating against a **held** anchor, so tremor still nets to zero but
deliberate crawl releases as one honest step.

**The 1-euro floor.** The camera path shipped a 0.3 Hz floor: ~530 ms of group
delay at slow speed — the "syrup then overshoot" mode `docs/plan.md` had
explicitly warned about. Shipped instead: `min_cutoff 1.5` (rests at ~106 ms),
`beta 0.03` (reaching ~4.5 Hz at 100 mm/s, ~7.5 Hz at 200), and `d_cutoff 2.0`,
because at 1.0 the derivative driving beta was itself ~5 frames late at 30 fps.
([strengthening-2026-08-18.md:9](../context/strengthening-2026-08-18.md),
`camera.py:606-621`)

---

## The unfixed list

Confirmed real, never fixed. Dormant while the cursor is unwired; inherited in
full by anyone who re-wires it.

**Transition jitter — three verified mechanisms, ~2,300 px/min of uncommanded
cursor travel.** Found by a five-lens swarm (29 candidates, 3 survived), each
survivor re-derived by an adversarial verifier told to refute it:

| mechanism | uncommanded travel | frequency |
|---|---|---|
| `settle` is a lerp **alpha**, not a gain — every freeze accrues positional debt discharged in one 33 ms frame | 952 px/min | 34/min |
| clutch re-engage teleports in absolute/touch mode | 886 px/min | 5.3/min, median 310 px, max 1074 px |
| `_touch_offset` cleared in one breath after every release | 468 px/min | 14/min — one per click |

**Ruled out by that same data, do not chase:** reach-box slide/re-anchor/
revival (zero of 233 large-jump events) and hand re-acquisition after dropout
(zero of 233, and zero of the 21 clutch drops).
([decisions.md:141-163](../decisions.md))

**From the 2026-08-19 hardening sign-off**
([hardening-2026-08-19.md:63-84](../context/hardening-2026-08-19.md)):

| id | what |
|---|---|
| MD-1 | the touch-sheet drag consumes raw landmarks with **no per-frame slew limit**, so edge-riding noise ratchets the box and screen-edge targets drift by tens of px |
| MD-3 | dynamic box width is latched from **one raw `span_img` frame** per engagement; a bad first frame skews DPI 10–30% until re-engagement (the fix touches the "pinned while tracked" guarantee) |
| MD-4 | stored-box vs live-zoom drift (≤1.8×) on `pointer_beta` and `pinch_arm_max_speed` |
| SI-3 | display geometry is cached once at init, so a mid-session display change clamps into stale rects |

---

## Two things that stayed correct throughout

**Drags were structurally frozen for weeks** by a settle factor recomputed
every frame. The click-settle factor was recomputed from raw pinch distance on
every move frame and multiplied into pointer gain. A held pinch (~15 pseudo-mm)
and a fist (~18) both sit below `settle_full` for their whole duration, so gain
went to **exactly 0** the moment the button latched — pinch-drag, fist-drag,
text selection and window moves all silently froze while the README promised
the opposite. Fix: settle returns 1.0 once either button is latched, and the
freeze band **completes at the firing threshold** (`settle_full == pinch_on`),
so mouse-down posts on a stopped cursor instead of at ~71% gain. (38091ac,
[strengthening-2026-08-18.md:7](../context/strengthening-2026-08-18.md))

**Recalibrating across a camera change invalidates every span-scaled
quantity.** The stored tuning had been fitted on the phone camera
(`ref_span_img` 0.058) against a live built-in-webcam span of 0.072–0.134, so
everything scaled by span was off by roughly **2×**. The current
`camera_tuning.json` carries `ref_span_img` 0.0955; the phone fit is preserved
as `camera_tuning.phone-2026-08-18.bak`. Pose thresholds carried over
unchanged. Changing camera or camera *position* invalidates the reach box and
the working distance; `calibrate capture` (~3 min) + `reach corners` (10 s)
rebuild it entirely. (85b7564)
