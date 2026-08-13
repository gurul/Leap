# The interaction model, and why each part is what it is

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
