#!/usr/bin/env bash
# Assert the environment still matches docs/context/environment.md. Non-zero exit = drift.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/.venv/bin/python" - <<'PY'
import sys, time
import leap

fail = []

status = leap.get_server_status(2000)
print(f"hyperion:      {status['version']}")
if not status["version"].startswith("v6.2"):
    fail.append(f"expected Hyperion v6.2.x, got {status['version']}")

devices = status["devices"]
print(f"devices:       {[(d['serial'], d['type']) for d in devices]}")
if not devices:
    fail.append("no device reported by the tracking service")

class Counter(leap.Listener):
    n = 0
    def on_tracking_event(self, event):
        Counter.n += 1

conn = leap.Connection()
conn.add_listener(Counter())
with conn.open():
    conn.set_tracking_mode(leap.TrackingMode.Desktop)
    t0 = time.monotonic()
    time.sleep(3.0)
    elapsed = time.monotonic() - t0

fps = Counter.n / elapsed
print(f"frame rate:    {fps:.0f} fps ({Counter.n} frames in {elapsed:.1f}s)")
if fps < 50:
    fail.append(f"frame rate {fps:.0f} fps is far below the ~110 fps baseline")

try:
    from ApplicationServices import AXIsProcessTrusted
    trusted = bool(AXIsProcessTrusted())
except ImportError:
    trusted = None
print(f"accessibility: {trusted}")
if trusted is False:
    fail.append("no Accessibility permission — CGEventPost will be silently dropped")

print()
if fail:
    for f in fail:
        print(f"FAIL: {f}")
    sys.exit(1)
print("OK: environment matches the verified baseline")
PY
