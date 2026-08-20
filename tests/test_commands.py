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


def test_hand_loss_at_a_full_ring_cancels_instead_of_firing():
    """A vanished hand is a tracking loss, not a release — the hold must
    reset without committing (present=False past grace is the cancel path)."""
    hold = PoseHold(arm=0.1, dwell=0.5)
    t = 0.0
    while t < 0.8:                          # held to a full ring
        assert hold.update(True, t) is False
        t += 0.033
    assert hold.progress(t) == 1.0
    # a single lost frame inside grace is still just a flicker
    assert hold.update(False, t + 0.03, present=False) is False
    assert hold.update(True, t + 0.06) is False
    # loss past grace: reset, NO fire
    assert hold.update(False, t + 0.10, present=False) is False
    assert hold.update(False, t + 0.30, present=False) is False
    assert hold.progress(t + 0.4) == 0.0


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

def hold_release(engine, make_snap, hold_s, release_extended=OPEN,
                 release_side="Right"):
    """Drive: pose held hold_s seconds at 30fps, then 0.5s of released frames.
    The releasing hand(s) stay TRACKED with the pose off — a deliberate
    release. A hand that VANISHES at a full ring is a tracking loss, which
    cancels instead of committing (see the loss tests)."""
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < hold_s:
        t += FRAME_US
        engine.on_snapshot(make_snap(t))
    for _ in range(15):
        t += FRAME_US
        if release_side == "Both":
            engine.on_snapshot(Snapshot(
                left=frame("Left", t, release_extended),
                right=frame("Right", t, release_extended)))
        elif release_side == "Left":
            engine.on_snapshot(Snapshot(left=frame("Left", t, release_extended)))
        else:
            engine.on_snapshot(Snapshot(right=frame("Right", t, release_extended)))
    return fired


def test_finger_frame_spawns_a_pane_with_the_rect():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine,
        lambda t: both_hands(t, Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)),
        hold_s=1.0, release_side="Both")
    panes = [e for e in fired if e.command is Command.NEW_PANE]
    assert len(panes) == 1
    x0, y0, x1, y1 = panes[0].data["rect"]
    assert x0 < x1 and y0 < y1


def test_a_short_frame_hold_is_a_no_op():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine,
        lambda t: both_hands(t, Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)),
        hold_s=0.3, release_side="Both")
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
        hold_s=0.9, release_side="Left")
    assert [e for e in fired if e.command is Command.COPY]
    assert not [e for e in fired if e.command is Command.MISSION_CONTROL]


def test_free_hand_v_sign_pastes():
    engine = CommandEngine(hand="Right")
    fired = hold_release(
        engine, lambda t: Snapshot(left=frame("Left", t, V_POSE)), hold_s=0.9,
        release_side="Left")
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
        engine, lambda t: Snapshot(left=frame("Left", t, ILY)), hold_s=0.9,
        release_side="Left")
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


def test_hand_vanishing_at_a_full_ring_fires_no_command():
    """Engine-level loss regression: an OK pose held past a full ring, then
    the hand vanishes — tracking loss must cancel, never release-fire."""
    wall = {"t": 0.0}
    engine = CommandEngine(hand="Right", clock=lambda: wall["t"])
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    ok = (False, True, True, True, True)
    while t / 1e6 < 0.9:                    # held well past arm + dwell
        t += FRAME_US
        wall["t"] = t / 1e6
        engine.on_snapshot(Snapshot(right=frame("Right", t, ok, pinch=30.0)))
    assert engine.mission.progress(t / 1e6) == 1.0
    for _ in range(15):                     # hand gone, well past grace
        wall["t"] += FRAME_US / 1e6
        engine.on_snapshot(Snapshot())
    assert fired == []


def test_free_hand_holds_never_blank_the_cursor():
    """COPY/PASTE/ENTER live on the hand the cursor ignores — arming them
    must not set `busy`, which would force-release an in-progress drag on
    the cursor hand."""
    engine = CommandEngine(hand="Right")
    t = 0
    while t < 400_000:                      # well past arm (0.15s)
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, V_POSE)))
    assert engine.paste.progress(t / 1e6) > 0.0
    assert not engine.busy


def test_pinch_shadow_blocks_the_pause_toggle():
    """A held click-pinch sheds ILY-shaped misread frames (middle+ring stay
    curled); arming the pause there would blank the cursor engine mid-drag."""
    engine = CommandEngine(hand="Right")
    t = 0
    for _ in range(10):                     # a click-pinch, held (dragging)
        t += FRAME_US
        engine.on_snapshot(Snapshot(
            right=frame("Right", t, CLICK_PINCH, pinch=15.0)))
    for _ in range(9):                      # ILY-shaped misreads, pinch closed
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, ILY, pinch=15.0)))
        assert not engine.toggle.armed, "shadowed frames must not arm the pause"
        assert not engine.busy


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


