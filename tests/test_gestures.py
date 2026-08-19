"""Gesture-layer tests. No hardware required — frames are synthesized.

The point of these is the failure modes that are miserable to debug by waving at a
sensor: chatter at a threshold, and state left held when tracking drops out.
"""

import dataclasses

import pytest

from leapinput.capture import HandFrame, Snapshot, Vec3
from leapinput.gestures import (Config, GestureEngine, Intent, Schmitt,
                                palm_down_degrees)

ORIGIN = Vec3(0.0, 0.0, 0.0)


FRAME_US = 9_000          # ~110 fps, matching the real device


def frame(**kw) -> HandFrame:
    base = dict(
        frame_id=1, timestamp=0, hand_id=1, side="Right",
        palm=Vec3(0.0, 150.0, 0.0), palm_velocity=ORIGIN,
        # Palm-down by default: the clutch gates everything below it, so a
        # fixture without it silently tests a system that can never act.
        palm_normal=Vec3(0.0, -1.0, 0.0),
        pinch_strength=0.0, pinch_distance=80.0,
        grab_strength=0.0,
        extended=(True,) * 5, 
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
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0))
    seen = drive(engine, [frame(palm=Vec3(0, 150, 0)),
                          frame(palm=Vec3(0, 40, 0))])
    assert seen == [Intent.ENGAGE, Intent.DISENGAGE]


def test_resting_hand_never_engages():
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0))
    assert drive(engine, [frame(palm=Vec3(0, 30, 0))] * 5) == []


def test_no_intents_emitted_while_disengaged():
    """A pinch below the engage height must not click anything."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0))
    seen = drive(engine, [frame(palm=Vec3(0, 30, 0), pinch_distance=10.0)] * 3)
    assert seen == []


# --- the safety property ----------------------------------------------------

def test_tracking_loss_releases_a_held_button():
    """The failure that leaves the machine with a stuck mouse button.

    Asserts the property, not an exact transcript — the sequence legitimately
    carries clutch events too, and pinning their exact positions would make every
    future vocabulary change look like a safety regression.
    """
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, pinch_dwell=0.0, clutch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=10.0), None])
    assert Intent.SELECT_DOWN in seen and Intent.SELECT_UP in seen
    assert seen.index(Intent.SELECT_UP) > seen.index(Intent.SELECT_DOWN)
    assert seen.index(Intent.SELECT_UP) < seen.index(Intent.DISENGAGE)


def test_dropping_below_engage_height_releases_a_held_button():
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, pinch_dwell=0.0, clutch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=10.0),
                          frame(palm=Vec3(0, 40, 0), pinch_distance=10.0)])
    assert seen[-1] is Intent.DISENGAGE
    assert Intent.SELECT_UP in seen
    assert seen.index(Intent.SELECT_UP) < seen.index(Intent.DISENGAGE)


def test_select_up_precedes_disengage():
    """Order matters: the button must come up while the pointer is still driven."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, pinch_dwell=0.0, clutch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=10.0), None])
    assert seen.index(Intent.SELECT_UP) < seen.index(Intent.DISENGAGE)


# --- gesture disambiguation -------------------------------------------------

def test_fist_reads_as_grab_not_pinch():
    """A closed fist collapses pinch_distance too. It must not fire SELECT."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, pinch_dwell=0.0, grab_dwell=0.0, clutch_dwell=0.0))
    seen = drive(engine, [frame(), frame(pinch_distance=8.0, grab_strength=0.95,
                                         extended=(False,) * 5)])
    assert Intent.SELECT_DOWN not in seen
    assert Intent.GRAB_DOWN in seen


def test_fast_motion_never_fires_a_swipe():
    """Swipes are cut: the motion carries the hand out of the tracking volume,
    so the gesture destroys the tracking it depends on. A live session fired
    swipe.right and swipe.down unintentionally."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0))
    fast = frame(palm_velocity=Vec3(900.0, 0.0, 0.0))
    seen = drive(engine, [frame(), fast, fast, fast])
    assert not any(str(i).startswith("Intent.SWIPE") for i in seen)


# --- clutch ------------------------------------------------------------------

PALM_DOWN = Vec3(0.0, -1.0, 0.0)
PALM_SIDE = Vec3(1.0, 0.0, 0.0)


