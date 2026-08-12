"""Gesture-layer tests. No hardware required — frames are synthesized.

The point of these is the failure modes that are miserable to debug by waving at a
sensor: chatter at a threshold, and state left held when tracking drops out.
"""

import dataclasses

import pytest

from leapinput.capture import HandFrame, Snapshot, Vec3
from leapinput.gestures import Config, GestureEngine, Intent, Schmitt

ORIGIN = Vec3(0.0, 0.0, 0.0)


FRAME_US = 9_000          # ~110 fps, matching the real device


def frame(**kw) -> HandFrame:
    base = dict(
        frame_id=1, timestamp=0, hand_id=1, side="Right", confidence=1.0,
        palm=Vec3(0.0, 150.0, 0.0), palm_stable=ORIGIN, palm_velocity=ORIGIN,
        palm_normal=ORIGIN, palm_direction=ORIGIN,
        pinch_strength=0.0, pinch_distance=80.0,
        grab_strength=0.0, grab_angle=0.0,
        extended=(True,) * 5, fingertips=(ORIGIN,) * 5,
    )
    base.update(kw)
    return HandFrame(**base)


def drive(engine: GestureEngine, frames) -> list[Intent]:
    """Feed frames with advancing timestamps.

    The engine clocks off the sensor's frame timestamps, so a fixture that stamps
    every frame at t=0 freezes time and silently suppresses every dwell and
    refractory window. Real frames always advance; the fixture must too.
    """
    seen: list[Intent] = []
    engine.subscribe(lambda e: seen.append(e.intent))
    for i, f in enumerate(frames):
        if f is None:
            engine.on_snapshot(Snapshot())
        else:
            engine.on_snapshot(Snapshot(right=dataclasses.replace(
                f, timestamp=f.timestamp + i * FRAME_US)))
    return [i for i in seen if i is not Intent.POINT_MOVE]


# --- Schmitt trigger --------------------------------------------------------

def test_schmitt_high_signal_latches_and_releases():
    s = Schmitt(on_at=0.85, off_at=0.55)
    assert s.update(0.9, 0.0) is True
    assert s.update(0.7, 0.1) is None      # inside the band: holds
    assert s.update(0.5, 0.2) is False


def test_schmitt_low_signal_orientation():
    """pinch_distance: smaller means engaged, so on_at < off_at."""
    s = Schmitt(on_at=22.0, off_at=38.0)
    assert s.update(18.0, 0.0) is True
    assert s.update(30.0, 0.1) is None
    assert s.update(45.0, 0.2) is False


def test_schmitt_rejects_chatter_across_a_single_threshold():
    """A bare threshold would fire on every one of these samples."""
    s = Schmitt(on_at=0.85, off_at=0.55)
    edges = [s.update(v, i * 0.01) for i, v in enumerate([0.84, 0.86, 0.84, 0.86, 0.84])]
    assert edges.count(True) == 1
    assert edges.count(False) == 0         # never dropped below off_at


def test_schmitt_dwell_suppresses_a_transient():
    s = Schmitt(on_at=0.85, off_at=0.55, dwell=0.05)
    assert s.update(0.9, 0.00) is None     # crossed, but not for long enough
    assert s.update(0.4, 0.01) is None     # went away again: no event ever fired
    assert s.state is False


# --- engagement -------------------------------------------------------------

def test_engages_above_threshold_and_disengages_below():
    engine = GestureEngine(Config(engage_dwell=0.0))
    seen = drive(engine, [frame(palm=Vec3(0, 150, 0)),
                          frame(palm=Vec3(0, 40, 0))])
    assert seen == [Intent.ENGAGE, Intent.DISENGAGE]


def test_resting_hand_never_engages():
    engine = GestureEngine(Config(engage_dwell=0.0))
    assert drive(engine, [frame(palm=Vec3(0, 30, 0))] * 5) == []


def test_no_intents_emitted_while_disengaged():
    """A pinch below the engage height must not click anything."""
    engine = GestureEngine(Config(engage_dwell=0.0))
    seen = drive(engine, [frame(palm=Vec3(0, 30, 0), pinch_distance=10.0)] * 3)
    assert seen == []


# --- the safety property ----------------------------------------------------

def test_tracking_loss_releases_a_held_button():
    """The failure that leaves the machine with a stuck mouse button."""
    engine = GestureEngine(Config(engage_dwell=0.0, pinch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=10.0), None])
    assert seen == [Intent.ENGAGE, Intent.SELECT_DOWN, Intent.SELECT_UP,
                    Intent.DISENGAGE]


def test_dropping_below_engage_height_releases_a_held_button():
    engine = GestureEngine(Config(engage_dwell=0.0, pinch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=10.0),
                          frame(palm=Vec3(0, 40, 0), pinch_distance=10.0)])
    assert seen[-2:] == [Intent.SELECT_UP, Intent.DISENGAGE]


def test_select_up_precedes_disengage():
    """Order matters: the button must come up while the pointer is still driven."""
    engine = GestureEngine(Config(engage_dwell=0.0, pinch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=10.0), None])
    assert seen.index(Intent.SELECT_UP) < seen.index(Intent.DISENGAGE)


# --- gesture disambiguation -------------------------------------------------

def test_fist_reads_as_grab_not_pinch():
    """A closed fist collapses pinch_distance too. It must not fire SELECT."""
    engine = GestureEngine(Config(engage_dwell=0.0, pinch_dwell=0.0, grab_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=8.0, grab_strength=0.95,
                                         extended=(False,) * 5)])
    assert Intent.SELECT_DOWN not in seen
    assert Intent.GRAB_DOWN in seen


def test_swipe_fires_once_then_respects_refractory():
    engine = GestureEngine(Config(engage_dwell=0.0, swipe_refractory=10.0))
    fast = frame(palm_velocity=Vec3(900.0, 0.0, 0.0))
    seen = drive(engine, [frame(), fast, fast, fast])
    assert seen.count(Intent.SWIPE_RIGHT) == 1


def test_swipe_suppressed_during_a_drag():
    engine = GestureEngine(Config(engage_dwell=0.0, pinch_dwell=0.0))
    dragging = frame(pinch_distance=10.0, palm_velocity=Vec3(900.0, 0.0, 0.0))
    seen = drive(engine, [frame(), dragging])
    assert Intent.SWIPE_RIGHT not in seen


def test_scroll_requires_the_two_finger_pose():
    engine = GestureEngine(Config(engage_dwell=0.0))
    moving = frame(palm_velocity=Vec3(0.0, 0.0, 50.0))
    assert Intent.SCROLL not in drive(engine, [frame(), moving])

    engine = GestureEngine(Config(engage_dwell=0.0))
    posed = frame(palm_velocity=Vec3(0.0, 0.0, 50.0),
                  extended=(False, True, True, False, False))
    assert Intent.SCROLL in drive(engine, [frame(), posed])