# --- the free hand's fist holds the mouse button ------------------------------

def fist_snap(t_us, present=True, cursor_extended=OPEN):
    """Free hand (Left) fisted, cursor hand (Right) present and neutral."""
    return Snapshot(
        left=frame("Left", t_us, (False,) * 5) if present else None,
        right=frame("Right", t_us, cursor_extended))


def drag_events(engine, snaps):
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    for s in snaps:
        engine.on_snapshot(s)
    return [(e.command, e.data.get("active")) for e in fired
            if e.command is Command.DRAG]


def test_a_free_hand_fist_presses_and_holds():
    engine = CommandEngine(hand="Right")
    t = 0
    snaps = []
    while t / 1e6 < 0.5:                        # past DRAG_ARM_S
        t += FRAME_US
        snaps.append(fist_snap(t))
    assert drag_events(engine, snaps) == [(Command.DRAG, True)]


def test_a_fist_shorter_than_the_arm_never_presses():
    """A hand closing on its way somewhere else must not drag."""
    engine = CommandEngine(hand="Right")
    t, snaps = 0, []
    while t / 1e6 < 0.10:                       # under DRAG_ARM_S (0.18)
        t += FRAME_US
        snaps.append(fist_snap(t))
    for _ in range(6):
        t += FRAME_US
        snaps.append(Snapshot(left=frame("Left", t, OPEN),
                              right=frame("Right", t, OPEN)))
    assert drag_events(engine, snaps) == []


def test_opening_the_fist_releases_the_button():
    engine = CommandEngine(hand="Right")
    t, snaps = 0, []
    while t / 1e6 < 0.5:
        t += FRAME_US
        snaps.append(fist_snap(t))
    for _ in range(3):
        t += FRAME_US
        snaps.append(Snapshot(left=frame("Left", t, OPEN),
                              right=frame("Right", t, OPEN)))
    assert drag_events(engine, snaps) == [(Command.DRAG, True),
                                          (Command.DRAG, False)]


def test_a_vanished_free_hand_releases_the_button():
    """Dead-man: tracking loss must drop the button on the same frame."""
    engine = CommandEngine(hand="Right")
    t, snaps = 0, []
    while t / 1e6 < 0.5:
        t += FRAME_US
        snaps.append(fist_snap(t))
    t += FRAME_US
    snaps.append(fist_snap(t, present=False))   # free hand gone
    assert drag_events(engine, snaps)[-1] == (Command.DRAG, False)


def test_pausing_mid_drag_releases_the_button():
    """A button held by a fist nobody is watching must not outlive the pause."""
    engine = CommandEngine(hand="Right")
    t, snaps = 0, []
    while t / 1e6 < 0.5:
        t += FRAME_US
        snaps.append(fist_snap(t))
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    for s in snaps:
        engine.on_snapshot(s)
    assert engine._dragging is True
    engine.enabled = False
    t += FRAME_US
    engine.on_snapshot(fist_snap(t))            # still fisted, engine paused
    assert (Command.DRAG, False) in [(e.command, e.data.get("active"))
                                     for e in fired]
    assert engine._dragging is False


def test_the_free_hand_fist_does_not_fire_copy_paste_or_enter():
    """A fist must be unambiguous against the other free-hand poses."""
    f = frame("Left", 0, (False,) * 5)
    assert not is_pinch_hold(f, 50.0) and not is_v_pose(f) and not is_ily_pose(f)


# --- minimal mode: four gestures, nothing else -------------------------------

def minimal() -> CommandEngine:
    return CommandEngine(hand="Right", minimal=True)


def fired_for(engine, pose, side="Left", hold_s=0.9):
    return hold_release(engine, lambda t: Snapshot(**{side.lower(): frame(side, t, pose)}),
                        hold_s=hold_s, release_side=side)


def test_minimal_keeps_the_four():
    """mic, Enter, paste, frame shot — the whole shipped vocabulary."""
    assert [e.command for e in fired_for(minimal(), ILY)] == [Command.ENTER]
    assert [e.command for e in fired_for(minimal(), V_POSE)] == [Command.PASTE]
    assert [e.command for e in fired_for(minimal(), THUMBS_UP)] == [Command.DICTATE]

    engine = minimal()
    fired = hold_release(engine, lambda t: both_hands(t, Vec3(-80.0, 260.0, 0.0),
                                                      Vec3(80.0, 380.0, 0.0)),
                         hold_s=1.0, release_side="Both")
    assert [e.command for e in fired] == [Command.NEW_PANE]


