"""Discrete-command layer: pose-holds -> Commands, alongside the cursor vocabulary.

Grounded in what shipping mid-air UIs converged on (Quest system gesture,
TouchFree Hover & Hold, ISS 2022 dwell study — 800ms dwell measured 0% selection
errors): STATIC poses held for a dwell, with visible progress, TRIGGERED ON
RELEASE so there is always an abort window. Never a translational gesture —
swipes were cut from this project because the motion carries the hand out of the
camera's view, and no product vocabulary uses them for commands either.

Commands, chosen for zero collision with the cursor vocabulary:

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
  DICTATE    thumbs-up on the CURSOR hand, a TOGGLE: one short thumbs-up
             opens the mic (active=True as the ring fills), another closes
             it. Between toggles the hand is free — rest it, point, leave
             the frame. Started as a shaka hold (cramped), then a thumbs-up
             hold (unsustainable, drifted out of view); the toggle is what
             the ergonomics literature prescribes — short deliberate poses,
             never sustained static holds. Safety nets: the ILY pause closes
             the mic, and the driver force-releases after its watchdog.
  COPY /     poses on the FREE hand — the one the cursor doesn't follow, an
  PASTE /    otherwise unused namespace, so nothing here can collide with
  ENTER      pointing (on the cursor hand, pinch IS the mouse button).
             Pinch-and-hold = copy ("grab it"); V sign = paste (the literal
             letter of Cmd+V); ILY = Enter. The V sign is banned on the
             cursor hand — index+middle extended is nearly the pointing
             posture — but the free hand never points. Enter gets ILY, not
             thumbs-up, deliberately: a resting hand with the thumb out can
             hold thumbs-up until any shift releases-and-fires it, and Enter
             is too consequential for that; ILY never occurs incidentally.

The split is by hand: the CURSOR hand owns pointing and its own commands
(mission control, pause, dictate); the FREE hand is a second command palette
(clipboard, enter). Together: frame shot -> clipboard, free-hand V pastes it;
thumbs-up dictates, free-hand ILY submits.
"""

from __future__ import annotations

import time
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
    DICTATE = "dictate"             # data: active=bool — push-to-talk edges
    COPY = "copy"                   # Cmd+C
    PASTE = "paste"                 # Cmd+V
    ENTER = "enter"                 # Return — submit what you dictated


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

    `fire_on_fill` inverts the commit: fire the moment the ring fills, while
    the pose is still held. That trades the abort window for instant feedback —
    right for the pause toggle, where waiting for the release means the chime
    arrives only after you leave the pose and you hold it wondering.
    """

    def __init__(self, arm: float = 0.15, dwell: float = 0.65,
                 grace: float = 0.12, fire_on_fill: bool = False):
        self.arm, self.dwell, self.grace = arm, dwell, grace
        self.fire_on_fill = fire_on_fill
        self._active_since: Optional[float] = None
        self._inactive_since: Optional[float] = None
        self._fired = False

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
        release that commits the command (or, with `fire_on_fill`, the frame
        the ring fills)."""
        if active:
            self._inactive_since = None
            if self._active_since is None:
                self._active_since = now
                self._fired = False
            if (self.fire_on_fill and not self._fired
                    and self.progress(now) >= 1.0):
                self._fired = True
                return True
            return False
        if self._active_since is None:
            return False
        if self._inactive_since is None:
            self._inactive_since = now
        if now - self._inactive_since < self.grace:
            return False                # single-frame flicker: still held
        fired = (not self._fired
                 and self.progress(self._inactive_since) >= 1.0)
        self._active_since = None
        self._inactive_since = None
        self._fired = False
        return fired

    def cancel(self) -> None:
        self._active_since = None
        self._inactive_since = None
        self._fired = False


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


def is_pinch_hold(f: HandFrame, pinch_on_mm: float) -> bool:
    """A deliberate pinch: thumb-index closed with at least one back finger
    extended. The extension requirement is what separates it from a RELAXED
    hand — measured on this corpus, a deliberate pinch reads as three
    extended, while a slack hand curls everything with the thumb resting
    near the index, which would satisfy a bare distance test."""
    return f.pinch_distance <= pinch_on_mm and any(f.extended[2:])


def is_thumbs_up(f: HandFrame) -> bool:
    """Thumb out, all four fingers curled. Replaced the shaka for dictation:
    same reliability class (both in MediaPipe's canned gesture set), but a
    closed fist with the thumb up is restful enough to hold for a whole
    dictation, where the shaka cramped. Adjacent to the drag fist — safe
    because the corpus measured fist at 100% zero-extended."""
    return f.extended == (True, False, False, False, False)


