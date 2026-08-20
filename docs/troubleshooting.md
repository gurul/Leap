# When it doesn't work

> **Mixed status as of 2026-08-20.** The diagnosis tools, the camera-permission
> section, the telemetry dashboard and the safety model are all live. The
> **CLICK bench** and the projection table below measure cursor accuracy under
> a projection nothing consumes by default — they need `--legacy`. The FRAME
> test still applies. See [decisions.md](decisions.md) ·
> [learnings/restoring.md](learnings/restoring.md).

"It doesn't work" has at least four distinct causes — no tracking, no
engagement, no clutch, no motion — and they need different fixes:

```bash
python -m leapinput.doctor      # 10s live sample, pass rate per pipeline stage
python -m leapinput.viz         # terminal view of what the sensor actually sees
python -m leapinput.record capture -o session.jsonl   # record a corpus
python -m leapinput.record analyze session.jsonl      # refit thresholds from it
```

The CLI also nudges: if a hand is tracked but the cursor is parked, it prints
which gate is holding it and the exact flag that would open it.

## The menu bar says ON and nothing tracks (camera permission)

macOS attributes a Camera grant to the **app that started the process tree**,
not to the process that opens the device. A session started from the menu bar
is a grandchild of `~/Applications/Leap Menubar.app`, so that bundle is what
System Settings lists — and the bundle's `Info.plist` must declare
`NSCameraUsageDescription`, or macOS refuses the request outright instead of
prompting. Nothing raises: the log gets one line from OpenCV,

```
OpenCV: not authorized to capture video (status 0), requesting...
```

and then `cap.read()` fails forever. The session stays up, the menu bar shows
✋, and no frame ever arrives. (Diagnosed 2026-08-20, after the wrapper was
built without the key.) The CLI now names this after 5 frameless seconds
instead of sitting there silently.

Fix, and the reason the wrapper is a build artifact rather than something you
assemble by hand:

```bash
scripts/install-menubar-app.sh --restart   # rebuild the bundle, relaunch it
```

Then press **Turn on** and approve the prompt. Editing the bundle changes its
ad-hoc signature, which invalidates existing grants, so expect to approve
Camera (and Accessibility) once after any rebuild. `tccutil reset Camera
world.era.leapinput.menubar` forces the prompt back if it doesn't appear.

A CLI run is a different grantee: there the responsible app is your terminal,
which is why `leapctl on` from a terminal that already has Camera can work on
the same machine where the menu bar switch does nothing.

## Live telemetry

Every session serves a diagnostics dashboard on `http://127.0.0.1:8788`:

- live pinch-distance trace with the real Schmitt thresholds drawn in, and
  yellow bands when the engine believes you're pinching;
- cursor x/y edge-reach traces (a flatline short of the border is the
  unreachable band);
- an event feed, and a **PHANTOM** button (or the `P` key) that tags the most
  recent click as unintended.

Every `select.down`/`grab.down` is recorded to
`~/.leapinput/telemetry/clicks-<date>.jsonl` with the 2 seconds of signals
before it and 0.5s after — so a misbehaving click is diagnosed from evidence,
not memory. Click records carry the cursor pixel they fired at, and every
committed command (the pane rect above all) rides the same live stream.
`--no-telemetry` disables the layer; `--telemetry-port N` moves it.

## "It used to be accurate" — the bench

Feel is not evidence, and the mapping changed three times in two days. Every
session serves a scored bench at `http://127.0.0.1:8788/bench`:

- **CLICK test** — a fixed ladder of ten targets down to 7px (the macOS
  traffic-light button). Every landing is plotted. The card to watch is
  **systematic bias**: a repeatable offset in one direction is the projection,
  not your aim.
- **FRAME test** — it draws a rectangle, you frame it with both hands, and the
  region the session actually captured is drawn back in green. Scored by
  overlap (IoU), centre offset (a **shifted** map) and size ratio (a **wrong
  zoom**) — the two failure modes are distinguishable, which "it feels off"
  is not.

The header prints the mapping that produced the score (zoom, inset, box mode,
PRISM), because a number is only comparable to another number taken under a
known projection. Bisect with one flag at a time:

```bash
scripts/leapctl on --reach-center fixed   # one projection, not one per engagement
scripts/leapctl on --reach-inset 0        # box maps exactly to the screen
scripts/leapctl on --no-precision         # drop the PRISM offset
scripts/leapctl on --no-reach             # whole frame, the pre-2026-08-18 map
```

### What the projection actually does now

Measured across 65 recorded clicks in `~/.leapinput/telemetry/`, with the
default palm-anchored box:

| | range across clicks |
|---|---|
| box origin x | 0.202 → 0.749 of the frame |
| box origin y | 0.275 → 0.669 |
| box width | 0.211 → 0.693 (zoom **1.4× → 4.7×**) |

That is not one projection with noise, it is a **different projection per
engagement** — different origin and a 3.3× spread in scale. Absolute
("touch") mapping promises that a point in the air is a point on the screen;
that promise holds only within a single engagement, which is why aim stopped
being learnable. `--reach-center fixed` trades the come-to-your-hand
convenience for a projection you can learn.

The comparison that motivated the shared-frame fix:
[mediapipe-touchdesigner](https://github.com/torinmb/mediapipe-touchdesigner)
hands MediaPipe's landmarks to the host **unchanged** — normalized whole-image
0–1 coordinates, one space shared by both hands, no per-hand ROI, recentring
or gain. Interactions built on it inherit a single static projection. Ours is
per-hand and moving, which is exactly the difference in how the framing
gesture feels.

## Safety, because this owns your mouse

A gesture bug here does not throw a stack trace — it takes the machine you
would use to fix it.

- **Dry-run is the default.** `--backend quartz` is opt-in, every time. A
  half-tuned Schmitt trigger wired to the real cursor will fight you for
  control.
- **An out-of-process guard.** The parent holds one end of a pipe; the guard
  blocks on the other. Any parent exit — clean, crashed, or `SIGKILL`, which
  no `finally:` survives — closes the pipe and the guard posts button-up.
  This is the only failure class an in-process handler cannot cover.
- **A deadline.** Every run auto-stops after 120s (`--duration 0` to
  disable). A runaway that owns the cursor is genuinely hard to quit by hand.
- **Fail-safe engagement.** Losing tracking releases everything held and
  disengages. There is no state in which the machine keeps acting on a hand
  that is no longer there. A frame-stream stall, a crashed capture thread,
  and a mid-session camera disconnect all reach the same release path.
- **Explicit permission gating.** Accessibility failures are *silent* on
  macOS — `CGEventPost` returns no error and simply does nothing — so it
  gates on `AXIsProcessTrusted()`, triggers the system grant prompt, and
  refuses to start rather than run with a dead cursor.
