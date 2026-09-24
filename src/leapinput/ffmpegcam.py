"""ffmpeg-backed capture for cameras OpenCV's AVFoundation backend cannot read.

The OBSBOT Tiny 3 opens under cv2.VideoCapture and then delivers zero frames in
every mode (measured 2026-09-24: 0 frames in 10s, while the MacBook camera gave
60 fps through the same code). ffmpeg's avfoundation input reads it fine at
1280x720 @ 120 fps, so this module runs ffmpeg as a child process and exposes
its raw BGR stream through the same cv2.VideoCapture shape CameraSource uses.

The ffmpeg child inherits the responsible app of the process tree, so the
Camera grant is still asked (and remembered) as "Leap Menubar".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from typing import Optional

import numpy as np

# Cameras that must go through ffmpeg, matched as a lowercase name substring.
FFMPEG_CAMERAS = ("obsbot",)

# Launched from the menu bar, PATH is launchd's minimal one — no Homebrew.
_FALLBACK_PATHS = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")


def ffmpeg_path() -> Optional[str]:
    found = shutil.which("ffmpeg")
    if found:
        return found
    return next((p for p in _FALLBACK_PATHS if os.access(p, os.X_OK)), None)


def wants_ffmpeg(name: str) -> bool:
    return any(k in name.lower() for k in FFMPEG_CAMERAS)


class FFmpegCapture:
    """cv2.VideoCapture-shaped reader over an ffmpeg avfoundation child.

    A reader thread keeps only the NEWEST frame. read() blocks until a frame
    newer than the last one served arrives, so slow detection drops frames
    instead of queueing them — the same contract as phonecam._PhoneCapture,
    and grab()-draining is a no-op by construction.
    """

    def __init__(self, device: str, width: int = 1280, height: int = 720,
                 fps: int = 120, ffmpeg: Optional[str] = None):
        self.width, self.height, self.fps = width, height, fps
        self._frame_bytes = width * height * 3
        exe = ffmpeg or ffmpeg_path()
        if exe is None:
            raise RuntimeError("ffmpeg not found — brew install ffmpeg")
        self._proc = subprocess.Popen(
            [exe, "-hide_banner", "-loglevel", "error", "-nostdin",
             "-fflags", "nobuffer", "-flags", "low_delay",
             "-f", "avfoundation", "-framerate", str(fps),
             "-video_size", f"{width}x{height}", "-pixel_format", "uyvy422",
             "-i", f"{device}:none",
             "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"],
            stdout=subprocess.PIPE, stderr=sys.stderr,
            bufsize=self._frame_bytes)
        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0
        self._served = 0
        self._closed = False
        self._thread = threading.Thread(target=self._reader, name="ffmpegcam",
                                        daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        out = self._proc.stdout
        while True:
            buf = bytearray(self._frame_bytes)
            view = memoryview(buf)
            got = 0
            while got < self._frame_bytes:
                n = out.readinto(view[got:])
                if not n:                       # ffmpeg exited or was killed
                    with self._cond:
                        self._closed = True
                        self._cond.notify_all()
                    return
                got += n
            frame = np.frombuffer(buf, np.uint8).reshape(
                self.height, self.width, 3)
            with self._cond:
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()

    def isOpened(self) -> bool:  # noqa: N802 - matching cv2's camelCase
        return not self._closed and self._proc.poll() is None

    def grab(self) -> bool:
        return True

    def read(self):
        with self._cond:
            self._cond.wait_for(
                lambda: self._seq > self._served or self._closed, timeout=1.0)
            if self._seq <= self._served:
                return False, None
            self._served = self._seq
            return True, self._frame

    def get(self, prop: int) -> float:
        import cv2
        return {cv2.CAP_PROP_FRAME_WIDTH: float(self.width),
                cv2.CAP_PROP_FRAME_HEIGHT: float(self.height),
                cv2.CAP_PROP_FPS: float(self.fps)}.get(prop, 0.0)

    def set(self, prop: int, value: float) -> bool:
        return False

    def release(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._thread.join(timeout=2)
