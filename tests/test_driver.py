"""Driver tests — the two bugs found in live use, pinned.

Both were invisible to every prior test because both need a real desk and a real
second monitor to show up.
"""

import dataclasses
import math

from leapinput.actions import DryRunBackend
from leapinput.capture import HandFrame, Vec3
from leapinput.driver import DirectDriver, Mapping
from leapinput.gestures import Intent, IntentEvent

ORIGIN = Vec3(0.0, 0.0, 0.0)

# A two-display layout matching this machine: the second panel sits ABOVE and LEFT
# of the main one, so its CG origin is negative on both axes.
LAPTOP_PLUS_MONITOR = (-541.0, -1440.0, 2019.0, 982.0)


def frame(x, y, z, t_us, vx=0.0, vz=0.0) -> HandFrame:
    """A hand at (x,y,z). Fingertips and knuckles ride with it, so the frame is
    valid for whichever tracking_point the driver is configured to follow."""
    at = Vec3(x, y, z)
    tips = tuple(Vec3(x + dx, y + 30.0, z - 60.0) for dx in (-20, -6, 4, 14, 24))
    knuckles = tuple(Vec3(x + dx, y + 10.0, z) for dx in (-20, -7, 7, 20))
    return HandFrame(
        frame_id=1, timestamp=t_us, hand_id=1, side="Right",
        palm=at, palm_velocity=Vec3(vx, 0.0, vz),
        palm_normal=Vec3(0.0, -1.0, 0.0),
        pinch_strength=0.0, pinch_distance=80.0, grab_strength=0.0,
        extended=(True,) * 5, index_tip=tips[1], knuckles=knuckles,
    )


def drive(driver, frames):
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frames[0]))
    for f in frames:
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, f.timestamp / 1e6, f))


def make(mapping=None, bounds=LAPTOP_PLUS_MONITOR):
    backend = DryRunBackend(bounds=bounds)
    return DirectDriver(backend, mapping or Mapping(plane="xz")), backend


# --- inversion --------------------------------------------------------------

def test_left_right_is_inverted_by_default():
    """Confirmed by use on this desk 2026-08-12: without this the cursor mirrors
    your hand horizontally."""
    assert Mapping(plane="xz").invert_x is True
    assert Mapping(plane="xz").invert_z is False


def test_hand_toward_user_moves_cursor_down_by_default():
    """+z is toward the user; CG +y is down. Confirmed by use: pull the hand back
    and the cursor comes down the screen; push it away and it goes up."""
    driver, _ = make()
    start = driver.y
    drive(driver, [frame(0, 150, 0, 0), frame(0, 150, 20, 100_000)])
    assert driver.y > start


def test_inversion_is_configurable_per_axis():
    a, _ = make(Mapping(plane="xz", invert_z=False))
    b, _ = make(Mapping(plane="xz", invert_z=True))
    for d in (a, b):
        drive(d, [frame(0, 150, 0, 0), frame(0, 150, 20, 100_000)])
    assert (a.y - 491.0) == -(b.y - 491.0), "invert_z must mirror the motion exactly"


def test_invert_x_mirrors_horizontal_motion():
    a, _ = make(Mapping(plane="xz", invert_x=False))
    b, _ = make(Mapping(plane="xz", invert_x=True))
    for d in (a, b):
        drive(d, [frame(0, 150, 0, 0), frame(20, 150, 0, 100_000)])
    assert (a.x - 756.0) == -(b.x - 756.0)


# --- multi-monitor ----------------------------------------------------------

def test_cursor_can_reach_a_display_above_and_left_of_main():
    """The live bug: clamping to (0,0,w,h) traps the cursor on the main display,
    because a second monitor placed up-left has NEGATIVE CG coordinates."""
    driver, _ = make()
    # Up-left with the shipped defaults (invert_x=True): hand RIGHT (+x) maps to
    # cursor-left, and away from the user (-z) maps to cursor-up.
    frames = [frame(i * 4.0, 150, -i * 4.0, i * 9000, vx=500.0, vz=-500.0)
              for i in range(60)]
    drive(driver, frames)
    assert driver.x < 0.0, "never crossed onto the left-hand display"
    assert driver.y < 0.0, "never crossed onto the upper display"


def test_cursor_is_clamped_to_the_union_not_the_main_screen():
    driver, _ = make()
    frames = [frame(i * 20.0, 150, -i * 20.0, i * 9000, vx=900.0, vz=-900.0)
              for i in range(200)]
    drive(driver, frames)
    assert driver.x >= -541.0 and driver.y >= -1440.0, "escaped the desktop union"


def test_single_display_still_clamps_at_zero():
    driver, _ = make(bounds=(0.0, 0.0, 1512.0, 982.0))
    frames = [frame(i * 20.0, 150, -i * 20.0, i * 9000, vx=900.0, vz=-900.0)
              for i in range(200)]
    drive(driver, frames)
    assert driver.x >= 0.0 and driver.y >= 0.0


# --- the ratchet ------------------------------------------------------------

def test_reclutching_does_not_teleport_the_cursor():
    """The whole point of relative control. Move, release, move the hand somewhere
    completely different, re-engage — the cursor stays put."""
    driver, _ = make()
    drive(driver, [frame(0, 150, 0, 0), frame(10, 150, 0, 100_000)])
    parked = (driver.x, driver.y)

    driver.on_intent(IntentEvent(Intent.CLUTCH_UP, 0.0, None))
    far = frame(200, 150, 90, 500_000)
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, far))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.5, far))

    assert (driver.x, driver.y) == parked


