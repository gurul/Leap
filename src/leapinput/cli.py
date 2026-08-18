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


def _overlay_status(cv2, bgr, engine, tracked, last_intent: str,
                    stats: dict | None = None) -> None:
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
    if stats and stats["fps"]:
        # Amber when detection cannot keep up: the honest explanation for lag.
        ok = stats["realtime"]
        cv2.putText(bgr, f"camera {stats['fps']:.0f}fps  "
                         f"detect {stats['detect_ms']:.0f}ms",
                    (8, h - 58), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255) if ok else (0, 191, 255), 1, cv2.LINE_AA)


def resolve_source_defaults(args) -> None:
    """Per-source defaults for every axis-and-posture flag the user left unset.

    invert_x is the one that bit: Mapping's default is the MEASURED Leap truth
    (invert_x=True, confirmed by use 2026-08-12), but building Mapping straight
    from a store_true argparse default silently clobbered it with False on
    every default run — the Leap shipped mirrored. Resolution now happens here,
    per source, and only for flags the user did not pass.
    """
    if args.plane is None:
        args.plane = "xy" if args.source == "camera" else "xz"
    if args.point is None:
        args.point = "knuckles" if args.source == "camera" else "index"
    if args.invert_x is None:
        args.invert_x = args.source == "leap"
    if args.invert_z is None:
        args.invert_z = False