def test_palm_down_is_zero_degrees():
    assert palm_down_degrees(frame(palm_normal=PALM_DOWN)) == pytest.approx(0.0)
    assert palm_down_degrees(frame(palm_normal=PALM_SIDE)) == pytest.approx(90.0)


def test_clutch_engages_palm_down_and_releases_on_rotation():
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    seen = drive(engine, [frame(palm_normal=PALM_DOWN),
                          frame(palm_normal=PALM_SIDE)])
    assert Intent.CLUTCH_DOWN in seen and Intent.CLUTCH_UP in seen


def test_pointer_does_not_move_without_the_clutch():
    """The ratchet: rotate the palm away and the cursor parks."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    for _ in range(5):
        engine.on_snapshot(Snapshot(right=frame(palm_normal=PALM_SIDE)))
    assert Intent.POINT_MOVE not in seen


def test_clicking_does_not_break_the_clutch():
    """Digit-disjoint by construction — a clutch that shares fingers with the
    click gets broken by every click it is meant to survive."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0,
                                  pinch_dwell=0.0))
    seen = drive(engine, [frame(palm_normal=PALM_DOWN),
                          frame(palm_normal=PALM_DOWN, pinch_distance=10.0),
                          frame(palm_normal=PALM_DOWN, pinch_distance=10.0)])
    assert Intent.SELECT_DOWN in seen
    assert Intent.CLUTCH_UP not in seen


def test_tracking_loss_releases_the_clutch():
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    seen = drive(engine, [frame(palm_normal=PALM_DOWN), None])
    assert seen.index(Intent.CLUTCH_UP) < seen.index(Intent.DISENGAGE)


def test_scroll_requires_a_fist():
    """Scroll moved off the index+middle pose, which was near-identical to the
    natural pointing posture — a live session emitted 61 scrolls inside one clutch
    just from pointing. Grab is the one channel that separates cleanly."""
    cfg = dict(engage_dwell=0.0, clutch_dwell=0.0, grab_dwell=0.0)

    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", **cfg))
    pointing = frame(palm_velocity=Vec3(0.0, 0.0, 50.0),
                     extended=(False, True, True, False, False))
    assert Intent.SCROLL not in drive(engine, [frame(), pointing])

    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", scroll_interval=0.0, **cfg))
    fist = lambda z: frame(palm=Vec3(0.0, 150.0, z), grab_strength=0.95,
                           extended=(False,) * 5)
    # Position control: the fist must TRAVEL, not merely be held.
    assert Intent.SCROLL in drive(engine, [frame(), fist(0.0), fist(10.0), fist(20.0)])


def test_a_held_still_fist_does_not_scroll():
    """The runaway: rate control kept scrolling for as long as the fist was held,
    measured at ~7700 px/sec. Position control stops when the hand stops."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0,
                                  grab_dwell=0.0, scroll_interval=0.0))
    still = frame(palm=Vec3(0.0, 150.0, 0.0), grab_strength=0.95,
                  extended=(False,) * 5)
    assert Intent.SCROLL not in drive(engine, [frame()] + [still] * 40)


def test_scroll_is_bounded_by_hand_travel():
    """Total scroll must be proportional to distance moved, not to time held."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0,
                                  grab_dwell=0.0, scroll_interval=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e))
    fist = lambda z: frame(palm=Vec3(0.0, 150.0, z), grab_strength=0.95,
                           extended=(False,) * 5)
    frames = [frame()] + [fist(i * 0.5) for i in range(60)]   # 30mm of travel
    drive(engine, frames)
    total = sum(abs(e.data.get("dy", 0.0)) for e in seen if e.intent is Intent.SCROLL)
    # 30mm at 3px/mm = ~90px, not the thousands rate control produced.
    assert total <= 150.0, f"scrolled {total:.0f}px for 30mm of hand travel"


