"""Reach: optimize the screen mapping for a camera FIXED in place.

A phone propped on a stand does not move, so the geometry between your resting
hand and the frame is stable — and measurable. The whole frame is the wrong
control surface for that setup: the comfortable reach covers only part of it,
which is exactly the "stretching way too far" and "out of bounds" failure. The
fix is a REACH BOX: the sub-rectangle of the frame your hand actually roams,
mapped to the full virtual plane (camera.Tuning.reach). Small comfortable
motion covers everything; overreach clamps at the box edge instead of losing
tracking.

    python -m leapinput.reach map              # roam comfortably -> fit -> save
    python -m leapinput.reach map --source phone
    python -m leapinput.reach test             # viewport check: the screen
                                               # drawn INSIDE the box, live
    python -m leapinput.reach show             # print the stored box
    python -m leapinput.reach clear            # back to whole-frame mapping

Fitting rule, same philosophy as calibrate.py: measure a distribution, not a
guess. Record where the knuckle centroid roams while the user deliberately
moves everywhere COMFORTABLE, take the p2..p98 envelope, pad it, and that is
the box. A box fitted from a lazy roam is caught by the min-size guard, and a
tiny roam that would produce absurd magnification is widened to the zoom cap,
loudly.
"""

from __future__ import annotations

import argparse
import dataclasses
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from .camera import (CameraSource, Tuning, camera_names, find_camera_index,
                     pick_camera_index, plane_norm)

ROAM_SECONDS = 12.0
READY_SECONDS = 3.0

# Fit guards. min_size is normalized frame units: a roam spanning under 16% of
# the frame on an axis is a hand that hovered, not a measured reach — refitting
# beats silently saving garbage. max_zoom caps magnification: past ~4x, landmark
# noise (1-3px) magnified onto the plane rivals deliberate slow motion.
FIT_P_LO, FIT_P_HI = 0.02, 0.98
FIT_MARGIN = 0.10           # padding per side, as a fraction of the fitted span
MIN_SPAN = 0.16
MAX_ZOOM = 4.0
MIN_FRAMES = 60


# --- fitting (pure, for tests) -------------------------------------------------

