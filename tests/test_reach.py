"""Reach box tests: the fitted-viewport maths, no camera required.

The reach box exists for one measured reality: a phone fixed on a stand sees a
frame much larger than the comfortable reach, so whole-frame mapping forces
stretching and out-of-bounds excursions. These pin the mapping (comfy box ->
full plane, clamped at the edges), the fit guards, and the absolute driver
that turns the box into a floating screen.
"""

import dataclasses

import pytest

from leapinput.actions import DryRunBackend
from leapinput.camera import (PLANE_X_MM, PLANE_Y_BASE, PLANE_Y_MM, Tuning,
                              _to_plane, plane_norm, tune_for_camera)
from leapinput.capture import HandFrame, Vec3
from leapinput.driver import DirectDriver, Mapping
from leapinput.gestures import Config, Intent, IntentEvent
from leapinput.reach import MAX_ZOOM, MIN_FRAMES, fit_reach, save_reach

BOX = (0.25, 0.30, 0.75, 0.70)      # a centred half-frame reach


def lm(x, y):
    return Vec3(x, y, 0.0)


# --- viewport mapping ---------------------------------------------------------

def test_reach_box_center_maps_to_plane_center():
    p = _to_plane(lm(0.5, 0.5), BOX)
    assert abs(p.x) < 1e-9
    assert abs(p.y - (PLANE_Y_BASE + PLANE_Y_MM / 2.0)) < 1e-9


def test_reach_box_edges_span_the_full_plane():
    left = _to_plane(lm(0.25, 0.5), BOX)
    right = _to_plane(lm(0.75, 0.5), BOX)
    assert left.x == -PLANE_X_MM / 2.0
    assert right.x == PLANE_X_MM / 2.0


def test_outside_the_box_clamps_instead_of_extrapolating():
    """Overreach must PIN the pointer at the edge, never fling it further —
    that is the 'bounds' half of the feature."""
    way_out = _to_plane(lm(0.05, 0.95), BOX)
    at_corner = _to_plane(lm(0.25, 0.70), BOX)
    assert (way_out.x, way_out.y) == (at_corner.x, at_corner.y)


def test_identity_box_is_the_old_whole_frame_mapping():
    for x, y in ((0.0, 0.0), (0.5, 0.45), (1.0, 1.0)):
        a, b = _to_plane(lm(x, y)), _to_plane(lm(x, y), (0.0, 0.0, 1.0, 1.0))
        assert (a.x, a.y) == (b.x, b.y)


def test_plane_norm_inverts_to_plane():
    for x, y in ((0.0, 0.0), (0.3, 0.8), (1.0, 1.0)):
        nx, ny = plane_norm(_to_plane(lm(x, y)))
        assert abs(nx - x) < 1e-9 and abs(ny - y) < 1e-9


def test_degenerate_stored_box_falls_back_to_whole_frame():
    t = Tuning(reach_x0=0.5, reach_x1=0.5, reach_y0=0.2, reach_y1=0.8)
    assert t.reach == (0.0, 0.0, 1.0, 1.0)
    assert not t.reach_active


def test_tuning_reach_roundtrips_through_json(tmp_path):
    path = tmp_path / "tuning.json"
    save_reach(BOX, path)
    loaded = Tuning.load(path)
    assert loaded.reach == BOX
    assert loaded.reach_active


def test_save_reach_preserves_pose_thresholds(tmp_path):
    """The box describes the SETUP; calibrate's thresholds describe the HAND.
    Writing one must never reset the other."""
    path = tmp_path / "tuning.json"
    Tuning(pinch_on_mm=31.0, extend_on_deg=48.5).save(path)
    save_reach(BOX, path)
    loaded = Tuning.load(path)
    assert loaded.pinch_on_mm == 31.0
    assert loaded.extend_on_deg == 48.5


# --- fitting ------------------------------------------------------------------

