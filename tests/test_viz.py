"""Viz panel tests. No terminal required — render() returns plain lines.

The one bug worth pinning here: the engaged badge must use the SAME threshold
the engine engages at. A hardcoded copy in the panel showed green in the
90-115mm band where the engine (engage_y=115) could never engage.
"""

from leapinput.capture import HandFrame, Vec3
from leapinput.gestures import Config
from leapinput.viz import PANEL_LINES, render

ORIGIN = Vec3(0.0, 0.0, 0.0)


def frame(y: float) -> HandFrame:
    return HandFrame(
        frame_id=1, timestamp=0, hand_id=1, side="Right",
        palm=Vec3(0.0, y, 0.0), palm_velocity=ORIGIN,
        palm_normal=Vec3(0.0, -1.0, 0.0),
        pinch_strength=0.0, pinch_distance=80.0,
        grab_strength=0.0,
        extended=(True,) * 5,
    )


def badge(lines: list[str]) -> str:
    text = "\n".join(lines)
    assert ("engaged" in text) != ("too low" in text)
    return "engaged" if "engaged" in text else "too low"


def test_badge_matches_engine_engage_threshold():
    engage_y = Config().engage_y
    # Just below the engine's engage height: the engine cannot engage, so the
    # panel must not claim it. This is the 90-115mm band the old literal lied in.
    assert badge(render(frame(engage_y - 1.0))) == "too low"
    assert badge(render(frame(engage_y + 1.0))) == "engaged"


def test_badge_respects_explicit_engage_y():
    assert badge(render(frame(50.0), engage_y=40.0)) == "engaged"
    assert badge(render(frame(50.0), engage_y=60.0)) == "too low"


def test_render_is_fixed_height():
    for f in (None, frame(150.0)):
        assert len(render(f)) == PANEL_LINES
