"""Driver tests — the two bugs found in live use, pinned.

Both were invisible to every prior test because both need a real desk and a real
second monitor to show up.
"""

import dataclasses

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
    assert backend.calls[-2:] == [("move", *down_xy), ("up", *down_xy)]


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

    region = frame_region_px((0.25, 0.25, 0.75, 0.75), (1512.0, 982.0), 0.05)
    assert region == (378, 245, 756, 491)


def test_a_sloppy_tiny_frame_is_rejected():
    from leapinput.driver import frame_region_px

    assert frame_region_px((0.5, 0.2, 0.52, 0.8), (1512.0, 982.0), 0.05) is None
    assert frame_region_px(None, (1512.0, 982.0), 0.05) is None


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
