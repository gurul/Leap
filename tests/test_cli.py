"""CLI flag resolution — pinning that what the flags SAY is what ships.

The bug this guards: Mapping's invert_x default is the measured Leap truth
(True, confirmed by use), and building Mapping straight from a store_true
argparse default silently overwrote it with False on every default run.
"""

import argparse
from types import SimpleNamespace

import leapinput.cli as cli
from leapinput.cli import _mic_desync_fix, _overlay_status, _StallWatch, \
    resolve_source_defaults


def parse(source: str, *extra: str) -> argparse.Namespace:
    ns = argparse.Namespace(source=source, plane=None, point=None,
                            invert_x=None, invert_z=None, drag=None, map=None)
    for flag in extra:
        key, _, val = flag.partition("=")
        setattr(ns, key, val == "True")
    resolve_source_defaults(ns)
    return ns


def test_leap_defaults_keep_the_measured_inversion():
    ns = parse("leap")
    assert ns.invert_x is True      # confirmed by use 2026-08-12
    assert ns.invert_z is False
    assert ns.plane == "xz"
    assert ns.point == "index"
    assert ns.drag is True          # grab_strength is clean on the Leap


def test_camera_defaults():
    ns = parse("camera")
    assert ns.invert_x is False     # mirrored view already matches
    assert ns.invert_z is False
    assert ns.plane == "xy"
    assert ns.point == "knuckles"
    assert ns.drag is False         # camera: pinch is the only button


def test_explicit_flags_override_both_directions():
    assert parse("leap", "invert_x=False").invert_x is False
    assert parse("camera", "invert_x=True").invert_x is True
    assert parse("leap", "invert_z=True").invert_z is True


def test_map_defaults_touch_for_cameras_relative_for_leap():
    """Touchscreen is the camera-side interaction framework (2026-08-18):
    people address a screen as fixed points; the dynamic box supplies the
    "dynamic". The Leap keeps the measured relative ratchet."""
    assert parse("leap").map == "relative"
    assert parse("camera").map == "touch"
    assert parse("phone").map == "touch"


# --- preview status line (FH-2): busy must name the hold, not blame the ---
# --- clutch --------------------------------------------------------------

class FakeCv2:
    """Records the status text; the constants only need to exist."""
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 0

    def __init__(self):
        self.texts = []

    def putText(self, bgr, text, *a, **k):
        self.texts.append(text)


def draw_status(busy: bool, label: str = "dictate") -> list[str]:
    fake = FakeCv2()
    bgr = SimpleNamespace(shape=(480, 640, 3))
    engine = SimpleNamespace(clutch=SimpleNamespace(state=False),
                             grab=SimpleNamespace(state=False),
                             pinch=SimpleNamespace(state=False))
    command_engine = SimpleNamespace(
        busy=busy, overlay={"label": label, "progress": 0.5, "rect": None})
    _overlay_status(fake, bgr, engine, tracked=object(), last_intent="-",
                    stats=None, command_engine=command_engine)
    return fake.texts


def test_status_line_names_the_command_hold_while_busy():
    texts = draw_status(busy=True, label="dictate")
    assert any("COMMAND HOLD" in t and "dictate" in t for t in texts)
    assert not any("LIFTED" in t for t in texts)


def test_status_line_still_says_lifted_when_no_hold_owns_the_input():
    texts = draw_status(busy=False)
    assert any("LIFTED" in t for t in texts)


# --- dictation watchdog desync fix (FH-3 / SI-1 wiring) -------------------

def test_mic_desync_closure_flips_the_flag_and_plays_the_off_cue(monkeypatch):
    played = []
    monkeypatch.setattr(cli, "_play", played.append)
    command_engine = SimpleNamespace(_dictating=True)
    _mic_desync_fix(command_engine)()
    assert command_engine._dictating is False
    assert played == ["Pop"]        # the mic-off cue _announce uses


# --- frame-stream stall watchdog (TL-1) ------------------------------------

def test_stall_watch_releases_once_and_warns_after_the_stream_ran():
    w = _StallWatch(stall_s=0.5)
    assert w.update(0, 0.0) == (False, False)       # baseline
    assert w.update(1, 0.1) == (False, False)       # advancing
    assert w.update(2, 0.2) == (False, False)
    assert w.update(2, 0.4) == (False, False)       # stalled, under threshold
    assert w.update(2, 0.8) == (True, True)         # release + warn, once
    assert w.update(2, 5.0) == (False, False)       # no repeat while stalled
    assert w.update(3, 5.1) == (False, False)       # recovery resets
    assert w.update(3, 5.8) == (True, True)         # a second stall warns again


def test_stall_watch_stays_quiet_when_the_stream_never_started():
    """The phone source legitimately idles before the browser connects: the
    idempotent release still fires, but no scary warning."""
    w = _StallWatch(stall_s=0.5)
    assert w.update(0, 0.0) == (False, False)
    assert w.update(0, 0.6) == (True, False)        # release yes, warn no
    assert w.update(0, 9.0) == (False, False)
