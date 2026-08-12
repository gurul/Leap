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
    engine = GestureEngine(Config())
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


def test_roaming_never_fires_a_swipe(fired):
    """Roam peaks at 419 mm/s against a 600 threshold. This is the whole reason
    swipes survived: the earlier analyzer compared the wrong statistics and
    reported an overlap that does not exist."""
    step = discrete(fired, "roam")
    assert not any(k.startswith("swipe.") for k in step)


def test_swipe_step_fires_swipes(fired):
    step = discrete(fired, "swipe")
    assert any(k.startswith("swipe.") for k in step)


def test_swipe_refractory_prevents_a_burst(fired):
    """664 frames of swiping is roughly 6s of flicking — a handful of swipes,
    not one per frame."""
    step = discrete(fired, "swipe")
    total = sum(v for k, v in step.items() if k.startswith("swipe."))
    assert 1 <= total <= 15, f"expected a few swipes, got {total}"


def test_static_poses_are_quiet(fired):
    """Holding still must not emit discrete intents. Chatter here would mean the
    Schmitt bands are too narrow for this hardware's noise floor."""
    for step in ("pinch", "fist", "open"):
        counts = discrete(fired, step)
        for intent, n in counts.items():
            assert n <= 4, f"{step} emitted {intent} {n}x — threshold chatter"
