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
