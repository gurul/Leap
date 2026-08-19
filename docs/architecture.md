# Architecture

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

Each layer only knows about the one below it. `capture.py` is the only module
that imports `leap`; `camera.py` is the only one that imports MediaPipe;
`phonecam.py` is the only one that knows WebRTC exists. Everything above them
consumes a frozen dataclass — which is why the temporal logic is testable
without hardware.

## Layout

| Path | What |
|---|---|
| `src/leapinput/camera.py` | Webcam frames → `HandFrame`. The only module importing MediaPipe; picks cameras by name, not index |
| `src/leapinput/phonecam.py` | The phone's browser as the camera: HTTPS capture page + WebRTC/aiortc receiver (with the low-latency patches) feeding the same loop |
| `src/leapinput/capture.py` | Leap frames → the same `HandFrame`. The only module importing `leap` |
| `src/leapinput/gestures.py` | `HandFrame` → `Intent`. Schmitt triggers, engagement state, the whole fiddly part |
| `src/leapinput/commands.py` | `HandFrame` → `Command`. Pose-holds: pane + Mission Control fire on release, pause fires on ring-fill |
| `src/leapinput/driver.py` | `Intent`/`Command` → backend calls. Gain curve, click stabilisation, pane placement |
| `src/leapinput/actions.py` | Backend seam: `QuartzBackend` (real) and `DryRunBackend` (prints) |
| `src/leapinput/guard.py` | The separate process that releases the button if this one dies |
| `src/leapinput/telemetry.py` | Live diagnostics dashboard + per-click signal-window recorder (the phantom-click evidence trail) |
| `src/leapinput/oneeuro.py` | Vendored 1€ filter — adaptive smoothing, heavy when slow, light when fast |
| `src/leapinput/reach.py` | Fixed-camera reach box: roam-fit the comfortable envelope, plus the live viewport test view |
| `src/leapinput/phonedepth.py` | LPD1 receiver for the LeapDepth iOS companion — synchronized RGB + metric depth over TCP (phase 1: prove the pipe) |
| `ios/LeapDepth/` | The native depth companion: Swift + AVFoundation, TrueDepth (front) / LiDAR (rear) → LPD1 stream. The deliberate no-install exception |
| `src/leapinput/{doctor,viz,record,calibrate}.py` | Diagnosis, live view, corpus capture, threshold fitting |
| `scripts/` | `setup.sh` (reproducible env) · `verify-env.sh` (drift check) · `leapctl` (always-on on/off switch) |

## Built with

Python 3.12, MediaPipe Tasks + OpenCV for hand landmarks, aiortc + aiohttp for
the phone's WebRTC path, PyObjC/Quartz for `CGEventPost`, CFFI against
`libLeapC.6` for the original hardware, pytest for the hardware-free tests.
The 1€ filter is Casiez, Roussel & Vogel (CHI 2012), vendored rather than
depended on. The 2026-08-18 passes borrowed robustness patterns from
[mediapipe-touchdesigner](https://github.com/torinmb/mediapipe-touchdesigner),
command shapes from shipping mid-air vocabularies, and tail-latency doctrine
from the quant world — details in
[the strengthening notes](context/strengthening-2026-08-18.md) and
[the latency notes](context/latency-research-2026-08-18.md).
