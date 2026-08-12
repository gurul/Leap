"""Capture-layer tests, centred on the field that lied.

Hyperion 6.2 with a v1 controller reports `palm.stabilized_position` as exactly
(0,0,0) on every frame. Consuming it directly zeroed the engagement height and the
cursor projection — the system could never engage, and no hardware-free test caught
it because the bug only appears when a real hand is present. These pin the fallback.
"""

from leapinput.capture import HandFrame, Vec3

ORIGIN = Vec3(0.0, 0.0, 0.0)


def frame(palm: Vec3, palm_stable: Vec3) -> HandFrame:
    return HandFrame(
        frame_id=1, timestamp=0, hand_id=1, side="Right", confidence=1.0,
        palm=palm, palm_stable=palm_stable, palm_velocity=ORIGIN,
        palm_normal=ORIGIN, palm_direction=ORIGIN,
        pinch_strength=0.0, pinch_distance=80.0,
        grab_strength=0.0, grab_angle=0.0,
        extended=(True,) * 5, fingertips=(ORIGIN,) * 5,
    )


def test_position_falls_back_when_stabilized_is_zeroed():
    """The measured Hyperion 6.2 + v1 behaviour."""
    f = frame(palm=Vec3(85.0, 232.0, 59.0), palm_stable=ORIGIN)
    assert f.position == Vec3(85.0, 232.0, 59.0)


def test_position_prefers_stabilized_when_populated():
    """So a future Hyperion that fills the field is picked up for free."""
    f = frame(palm=Vec3(85.0, 232.0, 59.0), palm_stable=Vec3(84.0, 231.0, 58.0))
    assert f.position == Vec3(84.0, 231.0, 58.0)


def test_a_genuinely_centred_hand_is_not_mistaken_for_zeroed():
    """x and z can legitimately be 0 at the device centre; only all-three-zero
    means the field is unpopulated."""
    f = frame(palm=Vec3(1.0, 1.0, 1.0), palm_stable=Vec3(0.0, 200.0, 0.0))
    assert f.position == Vec3(0.0, 200.0, 0.0)


def test_engagement_reads_a_real_height_not_zero():
    """The end-to-end symptom: a hand at working height must clear the gate."""
    from leapinput.gestures import Config, GestureEngine, Intent
    from leapinput.capture import Snapshot

    seen = []
    engine = GestureEngine(Config(engage_dwell=0.0))
    engine.subscribe(lambda e: seen.append(e.intent))
    engine.on_snapshot(Snapshot(right=frame(Vec3(0.0, 232.0, 0.0), ORIGIN)))
    assert Intent.ENGAGE in seen


# --- rigid tracking point ---------------------------------------------------

def _hand(palm: Vec3, knuckles: tuple) -> HandFrame:
    return HandFrame(
        frame_id=1, timestamp=0, hand_id=1, side="Right", confidence=1.0,
        palm=palm, palm_stable=ORIGIN, palm_velocity=ORIGIN,
        palm_normal=ORIGIN, palm_direction=ORIGIN,
        pinch_strength=0.0, pinch_distance=80.0, grab_strength=0.0, grab_angle=0.0,
        extended=(True,) * 5, fingertips=(ORIGIN,) * 5, knuckles=knuckles,
    )


KNUCKLES = (Vec3(-20.0, 100.0, 0.0), Vec3(-7.0, 100.0, 0.0),
            Vec3(7.0, 100.0, 0.0), Vec3(20.0, 100.0, 0.0))


def test_center_is_the_knuckle_mean():
    f = _hand(Vec3(0.0, 90.0, 10.0), KNUCKLES)
    assert f.center == Vec3(0.0, 100.0, 0.0)


def test_center_ignores_palm_centroid_drift():
    """The accuracy bug: palm.position is the centroid of a deforming surface, so
    curling the fingers to pinch shifts it several mm and the cursor creeps at the
    exact moment you are holding still on a target. The knuckle line does not move."""
    open_hand = _hand(Vec3(0.0, 90.0, 0.0), KNUCKLES)
    pinching = _hand(Vec3(6.0, 84.0, 5.0), KNUCKLES)      # centroid moved 9mm
    assert open_hand.palm != pinching.palm
    assert open_hand.center == pinching.center


def test_center_falls_back_for_recordings_without_knuckles():
    f = _hand(Vec3(3.0, 90.0, 4.0), ())
    assert f.center == f.position
