"""Regression tests for the 2026-11-15 critical review of 998e00e.

Each test is named for its finding (j1 = finding 1) and fails on 998e00e for
the reason the review gave.

SAFETY: this file must never post real input, on the new code or the old.
The old guard ignores LEAPINPUT_GUARD_SINK, so:
  - no test here spawns a guard process; the guard runs in-process with
    stdin replaced, and cli.Guard is faked wherever cli.main() runs;
  - an autouse fixture swaps in a fake Quartz whose every function raises,
    so any path that would reach CGEventPost fails loudly instead of posting;
  - cli.main() always runs with a fake camera source and a dry-run backend.
"""

import asyncio
import contextlib
import fcntl
import http.client
import io
import os
import signal
import sys
import threading
import time
import types
import zlib
from types import SimpleNamespace

import pytest

import leapinput.cli as cli
import leapinput.guard as guard
from leapinput import camera, ffmpegcam, phonecam
from leapinput.actions import DryRunBackend
from leapinput.capture import Snapshot
from leapinput.commands import Command, CommandEvent
from leapinput.driver import DirectDriver, ShortcutDriver
from leapinput.gestures import Config, GestureEngine
from leapinput.phonedepth import DepthFrame, _center_depth_mm
from leapinput.telemetry import Telemetry, TelemetryServer

OPTION = 58


# --- harness ------------------------------------------------------------------

def _fake_quartz():
    def refuse(name):
        def call(*a, **k):
            raise RuntimeError(f"Quartz.{name} called in a test: refused")
        return call

    def getattr_(name):
        if name.startswith("__"):           # import machinery probes
            raise AttributeError(name)
        return refuse(name)

    cg = types.ModuleType("Quartz.CoreGraphics")
    cg.__getattr__ = getattr_
    root = types.ModuleType("Quartz")
    root.CoreGraphics = cg
    root.__getattr__ = getattr_
    return root, cg


