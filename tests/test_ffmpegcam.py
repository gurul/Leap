"""FFmpegCapture against a fake ffmpeg that writes raw frames to stdout."""

import stat
import sys
import time

from leapinput.ffmpegcam import FFmpegCapture, wants_ffmpeg

W, H = 4, 2


def _fake_ffmpeg(tmp_path, frames: int, hold_s: float = 0.0):
    script = tmp_path / "ffmpeg"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        f"for i in range({frames}):\n"
        f"    sys.stdout.buffer.write(bytes([i]) * {W * H * 3})\n"
        "    sys.stdout.buffer.flush()\n"
        f"time.sleep({hold_s})\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_serves_newest_frame_once(tmp_path):
    cap = FFmpegCapture("cam", W, H, ffmpeg=_fake_ffmpeg(tmp_path, 3, 2.0))
    time.sleep(0.5)                     # all three frames land; newest wins
    ok, frame = cap.read()
    assert ok and frame.shape == (H, W, 3) and frame[0, 0, 0] == 2
    ok, _ = cap.read()                  # nothing newer: no repeat of the old one
    assert not ok
    cap.release()


def test_closed_stream_reads_false(tmp_path):
    cap = FFmpegCapture("cam", W, H, ffmpeg=_fake_ffmpeg(tmp_path, 0))
    time.sleep(0.5)
    assert cap.read() == (False, None)
    assert not cap.isOpened()
    cap.release()


def test_routing_by_name():
    assert wants_ffmpeg("OBSBOT Tiny 3 StreamCamera")
    assert not wants_ffmpeg("MacBook Pro Camera")
