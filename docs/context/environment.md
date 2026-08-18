# Verified environment

Everything here was measured on this machine, not inferred. Date verified: **2026-08-12**.
Re-verify with `scripts/verify-env.sh` rather than trusting this file after a Hyperion or macOS update.

## Host

| | |
|---|---|
| Machine | MacBook Pro, Apple M5 Pro, 18 cores, 48 GB |
| OS | macOS 26.5.2 (build 25F84), Darwin 25.5.0 |
| Main screen | 1512 × 982 logical points |
| Accessibility permission | **granted** to the terminal — `CGEventPost` synthetic events land |

## Device

| | |
|---|---|
| Model | **Original Leap Motion Controller (2013, v1)** — *not* the Leap Motion Controller 2 |
| Serial | `LP20006680004` |
| Type reported by service | `LMC` |
| Bus | USB 2.0, 480 Mb/s |
| Measured frame rate | ~111 fps (667 frames in 6.0 s, Desktop tracking mode) |

The v1 controller is the constraint that pins the software version. Hyperion **6.0 and 6.1 dropped v1
support entirely** (LMC2-only); **6.2 restored it**. Do not downgrade below 6.2.

## Tracking software

| | |
|---|---|
| Product | Ultraleap **Hyperion 6.2.0.0** |
| Architecture | native **arm64** |
| Install path | `/Applications/Ultraleap Hand Tracking.app` |
| Service binary | `Contents/bin/libtrack_server` (runs as a normal process, **no kext**) |
| Control Panel | `Contents/MacOS/Ultraleap Control Panel.app` |
| Version string from API | `v6.2.0-c98d293a` |

Ultraleap documents macOS 11.0+ and names only Intel i7 / M1 / M2 as tested silicon. An M5 Pro on
macOS 26 is **outside their tested matrix** — it works, but that is empirical, not supported.

## SDK layout

`/Applications/Ultraleap Hand Tracking.app/Contents/LeapSDK/`

```
include/LeapC.h
lib/libLeapC.6.dylib          <- SONAME .6
lib/libLeapC.dylib
lib/cmake/
leapc_cffi/
  __init__.py
  _leapc_cffi.cpython-312-darwin.so
  LeapC.h
  libLeapC.6.dylib
samples/                       CallbackSample.c, PollingSample.c, ImageSample.c,
                               MultiDeviceSample.c, InterpolationSample.c,
                               DeviceTransformSample.c, FiducialTrackingSample.c,
                               RecordPlaybackSample.c, ExampleConnection.c
```

## Gotchas that cost real time

1. **The bundled CFFI module is CPython 3.12 only.** `_leapc_cffi.cpython-312-darwin.so` will not
   import under any other Python. The system default here is 3.14.6, which fails with
   `ModuleNotFoundError: No module named '_cffi_backend'` or an ABI mismatch. Use `uv venv --python 3.12`.
   Rebuilding for another Python means `python -m build leapc-cffi` from source.

2. **`libLeapC.6.dylib`, not `.5`.** Gemini-era (v5) code and the official
   `ultraleap/leapc-python-bindings` repo expect `libLeapC.5.dylib`. The Hyperion-updated fork
   [`DDlabAU/LeapMotion-Python-Hyperion`](https://github.com/DDlabAU/LeapMotion-Python-Hyperion) is what works.

3. **`cffi` is not a declared dependency** of the bindings package but is required. Install it explicitly.

4. **`system_profiler SPUSBDataType | grep -i leap` returns nothing** while the tracking service holds
   the device open. System Information.app still shows it. Do not use that grep as a presence check —
   use `leap.get_server_status()` instead.

5. **Accessibility permission failures are silent.** Without it, `CGEventPost` returns no error and
   simply does nothing. Always gate on `ApplicationServices.AXIsProcessTrusted()` and warn.

## Known dead ends

Do not re-propose these without strong new evidence.

| Thing | Status |
|---|---|
| Ultraleap **TouchFree** (the official touchless-cursor product) | **Windows only**, v2.6.1 (20.05.2024). No Mac build exists. |
| **BetterTouchTool** Leap support | Removed in v1.89 (2018). Developer cited an unsupported framework and near-zero usage. Never restored. |
| Airspace / V2-SDK app ecosystem (PyLeapMouse, GameWAVE, …) | Targets the dead 32-bit-era V2 SDK. Will not run on modern macOS. |
| Ultraleap **Gemini 5.x** on this machine | Superseded; also 5.x is no longer distributed by Ultraleap. 6.2 is better on Apple Silicon (though *worse* than 5.2 on Intel). |

## Working baseline

A verified end-to-end Python environment exists. Reproduce it with `scripts/setup.sh`. The smoke test
`scripts/verify-env.sh` asserts: Hyperion version, device presence, frame throughput, and Accessibility
permission.

## Camera source (no Leap hardware)

Measured on this machine, **2026-08-12**, `--source camera`:

| | |
|---|---|
| Stack | mediapipe 1.0.0 (Tasks API only — `mp.solutions` is gone), opencv 5.0.0, CPython 3.12 |
| Model | `vendor/hand_landmarker.task` (float16, 7.8 MB, fetched from Google's model bucket — see `camera.py:MODEL_URL`) |
| Measured frame rate | **29.4 fps** at 640×480 (449 frames / 15.3 s), hand detected on 145/150 polls |
| End-to-end | full vocabulary verified live: engage → clutch.down → select.down/up → clutch.up → disengage |

Gotchas that cost time, so they are pinned here:

1. **Handedness is swapped on a mirrored feed.** MediaPipe 1.0.0 labels handedness for the
   *un-mirrored* image: a right hand read `"Left"` on **186/186 frames** of our selfie-view feed.
   `camera.py` swaps the label; do not "fix" that swap without re-measuring.
2. **mediapipe 1.x has no bundled model.** `HandLandmarker` needs the `.task` file downloaded
   separately; the old `mp.solutions.hands` API (which bundled it) no longer exists.
3. **Camera permission** must be granted to the terminal (System Settings → Privacy & Security →
   Camera), or `cv2.VideoCapture(0)` opens nothing.
4. The Leap SDK is now **optional**: `leapinput.capture` imports without `leap` installed and
   raises only if `LeapSource`/`server_status` are actually used.
5. **cv2 and PyAV each bundle ffmpeg.** With the `phone` extra installed, importing both
   `cv2` and `av` logs an objc duplicate-class warning (`AVFAudioReceiver` in two
   libavdevice dylibs). Harmless so far (the phonecam E2E loopback passes), but if
   `--source phone` ever crashes mysteriously, suspect this first.
6. **Virtual cameras steal index 0.** Installing Camo Studio (2026-08-18) put "Camo Camera"
   ahead of the MacBook camera in AVFoundation's enumeration, so `cv2.VideoCapture(0)` opened
   a black virtual feed and tracking silently died. `camera.pick_camera_index()` now resolves
   the built-in camera by name via `system_profiler` when no `--camera` index is given;
   an explicit `--camera N` still overrides.