# --- tracking point ---------------------------------------------------------

def test_index_fingertip_is_the_default_pointer():
    assert Mapping(plane="xz").tracking_point == "index"


def test_every_tracking_point_produces_motion():
    """Each mode must actually follow the hand — a mis-wired selector that always
    returned a constant would silently freeze the cursor."""
    for kind in ("index", "knuckles", "palm"):
        driver, _ = make(Mapping(plane="xz", tracking_point=kind))
        start = driver.x
        drive(driver, [frame(0, 150, 0, 0), frame(30, 150, 0, 100_000)])
        assert driver.x != start, f"{kind} did not move the cursor"


def test_knuckles_mode_ignores_finger_curl():
    """The rigid alternative: moving the index tip must not move the cursor."""
    driver, _ = make(Mapping(plane="xz", tracking_point="knuckles"))
    a = frame(0, 150, 0, 0)
    curled = dataclasses.replace(frame(0, 150, 0, 100_000),
                                 index_tip=Vec3(-25.0, 130.0, 30.0))
    drive(driver, [a, curled])
    assert (driver.x, driver.y) == (756.0, 491.0)


# --- the upright (xy) plane -------------------------------------------------

def test_xz_is_the_default_plane():
    """Measured, not chosen: over 590 tracked frames of real use the palm sat
    18.9 deg off down (100% clutchable) versus 85.4 deg off forward (0%), and the
    desk plane produced 816px of vertical travel against xy's 410px."""
    assert Mapping().plane == "xz"


def test_raising_the_hand_raises_the_cursor_in_xy():
    """The upright model: hand height drives screen height directly."""
    driver, _ = make(Mapping(plane="xy"))
    start = driver.y
    drive(driver, [frame(0, 150, 0, 0), frame(0, 200, 0, 100_000)])
    assert driver.y < start, "raising the hand should move the cursor up"


def test_lowering_the_hand_lowers_the_cursor_in_xy():
    driver, _ = make(Mapping(plane="xy"))
    start = driver.y
    drive(driver, [frame(0, 200, 0, 0), frame(0, 150, 100_000)] if False else
                  [frame(0, 200, 0, 0), frame(0, 150, 0, 100_000)])
    assert driver.y > start


def test_xy_ignores_hand_depth():
    """Pushing the hand toward or away from the screen must not move the cursor
    in the upright model — only the plane it is drawing on counts."""
    driver, _ = make(Mapping(plane="xy"))
    before = (driver.x, driver.y)
    drive(driver, [frame(0, 150, 0, 0), frame(0, 150, 60, 100_000)])
    assert (driver.x, driver.y) == before


def test_xz_ignores_hand_height():
    """The mirror property: hovering higher must not move a top-down cursor."""
    driver, _ = make(Mapping(plane="xz"))
    before = (driver.x, driver.y)
    drive(driver, [frame(0, 150, 0, 0), frame(0, 220, 0, 100_000)])
    assert (driver.x, driver.y) == before


# --- edge constraint ---------------------------------------------------------

def at(x, z=0.0, y=150.0):
    return frame(x, y, z, 0)


def test_cursor_moves_freely_in_the_reliable_core():
    driver, _ = make()
    assert driver._edge_factor(at(0)) == 1.0
    assert driver._edge_factor(at(120)) == 1.0


def test_motion_is_damped_toward_the_edge_of_the_cone():
    """LMC1 palm error rises from ~8mm centrally to RMS >20mm at the extremes, so
    raw motion out there is largely noise. At high gain that noise is what throws
    the cursor across the screen and 'beyond the plane'."""
    driver, _ = make()
    factors = [driver._edge_factor(at(x)) for x in (120, 160, 200, 260)]
    assert factors == sorted(factors, reverse=True)
    assert factors[-1] < 0.2


def test_motion_stops_completely_past_the_usable_cone():
    driver, _ = make()
    assert driver._edge_factor(at(400)) == 0.0


def test_edge_damping_limits_runaway_travel():
    """The end-to-end property: a hand sweeping far out of the cone must not keep
    dragging the cursor at full gain."""
    near, far = make()[0], make()[0]
    for driver, xs in ((near, range(0, 60)), (far, range(200, 260))):
        frames = [frame(x * 2.0, 150, 0, i * 9000, vx=400.0)
                  for i, x in enumerate(xs)]
        drive(driver, frames)
    assert abs(far.x - 756.0) < abs(near.x - 756.0), \
        "edge travel should move the cursor less than core travel"


# --- intent routing ----------------------------------------------------------

def test_a_fist_presses_a_real_mouse_button():
    """The bug: the vocabulary moved to fist-as-click, but the driver only had
    handlers for select.*, so grab.down was emitted into nothing for a whole
    session and the click silently did nothing."""
    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.0, None))
    driver.on_intent(IntentEvent(Intent.GRAB_UP, 0.0, None))
    assert [c[0] for c in backend.calls] == ["down", "up"]


def test_an_unrouted_intent_is_reported_not_swallowed(capsys):
    """Silent getattr dispatch is what let the missing grab handler survive.
    Every intent that is neither handled nor explicitly ignored must complain."""
    driver, _ = make()

    class Fake(str):
        name = "TOTALLY_UNROUTED"
        value = "totally.unrouted"

    driver.on_intent(IntentEvent(Fake("x"), 0.0, None))
    assert "no handler" in capsys.readouterr().err


