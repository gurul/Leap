"""Capture-layer tests.

The frame carries only what the 2D plane pipeline actually reads. Three fields
were removed after measurement rather than trimmed for tidiness:

  palm_stable     reported exactly (0,0,0) on every frame by Hyperion 6.2 with a
                  v1 controller. Not merely useless — consuming it silently
                  zeroed the engagement height and the cursor mapping, so the
                  system could never engage. A field that is always zero is a
                  correctness trap, not dead weight.
  palm_direction  never read anywhere.
  confidence      the LeapC header says "Not currently used (always 1.0)".
"""

import dataclasses

from leapinput.capture import HandFrame, Vec3

ORIGIN = Vec3(0.0, 0.0, 0.0)
KNUCKLES = (Vec3(-20.0, 100.0, 0.0), Vec3(-7.0, 100.0, 0.0),
            Vec3(7.0, 100.0, 0.0), Vec3(20.0, 100.0, 0.0))


def hand(palm: Vec3, *, index_tip: Vec3 = None, knuckles=KNUCKLES) -> HandFrame:
    return HandFrame(
        frame_id=1, timestamp=0, hand_id=1, side="Right",
        palm=palm, palm_velocity=ORIGIN, palm_normal=Vec3(0.0, -1.0, 0.0),
        pinch_strength=0.0, pinch_distance=80.0, grab_strength=0.0,
        extended=(True,) * 5, index_tip=index_tip, knuckles=knuckles,
    )


# --- the frame carries only what is read -------------------------------------

def test_dead_fields_are_gone():
    """palm_stable in particular: always (0,0,0) on this hardware, and consuming
    it once zeroed the whole system."""
    names = {f.name for f in dataclasses.fields(HandFrame)}
    assert not names & {"palm_stable", "palm_direction", "confidence", "grab_angle"}


def test_only_the_index_fingertip_is_built():
    """Four of five fingertips were allocated per frame and never read."""
    names = {f.name for f in dataclasses.fields(HandFrame)}
    assert "fingertips" not in names
    assert "index_tip" in names


# --- tracking point ----------------------------------------------------------

def test_index_is_the_tracked_point():
    f = hand(Vec3(0.0, 90.0, 0.0), index_tip=Vec3(5.0, 120.0, -30.0))
    assert f.track_point("index") == Vec3(5.0, 120.0, -30.0)


def test_center_is_the_knuckle_mean():
    assert hand(Vec3(0.0, 90.0, 10.0)).center == Vec3(0.0, 100.0, 0.0)


def test_center_ignores_finger_curl():
    """palm.position is the centroid of a deforming surface, so curling the
    fingers to pinch shifts it several mm — the cursor crept at the exact moment
    of holding still on a target. The knuckle line does not move."""
    assert hand(Vec3(0.0, 90.0, 0.0)).center == hand(Vec3(6.0, 84.0, 5.0)).center


def test_track_point_falls_back_when_a_tip_is_missing():
    f = hand(Vec3(3.0, 90.0, 4.0), index_tip=None)
    assert f.track_point("index") == f.center


# --- eccentricity drives the edge guard --------------------------------------

def test_eccentricity_is_zero_directly_above_the_device():
    assert hand(Vec3(0.0, 150.0, 0.0)).eccentricity == 0.0


def test_eccentricity_grows_toward_the_edge_of_the_cone():
    angles = [hand(Vec3(x, 150.0, 0.0)).eccentricity for x in (0, 60, 120, 240)]
    assert angles == sorted(angles)
    assert angles[-1] > 55.0


# --- engagement --------------------------------------------------------------

def test_engagement_reads_a_real_height():
    from leapinput.capture import Snapshot
    from leapinput.gestures import Config, GestureEngine, Intent

    seen = []
    engine = GestureEngine(Config(plane="xz", engage_dwell=0.0))
    engine.subscribe(lambda e: seen.append(e.intent))
    engine.on_snapshot(Snapshot(right=hand(Vec3(0.0, 232.0, 0.0))))
    assert Intent.ENGAGE in seen
