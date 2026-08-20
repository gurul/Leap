# Hand tracking and pose classification

What the sensors actually report, which signals separate and which do not, and
how a hand keeps its identity across dropouts. Most of this survived the strip
intact — the shipped tool is a pose classifier with no cursor attached.

---

## Trust the signal, not the field name

**An always-zero field is a correctness trap, not dead weight.**
`palm.stabilized_position` reads `(0,0,0)` on Hyperion 6.2 with a v1
controller — measured across 3,050 frames. Both the engagement gate and the
cursor projection consumed it, so height read zero every frame and the system
**could never have engaged**. It looked like a logic bug. (6d0d9dd)

The same pass removed three more fields that carried nothing: `palm_direction`
(never read), `confidence` (the LeapC header says "Not currently used (always
1.0)") and `grab_angle` (never read). (6399aaa) `HandFrame.position` still
falls back to the raw palm, so it would pick the stabilized value up for free
if a release ever started filling it.

**An instrument that reads a constant is a blind instrument, not a finding.**
`motion_scale` recorded flat `1.000` across 1,636 telemetry samples — the
dynamic reach box absorbs the span signal, so `motion_scale` carries no depth
information for diagnostics. The 1.00 the tilt diagnostic returned was the
blind instrument, not a null result; telemetry now records raw apparent
knuckle span per sample instead.
([phantom-clicks-2026-08-19.md:41-48](../context/phantom-clicks-2026-08-19.md))

---

## What separates, and what does not

Measured on the 3,639-frame corpus (`docs/context/session.jsonl`, 2026-08-12,
one user, one v1 controller). The `Config` docstring
(`src/leapinput/gestures.py:163-360`) is the fitted-threshold ledger: nearly
every field cites the distribution it came from.

| Signal | Separation | Verdict |
|---|---|---|
| finger count | fist 100% at 0 · two-finger 100% at 2 · open/roaming 100% at 5 | the cleanest discrete signal |
| pinch **distance** | pinched 17–18 mm vs open 83–87 mm — a 65 mm gap | usable; `pinch_on_mm = 50` sits mid-gap |
| `grab_strength` | >0.5 on 100% of fist frames, 0% of everything else | effectively binary on the Leap |
| `pinch_strength` | model-inferred exactly where thumb and index occlude | only a loose floor (0.50), never the primary |
| palm **height** | resting 145–183 mm vs working 137–242 mm | total overlap — useless as a gate |
| palm **angle** (clutch) | works: 18.9° median against a 30° cone | drifts — observed at 66°, freezing the cursor |

Sources: `gestures.py:190-307`, 09aa4e5, 0f5e127,
[interaction.md:137-149](../context/interaction.md).

**Height cannot gate engagement.** A hand resting on the desk is not tracked
*at all* — the rest protocol step caught 12 stray transition frames out of
3,639. **Presence is the gate**; `engage_y` is only a sanity floor (115 mm on
the Leap, dropping to 40 mm in the `xy` plane where height is the control
axis). (09aa4e5, 863d39d, `gestures.py:190-205`)

**A deliberate pinch reads as THREE extended fingers** — 100% of 443 corpus
frames, indistinguishable from a partly open hand. This is why
`lift_at_fingers = 4`, not 2. (15d5631, `gestures.py:284-307`)

**A fist reads 0 extended on 541/542 camera frames** — the most trustworthy
pose in the vocabulary, and the reason the fist carried the drag and later the
free-hand button. A held pinch reads 1–2, which is what lets a closing fist be
blocked from *starting* a pinch latch.
([strengthening-2026-08-18.md:17](../context/strengthening-2026-08-18.md))

Untested rung, then and now: **no frame in the corpus has exactly 1 extended
finger.** (0f5e127)

---

## The camera is a different sensor with the same interface

`--source camera` measured **29.4 fps at 640×480** (449 frames / 15.3 s), hand
detected on 145/150 polls, full vocabulary verified live end to end.
Current rate with the command layer running is **29.8 fps at ~29% CPU**.
([environment.md:99-129](../context/environment.md), 362252d, 31297f3)

Stack: mediapipe 1.0.0 (Tasks API only — `mp.solutions` is gone), opencv 5.0.0,
CPython 3.12, model `vendor/hand_landmarker.task` (float16, 7.8 MB, fetched
separately because mediapipe 1.x ships no bundled model).

### Three corrections the camera path needs

**1. Handedness is labelled for the un-mirrored image.** A right hand reads
`"Left"` on **186/186 frames** of a selfie feed. `camera.py` swaps it. Do not
"fix" that swap without re-measuring. (362252d)

**2. There is no trustworthy Z.** A webcam is monocular, so the interaction
plane is the image plane (`--plane xy`) and emitted Z is 0. `pinch_strength`
and `grab_strength` are synthesized from world-landmark geometry, which is the
mm-distance signal the gesture layer prefers anyway.

**3. MediaPipe's world-landmark *scale* jitters by tens of percent between
frames of the same pose** — it is re-estimated every frame from a monocular
view. So every pose distance is measured **relative to the knuckle span**,
which jitters identically and cancels in the ratio, then converted back to
pseudo-mm via `NOMINAL_SPAN_MM = 55` so the mm thresholds keep their meaning.
(`camera.py:102-108`)

