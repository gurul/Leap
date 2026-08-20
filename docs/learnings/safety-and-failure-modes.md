# Safety and failure modes

A gesture bug here does not throw a stack trace — it takes the machine you
would use to fix it. This page is the part of the project least affected by the
strip: the release paths, the guard and the permission gating all still apply,
and the invariants are the ones any future version should keep.

---

## The four properties, and why each exists

**Dry-run is the default.** `--backend quartz` is opt-in every time. A
half-tuned Schmitt trigger wired to the real cursor will fight you for control
of the machine you need in order to fix it.
([testing.md:17-21](../context/testing.md))

**An out-of-process guard.** The parent holds one end of a pipe; a separate
guard process blocks on the other. Any parent exit — clean, crashed, or
`SIGKILL`, which no `finally:` and no `atexit` survives — closes the pipe, the
read returns EOF, and the guard posts button-up for left, right and centre.
It depends on the OS reclaiming a file descriptor, not on the parent
successfully running any code, and it runs in its own process group so a
Ctrl-C aimed at the parent cannot kill it first. **Verified against a real
SIGKILL.** (a2059a7, `guard.py:1-105`)

This is the only failure class an in-process handler cannot cover, and it is
the load-bearing safety property of the whole project.

**A deadline.** Every run auto-stops after 120 s (`--duration 0` disables),
because a runaway process that owns the cursor is genuinely hard to quit by
hand. Paired with an exit-time empty-snapshot flush, because quitting
mid-pinch used to leave the mouse stranded down. (47e3c14)

**Fail-safe engagement.** Losing tracking releases everything held and
disengages. *There is no state in which the machine keeps acting on a hand that
is no longer there.*

---

## Every failure path reaches the same release

Wired one by one in the 2026-08-19 hardening pass
([hardening-2026-08-19.md:13-29](../context/hardening-2026-08-19.md)):

| failure | what happens |
|---|---|
| hand loss past the 0.12 s grace at a full command ring | **cancels** instead of firing |
| frame-stream stall | released twice over: in-process after the 150 ms flicker budget, plus a 0.5 s CLI watchdog on `source.frames` that also covers the Leap |
| capture-thread death | a guarded `finally` clears state and dispatches one empty Snapshot, each subscriber individually guarded, with the exception still propagating |
| tracking loss / height disengage | the finger ladder resets, so a stale count cannot fire a phantom `GRAB_DOWN` when the hand reappears (empirically reproduced before the fix) |
| single empty Leap tracking event | bridged by the camera's 150 ms blip logic — no button release |
| pause | feeds an empty Snapshot and releases everything, **deliberately** |
| dictation left open | force-released after `MAX_DICTATION_S = 180 s`, and the forced release resyncs `CommandEngine` so the chime vocabulary cannot invert |

The capture thread is the **only** caller of `on_snapshot`, which is why the
stall watchdogs exist at all: a stalled stream never delivers the empty
Snapshot that would release held input. (`cli.py:82-107`,
`camera.py:961-1057`)

---

## The recurring shape: a shared release path invoked for a non-release reason

Three occurrences, and worth checking for a fourth every time a new caller
appears.

1. **The clutch deadlock.** Gating clicks on the clutch introduced it:
   `_release_all` calls `force_off` on the clutch, which clears its
   pending-dwell timer. Calling it every un-clutched frame meant the dwell
   could never accumulate and the clutch could never engage at all. Caught by
   the **replay corpus**, not by hand. Buttons and clutch now have separate
   release paths; only genuine hand loss touches the clutch. (63161f2)
