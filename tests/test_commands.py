"""Discrete-command layer: pose-holds, fire-on-release, and the pane rect.

Frames are synthesized at ~30fps (33ms), the camera cadence these dwells were
sized for. Every temporal claim is driven through timestamps, matching how the
engines clock off the sensor.
"""

from leapinput.capture import HandFrame, Snapshot, Vec3
from leapinput.commands import (Command, CommandEngine, PoseHold, frame_rect,
                                is_frame_pose, is_ily_pose, is_ok_pose)

ORIGIN = Vec3(0.0, 0.0, 0.0)
FRAME_US = 33_000

L_POSE = (True, True, False, False, False)      # thumb + index
ILY = (True, True, False, False, True)
OPEN = (True,) * 5


def frame(side="Right", t_us=0, extended=OPEN, pinch=80.0,
          index_tip=Vec3(0.0, 350.0, 0.0)) -> HandFrame:
    return HandFrame(
        frame_id=1, timestamp=t_us, hand_id=0 if side == "Left" else 1,
        side=side, palm=Vec3(0.0, 350.0, 0.0), palm_velocity=ORIGIN,
        palm_normal=Vec3(0.0, 0.0, -1.0), pinch_strength=0.5,
        pinch_distance=pinch, grab_strength=0.0, extended=extended,
        index_tip=index_tip,
    )


def run(engine, snaps_and_times):
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    for snap in snaps_and_times:
        engine.on_snapshot(snap)
    return fired


def both_hands(t_us, l_tip, r_tip, extended=L_POSE):
    return Snapshot(
        left=frame("Left", t_us, extended, index_tip=l_tip),
        right=frame("Right", t_us, extended, index_tip=r_tip),
    )


# --- PoseHold semantics ------------------------------------------------------

def test_a_flicker_never_starts_a_ring():
    hold = PoseHold(arm=0.15, dwell=0.5)
    assert hold.update(True, 0.0) is False
    assert hold.progress(0.10) == 0.0          # under arm: no ring yet
    assert hold.update(False, 0.13) is False   # released before arming
    assert hold.update(False, 0.30) is False   # ...and past grace: reset, no fire


def test_fire_on_release_only_when_full():
    hold = PoseHold(arm=0.1, dwell=0.5)
    t = 0.0
    while t < 0.7:
        assert hold.update(True, t) is False   # holding never fires
        t += 0.033
    assert hold.progress(t) == 1.0
    # a single dropped frame inside grace does not commit or cancel
    assert hold.update(False, t + 0.03) is False
    assert hold.update(True, t + 0.06) is False
    # a real release commits
    assert hold.update(False, t + 0.10) is False    # grace running
    assert hold.update(False, t + 0.30) is True     # grace elapsed: FIRE


def test_early_release_cancels():
    hold = PoseHold(arm=0.1, dwell=0.5)
    hold.update(True, 0.0)
    hold.update(True, 0.2)                  # ~20% full
    assert hold.update(False, 0.25) is False
    assert hold.update(False, 0.50) is False    # past grace: cancelled, no fire
    assert hold.progress(0.6) == 0.0


# --- pose tests --------------------------------------------------------------

def test_pose_predicates():
    assert is_frame_pose(frame(extended=L_POSE))
    assert not is_frame_pose(frame(extended=OPEN))
    assert is_ily_pose(frame(extended=ILY))
    assert is_ok_pose(frame(extended=(False, True, True, True, True), pinch=30.0), 50.0)
    assert not is_ok_pose(frame(extended=(False, True, True, True, True), pinch=70.0), 50.0)
    assert not is_ok_pose(frame(extended=(False, True, False, False, False), pinch=30.0), 50.0)


def test_frame_rect_is_the_index_tip_diagonal():
    a = frame("Left", index_tip=Vec3(-80.0, 260.0, 0.0))    # left, low
    b = frame("Right", index_tip=Vec3(80.0, 380.0, 0.0))    # right, high
    x0, y0, x1, y1 = frame_rect(a, b)
    assert x0 < 0.5 < x1
    assert y0 < y1
    # PLANE geometry: x=-80 -> 0.25, x=80 -> 0.75; y=380 -> top ~0.25
    assert abs(x0 - 0.25) < 1e-6 and abs(x1 - 0.75) < 1e-6


# --- the engine --------------------------------------------------------------

def hold_release(engine, make_snap, hold_s, release_extended=OPEN):
    """Drive: pose held hold_s seconds at 30fps, then 0.5s of released frames."""
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < hold_s:
        t += FRAME_US
        engine.on_snapshot(make_snap(t))
    for _ in range(15):
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, release_extended)))
    return fired


def test_finger_frame_spawns_a_pane_with_the_rect():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine,
        lambda t: both_hands(t, Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)),
        hold_s=1.0)
    panes = [e for e in fired if e.command is Command.NEW_PANE]
    assert len(panes) == 1
    x0, y0, x1, y1 = panes[0].data["rect"]
    assert x0 < x1 and y0 < y1


def test_a_short_frame_hold_is_a_no_op():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine,
        lambda t: both_hands(t, Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)),
        hold_s=0.3)
    assert not [e for e in fired if e.command is Command.NEW_PANE]


def test_ily_toggles_off_and_back_on():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(right=frame("Right", t, ILY)), hold_s=2.0)
    toggles = [e for e in fired if e.command is Command.TOGGLE]
    assert len(toggles) == 1 and toggles[0].data["enabled"] is False
    assert engine.enabled is False
    # While disabled, the pane is dead...
    fired2 = hold_release(
        engine,
        lambda t: both_hands(t, Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)),
        hold_s=1.0)
    assert not [e for e in fired2 if e.command is Command.NEW_PANE]
    # ...but ILY is the way back in.
    fired3 = hold_release(
        engine, lambda t: Snapshot(right=frame("Right", t, ILY)), hold_s=2.0)
    toggles3 = [e for e in fired3 if e.command is Command.TOGGLE]
    assert len(toggles3) == 1 and toggles3[0].data["enabled"] is True


def test_ok_pose_fires_mission_control():
    engine = CommandEngine(hand="Right", pinch_on_mm=50.0)
    ok = (False, True, True, True, True)
    fired = hold_release(
        engine,
        lambda t: Snapshot(right=frame("Right", t, ok, pinch=30.0)),
        hold_s=0.9)
    assert [e for e in fired if e.command is Command.MISSION_CONTROL]


def test_open_hand_alone_fires_nothing():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(right=frame("Right", t, OPEN)), hold_s=2.0)
    assert fired == []
