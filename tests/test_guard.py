"""The supervisor must survive the failures in-process cleanup cannot."""

import subprocess
import sys
import time

import pytest


def alive(pid: int) -> bool:
    return subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0


def spawn_parent_holding_a_guard() -> tuple[subprocess.Popen, int]:
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time\n"
         "from leapinput.guard import Guard\n"
         "g = Guard().start()\n"
         "print(g.proc.pid, flush=True)\n"
         "time.sleep(30)\n"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    return proc, int(proc.stdout.readline().strip())


def settle(pid: int, want: bool, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if alive(pid) == want:
            return True
        time.sleep(0.05)
    return alive(pid) == want


def test_guard_releases_when_the_parent_is_sigkilled():
    """The case no `finally:` and no atexit hook can cover.

    If the parent is killed while holding a mouse button down, the button stays
    down and macOS thinks you are mid-drag on everything you touch. The guard
    depends only on the OS reclaiming a file descriptor, so it cannot be skipped.
    """
    parent, guard_pid = spawn_parent_holding_a_guard()
    assert alive(guard_pid), "guard should be running while the parent lives"

    parent.kill()
    parent.wait()

    assert settle(guard_pid, want=False), \
        "guard outlived a SIGKILLed parent — the pipe EOF was not observed"


def test_guard_exits_on_a_clean_stop():
    parent, guard_pid = spawn_parent_holding_a_guard()
    parent.terminate()
    parent.wait()
    assert settle(guard_pid, want=False)


def test_guard_stays_up_while_the_parent_lives():
    """A guard that exits early is worse than none — it reports safety it isn't
    providing."""
    parent, guard_pid = spawn_parent_holding_a_guard()
    try:
        time.sleep(1.0)
        assert alive(guard_pid)
    finally:
        parent.kill()
        parent.wait()