def test_deliberately_ignored_intents_stay_quiet(capsys):
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.ENGAGE, 0.0, None))
    assert capsys.readouterr().err == ""


# --- one button, two intents -------------------------------------------------

def test_a_pinch_closing_into_a_fist_is_one_click():
    """The live nesting: select.down, grab.down, grab.up, select.up on a single
    gesture. Pinch and fist are one continuum and drive ONE physical button, so
    naive routing posts down/down/up/up and macOS loses track of the drag."""
    driver, backend = make()
    for intent in (Intent.SELECT_DOWN, Intent.GRAB_DOWN,
                   Intent.GRAB_UP, Intent.SELECT_UP):
        driver.on_intent(IntentEvent(intent, 0.0, None))
    assert [c[0] for c in backend.calls] == ["down", "up"]


def test_redundant_presses_are_idempotent():
    driver, backend = make()
    for _ in range(5):
        driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.0, None))
    for _ in range(5):
        driver.on_intent(IntentEvent(Intent.GRAB_UP, 0.0, None))
    assert [c[0] for c in backend.calls] == ["down", "up"]


def test_disengage_never_leaves_the_button_held():
    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.0, None))
    driver.on_intent(IntentEvent(Intent.DISENGAGE, 0.0, None))
    assert [c[0] for c in backend.calls] == ["down", "up"]


# --- deadzone accumulation (plan item 2, 2026-08-18) -------------------------

def test_slow_drift_accumulates_instead_of_vanishing():
    """Motion slower than the per-frame deadzone must still arrive. The old code
    advanced the anchor before the deadzone check, permanently eating any hand
    motion under ~deadzone/frame — fine aiming was structurally impossible."""
    driver, _ = make(Mapping(plane="xz", deadzone_mm=0.6,
                             pointer_min_cutoff=1000.0))  # filter ~transparent
    start = driver.x
    frames = [frame(i * 0.3, 150, 0, i * 33_000) for i in range(61)]
    drive(driver, frames)
    # 18mm of total travel at 0.3mm/frame: with an accumulating anchor the
    # cursor must cover it (scaled by gain); consumed per-frame it moved 0.
    assert abs(driver.x - start) > 10.0


def test_alternating_noise_nets_to_nothing():
    """The same accumulator must NOT turn resting jitter into drift."""
    driver, _ = make(Mapping(plane="xz", deadzone_mm=0.6,
                             pointer_min_cutoff=1000.0))
    start = driver.x
    frames = [frame(0.25 if i % 2 else 0.0, 150, 0, i * 33_000)
              for i in range(60)]
    drive(driver, frames)
    assert abs(driver.x - start) < 2.0


# --- click-anchor lifecycle (plan item 3, 2026-08-18) ------------------------

def press_frame(x, z, t_us, pinch_mm) -> HandFrame:
    f = frame(x, 150, z, t_us)
    return dataclasses.replace(f, pinch_distance=pinch_mm, pinch_strength=0.9)


def test_second_click_does_not_teleport_to_the_first_anchor():
    """The anchor must die with its click. It used to survive select_up and
    warp the SECOND click back to the first position."""
    driver, backend = make()
    t = 0.0
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, t, frame(0, 150, 0, 0)))
    # First click at the initial position, anchor armed via a forming pinch.
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 frame(0, 150, 0, 10_000), {"settle": 0.5}))
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.02, frame(0, 150, 0, 20_000)))
    driver.on_intent(IntentEvent(Intent.SELECT_UP, 0.05, frame(0, 150, 0, 50_000)))
    first_xy = (driver.x, driver.y)
    # Move far away (full-settle frames), then click again with a fresh pinch.
    for i in range(2, 30):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, i * 0.033,
                                     frame(i * 8.0, 150, 0, i * 33_000),
                                     {"settle": 1.0}))
    moved_xy = (driver.x, driver.y)
    assert moved_xy != first_xy
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 1.0,
                                 frame(28 * 8.0, 150, 0, 1_000_000),
                                 {"settle": 0.5}))
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 1.03,
                                 frame(28 * 8.0, 150, 0, 1_030_000)))
    assert (driver.x, driver.y) == moved_xy, \
        "second click teleported back to the first click's stale anchor"


def test_a_stale_anchor_is_ignored():
    """Anchor armed, then a second of hesitation: the warp must not happen."""
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 frame(0, 150, 0, 10_000), {"settle": 0.5}))
    anchored = (driver.x, driver.y)
    # Drift a little while the pinch keeps forming (settle < 1 so no re-arm),
    # slowly enough to stay under ANCHOR_MAX_DIST_PX.
    for i in range(1, 10):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01 + i * 0.033,
                                     frame(i * 1.5, 150, 0, 10_000 + i * 33_000),
                                     {"settle": 0.5}))
    drifted = (driver.x, driver.y)
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 1.5,
                                 frame(15.0, 150, 0, 1_500_000)))
    assert (driver.x, driver.y) == drifted != anchored, \
        "a 1.5s-old anchor must not warp the click"


