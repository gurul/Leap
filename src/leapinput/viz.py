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

PANEL_LINES = 18

# Interaction volume shown by the spatial view, in mm. Matches driver.Mapping.
VOL_X = (-120.0, 120.0)     # left .. right
VOL_Y = (0.0, 350.0)        # desk .. top of the tracking cone
VOL_Z = (-110.0, 110.0)     # far (top of screen) .. near (bottom of screen)

GRID_W, GRID_H = 33, 7


def _bar(value: float, lo: float, hi: float, width: int = 18, fill: str = "█") -> str:
    t = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    n = int(t * width)
    return fill * n + "░" * (width - n)


def _slider(value: float, lo: float, hi: float, width: int = 18) -> str:
    t = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    n = int(t * (width - 1))
    return "─" * n + "●" + "─" * (width - 1 - n)


def _norm(value: float, lo: float, hi: float) -> float:
    return 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _spatial(frame: Optional[HandFrame]) -> list[str]:
    """Top-down X/Z plane with a Y elevation gauge beside it.

    The X/Z plane is the one that maps to the screen, so this is literally where
    the cursor would be. Y is drawn as a separate vertical axis because it does
    not map to screen position at all — it is the engage/disengage dimension.
    """
    cx, cy = GRID_W // 2, GRID_H // 2
    cells = [["·" if (r == cy or c == cx) else " " for c in range(GRID_W)]
             for r in range(GRID_H)]

    hand_row = None
    if frame is not None:
        p = frame.position
        col = int(_norm(p.x, *VOL_X) * (GRID_W - 1))
        row = int(_norm(p.z, *VOL_Z) * (GRID_H - 1))
        cells[row][col] = f"{GREEN}{BOLD}●{RESET}"
        hand_row = int((1.0 - _norm(p.y, *VOL_Y)) * (GRID_H - 1))

    top = f"  {DIM}┌─{RESET} {CYAN}x → z{RESET} {DIM}top view{RESET} " + \
          DIM + "─" * (GRID_W - 15) + "┐" + RESET
    out = [top]
    for r in range(GRID_H):
        # Y gauge: a vertical axis to the right of the plane, filled to hand height.
        if frame is None:
            gauge = f"{DIM}│{RESET}"
        elif hand_row == r:
            gauge = f"{GREEN}{BOLD}◀{RESET}"
        else:
            filled = hand_row is not None and r > hand_row
            gauge = f"{CYAN}█{RESET}" if filled else f"{DIM}│{RESET}"
        label = ""
        if r == 0:
            label = f" {DIM}{VOL_Y[1]:.0f}{RESET}"
        elif r == GRID_H - 1:
            label = f" {DIM}{VOL_Y[0]:.0f} y{RESET}"
        out.append(f"  {DIM}│{RESET}" + "".join(cells[r]) + f"{DIM}│{RESET} {gauge}{label}")
    out.append(f"  {DIM}└{'─' * GRID_W}┘{RESET}  {DIM}far↑ near↓{RESET}")
    return out


def render(frame: Optional[HandFrame], target: Optional[tuple] = None,
           hand: str = "Right") -> list[str]:
    """Return exactly PANEL_LINES lines describing the current frame."""
    width = min(shutil.get_terminal_size((80, 24)).columns, 72)
    rule = DIM + "─" * width + RESET
    lines = [rule]

    if frame is None:
        lines.append(f"  {RED}no {hand.lower()} hand in view{RESET}   "
                     f"{DIM}hold your hand above the device, palm down{RESET}")
        lines += _spatial(None)
        lines += [
            f"  {DIM}x{RESET}      —    {DIM}y{RESET}      —    {DIM}z{RESET}      —",
            "", "", "",
        ]
    else:
        p, v = frame.position, frame.palm_velocity
        names = ("T", "I", "M", "R", "P")
        fingers = "  ".join(
            (GREEN + f"{n}●" + RESET) if ext else (DIM + f"{n}·" + RESET)
            for n, ext in zip(names, frame.extended)
        )
        engaged = (GREEN + "engaged" + RESET) if p.y > 90 else (YELLOW + "too low" + RESET)
        lines.append(f"  {BOLD}{frame.side.upper()}{RESET} hand   "
                     f"{DIM}confidence{RESET} {frame.confidence:.2f}   "
                     f"{DIM}id{RESET} {frame.hand_id}   {engaged}")
        lines += _spatial(frame)
        # All three axes, same treatment. y is not a lesser dimension — it is the
        # one that decides whether anything happens at all.
        lines += [
            f"  {CYAN}x{RESET} {p.x:>+6.0f}mm {_slider(p.x, *VOL_X)} "
            f"{DIM}left→right{RESET}",
            f"  {CYAN}y{RESET} {p.y:>+6.0f}mm {_slider(p.y, *VOL_Y)} "
            f"{DIM}desk→up{RESET}",
            f"  {CYAN}z{RESET} {p.z:>+6.0f}mm {_slider(p.z, *VOL_Z)} "
            f"{DIM}far→near{RESET}",
            f"  {DIM}pinch{RESET} {frame.pinch_distance:>4.0f}mm "
            f"{_bar(80 - frame.pinch_distance, 0, 80, 10)}  "
            f"{DIM}grab{RESET} {frame.grab_strength:.2f} "
            f"{_bar(frame.grab_strength, 0, 1, 10)}  {fingers}",
            f"  {DIM}velocity{RESET}  x{v.x:>+5.0f}  y{v.y:>+5.0f}  z{v.z:>+5.0f} "
            f"{DIM}mm/s{RESET}",
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
