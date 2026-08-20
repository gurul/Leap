"""Camera capture tests: the landmark -> HandFrame maths, no mediapipe required.

The synthetic hands below are 21-point MediaPipe-shaped landmark lists (metres,
x right / y DOWN / z away from camera — the raw MediaPipe convention) built to be
unambiguous instances of the four poses the finger-ladder vocabulary reads:
open hand, fist, point, and pinch-while-pointing.
"""

import math

from leapinput.camera import (PLANE_X_MM, PLANE_Y_BASE, PLANE_Y_MM, Tuning,
                              handframe_of)
from leapinput.capture import Snapshot, Vec3
from leapinput.gestures import Config, GestureEngine, Intent

# --- synthetic world landmarks (pose signals) ---------------------------------

WRIST = Vec3(0.0, 0.09, 0.0)
THUMB_OUT = [Vec3(-0.03, 0.06, 0.0), Vec3(-0.045, 0.045, 0.0),
             Vec3(-0.055, 0.03, 0.0), Vec3(-0.065, 0.02, 0.0)]
THUMB_TUCKED = [Vec3(-0.03, 0.06, 0.0), Vec3(-0.045, 0.045, 0.0),
                Vec3(-0.01, 0.02, 0.015), Vec3(0.02, 0.0, 0.02)]

# Finger x offsets: index, middle, ring, pinky.
FINGER_X = (-0.02, 0.0, 0.017, 0.03)


def _finger(x0: float, curled: bool) -> list[Vec3]:
    """MCP, PIP, DIP, TIP. Straight points down-image (fingers up); curled folds
    the tip back toward the palm (positive z, toward the scene)."""
    if curled:
        return [Vec3(x0, 0.01, 0.0), Vec3(x0, -0.02, 0.01),
                Vec3(x0, -0.005, 0.018), Vec3(x0, 0.005, 0.02)]
    return [Vec3(x0, 0.01, 0.0), Vec3(x0, -0.02, 0.0),
            Vec3(x0, -0.04, 0.0), Vec3(x0, -0.06, 0.0)]


def _world(thumb: list[Vec3], curls: tuple[bool, bool, bool, bool]) -> list[Vec3]:
    lms = [WRIST] + list(thumb)
    for x0, curled in zip(FINGER_X, curls):
        lms += _finger(x0, curled)
    assert len(lms) == 21
    return lms


OPEN = _world(THUMB_OUT, (False, False, False, False))
FIST = _world(THUMB_TUCKED, (True, True, True, True))
POINT = _world(THUMB_TUCKED, (False, True, True, True))
# Point pose with the thumb tip brought to the index tip (index tip of a straight
# index finger sits at (-0.02, -0.06, 0)).
PINCH = _world(THUMB_TUCKED[:3] + [Vec3(-0.021, -0.058, 0.001)],
               (False, True, True, True))


def _image(x: float, y: float) -> list[Vec3]:
    """Normalized image landmarks; the whole hand collapsed to one point is fine
    for position-mapping tests, since palm/knuckles are means of subsets."""
    return [Vec3(x, y, 0.0)] * 21


def frame(world, x=0.5, y=0.45, t_us=0, prev=None):
    return handframe_of(_image(x, y), world, "Right", 1, t_us, prev=prev)


# --- pose signals --------------------------------------------------------------

def test_open_hand_reads_five_extended_and_no_pinch():
    f = frame(OPEN)
    assert f.extended == (True,) * 5
    assert f.extended_count == 5
    assert f.grab_strength < 0.35          # below Config.grab_off
    assert f.pinch_distance > 68.0         # beyond Config.pinch_off_mm
    assert f.pinch_strength < 0.5


def test_fist_reads_zero_extended_and_full_grab():
    f = frame(FIST)
    assert f.extended_count == 0
    assert f.grab_strength > 0.75          # above Config.grab_on


def test_point_reads_one_finger_and_does_not_click():
    f = frame(POINT)
    assert f.extended == (False, True, False, False, False)
    # Tucked thumb to straight index is ~75mm: outside the pinch entirely, so
    # pointing can never register as a click.
    assert f.pinch_distance > 68.0