2. **`busy` faking a tracking loss.** 21 clutch drops over 256 s of recorded
   session, **zero** from an actual hand loss, 17 on a `busy` frame, 8 of which
   killed a latched button mid-gesture. See
   [gesture-vocabulary.md](gesture-vocabulary.md#busy-must-not-fake-a-tracking-loss).
   (31297f3)
3. **The finger-ladder reset**, which had to be added to *both* the loss path
   and the height-disengage path — a stale debounced count of 0 read as FIST on
   the reappearing hand. (`gestures.py:458-481`)

---

## A silent gate is the worst failure mode in a system that owns your cursor

The clutch gates **all** pointer motion, so a posture that cannot reach it
presents as total failure with no output — indistinguishable from a crash.
Reproduced: a flat palm in the `xy` plane sits 90° off the palm-forward
reference, giving exactly **0 `point.move` events over 40 frames**.

Three responses shipped together, and the pattern is the durable part:

- `--no-clutch` as an escape hatch;
- a **watchdog** that after 4 s of a visible hand with no clutch prints the
  measured palm angle, the angle required, and the three concrete fixes with
  the numbers filled in;
- `leapinput.doctor`, so "not working" resolves to a number instead of a
  theory.

*"A silent gate is the worst failure mode in this design; it should never
again require a diagnosis session."* (fbf65c7, 230cca2)

The pattern was reapplied on 2026-08-20: the CLI now names the
camera-permission failure in words after 5 frameless seconds
([troubleshooting.md:30](../troubleshooting.md)).

---

## Failures that are silent by construction on macOS

Three of them, each of which cost a debugging session. Full mechanics in
[macos-platform.md](macos-platform.md).

| Missing grant | Symptom |
|---|---|
| **Accessibility** | `CGEventPost` returns no error and simply does nothing. The CLI gates on `AXIsProcessTrusted()` and refuses to start rather than run with a dead cursor. |
| **Camera** | OpenCV logs one line (`not authorized to capture video (status 0), requesting...`) and `cap.read()` fails forever. The session looks ON and tracks nothing. |
| **Screen Recording** | `screencapture` dies with "could not create image from rect", so the frame shot silently does nothing. Failure is now as audible as success — the Basso error chime plus a log line naming the fix. |

---

## Headless state must be audible, and "off" must mean off

A live session paused itself silently and read as broken, so **pause and resume
chime**. (e999f92)

`leapctl off` sweeps **three** process patterns instead of one: the wrapper
argv, any hand-run `bin/leapinput` session, and the helper processes
(`leapinput.guard`, `leapinput.overlay`). Verified: a full on/off cycle leaves
exactly one process alive — the menu bar switch itself, at 0.0% CPU, which has
to survive in order to turn things back on. Port 8788 released, no camera
light, no guard, no overlay. Driven by a stated requirement: *"make sure
everything is killed, so there's not background processes that are
overburdening our operating system."*
([decisions.md:214-226](../decisions.md))

**Open, unfixed: FH-5** — phone stream death is stdout-only while the menubar
still claims ON. **FH-4** — overlay helper death silently downgrades pane
framing to blind, forever.
([hardening-2026-08-19.md:81-84](../context/hardening-2026-08-19.md))

---

## Untrusted content: grab mode's rule

`--pane grab` files change requests for an agent to work. Two of its fields are
**data describing what to change, never instructions to follow**:

- `element` — markup and paths scraped from a web page by React Grab's Cmd+C
  DOM walk;
- `said` — whatever a speech recogniser heard in the room.

Both are bounded **on the way in**, not on the way out to a model:
`MAX_ELEMENT_CHARS = 8000`, `MAX_SAID_CHARS = 2000`, so a runaway page cannot
put a megabyte of markup into a record some agent later reads in full. Records
are written atomically (tmp + replace) so an agent polling `next` never reads a
half-written record. (`grab.py:22-49`)

The capture path cannot tell a description from an injection — that is the
whole reason the rule is stated at the boundary rather than assumed downstream.

---

## The one thing that is safe by construction now

The 2026-08-20 strip removed the entire class of "the machine took my cursor"
failures, because nothing subscribes the cursor driver. The gesture engine
still runs and still releases correctly, so restoring `--legacy` restores a
path that was already hardened — but it also restores the three unfixed jitter
mechanisms in
[screen-mapping.md](screen-mapping.md#the-unfixed-list).
