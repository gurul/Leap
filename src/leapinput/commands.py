"""Discrete-command layer: pose-holds -> Commands, alongside the cursor vocabulary.

Grounded in what shipping mid-air UIs converged on (Quest system gesture,
TouchFree Hover & Hold, ISS 2022 dwell study — 800ms dwell measured 0% selection
errors): STATIC poses held for a dwell, with visible progress, TRIGGERED ON
RELEASE so there is always an abort window. Never a translational gesture —
swipes were cut from this project because the motion carries the hand out of the
camera's view, and no product vocabulary uses them for commands either.

Three commands, chosen for zero collision with the cursor vocabulary:

  NEW_PANE   both hands framing a rectangle (thumbs + index fingers, the
             photographer's gesture). Two-handed while the cursor vocabulary is
             one-handed, so it cannot misfire while pointing. The framed region
             parameterises the action: spawn a window there.
  MISSION    an OK-style pinch with the OTHER three fingers extended. The
             extended fingers park the cursor first (4+ = lifted), so the pinch
             cannot click anything.
  TOGGLE     the ILoveYou pose (thumb + index + pinky) held for a full second:
             pause/resume all gesture control without leaving the camera's view.
             The pose essentially never occurs incidentally, which is exactly
             why it gets the highest-stakes job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .capture import HandFrame, Snapshot

# Normalized-rect conversion shares the camera's virtual plane constants.
from .camera import PLANE_X_MM, PLANE_Y_BASE, PLANE_Y_MM


class Command(str, Enum):
    NEW_PANE = "pane.new"           # data: rect=(x0, y0, x1, y1), normalized 0..1
    MISSION_CONTROL = "mission_control"
    TOGGLE = "toggle"               # data: enabled=bool (state AFTER the toggle)


@dataclass
class CommandEvent:
    command: Command
    at: float
    data: dict = field(default_factory=dict)


class PoseHold:
    """Arm -> dwell -> fire-on-release, with a flicker grace.

    A pose must persist `arm` seconds before the progress ring starts filling
    (single-frame classifier flickers never start a ring), fill for `dwell`
    seconds, and FIRE ONLY WHEN RELEASED with the ring full — the Quest system
    gesture's shape, which leaves an abort window (hold past full and just...
    keep holding, then break the pose slowly toward another pose; or drop the
    hand, which cancels everything via `cancel`). A pose that flickers OFF for
    under `grace` seconds is still considered held, because landmark noise at
    30fps drops single frames routinely.
    """

    def __init__(self, arm: float = 0.15, dwell: float = 0.65,
                 grace: float = 0.12):
        self.arm, self.dwell, self.grace = arm, dwell, grace
        self._active_since: Optional[float] = None
        self._inactive_since: Optional[float] = None

    @property
    def armed(self) -> bool:
        return self._active_since is not None

    def progress(self, now: float) -> float:
        """0..1 ring fill. 0 until armed, 1 = releasing now fires."""
        if self._active_since is None:
            return 0.0
        t = now - self._active_since - self.arm
        if t <= 0.0:
            return 0.0
        return min(1.0, t / self.dwell)

    def update(self, active: bool, now: float) -> bool:
        """Feed the per-frame pose test. Returns True exactly once: on the
        release that commits the command."""
        if active:
            self._inactive_since = None
            if self._active_since is None:
                self._active_since = now
            return False
        if self._active_since is None:
            return False
        if self._inactive_since is None:
            self._inactive_since = now
        if now - self._inactive_since < self.grace:
            return False                # single-frame flicker: still held
        fired = self.progress(self._inactive_since) >= 1.0
        self._active_since = None
        self._inactive_since = None
        return fired

    def cancel(self) -> None:
        self._active_since = None
        self._inactive_since = None


# --- pose tests, on the extended-finger flags we already compute --------------

def is_frame_pose(f: HandFrame) -> bool:
    """Thumb + index extended, the rest curled: one L of the photographer's
    rectangle."""
    return f.extended == (True, True, False, False, False)


def is_ok_pose(f: HandFrame, pinch_on_mm: float) -> bool:
    """Pinch with middle+ring+pinky extended. The extended fingers are what
    make it deliberate — a click-pinch happens while pointing, with them curled."""
    return (f.extended[2] and f.extended[3] and f.extended[4]
            and f.pinch_distance <= pinch_on_mm)


def is_ily_pose(f: HandFrame) -> bool:
    """Thumb + index + pinky out, middle + ring curled."""
    return f.extended == (True, True, False, False, True)


def _norm_point(p) -> tuple[float, float]:
    """Virtual-plane mm -> normalized screen-like coords (y down from top)."""
    xn = p.x / PLANE_X_MM + 0.5
    yn = 1.0 - (p.y - PLANE_Y_BASE) / PLANE_Y_MM
    return (min(1.0, max(0.0, xn)), min(1.0, max(0.0, yn)))


def frame_rect(a: HandFrame, b: HandFrame) -> tuple[float, float, float, float]:
    """The framed region: the two index fingertips are the diagonal corners.
    Kept deliberately loose (no rectangle-quality test) — corner self-occlusion
    causes false NEGATIVES, and the preview shows the user what they framed."""
    (ax, ay), (bx, by) = _norm_point(a.index_tip), _norm_point(b.index_tip)
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


class CommandEngine:
    """Consumes Snapshots next to GestureEngine, emits CommandEvents.

    Also owns the global `enabled` gate the TOGGLE pose flips. While disabled,
    every pose except TOGGLE is ignored — the CLI routes an empty Snapshot to
    the gesture engine, which releases everything held (the dead-man property,
    reused as a pause switch).
    """

    def __init__(self, hand: str = "Right", pinch_on_mm: float = 50.0):
        self.hand = hand
        self.pinch_on_mm = pinch_on_mm
        self.enabled = True
        self.pane = PoseHold(dwell=0.65)        # ~0.8s total with arm
        self.mission = PoseHold(dwell=0.45)     # ~0.6s total
        self.toggle = PoseHold(dwell=0.85)      # ~1.0s total: highest stakes
        self._rect: Optional[tuple] = None      # last rect while framing
        self._now = 0.0
        self._subscribers: list[Callable[[CommandEvent], None]] = []

    def subscribe(self, fn: Callable[[CommandEvent], None]) -> None:
        self._subscribers.append(fn)

    def _emit(self, command: Command, **data) -> None:
        event = CommandEvent(command, self._now, data)
        for fn in self._subscribers:
            fn(event)

    @property
    def busy(self) -> bool:
        """A command hold is armed: the cursor engine should stand down so the
        pose that forms the command cannot also steer the pointer."""
        return self.pane.armed or self.mission.armed or self.toggle.armed

    @property
    def overlay(self) -> dict:
        """What the preview should draw: the busiest active hold wins."""
        holds = (("frame the pane", self.pane, self._rect),
                 ("mission control", self.mission, None),
                 ("pause/resume" , self.toggle, None))
        label, best, rect = max(holds, key=lambda h: h[1].progress(self._now))
        return {"label": label if best.armed else "",
                "progress": best.progress(self._now),
                "rect": rect if best is self.pane else None}

    def on_snapshot(self, snap: Snapshot) -> None:
        frames = [f for f in (snap.left, snap.right) if f is not None]
        if frames:
            self._now = max(f.timestamp for f in frames) / 1e6
        now = self._now
        mine = snap.get(self.hand)

        # TOGGLE listens even while disabled — it is the way back in.
        ily = mine is not None and is_ily_pose(mine)
        if self.toggle.update(ily, now):
            self.enabled = not self.enabled
            self._emit(Command.TOGGLE, enabled=self.enabled)

        if not self.enabled:
            self.pane.cancel()
            self.mission.cancel()
            self._rect = None
            return

        # NEW_PANE: both hands in the L-pose. The rect is captured live so the
        # release commits what the preview showed, not a post-release slump.
        framing = (snap.left is not None and snap.right is not None
                   and is_frame_pose(snap.left) and is_frame_pose(snap.right))
        if framing:
            self._rect = frame_rect(snap.left, snap.right)
        if self.pane.update(framing, now):
            self._emit(Command.NEW_PANE, rect=self._rect)
        if not framing and not self.pane.armed:
            self._rect = None

        # MISSION: the OK pose, one hand, never while framing.
        ok = (not framing and mine is not None
              and is_ok_pose(mine, self.pinch_on_mm))
        if self.mission.update(ok, now):
            self._emit(Command.MISSION_CONTROL)