def test_pinch_while_pointing_clicks_and_stays_in_the_engaged_band():
    f = frame(PINCH)
    assert f.pinch_distance < 50.0         # inside Config.pinch_on_mm
    assert f.pinch_strength >= 0.5         # clears Config.pinch_min_strength
    # 1-3 extended keeps the ladder engaged, so the click can actually land.
    assert 1 <= f.extended_count <= 3


def test_finger_hysteresis_keeps_the_previous_state_in_the_band():
    # Index bent to exactly 65 deg: between EXTEND_ON (55) and EXTEND_OFF (75),
    # so the reading must follow the previous frame, whichever way it pointed.
    mid = list(OPEN)
    mid[8] = Vec3(-0.02, -0.02845, 0.01813)     # tip rotated 65 deg at the PIP
    from_open = handframe_of(_image(0.5, 0.45), mid, "Right", 2, 33_000,
                             prev=frame(OPEN))
    from_fist = handframe_of(_image(0.5, 0.45), mid, "Right", 2, 33_000,
                             prev=frame(FIST))
    assert from_open.extended[1] is True
    assert from_fist.extended[1] is False


def test_pinch_distance_is_hand_scale_invariant():
    # MediaPipe's per-frame metric scale jitters; the knuckle-span ratio cancels
    # it, so a uniformly rescaled hand must read the same pinch distance.
    grown = [Vec3(v.x * 1.3, v.y * 1.3, v.z * 1.3) for v in PINCH]
    assert abs(frame(PINCH).pinch_distance - frame(grown).pinch_distance) < 1e-6


def test_pose_signals_blend_with_the_previous_frame():
    snap = handframe_of(_image(0.5, 0.45), PINCH, "Right", 2, 33_000,
                        prev=frame(OPEN))
    raw = frame(PINCH).pinch_distance
    # One EMA step from wide open: partway down, not all the way.
    assert raw < snap.pinch_distance < frame(OPEN).pinch_distance
    # ...and one more pinch frame is already deep inside the click threshold.
    settled = handframe_of(_image(0.5, 0.45), PINCH, "Right", 3, 66_000, prev=snap)
    assert settled.pinch_distance < 50.0


def test_tuning_can_drive_pinch_from_the_image_signal():
    # World landmarks say wide open (~100mm), but the 2D tips touch — the
    # occlusion case where the depth guess lies and pixels do not.
    img = _image(0.5, 0.45)
    img[5], img[17] = Vec3(0.45, 0.45, 0.0), Vec3(0.55, 0.45, 0.0)   # span
    img[4] = img[8] = Vec3(0.52, 0.45, 0.0)                          # tips touch
    world_says = frame(OPEN).pinch_distance
    f = handframe_of(img, OPEN, "Right", 1, 0,
                     tuning=Tuning(pinch_source="image"))
    assert world_says > 68.0
    assert f.pinch_distance < 5.0


# --- position mapping ------------------------------------------------------------

def test_image_position_maps_mirrored_right_and_up():
    centre = frame(OPEN, x=0.5, y=0.5)
    right = frame(OPEN, x=0.8, y=0.5)
    high = frame(OPEN, x=0.5, y=0.2)
    assert abs(centre.palm.x) < 1e-9
    assert right.palm.x > centre.palm.x    # image right = +X (mirrored view)
    assert high.palm.y > centre.palm.y     # image up = +Y
    assert centre.palm.z == 0.0


def test_y_never_drops_below_the_xy_engage_floor():
    bottom = frame(OPEN, x=0.5, y=1.0)
    top = frame(OPEN, x=0.5, y=0.0)
    assert bottom.palm.y == PLANE_Y_BASE   # 200mm >> engage_y_xy (40)
    assert top.palm.y == PLANE_Y_BASE + PLANE_Y_MM
    # Presence is the gate: while tracked, height alone can never disengage.
    assert bottom.palm.y > Config().engage_y_xy