def test_fist_drag_consumes_the_pinch_anchor():
    """A pinch-to-fist handover is silent (no select.up), so a fist-drag used
    to leave the pre-drag anchor alive and warp the NEXT pinch-click back to
    where the hand was aiming before the drag."""
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    # Pinch starts forming: anchor armed at the pre-drag position.
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 frame(0, 150, 0, 10_000), {"settle": 0.5}))
    pre_drag = (driver.x, driver.y)
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.02, frame(0, 150, 0, 20_000)))
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.03, frame(0, 150, 0, 30_000)))
    # A quick short drag: real travel (past CLICK_TRAVEL_PX, so the up is not
    # pinned back) but ending inside the anchor trust bounds, where the stale
    # warp would fire.
    for i in range(1, 9):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.03 + i * 0.033,
                                     frame(i * 4.0, 150, 0, 30_000 + i * 33_000),
                                     {"settle": 1.0}))
    driver.on_intent(IntentEvent(Intent.GRAB_UP, 0.32, frame(32.0, 150, 0, 320_000)))
    dropped = (driver.x, driver.y)
    drift = math.hypot(dropped[0] - pre_drag[0], dropped[1] - pre_drag[1])
    assert DirectDriver.CLICK_TRAVEL_PX < drift < DirectDriver.ANCHOR_MAX_DIST_PX, \
        "test needs the drop point inside the anchor trust bounds"
    # Fresh pinch right where the drag ended; the pinch never fully reopened,
    # so no settle >= 1.0 frame ever cleared the old anchor.
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.37,
                                 frame(32.0, 150, 0, 370_000), {"settle": 0.5}))
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.42,
                                 frame(32.0, 150, 0, 420_000)))
    assert (driver.x, driver.y) == dropped, \
        "next pinch-click warped back to the pre-drag anchor"


def test_fist_click_warps_to_the_anchor_like_a_pinch():
    """grab.down is the same commit as select.down and deserves the same
    Heisenberg correction: a fresh fist warps back to where the hand was
    aiming before the closing fingers dragged the cursor off it."""
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 frame(0, 150, 0, 10_000), {"settle": 0.5}))
    anchored = (driver.x, driver.y)
    for i in range(1, 6):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01 + i * 0.033,
                                     frame(i * 1.5, 150, 0, 10_000 + i * 33_000),
                                     {"settle": 0.5}))
    assert (driver.x, driver.y) != anchored
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.25,
                                 frame(7.5, 150, 0, 250_000)))
    assert (driver.x, driver.y) == anchored, \
        "a fresh fist-click did not get the anchor warp a pinch-click gets"


def test_grab_down_mid_drag_never_warps_a_live_drag():
    """The pinch-into-fist handover emits grab.down while the button is already
    held (no select.up in between): even a fresh, nearby anchor must not
    teleport the drag back to where the click started."""
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.02, frame(0, 150, 0, 20_000)))
    for i in range(1, 15):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.02 + i * 0.033,
                                     frame(i * 4.0, 150, 0, 20_000 + i * 33_000),
                                     {"settle": 1.0}))
    dragged = (driver.x, driver.y)
    # Force the hostile case: an anchor that is fresh and inside the trust
    # bounds at handover time. An unguarded warp would consume it.
    driver._click_anchor = (dragged[0] - 20.0, dragged[1], 0.5)
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.52,
                                 frame(56.0, 150, 0, 520_000)))
    assert (driver.x, driver.y) == dragged, \
        "grab.down handover teleported a live drag back to the click anchor"


def test_grab_up_clears_the_click_anchor():
    """Defensive parity with select.up: no anchor survives a grab cycle."""
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.02, frame(0, 150, 0, 20_000)))
    driver._click_anchor = (driver.x, driver.y, 0.03)   # hostile: re-armed mid-hold
    driver.on_intent(IntentEvent(Intent.GRAB_UP, 0.05, frame(0, 150, 0, 50_000)))
    assert driver._click_anchor is None


def test_click_up_lands_on_the_down_pixel():
    """macOS resolves the click on mouse-up; a click (not a drag) must post
    down and up on the same pixel even if the opening pinch drifts a few px."""
    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.02, frame(0, 150, 0, 20_000)))
    down_xy = (driver.x, driver.y)
    # A few px of drift while the button is held (under CLICK_TRAVEL_PX).
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.05,
                                 frame(0.8, 150, 0, 50_000), {"settle": 1.0}))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.08,
                                 frame(1.6, 150, 0, 80_000), {"settle": 1.0}))
    driver.on_intent(IntentEvent(Intent.SELECT_UP, 0.1, frame(1.6, 150, 0, 100_000)))
    assert (driver.x, driver.y) == down_xy
    # Stronger than it used to be: the pin-back is no longer REACHED, because
    # a pinned pinch never moved the cursor for it to correct (2026-08-20).
    # down then up on the same pixel, with nothing in between.
    assert backend.calls[-2:] == [("down", *down_xy), ("up", *down_xy)]


# --- touch-mode click anchor (2026-08-19) ------------------------------------

def abs_frame(px, py, t_us) -> HandFrame:
    """A frame whose index tip sits at plane-mm (px, py) — the coordinates
    _move_absolute reads in the xy plane."""
    return frame(px + 6.0, py - 30.0, 0.0, t_us)