def cloud(x0, x1, y0, y1, n=300):
    """A deterministic sweep filling the given envelope."""
    return [(x0 + (x1 - x0) * (i % 25) / 24.0,
             y0 + (y1 - y0) * (i // 25) / max(1, (n // 25) - 1))
            for i in range(n)]


def test_fit_covers_the_roam_with_margin():
    box, report = fit_reach(cloud(0.30, 0.70, 0.40, 0.80))
    x0, y0, x1, y1 = box
    assert x0 < 0.30 and x1 > 0.70          # margin outside the roam
    assert y0 < 0.40 and y1 > 0.80
    assert 0.0 <= x0 and x1 <= 1.0
    assert any("zoom" in line for line in report)


def test_fit_rejects_too_few_frames():
    with pytest.raises(ValueError, match="frames"):
        fit_reach(cloud(0.2, 0.8, 0.2, 0.8, n=MIN_FRAMES - 1))


def test_fit_rejects_a_hovering_hand():
    """A hand that barely moved is not a measured reach."""
    with pytest.raises(ValueError, match="roam wider"):
        fit_reach(cloud(0.45, 0.55, 0.20, 0.80))


def test_fit_caps_the_zoom():
    box, report = fit_reach(cloud(0.40, 0.58, 0.40, 0.58))
    x0, y0, x1, y1 = box
    assert (x1 - x0) >= 1.0 / MAX_ZOOM - 1e-9
    assert (y1 - y0) >= 1.0 / MAX_ZOOM - 1e-9
    assert any("zoom cap" in line for line in report)


# --- rate constants scale with the zoom ---------------------------------------

def test_tune_for_camera_scales_noise_floor_with_zoom():
    plain, zoomed = Mapping(plane="xy"), Mapping(plane="xy")
    tune_for_camera(Config(plane="xy"), plain, Tuning())
    tune_for_camera(Config(plane="xy"), zoomed,
                    Tuning(reach_x0=0.25, reach_y0=0.25,
                           reach_x1=0.75, reach_y1=0.75))
    assert zoomed.deadzone_mm == pytest.approx(plain.deadzone_mm * 2.0)
    assert zoomed.speed_lo == pytest.approx(plain.speed_lo * 2.0)
    assert zoomed.speed_hi == pytest.approx(plain.speed_hi * 2.0)


# --- absolute mapping ---------------------------------------------------------

def hand_at(x_mm, y_mm, t_us) -> HandFrame:
    at = Vec3(x_mm, y_mm, 0.0)
    return HandFrame(
        frame_id=1, timestamp=t_us, hand_id=1, side="Right",
        palm=at, palm_velocity=Vec3(0.0, 0.0, 0.0),
        palm_normal=Vec3(0.0, 0.0, -1.0),
        pinch_strength=0.0, pinch_distance=80.0, grab_strength=0.0,
        extended=(True,) * 5, index_tip=at, knuckles=(at,) * 4,
    )


def absolute_driver():
    backend = DryRunBackend()
    mapping = Mapping(plane="xy", absolute=True, tracking_point="palm",
                      invert_x=False)
    return DirectDriver(backend, mapping), backend


def drive_to(driver, frames):
    driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, frames[0]))
    for f in frames:
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, f.timestamp / 1e6, f))


def test_absolute_plane_center_is_screen_center():
    driver, backend = absolute_driver()
    drive_to(driver, [hand_at(0.0, PLANE_Y_BASE + PLANE_Y_MM / 2.0, 0)])
    w, h = backend.screen
    assert driver.x == pytest.approx((w - 1) / 2.0, abs=1.5)
    assert driver.y == pytest.approx((h - 1) / 2.0, abs=1.5)


def test_absolute_plane_corners_reach_screen_corners():
    driver, backend = absolute_driver()
    w, h = backend.screen
    top_left = hand_at(-PLANE_X_MM / 2.0, PLANE_Y_BASE + PLANE_Y_MM, 0)
    drive_to(driver, [top_left])
    assert (driver.x, driver.y) == (0.0, 0.0)
    bottom_right = hand_at(PLANE_X_MM / 2.0, PLANE_Y_BASE, 100_000)
    driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.1, bottom_right))
    # The 1 euro filter needs a few frames to converge on a big jump.
    for i in range(2, 30):
        driver.on_intent(IntentEvent(
            Intent.POINT_MOVE, 0.1 * i,
            hand_at(PLANE_X_MM / 2.0, PLANE_Y_BASE, 100_000 * i)))
    assert driver.x == pytest.approx(w - 1, abs=2.0)
    assert driver.y == pytest.approx(h - 1, abs=2.0)


