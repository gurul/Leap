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