def test_eccentricity_stays_inside_the_edge_guard_everywhere():
    for x, y in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        f = frame(OPEN, x=x, y=y)
        assert f.eccentricity < 40.0       # Mapping.edge_ok_deg: never damped


def test_track_point_and_knuckles_are_populated():
    f = frame(POINT, x=0.5, y=0.5)
    assert len(f.knuckles) == 4
    assert f.side == "Right"
    p = f.track_point("index")
    assert p is not None and PLANE_Y_BASE <= p.y <= PLANE_Y_BASE + PLANE_Y_MM


def test_velocity_is_a_blended_finite_difference():
    f0 = frame(OPEN, x=0.5, t_us=0)
    f1 = frame(OPEN, x=0.55, t_us=33_333, prev=f0)
    assert f0.palm_velocity.x == 0.0
    # 16mm in 33ms is ~480mm/s raw; blended 50/50 with the previous (zero)
    # estimate it lands near 240.
    assert 200.0 < f1.palm_velocity.x < 300.0


# --- end to end: camera-shaped frames through the real gesture engine -----------

def test_engine_runs_the_full_vocabulary_from_camera_frames():
    engine = GestureEngine(Config(hand="Right", plane="xy"))
    seen: list[Intent] = []
    engine.subscribe(lambda e: seen.append(e.intent))

    t = 0

    def feed(world, n):
        nonlocal t
        for _ in range(n):
            t += 33_000                     # ~30fps in microseconds
            engine.on_snapshot(Snapshot(right=frame(world, t_us=t)))

    feed(OPEN, 5)                           # engage; open hand keeps mouse lifted
    feed(POINT, 5)                          # ladder engages: clutch down, moving
    feed(PINCH, 4)                          # pinch closes: click down
    feed(POINT, 4)                          # pinch opens: click up
    feed(OPEN, 10)                          # deliberate open hand: mouse lifts
    engine.on_snapshot(Snapshot())          # hand leaves the view: hard release

    def ordered(*intents):
        i = 0
        for intent in seen:
            if i < len(intents) and intent is intents[i]:
                i += 1
        return i == len(intents)

    assert ordered(Intent.ENGAGE, Intent.CLUTCH_DOWN, Intent.SELECT_DOWN,
                   Intent.SELECT_UP, Intent.CLUTCH_UP, Intent.DISENGAGE), seen
    assert Intent.POINT_MOVE in seen
    assert Intent.GRAB_DOWN not in seen     # nothing ever read as a fist


# --- isotropy (plan item 2, 2026-08-18) --------------------------------------

def test_equal_physical_motion_maps_to_equal_virtual_mm():
    """One centimetre of real hand travel must produce the same virtual mm
    horizontally and vertically. A 640x480 frame is 4:3, so equal PHYSICAL
    motion is equal FRACTIONS of width and height only when the plane constants
    keep the same mm-per-pixel on both axes (PLANE_Y_MM = PLANE_X_MM * 480/640).
    The old 320x300 pair made vertical ~25% hotter than horizontal."""
    assert PLANE_Y_MM == PLANE_X_MM * 480.0 / 640.0

    # A physical step of the same pixel count on each axis: 48px of a 640px
    # width is dx=0.075 normalized; 48px of a 480px height is dy=0.1.
    a = handframe_of(_image(0.5, 0.5), OPEN, "Right", 1, 1_000)
    bx = handframe_of(_image(0.575, 0.5), OPEN, "Right", 2, 34_000)
    by = handframe_of(_image(0.5, 0.4), OPEN, "Right", 3, 67_000)
    dx = abs(bx.palm.x - a.palm.x)
    dy = abs(by.palm.y - a.palm.y)
    assert abs(dx - dy) < 1e-9, f"anisotropic plane: {dx:.2f}mm vs {dy:.2f}mm"


# --- handedness identity (plan item 5, 2026-08-18) ---------------------------

