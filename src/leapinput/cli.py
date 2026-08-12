"""Entry point. Defaults to dry-run — taking over the cursor is opt-in."""

from __future__ import annotations

import argparse
import sys
import time

from . import (
    Config, DirectDriver, GestureEngine, Intent, LeapSource, Mapping,
    ShortcutDriver, Snapshot, make_backend, server_status,
)
from .guard import Guard


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput")
    ap.add_argument("--backend", choices=("dry-run", "quartz"), default="dry-run",
                    help="dry-run logs actions; quartz drives the real cursor")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    ap.add_argument("--shortcuts", action="store_true",
                    help="also map swipes to Spaces / app switcher")
    ap.add_argument("--verbose", action="store_true", help="log pointer moves too")
    ap.add_argument("--invert-x", action="store_true",
                    help="flip left/right (try it if the cursor mirrors you)")
    ap.add_argument("--invert-z", action="store_true",
                    help="flip up/down (depends on which way the device faces)")
    ap.add_argument("--plane", choices=("xy", "xz"), default="xy",
                    help="xy: hand upright, drawing on a vertical plane. "
                         "xz: hand flat over the device, top-down")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="sensitivity multiplier; 2 = twice as fast, 0.5 = half")
    ap.add_argument("--point", choices=("index", "knuckles", "palm"),
                    default="index",
                    help="what the cursor follows. index is most expressive but "
                         "moves when you pinch; knuckles is rigid through a click")
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

    engine = GestureEngine(Config(hand=args.hand, plane=args.plane))
    direct = DirectDriver(backend, Mapping(plane=args.plane,
                                          invert_x=args.invert_x,
                                          invert_z=args.invert_z,
                                          gain_scale=args.gain,
                                          tracking_point=args.point))
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
        if args.plane == "xy":
            print("  Hold your hand UPRIGHT, palm facing the screen, as if drawing")
            print("  on it. Raise/lower to move up/down; height is the cursor axis.")
        else:
            print("  Hold your hand FLAT over the device, palm down.")
        print("  pinch = click   fist+move = scroll   turn palm away = park cursor")
        if args.duration:
            print(f"  auto-stops after {args.duration:.0f}s")
    print(f"\nRaise your {args.hand.lower()} hand above the device to engage.")

    # The guard is a separate process holding the other end of a pipe. If this
    # process dies in any way — including SIGKILL, which no finally: survives — the
    # pipe closes and the guard releases every mouse button.
    guard = Guard().start() if args.backend == "quartz" else None

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
            if guard:
                guard.stop()
    print(f"{source.frames} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