def is_v_pose(f: HandFrame) -> bool:
    """Index + middle out, ring + pinky curled; the thumb is IGNORED — a
    natural peace sign often reads thumb-out, and requiring it curled made
    the pose flicker. Free hand only: on the cursor hand this is nearly the
    natural pointing posture (the reason the old two-finger scroll pose was
    cut)."""
    return (f.extended[1] and f.extended[2]
            and not f.extended[3] and not f.extended[4])


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

    def __init__(self, hand: str = "Right", pinch_on_mm: float = 50.0,
                 clock: Callable[[], float] = time.monotonic):
        self.hand = hand
        self.pinch_on_mm = pinch_on_mm
        self._clock = clock
        self._last_wall: Optional[float] = None
        self.enabled = True
        self.pane = PoseHold(dwell=0.65)        # ~0.8s total with arm
        self.mission = PoseHold(dwell=0.45)     # ~0.6s total
        # ~1.65s total. Was ~1s, and a live headless session paused itself: a
        # relaxed hand with middle+ring drooping reads as ILY, and one second
        # of it is easy to produce by accident. The pause must be deliberate.
        # fire_on_fill: the pause chime sounds the moment the hold completes,
        # not after you release — holding past a silent full ring feels broken.
        self.toggle = PoseHold(dwell=1.5, fire_on_fill=True)
        # fire_on_fill so the mic flips the moment the ring fills. A TOGGLE,
        # not a hold: the hold form failed in live use (unsustainable to hold,
        # easy to drift out of the camera's view) and the ergonomics
        # literature agrees — sustained static holds are the fatigue case,
        # short deliberate poses are the comfort case.
        self.dictate = PoseHold(dwell=0.45, fire_on_fill=True)
        self.copy = PoseHold(dwell=0.45)        # free hand, fire on release
        self.paste = PoseHold(dwell=0.45)
        # fire_on_fill + short dwell: Enter felt slow on release-commit, and
        # the abort window buys nothing here — ILY never occurs incidentally
        # (the same argument that put fire_on_fill on the pause toggle).
        self.enter = PoseHold(dwell=0.3, fire_on_fill=True)
        self._dictating = False
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
        return (self.pane.armed or self.mission.armed or self.toggle.armed
                or self.dictate.armed or self.copy.armed or self.paste.armed
                or self.enter.armed)

    @property
    def overlay(self) -> dict:
        """What the preview should draw: the busiest active hold wins."""
        holds = (("frame the pane", self.pane, self._rect),
                 ("mission control", self.mission, None),
                 ("pause/resume" , self.toggle, None),
                 ("dictate", self.dictate, None),
                 ("copy", self.copy, None),
                 ("paste", self.paste, None),
                 ("enter", self.enter, None))
        label, best, rect = max(holds, key=lambda h: h[1].progress(self._now))
        return {"label": label if best.armed else "",
                "progress": best.progress(self._now),
                "rect": rect if best is self.pane else None}

    def on_snapshot(self, snap: Snapshot) -> None:
        frames = [f for f in (snap.left, snap.right) if f is not None]
        # Sensor time drives everything while hands are visible; empty
        # snapshots carry no timestamp, so the wall clock bridges the gap.
        # Without the bridge, a hand vanishing mid-hold freezes the clock and
        # the hold never disarms — for dictation that means the mic (and a
        # system-wide Option) stays held until the hand happens to return.
        wall = self._clock()
        if frames:
            self._now = max(f.timestamp for f in frames) / 1e6
        elif self._last_wall is not None:
            self._now += wall - self._last_wall
        self._last_wall = wall
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
            self.copy.cancel()
            self.paste.cancel()
            self.enter.cancel()
            self._rect = None
            # Pausing mid-dictation must close the mic — a held hotkey with
            # nothing watching the pose would stick down forever.
            self.dictate.cancel()
            if self._dictating:
                self._dictating = False
                self._emit(Command.DICTATE, active=False)
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

        # DICTATE: thumbs-up on the cursor hand, a TOGGLE. One short
        # thumbs-up opens the mic; between toggles the hand is entirely free
        # — rest it, point, leave the frame — nothing here closes the mic
        # except another thumbs-up, the ILY pause, or the driver's watchdog.
        # The driver holds the dictation hotkey while _dictating is true.
        thumb = not framing and mine is not None and is_thumbs_up(mine)
        if self.dictate.update(thumb, now):
            self._dictating = not self._dictating
            self._emit(Command.DICTATE, active=self._dictating)

        # COPY / PASTE: poses on the free hand — the one the cursor ignores.
        other = snap.left if self.hand == "Right" else snap.right
        copying = (not framing and other is not None
                   and is_pinch_hold(other, self.pinch_on_mm))
        if self.copy.update(copying, now):
            self._emit(Command.COPY)
        pasting = (not framing and other is not None and is_v_pose(other))
        if self.paste.update(pasting, now):
            self._emit(Command.PASTE)
        entering = (not framing and other is not None and is_ily_pose(other))
        if self.enter.update(entering, now):
            self._emit(Command.ENTER)
