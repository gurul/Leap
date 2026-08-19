"""Discrete-command layer: pose-holds, fire-on-release, and the pane rect.

Frames are synthesized at ~30fps (33ms), the camera cadence these dwells were
sized for. Every temporal claim is driven through timestamps, matching how the
engines clock off the sensor.
"""

from leapinput.capture import HandFrame, Snapshot, Vec3
from leapinput.commands import (Command, CommandEngine, PoseHold, frame_rect,
                                is_frame_pose, is_ily_pose, is_ok_pose,
                                is_pinch_hold, is_thumbs_up, is_v_pose)

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


def test_fire_on_fill_fires_mid_hold_exactly_once():
    hold = PoseHold(arm=0.1, dwell=0.5, fire_on_fill=True)
    t, fires = 0.0, []
    while t < 2.0:                          # hold far past the fill
        if hold.update(True, t):
            fires.append(t)
        t += 0.033
    assert len(fires) == 1
    assert abs(fires[0] - 0.6) < 0.05       # arm + dwell, not at release
    # the eventual release must not fire a second time
    assert hold.update(False, t + 0.05) is False    # grace running
    assert hold.update(False, t + 0.30) is False    # grace elapsed: no re-fire
    # and the next hold starts a fresh cycle
    hold.update(True, 3.0)
    assert hold.update(True, 3.7) is True


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


def test_ily_pause_fires_while_still_holding_the_pose():
    """The chime must not wait for the release — pause commits at ring-fill."""
    engine = CommandEngine(hand="Right")
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < 2.0:                    # ILY held the whole time, no release
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, ILY)))
    toggles = [e for e in fired if e.command is Command.TOGGLE]
    assert len(toggles) == 1 and toggles[0].data["enabled"] is False


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


# --- dictation (thumbs-up push-to-talk) --------------------------------------

THUMBS_UP = (True, False, False, False, False)


def test_thumbs_up_toggles_the_mic_on_then_off():
    engine = CommandEngine(hand="Right")
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    def feed(seconds, extended):
        nonlocal t
        end = t / 1e6 + seconds
        while t / 1e6 < end:
            t += FRAME_US
            engine.on_snapshot(Snapshot(right=frame("Right", t, extended)))
    feed(1.5, THUMBS_UP)                    # long hold: fires ONCE (mic on)
    feed(0.5, OPEN)                         # release: mic stays on
    edges = [e.data["active"] for e in fired if e.command is Command.DICTATE]
    assert edges == [True]
    feed(1.0, THUMBS_UP)                    # second thumbs-up: mic off
    edges = [e.data["active"] for e in fired if e.command is Command.DICTATE]
    assert edges == [True, False]


def test_short_thumbs_up_never_opens_the_mic():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(right=frame("Right", t, THUMBS_UP)), hold_s=0.3)
    assert not [e for e in fired if e.command is Command.DICTATE]


def test_hand_is_free_while_dictating():
    """The toggle's whole point: after mic-on the hand can vanish, rest, or
    point without closing the mic — only another thumbs-up (or pause) does."""
    wall = {"t": 0.0}
    engine = CommandEngine(hand="Right", clock=lambda: wall["t"])
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < 1.5:
        t += FRAME_US
        wall["t"] = t / 1e6
        engine.on_snapshot(Snapshot(right=frame("Right", t, THUMBS_UP)))
    for _ in range(30):                     # hand gone: empty snapshots
        wall["t"] += FRAME_US / 1e6
        engine.on_snapshot(Snapshot())
    t = int(wall["t"] * 1e6)
    for _ in range(30):                     # hand back, pointing around
        t += FRAME_US
        wall["t"] = t / 1e6
        engine.on_snapshot(Snapshot(right=frame(
            "Right", t, (False, True, False, False, False))))
    edges = [e.data["active"] for e in fired if e.command is Command.DICTATE]
    assert edges == [True]                  # mic never closed


def test_pausing_stops_dictation():
    engine = CommandEngine(hand="Right")
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < 1.0:                    # mic open, pose still held
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, THUMBS_UP)))
    engine.enabled = False                  # leapctl pause / SIGUSR1
    t += FRAME_US
    engine.on_snapshot(Snapshot(right=frame("Right", t, THUMBS_UP)))
    edges = [e.data["active"] for e in fired if e.command is Command.DICTATE]
    assert edges == [True, False]


# --- free-hand clipboard (pinch-hold copy, V-sign paste) ---------------------

V_POSE = (False, True, True, False, False)


def test_free_hand_pinch_hold_copies():
    engine = CommandEngine(hand="Right", pinch_on_mm=50.0)
    fired = hold_release(
        engine,
        lambda t: Snapshot(left=frame("Left", t, (False, True, True, True, True),
                                      pinch=30.0)),
        hold_s=0.9)
    assert [e for e in fired if e.command is Command.COPY]
    assert not [e for e in fired if e.command is Command.MISSION_CONTROL]