def test_absolute_freezes_while_a_pinch_forms():
    """settle=0 means the click is committing: the cursor must hold still."""
    driver, _ = absolute_driver()
    drive_to(driver, [hand_at(0.0, PLANE_Y_BASE + PLANE_Y_MM / 2.0, 0)])
    was = (driver.x, driver.y)
    driver.on_intent(IntentEvent(
        Intent.POINT_MOVE, 0.1, hand_at(60.0, PLANE_Y_BASE + 40.0, 100_000),
        {"settle": 0.0}))
    assert (driver.x, driver.y) == was


# --- corner placement ---------------------------------------------------------

def test_corner_box_pads_outward_and_orders_corners():
    from leapinput.reach import corner_box
    box, report = corner_box((0.7, 0.8), (0.3, 0.4))   # given in any order
    x0, y0, x1, y1 = box
    assert x0 < 0.3 and x1 > 0.7            # pad extends outward
    assert y0 < 0.4 and y1 > 0.8
    assert any("zoom" in line for line in report)


def test_corner_box_caps_the_zoom():
    from leapinput.reach import corner_box
    box, report = corner_box((0.45, 0.45), (0.55, 0.55))
    x0, y0, x1, y1 = box
    assert (x1 - x0) >= 1.0 / MAX_ZOOM - 1e-9
    assert (y1 - y0) >= 1.0 / MAX_ZOOM - 1e-9
    assert any("zoom cap" in line for line in report)


def test_corner_box_rejects_coincident_corners():
    from leapinput.reach import corner_box
    with pytest.raises(ValueError, match="on top of each other"):
        corner_box((0.5, 0.5), (0.52, 0.9))


# --- distance-invariant sensitivity -------------------------------------------
# "when I am far away I have to do very exaggerated motions": apparent knuckle
# span ~ 1/distance is the free monocular depth proxy, so ref/current span
# rescales motion to physical units at any distance.

def test_motion_scale_doubles_when_the_hand_is_twice_as_far():
    from leapinput.camera import INDEX_MCP, PINKY_MCP, handframe_of

    def image_lms(span):
        lms = [Vec3(0.5, 0.5, 0.0)] * 21
        lms = list(lms)
        lms[INDEX_MCP] = Vec3(0.5 - span / 2.0, 0.5, 0.0)
        lms[PINKY_MCP] = Vec3(0.5 + span / 2.0, 0.5, 0.0)
        return lms

    from test_camera import OPEN as OPEN_WORLD
    t = Tuning(ref_span_img=0.2)
    near = handframe_of(image_lms(0.2), OPEN_WORLD, "Right", 1, 0, tuning=t)
    far = handframe_of(image_lms(0.1), OPEN_WORLD, "Right", 1, 0, tuning=t)
    assert near.motion_scale == pytest.approx(1.0, abs=0.01)
    assert far.motion_scale == pytest.approx(2.0, abs=0.05)


def test_motion_scale_is_clamped_and_off_without_a_reference():
    from leapinput.camera import INDEX_MCP, PINKY_MCP, handframe_of
    from test_camera import OPEN as OPEN_WORLD

    def image_lms(span):
        lms = [Vec3(0.5, 0.5, 0.0)] * 21
        lms = list(lms)
        lms[INDEX_MCP] = Vec3(0.5 - span / 2.0, 0.5, 0.0)
        lms[PINKY_MCP] = Vec3(0.5 + span / 2.0, 0.5, 0.0)
        return lms

    tiny = handframe_of(image_lms(0.041), OPEN_WORLD, "Right", 1, 0,
                        tuning=Tuning(ref_span_img=0.3))
    assert tiny.motion_scale == 3.0                 # clamped
    off = handframe_of(image_lms(0.1), OPEN_WORLD, "Right", 1, 0,
                       tuning=Tuning())             # no reference stored
    assert off.motion_scale == 1.0