def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    i = (len(s) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _cap_zoom(lo: float, hi: float, name: str,
              report: list[str]) -> tuple[float, float]:
    """Widen a span to the zoom cap around its centre, shifted into frame."""
    if (hi - lo) < 1.0 / MAX_ZOOM:
        mid = (lo + hi) / 2.0
        half = 0.5 / MAX_ZOOM
        lo, hi = mid - half, mid + half
        shift = max(0.0, -lo) - max(0.0, hi - 1.0)
        lo, hi = lo + shift, hi + shift
        report.append(f"  {name}: widened to the {MAX_ZOOM:.0f}x zoom cap "
                      f"(smaller than this, landmark noise rivals slow motion)")
    return lo, hi


def _axis(values: list[float], report: list[str], name: str) -> tuple[float, float]:
    lo, hi = _pct(values, FIT_P_LO), _pct(values, FIT_P_HI)
    span = hi - lo
    if span < MIN_SPAN:
        raise ValueError(
            f"{name} roam spanned only {span * 100:.0f}% of the frame "
            f"(need {MIN_SPAN * 100:.0f}%) — roam wider: sweep every corner "
            f"you can reach WITHOUT stretching, then refit")
    pad = FIT_MARGIN * span
    lo, hi = max(0.0, lo - pad), min(1.0, hi + pad)
    return _cap_zoom(lo, hi, name, report)


def fit_reach(points: list[tuple[float, float]]
              ) -> tuple[tuple[float, float, float, float], list[str]]:
    """Roamed (x, y) normalized frame coords -> (box, human-readable report)."""
    if len(points) < MIN_FRAMES:
        raise ValueError(
            f"only {len(points)} frames had a tracked hand — keep the hand in "
            f"view for the whole recording, then refit")
    report: list[str] = [f"fitted from {len(points)} frames"]
    x0, x1 = _axis([p[0] for p in points], report, "x")
    y0, y1 = _axis([p[1] for p in points], report, "y")
    zx, zy = 1.0 / (x1 - x0), 1.0 / (y1 - y0)
    report.append(f"  box x {x0:.2f}..{x1:.2f}  y {y0:.2f}..{y1:.2f} "
                  f"({(x1 - x0) * 100:.0f}% x {(y1 - y0) * 100:.0f}% of frame)")
    report.append(f"  zoom {zx:.1f}x horizontal, {zy:.1f}x vertical — the same "
                  f"hand travel now moves the cursor that much further")
    if max(zx / zy, zy / zx) > 1.8:
        report.append("  note: your reach is strongly lopsided; vertical and "
                      "horizontal will feel different. That matches your hand, "
                      "not a bug.")
    return (x0, y0, x1, y1), report


def corner_box(a: tuple[float, float], b: tuple[float, float],
               pad: float = 0.03
               ) -> tuple[tuple[float, float, float, float], list[str]]:
    """Two deliberately-placed corner points -> (box, report).

    The DIRECT alternative to the roam fit: the user says exactly where the
    hand should live by holding it at two opposite corners. The pad extends
    slightly OUTWARD so the screen edge is reachable at the exact spot the
    hand was held, not a hair beyond it. Same zoom cap as the roam fit; a
    degenerate pair (corners nearly on top of each other) is an error, not a
    16x-zoom surprise.
    """
    report: list[str] = []
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    if (x1 - x0) < 0.08 or (y1 - y0) < 0.08:
        raise ValueError("the two corners are nearly on top of each other — "
                         "hold them at opposite corners of where you want "
                         "your hand to work")
    x0, x1 = max(0.0, x0 - pad), min(1.0, x1 + pad)
    y0, y1 = max(0.0, y0 - pad), min(1.0, y1 + pad)
    x0, x1 = _cap_zoom(x0, x1, "x", report)
    y0, y1 = _cap_zoom(y0, y1, "y", report)
    zx, zy = 1.0 / (x1 - x0), 1.0 / (y1 - y0)
    report.append(f"  box x {x0:.2f}..{x1:.2f}  y {y0:.2f}..{y1:.2f} "
                  f"({(x1 - x0) * 100:.0f}% x {(y1 - y0) * 100:.0f}% of frame)")
    report.append(f"  zoom {zx:.1f}x horizontal, {zy:.1f}x vertical")
    return (x0, y0, x1, y1), report


def save_reach(box: tuple[float, float, float, float],
               path: Optional[Path] = None,
               ref_span_img: Optional[float] = None) -> Path:
    """Merge the box (and, when measured, the reference working distance)
    into camera_tuning.json without touching pose thresholds."""
    x0, y0, x1, y1 = box
    kwargs = dict(reach_x0=x0, reach_y0=y0, reach_x1=x1, reach_y1=y1)
    if ref_span_img is not None:
        kwargs["ref_span_img"] = ref_span_img
    tuning = dataclasses.replace(Tuning.load(path), **kwargs)
    return tuning.save(path)


def _median(values: list[float]) -> float:
    s = sorted(values)
    return s[len(s) // 2]


# Active-panel width of the 14.2-inch MacBook Pro (1512x982 logical) — the
# display this setup maps onto, for the touch-scale readout below.
MBP14_WIDTH_CM = 30.41


def physical_summary(tuning: Tuning) -> Optional[str]:
    """Estimated physical width of the reach box, from the calibrated span.

    Apparent knuckle span at the working distance is the yardstick: box
    width / span = box size in hand-spans, converted via the nominal span.
    On a 14.2-inch MacBook the line also reports the touch SCALE — how the
    box's physical size compares to the physical panel; near 1.0 means hand
    travel maps ~1:1 onto glass, the most literal touchscreen feel."""
    if not (tuning.reach_active and tuning.ref_span_img):
        return None
    from .actions import active_screen_size
    x0, _, x1, _ = tuning.reach
    span = tuning.span_mm_effective
    width_cm = (x1 - x0) / tuning.ref_span_img * span / 10.0
    basis = ("your measured" if tuning.hand_span_mm else "assuming a")
    line = (f"box ~{width_cm:.0f}cm wide in hand space "
            f"({basis} {span:.0f}mm knuckle span)")
    # The panel comparison only means anything on the panel itself — read the
    # display the cursor is on, since that is the one being mapped.
    if active_screen_size()[0] == 1512.0:
        line += (f" — {width_cm / MBP14_WIDTH_CM:.2f}x the 14.2-inch panel's "
                 f"{MBP14_WIDTH_CM:.1f}cm: touch scale")
    return line


# --- source plumbing ------------------------------------------------------------

def _build_source(args, tuning: Tuning, two_hands: bool = False) -> CameraSource:
    if args.source == "phone":
        from .phonecam import PhoneSource
        source = PhoneSource(preview=True, hand=args.hand, tuning=tuning,
                             two_hands=two_hands)
        print(f"  On the phone, open:  {source.url}")
        print("  (accept the certificate warning once, then tap Start)")
        return source
    if args.camera_name is not None:
        camera = find_camera_index(args.camera_name)
    elif args.camera is not None:
        camera = args.camera
    else:
        camera = pick_camera_index()
    names = camera_names()
    label = names[camera] if camera < len(names) else "?"
    print(f"camera {camera} ({label}, mirrored)")
    return CameraSource(camera=camera, preview=True, hand=args.hand,
                        tuning=tuning, two_hands=two_hands)


def _neutral(tuning: Tuning) -> Tuning:
    """The same tuning with the reach box removed — capture must record RAW
    frame coordinates, or a stored box would warp the measurement of itself."""
    return dataclasses.replace(tuning, reach_x0=0.0, reach_y0=0.0,
                               reach_x1=1.0, reach_y1=1.0)


# --- roam capture ---------------------------------------------------------------

def roam(args) -> int:
    import cv2

    source = _build_source(args, _neutral(Tuning.load()))
    state = {"recording": False}
    points: list[tuple[float, float]] = []
    spans: list[float] = []     # apparent knuckle span = the working distance

    def on_snapshot(snap) -> None:      # capture thread; keep it short
        if not state["recording"]:
            return
        frame = snap.get(args.hand)
        if frame is not None:
            points.append(plane_norm(frame.track_point("knuckles")))
            sig = source.latest_signals.get(args.hand)
            if sig is not None and sig.span_img:
                spans.append(sig.span_img)

    source.subscribe(on_snapshot)
    win = "leapinput reach (q aborts)"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    print(f"\nRoam your {args.hand.lower()} hand for {args.seconds:.0f}s: sweep "
          f"every corner you can reach COMFORTABLY — never stretch. The box is "
          f"fitted to what you show it.")

    aborted = False
    with source.open():
        # Wait for a tracked hand before any clock starts: the phone connects
        # on its own schedule (open the URL, tap Start), and a countdown that
        # runs while the user is still tapping records an empty roam.
        while not aborted and source.latest.get(args.hand) is None:
            bgr = source.preview_frame
            if bgr is not None:
                h, w = bgr.shape[:2]
                cv2.putText(bgr, f"show your {args.hand.lower()} hand to begin",
                            (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 200, 255), 2, cv2.LINE_AA)
                cv2.imshow(win, bgr)
            if cv2.waitKey(30) & 0xFF in (27, ord("q")):
                aborted = True
        for recording, dur in ((False, READY_SECONDS), (True, args.seconds)):
            state["recording"] = recording
            end = time.monotonic() + dur
            while time.monotonic() < end and not aborted:
                bgr = source.preview_frame
                if bgr is not None:
                    _roam_banner(cv2, bgr, recording, end - time.monotonic(),
                                 points)
                    cv2.imshow(win, bgr)
                if cv2.waitKey(30) & 0xFF in (27, ord("q")):
                    aborted = True
        state["recording"] = False
    cv2.destroyAllWindows()
    cv2.waitKey(1)

    if aborted:
        print("aborted — nothing written")
        return 1
    try:
        box, report = fit_reach(points)
    except ValueError as e:
        print(f"no fit: {e}", file=sys.stderr)
        return 1
    print("\n".join(report))
    ref = _median(spans) if spans else None
    if ref:
        print(f"  working distance captured (ref span {ref:.3f}) — sensitivity "
              f"now stays constant as you move nearer/farther")
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    out = save_reach(box, ref_span_img=ref)
    print(f"\nwrote {out}")
    line = physical_summary(Tuning.load())
    if line:
        print(f"  {line}")
    print("Every camera/phone session now maps this box to the screen.")
    print("Check it live:  python -m leapinput.reach test"
          + (" --source phone" if args.source == "phone" else ""))
    return 0


def _roam_banner(cv2, bgr, recording: bool, left: float,
                 points: list[tuple[float, float]]) -> None:
    h, w = bgr.shape[:2]
    cv2.rectangle(bgr, (0, 0), (w, 52), (30, 30, 30), -1)
    if recording:
        cv2.circle(bgr, (18, 22), 8, (0, 0, 230), -1)
        head, color = f"ROAM  {left:3.1f}s   {len(points)} frames", (0, 0, 230)
    else:
        head, color = f"get ready  {left:3.1f}s", (0, 200, 255)
    cv2.putText(bgr, head, (34, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
                cv2.LINE_AA)
    cv2.putText(bgr, "sweep everywhere comfortable - do NOT stretch",
                (34, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1,
                cv2.LINE_AA)
    # The trail is the measurement: seeing the coverage grow tells the user
    # which corners they have not shown yet.
    for x, y in points[-2000:]:
        cv2.circle(bgr, (int(x * w), int(y * h)), 2, (0, 200, 255), -1)
    if len(points) >= MIN_FRAMES:
        try:
            (x0, y0, x1, y1), _ = fit_reach(points)
            cv2.rectangle(bgr, (int(x0 * w), int(y0 * h)),
                          (int(x1 * w), int(y1 * h)), (0, 200, 0), 2)
        except ValueError:
            pass


# --- the hand as the ChArUco board ----------------------------------------------

HAND_MEASURE_S = 6.0


def hand(args) -> int:
    """Calibrate the hand's REAL size — the fiducial every frame contains.

    --span-mm takes a ruler measurement (across the back of the hand, centre
    of the index knuckle to centre of the pinky knuckle) — the gold standard.
    Without it, the MediaPipe world-landmark span is medianed over a few
    seconds of an open, flat, camera-facing hand: per-frame world scale
    jitters by tens of percent, but the median over hundreds of frames is a
    serviceable estimate. Either way the value turns every physical readout
    (box size, touch scale) from an assumption into a measurement.
    """
    if args.span_mm is not None:
        if not 30.0 <= args.span_mm <= 120.0:
            print(f"{args.span_mm}mm is outside any plausible knuckle span "
                  f"(30-120mm) — measure index-MCP to pinky-MCP", file=sys.stderr)
            return 2
        out = dataclasses.replace(Tuning.load(),
                                  hand_span_mm=args.span_mm).save()
        print(f"hand span {args.span_mm:.0f}mm (ruler) -> {out}")
        line = physical_summary(Tuning.load())
        if line:
            print(line)
        return 0

    import cv2
    source = _build_source(args, _neutral(Tuning.load()))
    win = "leapinput reach hand (q aborts)"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    print(f"\nHold your {args.hand.lower()} hand OPEN and FLAT, fingers "
          f"spread, palm to the camera, for {HAND_MEASURE_S:.0f}s.")
    spans: list[float] = []
    aborted = False
    end = None
    with source.open():
        while not aborted:
            frame = source.latest.get(args.hand)
            sig = source.latest_signals.get(args.hand)
            open_flat = (frame is not None and all(frame.extended)
                         and sig is not None and sig.span_mm > 0.0)
            if open_flat:
                if end is None:
                    end = time.monotonic() + HAND_MEASURE_S
                spans.append(sig.span_mm)
            bgr = source.preview_frame
            if bgr is not None:
                left = 0.0 if end is None else max(0.0, end - time.monotonic())
                msg = ("open your hand flat, fingers spread" if end is None
                       else f"measuring  {left:3.1f}s   {len(spans)} frames")
                cv2.putText(bgr, msg, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                            (0, 200, 255), 2, cv2.LINE_AA)
                cv2.imshow(win, bgr)
            if cv2.waitKey(30) & 0xFF in (27, ord("q")):
                aborted = True
            if end is not None and time.monotonic() >= end:
                break
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    if aborted or len(spans) < 60:
        print("aborted or too few frames — nothing written")
        return 1
    span = _median(spans)
    out = dataclasses.replace(Tuning.load(), hand_span_mm=span).save()
    print(f"hand span ~{span:.0f}mm (model estimate, {len(spans)} frames) "
          f"-> {out}")
    print("  (a ruler across the back of the hand is more accurate: "
          "rerun with --span-mm)")
    line = physical_summary(Tuning.load())
    if line:
        print(line)
    return 0


# --- corner placement: say exactly where the hand should live -------------------

CORNER_HOLD_S = 1.2         # stillness that commits a corner
CORNER_STILL_R = 0.035      # normalized radius that still counts as "still"
CORNER_CLEAR_R = 0.12       # must move this far from a corner before the next


def corners(args) -> int:
    import cv2

    source = _build_source(args, _neutral(Tuning.load()))
    win = "leapinput reach corners (q aborts)"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    print(f"\nPlace your {args.hand.lower()} hand where you WANT it to work: "
          f"first the TOP-LEFT corner, hold still ~{CORNER_HOLD_S:.0f}s, then "
          f"the BOTTOM-RIGHT corner.")

    captured: list[tuple[float, float]] = []
    spans: list[float] = []     # apparent knuckle span = the working distance
    anchor: Optional[tuple[float, float, float]] = None  # x, y, since
    cleared = True      # must leave the last corner before arming the next
    aborted = False

    with source.open():
        while len(captured) < 2 and not aborted:
            now = time.monotonic()
            frame = source.latest.get(args.hand)
            point = (plane_norm(frame.track_point("knuckles"))
                     if frame is not None else None)
            sig = source.latest_signals.get(args.hand)
            if point is not None and sig is not None and sig.span_img:
                spans.append(sig.span_img)

            if point is None:
                anchor = None
            else:
                if captured and not cleared:
                    dx, dy = (point[0] - captured[-1][0],
                              point[1] - captured[-1][1])
                    if dx * dx + dy * dy >= CORNER_CLEAR_R ** 2:
                        cleared = True
                    anchor = None
                elif (anchor is None
                      or (point[0] - anchor[0]) ** 2
                      + (point[1] - anchor[1]) ** 2 > CORNER_STILL_R ** 2):
                    anchor = (point[0], point[1], now)   # moved: re-anchor
                elif now - anchor[2] >= CORNER_HOLD_S:
                    captured.append((anchor[0], anchor[1]))
                    anchor = None
                    cleared = False

            bgr = source.preview_frame
            if bgr is not None:
                _corner_banner(cv2, bgr, captured, point, anchor, cleared, now)
                cv2.imshow(win, bgr)
            if cv2.waitKey(30) & 0xFF in (27, ord("q")):
                aborted = True
    cv2.destroyAllWindows()
    cv2.waitKey(1)

    if aborted or len(captured) < 2:
        print("aborted — nothing written")
        return 1
    try:
        box, report = corner_box(captured[0], captured[1])
    except ValueError as e:
        print(f"no fit: {e}", file=sys.stderr)
        return 1
    print("\n".join(report))
    ref = _median(spans) if spans else None
    if ref:
        print(f"  working distance captured (ref span {ref:.3f}) — sensitivity "
              f"now stays constant as you move nearer/farther")
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    out = save_reach(box, ref_span_img=ref)
    print(f"\nwrote {out}")
    line = physical_summary(Tuning.load())
    if line:
        print(f"  {line}")
    print("Check it live:  python -m leapinput.reach test"
          + (" --source phone" if args.source == "phone" else ""))
    return 0


def _corner_banner(cv2, bgr, captured, point, anchor, cleared, now) -> None:
    h, w = bgr.shape[:2]
    cv2.rectangle(bgr, (0, 0), (w, 52), (30, 30, 30), -1)
    if point is None:
        head = "show your hand"
    elif captured and not cleared:
        head = "now MOVE toward the bottom-right corner"
    else:
        which = "TOP-LEFT" if not captured else "BOTTOM-RIGHT"
        head = f"hold still at the {which} corner of your work area"
    cv2.putText(bgr, head, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                (0, 200, 255), 2, cv2.LINE_AA)
    for cx, cy in captured:
        p = (int(cx * w), int(cy * h))
        cv2.drawMarker(bgr, p, (0, 200, 0), cv2.MARKER_CROSS, 24, 2)
    if point is not None:
        p = (int(point[0] * w), int(point[1] * h))
        # Stillness ring fills toward commitment, same language as the
        # command holds.
        progress = (min(1.0, (now - anchor[2]) / CORNER_HOLD_S)
                    if anchor is not None else 0.0)
        cv2.ellipse(bgr, p, (16, 16), -90.0, 0.0, 360.0 * progress,
                    (0, 200, 0), 3, cv2.LINE_AA)
        cv2.circle(bgr, p, 4, (0, 255, 255), -1)
        if captured:        # live box preview from corner 1 to the hand
            c = (int(captured[0][0] * w), int(captured[0][1] * h))
            cv2.rectangle(bgr, c, p, (0, 200, 0), 1)


# --- the viewport test front-end ------------------------------------------------

class _ScreenGrab:
    """Latest screenshot of the ACTIVE display as a BGR array, refreshed on a
    daemon thread. This is what makes the test view literal: the actual screen,
    drawn inside the reach box — the 2D viewport floating in the camera's
    world. Active, not main: the box maps onto the screen the cursor is on, so
    move the cursor to the other display and the viewport follows it there.
    Degrades to None (grid fallback) without Screen Recording permission, with
    the fix named once instead of a silent black box."""

    PERIOD_S = 2.0

    def __init__(self):
        self.image = None
        self._path = Path(tempfile.mkdtemp(prefix="leapreach-")) / "screen.jpg"
        self._stop = threading.Event()
        self._warned = False
        self._thread = threading.Thread(target=self._loop, name="screen-grab",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import cv2
        from .actions import active_display
        while not self._stop.is_set():
            try:
                x0, y0, x1, y1 = active_display()
                # -R with the display's GLOBAL rect, not -m: -m is the main
                # display and nothing else, and -D's display numbering is its
                # own ordering, unrelated to CGGetActiveDisplayList's.
                out = subprocess.run(
                    ["screencapture", "-x", "-t", "jpg",
                     f"-R{int(x0)},{int(y0)},{int(x1 - x0)},{int(y1 - y0)}",
                     str(self._path)],
                    capture_output=True, text=True, timeout=10.0)
                img = cv2.imread(str(self._path)) if out.returncode == 0 else None
                self.image = img
                if img is None and not self._warned:
                    self._warned = True
                    print("[reach] screenshot unavailable — grant Screen "
                          "Recording to this terminal (System Settings > "
                          "Privacy & Security) for the live screen in the "
                          "box; showing a grid instead", file=sys.stderr)
            except Exception:
                self.image = None
            self._stop.wait(self.PERIOD_S)

    def stop(self) -> None:
        self._stop.set()


def _draw_viewport(cv2, bgr, tuning: Tuning, box, frame, screen_img) -> None:
    """The screen (or a grid) inside the reach box, plus the mapped cursor.
    `box` is the EFFECTIVE box — the palm-floating one when that mode is on."""
    import numpy as np
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = box
    bx0, by0 = int(x0 * w), int(y0 * h)
    bx1, by1 = int(x1 * w), int(y1 * h)
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)

    if screen_img is not None:
        patch = cv2.resize(screen_img, (bw, bh), interpolation=cv2.INTER_AREA)
        roi = bgr[by0:by1, bx0:bx1]
        cv2.addWeighted(patch, 0.55, roi, 0.45, 0.0, dst=roi)
    else:
        grid = np.zeros((bh, bw, 3), dtype=np.uint8)
        for i in range(1, 4):
            cv2.line(grid, (i * bw // 4, 0), (i * bw // 4, bh), (90, 90, 90), 1)
            cv2.line(grid, (0, i * bh // 4), (bw, i * bh // 4), (90, 90, 90), 1)
        roi = bgr[by0:by1, bx0:bx1]
        cv2.addWeighted(grid, 0.5, roi, 0.5, 0.0, dst=roi)

    zx, zy = tuning.reach_zoom
    cv2.putText(bgr, f"reach box = your screen   zoom {zx:.1f}x / {zy:.1f}x",
                (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
                cv2.LINE_AA)

    if frame is None:
        return
    nx, ny = plane_norm(frame.track_point("knuckles"))
    cx, cy = int((x0 + nx * (x1 - x0)) * w), int((y0 + ny * (y1 - y0)) * h)
    pinned = nx in (0.0, 1.0) or ny in (0.0, 1.0)
    color = (0, 0, 230) if pinned else (0, 255, 255)
    cv2.circle(bgr, (cx, cy), 7, color, 2)
    cv2.line(bgr, (cx - 12, cy), (cx + 12, cy), color, 1)
    cv2.line(bgr, (cx, cy - 12), (cx, cy + 12), color, 1)
    if pinned:
        cv2.putText(bgr, "PINNED at the edge - you are outside the box",
                    (8, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 230),
                    2, cv2.LINE_AA)


class JitterMeter:
    """Quantifies cursor steadiness live, in screen pixels.

    Two tracks over a rolling ~2s window: the FILTERED driver output (the
    dot — what a real session ships) and the RAW unfiltered mapping (the
    crosshair). Their gap is the filtering, measured instead of vibed. A
    window only counts as REST when the raw track's total excursion is
    small — deliberate motion would otherwise read as "jitter". The audited
    target: dot RMS <= ~2px at rest.
    """

    WINDOW = 60                 # ~2s at the ~30Hz display tick
    REST_SPAN_PX = 40.0         # raw peak-to-peak beyond this = deliberate motion

    def __init__(self):
        from collections import deque
        self._dot = deque(maxlen=self.WINDOW)
        self._raw = deque(maxlen=self.WINDOW)

    def add(self, dot_xy, raw_xy) -> None:
        self._dot.append(dot_xy)
        self._raw.append(raw_xy)

    def clear(self) -> None:
        self._dot.clear()
        self._raw.clear()

    @staticmethod
    def _rms(points) -> float:
        n = len(points)
        mx = sum(p[0] for p in points) / n
        my = sum(p[1] for p in points) / n
        return (sum((p[0] - mx) ** 2 + (p[1] - my) ** 2
                    for p in points) / n) ** 0.5

    @staticmethod
    def _span(points) -> float:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5

    def stats(self):
        """(dot_rms_px, raw_rms_px) during REST, else None."""
        if len(self._raw) < self.WINDOW // 2:
            return None
        if self._span(self._raw) > self.REST_SPAN_PX:
            return None
        return (self._rms(self._dot), self._rms(self._raw))


# What each fired command WOULD do — the test view proves recognition and
# routing; the real session proves synthesis (which needs Accessibility).
WOULD = {
    "pane.new": "frame shot (region -> clipboard)",
    "mission_control": "Mission Control",
    "toggle": "pause/resume",
    "dictate": "mic toggle (hold Option)",
    "copy": "press Cmd+C",
    "paste": "press Cmd+V",
    "enter": "press Return",
}


def test(args) -> int:
    import cv2
    from .actions import DryRunBackend
    from .camera import tune_for_camera
    from .cli import _overlay_commands
    from .commands import CommandEngine
    from .driver import DirectDriver, Mapping
    from .gestures import Config, GestureEngine

    tuning = Tuning.load()
    if not tuning.reach_active:
        print("no reach box stored yet — the viewport shows the whole frame. "
              "Fit your comfortable reach with:\n"
              "  python -m leapinput.reach map"
              + (" --source phone" if args.source == "phone" else ""),
              file=sys.stderr)
    # Both hands: the free-hand palette (copy/paste/enter) is half of what
    # this view exists to debug.
    source = _build_source(args, tuning, two_hands=True)

    # A SIMULATED touch cursor — the real engine and driver against a
    # dry-run backend, so the shipping physics (1 euro filter, deadband,
    # settle freeze, kinematic pinch gate) are testable here without
    # surrendering the real pointer. The thin crosshair drawn alongside is
    # the RAW unfiltered mapping — the gap between the two is the filtering,
    # visible live. Trust the dot; the crosshair is diagnostic.
    cfg = Config(hand=args.hand, plane="xy", grab_enabled=False)
    mapping = Mapping(plane="xy", invert_x=False, invert_z=False,
                      tracking_point="knuckles", absolute=True)
    tune_for_camera(cfg, mapping, tuning)
    engine = GestureEngine(cfg)
    sim = DirectDriver(DryRunBackend(), mapping)
    engine.subscribe(sim.on_intent)
    source.subscribe(engine.on_snapshot)

    commands = CommandEngine(hand=args.hand, pinch_on_mm=tuning.pinch_on_mm)
    fired: list[tuple[float, str]] = []

    def on_command(e) -> None:
        fired.append((time.monotonic(), WOULD.get(e.command.value,
                                                  e.command.value)))
        print(f"[reach test] {e.command.value} -> would "
              f"{WOULD.get(e.command.value, '?')}", file=sys.stderr)

    commands.subscribe(on_command)
    source.subscribe(commands.on_snapshot)

    meter = JitterMeter()
    last_report = [0.0]

    grab = _ScreenGrab()
    win = "leapinput reach test (q closes) - DRY RUN, cursor untouched"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    print("\nThe green box is your screen, floating where your hand is "
          "comfortable.\nThe crosshair is where the cursor would be. Command "
          "poses (both hands) are\nrecognized and logged but NOTHING is "
          "pressed. q closes.")
    with source.open():
        try:
            while True:
                bgr = source.preview_frame
                if bgr is not None:
                    box = source.reach_box(args.hand)
                    hand_frame = source.latest.get(args.hand)
                    _draw_viewport(cv2, bgr, tuning, box, hand_frame,
                                   grab.image)
                    _draw_sim(cv2, bgr, box, sim, engine)
                    if hand_frame is not None:
                        nx, ny = plane_norm(
                            hand_frame.track_point("knuckles"))
                        meter.add((sim.x, sim.y),
                                  (nx * (sim.w - 1.0), ny * (sim.h - 1.0)))
                    else:
                        meter.clear()
                    _draw_jitter(cv2, bgr, meter, last_report)
                    _overlay_commands(cv2, bgr, commands.overlay)
                    _draw_fired(cv2, bgr, fired)
                    if not commands.enabled:
                        cv2.putText(bgr, "PAUSED (ILY pose resumes)", (8, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 230),
                                    2, cv2.LINE_AA)
                    cv2.imshow(win, bgr)
                if cv2.waitKey(33) & 0xFF in (27, ord("q")):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            grab.stop()
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    return 0


def _draw_sim(cv2, bgr, box, sim, engine) -> None:
    """The relative (mouse-feel) cursor: a solid dot driven by the REAL
    gesture engine and driver against a dry-run backend. This is what a live
    session's default mapping does — clutch ratchet, gain curve, settle —
    drawn inside the viewport next to the absolute crosshair for comparison.
    """
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = box
    nx = sim.x / max(1.0, sim.w - 1.0)
    ny = sim.y / max(1.0, sim.h - 1.0)
    cx = int((x0 + nx * (x1 - x0)) * w)
    cy = int((y0 + ny * (y1 - y0)) * h)
    if not engine.clutch.state:
        color, label = (180, 180, 180), "parked (open hand)"
    elif engine.pinch.state:
        color, label = (0, 165, 255), "CLICK held"
    else:
        color, label = (0, 220, 0), "touch"
    cv2.circle(bgr, (cx, cy), 9, color, -1)
    cv2.circle(bgr, (cx, cy), 9, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(bgr, label, (cx + 14, cy - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, color, 1, cv2.LINE_AA)


def _draw_jitter(cv2, bgr, meter: JitterMeter, last_report: list) -> None:
    """The steadiness verdict, measured: dot vs raw RMS while at rest.
    Green = under the audited 2px target. Also printed every ~3s so the
    numbers land in the session log, not just on screen."""
    stats = meter.stats()
    if stats is None:
        cv2.putText(bgr, "jitter: hold the hand STILL to measure", (8, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1,
                    cv2.LINE_AA)
        return
    dot_rms, raw_rms = stats
    ok = dot_rms <= 2.0
    color = (0, 220, 0) if ok else (0, 165, 255)
    cv2.putText(bgr, f"REST JITTER  dot {dot_rms:4.1f}px  raw {raw_rms:4.1f}px"
                     f"   target <2  {'OK' if ok else 'OVER'}",
                (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    now = time.monotonic()
    if now - last_report[0] > 3.0:
        last_report[0] = now
        print(f"[jitter] dot={dot_rms:.1f}px raw={raw_rms:.1f}px "
              f"({'OK' if ok else 'OVER target'})", flush=True)


def _draw_fired(cv2, bgr, fired: list[tuple[float, str]]) -> None:
    """The last few commands that WOULD have fired, with their age — the
    proof that a pose was recognized AND routed to the right hand."""
    now = time.monotonic()
    recent = [(at, what) for at, what in fired[-4:] if now - at < 6.0]
    h = bgr.shape[0]
    for i, (at, what) in enumerate(reversed(recent)):
        cv2.putText(bgr, f"would {what}  ({now - at:.0f}s ago)",
                    (8, h - 54 - 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 220, 0), 1, cv2.LINE_AA)


# --- entry ----------------------------------------------------------------------

def _add_source_args(ap) -> None:
    ap.add_argument("--source", choices=("camera", "phone"), default="camera")
    ap.add_argument("--camera", type=int, default=None)
    ap.add_argument("--camera-name", default=None, metavar="NAME")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput.reach")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map", help="roam comfortably, fit the reach box, save")
    _add_source_args(m)
    m.add_argument("--seconds", type=float, default=ROAM_SECONDS)
    m.add_argument("--dry-run", action="store_true",
                   help="fit and report only; do not write camera_tuning.json")

    c = sub.add_parser("corners", help="place your hand at the two corners "
                                       "of where you WANT it to work — the "
                                       "direct alternative to `map`")
    _add_source_args(c)
    c.add_argument("--dry-run", action="store_true",
                   help="fit and report only; do not write camera_tuning.json")

    t = sub.add_parser("test", help="live viewport check: the screen drawn "
                                    "inside the box, cursor crosshair, dry run")
    _add_source_args(t)

    hd = sub.add_parser("hand", help="calibrate your hand's REAL size — the "
                                     "fiducial in every frame (ChArUco-board "
                                     "idea). --span-mm for a ruler "
                                     "measurement, else the camera estimates")
    _add_source_args(hd)
    hd.add_argument("--span-mm", type=float, default=None,
                    help="ruler measurement: index knuckle centre to pinky "
                         "knuckle centre, across the back of the hand")

    a = sub.add_parser("anchor", help="palm (default): dynamic screen-shaped "
                                      "box centred on your palm at each "
                                      "appearance; fixed: the exact placed "
                                      "rectangle")
    a.add_argument("mode", choices=("palm", "fixed"))

    sub.add_parser("show", help="print the stored reach box")
    sub.add_parser("clear", help="remove the reach box (whole-frame mapping)")

    args = ap.parse_args(argv)
    if args.cmd == "map":
        return roam(args)
    if args.cmd == "corners":
        return corners(args)
    if args.cmd == "test":
        return test(args)
    if args.cmd == "hand":
        return hand(args)
    tuning = Tuning.load()
    if args.cmd == "anchor":
        out = dataclasses.replace(tuning, reach_center=args.mode).save()
        print(f"reach anchor -> {args.mode}  ({out})")
        return 0
    if args.cmd == "show":
        if not tuning.reach_active:
            print("no reach box stored (whole-frame mapping)")
        else:
            x0, y0, x1, y1 = tuning.reach
            zx, zy = tuning.reach_zoom
            print(f"reach box x {x0:.2f}..{x1:.2f}  y {y0:.2f}..{y1:.2f}  "
                  f"zoom {zx:.1f}x / {zy:.1f}x  anchor {tuning.reach_center}"
                  + (f"  ref span {tuning.ref_span_img:.3f}"
                     if tuning.ref_span_img else ""))
            line = physical_summary(tuning)
            if line:
                print(line)
        return 0
    # Only `clear` may reach this point: an unrouted subcommand silently
    # CLEARING the calibration is exactly the bug this assert now catches
    # (it happened — `hand` fell through here before it was dispatched).
    assert args.cmd == "clear", f"unrouted subcommand {args.cmd!r}"
    out = save_reach((0.0, 0.0, 1.0, 1.0), ref_span_img=0.0)
    print(f"reach box and working distance cleared -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
