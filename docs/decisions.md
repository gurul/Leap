# Decision log

This repo is an exploratory medium. Features get built, measured, and then
kept, shelved or cut — and the ones that were shelved are expected to come
back. That only works if the *reasoning* survives, not just the diff.

**The rule: nothing is deleted.** Shelved features stay in the tree, wired off
behind a flag. This file records what moved, when, why, what evidence drove
it, and exactly how to bring it back. Every entry should be readable by
someone (or some agent) who was not in the room.

Format per entry: what changed · why · the evidence · how to restore · what
would make us reverse it.

---

## 2026-08-20 — the hand stopped driving the cursor

**What.** The shipped tool became five gestures: mic (thumbs-up), Enter (ILY
on the free hand), paste (V), frame shot (both hands), pause (ILY on the
cursor hand). Pointing, clicking, dragging, copy and Mission Control are wired
off.

**Why.** Stated plainly by the user: *"i only want the hand gesture control
for enter and mic and screenshot"*, and separately *"i don't need it
traditionally for cursor control, a mouse does the job well enough"*. The
tool's real jobs are CAD/GenCAD work, React Grab–style UI editing, and feeding
screenshots to an LLM — none of which need a hand-driven pointer.

**Evidence.** Every expensive bug in this repo lived in the pointing path. A
five-lens investigation of "transitions feel jittery" (2026-08-20, 29
candidates, 3 survived adversarial verification) found ~2,300 px/min of cursor
travel the hand never commanded, in three mechanisms — all of them positional
debt discharged in a single 33 ms frame. None of them can affect a tool that
does not move the cursor. See [the jitter findings](#2026-08-20--transition-jitter-three-verified-mechanisms).

**Restore.** `leapinput --legacy`. It re-subscribes the cursor driver
(`engine.subscribe(direct.on_intent)` — the whole strip is that one line) and
restores the full command vocabulary. Nothing else differs.

**Reverse it if.** Pointing becomes necessary away from a desk (a wall
display, a workshop bench) where there is no mouse to fall back on.

---

## 2026-08-20 — the phone/WebRTC source moved to legacy

**What.** `--source phone` refuses to start without `--legacy`, and the menu
bar item explains instead of launching.

**Why.** *"too overburdening, unnecessary, and a lot of unnecessary background
scripting."* It stands up a TLS server, a signalling loop, a per-session token
and an aiortc receive path — permanent background machinery in service of a
tool that watches for four poses. The built-in webcam does the job with none
of it.

**Evidence.** The webcam became the daily driver on 2026-08-19 and the phone
has not been the working source since. The latency work that justified it
(~17 ms/frame of receiver patches) was real but only mattered for *pointing*,
which is now gone.

**Restore.** `scripts/leapctl on --legacy --source phone`. Untouched:
`phonecam.py`, `phonedepth.py`, the certificates, the whole latency
engineering.

**Reverse it if.** A faster camera becomes the point again — the 60 fps phone
path is still the fastest source this project has.

---

## 2026-08-20 — a detection-rate cap was tried, then REVERTED

**What.** Detection ran on a 20 Hz budget for about an hour. It is now off by
default; `--detect-hz N` opts back in.

**Why it was tried.** With only pose *holds* wired, per-frame position buys
nothing, and a 0.6 s dwell does not care about 33 ms. It measured well: ~30%
CPU → ~17%.

**Why it was reverted.** It made the two-hand **frame shot** flicker — the
one feature the strip exists to serve. The likely mechanism is MediaPipe's
frame-to-frame tracking: it seeds each detection from the previous frame's
region, so starving it degrades landmark quality, which shows up as an
unstable `extended` tuple, which is exactly what the L-pose test reads. The
saving was real and irrelevant: *"as many resources as necessary should be
allocated to that."*

**Also learned:** a first attempt at 15 Hz measured **9.2 fps**, because the
skip loop's fixed `sleep(0.004)` per skipped frame cost more rate than the
budget did. It now sleeps the remainder — worth knowing if the cap is ever
reached for again.

**Restore the cap.** `--detect-hz 20`. Full rate is 29.8 fps at ~29% CPU.

**Reverse this if.** CPU ever matters more than framing quality — on battery,
say. It would still be wrong for the frame shot.

---

## 2026-08-20 — `busy` stopped faking a tracking loss

**What.** A command hold now calls `GestureEngine.park()` (drop the clutch)
instead of being fed an empty Snapshot. `CommandEngine.busy` additionally
requires the pose to have matched within `BUSY_STALE_S` (0.1 s).

**Why.** An empty Snapshot is the *tracking-loss* path: it force-released the
pinch and grab latches, rebuilt the finger ladder from 5, and fired DISENGAGE.
That is correct when a hand genuinely vanishes and wrong when someone is
simply framing a rectangle.

**Evidence.** 256 s of recorded session: 21 clutch drops, **zero** caused by
hand loss, **17 on a `busy` frame**, 8 of which killed a latched button
mid-gesture. 21 busy episodes with a median duration of 0.104 s — the
population was dominated by PoseHold's 0.12 s flicker grace rather than by
anyone holding a pose. The dominant trigger was two-handed pane framing (321
of 386 busy frames carried the thumb+index L pose), i.e. the frame shot, which
the stripped tool kept.

**Not changed:** pause still feeds an empty Snapshot and still releases
everything. That dead-man property is deliberate.

---

## 2026-08-20 — a pinch can no longer drag

**What.** `Mapping.pinch_drag = False`. While a pinch holds the button the
cursor is pinned to one pixel. The fist is the drag (legacy).

**Why.** *"pinch click is still buggy … hold and drag is getting mixed up"*,
then *"i dont want drag mechanism with this"*.

**Evidence.** `_up()` pinned only the mouse-*up* back to the down pixel; the
cursor tracked the hand for the whole hold, so macOS had already been dragging
— text selected, icons lifted — before the pin-back ran. There was no drag
threshold at all.

**Restore.** `--pinch-drag`.

---

## 2026-08-20 — transition jitter: three verified mechanisms

Found by a five-lens swarm, each survivor re-derived independently by an
adversarial verifier told to refute it. **Unfixed**, and mostly moot while the
cursor is unwired — recorded here so they are not re-discovered from scratch.

| mechanism | uncommanded travel | frequency |
|---|---|---|
| `settle` is a lerp *alpha*, not a gain — every freeze accrues positional debt discharged in one 33 ms frame | 952 px/min | 34/min |
| clutch re-engage teleports in absolute/touch mode | 886 px/min | 5.3/min, median 310 px, max 1074 px |
| `_touch_offset` cleared in one breath after every release | 468 px/min | 14/min — one per click |

**Refuted, with prejudice:** the PRISM precision offset. It was *my* leading
hypothesis for a measured +9.8 px x-bias on the bench, and the verifier's
finding was that "the stated mechanism is arithmetically false; the claimed
numbers do not reproduce; and the proposed fix would CREATE the exact symptom
under investigation." Do not disable PRISM on the strength of that theory.

**Ruled out by the data, do not chase:** reach-box slide/re-anchor/revival
(zero of 233 large-jump events; box-change frames are *quieter* than baseline)
and hand re-acquisition after dropout (zero of 233, and zero of the 21 clutch
drops).

---

## 2026-08-20 — "off" must mean off

**What.** `leapctl off` now sweeps three process patterns instead of one:
the wrapper argv, any hand-run `bin/leapinput --…` session, and the helper
processes (`leapinput.guard`, `leapinput.overlay`).

**Why.** *"whenever I turn off leap … make sure everything is killed, so
there's not background processes that are overburdening our operating system."*

**Verified.** A full on/off cycle leaves exactly one process alive — the menu
bar switch itself, at 0.0% CPU, which has to survive in order to turn things
back on. Port 8788 is released; no camera light, no guard, no overlay.

---

## Earlier

Pre-2026-08-20 measured facts live in [docs/context/](context/) —
[interaction model](context/interaction.md),
[strengthening](context/strengthening-2026-08-18.md),
[hardening](context/hardening-2026-08-19.md),
[edge reach](context/edge-reach-research-2026-08-19.md),
[phantom clicks](context/phantom-clicks-2026-08-19.md). Those are still the
reference for anything under `--legacy`.
