# Sources: webcam, phone, Leap Motion

The built-in webcam is the daily driver (2026-08-19). The phone and the Leap
are features: reach for the phone when a faster-than-webcam source helps, and
for the Leap when you want the precision benchmark.

| | webcam | phone (WebRTC) | Leap Motion |
|---|---|---|---|
| frame rate | 29.4 fps at 640×480 (449 frames / 15.3s) | 57.2 fps at 640×480 (1,137 frames / 19.9s) | 111 fps (measured, 667 frames / 6.0s) |
| latency | one extra camera exposure | ~40–80 ms glass-to-glass (encode + LAN + decode) | sub-frame |
| depth | none — image plane only (`--plane xy`) | none — image plane only (`--plane xy`) | real Z, so the desk plane works (`--plane xz`) |
| pinch / grab | synthesised from world-landmark geometry | synthesised from world-landmark geometry | reported by the SDK |
| needs | nothing | `[phone]` extra + any phone with Safari/Chrome | the hardware + Hyperion + the SDK pins below |

All three paths verified end-to-end from live frames: engage → click → drag →
release (Leap and webcam 2026-08-12, phone 2026-08-18).

Cameras are picked **by name**, not by index — virtual cameras (Camo, OBS)
shuffle AVFoundation's device order, and their feeds are black unless their
app is streaming. `--list-cameras` shows what's attached; `--camera-name
iphone` targets Continuity Camera (or any camera by substring), `--camera N`
forces a raw index.

## The phone as a 60 fps camera — no app required

`--source phone` turns the phone's browser into the capture device: Leap
serves one HTTPS page on your LAN, the phone's Safari streams its camera back
over WebRTC (hardware H.264, UDP, 60 fps where the phone allows it), and
frames feed the MediaPipe pipeline directly. No app install, no virtual
camera driver, no paired accounts.

```bash
VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[phone]'
.venv/bin/leapinput --source phone --backend dry-run   # prints the URL to open
```

Open the printed URL on the phone, accept the self-signed-certificate warning
once, tap **Start (rear)** or **Start (front)**. The random URL token is
persisted (`~/.leapinput/phonecam-token`) so the phone bookmark keeps
working; media never leaves your network (no STUN/TURN).

From the menu bar, **Use phone camera (starts server)** does the same thing
without a terminal: it stops a webcam session if one is running, starts the
phone source, then copies the URL to the clipboard and shows it. The LAN IP
in that URL changes with the network, so the menu reads it from the log the
running session just wrote rather than reusing an old one. The plain
**Turn on** never starts the server — the built-in camera is the default,
and the phone path is always an explicit choice.

Measured on 2026-08-18 (iPhone → M5 MacBook Pro, LAN Wi-Fi): **57.2 fps
delivered** (1,137 frames / 19.9 s), median frame cadence 16.7 ms — exact
60 Hz — 98.5% of frames unique motion. With detection at ~9 ms/frame on VGA,
the whole pipeline tracks at 60 fps-class rates.

On the phone source, the **IMU rides along** over a WebRTC datachannel: if
the stand gets bumped, the session tells you instead of silently degrading.
LiDAR/TrueDepth are not web-reachable — real depth comes from the
[LeapDepth native companion](../ios/LeapDepth), scaffolded: synchronized
RGB+depth over TCP, `python -m leapinput.phonedepth` to receive; see
[the depth plan](context/depth-companion-plan.md).

## The latency work (phone path)

A camera only feels like an input device if the path from photons to cursor
is short and, above all, *consistent*. The median here is physics — 16.7 ms
is a 60 Hz camera's own cadence — so the engineering is in the tail, and the
receive path was audited down to aiortc's source (seven parallel research
streams: WebRTC internals, Safari's encoder, the real-time-video literature,
alternative transports, VR latency compensation, and the HFT tail-latency
playbook):

- **aiortc's jitter buffer held every frame hostage for one extra frame** —
  it only released frame N when frame N+1's first packet arrived, never
  reading the RTP marker bit. Patched: ~16.7 ms back on every frame.
- **Head-of-line stalls bounded.** Jitter capacity 128 → 64: one unrecovered
  packet loss now costs a short stall + a keyframe request instead of a
  ~250–500 ms freeze. Freshness beats completeness for a cursor.
- **The encoder is never software.** H.264 is pinned in negotiation (hardware
  VideoToolbox on iPhone, no B-frames by spec), the decoder runs with
  FFmpeg's `low_delay` flag, and `contentHint='motion'` +
  `degradationPreference` make Safari sacrifice resolution before frame
  rate — never the reverse.
- **No congestion governor on a one-hop LAN.** aiortc's receive-side
  bandwidth estimate (REMB) initializes low and becomes a hard send
  ceiling — it caused a measured mid-session downscale. Stripped from
  negotiation; a 4 Mbps cap keeps frames small so a lost packet stalls less
  stream.
- **Conflation at the ingress, freshest-frame-wins at the consumer.** Frames
  are never queued anywhere: the receiver drains to the newest before paying
  conversion cost, and the pipeline always reads the latest frame, dropping
  stale ones — the same discipline (and the same p99-first measurement
  doctrine) quant systems use.
- **Runtime discipline:** tracking threads pinned to performance cores via
  macOS QoS, cyclic GC frozen after startup so it can't inject 10–50 ms
  pauses mid-gesture.

What's next, in order: killing AWDL (AirDrop's channel-hopping is the classic
macOS Wi-Fi jitter source), USB-C tethering (deletes the radio from the path
entirely), and ~35 ms of pose prediction — the VR trick that puts perceived
latency below the ~50 ms threshold where an indirect cursor becomes
indistinguishable from instant. Full findings, sources, and the ranked
roadmap: [`context/latency-research-2026-08-18.md`](context/latency-research-2026-08-18.md).

## The original hardware

The Leap Motion Controller path this project grew from still works, and
still sets the precision bar (111 fps, real depth):

```bash
./scripts/setup.sh                    # builds .venv, vendors the bindings, verifies
.venv/bin/leapinput                   # dry-run: logs what it would do
.venv/bin/leapinput --backend quartz  # drives the real cursor, 120s deadline
```

Hold your hand flat over the device, palm down. `scripts/verify-env.sh`
re-asserts the whole baseline (Hyperion version, device, frame rate,
Accessibility permission) and exits non-zero on drift — run it first whenever
something stops working.

## Why the setup is this specific

Three non-obvious pins for the Leap path, each of which will waste an
afternoon:

1. **Hyperion 6.2 or newer.** 6.0 and 6.1 dropped support for the 2013 v1
   controller entirely. 6.2 restored it.
2. **CPython 3.12 exactly.** The SDK's bundled CFFI extension is
   `_leapc_cffi.cpython-312-darwin.so`. No other Python imports it without
   rebuilding from source.
3. **The [`DDlabAU/LeapMotion-Python-Hyperion`](https://github.com/DDlabAU/LeapMotion-Python-Hyperion)
   fork**, not `ultraleap/leapc-python-bindings`. The official repo is
   Gemini-era and links `libLeapC.5`; Hyperion ships `libLeapC.6`.

And one for the camera path: **mediapipe 1.x has no bundled model** and
labels handedness for the *un-mirrored* image, so a right hand reads `"Left"`
on a selfie feed — 186/186 frames. `camera.py` swaps the label; don't "fix"
that without re-measuring.

Everything measured, plus the dead ends not worth re-exploring, is in
[`context/environment.md`](context/environment.md).
