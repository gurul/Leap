# When it doesn't work

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
not memory. `--no-telemetry` disables the layer; `--telemetry-port N` moves it.

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
