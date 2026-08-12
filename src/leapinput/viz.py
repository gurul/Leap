"""Live terminal view of what the sensor actually sees.

Built for the human in the loop: during capture you need to confirm the device
agrees with the pose you think you're holding *before* recording starts. Reading
that back off a JSONL file afterwards is how a whole session gets mislabeled.

Terminal rendering rather than a GUI window on purpose — it runs in the same shell
as the capture, needs no extra dependency, and survives over SSH.

    python -m leapinput.viz          # just watch the sensor
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from typing import Callable, Optional

from .capture import HandFrame, LeapSource, Snapshot

ESC = "\033["
DIM, BOLD, RESET = f"{ESC}2m", f"{ESC}1m", f"{ESC}0m"
GREEN, RED, YELLOW, CYAN = f"{ESC}32m", f"{ESC}31m", f"{ESC}33m", f"{ESC}36m"

PANEL_LINES = 11


def _bar(value: float, lo: float, hi: float, width: int = 18, fill: str = "█") -> str:
    t = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    n = int(t * width)
    return fill * n + "░" * (width - n)


def _slider(value: float, lo: float, hi: float, width: int = 18) -> str:
    t = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    n = int(t * (width - 1))
    return "─" * n + "●" + "─" * (width - 1 - n)


def render(frame: Optional[HandFrame], target: Optional[tuple] = None,
           hand: str = "Right") -> list[str]:
    """Return exactly PANEL_LINES lines describing the current frame."""
    width = min(shutil.get_terminal_size((80, 24)).columns, 72)
    rule = DIM + "─" * width + RESET
    lines = [rule]

    if frame is None:
        lines += [
            f"  {RED}no {hand.lower()} hand in view{RESET}",
            f"  {DIM}hold your hand above the device, palm down{RESET}",
            "", "", "", "", "",
        ]
    else:
        p = frame.position
        names = ("T", "I", "M", "R", "P")
        fingers = "  ".join(
            (GREEN + f"{n}●" + RESET) if ext else (DIM + f"{n}·" + RESET)
            for n, ext in zip(names, frame.extended)
        )
        lines += [
            f"  {BOLD}{frame.side.upper()}{RESET} hand   "
            f"{DIM}confidence{RESET} {frame.confidence:.2f}   "
            f"{DIM}id{RESET} {frame.hand_id}",
            f"  {DIM}x{RESET} {p.x:>+6.0f}  {_slider(p.x, -120, 120)}  {DIM}mm{RESET}",
            f"  {DIM}z{RESET} {p.z:>+6.0f}  {_slider(p.z, -110, 110)}  "
            f"{DIM}(− far / + near){RESET}",
            f"  {DIM}height{RESET} {p.y:>4.0f}  {_bar(p.y, 0, 350)}  "
            f"{GREEN + 'engaged' + RESET if p.y > 90 else DIM + 'resting' + RESET}",
            f"  {DIM}pinch{RESET} {frame.pinch_distance:>5.0f}mm "
            f"{_bar(80 - frame.pinch_distance, 0, 80)}  "
            f"{DIM}str{RESET} {frame.pinch_strength:.2f}",
            f"  {DIM}grab{RESET}  {frame.grab_strength:>5.2f}   "
            f"{_bar(frame.grab_strength, 0, 1)}  "
            f"{DIM}angle{RESET} {frame.grab_angle:.2f}",
            f"  {DIM}fingers{RESET}  {fingers}   "
            f"{DIM}vel{RESET} x{frame.palm_velocity.x:>+5.0f} "
            f"z{frame.palm_velocity.z:>+5.0f} {DIM}mm/s{RESET}",
        ]

    lines.append(rule)
    if target is None:
        lines.append("")
    else:
        desc, predicate = target
        ok = frame is not None and _safe(predicate, frame)
        badge = f"{GREEN}{BOLD}  ✓ MATCH  {RESET}" if ok else f"{RED}  ✗ not yet  {RESET}"
        lines.append(f"  {CYAN}target{RESET} {desc:<34}{badge}")
    return lines[:PANEL_LINES] + [""] * max(0, PANEL_LINES - len(lines))


def _safe(predicate: Callable, frame: HandFrame) -> bool:
    try:
        return bool(predicate(frame))
    except Exception:
        return False


class LivePanel:
    """Redraws a fixed-height panel in place on a background thread."""

    def __init__(self, source: LeapSource, hand: str = "Right", fps: float = 20.0):
        self.source, self.hand, self.period = source, hand, 1.0 / fps
        self.target: Optional[tuple] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._enabled = sys.stdout.isatty()

    def _frame(self) -> Optional[HandFrame]:
        return self.source.latest.get(self.hand)

    def _loop(self) -> None:
        sys.stdout.write("\n" * PANEL_LINES)
        while not self._stop.is_set():
            lines = render(self._frame(), self.target, self.hand)
            out = [f"{ESC}{PANEL_LINES}A"]
            for line in lines:
                out.append(f"\r{ESC}2K{line}\n")
            sys.stdout.write("".join(out))
            sys.stdout.flush()
            self._stop.wait(self.period)

    def start(self) -> "LivePanel":
        if self._enabled and self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="leapinput.viz")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    args = ap.parse_args(argv)

    source = LeapSource()
    source.subscribe(lambda snap: None)
    print(f"Watching {args.hand.lower()} hand. Ctrl-C to quit.")
    with source.open():
        with LivePanel(source, args.hand):
            try:
                while True:
                    time.sleep(0.2)
            except KeyboardInterrupt:
                pass
    print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
