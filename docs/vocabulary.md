# The gesture vocabulary

## Cursor control

| Pose | Action |
|---|---|
| point (1–3 fingers) | cursor moves |
| pinch | click, and **only** a click (two quick pinches = real double-click) |
| **free-hand fist** | **DRAG** — holds the mouse button while the cursor hand points |
| cursor-hand fist | drag (`--source leap`; off by default on camera¹, `--drag` re-enables) |
| open hand (4–5 fingers) | **LIFT** — cursor parked, reposition freely |
| hand out of view | disengaged, everything released |

¹ On camera, pinch misreads made the cursor-hand fist flaky.

**A pinch cannot drag** (2026-08-20, `Mapping.pinch_drag`, `--pinch-drag`
re-enables). The cursor is pinned to a single pixel for the whole hold, so a
pinch can never select text or lift an icon. It used to: the cursor tracked
the hand while the button was down, so any drift was a real drag to macOS, and
the `CLICK_TRAVEL_PX` pin-back only corrected where the mouse-*up* landed —
after the drag had already happened. Clicking a UI element is the common case
(and the one a source-mapping tool like React Grab needs to be exact); dragging
is the rare one, so it moved to a gesture that cannot be confused with a click.

**Drag is the free hand's fist.** Close the free hand, and the mouse button
stays down while the *cursor* hand points — one hand holds, the other moves,
which is how a mouse has always worked, and what rotating a 3D figure wants.
It arms after 0.18s so a hand closing on its way elsewhere cannot press;
release is never gated — opening the hand, losing it, or pausing drops the
button on that frame.

Slowing the hand down engages **precision mode** (PRISM): sub-1:1 motion for
tiny targets like the traffic-light buttons, transparent 1:1 at speed. Clicks
commit at contact depth (the deep-commit gate), on a cursor frozen by the
settle ramp — see [the phantom-click note](context/phantom-clicks-2026-08-19.md).

## Pose-hold commands (camera & phone paths)

Hold the pose until the ring in the preview fills, release to fire — the
shape every shipping mid-air UI converged on, and nothing here can carry the
hand out of frame the way cut-style swipes did:

| Pose | Hold | Action |
|---|---|---|
| frame a rectangle with both hands (thumb+index L-shapes) | ~0.8s | **FRAME SHOT** — screenshot of the framed region to the clipboard (`--pane window/tab`) |
| OK sign (pinch, 3 fingers up) | ~0.6s | Mission Control |
| ILY sign (thumb+index+pinky) | ~1.5s | pause / resume all gesture control (fires on ring-fill, with a chime) |
| thumbs-up | ~0.6s | **DICTATE** toggle — mic ON (Tink), thumbs-up again = OFF (Pop). Holds the Option key in between; rebind your dictation app (Willow Voice etc.) to a bare Option hold. Your hand is free while dictating. ILY pause also closes the mic; a 3-minute watchdog is the backstop |

While you hold the frame pose, the framed region is highlighted on the actual
screen, Cmd+Shift+4-style — amber while the dwell fills, green when releasing
will fire. The highlight window is excluded from screen capture, so it never
appears in its own shot (`--no-screen-overlay` disables it).

## The free hand

The hand the cursor doesn't follow is a second command palette — raise it
alone or alongside; a hand appearing away from the cursor hand's last
position is trusted to be the free hand:

| Pose (free hand, ~0.6s) | Action |
|---|---|
| pinch and hold | Cmd+C ("grab it") |
| V sign (thumb ignored) | Cmd+V (the literal letter) |
| ILY sign | Enter (submit what you dictated) |
| fist (hold, 0.18s to arm) | **DRAG** — mouse button down until you open the hand |

The full dictation loop: thumbs-up (Tink) and speak, thumbs-up again (Pop —
Willow pastes), free-hand ILY to submit.

ILY and the V sign get special routing: for these poses a hand raised alone
is always routed by the handedness label — the "a lone hand is probably the
cursor hand" adoption rule (built for flappy fists and pinches) stands down.
ILY because which hand it's on changes the command entirely (free hand =
Enter, cursor hand = pause); V because it *only* exists on the free hand, so
adopting a lone left-hand V as the cursor hand silently swallowed every
paste. Both are extended, distinctive poses the classifier labels reliably —
exactly the opposite of the curled poses the adoption rule defends against.

Two transition guards keep the cursor hand's own gestures from leaking into
this layer: releasing a click-pinch into an open palm passes straight through
the OK shape (which used to arm Mission Control every time), and a fist opens
thumb-first through a perfect thumbs-up — so a button posture casts a short
(0.4s) shadow in which the matching command hold refuses to arm. Deliberate
poses formed from rest are unaffected. And the cursor engine only stands down
once a command hold is actually *filling* (past its arm dwell), not on the
first pattern-matching frame — single-frame pose flickers no longer blank the
pointer mid-gesture.

## Verified, pose by pose

Replaying 3,639 recorded frames of real use — each pose does exactly one
thing and nothing else:

| pose | click | grab | lift | cursor moves |
|---|---|---|---|---|
| pinch (443 frames) | 1 | 0 | 0 | 437 |
| fist (444) | 0 | 1 | 0 | 438 |
| open hand (442) | 0 | 0 | 1 | 28 |
| two-finger (554) | 0 | 0 | 0 | 554 |
| roaming (665) | 0 | 0 | 0 | 0 |

## The four numbers that took the longest

**Lift is 4 fingers, not 2.** A deliberate pinch reads as *three* extended
fingers on this hardware — 100% of 443 corpus frames. Lifting at 2 parks the
cursor at the precise instant of every click. This is the single least
obvious number in the system.

**Gain turned out to be the tracking fix.** The control-display curve runs
2.12 px/mm at 10 mm/s up to 23.32 px/mm at 500 mm/s, and `--gain` scales both
ends together so the ~11× slow-to-fast ratio survives. Raising it took frame
rate from 36 → 116 fps and hand visibility from ~32% → ~100%, with no
tracking parameter touched: higher gain means less hand travel, which keeps
the hand in the reliable centre of the sensor's cone instead of out at the
edges where LMC1 palm error goes from ~8mm to RMS >20mm. At 23 px/mm, 20mm of
noise is a 460px cursor jump. Gain past 40° off-axis therefore fades to zero
by 62°.

**Hysteresis takes two forms.** Continuous signals (pinch distance, palm
angle, grab strength) use Schmitt triggers — two thresholds with a band
between them. Finger count is an *integer*, so there is no band to sit inside
and the guard has to be time. The debounce is deliberately asymmetric: 0.05s
to engage, 0.25s to lift. A symmetric 0.08s window produced ~28 clutch cycles
in one 60-second session.

**A fist cannot latch while a pinch is held.** They are one continuum —
closing a pinch passes through both, and both drive the same physical button.
Naive routing posts down/down/up/up and macOS loses track of whether a drag
is in progress. Whichever latched first owns the button, and the driver owns
button state idempotently on top of that.

Full derivations, including the dead ends, are in
[`context/interaction.md`](context/interaction.md).
