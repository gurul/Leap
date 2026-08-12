"""Entry point. Defaults to dry-run — taking over the cursor is opt-in."""

from __future__ import annotations

import argparse
import sys
import time

from . import (
    Config, DirectDriver, GestureEngine, Intent, LeapSource, Mapping,
    ShortcutDriver, make_backend, server_status,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput")
    ap.add_argument("--backend", choices=("dry-run", "quartz"), default="dry-run",
                    help="dry-run logs actions; quartz drives the real cursor")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    ap.add_argument("--shortcuts", action="store_true",
                    help="also map swipes to Spaces / app switcher")
    ap.add_argument("--verbose", action="store_true", help="log pointer moves too")
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
    print(f"Raise your {args.hand.lower()} hand above the device to engage. Ctrl-C to quit.")

    with source.open():
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print(f"\n{source.frames} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