def test_relative_cursor_travel_is_distance_invariant():
    """The same physical hand delta moves the cursor twice as far when the
    frame says the hand is twice as distant (half the image motion)."""
    def run(scale, dx_mm):
        backend = DryRunBackend()
        driver = DirectDriver(backend, Mapping(plane="xy", invert_x=False,
                                               tracking_point="palm"))
        f0 = dataclasses.replace(hand_at(0.0, 320.0, 0), motion_scale=scale)
        f1 = dataclasses.replace(hand_at(dx_mm, 320.0, 100_000),
                                 motion_scale=scale)
        driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, f0))
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.0, f0))
        start = driver.x
        driver.on_intent(IntentEvent(Intent.POINT_MOVE, 0.1, f1))
        return driver.x - start

    near = run(1.0, 10.0)       # 10mm of image-plane motion, at reference
    far = run(2.0, 5.0)         # the same physical motion, twice as far away
    # Not exact: the 1 euro filter is speed-adaptive, so a larger raw step
    # passes a slightly larger fraction. Within 10% is distance-invariant for
    # every practical purpose (the uncompensated error would be 100%).
    assert far == pytest.approx(near, rel=0.10)


def test_pinch_gate_judges_physical_speed():
    from leapinput.gestures import GestureEngine, Config
    engine = GestureEngine(Config(plane="xy"))
    slow_near = dataclasses.replace(
        hand_at(0.0, 320.0, 0), palm_velocity=Vec3(100.0, 0.0, 0.0))
    fast_far = dataclasses.replace(
        slow_near, motion_scale=2.0)    # same image speed, twice the distance
    assert engine._speed(slow_near) == pytest.approx(100.0)
    assert engine._speed(fast_far) == pytest.approx(200.0)


def test_clear_resets_the_working_distance(tmp_path):
    path = tmp_path / "tuning.json"
    save_reach(BOX, path, ref_span_img=0.21)
    assert Tuning.load(path).ref_span_img == 0.21
    save_reach((0.0, 0.0, 1.0, 1.0), path, ref_span_img=0.0)
    assert Tuning.load(path).ref_span_img == 0.0


# --- the dynamic palm-centred box ---------------------------------------------

def make_lms(cx, cy, span=0.1):
    lms = [Vec3(cx, cy, 0.0)] * 21
    lms = list(lms)
    from leapinput.camera import INDEX_MCP, PINKY_MCP
    lms[INDEX_MCP] = Vec3(cx - span / 2.0, cy, 0.0)
    lms[PINKY_MCP] = Vec3(cx + span / 2.0, cy, 0.0)
    return lms


def make_sig(span_img):
    from leapinput.camera import PoseSignals
    return PoseSignals(bends=(30.0,) * 4, thumb_ratio=1.2, pinch_mm=60.0,
                       span_mm=80.0, span_img=span_img)


def palm_source(**tuning_kw):
    from leapinput.camera import CameraSource
    defaults = dict(reach_x0=0.35, reach_y0=0.30, reach_x1=0.65,
                    reach_y1=0.60, ref_span_img=0.1, reach_center="palm")
    defaults.update(tuning_kw)
    return CameraSource(hand="Right", tuning=Tuning(**defaults),
                        screen_aspect=1512.0 / 982.0)


def test_dynamic_box_centres_on_the_palm_with_screen_shape():
    from leapinput.camera import CameraSource
    src = palm_source()
    box = src._resolve_reach("Right", make_lms(0.7, 0.6), make_sig(0.1))
    x0, y0, x1, y1 = box
    assert (x0 + x1) / 2.0 == pytest.approx(0.7, abs=0.02)
    assert (y0 + y1) / 2.0 == pytest.approx(0.6, abs=0.02)
    # Calibrated width, shrunk by the comfort inset so the box maps to more
    # than the screen (edge reach lands inside the comfortable envelope).
    w_expect = 0.30 * src._tuning.inset_scale
    assert (x1 - x0) == pytest.approx(w_expect, abs=0.01)
    assert (y1 - y0) == pytest.approx(w_expect * src.dyn_h_per_w,
                                      abs=0.01)   # shaped like the display
    # 14.2-inch MacBook panel: 1512x982 through the 4:3 frame
    assert src.dyn_h_per_w == pytest.approx((4.0 / 3.0) / (1512.0 / 982.0))


