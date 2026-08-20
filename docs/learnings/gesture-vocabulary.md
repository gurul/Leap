# Gesture vocabulary design

Why the vocabulary is these poses, held for these times, and what shape the
recurring failures take. Most of this is live: the shipped tool is exactly this
layer with the cursor unsubscribed.

---

## The design rules, earned one bug at a time

**1. One pose, one meaning.** Every scroll storm in this repo came from a pose
collision. Scroll on index+middle is near-identical to natural pointing once
the index fingertip drives the cursor — one session emitted **61 scroll events
inside a single clutch** purely from pointing. Scroll moved to the fist, and
was then removed from the fist too, because a fist is a drag. Scroll has no
home today. (63161f2, caa53ad)

**2. Nothing may carry the hand out of frame.** Swipes had clean velocity
separation — roaming peaks at 419 mm/s, a swipe at 803 — and were cut anyway,
because the motion carries the hand out of the tracking volume and trips the
dead-man. A live 60 s run fired `swipe.right` and `swipe.down`
unintentionally, and `swipe.down` landed immediately before a disengage. Every
command since is a **static pose-hold**. (a2059a7,
[interaction.md:139-143](../context/interaction.md))

**3. Poses you pass *through* are not poses.** See below — this is the single
most repeated bug shape in the repo.

**4. Whichever latched first owns the button.** Pinch and fist are one
continuum: closing a pinch passes through both, and both drive the same
physical button. The live log showed `select.down, grab.down, grab.up,
select.up` nested on a single gesture — the driver posted down/down/up/up and
macOS lost track of whether a drag was in progress. Fixed at two levels: the
gesture layer arbitrates, and the driver owns button state **idempotently**, so
no future vocabulary change can reintroduce the double press. (6fc79da)

**5. A release is never gated.** A stuck button is worse than any missed click.
The kinematic pinch gate, the drag arm delay and the command holds all gate
*onset* only.

---

## Hysteresis takes two forms, and the signal type dictates which

Continuous signals — pinch distance, palm angle, grab strength — get **Schmitt
triggers**: two thresholds with a band between them.

Finger count is an **integer**. There is no band to sit inside, so the guard
must be time: a debounce. And it must be **asymmetric** — 0.05 s to engage,
0.25 s to lift. A symmetric 0.08 s window produced **~28 clutch cycles in one
60 s session**, because finger count naturally flaps between 1 and 2 while
pointing and either direction was equally easy. Engaging should feel instant;
lifting interrupts the user, so it must be deliberate. (caa53ad,
[interaction.md:50-60](../context/interaction.md))

The same idea applied to discrete pose matches is `PoseHold`: a 0.15 s arm
before the ring starts, and a 0.12 s flicker grace.

**Gate the button on the debounced signal, never the raw one.** Grab was gated
on a raw `grab_strength` threshold with no hysteresis, so a momentary dip
released the button mid-drag — the live log shows `grab.down`/`grab.up` pairs
firing repeatedly. Moving the button to the debounced finger count alone (100%
accurate across 444 real fist frames) gave **1 grab.down, 0 grab.up, button
held for all 438 tracked frames**. Related: the pinch guard read
`grab_strength` *instantaneously*, so a momentary dip latched a click on top of
a held fist — `grab.down` then `select.down` with no release between, leaving
the button down through 400+ scroll events. The guard now reads the **latched**
grab state. (caa53ad, 37d923a)

---

## Poses you pass through are not poses

Three separate live failures, one mechanism, two shadow implementations.

| What happened | Why | Fix |
|---|---|---|
| Mission Control armed on **every** pinch release | releasing a click-pinch into an open palm extends middle/ring/pinky while thumb and index are still close — which **is** the OK pose | `BUTTON_POSE_SHADOW_S = 0.4`: a button posture casts a shadow in which the matching hold refuses to arm |
| dictation fired when a fist opened | a fist opens **thumb-first**, through a perfect thumbs-up | same shadow, tracked **per posture** — a thumbs-up can itself read pinch-distance ≤50 mm (curled index near the thumb base), so one shared shadow would have suppressed dictation forever |
| the mic opened while composing a frame shot | the L-pose is thumbs-up plus an extended index, so a hand entering or leaving the two-hand frame passes **through** thumbs-up; `not framing` only guarded the frames where **both** hands still read as L, and the transition was the gap | `FRAME_SHADOW_S = 0.6`: while a framing hold is armed, and for 0.6 s after, **no** other command can fire |

