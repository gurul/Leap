# leap-input

Turning Leap Motion hand tracking into computer-use actions on macOS.

## Status

**Phase 0 — context space established, environment verified.** The build plan is being produced;
see `docs/plan.md` once it lands.

What already works, measured on this machine:

- Ultraleap Hyperion 6.2.0 (arm64) driving an original 2013 Leap Motion Controller at **111 fps**
- Python 3.12 bindings reading live skeletal frames
- macOS Accessibility permission granted, so synthetic `CGEvent` input lands
- `src/leapmouse.py` — a thin vertical slice: palm position → cursor, pinch → click/drag

## Quick start

```bash
./scripts/setup.sh          # builds .venv, vendors the bindings, verifies
.venv/bin/python src/leapmouse.py
```

`scripts/verify-env.sh` re-asserts the whole baseline (Hyperion version, device, frame rate,
Accessibility) and exits non-zero on drift. Run it first whenever something stops working.

## Why the setup is this specific

Three non-obvious pins, each of which will waste an afternoon if you get them wrong:

1. **Hyperion 6.2 or newer.** Hyperion 6.0/6.1 dropped support for the 2013 v1 controller. 6.2 added it back.
2. **CPython 3.12 exactly.** The SDK's bundled CFFI extension is `_leapc_cffi.cpython-312-darwin.so`.
   No other Python can import it without rebuilding from source.
3. **The `DDlabAU/LeapMotion-Python-Hyperion` fork**, not `ultraleap/leapc-python-bindings`.
   The official repo is Gemini-era and links `libLeapC.5`; Hyperion ships `libLeapC.6`.

Full detail, including dead ends not worth re-exploring, is in
[`docs/context/environment.md`](docs/context/environment.md).

## Layout

```
docs/context/     durable facts — versions, paths, gotchas, dead ends
docs/plan.md      the build plan
scripts/          setup.sh (reproducible env), verify-env.sh (drift check)
src/              application code
vendor/           cloned bindings (gitignored)
```
