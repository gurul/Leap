"""Out-of-process supervisor that releases held input if the main process dies.

The failure this exists for: the driver posts a mouse-down for a pinch, or holds
Option for the mic, then the Python process wedges, hits an unhandled exception
in a C callback, or is SIGKILLed. The button or the modifier stays down. macOS
now believes you are mid-drag on every window you touch, or types Option
characters everywhere, and you have to fight it with the very machine that is
stuck.

No in-process handler covers this. `finally:` does not run on SIGKILL, and a
deadlocked interpreter never reaches it. So the release lives in a *different
process* whose only job is to notice this one stopped.

Mechanism: the parent spawns the guard with a pipe and holds the write end open.
The guard blocks reading it. Any parent exit — clean, crashed, or killed — closes
the pipe, the read returns EOF, and the guard posts the releases. It cannot
miss, because it depends on the OS reclaiming a file descriptor rather than on the
parent successfully running any code.

The pipe also carries a one-byte protocol (2026-11-15), because the shipped
tool's only held input is Option, not a mouse button:

    b"O"   the parent is about to press Option
    b"o"   the parent released Option

At EOF the guard always releases all three mouse buttons (unchanged), and
releases Option when the last byte said it is held. Any other byte, or a read
error, means the guard can no longer tell — so it releases Option too. Fail
toward release: a spare Option key-up is harmless, a missed one is not.

On start the guard writes b"R" to stdout once it can actually post (or write
to the sink), so the parent knows the safety net exists.

LEAPINPUT_GUARD_SINK=<file>: post nothing; append one line per release that
would have been posted (left, right, center, option). The test suite runs with
it set, so tests never post real input.

    python -m leapinput.guard      # normally spawned, not run by hand
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
from typing import Optional

SINK_ENV = "LEAPINPUT_GUARD_SINK"
KEY_OPTION = 58                     # kVK_Option, the dictation hold
READY = b"R"
OPTION_DOWN, OPTION_UP = b"O", b"o"
READY_TIMEOUT_S = 5.0


def _sink() -> Optional[str]:
    return os.environ.get(SINK_ENV) or None


def _write_sink(path: str, names) -> None:
    with open(path, "a") as fh:
        for name in names:
            fh.write(f"release {name}\n")


def release_all_buttons(option: bool = False) -> None:
    """Post button-up for every mouse button at the current cursor position,
    and the Option key-up when `option` is set."""
    names = ["left", "right", "center"] + (["option"] if option else [])
    sink = _sink()
    if sink is not None:
        _write_sink(sink, names)
        return
    from Quartz.CoreGraphics import (
        CGEventCreateKeyboardEvent, CGEventCreateMouseEvent, CGEventGetLocation,
        CGEventCreate, CGEventPost, CGEventSetFlags, CGEventSourceCreate,
        kCGEventLeftMouseUp, kCGEventRightMouseUp, kCGEventOtherMouseUp,
        kCGEventSourceStateHIDSystemState,
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
    if option:
        # Same shape as QuartzBackend.key_hold's release: an HID-state source
        # and flags cleared to 0. An up event that still asserts alternate
        # leaves the modifier stuck down system-wide.
        src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
        up = CGEventCreateKeyboardEvent(src, KEY_OPTION, False)
        CGEventSetFlags(up, 0)
        CGEventPost(kCGHIDEventTap, up)


def _ready_check() -> None:
    """Raise if the release could not run: better to say so at start than to
    discover it at the one moment it matters."""
    if _sink() is not None:
        return
    import Quartz.CoreGraphics  # noqa: F401


def read_until_eof(stream) -> bool:
    """Consume the parent's protocol bytes until EOF. True when Option must
    be released at the end."""
    option = False
    try:
        while True:
            b = stream.read(1)
            if not b:
                return option
            if b == OPTION_DOWN:
                option = True
            elif b == OPTION_UP:
                option = False
            else:
                # A byte we do not understand: we no longer know whether
                # Option is held. Stay alive (the parent may still need us),
                # but release Option at the end no matter what follows.
                print(f"guard: unknown byte {b!r}; Option will be released",
                      file=sys.stderr)
                return _drain(stream) or True
    except (KeyboardInterrupt, OSError):
        return True


def _drain(stream) -> bool:
    try:
        while stream.read(1):
            pass
    except (KeyboardInterrupt, OSError):
        pass
    return True


def main() -> int:
    """Block until the parent's pipe closes, then release."""
    try:
        _ready_check()
    except Exception as exc:
        print(f"guard: cannot post releases: {exc}", file=sys.stderr)
        return 1
    try:
        sys.stdout.buffer.write(READY)
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        pass                        # nobody is listening; still guard
    option = read_until_eof(sys.stdin.buffer)
    try:
        release_all_buttons(option=option)
        print("guard: released mouse buttons"
              + (" and Option" if option else ""), file=sys.stderr)
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
        self.ready = False

    def start(self) -> "Guard":
        self.proc = subprocess.Popen(
            # -P: do not put the working directory first on sys.path, so a
            # stray leapinput/ or Quartz.py in the cwd cannot replace the
            # release code.
            [sys.executable, "-P", "-m", "leapinput.guard"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Its own process group, so a Ctrl-C aimed at the parent's group does
            # not also kill the guard before it can do its job.
            start_new_session=True,
        )
        self.ready = self._wait_ready()
        if self.ready:
            print("guard: ready (releases buttons and Option if this process "
                  "dies)", file=sys.stderr)
        else:
            print("guard: NOT READY — if this session dies, a held mouse "
                  "button or Option will stay down. Check that "
                  "`python -m leapinput.guard` runs in this venv.",
                  file=sys.stderr)
        return self

    def _wait_ready(self) -> bool:
        out = self.proc.stdout if self.proc else None
        if out is None:
            return False
        try:
            r, _, _ = select.select([out], [], [], READY_TIMEOUT_S)
            return bool(r) and os.read(out.fileno(), 1) == READY
        except (OSError, ValueError):
            return False

    def option(self, held: bool) -> None:
        """Tell the guard Option is about to be pressed (held=True) or was
        released. Called from the gesture path: it logs, never raises."""
        proc = self.proc
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(OPTION_DOWN if held else OPTION_UP)
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            print(f"guard: could not report Option "
                  f"{'down' if held else 'up'}: {exc}", file=sys.stderr)

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
            if self.proc.stdout:
                try:
                    self.proc.stdout.close()
                except OSError:
                    pass
            self.proc = None

    def __enter__(self) -> "Guard":
        return self.start()

    def __exit__(self, *exc) -> bool:
        self.stop()
        return False


if __name__ == "__main__":
    raise SystemExit(main())