def test_absolute_click_stays_pinned_after_anchor_warp():
    """Touch mode: the anchor warp at select.down moves the cursor off the LIVE
    hand target, and the next full-settle frame used to lerp straight back —
    the snap accrued into _travel, the <12px pin-back refused, and mouse-up
    posted away from mouse-down: a corrected click became an accidental drag.
    The commit position must hold for the whole button hold."""
    driver, backend = make(Mapping(plane="xy", absolute=True,
                                   pointer_min_cutoff=1000.0),  # ~transparent
                           bounds=(0.0, 0.0, 1512.0, 982.0))
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, abs_frame(0, 260, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 abs_frame(0, 260, 10_000), {"settle": 1.0}))
    aim = (driver.x, driver.y)
    # The closing pinch drags the hand ~47px of target while settle holds the
    # cursor back; the anchor is armed at the aim point on the first frame.
    for i in range(1, 6):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01 + i * 0.033,
                                     abs_frame(i * 2.0, 260, 10_000 + i * 33_000),
                                     {"settle": 0.5}))
    assert (driver.x, driver.y) != aim
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.2,
                                 abs_frame(10.0, 260, 200_000)))
    assert (driver.x, driver.y) == aim          # warped back to the aim point
    # Pinch fully formed: a full-settle frame arrives with the hand still
    # displaced. The cursor must stay pinned at the warp position...
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.23,
                                 abs_frame(10.0, 260, 230_000), {"settle": 1.0}))
    assert (driver.x, driver.y) == aim, \
        "full-settle frame lerped the held click back to the live hand target"
    # ...and the click-up must land on the down pixel.
    driver.on_intent(IntentEvent(Intent.SELECT_UP, 0.3,
                                 abs_frame(10.0, 260, 300_000)))
    down = next(c for c in backend.calls if c[0] == "down")
    assert backend.calls[-1] == ("up", *down[1:])
    assert (driver.x, driver.y) == aim


def test_absolute_cursor_snaps_to_live_target_after_the_click():
    """The touch offset dies with the button: once the click completes, the
    next full-settle frame follows the live hand again."""
    driver, _ = make(Mapping(plane="xy", absolute=True,
                             pointer_min_cutoff=1000.0),
                     bounds=(0.0, 0.0, 1512.0, 982.0))
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, abs_frame(0, 260, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 abs_frame(0, 260, 10_000), {"settle": 1.0}))
    aim = (driver.x, driver.y)
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.04,
                                 abs_frame(2.0, 260, 40_000), {"settle": 0.5}))
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.07,
                                 abs_frame(2.0, 260, 70_000)))
    driver.on_intent(IntentEvent(Intent.SELECT_UP, 0.12,
                                 abs_frame(2.0, 260, 120_000)))
    assert (driver.x, driver.y) == aim          # click pinned to the aim point
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.15,
                                 abs_frame(40.0, 260, 150_000), {"settle": 1.0}))
    assert (driver.x, driver.y) != aim, "offset survived the click"


def _two_display_touch_driver():
    """Main 1920x1080 at the origin, laptop panel 1512x982 to its LEFT."""
    from leapinput.actions import DryRunBackend

    backend = DryRunBackend(screen=(1920.0, 1080.0),
                            bounds=(-1512.0, 0.0, 1920.0, 1080.0),
                            rects=[(0.0, 0.0, 1920.0, 1080.0),
                                   (-1512.0, 0.0, 0.0, 982.0)])
    backend.move(960.0, 540.0)                      # cursor on the main display
    driver = DirectDriver(backend, Mapping(plane="xy", absolute=True,
                                           pointer_min_cutoff=1000.0))
    return driver, backend


def test_touch_map_targets_the_display_the_cursor_is_on():
    """Touch mode maps the hand onto ONE screen, and the cursor picks which:
    park it on the second display and the SAME hand position now addresses
    that display instead of the main one."""
    driver, backend = _two_display_touch_driver()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, abs_frame(0, 260, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 abs_frame(0, 260, 10_000), {"settle": 1.0}))
    assert driver.x >= 0.0, "hand started mapped to the main display"

    backend.move(-700.0, 500.0)                     # user drags it to the laptop
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.4,
                                 abs_frame(0, 260, 400_000), {"settle": 1.0}))
    assert driver._active == (-1512.0, 0.0, 0.0, 982.0)
    assert driver.x < 0.0, "same hand position still aiming at the main display"
    assert backend.calls[-1][0] == "move" and backend.calls[-1][1] < 0


def test_the_touch_map_never_switches_display_mid_hold():
    """Re-basing the map during a drag would teleport it. The cursor crossing
    displays while the button is down is the DRAG doing that, not a request to
    move the map."""
    driver, backend = _two_display_touch_driver()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, abs_frame(0, 260, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 abs_frame(0, 260, 10_000), {"settle": 1.0}))
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.02, abs_frame(0, 260, 20_000)))
    backend.move(-700.0, 500.0)
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.4,
                                 abs_frame(0, 260, 400_000), {"settle": 1.0}))
    assert driver._active == (0.0, 0.0, 1920.0, 1080.0)


def test_a_drag_release_stays_where_it_was_dragged():
    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 150, 0, 0)))
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.02, frame(0, 150, 0, 20_000)))
    for i in range(1, 20):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, i * 0.033,
                                     frame(i * 8.0, 150, 0, i * 33_000),
                                     {"settle": 1.0}))
    dragged = (driver.x, driver.y)
    driver.on_intent(IntentEvent(Intent.GRAB_UP, 0.7, frame(152.0, 150, 0, 700_000)))
    assert (driver.x, driver.y) == dragged


# --- cursor truth (plan item 7, 2026-08-18) ----------------------------------

def test_reclutch_absorbs_external_cursor_motion():
    """Trackpad use between clutches must not snap the cursor back to the
    driver's phantom position: every clutch re-syncs from the backend."""
    driver, backend = make()
    drive(driver, [frame(0, 150, 0, 0), frame(30, 150, 0, 100_000)])
    driver.on_intent(IntentEvent(Intent.CLUTCH_UP, 0.2, None))
    backend._pos = (100.0, 200.0)          # the user moved the mouse
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.3, frame(30, 150, 0, 300_000)))
    assert (driver.x, driver.y) == (100.0, 200.0)


