"""Entry point. Defaults to dry-run — taking over the cursor is opt-in."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import (
    CameraSource, Config, DirectDriver, GestureEngine, Intent, LeapSource,
    Mapping, ShortcutDriver, Snapshot, make_backend, server_status,
    tune_for_camera,
)
from .camera import camera_names, find_camera_index, pick_camera_index
from .guard import Guard


def _overlay_status(cv2, bgr, engine, tracked, last_intent: str,
                    stats: dict | None = None, command_engine=None) -> None:
    """Engine truth, not camera truth: what the gesture layer thinks is happening."""
    if tracked is None:
        status, color = "NO HAND", (0, 0, 230)
    elif command_engine is not None and command_engine.busy:
        # busy blanks the cursor engine's snapshots; without this branch the
        # line below would blame the clutch ("LIFTED") for a parked cursor
        # that a command hold actually owns.
        label = command_engine.overlay.get("label") or "command"
        status = f"COMMAND HOLD  ({label} owns the input - cursor parked)"
        color = (255, 200, 0)
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


def _play(sound: str) -> None:
    """Best-effort, non-blocking system sound (macOS)."""
    import subprocess
    try:
        subprocess.Popen(["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _chime(resumed: bool) -> None:
    """Audible pause/resume cue."""
    _play("Glass" if resumed else "Bottle")


def _mic_desync_fix(command_engine) -> callable:
    """Closure for ShortcutDriver.on_forced_release: when the dictation
    watchdog force-releases Option, the pose state machine must agree the mic
    is off — otherwise the next thumbs-up 'stops' a mic that is already
    closed, and the one after that opens it silently. Runs on the watchdog's
    Timer thread: bool assignment is atomic under the GIL, and _play is a
    fire-and-forget Popen, so this stays thread-safe by staying tiny."""
    def _fix() -> None:
        command_engine._dictating = False
        _play("Pop")            # the mic-off cue _announce already uses
    return _fix


class _StallWatch:
    """A stalled frame stream never delivers the empty snapshot that releases
    held input — the capture thread is the only caller of on_snapshot, so its
    death (or a wedged device) strands a held mouse button. The guard process
    only fires on process death and the driver watchdog only covers Option;
    this covers the gap from the main loop by watching source.frames."""

    def __init__(self, stall_s: float = 0.5):
        self.stall_s = stall_s
        self._frames: int | None = None
        self._since = 0.0
        self._stalled = False

    def update(self, frames: int, now: float) -> tuple[bool, bool]:
        """(release, warn). release fires once on entering the stalled state;
        warn is suppressed when the stream never advanced at all (the phone
        source legitimately idles before the browser connects)."""
        if self._frames is None or frames != self._frames:
            self._frames = frames
            self._since = now
            self._stalled = False
            return False, False
        if not self._stalled and now - self._since >= self.stall_s:
            self._stalled = True
            return True, frames > 0
        return False, False


def resolve_source_defaults(args) -> None:
    """Per-source defaults for every axis-and-posture flag the user left unset.

    invert_x is the one that bit: Mapping's default is the MEASURED Leap truth
    (invert_x=True, confirmed by use 2026-08-12), but building Mapping straight
    from a store_true argparse default silently clobbered it with False on
    every default run — the Leap shipped mirrored. Resolution now happens here,
    per source, and only for flags the user did not pass.
    """
    if args.plane is None:
        args.plane = "xy" if args.source != "leap" else "xz"
    if args.point is None:
        args.point = "knuckles" if args.source != "leap" else "index"
    if args.invert_x is None:
        args.invert_x = args.source == "leap"
    if args.invert_z is None:
        args.invert_z = False
    if args.drag is None:
        args.drag = args.source == "leap"
    if args.map is None:
        # Touch is the camera-side framework: people address a screen as
        # fixed points (updated by use 2026-08-18). The Leap keeps the
        # measured relative ratchet — its reachable volume never fit absolute.
        args.map = "relative" if args.source == "leap" else "touch"


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
    ap.add_argument("--source", choices=("leap", "camera", "phone"),
                    default="leap",
                    help="leap: the Leap Motion controller. camera: a plain "
                         "webcam through MediaPipe — no Leap hardware needed. "
                         "phone: your phone's camera streamed from its browser "
                         "over WebRTC (open the printed URL in Safari)")
    ap.add_argument("--camera", type=int, default=None,
                    help="camera index for --source camera (default: auto — "
                         "the built-in camera, skipping virtual cameras like "
                         "Camo or OBS)")
    ap.add_argument("--camera-name", default=None, metavar="NAME",
                    help="pick the camera by name substring instead of index, "
                         "e.g. 'iphone' for Continuity Camera or 'camo'")
    ap.add_argument("--list-cameras", action="store_true",
                    help="print attached cameras with their indexes and exit")
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
    ap.add_argument("--no-screen-overlay", action="store_true",
                    help="camera only: don't draw the framed region on the "
                         "screen while holding the finger-frame pose")
    ap.add_argument("--pane", choices=("screenshot", "window", "tab"),
                    default="screenshot",
                    help="what the finger-frame gesture does: screenshot the "
                         "framed region to the clipboard (default), spawn a "
                         "new window placed over it, or open a tab")
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
    ap.add_argument("--drag", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="fist-drag. Default: off for --source camera (pinch "
                         "misreading as a fist made clicking flaky; pinch "
                         "already holds the button, so pinch-and-move still "
                         "drags), on for --source leap (grab_strength is "
                         "clean there)")
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
    ap.add_argument("--map", choices=("touch", "relative", "absolute"),
                    default=None,
                    help="touch (camera default): the screen is a touchscreen "
                         "sheet under your hand — fixed points, the dynamic "
                         "reach box follows overshoot. relative (leap "
                         "default): the clutch ratchet, like a mouse. "
                         "absolute: alias of touch. Fit the box first with "
                         "`python -m leapinput.reach corners`")
    ap.add_argument("--no-reach", action="store_true",
                    help="camera only: ignore the stored reach box and map the "
                         "whole frame, as before `leapinput.reach map` ran")
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
    ap.add_argument("--no-telemetry", action="store_true",
                    help="disable the live diagnostics dashboard + click log")
    ap.add_argument("--telemetry-port", type=int, default=8788,
                    help="localhost port for the telemetry dashboard")
    args = ap.parse_args(argv)

    if args.list_cameras:
        for i, name in enumerate(camera_names()):
            print(f"{i}  {name}")
        return 0
    if args.tutorial:
        if args.source == "leap":
            print("--tutorial requires a camera source", file=sys.stderr)
            return 2
        args.preview = True
        args.no_commands = False
        if args.backend != "dry-run":
            print("tutorial is a practice room: forcing --backend dry-run",
                  file=sys.stderr)
            args.backend = "dry-run"
        if args.duration == 120.0:      # the untouched default is too short here
            args.duration = 600.0
        if args.drag is None:           # the tutorial teaches the fist step
            args.drag = True
    resolve_source_defaults(args)

    if args.map in ("absolute", "touch") and args.source == "leap":
        print("--map absolute needs a camera source (it maps the reach box, "
              "a camera concept)", file=sys.stderr)
        return 2

    tuning = None
    if args.source != "leap":
        import dataclasses
        from .camera import Tuning
        tuning = Tuning.load()
        if args.no_reach:
            tuning = dataclasses.replace(tuning, reach_x0=0.0, reach_y0=0.0,
                                         reach_x1=1.0, reach_y1=1.0)
        if tuning.reach_active:
            zx, zy = tuning.reach_zoom
            print(f"reach box active — zoom {zx:.1f}x/{zy:.1f}x "
                  f"(refit: python -m leapinput.reach map | off: --no-reach)")
        elif args.map in ("absolute", "touch"):
            print("note: --map absolute with no reach box maps the WHOLE "
                  "frame to the screen; fit your comfortable reach first "
                  "with: python -m leapinput.reach map", file=sys.stderr)

    commands_on = args.source != "leap" and not args.no_commands
    if args.source == "camera":
        if args.camera_name is not None:
            try:
                args.camera = find_camera_index(args.camera_name)
            except RuntimeError as e:
                print(e, file=sys.stderr)
                return 2
        elif args.camera is None:
            args.camera = pick_camera_index()
        names = camera_names()
        label = names[args.camera] if args.camera < len(names) else "?"
        source = CameraSource(camera=args.camera, preview=args.preview,
                              hand=args.hand, two_hands=commands_on,
                              tuning=tuning)
        print(f"MediaPipe HandLandmarker — camera {args.camera} "
              f"({label}, mirrored)")
    elif args.source == "phone":
        from .phonecam import PhoneSource
        source = PhoneSource(preview=args.preview, hand=args.hand,
                             two_hands=commands_on, tuning=tuning)
        print("MediaPipe HandLandmarker — phone camera over WebRTC (mirrored)")
        print(f"  On the phone, open:  {source.url}")
        print("  (accept the certificate warning once, then tap Start)")
    elif args.preview:
        print("--preview requires a camera source", file=sys.stderr)
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
                         clutch_enabled=not args.no_clutch,
                         grab_enabled=args.drag)
    if args.clutch_deg is not None:
        gesture_cfg.clutch_on_deg = args.clutch_deg
        gesture_cfg.clutch_off_deg = args.clutch_deg + 15.0
        gesture_cfg.clutch_on_deg_xy = args.clutch_deg
        gesture_cfg.clutch_off_deg_xy = args.clutch_deg + 15.0
    mapping = Mapping(plane=args.plane, invert_x=args.invert_x,
                      invert_z=args.invert_z, gain_scale=args.gain,
                      tracking_point=args.point,
                      absolute=args.map in ("absolute", "touch"))
    if args.source != "leap":
        tune_for_camera(gesture_cfg, mapping, tuning)
    # User flags win over both the Leap defaults and the camera retune.
    if args.cutoff is not None:
        mapping.pointer_min_cutoff = args.cutoff
    if args.beta is not None:
        mapping.pointer_beta = args.beta
    engine = GestureEngine(gesture_cfg)
    direct = DirectDriver(backend, mapping)
    engine.subscribe(direct.on_intent)

    command_engine = None
    screen_overlay = None
    shortcuts = None
    if commands_on:
        from .commands import CommandEngine
        command_engine = CommandEngine(hand=args.hand,
                                       pinch_on_mm=gesture_cfg.pinch_on_mm)
        shortcuts = ShortcutDriver(backend, pane_action=args.pane)
        command_engine.subscribe(shortcuts.on_command)
        # Keep the pose state machine honest when the dictation watchdog
        # force-releases Option behind its back (plain attribute assignment:
        # harmless if the driver never fires it).
        shortcuts.on_forced_release = _mic_desync_fix(command_engine)

        # Cmd+Shift+4 shows you the region you're selecting; the finger-frame
        # must too — on the real screen, because the always-on session has no
        # preview window. (The overlay window is excluded from captures, so it
        # never appears in its own frame shot.)
        if sys.platform == "darwin" and not args.no_screen_overlay:
            from .overlay import ScreenOverlay
            screen_overlay = ScreenOverlay()

        # `leapctl status` (and the menu bar icon) read pause state from a
        # flag file — a signal can ask "toggle" but not "which way is it now".
        run_dir = Path(os.environ.get("LEAPINPUT_RUN_DIR",
                                      Path.home() / ".leapinput"))
        paused_flag = run_dir / "paused"

        def _write_paused(enabled: bool) -> None:
            try:
                if enabled:
                    paused_flag.unlink(missing_ok=True)
                else:
                    run_dir.mkdir(parents=True, exist_ok=True)
                    paused_flag.touch()
            except OSError:
                pass    # cosmetic state; never let it take down the session

        _write_paused(True)  # a fresh session always starts unpaused

        def _announce(e):
            print(f"[command] {e.command.value} {e.data or ''}", file=sys.stderr)
            # Headless runs have no overlay, so state changes must be HEARD:
            # a silent pause is indistinguishable from "it broke".
            if e.command.value == "toggle":
                _chime(resumed=e.data.get("enabled", True))
                _write_paused(e.data.get("enabled", True))
            elif e.command.value == "dictate":
                # The mic state must be HEARD: the pose is a toggle, and a
                # wrong guess about which state you're in means either talking
                # to nothing or Option held while you type.
                _play("Tink" if e.data.get("active") else "Pop")
        command_engine.subscribe(_announce)

    # Diagnostics: every select.down / grab.down is recorded with its
    # surrounding signal window, and a localhost dashboard shows the live
    # pinch trace with a button to tag phantom clicks — evidence first, the
    # lesson of the 352-click phantom-pinch hunt. Passive subscriber; it can
    # lose data but never take down the control loop.
    telemetry = None
    if not args.no_telemetry:
        from .telemetry import Telemetry, TelemetryServer
        tele_dir = Path(os.environ.get("LEAPINPUT_RUN_DIR",
                                       Path.home() / ".leapinput"))
        telemetry = Telemetry(engine, command_engine, direct=direct,
                              source=source, hand=args.hand,
                              pinch_on_mm=gesture_cfg.pinch_on_mm,
                              pinch_off_mm=gesture_cfg.pinch_off_mm,
                              out_dir=tele_dir / "telemetry")
        engine.subscribe(telemetry.on_intent)
        tele_url = TelemetryServer(telemetry, port=args.telemetry_port).start()
        if tele_url:
            print(f"telemetry dashboard: {tele_url}  "
                  "(P tags the last click as a phantom)")
        else:
            print(f"telemetry port {args.telemetry_port} taken — dashboard "
                  "off, click log still recording", file=sys.stderr)

    # Signal plumbing, asserted here and RE-asserted periodically in the main
    # loop, because two things sabotage it at the OS level:
    #   - `leapctl on` launches us via `nohup ... &` from a non-interactive
    #     shell, which hands us SIGINT as SIG_IGN — and Python honors an
    #     inherited ignore, so `leapctl off` would do nothing and the session
    #     (and the camera light) would outlive the switch.
    #   - something in camera/mediapipe startup resets SIGUSR1's sigaction to
    #     SIG_IGN behind Python's back (verified by reading sigaction from the
    #     live process: OS said SIG_IGN while Python still showed the handler),
    #     which silently killed `leapctl pause` and the menu bar's pause.
    # signal.signal() always overwrites the OS disposition, so re-asserting is
    # a complete cure, and at a few syscalls per second it is free.
    import signal

    def _flip(signum, frame_):
        # SIGUSR1 = pause/resume from outside — the ILY pose's terminal-side
        # twin, used by `leapctl pause` and the menu bar switch.
        command_engine.enabled = not command_engine.enabled
        _chime(resumed=command_engine.enabled)
        _write_paused(command_engine.enabled)
        print(f"[command] toggle {{'enabled': {command_engine.enabled}}} "
              "(signal)", file=sys.stderr)

    def _term(signum, frame_):
        raise KeyboardInterrupt

    def assert_signal_handlers() -> None:
        try:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            signal.signal(signal.SIGTERM, _term)
            if command_engine is not None:
                signal.signal(signal.SIGUSR1, _flip)
        except ValueError:
            pass        # not on the main thread; leapctl escalates to SIGKILL

    assert_signal_handlers()

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
            if screen_overlay is not None:
                screen_overlay.update(command_engine.overlay)
            ok = command_engine.enabled and not command_engine.busy
            engine.on_snapshot(snap if ok else Snapshot())
            if telemetry is not None:
                # After the engines, so sampled Schmitt states describe THIS
                # frame; the real snap, so a blanked cursor engine still
                # leaves the hand visible in the click log.
                telemetry.on_snapshot(snap)
        source.subscribe(routed)
    elif telemetry is not None:
        def observed(snap):
            engine.on_snapshot(snap)
            telemetry.on_snapshot(snap)
        source.subscribe(observed)
    else:
        source.subscribe(engine.on_snapshot)

    w, h = backend.screen
    print(f"screen {w:.0f}x{h:.0f} | backend={args.backend} | hand={args.hand}")
    if args.backend == "quartz":
        print("\n  *** DRIVING THE REAL CURSOR ***")
        print("  Drop your hand to the desk to release it — the device stops")
        print("  tracking entirely, so that is a hard disengage, not a threshold.")
        if args.source != "leap":
            print("  Face the camera; the view is mirrored — move right, cursor")
            print("  goes right. Hand out of view = hard release, like the Leap.")
        elif args.plane == "xy":
            print("  Hold your hand UPRIGHT, palm facing the screen, as if drawing")
            print("  on it. Raise/lower to move up/down; height is the cursor axis.")
        else:
            print("  Hold your hand FLAT over the device, palm down.")
        if mapping.absolute:
            print("  ABSOLUTE mapping: the reach box IS the screen — point at a")
            print("  spot to put the cursor there; no clutching needed.")
        if args.drag:
            print("  point = move   pinch = click   fist = drag   open hand = lift")
        else:
            print("  point = move   pinch = click (hold it + move = drag)   "
                  "open hand = lift")
        if commands_on:
            pane_label = {"screenshot": "screenshot that region -> clipboard",
                          "window": "new window there",
                          "tab": "new tab there"}[args.pane]
            free = "left" if args.hand == "Right" else "right"
            print("  commands (hold the pose until the ring fills, then release):")
            print(f"  {args.hand.lower()} (cursor) hand:")
            print(f"    frame a rectangle with both hands  = {pane_label}")
            print("    OK sign (pinch, 3 fingers up)      = Mission Control")
            print("    ILY sign (thumb+index+pinky) 1.5s  = pause / resume"
                  " (fires as the ring fills)")
            print("    thumbs-up ~0.6s                    = mic ON (chime); "
                  "thumbs-up again = mic OFF")
            print(f"  {free} (free) hand:")
            print("    pinch and hold = Cmd+C    V sign = Cmd+V    "
                  "ILY = Enter")
        if args.duration:
            print(f"  auto-stops after {args.duration:.0f}s")
    where = ("into the camera view" if args.source != "leap"
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
        # The heavy object graphs (mediapipe, cv2, aiortc) are built; per-frame
        # garbage dies by refcount, so cyclic GC only contributes surprise
        # 10-50ms pauses mid-gesture. Freeze what exists, then make gen-0
        # sweeps rare. (Not disabled outright: aiortc's asyncio does create
        # reference cycles.)
        import gc
        gc.collect()
        gc.freeze()
        gc.set_threshold(50_000, 10, 10)
        try:
            warned_at = time.monotonic() + 4.0
            lag_warned_at = time.monotonic() + 4.0
            sig_assert_at = time.monotonic() + 2.0
            stall_watch = _StallWatch()
            while deadline is None or time.monotonic() < deadline:
                if cv2 is not None:
                    frame_bgr = source.preview_frame
                    if frame_bgr is not None:
                        _overlay_status(cv2, frame_bgr, engine,
                                        source.latest.get(args.hand),
                                        last["intent"],
                                        getattr(source, "stats", None),
                                        command_engine)
                        if command_engine is not None:
                            _overlay_commands(cv2, frame_bgr,
                                              command_engine.overlay)
                            if not command_engine.enabled and tracker is None:
                                cv2.putText(frame_bgr, "PAUSED (ILY pose 1.5s resumes)",
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
                if time.monotonic() > sig_assert_at:
                    # camera/mediapipe startup clobbers SIGUSR1 to SIG_IGN at
                    # the C level (see the signal block above): take it back.
                    assert_signal_handlers()
                    sig_assert_at = time.monotonic() + 2.0
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
                release, stall_warn = stall_watch.update(source.frames,
                                                         time.monotonic())
                if release:
                    # Idempotent: Schmitt.force_off emits nothing when nothing
                    # is held, and the same call runs in the finally below.
                    engine.on_snapshot(Snapshot())
                    if stall_warn:
                        print("  frame stream stalled — released held input",
                              file=sys.stderr)
            else:
                print(f"\nauto-stopped after {args.duration:.0f}s")
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            # Never exit holding a button — that would strand the mouse down and
            # leave the machine selecting everything the user touches.
            engine.on_snapshot(Snapshot())
            if shortcuts is not None:
                # Never exit holding Option — a stuck system-wide modifier
                # breaks typing everywhere, not just here.
                shortcuts.release_dictation()
            if screen_overlay is not None:
                screen_overlay.close()
            if guard:
                guard.stop()
            if cv2 is not None:
                cv2.destroyAllWindows()
                cv2.waitKey(1)          # let Cocoa actually close the window
    print(f"{source.frames} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