Sources: [interaction.md:187-198](../context/interaction.md), 0b19969,
`commands.py:281, 310`.

A **deliberate** OK never casts a shadow — its back fingers are extended — so
it still arms instantly from rest. The frame shadow is the user's own
diagnosis, and the better one: *"not allowing other things to be triggered
while the framing is happening. Until it's released."*

**Any new pose should be checked against what it passes through.**

---

## Discrete commands: static holds with fire-on-release

The shape every shipping mid-air vocabulary converged on — Quest's system
gesture, TouchFree's Hover & Hold — and an 800 ms dwell measured **0% selection
errors** in the ISS 2022 mid-air study.

`PoseHold` implements the rules the research prescribes:

- a pose must persist **0.15 s** before the progress ring starts, so
  single-frame classifier flicker never arms;
- sub-**0.12 s** dropouts do not cancel a hold;
- **release commits** — holding past full keeps the abort window open;
- `fire_on_fill` inverts it for the three poses where waiting for release feels
  broken (pause, mic, Enter).

Dwells in use (`commands.py:337-356`; add the 0.15 s arm for the total the
hand feels): frame shot 0.65 → ~0.8 s, Mission Control 0.45 → ~0.6 s, ILY
pause 1.5 → ~1.65 s, dictate 0.45, copy/paste 0.45, Enter 0.3. (38091ac,
[strengthening-2026-08-18.md:21-29](../context/strengthening-2026-08-18.md),
`commands.py:86-160`)

**A 1 s ILY paused a session by accident.** A relaxed hand with middle and ring
drooping matches the ILY pattern, and one second of it is easy to produce
without meaning to. The dwell rose to 1.5 s (~1.65 s including the arm), and
`fire_on_fill` was added so the chime sounds the moment the hold completes —
holding past a silent full ring feels broken. (e999f92, `commands.py:336-341`)

**Dictation went shaka-hold → thumbs-up-hold → thumbs-up TOGGLE**, both earlier
forms failing in use: the shaka hold cramped, and the thumbs-up hold was
unsustainable and drifted the hand out of view. The ergonomics literature
prescribes short deliberate poses over sustained static holds, so it became a
toggle — one short thumbs-up opens the mic, another closes it, and between
toggles the hand is entirely free. A held system-wide Option is a serious
failure mode, so two safety nets exist: the ILY pause closes the mic, and the
driver force-releases after `MAX_DICTATION_S = 180`. (`commands.py:23-30`,
`driver.py:562-567`)

---

## Clicks: the two things that actually go wrong

### The Heisenberg effect — forming the gesture moves the pointer

Wolf et al. (CHI 2020) measured this at **30% of all mid-air pointing errors**,
and found that backdating the click to gesture onset cut errors by **25%**.
Ours drifts for a measured reason: pinching curls the index, which *is* the
tracked point.

Two responses shipped together:

- the cursor freezes progressively as the pinch closes (full speed at 55 mm,
  frozen by 38 mm), mirroring TouchFree's growing click deadzone;
- the driver records the cursor position when the pinch starts forming and
  restores it before posting button-down.

The anchor is trusted only **fresh** (≤0.75 s) and **nearby** (≤75 px), and it
dies with its click — it originally survived `select_up`, so a second quick
click warped back to the *first* click's position, seconds stale. Mouse-**up**
on a click (<12 px of held travel) is pinned to the down pixel, because macOS
resolves the click target on up.

A second-order bug from the same machinery: the anchor warp at `select.down`
was being undone by the next `settle = 1.0` absolute move and accrued into
`_travel`, defeating the <12 px pin-back — *exactly the clicks the anchor
exists to save were landing as drags*. The offset now lives for the whole
button hold and dies with the button. (a0d07da, 88db56e,
[hardening-2026-08-19.md:38-42](../context/hardening-2026-08-19.md))

Related published number: hand pointing fails **95.7% by missing** (spatial
targeting) versus 4.3% by slipping, while gaze is 99.2% slips (arXiv
2603.15991). Midas touch is a gaze problem; for hands the payoff is landing the
click, not more gating.