def test_drag_along_keeps_the_frame_edge_margin():
    """A box flush against the frame boundary demands knuckles at the image
    border, where fingers clip and landmarks degrade (2026-08-19 telemetry).
    The drag-along must stop FRAME_EDGE_MARGIN short of the edge."""
    from leapinput.camera import FRAME_EDGE_MARGIN
    src = palm_source()
    src._resolve_reach("Right", make_lms(0.5, 0.5), make_sig(0.1))
    for x in (0.7, 0.85, 0.99, 1.0):    # ride the hand hard right
        box = src._resolve_reach("Right", make_lms(x, 0.5), make_sig(0.1))
    assert box[2] == pytest.approx(1.0 - FRAME_EDGE_MARGIN)
    for x in (0.3, 0.1, 0.0):           # and hard left
        box = src._resolve_reach("Right", make_lms(x, 0.5), make_sig(0.1))
    assert box[0] == pytest.approx(FRAME_EDGE_MARGIN)


def test_rebuild_respects_the_frame_edge_margin():
    from leapinput.camera import FRAME_EDGE_MARGIN
    src = palm_source()
    box = src._resolve_reach("Right", make_lms(0.99, 0.5), make_sig(0.1))
    assert box[2] == pytest.approx(1.0 - FRAME_EDGE_MARGIN)


def test_comfort_inset_shrinks_the_box_and_zero_disables_it():
    """The inset maps the box to MORE than the screen so edges are reachable
    inside the comfortable envelope; reach_inset=0 must restore the exact
    pre-inset width (the knob is the off switch, not a code path)."""
    inset = palm_source()._resolve_reach("Right", make_lms(0.5, 0.5),
                                         make_sig(0.1))
    plain = palm_source(reach_inset=0.0)._resolve_reach(
        "Right", make_lms(0.5, 0.5), make_sig(0.1))
    assert (plain[2] - plain[0]) == pytest.approx(0.30, abs=0.01)
    assert (inset[2] - inset[0]) == pytest.approx(
        (plain[2] - plain[0]) * Tuning().inset_scale, abs=0.01)


def test_dynamic_box_shrinks_with_the_span_keeping_physical_size():
    """Twice the distance = half the apparent span = half the box in image
    terms — which is the SAME physical box, so sensitivity holds."""
    src = palm_source()
    near = src._resolve_reach("Right", make_lms(0.5, 0.5), make_sig(0.1))
    src._reach_now["Right"] = None                          # fresh appearance
    far = src._resolve_reach("Right", make_lms(0.5, 0.5), make_sig(0.07))
    assert (far[2] - far[0]) == pytest.approx((near[2] - near[0]) * 0.7,
                                              abs=0.01)
    src._reach_now["Right"] = None
    very_far = src._resolve_reach("Right", make_lms(0.5, 0.5), make_sig(0.02))
    assert (very_far[2] - very_far[0]) == pytest.approx(1.0 / 6.0, abs=0.01)


def test_dynamic_box_holds_inside_and_recenters_after_loss():
    src = palm_source()
    first = src._resolve_reach("Right", make_lms(0.3, 0.4), make_sig(0.1))
    src._prev["Right"] = object()       # hand is now continuously tracked
    inside = src._resolve_reach("Right", make_lms(0.35, 0.45), make_sig(0.1))
    assert inside == first              # stable while the hand stays inside
    src._prev["Right"] = None           # hand left; next appearance recenters
    src._reach_now["Right"] = None
    again = src._resolve_reach("Right", make_lms(0.8, 0.8), make_sig(0.1))
    assert again != first
    assert (again[0] + again[2]) / 2.0 == pytest.approx(0.8, abs=0.02)


def test_dynamic_box_survives_a_brief_dropout_in_place():
    """RC-1: a dropout past the 150ms hold used to recentre the box on
    reappearance, teleporting the cursor to ~screen centre. A quick comeback
    near where the hand vanished revives the dying box instead."""
    src = palm_source()
    first = src._resolve_reach("Right", make_lms(0.3, 0.4), make_sig(0.1),
                               now_us=1_000_000)
    src._prev["Right"] = None                       # dropout expired the hold
    src._reach_now["Right"] = None
    src._reach_gone["Right"] = (first, 1_000_000)   # ...and stashed the box
    # 300ms later, same spot: the old box comes back, not a recentred one.
    again = src._resolve_reach("Right", make_lms(0.32, 0.42), make_sig(0.1),
                               now_us=1_300_000)
    assert again == first
    assert src._reach_gone["Right"] is None         # consumed
    # A revival just past the edge (inside the 0.05 margin) still runs the
    # drag-along follow: the hand lands ON the edge, no teleport either way.
    src._prev["Right"] = None
    src._reach_now["Right"] = None
    src._reach_gone["Right"] = (first, 1_000_000)
    edge = src._resolve_reach("Right", make_lms(first[2] + 0.03, 0.4),
                              make_sig(0.1), now_us=1_300_000)
    assert edge[2] == pytest.approx(first[2] + 0.03, abs=0.005)
    assert edge[2] - edge[0] == pytest.approx(first[2] - first[0])


