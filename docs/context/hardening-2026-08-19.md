# 2026-08-19 hardening pass — control discipline borrowed from PuzzleCam

> **Dated finding.** The cursor and click fixes are in the `--legacy` path as
> of 2026-08-20 ([../decisions.md](../decisions.md)); the fail-safe work under
> "Applied — fail-safe on loss and stall" is live. **The deferred list at the
> bottom is a live backlog** — MD-1, MD-3, MD-4 and SI-3 are cursor-path and
> dormant, but EX-2 and FH-1 still bite the shipped tool. Suite was 246 → 280
> at this pass; it is 337 now.

A multi-agent audit of the control layer against [mishu006/Puzzle](https://github.com/mishu006/Puzzle)
(PuzzleCam), a 1,225-line MediaPipe photobooth app whose gesture control is unusually
disciplined. Its screenshot-frame flow in particular — direct absolute mapping, live
pre-commit preview, hold-to-arm with a minimum-size gate, a 450 ms tracking-loss grace
window, and a commit position locked at arm time — was the benchmark for our cursor path.

Two assess→adversarial-verify swarms produced 27 findings; 16 fixes were applied
(each with a regression test), the rest are recorded below for sign-off. Suite grew
246 → 280 tests, all green. No gesture semantics or comfort-tuned thresholds changed.

## Applied — fail-safe on loss and stall

- **Hand loss at a full command ring now cancels instead of firing** (`commands.py`).
  `PoseHold.update` takes `present=`; loss past the 0.12 s grace resets without
  evaluating the release-fire condition, matching the docstring's promise.
- **Frame-stream stall releases held input** twice over: in-process after the 150 ms
  flicker budget (`camera.py` not-ok branch, inherited by the phone source) and a
  0.5 s CLI watchdog on `source.frames` that also covers the Leap source (`cli.py`).
- **Capture-thread death releases held input** (`camera.py`): `_run` is a guarded
  wrapper whose `finally` clears state and dispatches one empty Snapshot with each
  subscriber individually guarded; the exception still propagates.
- **Finger ladder resets on tracking loss and height disengage** (`gestures.py`):
  a stale count can no longer fire a phantom GRAB_DOWN when the hand reappears
  (empirically reproduced before the fix).
- **Leap source gained the camera's 150 ms blip bridge** (`capture.py`): single empty
  tracking events no longer release buttons; the hold expires from the original stamp
  so the dead-man behavior is unchanged.

## Applied — cursor and click quality

- **Reach box survives brief dropouts in place** (`camera.py` `_reach_gone`): a
  reappearance within 500 ms with the knuckle centroid inside the old box (+0.05
  margin) revives the dying box instead of rebuilding centered — a 150–500 ms tracker
  blip no longer teleports the cursor to ~screen center mid-aim. Far or late
  reappearances still get the documented come-to-the-hand recenter.
- **Click commit position locked for the whole button hold** (`driver.py`
  `_touch_offset`): the anchor warp at select.down was being undone by the next
  settle=1.0 absolute move, accruing into `_travel` and defeating the <12 px pin-back —
  exactly the clicks the anchor exists to save were landing as drags. The offset dies
  with the button; drags still track 1:1.
- **Grab commits joined the anchor lifecycle** (`driver.py`): fist-clicks get the same
  anchor warp as pinch-clicks, guarded on `not _button_down` so the silent
  pinch-into-fist handover can never teleport a live drag; grab.up clears the anchor;
  every `_down` consumes it (fixes stale-anchor warp after an interleaved fist-drag).
- **Free-hand holds no longer blank the cursor engine** (`commands.py` `busy` spans
  only pane/mission/toggle/dictate); the pause toggle is gated on the existing pinch
  shadow so it cannot arm mid-pinch and drop a drag.

## Applied — honest state and startup

- **Dictation watchdog resyncs CommandEngine** (`driver.py` `on_forced_release` →
  `cli.py` closure): the forced Option release now flips `_dictating` and plays the
  mic-off Pop, so the chime vocabulary can no longer invert for a full cycle.
- **Preview status names the real owner**: `COMMAND HOLD (<label> owns the input)`
  instead of blaming the open hand while `busy` parks the cursor (`cli.py`).
- **Phone server startup fails fast** (`phonecam.py`): the ready-wait timeout raises
  instead of printing a URL for an unbound server; the openssl cert call got a timeout.
- **viz engaged badge derives from `Config().engage_y`** instead of a hardcoded 90
  that disagreed with the engine's 115/100 Schmitt.

## Deferred — confirmed real, needs maintainer sign-off

- **MD-1** `camera.py` — touch-sheet drag consumes raw landmarks with no per-frame
  slew limit; edge-riding noise ratchets the box so screen-edge targets drift by tens
  of px. Fix (bounded per-frame step) interacts with fast-drag cadence; needs a live session.
- **MD-3** `camera.py` — dynamic box width latched from one raw `span_img` frame per
  engagement; a bad first frame skews DPI ~10–30 % until re-engagement. Fix (POSE_BLEND
  the first ~5 frames) touches the "pinned while tracked" guarantee.
- **MD-4** `camera.py`/`driver.py`/`gestures.py` — the acknowledged stored-box vs
  live-zoom drift (≤1.8×) on `pointer_beta` and `pinch_arm_max_speed`; the code's own
  NOTE names the fix (live zoom on `HandFrame`), spans three modules.
- **EX-2** `commands.py` — free-hand copy/paste/enter can fire while the cursor hand
  holds a button; suppressing needs a priority-rule decision.
- **SI-3** `driver.py`/`actions.py` — display geometry cached once at init; display
  changes mid-session clamp into stale rects. Mechanism choice (clutch-time refresh vs
  `CGDisplayRegisterReconfigurationCallback`) is a design call.
- **FH-1** `overlay.py` — headless sessions get no hold-progress ring (the abort
  affordance release-fire depends on); needs a rect-less overlay protocol extension.
- **FH-4** `overlay.py` — helper death silently downgrades pane framing to blind
  forever; a one-shot respawn changes a pinned test's contract.
- **FH-5** `phonecam.py`/`leapctl`/`menubar.py` — phone stream death is stdout-only
  while the menubar claims ON; wants a `nocam` status flag and a scoped chime.