def test_minimal_drops_everything_else():
    """Mission Control, copy, the fist drag and the ILY pause are unwired —
    the poses can be made and nothing happens."""
    ok_pose = (False, True, True, True, True)
    assert fired_for(minimal(), ok_pose) == []                  # no MISSION
    engine = minimal()
    assert drag_events(engine, [fist_snap(t * FRAME_US) for t in range(1, 20)]) == []

    # COPY needs a pinch-hold; minimal must not fire it (Cmd+C is React Grab's)
    engine = minimal()
    fired = hold_release(
        engine,
        lambda t: Snapshot(left=frame("Left", t, (False, True, True, True, True),
                                      pinch=20.0)),
        hold_s=0.9, release_side="Left")
    assert [e for e in fired if e.command is Command.COPY] == []

    # The fist is unbound in minimal: no drag, and no pause either (ILY keeps
    # the pause, so the fist is free rather than doubling up).
    engine = minimal()
    assert drag_events(engine, [fist_snap(t * FRAME_US) for t in range(1, 40)]) == []


def test_minimal_keeps_the_ily_pause_on_the_cursor_hand():
    """Pause survives the strip unchanged: ILY on the configured hand toggles,
    ILY on the other submits. The one pose whose meaning is hand-dependent."""
    engine = minimal()
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < 2.2:                        # past the long pause dwell
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, ILY)))
    assert [(e.command, e.data.get("enabled")) for e in fired] \
        == [(Command.TOGGLE, False)]
    assert engine.enabled is False

    # ...and it is still the way back in while disabled.
    while t / 1e6 < 3.0:                        # let the pose drop first
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, OPEN)))
    while t / 1e6 < 5.5:
        t += FRAME_US
        engine.on_snapshot(Snapshot(right=frame("Right", t, ILY)))
    assert engine.enabled is True


def test_minimal_ily_on_the_free_hand_is_still_enter():
    engine = minimal()
    assert [e.command for e in fired_for(engine, ILY, side="Left")] \
        == [Command.ENTER]
    assert engine.enabled is True               # never paused


def test_minimal_pause_silences_the_other_three():
    engine = minimal()
    engine.enabled = False
    assert [e.command for e in fired_for(engine, V_POSE)] == []
    assert [e.command for e in fired_for(engine, THUMBS_UP)] == []


def test_minimal_fires_from_either_hand():
    """Everything except ILY answers to whichever hand is up."""
    for side in ("Left", "Right"):
        assert [e.command for e in fired_for(minimal(), V_POSE, side=side)] \
            == [Command.PASTE]
        assert [e.command for e in fired_for(minimal(), THUMBS_UP, side=side)] \
            == [Command.DICTATE]


def test_legacy_still_has_the_whole_vocabulary():
    """Nothing was deleted — --legacy must restore it exactly."""
    engine = CommandEngine(hand="Right")            # minimal=False
    assert [e.command for e in fired_for(engine, V_POSE)] == [Command.PASTE]
    engine = CommandEngine(hand="Right")
    assert drag_events(engine, [fist_snap(t * FRAME_US) for t in range(1, 20)]) \
        == [(Command.DRAG, True)]


# --- the frame shot commits the composition, not the release ------------------

def test_release_frames_cannot_distort_the_committed_rect():
    """The reported defect (2026-08-20, live use): "frame sets up perfectly...
    whenever I try to release out, it kinda distorts the frame".

    `extended` is a Schmitt trigger, so a finger uncurling out of the L keeps
    reading as extended for several frames while the hand is already moving.
    Those frames still classify as framing — and they were the ones the commit
    sampled.
    """
    engine = minimal()
    fired = []
    engine.subscribe(lambda e: fired.append(e))

    STEADY_L = Vec3(-80.0, 260.0, 0.0)
    STEADY_R = Vec3(80.0, 380.0, 0.0)
    t = 0
    while t / 1e6 < 1.2:                        # compose, held steady
        t += FRAME_US
        engine.on_snapshot(both_hands(t, STEADY_L, STEADY_R))
    # The release: fingers moving, pose STILL classified as framing.
    for i in range(1, 5):
        t += FRAME_US
        engine.on_snapshot(both_hands(t,
                                      Vec3(-80.0 + i * 25, 260.0 + i * 20, 0.0),
                                      Vec3(80.0 - i * 25, 380.0 - i * 20, 0.0)))
    for _ in range(8):                          # pose finally drops -> fires
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, OPEN),
                                    right=frame("Right", t, OPEN)))

    panes = [e for e in fired if e.command is Command.NEW_PANE]
    assert len(panes) == 1
    steady = frame_rect(frame("Left", 0, L_POSE, index_tip=STEADY_L),
                        frame("Right", 0, L_POSE, index_tip=STEADY_R))
    got = panes[0].data["rect"]
    for a, b in zip(got, steady):
        assert abs(a - b) < 1e-6, f"release contaminated the rect: {got} vs {steady}"


