# Leap

**Hand tracking → real macOS cursor input.** Point to move, pinch to click, make a fist to drag — with a Leap Motion Controller, or with nothing but a webcam.

Touchless mice are a graveyard of demos that feel magical for ten seconds and unusable for ten minutes. Leap is an attempt to find out why, and to fix it with measurement instead of taste. Every threshold in here — the pinch distance, the clutch debounce, the gain curve, the finger count that lifts the cursor — was fitted from recorded hand data on real hardware, and the numbers that look arbitrary are the ones that took the longest to earn.

- **Two sensors, one pipeline.** A $80 Leap Motion at ~111 fps or a plain webcam at ~30 fps, feeding the identical gesture vocabulary.
- **Verified against a corpus, not a demo.** 3,639 recorded frames of real use replay through the pipeline in CI; each pose does exactly one thing and nothing else.
- **149 hardware-free tests in 1.5s.** All the fiddly temporal logic runs on frozen dataclasses — no device, no hands, no flakiness.
- **Designed to fail safe.** A separate guard process releases every mouse button if the main process dies — even to `SIGKILL`.

## How it works

```
┌─────────────┐                                  ┌──────────────┐
│ Leap Motion │──┐                            ┌──│ DirectDriver │── the hand IS the cursor
│  ~111 fps   │  │  ┌──────────┐  ┌─────────┐ │  └──────────────┘
└─────────────┘  ├─▶│ HandFrame│─▶│ gestures│─┤
┌─────────────┐  │  │ (plain   │  │  Schmitt│ │  ┌──────────────┐
│   webcam    │──┘  │  data)   │  │ triggers│ └──│ShortcutDriver│── pane / Mission Control
│  ~30 fps    │     └──────────┘  └────┬────┘    └──────┬───────┘
└─────────────┘          │             │ Intent         ▲ Command
                         │             ▼                │
                         │  ┌─────────────────┐  ┌──────┴───────┐
                         └─▶│ commands        │  │              │
                            │ pose-holds ─────┼──┘              │
                            └─────────────────┘                 │
                                 ┌───────────────────────────┐  │
                                 │ Backend: dry-run │ Quartz │◀─┴─▶ CGEventPost
                                 └───────────────────────────┘
                                        ▲
                    ┌───────────────────┴────────────────────┐
                    │ GUARD (separate process, pipe-EOF)     │
                    │ releases every button if this one dies │
                    └────────────────────────────────────────┘
```

Each layer only knows about the one below it. `capture.py` is the only module that imports `leap`; `camera.py` is the only one that imports MediaPipe. Everything above them consumes a frozen dataclass — which is why the temporal logic is testable without hardware.

## The vocabulary

### Cursor control

| Pose | Action |
|---|---|
| point (1–3 fingers) | cursor moves |
| pinch | click / drag (two quick pinches = real double-click) |
| fist | drag (`--source leap`; off by default on camera¹, `--drag` re-enables) |
| open hand (4–5 fingers) | **LIFT** — cursor parked, reposition freely |
| hand out of view | disengaged, everything released |

¹ On camera, pinch misreads made the fist flaky — and pinch already holds the button, so pinch-and-move drags.

### Pose-hold commands (camera path)

Hold the pose until the ring in the preview fills, release to fire — the shape every shipping mid-air UI converged on, and nothing here can carry the hand out of frame the way cut-style swipes did:

| Pose | Hold | Action |
|---|---|---|
| frame a rectangle with both hands (thumb+index L-shapes) | ~0.8s | **FRAME SHOT** — screenshot of the framed region to the clipboard (`--pane window/tab`) |
| OK sign (pinch, 3 fingers up) | ~0.6s | Mission Control |
| ILY sign (thumb+index+pinky) | ~1.5s | pause / resume all gesture control (fires on ring-fill, with a chime) |
| thumbs-up | ~0.6s | **DICTATE** toggle — mic ON (Tink), thumbs-up again = OFF (Pop). Holds the Option key in between; rebind your dictation app (Willow Voice etc.) to a bare Option hold. Your hand is free while dictating. ILY pause also closes the mic; a 3-minute watchdog is the backstop |

While you hold the frame pose, the framed region is highlighted on the actual screen, Cmd+Shift+4-style — amber while the dwell fills, green when releasing will fire. The highlight window is excluded from screen capture, so it never appears in its own shot (`--no-screen-overlay` disables it).

### The free hand

The hand the cursor doesn't follow is a second command palette — raise it alone or alongside; a hand appearing away from the cursor hand's last position is trusted to be the free hand:

| Pose (free hand, ~0.6s) | Action |
|---|---|
| pinch and hold | Cmd+C ("grab it") |
| V sign (thumb ignored) | Cmd+V (the literal letter) |
| ILY sign | Enter (submit what you dictated) |

The full dictation loop: thumbs-up (Tink) and speak, thumbs-up again (Pop — Willow pastes), free-hand ILY to submit.

### Verified, pose by pose

Replaying 3,639 recorded frames of real use — each pose does exactly one thing and nothing else:

