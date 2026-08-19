"""Phone-camera source tests: shim semantics and page contract, no network.

The full TLS + WebRTC media path is covered by a loopback harness run manually
(synthetic aiortc sender); these tests pin the pieces that must not drift: the
freshest-frame-wins shim contract and the capture page's constraints.
"""

import threading
import time

from leapinput.phonecam import PAGE, _PhoneCapture, lan_ip


class FakeServer:
    """Just the cond/frame/seq surface _PhoneCapture reads."""

    def __init__(self):
        self.cond = threading.Condition()
        self.frame = None
        self.seq = 0
        self.stopped = False

    def push(self, frame):
        with self.cond:
            self.frame = frame
            self.seq += 1
            self.cond.notify_all()

    def stop(self):
        self.stopped = True


def test_read_times_out_false_when_nothing_streams():
    cap = _PhoneCapture(FakeServer())
    t0 = time.monotonic()
    ok, frame = cap.read()
    assert ok is False and frame is None
    assert time.monotonic() - t0 < 2.0      # bounded wait, not a hang


def test_read_serves_each_frame_once_and_always_the_newest():
    srv = FakeServer()
    cap = _PhoneCapture(srv)
    srv.push("frame-1")
    srv.push("frame-2")                     # arrives before anyone reads
    ok, frame = cap.read()
    assert ok and frame == "frame-2"        # newest wins, frame-1 dropped
    ok, frame = cap.read()
    assert ok is False                      # same frame is never served twice


def test_read_wakes_on_late_arrival():
    srv = FakeServer()
    cap = _PhoneCapture(srv)
    threading.Timer(0.1, srv.push, args=("late",)).start()
    ok, frame = cap.read()
    assert ok and frame == "late"


def test_release_stops_server_and_grab_is_free():
    srv = FakeServer()
    cap = _PhoneCapture(srv)
    assert cap.isOpened() and cap.grab()
    cap.release()
    assert srv.stopped


def test_page_asks_for_60fps_and_stays_lan_only():
    assert "frameRate: { ideal: 60, max: 60 }" in PAGE
    assert "getUserMedia" in PAGE
    assert "iceServers: []" in PAGE         # no STUN: never leaves the LAN


def test_lan_ip_is_dotted_quad():
    ip = lan_ip()
    assert ip.count(".") == 3


# -- aiortc low-latency patches ------------------------------------------------

def _packet(seq, ts, marker=0, data=b"x"):
    from aiortc.rtp import RtpPacket
    p = RtpPacket(payload_type=96, sequence_number=seq, timestamp=ts)
    p.marker = marker
    p._data = data
    return p


def test_marker_bit_emits_frame_without_waiting_for_next_frame():
    from leapinput.phonecam import _patch_aiortc_low_latency
    _patch_aiortc_low_latency()
    from aiortc.jitterbuffer import JitterBuffer

    jb = JitterBuffer(capacity=16, is_video=True)
    pli, frame = jb.add(_packet(0, ts=1000, data=b"a"))
    assert frame is None                        # frame not complete yet
    pli, frame = jb.add(_packet(1, ts=1000, marker=1, data=b"b"))
    # Stock aiortc returns None here and waits ~16.7ms for frame 2's first
    # packet; the patch emits on the marker bit immediately.
    assert frame is not None and frame.data == b"ab"
    # buffer advanced: the next frame assembles and emits normally
    pli, frame = jb.add(_packet(2, ts=2000, marker=1, data=b"c"))
    assert frame is not None and frame.data == b"c"


def test_marker_patch_leaves_incomplete_frames_alone():
    from leapinput.phonecam import _patch_aiortc_low_latency
    _patch_aiortc_low_latency()
    from aiortc.jitterbuffer import JitterBuffer

    jb = JitterBuffer(capacity=16, is_video=True)
    pli, frame = jb.add(_packet(0, ts=1000))
    assert frame is None                        # no marker, no next frame
    # arrival of the NEXT frame's packet still releases it (original path)
    pli, frame = jb.add(_packet(1, ts=2000))
    assert frame is not None and frame.timestamp == 1000


def test_video_jitter_capacity_bounded_to_64():
    from leapinput.phonecam import _patch_aiortc_low_latency
    _patch_aiortc_low_latency()
    from aiortc.jitterbuffer import JitterBuffer

    assert JitterBuffer(capacity=128, is_video=True).capacity == 64
    # audio and explicit capacities are untouched
    assert JitterBuffer(capacity=128, is_video=False).capacity == 128
    assert JitterBuffer(capacity=16, is_video=True).capacity == 16


def test_page_prefers_framerate_and_hints_motion():
    assert "contentHint = 'motion'" in PAGE
    assert "maintain-framerate" in PAGE


# --- IMU: the stand-bump detector ---------------------------------------------

def _bare_server():
    """A server instance without network/token side effects — _on_imu is
    pure state-machine over its own attributes."""
    from leapinput.phonecam import _PhoneCamServer
    s = _PhoneCamServer.__new__(_PhoneCamServer)
    s.imu_gravity = None
    s.stand_moved_at = 0.0
    s._imu_warned_at = 0.0
    return s


def test_steady_gravity_never_reads_as_a_bump():
    s = _bare_server()
    for _ in range(50):                       # phone at rest on the stand
        s._on_imu({"x": 0.1, "y": 9.7, "z": 1.2})
    assert s.stand_moved_at == 0.0
    assert s.imu_gravity is not None
    assert abs(s.imu_gravity[1] - 9.7) < 0.01


def test_a_stand_bump_is_detected_and_slow_tilt_is_not():
    s = _bare_server()
    for _ in range(20):
        s._on_imu({"x": 0.1, "y": 9.7, "z": 1.2})
    # Slow drift (thermal creep, tiny slippage): tracked into gravity, no bump.
    for i in range(40):
        s._on_imu({"x": 0.1 + i * 0.01, "y": 9.7, "z": 1.2})
    assert s.stand_moved_at == 0.0
    # A real knock: several m/s^2 away from the gravity estimate.
    s._on_imu({"x": 5.0, "y": 6.0, "z": 1.2})
    assert s.stand_moved_at > 0.0