def test_containment_never_lands_in_the_void():
    """Two displays: 1512x982 at (0,0) and 2560x1440 at (-541,-1440). The union
    rectangle contains a void (e.g. right of the laptop, above its top edge);
    the old union clamp could strand the cursor there."""
    from leapinput.actions import DryRunBackend

    backend = DryRunBackend(bounds=LAPTOP_PLUS_MONITOR)
    driver = DirectDriver(backend, Mapping(plane="xz"))
    driver.rects = [(0.0, 0.0, 1512.0, 982.0),
                    (-541.0, -1440.0, 2019.0, 0.0)]

    def inside_some(x, y):
        return any(x0 <= x <= x1 - 1 and y0 <= y <= y1 - 1
                   for x0, y0, x1, y1 in driver.rects)

    # A grid over and past the union, including the void at (1800, 500):
    # right of the laptop's 1512 edge, below the monitor's bottom (y>0).
    for x in (-800.0, -541.0, 0.0, 756.0, 1511.0, 1800.0, 2100.0):
        for y in (-1500.0, -1440.0, -700.0, 0.0, 500.0, 981.0, 1200.0):
            cx, cy = driver._contain(x, y)
            assert inside_some(cx, cy), f"({x},{y}) contained to void ({cx},{cy})"
    # And a point in the void specifically must land on a real display.
    cx, cy = driver._contain(1800.0, 500.0)
    assert inside_some(cx, cy)


def test_click_state_builds_doubles_and_resets():
    from leapinput.actions import next_click_state

    t0 = 100.0
    s1 = next_click_state(1, None, None, t0, (10, 10))
    assert s1 == 1
    s2 = next_click_state(s1, t0 + 0.1, (10, 10), t0 + 0.3, (12, 11))
    assert s2 == 2
    s3 = next_click_state(s2, t0 + 0.5, (12, 11), t0 + 0.8, (12, 12))
    assert s3 == 3
    # A pause resets…
    assert next_click_state(s3, t0 + 1.0, (12, 12), t0 + 1.9, (12, 12)) == 1
    # …and so does distance.
    assert next_click_state(2, t0 + 2.0, (12, 12), t0 + 2.1, (80, 12)) == 1


# --- finger-frame region mapping (2026-08-18) --------------------------------

def test_frame_region_maps_to_screen_pixels():
    from leapinput.driver import frame_region_px

    region = frame_region_px((0.25, 0.25, 0.75, 0.75),
                             (0.0, 0.0, 1512.0, 982.0), 0.05)
    assert region == (378, 245, 756, 491)


def test_frame_region_carries_the_second_display_origin():
    """A display left of the main one has a NEGATIVE origin, and the region
    must land there — not at the same offset on the main screen."""
    from leapinput.driver import frame_region_px

    region = frame_region_px((0.25, 0.25, 0.75, 0.75),
                             (-1512.0, 0.0, 0.0, 982.0), 0.05)
    assert region == (-1134, 245, 756, 491)


def test_a_sloppy_tiny_frame_is_rejected():
    from leapinput.driver import frame_region_px

    screen = (0.0, 0.0, 1512.0, 982.0)
    assert frame_region_px((0.5, 0.2, 0.52, 0.8), screen, 0.05) is None
    assert frame_region_px(None, screen, 0.05) is None


def test_the_frame_shot_follows_the_cursor_to_the_other_display():
    """The whole point: frame a region while working on the second display and
    the shutter fires THERE, not at the same coordinates on the main screen."""
    from leapinput import driver as drv
    from leapinput.actions import DryRunBackend
    from leapinput.commands import Command, CommandEvent

    backend = DryRunBackend(
        screen=(1920.0, 1080.0),
        bounds=(-1512.0, 0.0, 1920.0, 1080.0),
        rects=[(0.0, 0.0, 1920.0, 1080.0),          # main
               (-1512.0, 0.0, 0.0, 982.0)])         # laptop panel, to its left
    backend.move(-700.0, 500.0)                     # cursor on the laptop

    captured = []
    original = drv._screenshot_region
    drv._screenshot_region = lambda *a: captured.append(a)
    try:
        sd = drv.ShortcutDriver(backend)
        sd.on_command(CommandEvent(Command.NEW_PANE, 0.0,
                                   {"rect": (0.25, 0.25, 0.75, 0.75)}))
    finally:
        drv._screenshot_region = original
    assert captured == [(-1134, 245, 756, 491)]


def test_screenshot_pane_presses_no_keys():
    """The screenshot action must not send Cmd+N into the frontmost app."""
    from leapinput import driver as drv
    from leapinput.actions import DryRunBackend
    from leapinput.commands import Command, CommandEvent

    captured = []
    original = drv._screenshot_region
    drv._screenshot_region = lambda *a: captured.append(a)
    try:
        backend = DryRunBackend()
        sd = drv.ShortcutDriver(backend)        # default: screenshot
        sd.on_command(CommandEvent(Command.NEW_PANE, 0.0,
                                   {"rect": (0.2, 0.2, 0.8, 0.8)}))
    finally:
        drv._screenshot_region = original
    assert captured and captured[0][2] > 0      # a real region was captured
    assert not [c for c in backend.calls if c[0] == "key"]


# --- dictation hold and free-hand clipboard (2026-08-18) ---------------------

