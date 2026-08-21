# Leap

![Leap — two hands framing a region of the screen to capture it](docs/assets/hero.png)

**Five hand gestures, from your webcam, for the things a mouse cannot do while
your hands are somewhere else.** Open the mic and dictate, submit, paste, and
frame a region of the screen with both hands to capture it. No special
hardware, no setup beyond a virtualenv.

The hand deliberately does **not** drive the cursor. It used to — that was the
whole project — and all of it still works behind `--legacy`. But a mouse
points better, and every expensive bug here lived in the pointing path. What
ships is the part that earns its keep.

## The vocabulary

| Pose | Action |
|---|---|
| thumbs-up | mic on (chime); thumbs-up again = off |
| ILY on your **other** hand | Enter — submit what you dictated |
| V sign (peace) | Cmd+V |
| frame a rectangle with both hands | screenshot that region → clipboard |
| ILY on your **cursor** hand | pause / resume everything |

Hold each until the ring fills, then release — except the pause, which fires
as the ring fills so the chime does not wait for you. Either hand fires the mic, the
paste and the frame shot; ILY is the one pose whose meaning depends on which
hand makes it, which is what buys a pause without spending a second pose on
it. While you are composing a frame shot, nothing else can fire.

The frame lands on **the display your cursor is on**, not the main one — the
highlight and the shutter both follow it, so on a two-screen desk you frame
the screen you are looking at.

## Quick start

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[dev,camera]'
curl -L --create-dirs -o vendor/hand_landmarker.task \
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"

.venv/bin/leapinput --source camera                     # dry-run
.venv/bin/leapinput --source camera --backend quartz    # for real
```

Always on:

```bash
scripts/leapctl on                 # detached; also: off / status / log
scripts/install-menubar-app.sh     # menu bar switch, can start at login
```

`off` means off — the session, its guard and its overlay all go, leaving only
the menu bar switch. The `.app` wrapper is not just packaging: macOS attributes
the Camera grant to the app that starts the process tree, so the bundle is what
System Settings lists and what must declare `NSCameraUsageDescription`.

## Why it holds up

- **Verified against a corpus, not a demo.** 3,639 recorded frames of real use
  replay through the pipeline in CI. 337 hardware-free tests in under six
  seconds.
- **Arguments are settled with data.** Every threshold was fitted from
  recorded hand data, and every fix this month was pinned by a test that fails
  on the old code first. A phantom-click hunt took 352 recorded clicks to
  settle; a "the frame is jittery" report was traced to a rect being sampled
  during the Schmitt tail of a releasing finger.
- **Designed to fail safe.** Dry-run by default. A separate guard process
  releases every button if the main process dies — even to `SIGKILL`. Tracking
  loss, stream stalls and crashes all reach the same release path.

## Docs

Start at **[docs/START-HERE.md](docs/START-HERE.md)**.

| Doc | What |
|---|---|
| [docs/decisions.md](docs/decisions.md) | Why the tool is shaped like this. What moved, the evidence, **how to bring it back** |
| [docs/learnings/](docs/learnings/) | The durable knowledge, by subject — including everything now shelved |
| [docs/vocabulary.md](docs/vocabulary.md) | Full gesture tables, routing rules, corpus verification |
| [docs/troubleshooting.md](docs/troubleshooting.md) | When it doesn't work; the telemetry dashboard and bench; the safety model |
| [docs/calibration.md](docs/calibration.md) | Fitting thresholds and the reach box to your hand |
| [docs/architecture.md](docs/architecture.md) | Pipeline, layer rules, module map |
| [docs/sources.md](docs/sources.md) | Webcam vs phone vs Leap Motion |

## Legacy

Nothing was deleted. `--legacy` restores the full cursor-driving tool —
pointing, clicking, dragging, copy, Mission Control — along with the reach
box, PRISM precision, the accuracy bench and the phone/WebRTC source. It is
kept to be explored and built on, and the reasoning behind every shelved piece
is in [docs/decisions.md](docs/decisions.md) and
[docs/learnings/](docs/learnings/).

```bash
leapinput --legacy                        # the whole previous tool
leapctl on --legacy --source phone        # the 60fps phone camera; without
                                          # --legacy this exits, by design
```

Built with Python 3.12, MediaPipe Tasks + OpenCV, PyObjC/Quartz for
`CGEventPost`, and a vendored 1€ filter (Casiez, Roussel & Vogel, CHI 2012).