### 2D pixel-space pinch beats 3D world pinch

Measured 2026-08-12: during a **held** pinch the occluded fingertips inflate
the world reconstruction to p95 47.5 mm, while a ready-to-pinch hover dips to
29.3 mm — the 3D distributions **overlap by 18 mm**. In pixel space the held
tips merge regardless of the depth guess. `calibrate analyze` now fits both
candidates and picks whichever separates better on your own data
(`Tuning.pinch_source`; currently `"image"` in `camera_tuning.json`).
(`camera.py:339-344`, `calibrate.py:220-241`)

### Camera index 0 stops meaning "the webcam"

Virtual cameras (Camo, OBS) register ahead of the built-in one in
AVFoundation's enumeration order, and open as a black feed unless their app is
streaming. Installing Camo Studio put "Camo Camera" ahead of the MacBook
camera and tracking silently died. Cameras are picked **by name** via
`system_profiler`, which enumerates in the same order; `--camera N` overrides.
(`camera.py:683-727`, [environment.md:125-129](../context/environment.md))

---

## Apparent knuckle span is the free depth signal

A hand's image size scales with 1/distance while its world span stays
hand-sized. That single observation replaced a depth model.

- **`MIN_SPAN_IMG = 0.04`** (≈ beyond ~1.2 m) rejects background people and
  out-of-range hands at zero model cost. (`camera.py:75`)
- **`HandFrame.motion_scale = ref_span / current_span`** (clamped 0.5..3.0,
  EMA-blended) makes sensitivity distance-invariant — the answer to "when I am
  far away I have to do very exaggerated motions".
- Two rules that took thought: `motion_scale` is applied **after** the deadzone
  check (image noise does not grow with distance, so the noise floor must not
  be magnified with the motion), and **positions are never scaled**.
- Leap frames carry `motion_scale = 1.0` — real depth, nothing to compensate.

**Depth Anything was evaluated and rejected** as a dependency: PyTorch plus
tens of ms/frame against a 30 fps budget, and relative-not-metric output. The
one benefit it would have bought is had for free.
([strengthening-2026-08-18.md:35-37](../context/strengthening-2026-08-18.md),
[interaction.md:242-264](../context/interaction.md))

In dynamic-palm-box mode delta scaling is **disabled** — the box itself
compensates, and scaling both would double it. See
[screen-mapping.md](screen-mapping.md#the-reach-box).

---

## Identity: the label flaps, so identity comes from continuity

MediaPipe's handedness label flaps on **fists and pinches** — curled,
self-occluded poses. Each flap made the configured hand vanish for a frame,
which reads downstream as tracking loss and released everything mid-drag past
150 ms. (402f722)

The fix, and then the fix to the fix:

1. One visible hand + a configured `--hand` = that hand, whatever the label
   says.
2. That rule over-reached. A **left hand raised in ILY** near the cursor
   hand's last position was adopted as the cursor hand, so ~1.65 s later the
   session **paused instead of submitting Enter**. Same class: a lone left-hand
   V was adopted as the cursor hand, where V is inert, so paste silently did
   nothing.
3. So identity now wins only on wrist **continuity** with where the cursor hand
   just was (max gap 500,000 µs, max wrist jump 0.18 of the frame), and two
   poses became label-trust exceptions read straight off `PoseSignals` before a
   `HandFrame` exists: `ily_shaped()` and `v_shaped()`. The classifier is
   reliable on these maximally-extended poses; the flap defense exists for
   curled hands. (5394fea, `camera.py:274-311, 404-441`)

This is load-bearing in the shipped tool: ILY's hand routing (free hand =
Enter, cursor hand = pause) is one of the five gestures.

**Asking for two hands invites a phantom.** `num_hands` is 1 when a cursor hand
is configured and two-hand gestures are off, 2 otherwise — a face or a
background person can otherwise enter as a second hand. Setting `--hand` buys
both a narrower detector and the lone-hand assignment.
(`camera.py:920-932`)

---

## Dropouts are binary, so hold the last frame — but restamp it

MediaPipe occlusion failures are whole-hand dropouts of a few frames, not
gradual noise. Both sources hold the last frame through sub-**150 ms**
flickers, so a mid-pinch dropout cannot release the button; a hand deliberately
removed still hard-disengages ~5 frames later. (`camera.py:1134-1162`,
`capture.py:194-209`)

The subtle part, learned the hard way: **the held frame must be restamped and
its velocity frozen.** The engine clocks off frame timestamps, so re-serving
the old stamp froze the engine's clock and stalled every pending release dwell
for the dropout's duration; the stale velocity would spike the gain curve.
`_prev` keeps the *original* frame so the 150 ms age check still expires.

The Leap source gained the same blip bridge on 2026-08-19, so single empty
tracking events no longer release buttons.
([hardening-2026-08-19.md:27-29](../context/hardening-2026-08-19.md))

