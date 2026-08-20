"""Telemetry-layer tests. The layer is diagnostics: the contract under test is
"records the truth, tags phantoms, and can never hurt the control loop"."""

import json
import time
import urllib.request

from leapinput.capture import HandFrame, Snapshot, Vec3
from leapinput.gestures import Config, GestureEngine, Intent, IntentEvent
from leapinput.telemetry import (POST_FRAMES, Telemetry, TelemetryServer)

ORIGIN = Vec3(0.0, 0.0, 0.0)


def frame(**kw) -> HandFrame:
    base = dict(
        frame_id=1, timestamp=0, hand_id=1, side="Right",
        palm=Vec3(0.0, 150.0, 0.0), palm_velocity=ORIGIN,
        palm_normal=Vec3(0.0, -1.0, 0.0),
        pinch_strength=0.0, pinch_distance=80.0,
        grab_strength=0.0,
        extended=(True,) * 5,
    )
    base.update(kw)
    return HandFrame(**base)


def make_telemetry(tmp_path=None) -> Telemetry:
    return Telemetry(GestureEngine(Config()), hand="Right",
                     pinch_on_mm=40.0, pinch_off_mm=60.0,
                     out_dir=tmp_path)


def intent(kind: Intent, **data) -> IntentEvent:
    return IntentEvent(intent=kind, at=time.monotonic(), frame=None,
                       data=data)


# --- sampling ----------------------------------------------------------------

def test_samples_capture_hand_and_engine_state():
    tele = make_telemetry()
    tele.on_snapshot(Snapshot(right=frame(pinch_distance=42.5)))
    s = tele.ring[-1]
    assert s["hand"] is True and s["other"] is False
    assert s["pd"] == 42.5
    assert s["pinch"] is False and s["fingers"] == 5


def test_empty_snapshots_still_sample():
    tele = make_telemetry()
    tele.on_snapshot(Snapshot())
    s = tele.ring[-1]
    assert s["hand"] is False and "pd" not in s


def test_point_move_settle_is_carried_into_samples():
    tele = make_telemetry()
    tele.on_intent(intent(Intent.POINT_MOVE, settle=0.25))
    tele.on_snapshot(Snapshot(right=frame()))
    assert tele.ring[-1]["settle"] == 0.25


# --- click incidents -----------------------------------------------------------

