# Leap

**Your phone is a 60 fps hand-tracking input device for your Mac.** Point to move the cursor, pinch to click, make a fist to drag — through a camera, with nothing to install on the phone and no special hardware anywhere.

This project began as an experiment with a Leap Motion Controller — an infrared hand-tracking unit tracking at 111 fps — and this is its successor: the same measured gesture vocabulary rebuilt around cameras everyone already owns, to make touchless input accessible and genuinely usable for traditional interface work. The Leap hardware path still works and remains the precision benchmark; the center of gravity is now the visual pipeline — webcam, iPhone over WebRTC, and the low-latency engineering that makes a camera feel like an input device rather than a video call. More research is coming on exactly that front.

Touchless mice are a graveyard of demos that feel magical for ten seconds and unusable for ten minutes. Leap is an attempt to find out why, and to fix it with measurement instead of taste. Every threshold in here — the pinch distance, the clutch debounce, the gain curve, the finger count that lifts the cursor — was fitted from recorded hand data, and the numbers that look arbitrary are the ones that took the longest to earn.

- **The phone is the flagship source.** iPhone Safari → WebRTC → MediaPipe, measured at **57.2 fps delivered with a 16.7 ms median frame cadence** (exact 60 Hz) and ~9 ms/frame detection: the whole pipeline tracks at 60 fps-class rates.
- **Latency-engineered end to end.** A seven-stream research pass (WebRTC internals, Safari encoder behavior, real-time-video literature, the HFT playbook) drove receiver patches worth ~17 ms/frame plus tail-jitter fixes — all documented, all measured. See [the latency notes](docs/context/latency-research-2026-08-18.md).
- **Verified against a corpus, not a demo.** 3,639 recorded frames of real use replay through the pipeline in CI; each pose does exactly one thing and nothing else.
- **191 hardware-free tests in under four seconds.** All the fiddly temporal logic runs on frozen dataclasses — no device, no hands, no flakiness.
- **Designed to fail safe.** A separate guard process releases every mouse button if the main process dies — even to `SIGKILL`.

## How it works

```
┌─────────────┐                                  ┌──────────────┐
│ Leap Motion │──┐                            ┌──│ DirectDriver │── the hand IS the cursor
│  ~111 fps   │  │                            │  └──────────────┘
└─────────────┘  │  ┌──────────┐  ┌─────────┐ │
┌─────────────┐  ├─▶│ HandFrame│─▶│ gestures│─┤
│   webcam    │──┤  │ (plain   │  │  Schmitt│ │  ┌──────────────┐
│  ~30 fps    │  │  │  data)   │  │ triggers│ └──│ShortcutDriver│── pane / Mission Control
└─────────────┘  │  └──────────┘  └────┬────┘    └──────┬───────┘
┌─────────────┐  │       │             │ Intent         ▲ Command
│phone Safari │──┘       │             ▼                │
│WebRTC ~60fps│          │  ┌─────────────────┐  ┌──────┴───────┐
└─────────────┘          └─▶│ commands        │  │              │
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

Each layer only knows about the one below it. `capture.py` is the only module that imports `leap`; `camera.py` is the only one that imports MediaPipe; `phonecam.py` is the only one that knows WebRTC exists. Everything above them consumes a frozen dataclass — which is why the temporal logic is testable without hardware.

## Quick start

### Your phone as the camera — no app required

`--source phone` turns the phone's browser into the capture device: Leap serves one HTTPS page on your LAN, the phone's Safari streams its camera back over WebRTC (hardware H.264, UDP, 60 fps where the phone allows it), and frames feed the MediaPipe pipeline directly. No app install, no virtual camera driver, no paired accounts — and no third-party webcam software to pay for.

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[dev,camera,phone]'
curl -L --create-dirs -o vendor/hand_landmarker.task \
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"

.venv/bin/leapinput --source phone --backend dry-run   # prints the URL to open
```

Open the printed URL on the phone, accept the self-signed-certificate warning once, tap **Start (rear)** or **Start (front)**. The random URL token is persisted (`~/.leapinput/phonecam-token`) so the phone bookmark keeps working; media never leaves your network (no STUN/TURN).

Measured on 2026-08-18 (iPhone → M5 MacBook Pro, LAN Wi-Fi): **57.2 fps delivered** (1,137 frames / 19.9 s), median frame cadence 16.7 ms — exact 60 Hz — 98.5% of frames unique motion. With detection at ~9 ms/frame on VGA, the whole pipeline tracks at 60 fps-class rates.

### Or any webcam

`--source camera` runs the identical vocabulary through the built-in (or any attached) camera — the same install as above minus the `phone` extra:

```bash
.venv/bin/leapinput --source camera                     # dry-run first
.venv/bin/leapinput --source camera --backend quartz    # drives the real cursor
```

Face the camera; the view is mirrored, so moving your hand right moves the cursor right. Add `--preview` for a live window with the hand skeleton, per-finger state and a gesture readout.

