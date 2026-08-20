# Measurement method

How this project settles arguments. Every threshold here was fitted from
recorded hand data, every claimed fix is pinned by a test that fails on the old
code first, and the leading hypothesis has been killed by its own verifier more
than once.

This page is the most reusable thing in the repo. The features change; the
method is why any of the numbers can be trusted.

---

## Capture must wait for the pose, never for a clock

**A countdown makes the human race the protocol.** The first guided capture
used a 3-second countdown and recorded **the previous pose in every one of
seven steps** — a clean one-step label shift that produced thresholds that were
wrong but plausible-looking. Every value derived from it was wrong in a way
that looked fine.

Replaced by **self-synchronizing capture**: each step blocks (up to 45 s) until
the expected pose has been held continuously for **0.6 s**, and each step must
prove **≥70%** of its frames satisfy the predicate before analysis trusts it.
The same predicate drives the live panel and the validation, so what you watch
is what is enforced. The fitter also flags sparse capture (<60% of the expected
~100 fps) and exits 2 with "thresholds from this session would be wrong."

The bad session is kept in the tree as
`docs/context/session-INVALID-2026-08-12.jsonl` — it is the evidence for the
`stabilized_position` defect and a regression fixture. (6d0d9dd, e890fe8,
`record.py:33-222`)

**Any future recalibration protocol should be pose-gated and self-validating.**
The same wait-for-a-hand-first pattern is used in `calibrate capture` and
`reach roam`.

---

## The fitting rule: place the band inside the measured gap, or refuse

Per signal: take the two populations that must be separated, find the gap
between p95 of the low cloud and p5 of the high cloud, and place `on` at **35%**
and `off` at **70%** of that gap. **No gap = the signal keeps its default,
loudly.**

Minimum gaps: 8.0° finger bend, 0.06 thumb ratio, 10.0 mm pinch.

The "apart" protocol step (thumb and index ~3 cm apart, ready to pinch) exists
because the pinch **off** threshold lives between a held pinch and a
ready-to-pinch hover — the two postures a real click cycles between. Fitting it
against a wide-open hand it never sees would produce a release threshold no
click ever exercises.

The fit ends by **reclassifying the corpus** with the fitted single-frame
thresholds and printing the hit rate per pose. (`calibrate.py:12-43, 158-261`)

The reach-box fit has the same shape: p2..p98 of a comfortable roam, 10% margin
per side, and guards that **refuse** rather than save garbage — an axis roamed
under 16% of the frame is a hover not a reach, zoom is capped at 4×, and fewer
than 60 frames is not a fit. (`reach.py:42-142`)

---

## Corpora, and why time comes from the sensor

Every frame carries the tracking service's microsecond timestamp. Dwell and
refractory windows therefore measure **when the motion happened**, not when
Python got to the callback — a GC pause or a slow subscriber cannot stretch a
dwell.

The engine clocked dwell off `time.monotonic()` once, and it was wrong for
exactly that reason. A companion bug from the same replay: `_last_swipe`
initialized to `0.0` read as "a swipe just happened at t=0" and suppressed
every swipe until the refractory elapsed. (09aa4e5)

Sensor time is also what makes the corpus a **real regression test**: a
recorded session replays to exactly the same intents at any speed.

| Corpus | What |
|---|---|
| `docs/context/session.jsonl` | 3,639 frames, 2026-08-12, one user, one v1 controller — the provenance of almost every Leap threshold. Cited by name in `driver.py:30`, `gestures.py:166`, `tests/test_replay.py:19` |
| `docs/context/session-INVALID-2026-08-12.jsonl` | 3,050 frames from the countdown protocol. Kept deliberately as evidence and fixture |
| `camera_session.jsonl` | the camera-path capture the fitter reads (gitignored, machine-local) |
| `~/.leapinput/telemetry/clicks-<date>.jsonl` | every button commit with 2 s before and 0.5 s after |

The command layer needs a **wall-clock bridge** for the opposite case: empty
snapshots carry no timestamp, and without the bridge a hand vanishing mid-hold
freezes the clock and the hold never disarms — which for dictation means a
system-wide Option stays held until the hand happens to return.
(`commands.py:490-503`)

---

## Statistics traps that produced false findings

