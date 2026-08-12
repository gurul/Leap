"""Replay the real recorded session through the engine.

This is the test that actually matters. Synthetic frames prove the state machine is
internally consistent; only real frames prove the *thresholds* separate real poses.
Both prior threshold sets looked perfectly reasonable and were wrong.

Deterministic because the engine clocks off the sensor's own frame timestamps, so a
3639-frame session replays identically at any speed.
"""

import json
import pathlib

import pytest

from leapinput.capture import HandFrame, Snapshot, Vec3
from leapinput.gestures import Config, GestureEngine, Intent

SESSION = pathlib.Path(__file__).parent.parent / "docs" / "context" / "session.jsonl"
pytestmark = pytest.mark.skipif(not SESSION.exists(), reason="no recorded session")


def rehydrate(row: dict) -> HandFrame:
    def vec(key: str) -> Vec3:
        return Vec3(row[f"{key}_x"], row[f"{key}_y"], row[f"{key}_z"])

    return HandFrame(
        frame_id=row["frame_id"], timestamp=row["timestamp"], hand_id=row["hand_id"],
        side=row["side"], confidence=row["confidence"],
        palm=vec("palm"), palm_stable=vec("palm_stable"),
        palm_velocity=vec("palm_velocity"), palm_normal=vec("palm_normal"),
        palm_direction=vec("palm_direction"),
        pinch_strength=row["pinch_strength"], pinch_distance=row["pinch_distance"],
        grab_strength=row["grab_strength"], grab_angle=row["grab_angle"],
        extended=tuple(row["extended"]), fingertips=(Vec3(0.0, 0.0, 0.0),) * 5,
    )


@pytest.fixture(scope="module")
def fired():
    """{step: {intent: count}} from replaying the whole session."""
    rows = [json.loads(line) for line in SESSION.open()]
    out: dict[str, dict[str, int]] = {}
    # The recorded corpus is hand-flat-over-device, i.e. the xz plane.
    engine = GestureEngine(Config(plane="xz", clutch_mode="palm"))
    step = {"now": None}

    def record(event):
        bucket = out.setdefault(step["now"], {})
        bucket[event.intent.value] = bucket.get(event.intent.value, 0) + 1

    engine.subscribe(record)
    for row in rows:
        step["now"] = row["step"]
        engine.on_snapshot(Snapshot(right=rehydrate(row)))
    return out


def discrete(fired, step):
    return {k: v for k, v in fired.get(step, {}).items() if k != Intent.POINT_MOVE.value}


def test_engagement_opens_on_a_tracked_hand(fired):
    assert fired.get("hover", {}).get(Intent.POINT_MOVE.value, 0) > 300


def test_pinch_step_fires_select(fired):
    assert Intent.SELECT_DOWN.value in discrete(fired, "pinch")


def test_open_hand_never_fires_select(fired):
    """65mm of separation should mean zero false positives, not few."""
    assert Intent.SELECT_DOWN.value not in discrete(fired, "open")


def test_fist_fires_grab_not_select(fired):
    """A fist collapses pinch_distance to ~15mm — well past the pinch threshold —
    so this is the disambiguation that stops a fist reading as a click."""
    step = discrete(fired, "fist")
    assert Intent.GRAB_DOWN.value in step
    assert Intent.SELECT_DOWN.value not in step


def test_no_step_ever_fires_a_swipe(fired):
    """Across all 3639 real frames, including 664 of deliberate swiping.
    Swipes are cut; this pins that they stay cut."""
    for step in ("hover", "roam", "pinch", "open", "fist", "two_finger", "swipe"):
        fired_here = discrete(fired, step)
        assert not any(k.startswith("swipe.") for k in fired_here), \
            f"{step} fired a swipe"


def test_clutch_engages_on_real_frames(fired):
    """Palm-down is the neutral desk posture, so real pointing frames should
    clutch without the user being told to hold anything."""
    assert Intent.CLUTCH_DOWN.value in discrete(fired, "hover")


def test_static_poses_are_quiet(fired):
    """Holding still must not emit discrete intents. Chatter here would mean the
    Schmitt bands are too narrow for this hardware's noise floor."""
    for step in ("pinch", "fist", "open"):
        counts = discrete(fired, step)
        for intent, n in counts.items():
            if intent == Intent.SCROLL.value:
                continue        # scroll is continuous by design while grabbing
            assert n <= 4, f"{step} emitted {intent} {n}x — threshold chatter"


# --- the finger ladder, against the real corpus ------------------------------

@pytest.fixture(scope="module")
def ladder_fired():
    rows = [json.loads(line) for line in SESSION.open()]
    out: dict[str, dict[str, int]] = {}
    engine = GestureEngine(Config(plane="xz", clutch_mode="fingers"))
    step = {"now": None}

    def record(event):
        bucket = out.setdefault(step["now"], {})
        bucket[event.intent.value] = bucket.get(event.intent.value, 0) + 1

    engine.subscribe(record)
    for row in rows:
        step["now"] = row["step"]
        engine.on_snapshot(Snapshot(right=rehydrate(row)))
    return out


def test_real_fist_frames_grab(ladder_fired):
    """444 frames of a real fist, 100% of them at 0 extended fingers."""
    assert Intent.GRAB_DOWN.value in discrete(ladder_fired, "fist")


def test_real_open_hand_frames_lift_the_mouse(ladder_fired):
    """Open hand and roaming were 100% at 5 extended — unambiguously lifted, so
    the cursor must be parked and no button may be held."""
    for step in ("open", "roam"):
        assert Intent.GRAB_DOWN.value not in discrete(ladder_fired, step)
        assert ladder_fired.get(step, {}).get(Intent.POINT_MOVE.value, 0) < 20


def test_real_two_finger_frames_lift_the_mouse(ladder_fired):
    """554 frames at exactly 2 extended — the lift threshold.

    Moves survive the lift debounce (0.25s = ~28 frames at 110fps) before the
    lift is confirmed. That window is deliberately long: lifting interrupts the
    user, so it must be a deliberate open hand rather than a flicker. Assert the
    cursor stops, not that it never moved.
    """
    step = ladder_fired.get("two_finger", {})
    assert step.get(Intent.CLUTCH_UP.value, 0) >= 1
    assert step.get(Intent.POINT_MOVE.value, 0) <= 35, "cursor kept moving while lifted"


def test_real_pinch_frames_never_click(ladder_fired):
    """A deliberate pinch reads as 3 extended fingers on this hardware."""
    assert Intent.SELECT_DOWN.value not in discrete(ladder_fired, "pinch")


def test_a_real_fist_holds_the_button(ladder_fired):
    """The bug: gating the button on a raw grab_strength threshold gave it no
    hysteresis, so a momentary dip dropped it mid-drag — the live log shows
    grab.down/grab.up pairs firing repeatedly. Across 444 real fist frames the
    button must go down once and stay down."""
    step = ladder_fired.get("fist", {})
    assert step.get(Intent.GRAB_DOWN.value, 0) == 1
    assert step.get(Intent.GRAB_UP.value, 0) == 0


def test_a_fist_still_moves_the_cursor(ladder_fired):
    """A fist is a DRAG, so the cursor must keep tracking while it is held."""
    assert ladder_fired.get("fist", {}).get(Intent.POINT_MOVE.value, 0) > 300


def test_a_fist_does_not_also_scroll(ladder_fired):
    """One pose, one meaning. A fist carrying both drag and scroll is what
    produced 447 scroll events in a single session."""
    assert Intent.SCROLL.value not in discrete(ladder_fired, "fist")