def _overlay_commands(cv2, bgr, overlay: dict) -> None:
    """Two-level feedback (the dwell literature's rule): the label acknowledges
    RECOGNITION the moment a pose is armed; the ring fills toward COMMITMENT;
    release fires. The live rectangle shows exactly what a pane would frame."""
    h, w = bgr.shape[:2]
    rect = overlay.get("rect")
    if rect is not None:
        x0, y0, x1, y1 = rect
        cv2.rectangle(bgr, (int(x0 * w), int(y0 * h)),
                      (int(x1 * w), int(y1 * h)), (255, 200, 0), 2)
    progress = overlay.get("progress", 0.0)
    if overlay.get("label"):
        cx, cy, r = w - 44, 44, 22
        done = progress >= 1.0
        color = (0, 220, 0) if done else (255, 200, 0)
        cv2.ellipse(bgr, (cx, cy), (r, r), -90.0, 0.0, 360.0 * progress,
                    color, 4, cv2.LINE_AA)
        cv2.putText(bgr, overlay["label"] + ("  release!" if done else ""),
                    (w - 230, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                    cv2.LINE_AA)


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
    ap.add_argument("--tutorial", action="store_true",
                    help="camera only: guided practice room — walks through the "
                         "whole vocabulary step by step over the preview. "
                         "Forces dry-run: the tutorial never touches the real "
                         "cursor")
    ap.add_argument("--no-commands", action="store_true",
                    help="camera only: disable the pose-hold commands (finger-"
                         "frame pane, OK-pose Mission Control, ILY pause)")
    ap.add_argument("--pane", choices=("window", "tab"), default="window",
                    help="what the finger-frame gesture spawns: a new window "
                         "placed over the framed region (default), or a tab")
    ap.add_argument("--verbose", action="store_true", help="log pointer moves too")
    ap.add_argument("--invert-x", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="flip left/right (try it if the cursor mirrors you). "
                         "Default: on for --source leap (confirmed by use), "
                         "off for camera (the mirrored view already matches)")
    ap.add_argument("--invert-z", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="flip up/down (depends on which way the device faces)")
    ap.add_argument("--plane", choices=("xz", "xy"), default=None,
                    help="xz: desk plane — hand forward/back moves the cursor "
                         "up/down. xy: hand height moves it up/down. Default: "
                         "xz for --source leap, xy for --source camera (a webcam "
                         "sees the image plane; it has no usable depth axis)")
    ap.add_argument("--no-clutch", action="store_true",
                    help="pointer moves whenever a hand is tracked. Use this if "
                         "the cursor will not move at all; you lose the ratchet, "
                         "and fist-drag / open-hand lift are unavailable "
                         "(pinch still clicks)")
    ap.add_argument("--clutch-deg", type=float, default=None,
                    help="how far the palm may tilt and still hold the clutch "
                         "(default 30). Raise it if the cursor will not move")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="sensitivity multiplier; 2 = twice as fast, 0.5 = half")
    ap.add_argument("--cutoff", type=float, default=None,
                    help="1 euro filter floor in Hz. Lower = smoother when "
                         "still but laggier; raise it if the cursor feels like "
                         "syrup, lower it if it shivers at rest")
    ap.add_argument("--beta", type=float, default=None,
                    help="1 euro speed coefficient. Raise it if fast motion "
                         "lags behind the hand")
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
    if args.tutorial:
        if args.source != "camera":
            print("--tutorial requires --source camera", file=sys.stderr)
            return 2
        args.preview = True
        args.no_commands = False
        if args.backend != "dry-run":
            print("tutorial is a practice room: forcing --backend dry-run",
                  file=sys.stderr)
            args.backend = "dry-run"
        if args.duration == 120.0:      # the untouched default is too short here
            args.duration = 600.0
    resolve_source_defaults(args)

    commands_on = args.source == "camera" and not args.no_commands
    if args.source == "camera":
        source = CameraSource(camera=args.camera, preview=args.preview,
                              hand=args.hand, two_hands=commands_on)
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
    # User flags win over both the Leap defaults and the camera retune.
    if args.cutoff is not None:
        mapping.pointer_min_cutoff = args.cutoff
    if args.beta is not None:
        mapping.pointer_beta = args.beta
    engine = GestureEngine(gesture_cfg)
    direct = DirectDriver(backend, mapping)
    engine.subscribe(direct.on_intent)

    command_engine = None
    if commands_on:
        from .commands import CommandEngine
        command_engine = CommandEngine(hand=args.hand,
                                       pinch_on_mm=gesture_cfg.pinch_on_mm)
        shortcuts = ShortcutDriver(backend, pane_action=args.pane)
        command_engine.subscribe(shortcuts.on_command)
        command_engine.subscribe(
            lambda e: print(f"[command] {e.command.value} {e.data or ''}",
                            file=sys.stderr))

    tracker = None
    if args.tutorial:
        from .tutorial import TutorialTracker
        tracker = TutorialTracker()
        engine.subscribe(tracker.on_intent)
        if command_engine is not None:
            command_engine.subscribe(tracker.on_command)

    last = {"intent": "-"}

    def trace(event):
        if event.intent is not Intent.POINT_MOVE:
            last["intent"] = event.intent.value
        if event.intent is not Intent.POINT_MOVE or args.verbose:
            print(f"{event.intent.value}", file=sys.stderr)

    engine.subscribe(trace)

    if command_engine is not None:
        def routed(snap):
            # Commands see everything (TOGGLE is the way back in); the cursor
            # engine sees an empty snapshot while paused OR while a command
            # pose is armed — releasing held buttons and parking the pointer,
            # so framing a pane cannot also steer the cursor. Resuming is
            # jump-free: the next clutch re-syncs from the real cursor.
            command_engine.on_snapshot(snap)
            ok = command_engine.enabled and not command_engine.busy
            engine.on_snapshot(snap if ok else Snapshot())
        source.subscribe(routed)
    else:
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
        if commands_on:
            print("  commands (hold the pose until the ring fills, then release):")
            print("    frame a rectangle with both hands  = new pane there")
            print("    OK sign (pinch, 3 fingers up)      = Mission Control")
            print("    ILY sign (thumb+index+pinky) 1s    = pause / resume")
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
            lag_warned_at = time.monotonic() + 4.0
            while deadline is None or time.monotonic() < deadline:
                if cv2 is not None:
                    frame_bgr = source.preview_frame
                    if frame_bgr is not None:
                        _overlay_status(cv2, frame_bgr, engine,
                                        source.latest.get(args.hand),
                                        last["intent"],
                                        getattr(source, "stats", None))
                        if command_engine is not None:
                            _overlay_commands(cv2, frame_bgr,
                                              command_engine.overlay)
                            if not command_engine.enabled and tracker is None:
                                cv2.putText(frame_bgr, "PAUSED (ILY pose 1s resumes)",
                                            (8, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                            0.7, (0, 0, 230), 2, cv2.LINE_AA)
                        if tracker is not None:
                            from . import tutorial
                            tutorial.draw(cv2, frame_bgr, tracker)
                        cv2.imshow(win, frame_bgr)
                    if cv2.waitKey(33) & 0xFF in (27, ord("q")):
                        print("\npreview closed")
                        break
                else:
                    time.sleep(0.2)
                if time.monotonic() > warned_at:
                    warn_if_stuck()
                    warned_at = time.monotonic() + 8.0
                stats = getattr(source, "stats", None)
                if (stats and stats["fps"] and not stats["realtime"]
                        and time.monotonic() > lag_warned_at):
                    print(f"  tracking below realtime (detect "
                          f"{stats['detect_ms']:.0f}ms > frame budget at "
                          f"{stats['fps']:.0f}fps) — cursor will lag",
                          file=sys.stderr)
                    lag_warned_at = time.monotonic() + 5.0
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