### Phantom clicks had two different causes, and two different fixes

**Mid-flight.** First live reach-test session on the phone-on-stand setup: of
28 button presses, **1 was a true click** (<12 px held travel) and **24 latched
mid-flight** (median 550 px of travel while held). A relaxed, foreshortened
hand travelling across the fitted box reads pinch-shaped long enough to beat
the 2-frame dwell. The literature says selection has a kinematic signature —
people decelerate to near-stillness before committing (RIDS, UIST 2022; arXiv
2602.01061 cuts bare-hand error 22% → 7.5% by weighting pre-confirmation
history). So `Config.pinch_arm_max_speed = 150 mm/s`, scaled by box zoom: a
pinch may only **latch** below it. Onset-only, and the settle freeze is skipped
above the same speed, since no click can form there. (f819df5,
[interaction.md:212-234](../context/interaction.md))

**At rest.** Live telemetry, 11 recorded clicks each with a 2 s pre / 0.5 s
post signal window:

| class | count | pinch bottom |
|---|---|---|
| deliberate | 9 | ≤ **25.6** pseudo-mm |
| phantom (slow rest-band drift) | 2 | **28.2** and **33.9** |

A pinch is a **contact** event. A relaxed pointing hand parks the thumb 28–45
pseudo-mm from the index, and the calibrated `pinch_on` (37.7) sits *inside*
that band. No second signal separates the classes: `pinch_strength` is
synthesized from the same distance and the extended-finger bits read
identically.

**A velocity gate was considered and rejected** — one deliberate pinch
descended at 0.8 mm per 5 frames and still bottomed at 13.8, so a velocity gate
would break real slow clicks. Depth separates the classes; speed does not.

Fix: `Config.pinch_commit_mm` fires the Schmitt at `pinch_on − 10` (27.7) while
`pinch_off`, the release assist and the settle ramp stay put — the extra
descent happens on an **already-frozen** cursor. Margin honesty: the separation
is thin, 25.6 vs 28.2. The Leap keeps `None`; its real depth signal never had
the rest-band overlap.
([phantom-clicks-2026-08-19.md](../context/phantom-clicks-2026-08-19.md))

Corroborating scale: one buggy session — pose thresholds fitted at a different
camera geometry — logged **352 `select.down` events** with rapid down/up
cycling. (6821401)

**A relaxed post-click hand parks inside the hysteresis band.** A held pinch
measures 15–18 mm, but a hand that relaxes "kind of open" after a click never
reaches the 68 mm off threshold — the click becomes a silent hold. Release
assist: distance above the *engage* threshold, sustained for 0.20 s, is read as
release intent. Single-frame noise spikes mid-drag are far shorter.
(`gestures.py:246-252`)

---

## The frame shot: commit the composition, not the release

The flagship shipped gesture, and the one with the sharpest regression case.

`extended` is a Schmitt trigger (calibrated here: `extend_on` 61.1°,
`extend_off` 80.1°), so a finger uncurling out of the L keeps reading as
extended for several frames while the hand is **already moving** — and those
frames, still classified as framing, were the ones overwriting the rect. The
commit sampled the single worst moment of the gesture.

Fix: discard every sample within `RECT_RELEASE_GUARD_S = 0.20` of the release
and commit the **median** of the `RECT_SETTLE_WINDOW_S = 0.30` window before it
(median, not mean — one late landmark spike lands exactly on a corner).

Pinned by a test that fails hard on the old path: a rect composed at
(0.25, 0.25, 0.75, 0.75) committed as **(0.4375, 0.4167, 0.5625, 0.5833)** —
about a **quarter** of the intended area. (0b19969,
[decisions.md:166-187](../decisions.md))

This is the click anchor's argument applied to two hands: trust where the user
was aiming before the gesture that commits it moved them.

