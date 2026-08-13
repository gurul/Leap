"""Entry point. Defaults to dry-run — taking over the cursor is opt-in."""

from __future__ import annotations

import argparse
import sys
import time

from . import (
    CameraSource, Config, DirectDriver, GestureEngine, Intent, LeapSource,
    Mapping, ShortcutDriver, Snapshot, make_backend, server_status,
    tune_for_camera,
)
from .guard import Guard


def _overlay_status(cv2, bgr, engine, tracked, last_intent: str) -> None:
    """Engine truth, not camera truth: what the gesture layer thinks is happening."""
    if tracked is None:
        status, color = "NO HAND", (0, 0, 230)
    elif not engine.clutch.state:
        status, color = "LIFTED  (open hand - cursor parked)", (180, 180, 180)
    elif engine.grab.state:
        status, color = "DRAG  (fist holds the button)", (0, 165, 255)
    elif engine.pinch.state:
        status, color = "CLICK  (pinch holds the button)", (0, 165, 255)
    else:
        status, color = "MOVING", (0, 200, 0)
    h = bgr.shape[0]
    cv2.putText(bgr, status, (8, h - 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                color, 2, cv2.LINE_AA)
    cv2.putText(bgr, f"last intent: {last_intent}", (8, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput")
    ap.add_argument("--backend", choices=("dry-run", "quartz"), default="dry-run",
                    help="dry-run logs actions; quartz drives the real cursor")
    ap.add_argument("--source", choices=("leap", "camera"), default="leap",
                    help="leap: the Leap Motion controller. camera: a plain "
                         "webcam through MediaPipe — no Leap hardware needed")
    ap.add_argument("--camera", type=int, default=0,
                    help="camera index for --source camera (default 0)")
    ap.add_argument("--preview", action="store_true",
                    help="camera only: show the mirrored feed with the hand "
                         "skeleton, per-finger state and live gesture readout. "
                         "Press q in the window to stop")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    ap.add_argument("--shortcuts", action="store_true",
                    help="also map swipes to Spaces / app switcher")
    ap.add_argument("--verbose", action="store_true", help="log pointer moves too")
    ap.add_argument("--invert-x", action="store_true",
                    help="flip left/right (try it if the cursor mirrors you)")
    ap.add_argument("--invert-z", action="store_true",
                    help="flip up/down (depends on which way the device faces)")
    ap.add_argument("--plane", choices=("xz", "xy"), default=None,
                    help="xz: desk plane — hand forward/back moves the cursor "
                         "up/down. xy: hand height moves it up/down. Default: "
                         "xz for --source leap, xy for --source camera (a webcam "
                         "sees the image plane; it has no usable depth axis)")
    ap.add_argument("--no-clutch", action="store_true",
                    help="pointer moves whenever a hand is tracked. Use this if "
                         "the cursor will not move at all; you lose the ratchet")
    ap.add_argument("--clutch-deg", type=float, default=None,
                    help="how far the palm may tilt and still hold the clutch "
                         "(default 30). Raise it if the cursor will not move")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="sensitivity multiplier; 2 = twice as fast, 0.5 = half")
    ap.add_argument("--point", choices=("index", "knuckles", "palm"),
                    default=None,
                    help="what the cursor follows. index is most expressive but "
                         "moves when you pinch; knuckles is rigid through a click. "
                         "Default: index for leap, knuckles for camera (the index "
                         "tip is MediaPipe's noisiest landmark)")
    ap.add_argument("--duration", type=float, default=120.0,
                    help="stop automatically after N seconds (0 = no limit). A "
                         "runaway that owns the cursor is hard to quit by hand, so "
                         "the real backend always gets a deadline by default.")
    args = ap.parse_args(argv)
    if args.plane is None:
        args.plane = "xy" if args.source == "camera" else "xz"
    if args.point is None:
        args.point = "knuckles" if args.source == "camera" else "index"

    if args.source == "camera":
        source = CameraSource(camera=args.camera, preview=args.preview)
        print(f"MediaPipe HandLandmarker — camera {args.camera} (mirrored)")
    elif args.preview:
        print("--preview requires --source camera", file=sys.stderr)
        return 2
    else:
        status = server_status()
        devices = [d["serial"] for d in status["devices"]]
        if not devices:
            print("No Leap device attached to the tracking service.", file=sys.stderr)
            return 1
        print(f"Hyperion {status['version']} — devices {devices}")
        source = LeapSource()

    backend = make_backend(args.backend, verbose=args.verbose) \
        if args.backend == "dry-run" else make_backend(args.backend)

    gesture_cfg = Config(hand=args.hand, plane=args.plane,
                         clutch_enabled=not args.no_clutch)
    if args.clutch_deg is not None:
        gesture_cfg.clutch_on_deg = args.clutch_deg
        gesture_cfg.clutch_off_deg = args.clutch_deg + 15.0
        gesture_cfg.clutch_on_deg_xy = args.clutch_deg
        gesture_cfg.clutch_off_deg_xy = args.clutch_deg + 15.0
    mapping = Mapping(plane=args.plane, invert_x=args.invert_x,
                      invert_z=args.invert_z, gain_scale=args.gain,
                      tracking_point=args.point)
    if args.source == "camera":
        tune_for_camera(gesture_cfg, mapping)
    engine = GestureEngine(gesture_cfg)
    direct = DirectDriver(backend, mapping)
    engine.subscribe(direct.on_intent)
    if args.shortcuts:
        engine.subscribe(ShortcutDriver(backend).on_intent)

    last = {"intent": "-"}

    def trace(event):
        if event.intent is not Intent.POINT_MOVE:
            last["intent"] = event.intent.value
        if event.intent is not Intent.POINT_MOVE or args.verbose:
            print(f"{event.intent.value}", file=sys.stderr)

    engine.subscribe(trace)

    source.subscribe(engine.on_snapshot)

    w, h = backend.screen
    print(f"screen {w:.0f}x{h:.0f} | backend={args.backend} | hand={args.hand}")
    if args.backend == "quartz":
        print("\n  *** DRIVING THE REAL CURSOR ***")
        print("  Drop your hand to the desk to release it — the device stops")
        print("  tracking entirely, so that is a hard disengage, not a threshold.")
        if args.source == "camera":
            print("  Face the camera; the view is mirrored — move right, cursor")
            print("  goes right. Hand out of view = hard release, like the Leap.")
        elif args.plane == "xy":
            print("  Hold your hand UPRIGHT, palm facing the screen, as if drawing")
            print("  on it. Raise/lower to move up/down; height is the cursor axis.")
        else:
            print("  Hold your hand FLAT over the device, palm down.")
        print("  point = move   pinch = click   fist = drag   open hand = lift")
        if args.duration:
            print(f"  auto-stops after {args.duration:.0f}s")
    where = ("into the camera view" if args.source == "camera"
             else "above the device")
    print(f"\nRaise your {args.hand.lower()} hand {where} to engage.")

    # The guard is a separate process holding the other end of a pipe. If this
    # process dies in any way — including SIGKILL, which no finally: survives — the
    # pipe closes and the guard releases every mouse button.
    guard = Guard().start() if args.backend == "quartz" else None

    def warn_if_stuck() -> None:
        seen = source.latest.get(args.hand)
        if seen is None or engine.clutch.state or not gesture_cfg.clutch_enabled:
            return
        if gesture_cfg.clutch_mode == "fingers":
            print(f"\n  cursor is parked: {engine.fingers.value} fingers extended.")
            print("  point to move it; an OPEN HAND (4+ fingers) lifts the mouse.\n")
            return
        angle = engine.last_clutch_angle
        if angle is None:
            return
        facing = "toward the screen" if args.plane == "xy" else "down at the desk"
        print(f"\n  cursor is frozen because the CLUTCH is not engaging.")
        print(f"  your palm is {angle:.0f} deg off; it must be within "
              f"{engine.clutch.on_at:.0f} deg of facing {facing}.")
        print(f"  fixes:  --clutch-deg {max(35, int(angle) + 10)}   "
              f"|  --no-clutch   |  --plane {'xz' if args.plane == 'xy' else 'xy'}\n")

    deadline = time.monotonic() + args.duration if args.duration else None
    cv2 = None
    if args.preview:
        # cv2 windows must be created and pumped on the MAIN thread on macOS;
        # the capture thread only annotates frames (source.preview_frame).
        import cv2
        win = "leapinput camera (q closes)"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    with source.open():
        try:
            warned_at = time.monotonic() + 4.0
            while deadline is None or time.monotonic() < deadline:
                if cv2 is not None:
                    frame_bgr = source.preview_frame
                    if frame_bgr is not None:
                        _overlay_status(cv2, frame_bgr, engine,
                                        source.latest.get(args.hand),
                                        last["intent"])
                        cv2.imshow(win, frame_bgr)
                    if cv2.waitKey(33) & 0xFF in (27, ord("q")):
                        print("\npreview closed")
                        break
                else:
                    time.sleep(0.2)
                if time.monotonic() > warned_at:
                    warn_if_stuck()
                    warned_at = time.monotonic() + 8.0
            else:
                print(f"\nauto-stopped after {args.duration:.0f}s")
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            # Never exit holding a button — that would strand the mouse down and
            # leave the machine selecting everything the user touches.
            engine.on_snapshot(Snapshot())
            if guard:
                guard.stop()
            if cv2 is not None:
                cv2.destroyAllWindows()
                cv2.waitKey(1)          # let Cocoa actually close the window
    print(f"{source.frames} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