def test_a_single_landmark_spike_cannot_move_the_rect():
    """Median, not mean: one bad corner frame inside the settle window would
    drag an average, and a rect corner is exactly where a spike lands."""
    engine = minimal()
    fired = []
    engine.subscribe(lambda e: fired.append(e))

    STEADY_L, STEADY_R = Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)
    t = 0
    while t / 1e6 < 1.0:
        t += FRAME_US
        spike = (t / 1e6 > 0.80 and t / 1e6 < 0.84)     # one frame, far off
        engine.on_snapshot(both_hands(
            t,
            Vec3(-150.0, 200.0, 0.0) if spike else STEADY_L,
            STEADY_R))
    for _ in range(10):
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, OPEN),
                                    right=frame("Right", t, OPEN)))

    panes = [e for e in fired if e.command is Command.NEW_PANE]
    assert len(panes) == 1
    steady = frame_rect(frame("Left", 0, L_POSE, index_tip=STEADY_L),
                        frame("Right", 0, L_POSE, index_tip=STEADY_R))
    for a, b in zip(panes[0].data["rect"], steady):
        assert abs(a - b) < 1e-6


def test_a_short_hold_still_commits_something_sane():
    """Held only just long enough to fill the ring: everything on record sits
    inside the guard, and the commit must still be a real rect."""
    engine = CommandEngine(hand="Right", minimal=True)
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    t = 0
    while t / 1e6 < 0.85:                       # ~ arm + dwell, no more
        t += FRAME_US
        engine.on_snapshot(both_hands(t, Vec3(-80.0, 260.0, 0.0),
                                      Vec3(80.0, 380.0, 0.0)))
    for _ in range(8):
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, OPEN),
                                    right=frame("Right", t, OPEN)))
    panes = [e for e in fired if e.command is Command.NEW_PANE]
    assert len(panes) == 1
    x0, y0, x1, y1 = panes[0].data["rect"]
    assert x0 < x1 and y0 < y1


# --- one composition, one command --------------------------------------------

def test_forming_the_frame_pose_cannot_open_the_mic():
    """The L-pose is thumbs-up plus an extended index, so a hand entering or
    leaving the frame gesture passes THROUGH thumbs-up. Reported live: "it
    also triggers the mic sometimes"."""
    engine = minimal()
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    L, R = Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)
    t = 0
    while t / 1e6 < 1.0:                        # compose: arms the pane hold
        t += FRAME_US
        engine.on_snapshot(both_hands(t, L, R))
    # Break it the way a hand really does: one index drops first, so THIS hand
    # now reads as a clean thumbs-up while the other is still an L.
    while t / 1e6 < 1.9:
        t += FRAME_US
        engine.on_snapshot(Snapshot(
            left=frame("Left", t, THUMBS_UP, index_tip=L),
            right=frame("Right", t, L_POSE, index_tip=R)))
    assert [e.command for e in fired if e.command is Command.DICTATE] == []
    assert engine._dictating is False


def test_the_frame_shadow_blocks_every_other_command():
    """One composition, one command — nothing else fires until it is done."""
    engine = minimal()
    L, R = Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)
    t = 0
    while t / 1e6 < 1.0:
        t += FRAME_US
        engine.on_snapshot(both_hands(t, L, R))

    for pose, cmd in ((V_POSE, Command.PASTE), (ILY, Command.ENTER),
                      (THUMBS_UP, Command.DICTATE)):
        fired = []
        e2 = minimal()
        e2.subscribe(lambda ev: fired.append(ev))
        t2 = 0
        while t2 / 1e6 < 1.0:                   # arm a composition
            t2 += FRAME_US
            e2.on_snapshot(both_hands(t2, L, R))
        while t2 / 1e6 < 1.5:                   # then try to fire something else
            t2 += FRAME_US
            e2.on_snapshot(Snapshot(left=frame("Left", t2, pose),
                                    right=frame("Right", t2, OPEN)))
        assert [x for x in fired if x.command is cmd] == [], \
            f"{cmd} fired inside the frame shadow"


def test_the_shadow_expires_so_normal_use_resumes():
    engine = minimal()
    L, R = Vec3(-80.0, 260.0, 0.0), Vec3(80.0, 380.0, 0.0)
    t = 0
    while t / 1e6 < 1.0:
        t += FRAME_US
        engine.on_snapshot(both_hands(t, L, R))
    while t / 1e6 < 1.0 + engine.FRAME_SHADOW_S + 0.3:   # let it lapse
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, OPEN),
                                    right=frame("Right", t, OPEN)))
    fired = []
    engine.subscribe(lambda e: fired.append(e))
    while t / 1e6 < 3.5:
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, V_POSE)))
    for _ in range(12):
        t += FRAME_US
        engine.on_snapshot(Snapshot(left=frame("Left", t, OPEN)))
    assert [e.command for e in fired] == [Command.PASTE]
