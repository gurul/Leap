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