| pose | click | grab | lift | cursor moves |
|---|---|---|---|---|
| pinch (443 frames) | 1 | 0 | 0 | 437 |
| fist (444) | 0 | 1 | 0 | 438 |
| open hand (442) | 0 | 0 | 1 | 28 |
| two-finger (554) | 0 | 0 | 0 | 554 |
| roaming (665) | 0 | 0 | 0 | 0 |

## Quick start

### With just a webcam

No Leap hardware, no SDK, no Hyperion service — `--source camera` runs the identical vocabulary through MediaPipe HandLandmarker:

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[dev,camera]'
curl -L --create-dirs -o vendor/hand_landmarker.task \
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"

.venv/bin/leapinput --source camera                     # dry-run first
.venv/bin/leapinput --source camera --backend quartz    # drives the real cursor
```

Face the camera; the view is mirrored, so moving your hand right moves the cursor right. Add `--preview` for a live window with the hand skeleton, per-finger state and a gesture readout.

First time? Start in the practice room:

```bash
.venv/bin/leapinput --source camera --tutorial
```

A guided walkthrough over the live preview: point, click, drag, park, then the pose commands — each step advancing only when the real pipeline detects the real gesture. It forces dry-run, so nothing touches your actual cursor while you learn.

Then calibrate, because the camera thresholds ship as guesses and your hand is the ground truth:

```bash
.venv/bin/python -m leapinput.calibrate capture
```

A few prompted rounds of open/point/pinch/fist fit your personal thresholds into `camera_tuning.json` (gitignored), which the camera source loads automatically.

### With a Leap Motion Controller

```bash
./scripts/setup.sh                    # builds .venv, vendors the bindings, verifies
.venv/bin/leapinput                   # dry-run: logs what it would do
.venv/bin/leapinput --backend quartz  # drives the real cursor, 120s deadline
```

Hold your hand flat over the device, palm down. `scripts/verify-env.sh` re-asserts the whole baseline (Hyperion version, device, frame rate, Accessibility permission) and exits non-zero on drift — run it first whenever something stops working.

### Always-on

When it's good enough to live with, run it as a persistent session:

```bash
scripts/leapctl on        # detached, no deadline, survives the terminal
scripts/leapctl status
scripts/leapctl off       # clean stop: buttons released
scripts/leapctl log       # tail the session log
```

The ILY pose pauses and resumes gesture control in-band — no terminal needed — and `leapctl pause` does the same from a shell (a chime confirms which way it went). The session mirrors the pause state to `~/.leapinput/paused`, so `leapctl status` reports `running (paused, …)` too. The out-of-process guard still covers every crash path, and hand-out-of-view still releases everything instantly.

For a one-click switch, put it in the menu bar (✋ = on, 🤟 = paused — the icon shows the pose that resumes it, ✊ = off):

```bash
VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[menubar]'
nohup .venv/bin/leapinput-menubar >/dev/null 2>&1 &
```

## What the webcam costs you

| | Leap Motion | webcam |
|---|---|---|
| frame rate | 111 fps (measured, 667 frames / 6.0s) | 29.4 fps at 640×480 (449 frames / 15.3s) |
| latency | sub-frame | one extra camera exposure |
| depth | real Z, so the desk plane works (`--plane xz`) | none — image plane only (`--plane xy`) |
| pinch / grab | reported by the SDK | synthesised from world-landmark geometry |

Both paths were verified end-to-end on 2026-08-12: engage → click → drag → release, from live frames.

## The four numbers that took the longest

**Lift is 4 fingers, not 2.** A deliberate pinch reads as *three* extended fingers on this hardware — 100% of 443 corpus frames. Lifting at 2 parks the cursor at the precise instant of every click. This is the single least obvious number in the system.

**Gain turned out to be the tracking fix.** The control-display curve runs 2.12 px/mm at 10 mm/s up to 23.32 px/mm at 500 mm/s, and `--gain` scales both ends together so the ~11× slow-to-fast ratio survives. Raising it took frame rate from 36 → 116 fps and hand visibility from ~32% → ~100%, with no tracking parameter touched: higher gain means less hand travel, which keeps the hand in the reliable centre of the sensor's cone instead of out at the edges where LMC1 palm error goes from ~8mm to RMS >20mm. At 23 px/mm, 20mm of noise is a 460px cursor jump. Gain past 40° off-axis therefore fades to zero by 62°.

**Hysteresis takes two forms.** Continuous signals (pinch distance, palm angle, grab strength) use Schmitt triggers — two thresholds with a band between them. Finger count is an *integer*, so there is no band to sit inside and the guard has to be time. The debounce is deliberately asymmetric: 0.05s to engage, 0.25s to lift. A symmetric 0.08s window produced ~28 clutch cycles in one 60-second session.

**A fist cannot latch while a pinch is held.** They are one continuum — closing a pinch passes through both, and both drive the same physical button. Naive routing posts down/down/up/up and macOS loses track of whether a drag is in progress. Whichever latched first owns the button, and the driver owns button state idempotently on top of that.

Full derivations, including the dead ends, are in [`docs/context/interaction.md`](docs/context/interaction.md).

## Safety, because this owns your mouse

A gesture bug here does not throw a stack trace — it takes the machine you would use to fix it.

- **Dry-run is the default.** `--backend quartz` is opt-in, every time. A half-tuned Schmitt trigger wired to the real cursor will fight you for control.
- **An out-of-process guard.** The parent holds one end of a pipe; the guard blocks on the other. Any parent exit — clean, crashed, or `SIGKILL`, which no `finally:` survives — closes the pipe and the guard posts button-up. This is the only failure class an in-process handler cannot cover.
- **A deadline.** Every run auto-stops after 120s (`--duration 0` to disable). A runaway that owns the cursor is genuinely hard to quit by hand.
- **Fail-safe engagement.** Losing tracking releases everything held and disengages. There is no state in which the machine keeps acting on a hand that is no longer there. `test_tracking_loss_releases_a_held_button` and `test_select_up_precedes_disengage` are the two tests that matter most.
- **Explicit permission gating.** Accessibility failures are *silent* on macOS — `CGEventPost` returns no error and simply does nothing — so it gates on `AXIsProcessTrusted()` and warns.

## When it doesn't work

"It doesn't work" has at least four distinct causes — no tracking, no engagement, no clutch, no motion — and they need different fixes:

```bash
python -m leapinput.doctor      # 10s live sample, pass rate per pipeline stage
python -m leapinput.viz         # terminal view of what the sensor actually sees
python -m leapinput.record capture -o session.jsonl   # record a corpus
python -m leapinput.record analyze session.jsonl      # refit thresholds from it
```

The CLI also nudges: if a hand is tracked but the cursor is parked, it prints which gate is holding it and the exact flag that would open it.

## Why the setup is this specific

Three non-obvious pins for the Leap path, each of which will waste an afternoon:

1. **Hyperion 6.2 or newer.** 6.0 and 6.1 dropped support for the 2013 v1 controller entirely. 6.2 restored it.
2. **CPython 3.12 exactly.** The SDK's bundled CFFI extension is `_leapc_cffi.cpython-312-darwin.so`. No other Python imports it without rebuilding from source.
3. **The [`DDlabAU/LeapMotion-Python-Hyperion`](https://github.com/DDlabAU/LeapMotion-Python-Hyperion) fork**, not `ultraleap/leapc-python-bindings`. The official repo is Gemini-era and links `libLeapC.5`; Hyperion ships `libLeapC.6`.

And one for the camera path: **mediapipe 1.x has no bundled model** and labels handedness for the *un-mirrored* image, so a right hand reads `"Left"` on a selfie feed — 186/186 frames. `camera.py` swaps the label; don't "fix" that without re-measuring.

Everything measured, plus the dead ends not worth re-exploring, is in [`docs/context/environment.md`](docs/context/environment.md).

## Layout

| Path | What |
|---|---|
| `src/leapinput/capture.py` | Leap frames → `HandFrame`. The only module importing `leap` |
| `src/leapinput/camera.py` | Webcam frames → the same `HandFrame`. The only module importing MediaPipe |
| `src/leapinput/gestures.py` | `HandFrame` → `Intent`. Schmitt triggers, engagement state, the whole fiddly part |
| `src/leapinput/commands.py` | `HandFrame` → `Command`. Pose-holds: pane + Mission Control fire on release, pause fires on ring-fill |
| `src/leapinput/driver.py` | `Intent`/`Command` → backend calls. Gain curve, click stabilisation, pane placement |
| `src/leapinput/actions.py` | Backend seam: `QuartzBackend` (real) and `DryRunBackend` (prints) |
| `src/leapinput/guard.py` | The separate process that releases the button if this one dies |
| `src/leapinput/oneeuro.py` | Vendored 1€ filter — adaptive smoothing, heavy when slow, light when fast |
| `src/leapinput/{doctor,viz,record,calibrate}.py` | Diagnosis, live view, corpus capture, threshold fitting |
| `scripts/` | `setup.sh` (reproducible env) · `verify-env.sh` (drift check) · `leapctl` (always-on on/off switch) |
| `docs/context/` | Durable measured facts: [environment](docs/context/environment.md) · [interaction model](docs/context/interaction.md) · [testing](docs/context/testing.md) · [2026-08-18 strengthening pass](docs/context/strengthening-2026-08-18.md) |
| `docs/` | [Build plan](docs/plan.md) · [OSS survey dossier](docs/oss-dossier.md) |

## Built with

Python 3.12, CFFI against `libLeapC.6`, PyObjC/Quartz for `CGEventPost`, MediaPipe Tasks + OpenCV for the camera path, pytest for the 149 hardware-free tests. The 1€ filter is Casiez, Roussel & Vogel (CHI 2012), vendored rather than depended on. The 2026-08-18 pass borrowed robustness patterns from [mediapipe-touchdesigner](https://github.com/torinmb/mediapipe-touchdesigner) and command shapes from shipping mid-air vocabularies — details in [the strengthening notes](docs/context/strengthening-2026-08-18.md).
