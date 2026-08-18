"""The screen-overlay client's wire protocol, without an AppKit helper.

The helper's drawing is verified by screenshot (see overlay.py's capturable
test hook); these tests pin the session-side contract: what goes down the
pipe, that identical states are not re-sent, and that a dead helper never
takes the control loop with it.
"""

import io
import json
import threading

from leapinput.overlay import ScreenOverlay


class FakeProc:
    def __init__(self):
        self.stdin = io.BytesIO()


def client() -> tuple[ScreenOverlay, FakeProc]:
    ov = ScreenOverlay.__new__(ScreenOverlay)
    ov._lock = threading.Lock()
    ov._last = None
    ov._proc = FakeProc()
    return ov, ov._proc


def lines(proc: FakeProc) -> list[dict]:
    return [json.loads(l) for l in proc.stdin.getvalue().splitlines()]


def test_rect_update_sends_quantized_state():
    ov, proc = client()
    ov.update({"rect": (0.1234567, 0.2, 0.5, 0.9), "progress": 0.61234})
    (msg,) = lines(proc)
    assert msg == {"rect": [0.123, 0.2, 0.5, 0.9],
                   "progress": 0.61, "done": False}


def test_full_ring_is_flagged_done():
    ov, proc = client()
    ov.update({"rect": (0.1, 0.2, 0.5, 0.9), "progress": 1.0})
    assert lines(proc)[0]["done"] is True


def test_no_rect_sends_hide_once():
    ov, proc = client()
    ov.update({"rect": None, "progress": 0.0})
    ov.update({"rect": None, "progress": 0.0})
    ov.update({"rect": None, "progress": 0.0})
    assert lines(proc) == [{"rect": None}]


def test_identical_states_are_not_resent():
    ov, proc = client()
    for _ in range(5):
        ov.update({"rect": (0.1, 0.2, 0.5, 0.9), "progress": 0.5})
    assert len(lines(proc)) == 1


def test_sub_quantum_jitter_is_not_resent():
    ov, proc = client()
    ov.update({"rect": (0.1, 0.2, 0.5, 0.9), "progress": 0.5})
    ov.update({"rect": (0.10004, 0.2, 0.5, 0.9), "progress": 0.501})
    assert len(lines(proc)) == 1


def test_dead_helper_is_dropped_quietly():
    ov, proc = client()
    proc.stdin.close()      # writes now raise, like a broken pipe
    ov.update({"rect": (0.1, 0.2, 0.5, 0.9), "progress": 0.5})
    assert ov._proc is None
    ov.update({"rect": (0.3, 0.2, 0.5, 0.9), "progress": 0.6})  # still no raise
    ov.close()                                                  # nor here