def _shortcut_driver():
    from leapinput import driver as drv
    from leapinput.actions import DryRunBackend

    backend = DryRunBackend()
    return drv.ShortcutDriver(backend), backend


def _cmd(command, **data):
    from leapinput.commands import Command, CommandEvent
    return CommandEvent(Command(command), 0.0, data)


def test_dictate_holds_and_releases_option():
    sd, backend = _shortcut_driver()
    sd.on_command(_cmd("dictate", active=True))
    sd.on_command(_cmd("dictate", active=False))
    holds = [c for c in backend.calls if c[0] == "key_hold"]
    assert holds == [("key_hold", sd.KEY_OPTION, True, {"alt": True}),
                     ("key_hold", sd.KEY_OPTION, False, {"alt": True})]
    assert sd._dict_timer is None               # watchdog disarmed with the key


def test_dictate_edges_are_idempotent():
    sd, backend = _shortcut_driver()
    sd.on_command(_cmd("dictate", active=True))
    sd.on_command(_cmd("dictate", active=True))     # duplicate start
    sd.release_dictation()
    sd.release_dictation()                          # duplicate stop
    holds = [c for c in backend.calls if c[0] == "key_hold"]
    assert [h[2] for h in holds] == [True, False]


def test_watchdog_fire_invokes_forced_release_callback():
    """A watchdog force-release must tell the state-tracking layer (the CLI's
    snapshot gate), or its next chime plays inverted."""
    sd, backend = _shortcut_driver()
    fired = []
    sd.on_forced_release = lambda: fired.append(True)
    sd.on_command(_cmd("dictate", active=True))
    sd._dictation_watchdog()                    # fire the timer body directly
    assert fired == [True]
    holds = [c for c in backend.calls if c[0] == "key_hold"]
    assert [h[2] for h in holds] == [True, False]


def test_normal_toggle_off_does_not_invoke_forced_release():
    sd, _ = _shortcut_driver()
    fired = []
    sd.on_forced_release = lambda: fired.append(True)
    sd.on_command(_cmd("dictate", active=True))
    sd.on_command(_cmd("dictate", active=False))
    assert fired == []
    # And a watchdog that lost the race to the stop edge stays quiet too:
    # nothing was actually released, so nothing must be reported.
    sd._dictation_watchdog()
    assert fired == []


def test_forced_release_callback_errors_do_not_propagate(capsys):
    """The callback runs on the Timer thread; an error there must not kill it
    (Option is already released by then — cleanup must finish quietly)."""
    def boom():
        raise RuntimeError("chime desync")

    sd, backend = _shortcut_driver()
    sd.on_forced_release = boom
    sd.on_command(_cmd("dictate", active=True))
    sd._dictation_watchdog()                    # must not raise
    holds = [c for c in backend.calls if c[0] == "key_hold"]
    assert [h[2] for h in holds] == [True, False]
    assert "on_forced_release failed" in capsys.readouterr().err


def test_copy_paste_press_cmd_c_and_v():
    sd, backend = _shortcut_driver()
    sd.on_command(_cmd("copy"))
    sd.on_command(_cmd("paste"))
    keys = [c for c in backend.calls if c[0] == "key"]
    assert keys == [("key", sd.KEY_C, {"cmd": True}),
                    ("key", sd.KEY_V, {"cmd": True})]


def test_enter_taps_return():
    sd, backend = _shortcut_driver()
    sd.on_command(_cmd("enter"))
    assert ("key", sd.KEY_RETURN, {}) in backend.calls


def _drive_abs(mapping, step, frames=10):
    """CLUTCH_DOWN then full-settle POINT_MOVEs advancing `step` plane-mm per
    33ms frame; returns cursor travel in px."""
    driver, _ = make(mapping, bounds=(0.0, 0.0, 1512.0, 982.0))
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, abs_frame(50, 260, 0)))
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01,
                                 abs_frame(50, 260, 10_000), {"settle": 1.0}))
    x0 = driver.x
    for i in range(1, frames + 1):
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.01 + i * 0.033,
                                     abs_frame(50 + i * step, 260,
                                               10_000 + i * 33_000),
                                     {"settle": 1.0}))
    return driver, driver.x - x0


def test_touch_precision_scales_slow_motion_down():
    """Slow hand = small target (PRISM): the same slow crawl must travel a
    precision fraction of its 1:1 distance."""
    plain = Mapping(plane="xy", absolute=True, pointer_min_cutoff=1000.0,
                    precision_gain_min=1.0)          # layer off
    prec = Mapping(plane="xy", absolute=True, pointer_min_cutoff=1000.0)
    _, moved_plain = _drive_abs(plain, step=1.0)     # ~140 px/s: aiming speed
    _, moved_prec = _drive_abs(prec, step=1.0)
    assert moved_plain > 0
    assert moved_prec < 0.6 * moved_plain
    assert moved_prec > 0.15 * moved_plain           # scaled, not frozen


def test_touch_precision_is_transparent_at_speed():
    """Ballistic motion stays position-faithful: 1:1 within the deadband."""
    plain = Mapping(plane="xy", absolute=True, pointer_min_cutoff=1000.0,
                    precision_gain_min=1.0)
    prec = Mapping(plane="xy", absolute=True, pointer_min_cutoff=1000.0)
    _, moved_plain = _drive_abs(plain, step=25.0)    # ~3500 px/s: a flick
    _, moved_prec = _drive_abs(prec, step=25.0)
    assert abs(moved_prec - moved_plain) < 3.0


