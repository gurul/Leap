"""Capture layer: Leap tracking frames -> a normalized, framework-free HandFrame.

Nothing above this module imports `leap`. That keeps the gesture and action layers
testable from recorded frames, and leaves room to swap in a different capture device
(MediaPipe, Vision.framework) without touching anything downstream.

Coordinate system, Desktop tracking mode, device flat on the desk:
    +X right, +Y up (away from the desk), +Z toward the user. Units: millimetres.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import leap


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    @classmethod
    def of(cls, v) -> "Vec3":
        return cls(v.x, v.y, v.z)


@dataclass(frozen=True)
class HandFrame:
    """One hand, one instant. Everything the layers above are allowed to know about."""

    frame_id: int
    timestamp: int              # microseconds, from the tracking service
    hand_id: int
    side: str                   # "Left" | "Right"
    confidence: float

    palm: Vec3                  # raw palm centre
    palm_stable: Vec3           # Leap's own jitter-reduced palm position — prefer this
    palm_velocity: Vec3         # mm/s
    palm_normal: Vec3           # points out of the palm
    palm_direction: Vec3        # points from palm toward the fingers

    pinch_strength: float       # 0..1
    pinch_distance: float       # mm between thumb and index tips
    grab_strength: float        # 0..1
    grab_angle: float           # radians

    extended: tuple[bool, ...]  # thumb, index, middle, ring, pinky
    fingertips: tuple[Vec3, ...]

    @property
    def extended_count(self) -> int:
        return sum(self.extended)

    @classmethod
    def of(cls, hand, frame_id: int, timestamp: int) -> "HandFrame":
        digits = hand.digits
        return cls(
            frame_id=frame_id,
            timestamp=timestamp,
            hand_id=hand.id,
            side=str(hand.type).split(".")[-1],
            confidence=hand.confidence,
            palm=Vec3.of(hand.palm.position),
            palm_stable=Vec3.of(hand.palm.stabilized_position),
            palm_velocity=Vec3.of(hand.palm.velocity),
            palm_normal=Vec3.of(hand.palm.normal),
            palm_direction=Vec3.of(hand.palm.direction),
            pinch_strength=hand.pinch_strength,
            pinch_distance=hand.pinch_distance,
            grab_strength=hand.grab_strength,
            grab_angle=hand.grab_angle,
            extended=tuple(bool(d.is_extended) for d in digits),
            fingertips=tuple(Vec3.of(d.distal.next_joint) for d in digits),
        )


@dataclass
class Snapshot:
    """The most recent frame per side. `None` means that hand is not being tracked."""

    left: Optional[HandFrame] = None
    right: Optional[HandFrame] = None

    def get(self, side: str) -> Optional[HandFrame]:
        return self.right if side == "Right" else self.left


class _Listener(leap.Listener):
    def __init__(self, sink: Callable[[Snapshot], None]):
        super().__init__()
        self._sink = sink

    def on_tracking_event(self, event):
        snap = Snapshot()
        for hand in event.hands:
            frame = HandFrame.of(hand, event.tracking_frame_id, event.timestamp)
            setattr(snap, frame.side.lower(), frame)
        self._sink(snap)


class LeapSource:
    """Owns the connection and pushes a Snapshot per tracking frame (~110 Hz).

    Callbacks run on the tracking thread, so keep them short. Anything expensive
    belongs behind a queue.
    """

    def __init__(self, mode=None):
        self._mode = mode or leap.TrackingMode.Desktop
        self._subscribers: list[Callable[[Snapshot], None]] = []
        self._connection = leap.Connection()
        self._connection.add_listener(_Listener(self._dispatch))
        self._lock = threading.Lock()
        self.latest = Snapshot()
        self.frames = 0

    def subscribe(self, fn: Callable[[Snapshot], None]) -> None:
        self._subscribers.append(fn)

    def _dispatch(self, snap: Snapshot) -> None:
        with self._lock:
            self.latest = snap
            self.frames += 1
        for fn in self._subscribers:
            fn(snap)

    def open(self):
        ctx = self._connection.open()
        ctx.__enter__()
        self._connection.set_tracking_mode(self._mode)
        return _Session(self._connection, ctx)


class _Session:
    def __init__(self, connection, ctx):
        self._connection = connection
        self._ctx = ctx

    def close(self):
        self._ctx.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def server_status(timeout_ms: int = 2000) -> dict:
    """Version + attached devices, without opening a tracking connection."""
    return leap.get_server_status(timeout_ms)