Cameras are picked **by name**, not by index — virtual cameras (Camo, OBS) shuffle AVFoundation's device order, and their feeds are black unless their app is streaming. `--list-cameras` shows what's attached; `--camera-name iphone` targets Continuity Camera (or any camera by substring), `--camera N` forces a raw index.

### Learn it, then fit it to your hand

First time? Start in the practice room (works with any camera source):

```bash
.venv/bin/leapinput --source camera --tutorial
```

A guided walkthrough over the live preview: point, click, drag, park, then the pose commands — each step advancing only when the real pipeline detects the real gesture. It forces dry-run, so nothing touches your actual cursor while you learn.

Then calibrate, because the thresholds ship as guesses and your hand is the ground truth:

```bash
.venv/bin/python -m leapinput.calibrate capture
```

A few prompted rounds of open/point/pinch/fist fit your personal thresholds into `camera_tuning.json` (gitignored), which the camera sources load automatically.

### Always-on

When it's good enough to live with, run it as a persistent session:

```bash
scripts/leapctl on                   # detached, no deadline, survives the terminal
scripts/leapctl on --source phone    # same, tracking through your phone's camera
scripts/leapctl status
scripts/leapctl off       # clean stop: buttons released
scripts/leapctl log       # tail the session log
```

The ILY pose pauses and resumes gesture control in-band — no terminal needed — and `leapctl pause` does the same from a shell (a chime confirms which way it went). The session mirrors the pause state to `~/.leapinput/paused`, so `leapctl status` reports `running (paused, …)` too. The out-of-process guard still covers every crash path, and hand-out-of-view still releases everything instantly.

For a one-click switch, put it in the menu bar (✋ = on, 🤟 = paused — the icon shows the pose that resumes it, ✊ = off). **Turn on** starts the phone source, so the WebRTC server comes up automatically — open the phone's bookmark and tap Start; until then the session just idles waiting for frames:

```bash
VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[menubar]'
nohup .venv/bin/leapinput-menubar >/dev/null 2>&1 &
```

### The original hardware

The Leap Motion Controller path this project grew from still works, and still sets the precision bar (111 fps, real depth):

```bash
./scripts/setup.sh                    # builds .venv, vendors the bindings, verifies
.venv/bin/leapinput                   # dry-run: logs what it would do
.venv/bin/leapinput --backend quartz  # drives the real cursor, 120s deadline
```

Hold your hand flat over the device, palm down. `scripts/verify-env.sh` re-asserts the whole baseline (Hyperion version, device, frame rate, Accessibility permission) and exits non-zero on drift — run it first whenever something stops working.

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

### Pose-hold commands (camera & phone paths)

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

ILY is the one pose where which hand it's on changes the command entirely (free hand = Enter, cursor hand = pause), so it gets special routing: an ILY-shaped hand raised alone is always routed by the handedness label — the "a lone hand is probably the cursor hand" adoption rule (built for flappy fists and pinches) stands down. Left-hand ILY is Enter, even raised exactly where the cursor hand just was; it can no longer be mistaken for the pause toggle.

### Verified, pose by pose

Replaying 3,639 recorded frames of real use — each pose does exactly one thing and nothing else:

| pose | click | grab | lift | cursor moves |
|---|---|---|---|---|
| pinch (443 frames) | 1 | 0 | 0 | 437 |
| fist (444) | 0 | 1 | 0 | 438 |
| open hand (442) | 0 | 0 | 1 | 28 |
| two-finger (554) | 0 | 0 | 0 | 554 |
| roaming (665) | 0 | 0 | 0 | 0 |

## The latency work

A camera only feels like an input device if the path from photons to cursor is short and, above all, *consistent*. The median here is physics — 16.7 ms is a 60 Hz camera's own cadence — so the engineering is in the tail, and the receive path was audited down to aiortc's source (seven parallel research streams: WebRTC internals, Safari's encoder, the real-time-video literature, alternative transports, VR latency compensation, and the HFT tail-latency playbook):

- **aiortc's jitter buffer held every frame hostage for one extra frame** — it only released frame N when frame N+1's first packet arrived, never reading the RTP marker bit. Patched: ~16.7 ms back on every frame.
- **Head-of-line stalls bounded.** Jitter capacity 128 → 64: one unrecovered packet loss now costs a short stall + a keyframe request instead of a ~250–500 ms freeze. Freshness beats completeness for a cursor.
- **The encoder is never software.** H.264 is pinned in negotiation (hardware VideoToolbox on iPhone, no B-frames by spec), the decoder runs with FFmpeg's `low_delay` flag, and `contentHint='motion'` + `degradationPreference` make Safari sacrifice resolution before frame rate — never the reverse.
- **No congestion governor on a one-hop LAN.** aiortc's receive-side bandwidth estimate (REMB) initializes low and becomes a hard send ceiling — it caused a measured mid-session downscale. Stripped from negotiation; a 4 Mbps cap keeps frames small so a lost packet stalls less stream.
- **Conflation at the ingress, freshest-frame-wins at the consumer.** Frames are never queued anywhere: the receiver drains to the newest before paying conversion cost, and the pipeline always reads the latest frame, dropping stale ones — the same discipline (and the same p99-first measurement doctrine) quant systems use.
- **Runtime discipline:** tracking threads pinned to performance cores via macOS QoS, cyclic GC frozen after startup so it can't inject 10–50 ms pauses mid-gesture.

What's next, in order: killing AWDL (AirDrop's channel-hopping is the classic macOS Wi-Fi jitter source), USB-C tethering (deletes the radio from the path entirely), and ~35 ms of pose prediction — the VR trick that puts perceived latency below the ~50 ms threshold where an indirect cursor becomes indistinguishable from instant. Full findings, sources, and the ranked roadmap: [`docs/context/latency-research-2026-08-18.md`](docs/context/latency-research-2026-08-18.md).

