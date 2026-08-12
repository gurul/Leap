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
    return HandFrame(
        frame_id=1, timestamp=t_us, hand_id=1, side="Right", confidence=1.0,
        palm=Vec3(x, y, z), palm_stable=ORIGIN, palm_velocity=Vec3(vx, 0.0, vz),
        palm_normal=Vec3(0.0, -1.0, 0.0), palm_direction=ORIGIN,
        pinch_strength=0.0, pinch_distance=80.0, grab_strength=0.0, grab_angle=0.0,
        extended=(True,) * 5, fingertips=(ORIGIN,) * 5,
    )


def drive(driver, frames):
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frames[0]))
    for f in frames:
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, f.timestamp / 1e6, f))


def make(mapping=None, bounds=LAPTOP_PLUS_MONITOR):
    backend = DryRunBackend(bounds=bounds)
    return DirectDriver(backend, mapping or Mapping()), backend


# --- inversion --------------------------------------------------------------

def test_hand_toward_user_moves_cursor_up_by_default():
    """+z is toward the user. invert_z=True is the measured-correct setting for
    this desk, so pulling the hand back moves the cursor UP the screen and
    pushing it away moves down — reach forward for the far monitor."""
    driver, _ = make()
    start = driver.y
    drive(driver, [frame(0, 150, 0, 0), frame(0, 150, 20, 100_000)])
    assert driver.y < start


def test_inversion_is_configurable_per_axis():
    a, _ = make(Mapping(invert_z=False))
    b, _ = make(Mapping(invert_z=True))
    for d in (a, b):
        drive(d, [frame(0, 150, 0, 0), frame(0, 150, 20, 100_000)])
    assert (a.y - 491.0) == -(b.y - 491.0), "invert_z must mirror the motion exactly"


def test_invert_x_mirrors_horizontal_motion():
    a, _ = make(Mapping(invert_x=False))
    b, _ = make(Mapping(invert_x=True))
    for d in (a, b):
        drive(d, [frame(0, 150, 0, 0), frame(20, 150, 0, 100_000)])
    assert (a.x - 756.0) == -(b.x - 756.0)


# --- multi-monitor ----------------------------------------------------------

def test_cursor_can_reach_a_display_above_and_left_of_main():
    """The live bug: clamping to (0,0,w,h) traps the cursor on the main display,
    because a second monitor placed up-left has NEGATIVE CG coordinates."""
    driver, _ = make()
    # Up-left = hand left (-x) and TOWARD the user (+z), given invert_z.
    frames = [frame(-i * 4.0, 150, i * 4.0, i * 9000, vx=-500.0, vz=500.0)
              for i in range(60)]
    drive(driver, frames)
    assert driver.x < 0.0, "never crossed onto the left-hand display"
    assert driver.y < 0.0, "never crossed onto the upper display"


def test_cursor_is_clamped_to_the_union_not_the_main_screen():
    driver, _ = make()
    frames = [frame(-i * 20.0, 150, i * 20.0, i * 9000, vx=-900.0, vz=900.0)
              for i in range(200)]
    drive(driver, frames)
    assert driver.x >= -541.0 and driver.y >= -1440.0, "escaped the desktop union"


def test_single_display_still_clamps_at_zero():
    driver, _ = make(bounds=(0.0, 0.0, 1512.0, 982.0))
    frames = [frame(-i * 20.0, 150, i * 20.0, i * 9000, vx=-900.0, vz=900.0)
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