def test_click_writes_pre_and_post_window(tmp_path):
    tele = make_telemetry(tmp_path)
    for i in range(10):
        tele.on_snapshot(Snapshot(right=frame(timestamp=i * 9000)))
    tele.on_intent(intent(Intent.SELECT_DOWN))
    for i in range(POST_FRAMES):
        tele.on_snapshot(Snapshot(right=frame(timestamp=(10 + i) * 9000)))

    files = list(tmp_path.glob("clicks-*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text().splitlines()[0])
    assert rec["type"] == "click" and rec["id"] == 1
    assert rec["intent"] == "select.down"
    assert len(rec["pre"]) == 10 and len(rec["post"]) == POST_FRAMES
    assert rec["pinch_on_mm"] == 40.0


def test_mark_tags_the_latest_click_exactly_once(tmp_path):
    tele = make_telemetry(tmp_path)
    tele.on_intent(intent(Intent.SELECT_DOWN))
    assert tele.mark_phantom("that was not me") == 1
    assert tele.mark_phantom() is None          # no new click: no double-tag
    tele.on_intent(intent(Intent.GRAB_DOWN))
    assert tele.mark_phantom() == 2

    marks = [json.loads(line)
             for line in list(tmp_path.glob("clicks-*.jsonl"))[0]
             .read_text().splitlines() if '"mark"' in line]
    assert [m["click_id"] for m in marks] == [1, 2]
    assert marks[0]["note"] == "that was not me"


def test_mark_before_any_click_is_a_noop(tmp_path):
    tele = make_telemetry(tmp_path)
    assert tele.mark_phantom() is None
    assert tele.marks == 0


# --- the do-no-harm contract ---------------------------------------------------

def test_entry_points_swallow_garbage():
    tele = make_telemetry()
    tele.on_snapshot(None)                      # not a Snapshot at all
    tele.on_intent(None)
    tele.on_snapshot(Snapshot(right=frame()))   # still alive and sampling
    assert len(tele.ring) == 1


# --- the dashboard server --------------------------------------------------------

def test_server_serves_page_state_and_mark(tmp_path):
    tele = make_telemetry(tmp_path)
    tele.on_intent(intent(Intent.SELECT_DOWN))
    server = TelemetryServer(tele, port=0)      # ephemeral: tests can't collide
    url = server.start()
    assert url is not None
    try:
        page = urllib.request.urlopen(f"{url}/", timeout=5).read().decode()
        assert "LEAP TELEMETRY" in page
        state = json.loads(urllib.request.urlopen(f"{url}/state",
                                                  timeout=5).read())
        assert state["clicks"] == 1 and state["pinch_on_mm"] == 40.0
        req = urllib.request.Request(f"{url}/mark", data=b"phantom",
                                     method="POST")
        marked = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert marked["marked"] == 1
    finally:
        server.stop()


# --- the accuracy bench ----------------------------------------------------------

class _FakeCommand:
    """Shaped like commands.CommandEvent: .command.value plus .data."""

    class _Kind:
        def __init__(self, value):
            self.value = value

    def __init__(self, value, **data):
        self.command = self._Kind(value)
        self.data = data


class _FakeDirect:
    """DirectDriver stand-in: cursor position and screen size."""
    x, y, w, h = 300.4, 150.6, 1512, 982
    map = None


def test_pane_rect_reaches_the_browser_the_moment_it_fires():
    """The bench scores framing against the committed rect, so the rect must
    ride the live event stream — not only the session log."""
    tele = make_telemetry()
    q = tele.attach()
    tele.on_command(_FakeCommand("pane.new", rect=(0.1, 0.2, 0.3, 0.44444)))
    rec = q.get(timeout=2)
    assert rec["type"] == "command" and rec["command"] == "pane.new"
    assert rec["rect"] == [0.1, 0.2, 0.3, 0.4444]
    assert tele.events[-1]["rect"] is not None


def test_commands_without_a_rect_are_still_reported():
    tele = make_telemetry()
    tele.on_command(_FakeCommand("mission.control"))
    assert tele.events[-1] == {**tele.events[-1], "command": "mission.control",
                               "rect": None}


def test_on_command_swallows_garbage_like_every_other_entry_point():
    tele = make_telemetry()
    tele.on_command(None)                       # not a CommandEvent at all
    tele.on_command(_FakeCommand("pane.new", rect="not a rect"))
    assert len(tele.events) == 0                # dropped, never raised


def test_clicks_carry_where_the_cursor_actually_was():
    tele = make_telemetry()
    tele.direct = _FakeDirect()
    q = tele.attach()
    tele.on_intent(intent(Intent.SELECT_DOWN))
    q.get(timeout=2)                            # the intent record leads
    rec = q.get(timeout=2)
    assert rec["type"] == "click" and rec["cx"] == 300.4 and rec["cy"] == 150.6


def test_state_publishes_the_screen_and_the_mapping_knobs():
    """A score is only comparable against another run if the mapping that
    produced it is on the page next to it."""
    tele = make_telemetry()
    tele.direct = _FakeDirect()
    assert tele.state()["screen"] == [1512, 982]
    assert tele.state()["mapping"] == {}         # no source/mapping wired: empty
    assert "screen" in tele.state() and "mapping" in tele.state()


def test_server_serves_the_bench(tmp_path):
    tele = make_telemetry(tmp_path)
    server = TelemetryServer(tele, port=0)
    url = server.start()
    try:
        page = urllib.request.urlopen(f"{url}/bench", timeout=5).read().decode()
        assert "LEAP BENCH" in page
        assert "pane.new" in page               # the frame test is wired
    finally:
        server.stop()