**Comparing p75 against p99 invents an overlap that is not there.** The first
analyzer reported that roaming speed overlapped swipe speed badly enough to
misfire, by comparing swipe p75 against roam p99 — a burst's *average* against
a sustained motion's *ceiling*. Peak-vs-ceiling shows **384 mm/s of headroom**
(roam tops at 419 mm/s, swipe peaks at 803), so the threshold was set at 600.
`record.py analyze` now reports swipe peak p95 vs roam ceiling and the headroom
between them. (09aa4e5, `record.py:276-289`)

*That false alarm nearly got swipes cut on 2026-08-12 — for the wrong reason.
They were cut later for a better one; see
[dead-ends.md](dead-ends.md).*

**An instrument that reads a constant is a blind instrument, not a finding.**
`motion_scale` recorded flat 1.000 across 1,636 telemetry samples because the
dynamic box absorbs the span signal. The 1.00 the tilt diagnostic returned was
the instrument, not a result. Check any derived telemetry channel varies before
trusting a null from it.
([phantom-clicks-2026-08-19.md:41-48](../context/phantom-clicks-2026-08-19.md))

---

## Feel is not evidence — the scored bench

The mapping changed three times in two days, which is why every session serves
a scored bench at `http://127.0.0.1:8788/bench`. It is deliberately a
**separate page** from the telemetry dashboard: the dashboard answers "what did
the hand do" while you work; the bench asks you to perform a **known task** and
scores it, and only the second can answer "is this worse than it was".

**CLICK test** — a **fixed** ladder of ten targets, never random, because two
runs are only comparable if they asked for the same targets. Radii 34, 34, 24,
24, 16, 16, 11, 11, **7, 7** px; 7 px is the macOS traffic-light button, the
target PRISM exists to make reachable. Scores: hit rate, median/mean miss,
**systematic bias** in x/y (a repeatable offset in one direction is the
projection, not your aim), and small-target rate for r ≤ 11 px.

**FRAME test** — four fixed rectangles; the region actually captured is drawn
back in green and scored by **IoU**, **centre offset** (a shifted map) and
**size ratio** (a wrong zoom). Two distinguishable failure modes, which "it
feels off" is not.

The header prints the mapping that produced the score, because a number is only
comparable to another number taken under a known projection.
(`telemetry.py:499-676`, [troubleshooting.md:68-92](../troubleshooting.md))

**Bisect with one flag at a time.** `apply_projection_flags` exists as its own
function because these are the bench's independent variables — one switch per
2026-08-18/19 projection change, so a score attributes to one of them instead
of to "the new mapping" as a lump:

```bash
scripts/leapctl on --reach-center fixed   # one projection, not one per engagement
scripts/leapctl on --reach-inset 0        # box maps exactly to the screen
scripts/leapctl on --no-precision         # drop the PRISM offset
scripts/leapctl on --no-reach             # whole frame, the pre-2026-08-18 map
```

(All of the above require `--legacy` to be meaningful, since nothing drives the
cursor by default.)

---

## Live telemetry: record the evidence before you need it

*"Guesses about phantom clicks have been wrong before."* The telemetry layer
records **every** button commit with a 2 s pre-window (120 frames from a
900-frame / ~15 s ring) plus 30 post-frames, and lets the user tag unintended
ones live from a browser (the `P` key).

Two design details that mattered: cursor x/y is sampled **at the click** rather
than inferred from the nearest ring sample, because a frame of cursor travel is
a sizeable fraction of the error being measured; and every entry point
swallows exceptions, because **diagnostics may lose data, never break
control**. (`telemetry.py:1-30, 147-175`)

It paid for itself immediately: the phantom-click diagnosis, the 255
right-edge samples that found the frame-boundary starvation, and the 65-click
projection table are all telemetry findings.

A related steadiness instrument: `reach test` runs the **real** engine and
driver against a `DryRunBackend` and measures dot RMS over a rolling ~2 s
window against a **raw unfiltered** baseline — their gap *is* the filtering,
measured instead of vibed. A window only counts as REST when the raw track's
peak-to-peak excursion is under 40 px, or deliberate motion would read as
jitter. Target: ≤2 px RMS. (`reach.py:609-656`)

