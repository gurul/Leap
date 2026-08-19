"""Capture layer: Leap tracking frames -> a normalized, framework-free HandFrame.

Nothing above this module imports `leap`. That keeps the gesture and action layers
testable from recorded frames, and leaves room to swap in a different capture device
(MediaPipe, Vision.framework) without touching anything downstream.

Coordinate system, Desktop tracking mode, device flat on the desk:
    +X right, +Y up (away from the desk), +Z toward the user. Units: millimetres.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

# Optional: this module defines the framework-free HandFrame/Snapshot types that
# every capture source shares, so it must import on machines with no Leap SDK at
# all (e.g. a camera-only setup driving leapinput.camera.CameraSource).
try:
    import leap
except ImportError:          # no SDK — LeapSource/server_status raise if used
    leap = None


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

    palm: Vec3                  # palm centre
    palm_velocity: Vec3         # mm/s
    palm_normal: Vec3           # points out of the palm; palm-mode clutch only

    pinch_strength: float       # 0..1
    pinch_distance: float       # mm between thumb and index tips
    grab_strength: float        # 0..1; palm-mode grab and pose validation

    extended: tuple[bool, ...]  # thumb, index, middle, ring, pinky
    index_tip: Vec3 = None      # the default tracked point
    knuckles: tuple[Vec3, ...] = ()   # index..pinky MCP joints; see `center`

    # Distance compensation for monocular sources: how much to scale MOTION
    # (relative deltas, speeds) so one physical centimetre of hand travel means
    # the same thing at any distance from the camera. The camera derives it
    # from apparent knuckle span (image size ~ 1/distance — the free depth
    # proxy; the signal a Depth Anything integration would buy at model cost).
    # 1.0 = at the calibrated reference distance, and always 1.0 for sources
    # with real depth (the Leap). Positions are NOT scaled — the reach box is
    # a frame region and absolute mapping must stay position-faithful.
    motion_scale: float = 1.0

    @property
    def extended_count(self) -> int:
        return sum(self.extended)

    def track_point(self, kind: str) -> Vec3:
        """The point the cursor follows.

        "index"    — index fingertip. What people expect from pointing, and the
                     most precise: the fingertip travels further than the palm for
                     the same wrist motion, so small aims are easier to express.
                     Costs noise (it is the end of the longest kinematic chain)
                     and it MOVES WHEN YOU PINCH, since pinching curls the index
                     toward the thumb.
        "knuckles" — mean of the index..pinky MCP joints. Rigid through any finger
                     pose, so a pinch cannot drag the cursor. Less expressive.
        "palm"     — raw palm centroid. Drifts as fingers curl; kept for comparison.
        """
        if kind == "index" and self.index_tip is not None:
            return self.index_tip
        if kind == "palm":
            return self.position
        return self.center

    @property
    def eccentricity(self) -> float:
        """Degrees off the device's vertical axis — how far into the edge you are.

        The device looks straight up, so this is the angle that predicts tracking
        quality. LMC1 palm error is ~8mm in the central volume but RMS >20mm at
        the extreme left, right or bottom, and hands near the edge of the field of
        view are the ones that drop out. Measured on this desk, normal use stays
        under 45 deg for 95% of frames.
        """
        p = self.position
        horizontal = math.hypot(p.x, p.z)
        if p.y <= 0.0:
            return 90.0
        return math.degrees(math.atan2(horizontal, p.y))

    @property
    def center(self) -> Vec3:
        """Rigid palm centre — the knuckle line, not `palm.position`.

        `palm.position` is the centroid of a deforming surface, so it SHIFTS when
        the fingers curl. Pinching therefore drags the tracked point a few mm and
        the cursor creeps at the exact moment you are trying to hold still on a
        target. The four finger MCP joints move as one rigid body with the hand, so
        their mean stays put through any finger pose.

        Falls back to `position` when knuckles are absent (older recordings).
        """
        if not self.knuckles:
            return self.position
        n = len(self.knuckles)
        return Vec3(sum(k.x for k in self.knuckles) / n,
                    sum(k.y for k in self.knuckles) / n,
                    sum(k.z for k in self.knuckles) / n)

    @property
    def position(self) -> Vec3:
        return self.palm

    @classmethod
    def of(cls, hand, frame_id: int, timestamp: int) -> "HandFrame":
        digits = hand.digits
        return cls(
            frame_id=frame_id,
            timestamp=timestamp,
            hand_id=hand.id,
            side=str(hand.type).split(".")[-1],
            palm=Vec3.of(hand.palm.position),
            palm_velocity=Vec3.of(hand.palm.velocity),
            palm_normal=Vec3.of(hand.palm.normal),
            pinch_strength=hand.pinch_strength,
            pinch_distance=hand.pinch_distance,
            grab_strength=hand.grab_strength,
            extended=tuple(bool(d.is_extended) for d in digits),
            # Index fingertip only. It is the sole tracked point in normal use, and
            # building the other four cost four Vec3 allocations per frame for
            # nothing. `knuckles` mode reads the metacarpals lazily instead.
            index_tip=Vec3.of(digits[1].distal.next_joint),
            knuckles=tuple(Vec3.of(d.metacarpal.next_joint) for d in digits[1:]),
        )


@dataclass
class Snapshot:
    """The most recent frame per side. `None` means that hand is not being tracked."""

    left: Optional[HandFrame] = None
    right: Optional[HandFrame] = None

    def get(self, side: str) -> Optional[HandFrame]:
        return self.right if side == "Right" else self.left


def _make_listener(sink: Callable[[Snapshot], None]):
    """Build the leap.Listener subclass at call time, not import time.

    Subclassing leap.Listener in the module body would make the whole module —
    and the shared HandFrame types — unimportable without the SDK.
    """

    class _Listener(leap.Listener):
        def on_tracking_event(self, event):
            snap = Snapshot()
            for hand in event.hands:
                frame = HandFrame.of(hand, event.tracking_frame_id, event.timestamp)
                setattr(snap, frame.side.lower(), frame)
            sink(snap)

    return _Listener()


class LeapSource:
    """Owns the connection and pushes a Snapshot per tracking frame (~110 Hz).

    Callbacks run on the tracking thread, so keep them short. Anything expensive
    belongs behind a queue.
    """

    def __init__(self, mode=None):
        if leap is None:
            raise RuntimeError(
                "the `leap` bindings are not installed — run scripts/setup.sh, "
                "or use `--source camera` which needs no Leap hardware")
        self._mode = mode or leap.TrackingMode.Desktop
        self._subscribers: list[Callable[[Snapshot], None]] = []
        self._connection = leap.Connection()
        self._connection.add_listener(_make_listener(self._dispatch))
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
    if leap is None:
        raise RuntimeError(
            "the `leap` bindings are not installed — run scripts/setup.sh, "
            "or use `--source camera` which needs no Leap hardware")
    return leap.get_server_status(timeout_ms)