def test_resolve_side_trusts_identity_over_a_flapping_label():
    """One visible hand + a configured side: the label may flip every frame
    (it does, on fists and pinches) without the hand changing identity."""
    from leapinput.camera import resolve_side
    for label in ("Left", "Right", "Left", "Left", "Right"):
        assert resolve_side(label, 1, "Right") == "Right"


def test_resolve_side_keeps_the_mirror_swap_for_two_hands():
    """Two detections: the un-mirrored-image label swap still applies."""
    from leapinput.camera import resolve_side
    assert resolve_side("Left", 2, "Right") == "Right"
    assert resolve_side("Right", 2, "Right") == "Left"
    assert resolve_side("Left", 1, None) == "Right"    # unconfigured: swap only


def test_a_label_flap_does_not_release_a_drag():
    """Six mid-drag frames whose labels flip: routed through resolve_side the
    configured hand never vanishes, so the engine never releases the grab."""
    from leapinput.camera import resolve_side

    engine = GestureEngine(Config(plane="xy", clutch_mode="fingers",
                                  engage_dwell=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    labels = ["Left", "Right", "Left", "Right", "Left", "Right"] * 5
    for label in labels:
        t += 33_000
        side = resolve_side(label, 1, "Right")
        f = handframe_of(_image(0.5, 0.5), FIST, side, 1, t)
        engine.on_snapshot(Snapshot(right=f))
    assert Intent.GRAB_DOWN in seen
    assert Intent.GRAB_UP not in seen
    assert Intent.DISENGAGE not in seen


# --- dropout restamping (plan item 6, 2026-08-18) ----------------------------

def test_a_release_dwell_completes_through_a_dropout():
    """The engine clocks off frame timestamps. A dropout used to re-serve the
    held frame with its OLD stamp, freezing the clock and stalling every
    pending dwell. Restamped holds keep time moving: an open hand followed by
    a short dropout still lifts within finger_lift_hold of the open hand."""
    import dataclasses as dc

    engine = GestureEngine(Config(plane="xy", clutch_mode="fingers",
                                  engage_dwell=0.0, finger_hold=0.0,
                                  finger_lift_hold=0.10))
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    fist = handframe_of(_image(0.5, 0.5), FIST, "Right", 1, 0)
    open_hand = handframe_of(_image(0.5, 0.5), OPEN, "Right", 1, 0)
    for _ in range(10):                 # drag
        t += 33_000
        engine.on_snapshot(Snapshot(right=dc.replace(fist, timestamp=t)))
    t += 33_000                         # one frame of deliberate open hand
    engine.on_snapshot(Snapshot(right=dc.replace(open_hand, timestamp=t)))
    # Dropout: the capture layer re-serves the open hand RESTAMPED, as
    # CameraSource now does. Time advances, so the lift dwell can elapse.
    for _ in range(6):
        t += 33_000
        engine.on_snapshot(Snapshot(right=dc.replace(open_hand, timestamp=t)))
    assert Intent.GRAB_UP in seen
    assert Intent.CLUTCH_UP in seen


# --- span depth gate (2026-08-18) --------------------------------------------

def test_a_distant_hand_reads_as_below_the_span_gate():
    """A hand across the room projects a tiny knuckle span; the capture loop
    ignores it (span_img < MIN_SPAN_IMG) so a background person can never grab
    the cursor. A hand at working distance passes comfortably."""
    from leapinput.camera import MIN_SPAN_IMG, pose_signals

    def image_hand(scale: float) -> list[Vec3]:
        # Index MCP (5) and pinky MCP (17) separated by `scale` in image space.
        lms = [Vec3(0.5, 0.5, 0.0)] * 21
        lms[5] = Vec3(0.5 - scale / 2, 0.5, 0.0)
        lms[17] = Vec3(0.5 + scale / 2, 0.5, 0.0)
        return lms

    near = pose_signals(OPEN, image_hand(0.10))
    far = pose_signals(OPEN, image_hand(0.02))
    assert near.span_img > MIN_SPAN_IMG
    assert far.span_img < MIN_SPAN_IMG


# --- lone-hand side: continuity vs label (2026-08-18) ------------------------

def test_lone_hand_continuous_with_cursor_hand_keeps_identity():
    """The label-flap case: mid-pinch the label flips, but the hand is where
    the cursor hand just was — identity wins."""
    from leapinput.camera import lone_hand_side
    side = lone_hand_side("Left", "Right", prev_wrist=(0.50, 0.50),
                          wrist=(0.52, 0.51), elapsed_us=33_000)
    assert side == "Right"


def test_lone_free_hand_raised_alone_is_believed():
    """Raising ONLY the left hand must read as Left or the free-hand poses
    (clipboard, enter) are unreachable — the bug that made paste 'not work'."""
    from leapinput.camera import lone_hand_side
    # Cursor hand never seen:
    assert lone_hand_side("Left", "Right", prev_wrist=None,
                          wrist=(0.3, 0.5), elapsed_us=0) == "Left"
    # Cursor hand seen long ago:
    assert lone_hand_side("Left", "Right", prev_wrist=(0.7, 0.5),
                          wrist=(0.68, 0.5), elapsed_us=2_000_000) == "Left"
    # Cursor hand recent but ELSEWHERE in the frame:
    assert lone_hand_side("Left", "Right", prev_wrist=(0.8, 0.6),
                          wrist=(0.2, 0.4), elapsed_us=33_000) == "Left"


# --- ILY routing: the label decides Enter vs pause (2026-08-18) --------------

def test_ily_shaped_matches_only_the_ily_hand():
    """The routing-time ILY read: thumb + index + pinky out, middle + ring
    curled — prev-less, straight off PoseSignals. Everything adjacent (fist,
    point, open hand, horns) must NOT match, or ordinary cursor work would
    start trusting flappy labels."""
    from leapinput.camera import PoseSignals, Tuning, ily_shaped

    t = Tuning()

    def sig(thumb_ratio, bends):
        return PoseSignals(bends=bends, thumb_ratio=thumb_ratio,
                           pinch_mm=60.0, span_mm=80.0)

    assert ily_shaped(sig(1.3, (30, 110, 110, 30)), t)          # ILY
    assert not ily_shaped(sig(0.7, (100, 110, 110, 100)), t)    # fist
    assert not ily_shaped(sig(1.3, (30, 110, 110, 110)), t)     # point (L)
    assert not ily_shaped(sig(1.3, (30, 30, 30, 30)), t)        # open hand
    assert not ily_shaped(sig(0.7, (30, 110, 110, 30)), t)      # horns (no thumb)
    assert not ily_shaped(sig(1.3, (30, 30, 110, 110)), t)      # V sign


def test_lone_left_ily_near_the_cursor_hands_last_spot_is_still_left():
    """The Enter-vs-pause confusion, end to end at the routing rule: the left
    hand raised in ILY where the cursor hand just was would be adopted by
    continuity (lone_hand_side says the configured hand) — but for an
    ILY-shaped detection the capture loop trusts the label instead, so it must
    route Left = Enter, never cursor-hand ILY = pause."""
    from leapinput.camera import (PoseSignals, Tuning, ily_shaped,
                                  lone_hand_side)

    ily = PoseSignals(bends=(30, 110, 110, 30), thumb_ratio=1.3,
                      pinch_mm=60.0, span_mm=80.0)
    # Continuity alone would misroute this detection to the cursor hand:
    assert lone_hand_side("Left", "Right", prev_wrist=(0.50, 0.50),
                          wrist=(0.52, 0.51), elapsed_us=33_000) == "Right"
    # ...which is exactly why the capture loop bypasses it for ILY:
    assert ily_shaped(ily, Tuning())


def test_v_shaped_matches_only_the_v_hand():
    """The routing-time V read (paste, free hand only): index + middle out,
    ring + pinky curled, thumb ignored — a natural peace sign often reads
    thumb-out. Adjacent poses must NOT match, for the same reason as ILY."""
    from leapinput.camera import PoseSignals, Tuning, v_shaped

    t = Tuning()

    def sig(thumb_ratio, bends):
        return PoseSignals(bends=bends, thumb_ratio=thumb_ratio,
                           pinch_mm=60.0, span_mm=80.0)

    assert v_shaped(sig(0.7, (30, 30, 110, 110)), t)            # V sign
    assert v_shaped(sig(1.3, (30, 30, 110, 110)), t)            # thumb-out V
    assert not v_shaped(sig(1.3, (30, 110, 110, 110)), t)       # point
    assert not v_shaped(sig(1.3, (30, 30, 30, 30)), t)          # open hand
    assert not v_shaped(sig(0.7, (100, 110, 110, 100)), t)      # fist
    assert not v_shaped(sig(1.3, (30, 110, 110, 30)), t)        # ILY


# --- capture-loop loss hardening (2026-08-19) ---------------------------------

def _engine_mid_grab():
    """A real GestureEngine driven into a held grab by direct fist frames,
    plus the intent log — the 'button is down' precondition for the release
    tests below."""
    engine = GestureEngine(Config(plane="xy", clutch_mode="fingers",
                                  engage_dwell=0.0))
    seen: list[Intent] = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for _ in range(30):
        t += 33_000
        f = handframe_of(_image(0.5, 0.5), FIST, "Right", 1, t)
        engine.on_snapshot(Snapshot(right=f))
    assert Intent.GRAB_DOWN in seen and Intent.GRAB_UP not in seen
    return engine, seen


def test_a_stream_stall_releases_held_input_exactly_once():
    """The read loop's not-ok branch used to sleep+continue forever, never
    reaching the release path — an unplugged camera or a stopped phone stream
    left a held button down indefinitely. Failed reads outlasting the 150ms
    flicker budget must dispatch one empty Snapshot (the engine's release
    path) and then go quiet until frames return."""
    import threading as th
    import time as tm

    from leapinput.camera import CameraSource

    class DeadCap:
        def read(self):
            return (False, None)

        def grab(self):
            pass

    src = CameraSource(hand="Right", screen_aspect=1512 / 982)
    engine, seen = _engine_mid_grab()
    src.subscribe(engine.on_snapshot)
    src._prev["Right"] = handframe_of(_image(0.5, 0.5), FIST, "Right", 1, 0)
    src._reach_now["Right"] = (0.3, 0.3, 0.6, 0.6)
    worker = th.Thread(target=src._run, args=(None, None, DeadCap(), None),
                       daemon=True)
    worker.start()
    deadline = tm.monotonic() + 2.0
    while src.frames == 0 and tm.monotonic() < deadline:
        tm.sleep(0.01)
    try:
        assert src.frames == 1, "stall never dispatched a release"
        assert Intent.GRAB_UP in seen and Intent.DISENGAGE in seen
        assert src._prev["Right"] is None       # next appearance re-centres
        # ...unless it is quick and nearby: the dying box is stashed so a
        # brief stream hiccup does not cost the hand its aim (RC-1).
        assert src._reach_now["Right"] is None
        gone_box, _ = src._reach_gone["Right"]
        assert gone_box == (0.3, 0.3, 0.6, 0.6)
        tm.sleep(0.2)                           # stall persists...
        assert src.frames == 1                  # ...but releases only ONCE
    finally:
        src._stop.set()
        worker.join(timeout=2.0)


def test_a_capture_thread_crash_releases_held_input_and_reraises():
    """A detection (or subscriber) exception used to kill the daemon thread
    with no final dispatch: buttons stayed held while the process lived. The
    loop must release via one empty Snapshot on the way out — each subscriber
    guarded, so a crashing one cannot block the engine's release — and still
    re-raise so the traceback reaches stderr."""
    import pytest

    from leapinput.camera import CameraSource

    class FakeCv2:
        COLOR_BGR2RGB = 0

        def flip(self, bgr, code):
            return bgr

        def cvtColor(self, bgr, code):
            return bgr

    class FakeMp:
        class ImageFormat:
            SRGB = 0

        @staticmethod
        def Image(image_format=None, data=None):
            return object()

    class LiveCap:
        def read(self):
            return (True, object())

        def grab(self):
            pass

    class CrashingLandmarker:
        def detect_for_video(self, image, ms):
            raise RuntimeError("mediapipe crashed")

    src = CameraSource(hand="Right", screen_aspect=1512 / 982)
    engine, seen = _engine_mid_grab()

    def bad_subscriber(snap):
        raise ValueError("subscriber crashed")

    src.subscribe(bad_subscriber)               # ahead of the engine
    src.subscribe(engine.on_snapshot)
    src._prev["Right"] = handframe_of(_image(0.5, 0.5), FIST, "Right", 1, 0)
    with pytest.raises(RuntimeError, match="mediapipe crashed"):
        src._run(FakeCv2(), FakeMp(), LiveCap(), CrashingLandmarker())
    assert Intent.GRAB_UP in seen and Intent.DISENGAGE in seen
    assert src._prev["Right"] is None


# --- the two-hand framing rectangle, across two reach boxes -------------------

def _framing_hands(l_box, r_box, l_at=(0.35, 0.30), r_at=(0.65, 0.70)):
    """Both hands in the L-pose, each mapped through its OWN reach box — what
    dynamic ("palm") mode hands to the command layer every frame."""
    return (handframe_of(_image(*l_at), OPEN, "Left", 1, 0, reach=l_box),
            handframe_of(_image(*r_at), OPEN, "Right", 1, 0, reach=r_box))


def test_pane_rect_measures_the_hands_not_their_reach_boxes():
    """Regression: the framed rect must describe where the HANDS are.

    In palm mode each hand carries its own box, centred on that palm and sized
    by that hand's apparent span. Reading the rect off box-relative fingertips
    measured each tip's offset from its own palm instead — here the right
    hand's wider box (it is nearer the camera) pushes its normalized tip LEFT
    of the left hand's, swapping the corners: an inverted box.
    """
    from leapinput.commands import frame_rect

    left, right = _framing_hands((0.15, 0.15, 0.45, 0.45),   # snug box
                                 (0.40, 0.40, 1.00, 1.00))   # nearer: wider box
    x0, y0, x1, y1 = frame_rect(left, right)
    assert abs(x0 - 0.35) < 1e-6 and abs(x1 - 0.65) < 1e-6
    assert abs(y0 - 0.30) < 1e-6 and abs(y1 - 0.70) < 1e-6

    # The corner-swapping symptom, stated directly: box-relative tips put the
    # LEFT hand to the right of the right hand. The rect must not follow them.
    from leapinput.camera import plane_norm
    assert plane_norm(left.index_tip)[0] > plane_norm(right.index_tip)[0]


def test_pane_rect_ignores_a_hand_moving_closer_to_the_camera():
    """Approaching the camera grows that hand's box. The framed region is a
    position in the frame, so it must not move when only the box does."""
    from leapinput.commands import frame_rect

    far = frame_rect(*_framing_hands((0.15, 0.15, 0.45, 0.45),
                                     (0.55, 0.55, 0.85, 0.85)))
    near = frame_rect(*_framing_hands((0.15, 0.15, 0.45, 0.45),
                                      (0.20, 0.20, 1.00, 1.00)))
    assert far == near


def test_pane_rect_shrinks_as_the_hands_close_in():
    from leapinput.commands import frame_rect

    box_l, box_r = (0.15, 0.15, 0.45, 0.45), (0.55, 0.55, 0.85, 0.85)
    wide = frame_rect(*_framing_hands(box_l, box_r, (0.20, 0.20), (0.80, 0.80)))
    tight = frame_rect(*_framing_hands(box_l, box_r, (0.45, 0.45), (0.55, 0.55)))
    assert (tight[2] - tight[0]) < (wide[2] - wide[0])
    assert tight[0] < tight[2] and tight[1] < tight[3]      # never inverted
