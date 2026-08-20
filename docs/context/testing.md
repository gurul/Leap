# Testing notes

## Layer boundaries make most of this testable without hardware

`capture.py` is the only module that imports `leap`. Everything above it consumes
`HandFrame`, a plain frozen dataclass. So the gesture engine — where all the fiddly
temporal logic lives — is tested by synthesizing frames, with no device and no hands:

```bash
.venv/bin/python -m pytest -q      # 337 tests, 5.4s (measured 2026-08-20)
```

(The count read "14 tests, ~0.02s" when this file was written on 2026-08-12.
The progression since: 14 → 26 → 42 → 87 → 149 → 181 → 246 → 297 → 337. One
known defect: `tests/test_calibrate.py:114` opens the gitignored
`camera_session.jsonl` by relative path with no skip guard, so it errors on a
fresh clone or from any cwd but the repo root.)

The tests that matter most are the safety ones: `test_tracking_loss_releases_a_held_button`
and `test_select_up_precedes_disengage`. Those cover the failure that leaves your machine
with a stuck mouse button because your hand left the interaction volume mid-drag.

## Always develop against `DryRunBackend`

`--backend dry-run` is the default, and that is deliberate. A half-tuned Schmitt trigger
wired to the real cursor will fight you for control of the machine you need in order to
fix it. Tune thresholds against dry-run logs, then switch to `--backend quartz`.

## Traps that cost real time

### Backgrounded processes never receive SIGINT here

Running `cmd &` from a **non-interactive** shell (which is what tool-driven shells are)
sets SIGINT to `SIG_IGN`, and the child inherits it. `kill -INT <pid>` then does nothing,
and the process looks hung. This has nothing to do with Leap — a bare `time.sleep(30)`
script behaves identically. Verified 2026-08-12.

Do not conclude "the shutdown path hangs" from this. To actually test signal handling:

```python
signal.signal(signal.SIGINT, signal.default_int_handler)   # undo the inherited SIG_IGN
threading.Timer(3.0, lambda: signal.raise_signal(signal.SIGINT)).start()
```

The CLI exits cleanly on a genuine SIGINT (`rc=0`, teardown in ~0.01 s).

### Redirected stdout is block-buffered

`python -m leapinput.cli > log 2>&1` shows nothing until the buffer flushes, which reads
as "it hung before printing." Use `python -u`. Set `PYTHONFAULTHANDLER=1` and
`kill -ABRT <pid>` to dump every thread's stack when something genuinely is stuck — that
is how the above was diagnosed.

### `Connection.close()` is fast; suspect your harness first

Measured at 0.01 s. The poll thread checks `_stop_poll_flag` each iteration and
`LeapPollConnection` returns within its timeout. If teardown appears to block, the cause
is almost certainly the test harness, not the binding.

## Verifying against hardware

`scripts/verify-env.sh` asserts Hyperion version, device presence, frame rate (~111 fps
baseline) and Accessibility permission, exiting non-zero on drift. Run it before
debugging anything else — it distinguishes "my code is wrong" from "the service died".

With no hand over the device the full chain should produce **many frames and zero
intents**. That is the engagement gate working, not a failure.