**A reappearing hand must not teleport the cursor.** A reappearance within
500 ms with the knuckle centroid inside the old reach box (+0.05 margin)
*revives* the dying box instead of rebuilding it centred. Far or late
reappearances still get the come-to-the-hand recentre.
([hardening-2026-08-19.md:33-37](../context/hardening-2026-08-19.md)) — and
that mechanism was later **exonerated by data**: reach-box slide, re-anchor
and revival accounted for zero of 233 large-jump events, and box-change frames
are *quieter* than baseline. ([decisions.md:159-163](../decisions.md))

---

## Tracking degrades at the edges, and that is the truth gate

**Leap.** LMC1 palm error is ~8 mm in the central volume but **RMS >20 mm at
the extreme left, right or bottom**. At 23 px/mm that is a **460 px cursor
jump** — the actual mechanism behind "it goes beyond the plane". Cursor gain
therefore fades from full inside 40° off-axis to zero by 62°. Normal use on
this desk stays under 45° for 95% of frames, so the guard is invisible.
(0f5e127, [interaction.md:86-98](../context/interaction.md))

**Camera.** The same principle became `FRAME_EDGE_MARGIN = 0.04`: the reach
box is kept clear of the image boundary, because reaching a box edge that sits
flush at the frame edge demands knuckles *at* the border, where fingers are
out of frame and landmarks are extrapolated. Live telemetry found 255
right-edge samples at `box_x1 = 1.000`, with the session's only frozen-landmark
run there. (`camera.py:84`,
[edge-reach-research-2026-08-19.md:22-33](../context/edge-reach-research-2026-08-19.md))

**Landmark noise at rest is ~1–3 px**, which at 640 px across a 320 mm plane is
up to ~1.5 mm of per-frame delta. That figure sets the camera deadzone
(0.6 mm) and caps reach-box zoom at 4× — past that, noise on the plane rivals
deliberate slow motion. (`camera.py:618-621`, `reach.py:46-52`)

**Lighting is a first-class variable no threshold can fix.** A "the frame is
jittery" report was traced partly to a dark room with poor
foreground/background separation. Low light also silently extends exposure and
can halve the delivered frame rate.
([decisions.md:197-200](../decisions.md),
[latency-research-2026-08-18.md:85-87](../context/latency-research-2026-08-18.md))

---

## The hand as a ChArUco board

`reach hand` calibrates your **real** knuckle span (index MCP to pinky MCP) —
a rigid, known-size object present in every frame, which is what converts image
measurements to metric. Ruler entry (`--span-mm`, plausible range 30–120 mm)
beats the MediaPipe world-landmark median, which needs ≥60 frames of a flat
open hand to stabilise.

Deliberately **not** used to renormalize pose pseudo-mm — the calibrated pinch
thresholds live in that space and would silently shift. It powers physical
readouts only. What it found: the corner-placed box measured ~28 cm wide,
0.93× the panel's physical 30.4 cm glass — the user had unknowingly calibrated
a near-1:1 touch surface.
([interaction.md:328-342](../context/interaction.md), `reach.py:332-406`)

`hand_span_mm` is currently `0.0` in `camera_tuning.json` — the ruler step was
never run on the webcam setup.

---

## The hardware, for the record

| | |
|---|---|
| Device | Original Leap Motion Controller (2013, v1), serial `LP20006680004`, USB 2.0 |
| Measured rate | ~111 fps (667 frames in 6.0 s) |
| Driver | Ultraleap Hyperion 6.2.0.0, arm64 |
| Host | MacBook Pro M5 Pro, macOS 26.5.2 |

Hyperion **6.0 and 6.1 dropped v1 support entirely**; 6.2 restored it — do not
downgrade below 6.2. The bundled CFFI module is **CPython 3.12 only**
(`_leapc_cffi.cpython-312-darwin.so`), it needs `libLeapC.6.dylib` rather than
the `.5` the official bindings expect (hence the DDlabAU fork), and `cffi` is
required but undeclared. An M5 Pro on macOS 26 is outside Ultraleap's tested
matrix — it works, but empirically. (abe2d34,
[environment.md:19-92](../context/environment.md))

The Leap path is **legacy** as of 2026-08-20; the daily driver is the built-in
webcam. Re-verify with `scripts/verify-env.sh` rather than trusting the file.
Known dead ends around this hardware are in
[dead-ends.md](dead-ends.md#the-leap-ecosystem).

---

## Real depth, if it ever comes back

LiDAR/TrueDepth are **not reachable from the web** — Safari exposes no depth
API — so real metric depth needs a native companion. `ios/LeapDepth/` (Swift +
AVFoundation) is scaffolded and proven live with real millimetre readings from
front TrueDepth at 640×480: synchronized RGB + depth over plain TCP, wire
format LPD1, received by `python -m leapinput.phonedepth`.

Phase 1 (prove the pipe) is done. **Phase 2 — `DepthPhoneSource`, sampling the
aligned depth map at each landmark pixel — was never built.** It would retire
every monocular workaround at once: span-as-depth, world-scale jitter,
`motion_scale`, the ChArUco hand assumption. Currently 1–14 fps; target 30+.
Free-team signing on the phone expired ~2026-08-25.
([depth-companion-plan.md](../context/depth-companion-plan.md))