def test_free_hand_v_sign_pastes():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(left=frame("Left", t, V_POSE)), hold_s=0.9)
    assert [e for e in fired if e.command is Command.PASTE]


def test_cursor_hand_v_sign_does_not_paste():
    """Index+middle on the cursor hand is nearly the pointing posture — the
    clipboard namespace is the free hand ONLY."""
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(right=frame("Right", t, V_POSE)), hold_s=0.9)
    assert not [e for e in fired if e.command is Command.PASTE]


def test_new_pose_predicates():
    assert is_thumbs_up(frame(extended=THUMBS_UP))
    assert not is_thumbs_up(frame(extended=(False,) * 5))   # a fist is a drag
    assert is_v_pose(frame(extended=V_POSE))
    # Thumb is ignored — a natural peace sign often reads thumb-out.
    assert is_v_pose(frame(extended=(True, True, True, False, False)))
    assert not is_v_pose(frame(extended=L_POSE))
    assert not is_v_pose(frame(extended=OPEN))
    # Deliberate pinch: closed thumb-index with a back finger up...
    assert is_pinch_hold(frame(extended=(False, False, True, False, False),
                               pinch=30.0), 50.0)
    # ...but a slack fully-curled hand with the thumb near the index is not.
    assert not is_pinch_hold(frame(extended=(False,) * 5, pinch=30.0), 50.0)
    assert not is_pinch_hold(frame(extended=(False, False, True, False, False),
                                   pinch=70.0), 50.0)


def test_free_hand_ily_fires_enter_not_pause():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(left=frame("Left", t, ILY)), hold_s=0.9)
    assert [e for e in fired if e.command is Command.ENTER]
    assert not [e for e in fired if e.command is Command.TOGGLE]


def test_cursor_hand_ily_pauses_and_never_enters():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(right=frame("Right", t, ILY)), hold_s=2.0)
    assert [e for e in fired if e.command is Command.TOGGLE]
    assert not [e for e in fired if e.command is Command.ENTER]




# --- transition shadows and busy gating --------------------------------------
# The live failure: releasing a click-pinch into an open palm passes through
# the OK shape (back fingers out, thumb-index still close), which armed
# mission control — and `busy` blanked the cursor engine from the very first
# pattern-matching frame.

CLICK_PINCH = (False, True, False, False, False)


def test_busy_waits_for_the_arm_time():
    """One pattern-matching frame must NOT blank the cursor engine — busy
    begins when the ring does, after the arm dwell."""
    engine = CommandEngine(hand="Right")
    t = FRAME_US
    engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=30.0)))
    assert not engine.busy
    while t < 400_000:                      # well past arm (0.15s)
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=30.0)))
    assert engine.busy


def test_pinch_release_transition_never_arms_mission():
    engine = CommandEngine(hand="Right")
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    for _ in range(10):                     # a click-pinch, held
        t += FRAME_US
        engine.on_snapshot(Snapshot(
            right=frame("Right", t, CLICK_PINCH, pinch=15.0)))
    for _ in range(9):                      # ~0.3s of opening: OK-shaped frames
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=30.0)))
        assert not engine.mission.armed, "transition frames must not arm"
        assert not engine.busy
    for _ in range(15):                     # fully open
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=80.0)))
    assert not [e for e in fired if e.command is Command.MISSION_CONTROL]


def test_deliberate_ok_pose_from_rest_still_fires_mission():
    engine = CommandEngine(hand="Right")
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    for _ in range(20):                     # resting open hand, no shadow
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=80.0)))
    for _ in range(25):                     # OK pose past arm + dwell
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=30.0)))
    for _ in range(15):                     # release commits
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN, pinch=80.0)))
    assert [e for e in fired if e.command is Command.MISSION_CONTROL]


def test_fist_release_transition_never_arms_dictation():
    """A fist opens thumb-first — a perfect thumbs-up for a few frames."""
    engine = CommandEngine(hand="Right")
    t = 0
    for _ in range(10):
        t += FRAME_US
        engine.on_snapshot(Snapshot(
            right=frame("Right", t, (False,) * 5, pinch=20.0)))
    for _ in range(9):                      # ~0.3s of thumb-first opening
        t += FRAME_US
        engine.on_snapshot(Snapshot(
            right=frame("Right", t, THUMBS_UP, pinch=40.0)))
        assert not engine.dictate.armed


def test_thumbs_up_formed_without_a_fist_arms_immediately():
    """The shadow must cost nothing on the normal path: a thumbs-up that never
    passed through a full fist (thumb was always out) arms on schedule."""
    engine = CommandEngine(hand="Right")
    t = 0
    for _ in range(20):                     # thumbs-up held ~0.66s
        t += FRAME_US
        engine.on_snapshot(Snapshot(
            right=frame("Right", t, THUMBS_UP, pinch=40.0)))
    assert engine.dictate.progress(t / 1e6) > 0.0