---

## Adversarial swarms against real repositories, not search snippets

The pattern recurs and has a track record:

| Pass | Shape | Outcome |
|---|---|---|
| 2026-08-12 OSS survey (73adc63) | 34 agents, 5 lenses, 25 candidates each adversarially verified against the real repository — GitHub API, clones, on-machine probes | 13 ADOPT, 8 TRIAL, 4 REJECT, **0 unverifiable**. Artifacts: [oss-dossier.md](../oss-dossier.md), [plan.md](../plan.md) |
| 2026-08-18 vocabulary review (402f722) | 7-dimension literature swarm grading poses on comfort × trackability across 65 sourced findings | produced the dictation toggle and the retired fist |
| 2026-08-19 control hardening (f59fad4) | two assess → adversarial-verify swarms against PuzzleCam | 27 findings, 16 applied **each with a regression test**, 8 deferred with sign-off notes |
| 2026-08-20 jitter hunt | five lenses, 29 candidates | 3 survived; the survivor list includes an explicit **REFUTED** entry |

**The discipline that makes it work is the adversarial second pass** — the
verifier is told to refute the finding. It killed the repo's own leading
hypothesis: PRISM was blamed for a measured +9.8 px x-bias, and the verdict was
*"the stated mechanism is arithmetically false; the claimed numbers do not
reproduce; and the proposed fix would CREATE the exact symptom under
investigation."*

A finding is only worth recording with its **negative space** too. The jitter
hunt's most useful output was the list of things ruled out — reach-box
slide/re-anchor/revival (zero of 233 large-jump events) and hand reacquisition
(zero of 233) — so nobody chases them again.
([decisions.md:141-163](../decisions.md))

---

## The substrate that makes 337 hardware-free tests possible

Four layers, each knowing only the one below:

```
capture   Leap / camera frames → HandFrame   (the SOLE importer of `leap` / MediaPipe)
gestures  HandFrame → Intent                 (Schmitt triggers, engagement state)
driver    Intent → Backend                   (gain curve, click stabilisation)
actions   Backend → the machine              (Quartz, or DryRun)
```

`HandFrame` is a plain frozen dataclass, so the gesture engine — where all the
fiddly temporal logic lives — is tested by **synthesizing frames**, with no
device and no hands. The `Intent` enum is also the seam a CUA driver would plug
into: gestures become high-level commands for an agent without touching the
layers below.

Test count over the project: 14 → 26 → 42 → 87 → 149 → 181 → 246 → 297 → **337
(5.4 s, measured 2026-08-20)**.

The tests that matter most are the safety ones —
`test_tracking_loss_releases_a_held_button` and
`test_select_up_precedes_disengage` — and several replay **real captured
frames** through the actual driver.

This layering is also why the 2026-08-20 strip could be **one unsubscribed
line** with nothing deleted: without `engine.subscribe(direct.on_intent)`, no
`Intent` reaches the cursor. (abe2d34,
[testing.md:5-15](../context/testing.md), `cli.py:436-443`)

**One known test defect:** `tests/test_calibrate.py:114` opens
`camera_session.jsonl` by relative path with no skip guard, and that file is
gitignored — so it errors on a fresh clone or from any cwd but the repo root.
Its Leap-side counterpart is handled correctly (`tests/test_replay.py:19`
builds the path from `__file__`), which is what lets the corpus replay run
anywhere.

---

## Two more habits worth copying

**Dry-run first, always.** `--backend dry-run` is the default because a
half-tuned Schmitt trigger wired to the real cursor will fight you for control
of the machine you need in order to fix it. `--tutorial` is the end-to-end
verification: a guided practice room over the live preview that advances only
when the real pipeline detects the real gesture, and it **forces** dry-run.
(Note: the tutorial still teaches the legacy point/click/drag vocabulary.)

**Unrouted things must be loud.** Silent `getattr` dispatch hid a dead gesture
for a whole session (c186b3c), and in `reach.py` an unrouted subcommand fell
through to `clear` and silently **wiped the calibration** — the fallthrough now
asserts. Both are the same lesson: a dispatch table that ignores what it does
not know will eventually be handed something important. (`driver.py:265-281`,
`reach.py:900-905`)
