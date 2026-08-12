"""Entry point. Defaults to dry-run — taking over the cursor is opt-in."""

from __future__ import annotations

import argparse
import sys
import time

from . import (
    Config, DirectDriver, GestureEngine, Intent, LeapSource, Mapping,
    ShortcutDriver, Snapshot, make_backend, server_status,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput")
    ap.add_argument("--backend", choices=("dry-run", "quartz"), default="dry-run",
                    help="dry-run logs actions; quartz drives the real cursor")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    ap.add_argument("--shortcuts", action="store_true",
                    help="also map swipes to Spaces / app switcher")
    ap.add_argument("--verbose", action="store_true", help="log pointer moves too")
    ap.add_argument("--duration", type=float, default=120.0,
                    help="stop automatically after N seconds (0 = no limit). A "
                         "runaway that owns the cursor is hard to quit by hand, so "
                         "the real backend always gets a deadline by default.")
    args = ap.parse_args(argv)

    status = server_status()
    devices = [d["serial"] for d in status["devices"]]
    if not devices:
        print("No Leap device attached to the tracking service.", file=sys.stderr)
        return 1
    print(f"Hyperion {status['version']} — devices {devices}")

    backend = make_backend(args.backend, verbose=args.verbose) \
        if args.backend == "dry-run" else make_backend(args.backend)

    engine = GestureEngine(Config(hand=args.hand))
    direct = DirectDriver(backend, Mapping())
    engine.subscribe(direct.on_intent)
    if args.shortcuts:
        engine.subscribe(ShortcutDriver(backend).on_intent)

    def trace(event):
        if event.intent is not Intent.POINT_MOVE or args.verbose:
            print(f"{event.intent.value}", file=sys.stderr)

    engine.subscribe(trace)

    source = LeapSource()
    source.subscribe(engine.on_snapshot)

    w, h = backend.screen
    print(f"screen {w:.0f}x{h:.0f} | backend={args.backend} | hand={args.hand}")
    if args.backend == "quartz":
        print("\n  *** DRIVING THE REAL CURSOR ***")
        print("  Drop your hand to the desk to release it — the device stops")
        print("  tracking entirely, so that is a hard disengage, not a threshold.")
        print("  pinch = click/drag   fist = grab   Ctrl-C to quit")
        if args.duration:
            print(f"  auto-stops after {args.duration:.0f}s")
    print(f"\nRaise your {args.hand.lower()} hand above the device to engage.")

    deadline = time.monotonic() + args.duration if args.duration else None
    with source.open():
        try:
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.2)
            print(f"\nauto-stopped after {args.duration:.0f}s")
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            # Never exit holding a button — that would strand the mouse down and
            # leave the machine selecting everything the user touches.
            engine.on_snapshot(Snapshot())
    print(f"{source.frames} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
