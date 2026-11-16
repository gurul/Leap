"""The supervisor must survive the failures in-process cleanup cannot.

Every guard here writes to LEAPINPUT_GUARD_SINK instead of posting events
(2026-11-15). Before that these tests posted real mouse-ups at the cursor on
every run, and passed even where the release could not run at all: they only
checked that the guard process exited. Now they assert the release lines.
"""

import os
import subprocess
import sys
import time

import pytest


def alive(pid: int) -> bool:
    return subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0


def spawn_parent_holding_a_guard(sink, hold_option: bool = False
                                 ) -> tuple[subprocess.Popen, int]:
    env = dict(os.environ, LEAPINPUT_GUARD_SINK=str(sink))
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time\n"
         "from leapinput.guard import Guard\n"
         "g = Guard().start()\n"
         "assert g.ready\n"
         + ("g.option(True)\n" if hold_option else "")
         + "print(g.proc.pid, flush=True)\n"
         "time.sleep(30)\n"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
    )
    return proc, int(proc.stdout.readline().strip())


def settle(pid: int, want: bool, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if alive(pid) == want:
            return True
        time.sleep(0.05)
    return alive(pid) == want


def released(sink) -> list[str]:
    return sink.read_text().split() if sink.exists() else []


def test_guard_releases_when_the_parent_is_sigkilled(tmp_path):
    """The case no `finally:` and no atexit hook can cover.

    If the parent is killed while holding a mouse button down, the button stays
    down and macOS thinks you are mid-drag on everything you touch. The guard
    depends only on the OS reclaiming a file descriptor, so it cannot be skipped.
    """
    sink = tmp_path / "sink.txt"
    parent, guard_pid = spawn_parent_holding_a_guard(sink)
    assert alive(guard_pid), "guard should be running while the parent lives"

    parent.kill()
    parent.wait()

    assert settle(guard_pid, want=False), \
        "guard outlived a SIGKILLed parent — the pipe EOF was not observed"
    lines = sink.read_text().splitlines()
    assert lines == ["release left", "release right", "release center"]


def test_guard_releases_option_held_at_sigkill(tmp_path):
    """The shipped tool holds Option for the mic, not a mouse button."""
    sink = tmp_path / "sink.txt"
    parent, guard_pid = spawn_parent_holding_a_guard(sink, hold_option=True)
    parent.kill()
    parent.wait()
    assert settle(guard_pid, want=False)
    assert "release option" in sink.read_text().splitlines()


def test_guard_exits_on_a_clean_stop(tmp_path):
    sink = tmp_path / "sink.txt"
    parent, guard_pid = spawn_parent_holding_a_guard(sink)
    parent.terminate()
    parent.wait()
    assert settle(guard_pid, want=False)
    assert "release left" in sink.read_text().splitlines()


def test_guard_stays_up_while_the_parent_lives(tmp_path):
    """A guard that exits early is worse than none — it reports safety it isn't
    providing."""
    sink = tmp_path / "sink.txt"
    parent, guard_pid = spawn_parent_holding_a_guard(sink)
    try:
        time.sleep(1.0)
        assert alive(guard_pid)
        assert not sink.exists(), "released while the parent still lives"
    finally:
        parent.kill()
        parent.wait()
