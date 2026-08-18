"""Guided practice room: step-by-step visual tutorial over the camera preview.

`leapinput --tutorial` walks through the whole vocabulary one gesture at a
time — point, click, drag, park, then the pose commands — advancing when the
REAL pipeline detects the real gesture, so completing the tutorial *is* the
end-to-end test of the build. It forces the dry-run backend: a practice room
must not fight you for the actual cursor.

The tracker is deliberately cv2-free and consumes the same IntentEvents and
CommandEvents the drivers do, so every step transition is unit-testable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .commands import Command, CommandEvent
from .gestures import Intent, IntentEvent


@dataclass
class Step:
    title: str
    hint: str
    goal: int = 1                   # progress units to complete
    count: int = 0

    @property
    def done(self) -> bool:
        return self.count >= self.goal


def make_steps() -> list[Step]:
    return [
        Step("Show your hand",
             "raise your hand into the camera view"),
        Step("Point and move",
             "point (1 finger) and steer the cursor around", goal=30),
        Step("Pinch to click",
             "touch thumb and index together, then open them"),
        Step("Fist to drag",
             "make a fist, move it sideways, then point again", goal=12),
        Step("Open hand to park",
             "open all five fingers — the cursor parks so you can reposition"),
        Step("Frame a pane",
             "make an L with thumb+index on BOTH hands, frame a rectangle, "
             "hold until the ring fills, release"),
        Step("OK for Mission Control",
             "pinch with middle+ring+pinky extended, hold, release"),
        Step("ILY to pause",
             "thumb + index + pinky out, hold 1s — everything pauses"),
        Step("ILY to resume",
             "same pose again brings it back. You're in control"),
    ]


class TutorialTracker:
    """Feeds on the live event streams; owns which step the user is on."""

    FLASH_S = 1.2                   # how long the "nice!" flash lingers

    def __init__(self):
        self.steps = make_steps()
        self.index = 0
        self._saw_select_down = False
        self._grab_held = False
        self._completed_at: Optional[float] = None

    @property
    def current(self) -> Optional[Step]:
        return self.steps[self.index] if self.index < len(self.steps) else None

    @property
    def done(self) -> bool:
        return self.current is None

    def _advance(self) -> None:
        self._completed_at = time.monotonic()
        self.index += 1

    def _bump(self, n: int = 1) -> None:
        step = self.current
        step.count += n
        if step.done:
            self._advance()

    @property
    def flash(self) -> bool:
        """True briefly after each completed step — draw the checkmark."""
        return (self._completed_at is not None
                and time.monotonic() - self._completed_at < self.FLASH_S)

    def on_intent(self, event: IntentEvent) -> None:
        i, intent = self.index, event.intent
        if i == 0 and intent is Intent.ENGAGE:
            self._bump()
        elif i == 1 and intent is Intent.POINT_MOVE:
            self._bump()
        elif i == 2:
            if intent is Intent.SELECT_DOWN:
                self._saw_select_down = True
            elif intent is Intent.SELECT_UP and self._saw_select_down:
                self._bump()
        elif i == 3:
            if intent is Intent.GRAB_DOWN:
                self._grab_held = True
            elif intent is Intent.GRAB_UP:
                self._grab_held = False
            elif intent is Intent.POINT_MOVE and self._grab_held:
                self._bump()
        elif i == 4 and intent is Intent.CLUTCH_UP:
            self._bump()

    def on_command(self, event: CommandEvent) -> None:
        i, cmd = self.index, event.command
        if i == 5 and cmd is Command.NEW_PANE:
            self._bump()
        elif i == 6 and cmd is Command.MISSION_CONTROL:
            self._bump()
        elif i == 7 and cmd is Command.TOGGLE and not event.data.get("enabled"):
            self._bump()
        elif i == 8 and cmd is Command.TOGGLE and event.data.get("enabled"):
            self._bump()


def draw(cv2, bgr, tracker: TutorialTracker) -> None:
    """Banner over the preview: step, instruction, progress, completion flash."""
    h, w = bgr.shape[:2]
    cv2.rectangle(bgr, (0, 0), (w, 96), (30, 30, 30), -1)
    if tracker.done:
        cv2.putText(bgr, "Tutorial complete — you know the whole vocabulary!",
                    (12, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 0), 2,
                    cv2.LINE_AA)
        cv2.putText(bgr, "run again with --backend quartz to drive the real cursor",
                    (12, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200),
                    1, cv2.LINE_AA)
        return
    step = tracker.current
    n = len(tracker.steps)
    cv2.putText(bgr, f"step {tracker.index + 1}/{n}: {step.title}",
                (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 200, 0), 2,
                cv2.LINE_AA)
    cv2.putText(bgr, step.hint, (12, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (255, 255, 255), 1, cv2.LINE_AA)
    if step.goal > 1:
        frac = step.count / step.goal
        cv2.rectangle(bgr, (12, 82), (12 + int(frac * (w - 24)), 90),
                      (255, 200, 0), -1)
        cv2.rectangle(bgr, (12, 82), (w - 12, 90), (120, 120, 120), 1)
    if tracker.flash:
        cv2.putText(bgr, "nice!", (w - 130, 44), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 220, 0), 3, cv2.LINE_AA)
