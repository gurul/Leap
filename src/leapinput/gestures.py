"""Gesture layer: HandFrame stream -> discrete Intents + a continuous pointer signal.

Two hard-won rules shape everything here:

1. **Every discrete gesture is a Schmitt trigger, never a bare threshold.** A single
   threshold on a noisy 110 Hz signal fires and unfires dozens of times per second at
   the boundary. Separate enter/exit thresholds plus a minimum dwell make it stable.

2. **Engagement is explicit and fails safe.** The user's hand leaves the interaction
   volume constantly — reaching for coffee, scratching their nose. Losing tracking or
   dropping below the engage height releases everything held and disengages. There is
   no state in which the machine keeps acting on a hand that is no longer there.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .capture import HandFrame, Snapshot


class Intent(str, Enum):
    """What the user meant. Deliberately device- and action-agnostic — this is the
    seam a CUA driver subscribes to instead of the raw frames."""

    ENGAGE = "engage"
    DISENGAGE = "disengage"
    POINT_MOVE = "point.move"
    SELECT_DOWN = "select.down"
    SELECT_UP = "select.up"
    GRAB_DOWN = "grab.down"
    GRAB_UP = "grab.up"
    SCROLL = "scroll"
    SWIPE_LEFT = "swipe.left"
    SWIPE_RIGHT = "swipe.right"
    SWIPE_UP = "swipe.up"
    SWIPE_DOWN = "swipe.down"


@dataclass
class IntentEvent:
    intent: Intent
    at: float                       # time.monotonic()
    frame: Optional[HandFrame] = None
    data: dict = None               # intent-specific payload

    def __post_init__(self):
        if self.data is None:
            self.data = {}


class Schmitt:
    """Two-threshold latch with a minimum dwell time.

    `on_at` and `off_at` may be ordered either way: if on_at > off_at the latch is
    "high when the signal is high" (e.g. pinch_strength); if on_at < off_at it is
    "high when the signal is low" (e.g. pinch_distance in mm, where *closer* means on).
    """

    def __init__(self, on_at: float, off_at: float, dwell: float = 0.0):
        self.on_at, self.off_at, self.dwell = on_at, off_at, dwell
        self.state = False
        self._pending_since: Optional[float] = None

    def _crossed_on(self, value: float) -> bool:
        return value >= self.on_at if self.on_at > self.off_at else value <= self.on_at

    def _crossed_off(self, value: float) -> bool:
        return value <= self.off_at if self.on_at > self.off_at else value >= self.off_at

    def update(self, value: float, now: float) -> Optional[bool]:
        """Returns True on rising edge, False on falling edge, None if unchanged."""
        target = self._crossed_on(value) if not self.state else not self._crossed_off(value)
        if target == self.state:
            self._pending_since = None
            return None
        if self._pending_since is None:
            self._pending_since = now
        if now - self._pending_since < self.dwell:
            return None
        self._pending_since = None
        self.state = target
        return target

    def force_off(self) -> bool:
        """Release without waiting for dwell. Returns True if it was held."""
        was = self.state
        self.state = False
        self._pending_since = None
        return was


@dataclass
class Config:
    hand: str = "Right"

    # Engagement volume. Below engage_y the hand is "resting" and controls nothing.
    engage_y: float = 90.0          # mm above the device to take control
    release_y: float = 55.0         # mm below which control is released
    engage_dwell: float = 0.12      # s of sustained height before engaging

    # Select = thumb/index pinch. Distance in mm is more stable than pinch_strength
    # on a v1 controller, which reports strength as a coarse, quantized curve.
    pinch_on_mm: float = 22.0
    pinch_off_mm: float = 38.0
    pinch_dwell: float = 0.04

    # Grab = whole-hand fist.
    grab_on: float = 0.85
    grab_off: float = 0.55
    grab_dwell: float = 0.06

    # Swipes: peak palm speed with a refractory period so one flick fires once.
    swipe_speed: float = 700.0      # mm/s
    swipe_refractory: float = 0.6   # s

    # Scroll: two fingers extended, vertical palm motion.
    scroll_gain: float = 0.35


class GestureEngine:
    """Consumes Snapshots, emits IntentEvents. Holds all the temporal state."""

    def __init__(self, config: Optional[Config] = None):
        self.cfg = config or Config()
        self.engaged = Schmitt(self.cfg.engage_y, self.cfg.release_y, self.cfg.engage_dwell)
        self.pinch = Schmitt(self.cfg.pinch_on_mm, self.cfg.pinch_off_mm, self.cfg.pinch_dwell)
        self.grab = Schmitt(self.cfg.grab_on, self.cfg.grab_off, self.cfg.grab_dwell)
        self._last_swipe = 0.0
        self._subscribers: list[Callable[[IntentEvent], None]] = []

    def subscribe(self, fn: Callable[[IntentEvent], None]) -> None:
        self._subscribers.append(fn)

    def _emit(self, intent: Intent, frame: Optional[HandFrame] = None, **data) -> None:
        event = IntentEvent(intent, time.monotonic(), frame, data)
        for fn in self._subscribers:
            fn(event)

    def _release_all(self, frame: Optional[HandFrame]) -> None:
        if self.pinch.force_off():
            self._emit(Intent.SELECT_UP, frame)
        if self.grab.force_off():
            self._emit(Intent.GRAB_UP, frame)

    def on_snapshot(self, snap: Snapshot) -> None:
        now = time.monotonic()
        frame = snap.get(self.cfg.hand)

        # Tracking lost: release everything held, then disengage. Order matters —
        # a held button must come up before the pointer stops being driven.
        if frame is None:
            self._release_all(None)
            if self.engaged.force_off():
                self._emit(Intent.DISENGAGE, None)
            return

        edge = self.engaged.update(frame.palm_stable.y, now)
        if edge is True:
            self._emit(Intent.ENGAGE, frame)
        elif edge is False:
            self._release_all(frame)
            self._emit(Intent.DISENGAGE, frame)

        if not self.engaged.state:
            return

        self._emit(Intent.POINT_MOVE, frame)

        # Pinch to select. Guarded on the index finger actually being involved:
        # a closed fist collapses pinch_distance too, and that should read as grab.
        if frame.grab_strength < self.cfg.grab_on:
            edge = self.pinch.update(frame.pinch_distance, now)
            if edge is True:
                self._emit(Intent.SELECT_DOWN, frame)
            elif edge is False:
                self._emit(Intent.SELECT_UP, frame)

        if not self.pinch.state:
            edge = self.grab.update(frame.grab_strength, now)
            if edge is True:
                self._emit(Intent.GRAB_DOWN, frame)
            elif edge is False:
                self._emit(Intent.GRAB_UP, frame)

        self._maybe_scroll(frame)
        self._maybe_swipe(frame, now)

    def _maybe_scroll(self, frame: HandFrame) -> None:
        # Index + middle extended, others curled: a deliberate, distinctive pose.
        if frame.extended[1] and frame.extended[2] and not any(
            (frame.extended[0], frame.extended[3], frame.extended[4])
        ):
            dy = frame.palm_velocity.z * self.cfg.scroll_gain
            if abs(dy) > 1.0:
                self._emit(Intent.SCROLL, frame, dy=dy)

    def _maybe_swipe(self, frame: HandFrame, now: float) -> None:
        if self.pinch.state or self.grab.state:
            return                      # a swipe during a drag is a drag, not a swipe
        if now - self._last_swipe < self.cfg.swipe_refractory:
            return
        v = frame.palm_velocity
        if abs(v.x) > self.cfg.swipe_speed and abs(v.x) > abs(v.z) * 1.6:
            self._last_swipe = now
            self._emit(Intent.SWIPE_RIGHT if v.x > 0 else Intent.SWIPE_LEFT, frame,
                       speed=v.x)
        elif abs(v.z) > self.cfg.swipe_speed and abs(v.z) > abs(v.x) * 1.6:
            self._last_swipe = now
            self._emit(Intent.SWIPE_DOWN if v.z > 0 else Intent.SWIPE_UP, frame,
                       speed=v.z)
