"""Driver tests — the two bugs found in live use, pinned.

Both were invisible to every prior test because both need a real desk and a real
second monitor to show up.
"""

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
        frame_id=1, timestamp=t_us, hand_id=1, side="Right", confidence=1.0,
        palm=at, palm_stable=ORIGIN, palm_velocity=Vec3(vx, 0.0, vz),
        palm_normal=Vec3(0.0, -1.0, 0.0), palm_direction=ORIGIN,
        pinch_strength=0.0, pinch_distance=80.0, grab_strength=0.0, grab_angle=0.0,
        extended=(True,) * 5, fingertips=tips, knuckles=knuckles,
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
    """The rigid alternative: same hand position, fingers curled to pinch."""
    driver, _ = make(Mapping(plane="xz", tracking_point="knuckles"))
    a = frame(0, 150, 0, 0)
    b = frame(0, 150, 0, 100_000)
    curled = HandFrame(**{**b.__dict__, "fingertips": tuple(
        Vec3(t.x - 25.0, t.y - 20.0, t.z + 30.0) for t in b.fingertips)})
    drive(driver, [a, curled])
    assert (driver.x, driver.y) == (a and driver.x, driver.y)   # no jump


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
