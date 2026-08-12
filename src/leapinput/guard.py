"""Out-of-process supervisor that releases the mouse if the main process dies.

The failure this exists for: the driver posts a mouse-down for a pinch, then the
Python process wedges, hits an unhandled exception in a C callback, or is SIGKILLed.
The button stays down. macOS now believes you are mid-drag on every window you
touch, and you have to fight a stuck button to fix it — with the very machine that
is stuck.

No in-process handler covers this. `finally:` does not run on SIGKILL, and a
deadlocked interpreter never reaches it. So the release lives in a *different
process* whose only job is to notice this one stopped.

Mechanism: the parent spawns the guard with a pipe and holds the write end open.
The guard blocks reading it. Any parent exit — clean, crashed, or killed — closes
the pipe, the read returns EOF, and the guard posts button-up events. It cannot
miss, because it depends on the OS reclaiming a file descriptor rather than on the
parent successfully running any code.

    python -m leapinput.guard      # normally spawned, not run by hand
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional


def release_all_buttons() -> None:
    """Post button-up for every mouse button at the current cursor position."""
    from Quartz.CoreGraphics import (
        CGEventCreateMouseEvent, CGEventGetLocation, CGEventCreate, CGEventPost,
        kCGEventLeftMouseUp, kCGEventRightMouseUp, kCGEventOtherMouseUp,
        kCGMouseButtonLeft, kCGMouseButtonRight, kCGMouseButtonCenter,
        kCGHIDEventTap,
    )

    where = CGEventGetLocation(CGEventCreate(None))
    for event_type, button in (
        (kCGEventLeftMouseUp, kCGMouseButtonLeft),
        (kCGEventRightMouseUp, kCGMouseButtonRight),
        (kCGEventOtherMouseUp, kCGMouseButtonCenter),
    ):
        CGEventPost(kCGHIDEventTap,
                    CGEventCreateMouseEvent(None, event_type, where, button))


def main() -> int:
    """Block until the parent's pipe closes, then release."""
    try:
        # Any read that returns empty means EOF means the parent is gone.
        while sys.stdin.buffer.read(1):
            pass
    except (KeyboardInterrupt, OSError):
        pass
    try:
        release_all_buttons()
        print("guard: released mouse buttons", file=sys.stderr)
    except Exception as exc:                    # never die silently
        print(f"guard: release FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


class Guard:
    """Spawns and owns the supervisor process.

    Deliberately not a daemon thread or an atexit hook — both live inside the
    process whose death is the thing being guarded against.
    """

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> "Guard":
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "leapinput.guard"],
            stdin=subprocess.PIPE,
            # Its own process group, so a Ctrl-C aimed at the parent's group does
            # not also kill the guard before it can do its job.
            start_new_session=True,
        )
        return self

    def stop(self) -> None:
        """Close the pipe, which is the signal to release and exit."""
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=3.0)
        except (subprocess.TimeoutExpired, OSError):
            self.proc.kill()
        finally:
            self.proc = None

    def __enter__(self) -> "Guard":
        return self.start()

    def __exit__(self, *exc) -> bool:
        self.stop()
        return False


if __name__ == "__main__":
    raise SystemExit(main())