def test_a_fist_cannot_also_latch_a_click():
    """A fist collapses pinch_distance to ~15mm. The live log shows grab.down then
    select.down with no release, leaving the button held through 400+ scrolls."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0,
                                  grab_dwell=0.0, pinch_dwell=0.0))
    fist = frame(grab_strength=0.95, pinch_distance=15.0, extended=(False,) * 5)
    seen = drive(engine, [frame(), fist, fist, fist])
    assert Intent.GRAB_DOWN in seen
    assert Intent.SELECT_DOWN not in seen


def test_clicks_are_gated_on_the_clutch():
    """Releasing the clutch is lifting the mouse; its button does nothing mid-air.
    A live session fired select.down/up after clutch.up while repositioning."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0, pinch_dwell=0.0))
    parked_and_pinching = frame(palm_normal=Vec3(1.0, 0.0, 0.0), pinch_distance=10.0)
    seen = drive(engine, [frame(), parked_and_pinching, parked_and_pinching])
    assert Intent.SELECT_DOWN not in seen


# --- interaction plane -------------------------------------------------------

PALM_FORWARD = Vec3(0.0, 0.0, -1.0)


def test_clutch_reference_follows_the_plane():
    """The posture that DEFINES upright mode is the posture that RELEASES a
    palm-down clutch, so the reference has to move with the plane."""
    upright = frame(palm_normal=PALM_FORWARD, palm=Vec3(0, 150, 0))
    flat = frame(palm_normal=PALM_DOWN, palm=Vec3(0, 150, 0))

    xy = GestureEngine(Config(plane="xy", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    assert Intent.CLUTCH_DOWN in drive(xy, [upright, upright])

    xz = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    assert Intent.CLUTCH_DOWN in drive(xz, [flat, flat])


def test_a_flat_palm_does_not_clutch_in_upright_mode():
    xy = GestureEngine(Config(plane="xy", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    flat = frame(palm_normal=PALM_DOWN, palm=Vec3(0, 150, 0))
    assert Intent.CLUTCH_DOWN not in drive(xy, [flat, flat])


def test_upright_mode_drops_the_height_floor():
    """Height is the control axis in xy, so a meaningful floor would disengage the
    user for the crime of moving the cursor downward."""
    low = frame(palm_normal=PALM_FORWARD, palm=Vec3(0, 60, 0))
    xy = GestureEngine(Config(plane="xy", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    assert Intent.ENGAGE in drive(xy, [low])

    xz = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    assert Intent.ENGAGE not in drive(xz, [frame(palm_normal=PALM_DOWN,
                                                 palm=Vec3(0, 60, 0))])


# --- click stabilisation (arXiv 2603.15991: hand errors are 95.7% misses) -----

def test_cursor_freezes_as_a_click_forms():
    """Hand pointing fails by missing, not by misfiring. Pinching curls the index
    — the tracked point — so the last millimetres of a click drag the cursor off
    target. Freeze progressively instead."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e))
    for d in (80.0, 50.0, 40.0, 36.0):
        engine.on_snapshot(Snapshot(right=frame(pinch_distance=d)))
    settles = [e.data["settle"] for e in seen if e.intent is Intent.POINT_MOVE]
    assert settles == sorted(settles, reverse=True), "must decrease monotonically"
    assert settles[0] == 1.0 and settles[-1] == 0.0


def test_an_open_hand_moves_at_full_speed():
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e))
    engine.on_snapshot(Snapshot(right=frame(pinch_distance=80.0)))
    moves = [e for e in seen if e.intent is Intent.POINT_MOVE]
    assert moves and moves[-1].data["settle"] == 1.0


# --- finger ladder: 0 = grab, 1 = point, 2+ = lifted -------------------------

def ladder(engine, counts):
    """Drive the engine through a sequence of extended-finger counts."""
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for n in counts:
        ext = tuple(i < n for i in range(5))
        for _ in range(40):            # clear even the 0.25s lift debounce
            t += 9000
            engine.on_snapshot(Snapshot(right=frame(
                timestamp=t, extended=ext,
                grab_strength=0.95 if n == 0 else 0.0)))
    return [i for i in seen if i is not Intent.POINT_MOVE]


def cfg_fingers(**kw):
    return Config(plane="xz", clutch_mode="fingers", engage_dwell=0.0, **kw)


def test_an_open_hand_lifts_the_mouse():
    """Four or more fingers, because a pinch reads as three."""
    seen = ladder(GestureEngine(cfg_fingers()), [1, 5])
    assert seen[-1] is Intent.CLUTCH_UP


def test_three_fingers_do_not_lift_the_mouse():
    """A pinch is 3 extended; lifting there would park the cursor at the exact
    moment of the click."""
    seen = ladder(GestureEngine(cfg_fingers()), [1, 3])
    assert Intent.CLUTCH_UP not in seen


def test_one_finger_engages_the_cursor():
    seen = ladder(GestureEngine(cfg_fingers()), [5, 1])
    assert Intent.CLUTCH_DOWN in seen


def test_fist_grabs_while_still_engaged():
    """A fist is the button, and dragging must keep working — so a fist must NOT
    lift the mouse."""
    seen = ladder(GestureEngine(cfg_fingers()), [1, 0])
    assert Intent.GRAB_DOWN in seen
    assert Intent.CLUTCH_UP not in seen


def test_lifting_releases_a_held_grab():
    """Opening the hand mid-drag must drop the button before parking."""
    seen = ladder(GestureEngine(cfg_fingers()), [0, 5])
    assert seen.index(Intent.GRAB_UP) < seen.index(Intent.CLUTCH_UP)


def test_pinch_never_clicks_in_finger_mode():
    """Pinch is model-inferred exactly where thumb and index occlude. On this
    corpus a deliberate pinch read as 3 extended fingers — indistinguishable from
    a partly open hand — so it drives nothing."""
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for _ in range(30):
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, pinch_distance=8.0,
            extended=(False, False, True, True, True))))
    assert Intent.SELECT_DOWN not in seen


def test_a_single_dropped_frame_does_not_flip_state():
    """Finger count is discrete, so hysteresis has to be time. One bad frame of
    finger tracking must not lift the mouse mid-gesture."""
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for i in range(40):
        t += 9000
        n = 4 if i == 20 else 1        # one spurious open-hand frame
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, extended=tuple(k < n for k in range(5)))))
    assert Intent.CLUTCH_UP not in seen


# --- settle latch: drags must move (plan item 1, 2026-08-18) -----------------

def test_settle_returns_to_full_gain_once_the_pinch_latches():
    """A held pinch sits at ~15mm — far below settle_full — for its whole
    duration. Settle exists to stabilise a FORMING click; once the button is
    latched the gesture is a drag and the cursor must move at full gain."""
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm",
                                  engage_dwell=0.0, clutch_dwell=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e))
    t = 0
    for d in (80.0, 45.0, 45.0, 45.0, 45.0, 15.0, 15.0, 15.0):
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(timestamp=t, pinch_distance=d)))
    downs = [i for i, e in enumerate(seen) if e.intent is Intent.SELECT_DOWN]
    assert downs, "the pinch must latch"
    after = [e.data["settle"] for e in seen[downs[0]:]
             if e.intent is Intent.POINT_MOVE]
    assert after and all(s == 1.0 for s in after), \
        f"drag frames must carry settle=1.0, got {after}"


def test_settle_reaches_zero_at_the_firing_threshold():
    """The freeze must complete AT pinch_on, not 12mm past it — the click has to
    post on a stopped cursor."""
    cfg = Config(plane="xz", clutch_mode="palm", engage_dwell=0.0, clutch_dwell=0.0)
    assert cfg.settle_full_mm == cfg.pinch_on_mm
    engine = GestureEngine(cfg)
    seen = []
    engine.subscribe(lambda e: seen.append(e))
    # Distance parked exactly at the on-threshold: not yet latched (dwell), but
    # the settle ramp must already read 0.0.
    engine.on_snapshot(Snapshot(right=frame(timestamp=9000,
                                            pinch_distance=cfg.pinch_on_mm)))
    moves = [e for e in seen if e.intent is Intent.POINT_MOVE]
    assert moves and moves[-1].data["settle"] == 0.0


def test_a_fist_drag_carries_full_gain():
    """Fist = button down + cursor still moves. The fist collapses raw pinch
    distance below settle_full, which used to pin gain at zero for the whole
    drag."""
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e))
    t = 0
    for _ in range(40):
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, extended=(False,) * 5,
            pinch_distance=15.0, grab_strength=0.95)))
    assert any(e.intent is Intent.GRAB_DOWN for e in seen)
    after = [e.data["settle"] for e in seen if e.intent is Intent.POINT_MOVE
             and seen.index(e) > next(i for i, x in enumerate(seen)
                                      if x.intent is Intent.GRAB_DOWN)]
    assert after and all(s == 1.0 for s in after)


# --- fist may not start a pinch (plan item 4, 2026-08-18) --------------------

def test_a_closing_fist_cannot_start_a_pinch():
    """On the way shut a fist collapses thumb-index distance through the pinch
    band. The debounced count must win: GRAB_DOWN fires, SELECT_DOWN never."""
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    # Two pointing frames, then the fist lands: count 0 with a collapsed,
    # high-strength pinch signal — exactly the race that stole the drag.
    frames = ([((False, True, False, False, False), 80.0, 0.0)] * 2
              + [((False,) * 5, 12.0, 1.0)] * 40)
    for ext, d, s in frames:
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, extended=ext, pinch_distance=d, pinch_strength=s,
            grab_strength=0.95 if d < 20 else 0.0)))
    assert Intent.GRAB_DOWN in seen
    assert Intent.SELECT_DOWN not in seen


def test_a_latched_pinch_hands_the_button_to_the_fist_silently():
    """Pinch closing into a fist: one physical button, no release mid-gesture.
    The pinch latch transfers to grab without an intervening SELECT_UP."""
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    # A real pinch first (1-2 extended, strong signal), then the fist closes.
    for ext, d, s in ([((False, True, False, False, False), 15.0, 0.9)] * 20
                      + [((False,) * 5, 12.0, 0.9)] * 40):
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, extended=ext, pinch_distance=d, pinch_strength=s,
            grab_strength=0.95 if ext == (False,) * 5 else 0.0)))
    assert Intent.SELECT_DOWN in seen
    assert Intent.GRAB_DOWN in seen
    # No release between the two downs: the button never came up mid-gesture.
    sel_down = seen.index(Intent.SELECT_DOWN)
    grab_down = seen.index(Intent.GRAB_DOWN)
    between = seen[sel_down:grab_down]
    assert Intent.SELECT_UP not in between
    assert Intent.GRAB_UP not in between


# --- --no-clutch must work in finger mode (plan item 8, 2026-08-18) ----------

def test_clutch_bypass_is_reachable_in_finger_mode():
    """--no-clutch is the advertised stuck-cursor escape hatch. It used to be
    dead code in the default finger vocabulary: even a parked open hand must
    move the cursor under bypass."""
    engine = GestureEngine(cfg_fingers(clutch_enabled=False))
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for _ in range(5):
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(timestamp=t,
                                                extended=(True,) * 5)))
    assert Intent.CLUTCH_DOWN in seen
    assert Intent.POINT_MOVE in seen


# --- no-drag mode: pinch is the only button (2026-08-18) ---------------------

def test_no_drag_keeps_the_fist_inert():
    """grab_enabled=False: a fist neither presses the button nor lifts the
    mouse — it just moves the cursor like pointing does."""
    seen = ladder(GestureEngine(cfg_fingers(grab_enabled=False)), [1, 0])
    assert Intent.GRAB_DOWN not in seen
    assert Intent.CLUTCH_UP not in seen


def test_no_drag_never_steals_a_held_pinch():
    """With the fist inert there is no pinch->fist handover: a latched pinch
    whose finger count collapses to 0 keeps the button held (the drag), and
    releases only when the pinch opens."""
    engine = GestureEngine(cfg_fingers(grab_enabled=False,
                                       pinch_min_strength=0.0))
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    def feed(n, ext, pinch):
        nonlocal t
        for _ in range(n):
            t += 9000
            engine.on_snapshot(Snapshot(right=frame(
                timestamp=t, extended=ext, pinch_distance=pinch,
                pinch_strength=0.9)))
    feed(30, (True, True, False, False, False), 80.0)   # engaged, open pinch
    feed(30, (True, True, False, False, False), 10.0)   # pinch: button down
    assert Intent.SELECT_DOWN in seen
    feed(30, (False,) * 5, 10.0)                        # collapses to a fist
    assert Intent.SELECT_UP not in seen                 # still dragging
    assert Intent.GRAB_DOWN not in seen
    feed(30, (True, True, False, False, False), 80.0)   # pinch opens
    assert Intent.SELECT_UP in seen


# --- pinch release assist (2026-08-18) ---------------------------------------

def _pinch_frames(engine, distances, ext=(False, True, True, False, False)):
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for d in distances:
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, extended=ext, pinch_distance=d, pinch_strength=0.9)))
    return seen


def test_relaxed_half_open_hand_releases_the_click():
    """After a click, a naturally relaxed hand parks INSIDE the 50-68mm
    hysteresis band and used to hold the button forever. Sustained distance
    above the engage threshold is release intent."""
    engine = GestureEngine(cfg_fingers())
    seen = _pinch_frames(engine,
                         [80.0] * 20 + [10.0] * 20    # click
                         + [55.0] * 40)               # relaxed: in the band
    assert Intent.SELECT_DOWN in seen
    assert Intent.SELECT_UP in seen                   # assist released it


def test_a_real_pinch_drag_is_never_assist_released():
    engine = GestureEngine(cfg_fingers())
    seen = _pinch_frames(engine,
                         [80.0] * 20 + [16.0] * 300)  # 2.7s held pinch
    assert Intent.SELECT_DOWN in seen
    assert Intent.SELECT_UP not in seen


def test_a_noise_spike_inside_the_band_does_not_release():
    """1-2 frames above the engage threshold mid-drag are landmark noise
    (the reason the hysteresis band exists); the assist must wait them out."""
    engine = GestureEngine(cfg_fingers())
    seen = _pinch_frames(engine,
                         [80.0] * 20 + [16.0] * 30
                         + [55.0] * 2                 # 18ms spike
                         + [16.0] * 30)
    assert Intent.SELECT_DOWN in seen
    assert Intent.SELECT_UP not in seen


# --- kinematic pinch gate (2026-08-18) ---------------------------------------
# Measured on the phone source: 24 of 28 presses in one live session latched
# MID-FLIGHT (median 550px of held travel; 1 true click). People decelerate to
# near-stillness before selecting (RIDS, UIST 2022), so a pinch-shaped read at
# speed is a tracking artifact, not a click.

PINCH_POSE = dict(pinch_distance=20.0, pinch_strength=0.9,
                  extended=(False, True, False, False, False))


def test_a_pinch_cannot_latch_mid_flight():
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for _ in range(30):                     # pinch-shaped, but travelling fast
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, palm_velocity=Vec3(400.0, 0.0, 0.0), **PINCH_POSE)))
    assert Intent.SELECT_DOWN not in seen
    for _ in range(10):                     # the hand stops: same pinch latches
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(timestamp=t, **PINCH_POSE)))
    assert Intent.SELECT_DOWN in seen


def test_a_latched_pinch_drags_and_releases_at_full_speed():
    """The gate is onset-only: drags move fast, and a release is NEVER
    blocked — a stuck button is worse than any missed click."""
    engine = GestureEngine(cfg_fingers())
    seen = []
    engine.subscribe(lambda e: seen.append(e.intent))
    t = 0
    for _ in range(20):                     # latch while still (the finger
        t += 9000                           # debounce eats the first ~6 frames)
        engine.on_snapshot(Snapshot(right=frame(timestamp=t, **PINCH_POSE)))
    assert Intent.SELECT_DOWN in seen
    fast = Vec3(500.0, 0.0, 0.0)
    for _ in range(10):                     # drag at speed: stays held
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, palm_velocity=fast, **PINCH_POSE)))
    assert Intent.SELECT_UP not in seen
    for _ in range(10):                     # open while still fast: releases
        t += 9000
        engine.on_snapshot(Snapshot(right=frame(
            timestamp=t, palm_velocity=fast, pinch_distance=80.0,
            extended=(False, True, False, False, False))))
    assert Intent.SELECT_UP in seen


def test_settle_does_not_freeze_a_fast_hand():
    """No click can latch during fast travel (the gate above), so a
    pinch-shaped read out there must not stutter the cursor either."""
    engine = GestureEngine(cfg_fingers())
    in_band = 52.0          # between settle_full (50) and settle_start (55)
    slow = frame(pinch_distance=in_band)
    fast = frame(pinch_distance=in_band, palm_velocity=Vec3(400.0, 0.0, 0.0))
    assert engine._settle_factor(slow) < 1.0
    assert engine._settle_factor(fast) == 1.0