Two other properties the frame shot depends on: the whole-frame fingertip fix
([screen-mapping.md](screen-mapping.md#one-box-per-hand--so-hands-are-not-comparable-in-box-coordinates))
and full-rate detection ([latency-and-pipeline.md](latency-and-pipeline.md#the-detection-rate-cap-measured-well-and-reverted-anyway)).

---

## `busy` must not fake a tracking loss

A command hold used to be answered by feeding the cursor engine an empty
`Snapshot`. An empty Snapshot is the **tracking-loss path**: it force-released
the pinch and grab latches, rebuilt the finger ladder from 5, and fired
DISENGAGE.

Measured over 256 s of recorded session: **21 clutch drops, zero caused by an
actual hand loss, 17 on a `busy` frame**, 8 of which killed a latched button
mid-gesture. 21 busy episodes with a **median duration of 0.104 s** — the
population was PoseHold's 0.12 s flicker-grace *tail*, not anyone holding a
pose. The dominant trigger was two-handed pane framing: 321 of 386 busy frames
carried the thumb+index L.

Fix: `GestureEngine.park()` (drop the clutch, keep everything else), and
`CommandEngine.busy` additionally requires the pose to have matched within
`BUSY_STALE_S = 0.1 s`. **Pause still feeds an empty Snapshot and still
releases everything** — that dead-man property is deliberate. (31297f3,
[decisions.md:100-121](../decisions.md))

Note the shape: this is the **third** time a shared release path was invoked
for a non-release reason. The first was the clutch deadlock —
`_release_all` called `force_off` on the clutch, which clears its pending-dwell
timer, so calling it every un-clutched frame meant the dwell could never
accumulate and the clutch could never engage at all. Caught by the replay
corpus, not by hand. (63161f2)

---

## Small state bugs worth not rediscovering

- **`_last_swipe` must be `float('-inf')`, never `0.0`.** Zero reads as "a
  swipe just happened at t=0" and suppresses every swipe until the refractory
  elapses — invisible against real sensor timestamps, fatal on any timebase
  starting near zero. (`gestures.py:383-387`)
- **The finger ladder must reset to 5 on tracking loss and on disengage.** A
  debounced count of 0 surviving a loss means the first frames of a reappearing
  hand read as FIST and fire a phantom `GRAB_DOWN` at the parked cursor.
  Empirically reproduced before the fix. (`gestures.py:458-481`)
- **Silent `getattr` dispatch let an entire vocabulary be unwired with zero
  errors.** The vocabulary moved to fist-as-click but `DirectDriver` only had
  handlers for `select.down`/`select.up`, and `getattr`-based dispatch silently
  ignores anything unhandled — so `grab.down`/`grab.up` were emitted into
  nothing for entire sessions. The log looked correct while the click did
  absolutely nothing. Dispatch is now loud. (c186b3c) *Worth remembering now:
  the 2026-08-20 strip is itself exactly one unsubscribed line.*

---

## Free-hand routing, and the drag

The hand the cursor does not follow is a second command palette. ILY and V get
label-trust routing (see
[hand-tracking.md](hand-tracking.md#identity-the-label-flaps-so-identity-comes-from-continuity));
everything else routes by continuity.

**Drag is the free hand's fist** (legacy). One hand holds, the other moves —
how a mouse has always worked, and what rotating a 3D figure wants. It arms
after `DRAG_ARM_S = 0.18` so a hand closing on its way somewhere else cannot
press; release is never gated — an opened hand, a vanished hand and a disabled
engine all drop the button on the same frame. Pausing mid-drag emits DRAG
inactive for the same reason it cancels dictation.

**Copy is behind `--legacy` for a specific reason:** free-hand pinch-hold fires
Cmd+C, which **is** React Grab's trigger — firing it from a resting pinch would
grab components nobody asked for. (`commands.py:633-644`)

**Open, unfixed: EX-2** — free-hand copy/paste/enter can fire while the cursor
hand holds a button. Suppressing it needs a priority-rule decision.
([hardening-2026-08-19.md:74-75](../context/hardening-2026-08-19.md))

**Open, unfixed: FH-1** — headless sessions get no hold-progress ring, which is
the abort affordance that fire-on-release depends on. This one bites the
shipped tool.

---

## Corpus verification

Replaying 3,639 recorded frames of real use — each pose does exactly one thing
and nothing else:

| pose | click | grab | lift | cursor moves |
|---|---|---|---|---|
| pinch (443 frames) | 1 | 0 | 0 | 437 |
| fist (444) | 0 | 1 | 0 | 438 |
| open hand (442) | 0 | 0 | 1 | 28 |
| two-finger (554) | 0 | 0 | 0 | 554 |
| roaming (665) | 0 | 0 | 0 | 0 |

([interaction.md:17-26](../context/interaction.md))