def test_dynamic_box_recenters_after_a_long_or_far_reappearance():
    """The revival is for dropouts only: a reappearance later than the 500ms
    continuity window, or away from the old box, keeps the documented
    come-to-the-hand recentre."""
    src = palm_source()
    first = src._resolve_reach("Right", make_lms(0.3, 0.4), make_sig(0.1),
                               now_us=1_000_000)
    # Too late: 600ms > the 500ms window lone_hand_side uses.
    src._prev["Right"] = None
    src._reach_now["Right"] = None
    src._reach_gone["Right"] = (first, 1_000_000)
    late = src._resolve_reach("Right", make_lms(0.32, 0.42), make_sig(0.1),
                              now_us=1_600_000)
    assert late != first
    assert (late[0] + late[2]) / 2.0 == pytest.approx(0.32, abs=0.02)
    # Too far: outside the old box's 0.05 margin.
    src._prev["Right"] = None
    src._reach_now["Right"] = None
    src._reach_gone["Right"] = (first, 1_000_000)
    far = src._resolve_reach("Right", make_lms(0.8, 0.8), make_sig(0.1),
                             now_us=1_300_000)
    assert far != first
    assert (far[0] + far[2]) / 2.0 == pytest.approx(0.8, abs=0.02)
    assert src._reach_gone["Right"] is None         # cleared either way


def test_dynamic_box_follows_overshoot_like_a_touch_sheet():
    """Crossing an edge drags the box with the hand — natural cadence, not an
    error — so reversing responds instantly with no overshoot debt."""
    src = palm_source()
    first = src._resolve_reach("Right", make_lms(0.5, 0.5), make_sig(0.1))
    src._prev["Right"] = object()
    # Push well past the right edge: the box slides so the hand sits ON it.
    dragged = src._resolve_reach("Right", make_lms(0.9, 0.5), make_sig(0.1))
    assert dragged[2] == pytest.approx(0.9, abs=0.01)   # right edge = hand
    assert dragged[2] - dragged[0] == pytest.approx(first[2] - first[0])
    # Reverse: the box STAYS where it was dragged; the hand is now inside it,
    # so the mapped point moves immediately.
    back = src._resolve_reach("Right", make_lms(0.8, 0.5), make_sig(0.1))
    assert back == dragged
    # And the box never leaves the frame, however far the hand pushes.
    pushed = src._resolve_reach("Right", make_lms(0.999, 0.999), make_sig(0.1))
    assert pushed[2] <= 1.0 and pushed[3] <= 1.0


def test_dynamic_box_shifts_inside_the_frame_at_the_edge():
    src = palm_source()
    box = src._resolve_reach("Right", make_lms(0.98, 0.02), make_sig(0.1))
    x0, y0, x1, y1 = box
    assert 0.0 <= x0 and x1 <= 1.0 and 0.0 <= y0 and y1 <= 1.0


def test_fixed_anchor_keeps_the_placed_rectangle():
    src = palm_source(reach_center="fixed")
    box = src._resolve_reach("Right", make_lms(0.9, 0.9), make_sig(0.1))
    assert box == (0.35, 0.30, 0.65, 0.60)


def test_palm_mode_disables_delta_distance_scaling():
    """The dynamic box already re-sizes with distance at each appearance —
    scaling deltas too would compensate twice."""
    from leapinput.camera import handframe_of
    from test_camera import OPEN as OPEN_WORLD
    t = Tuning(reach_x0=0.35, reach_y0=0.30, reach_x1=0.65, reach_y1=0.60,
               ref_span_img=0.2, reach_center="palm")
    far = handframe_of(make_lms(0.5, 0.5, span=0.1), OPEN_WORLD, "Right",
                       1, 0, tuning=t)
    assert far.motion_scale == 1.0