## Choosing a source

| | phone (WebRTC) | webcam | Leap Motion |
|---|---|---|---|
| frame rate | 57.2 fps at 640×480 (1,137 frames / 19.9s) | 29.4 fps at 640×480 (449 frames / 15.3s) | 111 fps (measured, 667 frames / 6.0s) |
| latency | ~40–80 ms glass-to-glass (encode + LAN + decode) | one extra camera exposure | sub-frame |
| depth | none — image plane only (`--plane xy`) | none — image plane only (`--plane xy`) | real Z, so the desk plane works (`--plane xz`) |
| pinch / grab | synthesised from world-landmark geometry | synthesised from world-landmark geometry | reported by the SDK |
| needs | `[phone]` extra + any phone with Safari/Chrome | nothing | the hardware + Hyperion + the SDK pins below |

All three paths verified end-to-end from live frames: engage → click → drag → release (Leap and webcam 2026-08-12, phone 2026-08-18).

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
- **Explicit permission gating.** Accessibility failures are *silent* on macOS — `CGEventPost` returns no error and simply does nothing — so it gates on `AXIsProcessTrusted()`, triggers the system grant prompt, and refuses to start rather than run with a dead cursor.

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
| `src/leapinput/phonecam.py` | The phone's browser as the camera: HTTPS capture page + WebRTC/aiortc receiver (with the low-latency patches) feeding the same loop |
| `src/leapinput/camera.py` | Webcam frames → `HandFrame`. The only module importing MediaPipe; picks cameras by name, not index |
| `src/leapinput/capture.py` | Leap frames → the same `HandFrame`. The only module importing `leap` |
| `src/leapinput/gestures.py` | `HandFrame` → `Intent`. Schmitt triggers, engagement state, the whole fiddly part |
| `src/leapinput/commands.py` | `HandFrame` → `Command`. Pose-holds: pane + Mission Control fire on release, pause fires on ring-fill |
| `src/leapinput/driver.py` | `Intent`/`Command` → backend calls. Gain curve, click stabilisation, pane placement |
| `src/leapinput/actions.py` | Backend seam: `QuartzBackend` (real) and `DryRunBackend` (prints) |
| `src/leapinput/guard.py` | The separate process that releases the button if this one dies |
| `src/leapinput/oneeuro.py` | Vendored 1€ filter — adaptive smoothing, heavy when slow, light when fast |
| `src/leapinput/{doctor,viz,record,calibrate}.py` | Diagnosis, live view, corpus capture, threshold fitting |
| `scripts/` | `setup.sh` (reproducible env) · `verify-env.sh` (drift check) · `leapctl` (always-on on/off switch) |
| `docs/context/` | Durable measured facts: [latency research](docs/context/latency-research-2026-08-18.md) · [environment](docs/context/environment.md) · [interaction model](docs/context/interaction.md) · [testing](docs/context/testing.md) · [2026-08-18 strengthening pass](docs/context/strengthening-2026-08-18.md) |
| `docs/` | [Build plan](docs/plan.md) · [OSS survey dossier](docs/oss-dossier.md) |

## Built with

Python 3.12, MediaPipe Tasks + OpenCV for hand landmarks, aiortc + aiohttp for the phone's WebRTC path, PyObjC/Quartz for `CGEventPost`, CFFI against `libLeapC.6` for the original hardware, pytest for the 191 hardware-free tests. The 1€ filter is Casiez, Roussel & Vogel (CHI 2012), vendored rather than depended on. The 2026-08-18 passes borrowed robustness patterns from [mediapipe-touchdesigner](https://github.com/torinmb/mediapipe-touchdesigner), command shapes from shipping mid-air vocabularies, and tail-latency doctrine from the quant world — details in [the strengthening notes](docs/context/strengthening-2026-08-18.md) and [the latency notes](docs/context/latency-research-2026-08-18.md).