@pytest.fixture(autouse=True)
def no_real_input(tmp_path, monkeypatch):
    root, cg = _fake_quartz()
    monkeypatch.setitem(sys.modules, "Quartz", root)
    monkeypatch.setitem(sys.modules, "Quartz.CoreGraphics", cg)
    sink = tmp_path / "guard-sink.txt"
    monkeypatch.setenv("LEAPINPUT_GUARD_SINK", str(sink))
    monkeypatch.setenv("LEAPINPUT_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.delenv("LEAPINPUT_LOCK_FILE", raising=False)
    saved = {s: signal.getsignal(s)
             for s in (signal.SIGINT, signal.SIGTERM, signal.SIGUSR1)}
    yield sink
    for s, h in saved.items():
        signal.signal(s, h)


def sink_lines(sink) -> list[str]:
    return sink.read_text().splitlines() if sink.exists() else []


def run_guard_main(monkeypatch, data: bytes) -> int:
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    return guard.main()


class RecordingBackend(DryRunBackend):
    """Dry-run, with one shared log for key holds and guard notices."""

    def __init__(self, log=None):
        super().__init__()
        self.log = log if log is not None else []

    def key_hold(self, keycode, down, **mods):
        self.log.append(("key_hold", keycode, down))
        super().key_hold(keycode, down, **mods)


def dictate(active: bool) -> CommandEvent:
    return CommandEvent(Command.DICTATE, 0.0, {"active": active})


class FastTime:
    """cli's clock, run 10x fast, so the 4-5 s warnings land in under 1 s."""
    K = 10.0

    def __init__(self):
        self._t0 = time.monotonic()

    def monotonic(self):
        return self._t0 + (time.monotonic() - self._t0) * self.K

    def sleep(self, s):
        time.sleep(s / self.K)

    def __getattr__(self, name):
        return getattr(time, name)


class FakeSource:
    """CameraSource's shape: subscribe/open/latest/frames/stats. A thread
    plays the capture thread, dispatching empty snapshots every 5 ms.

    tick(source) runs on that thread each frame; on_close(source) runs as
    the capture thread's last act, before it stops (a frame in flight)."""

    last = None
    tick = None
    on_close = None
    stats = None
    advance = True

    def __init__(self, *a, **k):
        type(self).last = self
        self.latest = Snapshot()
        self.frames = 0
        self.preview_frame = None
        self.stats = type(self).stats
        self.advancing = type(self).advance
        self._subs = []
        self._stop = threading.Event()
        self.closed_at_frames = None

    def subscribe(self, cb):
        self._subs.append(cb)

    def _run(self):
        while not self._stop.is_set():
            if self.advancing:
                self.frames += 1
                for cb in self._subs:
                    cb(Snapshot())
            if type(self).tick is not None:
                type(self).tick(self)
            time.sleep(0.005)

    @contextlib.contextmanager
    def open(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        try:
            yield self
        finally:
            if type(self).on_close is not None:
                type(self).on_close(self)
            self._stop.set()
            t.join(timeout=2)


class FakeGuard:
    started = 0

    def start(self):
        type(self).started += 1
        self.ready = True
        return self

    def option(self, held):
        pass

    def stop(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    """Patch cli.main()'s hardware edges. Returns a namespace the test fills
    in before calling run()."""
    for attr in ("last", "tick", "on_close", "stats"):
        monkeypatch.setattr(FakeSource, attr, None)
    monkeypatch.setattr(FakeSource, "advance", True)
    h = SimpleNamespace(backend=RecordingBackend(), backend_names=[],
                        shortcuts=[], directs=[],
                        names=["MacBook Pro Camera"])

    def make_backend(name, **kw):
        h.backend_names.append(name)
        return h.backend

    class RecShortcuts(ShortcutDriver):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            h.shortcuts.append(self)

    class RecDirect(DirectDriver):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            h.directs.append(self)

    monkeypatch.setattr(cli, "CameraSource", FakeSource)
    monkeypatch.setattr(cli, "make_backend", make_backend)
    monkeypatch.setattr(cli, "Guard", FakeGuard)
    monkeypatch.setattr(cli, "ShortcutDriver", RecShortcuts)
    monkeypatch.setattr(cli, "DirectDriver", RecDirect)
    monkeypatch.setattr(cli, "camera_names", lambda: h.names)
    monkeypatch.setattr(cli, "pick_camera_index", lambda: 0)
    monkeypatch.setattr(cli, "time", FastTime())
    monkeypatch.setattr(cli, "_play", lambda sound: None)

    def run(*extra, duration="3"):
        argv = ["--source", "camera", "--camera", "0", "--no-telemetry",
                "--no-screen-overlay", "--duration", duration, *extra]
        return cli.main(argv)

    h.run = run
    return h


# --- finding 1: the guard never released Option -----------------------------------

def test_j1_guard_releases_option_held_at_end_of_input(monkeypatch, no_real_input):
    """Option is the one input the shipped tool holds. A SIGKILL mid-dictation
    used to leave it down: the guard only posted mouse-ups."""
    assert run_guard_main(monkeypatch, b"O") == 0
    assert "release option" in sink_lines(no_real_input)


def test_j1_guard_does_not_release_option_the_parent_let_go(monkeypatch,
                                                            no_real_input):
    assert run_guard_main(monkeypatch, b"OoOo") == 0
    lines = sink_lines(no_real_input)
    assert lines == ["release left", "release right", "release center"]


def test_j1_guard_fails_toward_release_on_a_byte_it_cannot_read(monkeypatch,
                                                                no_real_input):
    # Even a later "o" must not undo it: after an unknown byte the guard
    # cannot trust the stream any more.
    assert run_guard_main(monkeypatch, b"O?o") == 0
    assert "release option" in sink_lines(no_real_input)


def test_j1_shortcut_driver_tells_the_guard_each_option_edge():
    log = []
    sd = ShortcutDriver(RecordingBackend(log))
    sd.on_option = lambda held: log.append(("guard", held))
    sd.on_command(dictate(True))
    sd.on_command(dictate(False))
    # The guard hears of the press BEFORE it is posted, and of the release
    # after: a kill in between always leaves the guard releasing.
    assert log == [("guard", True), ("key_hold", OPTION, True),
                   ("key_hold", OPTION, False), ("guard", False)]


def test_j1_a_failed_guard_write_never_raises_into_the_gesture_path(capsys):
    g = guard.Guard()
    closed = io.BytesIO()
    closed.close()
    g.proc = SimpleNamespace(stdin=closed)
    g.option(True)                      # must not raise
    assert "could not report Option" in capsys.readouterr().err

    sd = ShortcutDriver(RecordingBackend())
    sd.on_option = g.option
    sd.on_command(dictate(True))        # press still happens, no exception
    assert sd.release_dictation()


class _FakeGuardProc:
    def __init__(self, ready: bool):
        r, w = os.pipe()
        if ready:
            os.write(w, b"R")
        self._w = w
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self.stdin = open(os.devnull, "wb")
        self.pid = -1

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass

    def close(self):
        os.close(self._w)


def test_j1_parent_logs_clearly_when_the_guard_is_not_ready(monkeypatch, capsys):
    procs = []

    def popen(*a, **k):
        procs.append(_FakeGuardProc(ready=False))
        return procs[-1]

    monkeypatch.setattr(guard.subprocess, "Popen", popen)
    monkeypatch.setattr(guard, "READY_TIMEOUT_S", 0.2, raising=False)
    g = guard.Guard().start()
    try:
        assert getattr(g, "ready", None) is False
        assert "NOT READY" in capsys.readouterr().err
    finally:
        g.stop()
        procs[0].close()


def test_j1_parent_confirms_a_ready_guard(monkeypatch):
    procs = []

    def popen(*a, **k):
        procs.append(_FakeGuardProc(ready=True))
        return procs[-1]

    monkeypatch.setattr(guard.subprocess, "Popen", popen)
    g = guard.Guard().start()
    try:
        assert getattr(g, "ready", None) is True
    finally:
        g.stop()
        procs[0].close()


# --- finding 2: shutdown could press Option again -------------------------------

def test_j2_no_press_after_close():
    log = []
    sd = ShortcutDriver(RecordingBackend(log))
    sd.close()
    sd.on_command(dictate(True))
    sd.on_command(CommandEvent(Command.PASTE, 0.0))
    assert log == []


def test_j2_close_releases_a_held_option():
    log = []
    sd = ShortcutDriver(RecordingBackend(log))
    sd.on_command(dictate(True))
    sd.close()
    assert log[-1] == ("key_hold", OPTION, False)


def test_j2_cli_exit_leaves_option_up_when_a_frame_lands_during_shutdown(
        harness, monkeypatch, capsys):
    """The shutdown race, end to end through cli.main(), and the signal path
    with it: SIGTERM stops the session, and the capture thread delivers one
    last thumbs-up before it stops. On 998e00e that press landed AFTER the
    exit release, so the process ended with Option held."""
    def tick(src):
        if src.frames == 20:
            os.kill(os.getpid(), signal.SIGTERM)

    def last_frame(src):
        for sd in harness.shortcuts:
            sd.on_command(dictate(True))

    FakeSource.tick = staticmethod(tick)
    FakeSource.on_close = staticmethod(last_frame)
    assert harness.run(duration="30") == 0
    out = capsys.readouterr().out
    assert "stopped" in out                         # the SIGTERM path ran
    assert "auto-stopped" not in out
    holds = [c for c in harness.backend.log if c[:2] == ("key_hold", OPTION)]
    assert not holds or holds[-1][2] is False, holds
    assert not harness.shortcuts[0]._dictating


# --- finding 3: the stall release missed the legacy fist-drag button ---------------

def test_j3_stall_release_lets_go_of_the_legacy_drag_button(harness):
    state = {}

    def tick(src):
        if not state and harness.directs:
            harness.directs[0].on_command(
                CommandEvent(Command.DRAG, 0.0, {"active": True}))
            state["pressed"] = True
            src.advancing = False           # the stream stalls, fist held

    def at_close(src):
        state["held_at_close"] = harness.directs[0]._button_down

    FakeSource.tick = staticmethod(tick)
    FakeSource.on_close = staticmethod(at_close)
    assert harness.run("--legacy", duration="3") == 0
    assert state.get("pressed")
    # Released by the STALL path, while the capture thread was still alive —
    # not only by the exit release after it.
    assert state["held_at_close"] is False
    downs = [c for c in harness.backend.calls if c[0] == "down"]
    ups = [c for c in harness.backend.calls if c[0] == "up"]
    assert len(downs) == 1 and len(ups) == 1


# --- finding 5: nothing stopped a second session ------------------------------

def _hold_lock(tmp_path):
    path = tmp_path / "run" / "session.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fh


def test_j5_second_quartz_session_exits_before_driving_anything(
        harness, tmp_path, capsys):
    held = _hold_lock(tmp_path)
    try:
        rc = harness.run("--backend", "quartz", duration="1")
        assert rc == 2
        assert "quartz" not in harness.backend_names
        assert FakeSource.last is None
        assert "already driving" in capsys.readouterr().err
        # A dry-run session posts nothing, so it takes no lock and runs.
        assert harness.run(duration="1") == 0
    finally:
        held.close()


# --- finding 7: the legacy phone source ------------------------------------------

def test_j7_phone_token_is_128_bits_and_new_every_session(tmp_path, monkeypatch):
    monkeypatch.setattr(phonecam, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(phonecam, "lan_ip", lambda: "127.0.0.1")
    a = phonecam._PhoneCamServer(port=1)
    b = phonecam._PhoneCamServer(port=1)
    assert len(a.token) >= 22               # token_urlsafe(16) = 128 bits
    assert a.token != b.token
    assert not (tmp_path / "state" / "phonecam-token").exists()


def test_j7_a_second_offer_does_not_replace_a_connected_stream(monkeypatch):
    import aiortc

    class LivePC:
        connectionState = "connected"
        closed = False

        async def close(self):
            self.closed = True

    def refuse(*a, **k):
        raise RuntimeError("a new peer was built over a live stream")

    monkeypatch.setattr(phonecam, "_patch_aiortc_low_latency", lambda: None)
    monkeypatch.setattr(aiortc, "RTCPeerConnection", refuse)
    srv = phonecam._PhoneCamServer.__new__(phonecam._PhoneCamServer)
    live = srv._pc = LivePC()

    class Req:
        async def json(self):
            return {"sdp": "v=0", "type": "offer"}

    try:
        resp = asyncio.run(srv._offer(Req()))
    except RuntimeError:
        resp = None
    assert not live.closed, "the user's own stream was cut off"
    assert resp is not None and resp.status == 409


def test_j7_depth_inflation_is_capped():
    bomb = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = bomb.compress(bytes(4 << 20)) + bomb.flush()
    frame = DepthFrame(0, "front", 1.0, 1.0, 0.0, 0.0, 2, 2, b"", data)
    with pytest.raises(ValueError):
        frame.depth_mm()


def test_j7_undecodable_depth_does_not_end_the_receiver():
    # ASCII on purpose: "n" opens a DEFLATE block of the reserved type 3.
    # (No backslash escapes in this file: the control script echoes pytest's
    # output through /bin/sh, whose echo expands them into raw bytes.)
    frame = DepthFrame(0, "front", 1.0, 1.0, 0.0, 0.0, 4, 4, b"",
                       b"not deflate at all")
    assert _center_depth_mm(frame) is None


# --- finding 9: the guard posts nothing under the sink -----------------------

def test_j9_sink_names_every_release_and_posts_nothing(no_real_input):
    # Quartz is faked to raise: reaching it (998e00e did) fails this test.
    guard.release_all_buttons()
    assert sink_lines(no_real_input) == [
        "release left", "release right", "release center"]


def test_j9_guard_main_writes_the_sink_at_end_of_input(monkeypatch,
                                                       no_real_input):
    assert run_guard_main(monkeypatch, b"") == 0
    assert sink_lines(no_real_input) == [
        "release left", "release right", "release center"]


# --- finding 11: an OBSBOT with no ffmpeg ----------------------------------------

def test_j11_auto_pick_skips_a_camera_that_needs_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(ffmpegcam, "ffmpeg_path", lambda: None)
    monkeypatch.setattr(camera, "camera_names",
                        lambda: ["OBSBOT Tiny 3 StreamCamera",
                                 "MacBook Pro Camera"])
    assert camera.pick_camera_index() == 1


def test_j11_no_frame_message_names_ffmpeg_not_permission(harness, monkeypatch,
                                                          capsys):
    monkeypatch.setattr(ffmpegcam, "ffmpeg_path", lambda: None)
    harness.names = ["OBSBOT Tiny 3 StreamCamera"]
    FakeSource.advance = False              # OpenCV gets no frames
    assert harness.run(duration="6") == 0
    err = capsys.readouterr().err
    assert "ffmpeg" in err.split("CAMERA DELIVERED NO FRAMES", 1)[-1]
    assert "denied Camera permission" not in err


# --- finding 12: "cursor will lag" in a mode with no cursor --------------------

def test_j12_lag_warning_only_in_legacy(harness, capsys):
    FakeSource.stats = {"fps": 120.0, "realtime": False, "detect_ms": 20.0}
    assert harness.run(duration="6") == 0
    assert "cursor will lag" not in capsys.readouterr().err
    assert harness.run("--legacy", duration="6") == 0
    assert "cursor will lag" in capsys.readouterr().err


# --- finding 14: the telemetry server ----------------------------------------------

@pytest.fixture
def dashboard(tmp_path):
    tele = Telemetry(GestureEngine(Config()), hand="Right", pinch_on_mm=40.0,
                     pinch_off_mm=60.0, out_dir=tmp_path)
    server = TelemetryServer(tele, port=0)
    assert server.start() is not None
    yield server, tele
    server.stop()


def _request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        return conn.getresponse().status
    finally:
        conn.close()


def test_j14_foreign_host_header_is_refused(dashboard):
    server, _ = dashboard
    host = {"Host": f"127.0.0.1:{server.port}"}
    assert _request(server.port, "GET", "/state", host) == 200
    assert _request(server.port, "GET", "/state",
                    {"Host": f"rebound.example:{server.port}"}) == 403


def test_j14_mark_needs_the_dashboard_header(dashboard):
    server, tele = dashboard
    host = {"Host": f"localhost:{server.port}"}
    assert _request(server.port, "POST", "/mark", host, b"x") == 403
    assert tele.marks == 0
    assert _request(server.port, "POST", "/mark",
                    {**host, "X-Leap": "1"}, b"x") == 200


def test_j14_mark_body_is_capped(dashboard):
    server, _ = dashboard
    headers = {"Host": f"127.0.0.1:{server.port}", "X-Leap": "1",
               "Content-Length": str(1 << 30)}
    try:
        status = _request(server.port, "POST", "/mark", headers, b"x")
    except (TimeoutError, OSError):
        status = None                   # 998e00e: blocked reading 1 GiB
    assert status == 413
