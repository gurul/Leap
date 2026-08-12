"""Driver layer: Intent stream -> Backend calls.

`DirectDriver` is the low-latency path — the hand *is* the cursor. A future CUA driver
consumes the same Intent stream but treats gestures as high-level commands handed to
an agent rather than as pointer motion. Both subscribe to `GestureEngine`; they are
interchangeable, and can run side by side (direct pointing, agent-dispatched swipes).
"""

from __future__ import annotations

from dataclasses import dataclass

from .actions import Backend
from .capture import HandFrame
from .gestures import Intent, IntentEvent


@dataclass
class Mapping:
    """The interaction box, in millimetres, in Leap device coordinates.

    Sized deliberately small. A big box means big arm movements, and big arm movements
    are what killed this input category — see docs/context/ergonomics. Small box plus
    a wide gain is the same screen coverage for a fraction of the shoulder load.
    """

    x_min: float = -110.0
    x_max: float = 110.0
    z_far: float = -100.0    # away from you -> top of screen
    z_near: float = 100.0    # toward you   -> bottom of screen

    smoothing: float = 0.45  # EMA on top of Leap's stabilized position
    scroll_gain: float = 1.0


def _remap(value: float, lo: float, hi: float, out_hi: float) -> float:
    t = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, t)) * out_hi


class DirectDriver:
    """Hand as mouse. Pointer position is only ever updated while engaged."""

    def __init__(self, backend: Backend, mapping: Mapping | None = None):
        self.backend = backend
        self.map = mapping or Mapping()
        self.w, self.h = backend.screen
        self.x, self.y = self.w / 2.0, self.h / 2.0
        self._primed = False

    def _project(self, frame: HandFrame) -> tuple[float, float]:
        p = frame.palm_stable
        return (_remap(p.x, self.map.x_min, self.map.x_max, self.w),
                _remap(p.z, self.map.z_far, self.map.z_near, self.h))

    def on_intent(self, event: IntentEvent) -> None:
        handler = getattr(self, f"_on_{event.intent.name.lower()}", None)
        if handler:
            handler(event)

    # --- engagement ---------------------------------------------------------

    def _on_engage(self, event: IntentEvent) -> None:
        # Re-engaging should not fling the cursor across the screen from wherever
        # it was left. Snap to the hand's current projection instead of gliding.
        self._primed = False

    def _on_disengage(self, event: IntentEvent) -> None:
        self._primed = False

    # --- pointer ------------------------------------------------------------

    def _on_point_move(self, event: IntentEvent) -> None:
        tx, ty = self._project(event.frame)
        if not self._primed:
            self.x, self.y, self._primed = tx, ty, True
        else:
            a = self.map.smoothing
            self.x += (tx - self.x) * a
            self.y += (ty - self.y) * a
        self.backend.move(self.x, self.y)

    # --- buttons ------------------------------------------------------------

    def _on_select_down(self, event: IntentEvent) -> None:
        self.backend.down(self.x, self.y)

    def _on_select_up(self, event: IntentEvent) -> None:
        self.backend.up(self.x, self.y)

    def _on_scroll(self, event: IntentEvent) -> None:
        self.backend.scroll(event.data.get("dy", 0.0) * self.map.scroll_gain)


# macOS virtual keycodes for the shortcuts the swipe gestures map to.
_KEY_LEFT_ARROW, _KEY_RIGHT_ARROW, _KEY_TAB = 0x7B, 0x7C, 0x30


class ShortcutDriver:
    """Swipes -> system shortcuts. Separate from DirectDriver so pointer control and
    discrete commands can be enabled independently."""

    def __init__(self, backend: Backend):
        self.backend = backend

    def on_intent(self, event: IntentEvent) -> None:
        if event.intent is Intent.SWIPE_LEFT:
            self.backend.key(_KEY_LEFT_ARROW, ctrl=True)      # previous Space
        elif event.intent is Intent.SWIPE_RIGHT:
            self.backend.key(_KEY_RIGHT_ARROW, ctrl=True)     # next Space
        elif event.intent is Intent.SWIPE_UP:
            self.backend.key(_KEY_TAB, cmd=True)              # app switcher