def test_camera_gain_boost_is_zoom_aware():
    """Audited 2026-08-18: the box zoom already IS the DPI. The boost only
    tops up what the zoom has not delivered — full 2x boxless, none at a
    3.3x box — so noise amplification can never stack multiplicatively."""
    from leapinput.camera import CAMERA_GAIN_BOOST
    plain = Mapping(plane="xy")

    boxless = Mapping(plane="xy")
    tune_for_camera(Config(plane="xy"), boxless, Tuning())
    # Even boxless, the comfort inset delivers 1/inset_scale of zoom, so the
    # boost only tops up the remainder — total DPI target unchanged.
    topped = CAMERA_GAIN_BOOST * Tuning().inset_scale
    assert boxless.gain_min == pytest.approx(plain.gain_min * topped)
    assert boxless.gain_max == pytest.approx(plain.gain_max * topped)

    boxed = Mapping(plane="xy")     # zoom 2.0 > boost 2.0/2.0 => no boost
    tune_for_camera(Config(plane="xy"), boxed,
                    Tuning(reach_x0=0.25, reach_y0=0.25,
                           reach_x1=0.75, reach_y1=0.75))
    assert boxed.gain_min == pytest.approx(plain.gain_min)
    assert boxed.gain_max == pytest.approx(plain.gain_max)
    # the ratio the docstring defends survives in both configurations
    assert boxed.gain_max / boxed.gain_min == \
        pytest.approx(plain.gain_max / plain.gain_min)


def test_camera_beta_scales_down_with_zoom():
    """The 1 euro adaptive term must see PHYSICAL speed — the box zoom
    multiplies derivatives, so beta divides by it or the filter opens on
    noise it was tuned to crush."""
    flat, zoomed = Mapping(plane="xy"), Mapping(plane="xy")
    tune_for_camera(Config(plane="xy"), flat, Tuning())
    tune_for_camera(Config(plane="xy"), zoomed,
                    Tuning(reach_x0=0.25, reach_y0=0.25,
                           reach_x1=0.75, reach_y1=0.75))
    assert zoomed.pointer_beta == pytest.approx(flat.pointer_beta / 2.0)


# --- the hand as the ChArUco board --------------------------------------------

def test_hand_span_roundtrips_and_upgrades_the_physical_readout(tmp_path):
    from leapinput.reach import physical_summary
    path = tmp_path / "tuning.json"
    save_reach(BOX, path, ref_span_img=0.05)
    assumed = physical_summary(Tuning.load(path))
    assert "assuming" in assumed
    t = dataclasses.replace(Tuning.load(path), hand_span_mm=72.0)
    t.save(path)
    measured = physical_summary(Tuning.load(path))
    assert "your measured 72mm" in measured
    # 72mm vs the 55mm nominal: the metric estimate scales accordingly.
    assert Tuning.load(path).span_mm_effective == 72.0


def test_span_mm_effective_falls_back_to_nominal():
    from leapinput.camera import NOMINAL_SPAN_MM
    assert Tuning().span_mm_effective == NOMINAL_SPAN_MM
    assert Tuning(hand_span_mm=68.0).span_mm_effective == 68.0


# --- the jitter meter ----------------------------------------------------------

def test_jitter_meter_measures_rest_and_ignores_motion():
    from leapinput.reach import JitterMeter
    m = JitterMeter()
    # A resting hand: small alternating noise around a fixed point.
    for i in range(JitterMeter.WINDOW):
        d = 1.0 if i % 2 else -1.0
        m.add((500.0 + d, 400.0), (500.0 + 4 * d, 400.0))
    dot, raw = m.stats()
    assert dot == pytest.approx(1.0, abs=0.05)
    assert raw == pytest.approx(4.0, abs=0.2)
    # Deliberate motion: the raw track sweeps far — no rest verdict.
    m2 = JitterMeter()
    for i in range(JitterMeter.WINDOW):
        m2.add((500.0 + i * 3.0, 400.0), (500.0 + i * 3.0, 400.0))
    assert m2.stats() is None
    # Too few samples: no verdict either.
    m3 = JitterMeter()
    m3.add((0.0, 0.0), (0.0, 0.0))
    assert m3.stats() is None