def test_touch_precision_offset_is_bounded_and_bleeds_at_speed():
    prec = Mapping(plane="xy", absolute=True, pointer_min_cutoff=1000.0)
    driver, _ = _drive_abs(prec, step=1.0, frames=60)   # long slow crawl
    off = math.hypot(*driver._prec_off)
    assert off <= prec.precision_offset_max_px + 1e-6
    assert off > 5.0                                    # it did accumulate
    t0 = 10_000 + 61 * 33_000
    for i in range(30):                                 # now flick around
        # Alternate INSIDE the plane range: a clamped-out-of-range target
        # reads as zero motion and would never register as speed.
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 3.0 + i * 0.033,
                                     abs_frame(60.0 + (i % 2) * 60.0, 260,
                                               t0 + i * 33_000),
                                     {"settle": 1.0}))
    assert math.hypot(*driver._prec_off) < off * 0.3    # bled away


# --- a pinch clicks, and only clicks ------------------------------------------

def _hold_and_move(driver, down_intent, up_intent, t0=0.0):
    """Press, drag the hand 120mm sideways over ~0.4s, release. Returns the
    cursor positions observed while the button was held."""
    start = frame(0.0, 200.0, 0.0, 0)
    drive(driver, [start])
    driver.on_intent(IntentEvent(down_intent, t0, start))
    seen = []
    for i in range(1, 13):
        f = frame(i * 10.0, 200.0, 0.0, i * 33_000, vx=300.0)
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, t0 + i * 0.033, f))
        seen.append((driver.x, driver.y))
    driver.on_intent(IntentEvent(up_intent, t0 + 0.45, None))
    return seen


def test_a_held_pinch_cannot_drag_the_cursor():
    """The defect this pins: the pin-back only corrected where the mouse-UP
    landed, so the cursor tracked the hand for the whole hold and macOS had
    already been dragging — a pinch meant as a click selected text."""
    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 200, 0, 0)))
    seen = _hold_and_move(driver, Intent.SELECT_DOWN, Intent.SELECT_UP)
    assert len(set(seen)) == 1, f"cursor moved while pinched: {set(seen)}"
    # ...and no move events reached the OS between the down and the up.
    kinds = [c[0] for c in backend.calls]
    down, up = kinds.index("down"), len(kinds) - 1 - kinds[::-1].index("up")
    assert "move" not in kinds[down:up]


def test_a_held_fist_still_drags():
    """The fist is the drag gesture; pinning the pinch must not pin it too."""
    driver, _ = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 200, 0, 0)))
    seen = _hold_and_move(driver, Intent.GRAB_DOWN, Intent.GRAB_UP)
    assert len(set(seen)) > 1, "fist-drag froze — the drag gesture is dead"


def test_pinch_drag_can_be_turned_back_on():
    driver, _ = make(Mapping(plane="xz", pinch_drag=True))
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 200, 0, 0)))
    seen = _hold_and_move(driver, Intent.SELECT_DOWN, Intent.SELECT_UP)
    assert len(set(seen)) > 1


def test_a_pinch_that_becomes_a_fist_hands_over_a_live_drag():
    """The pinch->fist handover emits grab.down with the button already held.
    That must ARM the drag, not stay pinned — otherwise the documented
    'close into a fist to drag' path is dead."""
    driver, _ = make()
    start = frame(0.0, 200.0, 0.0, 0)
    drive(driver, [start])
    driver.on_intent(IntentEvent(Intent.SELECT_DOWN, 0.0, start))
    driver.on_intent(IntentEvent(Intent.GRAB_DOWN, 0.05, start))   # handover
    before = (driver.x, driver.y)
    for i in range(1, 10):
        f = frame(i * 10.0, 200.0, 0.0, i * 33_000, vx=300.0)
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.05 + i * 0.033, f))
    assert (driver.x, driver.y) != before


def test_a_pinned_pinch_never_leaves_the_button_held():
    """The hard rule: no pin, freeze or guard may strand a button down."""
    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 200, 0, 0)))
    _hold_and_move(driver, Intent.SELECT_DOWN, Intent.SELECT_UP)
    assert [c[0] for c in backend.calls].count("down") == 1
    assert [c[0] for c in backend.calls][-1] == "up" or "up" in [c[0] for c in backend.calls]
    assert driver._button_down is False


def test_the_drag_command_presses_and_the_cursor_follows():
    """The free-hand fist arrives as a COMMAND, not an intent, and must hold
    the button while the cursor hand goes on moving."""
    from leapinput.commands import Command, CommandEvent

    driver, backend = make()
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frame(0, 200, 0, 0)))
    driver.on_command(CommandEvent(Command.DRAG, 0.0, {"active": True}))
    assert driver._button_down is True
    seen = []
    for i in range(1, 10):
        f = frame(i * 10.0, 200.0, 0.0, i * 33_000, vx=300.0)
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, i * 0.033, f))
        seen.append((driver.x, driver.y))
    assert len(set(seen)) > 1, "fist-drag did not move the cursor"
    driver.on_command(CommandEvent(Command.DRAG, 0.4, {"active": False}))
    assert driver._button_down is False
    assert [c[0] for c in backend.calls].count("down") == 1


def test_other_commands_do_not_touch_the_mouse():
    from leapinput.commands import Command, CommandEvent

    driver, backend = make()
    for cmd in (Command.COPY, Command.PASTE, Command.ENTER,
                Command.MISSION_CONTROL):
        driver.on_command(CommandEvent(cmd, 0.0, {}))
    assert backend.calls == []
    assert driver._button_down is False
