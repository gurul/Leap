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
             LEFT-hand ILY is guaranteed to route here: for a lone ILY-shaped
             detection the camera layer trusts the handedness label over the
             identity/continuity assumption (camera.ily_shaped), so an
             intended Enter can never be adopted as the cursor hand and read
             as the pause toggle.

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
    DRAG = "drag"                   # data: active=bool — free-hand fist HOLD


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

    def update(self, active: bool, now: float, present: bool = True) -> bool:
        """Feed the per-frame pose test. Returns True exactly once: on the
        release that commits the command (or, with `fire_on_fill`, the frame
        the ring fills). `present` is whether the hand(s) this pose reads are
        tracked at all: a release with the hand still tracked commits, but a
        hand that VANISHES is a tracking loss — after the same grace (routine
        single-frame landmark dropouts still survive it), the hold resets
        WITHOUT firing. Never commit on a hand that is no longer there."""
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
        fired = (present and not self._fired
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


def other_hand(snap: Snapshot, hand: str) -> Optional[HandFrame]:
    """The hand that is not `hand`."""
    return snap.left if hand == "Right" else snap.right


def _either(snap: Snapshot, test) -> Optional[HandFrame]:
    """The first hand matching `test`, whichever side it is on. Minimal mode
    has no cursor hand, so a pose means the same thing on both."""
    for f in (snap.right, snap.left):
        if f is not None and test(f):
            return f
    return None


def is_fist(f: HandFrame) -> bool:
    """Every finger curled. The cleanest pose on this hardware — the corpus
    read 0 extended on 541/542 fist frames — which is why it can be trusted as
    a HOLD, where a misread costs a stuck mouse button rather than one bad
    click. On the free hand it is unambiguous: COPY needs a thumb-index pinch
    with a back finger extended, PASTE two, ENTER three."""
    return not any(f.extended)


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
    causes false NEGATIVES, and the preview shows the user what they framed.

    WHOLE-FRAME fingertips, never `index_tip`: this is the one place two hands
    are measured against each other, and `index_tip` is relative to the reach
    box mapping that hand alone. Once those boxes became dynamic (each centred
    on its own palm, each SIZED BY THAT HAND'S DISTANCE), this read each tip's
    offset from its own palm instead of where the hands were — so bringing a
    hand closer to the camera grew its box, shrank its normalized offset, and
    swapped the corners: the box inverted. The frame is the canvas, as it was
    before reach boxes existed.
    """
    pa = a.index_tip_frame if a.index_tip_frame is not None else a.index_tip
    pb = b.index_tip_frame if b.index_tip_frame is not None else b.index_tip
    (ax, ay), (bx, by) = _norm_point(pa), _norm_point(pb)
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


class CommandEngine:
    """Consumes Snapshots next to GestureEngine, emits CommandEvents.

    Also owns the global `enabled` gate the TOGGLE pose flips. While disabled,
    every pose except TOGGLE is ignored — the CLI routes an empty Snapshot to
    the gesture engine, which releases everything held (the dead-man property,
    reused as a pause switch).
    """

    # How long a button posture suppresses cursor-hand command arming, sized
    # to outlast the hand-opening transition (~0.1-0.3s at 30fps) without
    # noticeably delaying a deliberate pose formed from a fist.
    BUTTON_POSE_SHADOW_S = 0.4

    # How long the free hand must hold a fist before the button presses. Long
    # enough that a hand closing on its way to somewhere else does not drag,
    # short enough that a deliberate grab feels immediate.
    DRAG_ARM_S = 0.18

    def __init__(self, hand: str = "Right", pinch_on_mm: float = 50.0,
                 clock: Callable[[], float] = time.monotonic,
                 minimal: bool = False):
        # minimal (the default the CLI ships, 2026-08-20): three gestures —
        # mic, Enter, frame shot — and nothing else. The rest of the
        # vocabulary is not deleted, only unwired; `--legacy` restores it.
        # Everything cut here served CURSOR work, which a mouse does better:
        # copy/paste, Mission Control, the fist drag, and the ILY pause (the
        # menu bar is a more reliable off switch than a pose). Dropping the
        # pause also lets ILY mean Enter on EITHER hand, which retires the
        # hand-routing rules that were a bug class of their own.
        self.minimal = minimal
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
        self._dragging = False                  # free-hand fist holds the button
        self._drag_since: Optional[float] = None
        self._rect: Optional[tuple] = None      # last rect while framing
        self._now = 0.0
        # When the cursor hand was last in a BUTTON posture. Cursor-hand
        # command poses inside the shadow are transitions, not commands — see
        # on_snapshot. Tracked separately per posture because each suppresses
        # a different command: a click-pinch opens INTO the OK shape (mission),
        # a fist opens thumb-first INTO the thumbs-up (dictate).
        self._pinch_shadow_until = float("-inf")
        self._fist_shadow_until = float("-inf")
        self._subscribers: list[Callable[[CommandEvent], None]] = []

    def subscribe(self, fn: Callable[[CommandEvent], None]) -> None:
        self._subscribers.append(fn)

    def _emit(self, command: Command, **data) -> None:
        event = CommandEvent(command, self._now, data)
        for fn in self._subscribers:
            fn(event)

    @property
    def busy(self) -> bool:
        """A CURSOR-HAND command hold is PAST ITS ARM TIME: the cursor engine
        should stand down so the pose that forms the command cannot also steer
        the pointer.

        Gated on progress, not on `armed` — armed is true from the very first
        pattern-matching frame, and the CLI answers `busy` by feeding the
        cursor engine an EMPTY snapshot, which force-releases held buttons and
        the clutch. Measured in live use: transitional frames (a pinch opening
        into a palm) pattern-match command poses for a frame or two, and each
        one blanked the cursor mid-gesture. The arm dwell exists precisely to
        absorb those frames; busy must wait for it too.

        Free-hand holds (copy/paste/enter) are excluded: the cursor engine
        never reads that hand, so blanking it protects nothing — it only
        force-releases an in-progress drag on the cursor hand. Pane stays:
        two-handed, it includes the cursor hand.
        """
        return any(h.progress(self._now) > 0.0
                   for h in (self.pane, self.mission, self.toggle,
                             self.dictate))

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

        # The cursor hand's button postures leak into command poses on their
        # way OPEN: releasing a click-pinch extends middle/ring/pinky while
        # thumb and index are still close — the exact OK shape — and a fist
        # opens thumb-first through a perfect thumbs-up. Those frames are
        # transitions, not commands, and in live use they armed mission
        # control every time a pinch was released into an open palm. A button
        # posture casts a short shadow in which the matching cursor-hand hold
        # refuses to arm. A DELIBERATE OK never casts one (its back fingers
        # are extended), so it arms instantly from rest; a thumbs-up formed
        # without passing through a full fist arms instantly too.
        if mine is not None:
            if mine.extended_count == 0:
                self._fist_shadow_until = now + self.BUTTON_POSE_SHADOW_S
            if (mine.pinch_distance <= self.pinch_on_mm
                    and not (mine.extended[2] and mine.extended[3]
                             and mine.extended[4])):
                self._pinch_shadow_until = now + self.BUTTON_POSE_SHADOW_S
        pinch_shadow = now < max(self._pinch_shadow_until,
                                 self._fist_shadow_until)
        fist_shadow = now < self._fist_shadow_until

        # TOGGLE listens even while disabled — it is the way back in. While
        # enabled it respects the pinch shadow like the other cursor-hand
        # holds: a held click-pinch sheds ILY-shaped misread frames (middle +
        # ring stay curled, refreshing the shadow), and the pause arming
        # mid-drag blanks the cursor engine via `busy` and drops the drag.
        # Disabled needs no gate — there is nothing held to protect.
        # PAUSE. Legacy keeps ILY on the cursor hand. Minimal moves it to a
        # held FIST, on either hand: ILY had to become Enter (there is no
        # cursor hand left to distinguish the two), and the fist is the
        # cleanest pose on this hardware — 0 extended on 541/542 corpus frames
        # — which is what a toggle nobody is watching needs. It is also the
        # only pose minimal mode does not otherwise use.
        paused_pose = (mine is not None and is_ily_pose(mine)
                       and (not self.enabled or not pinch_shadow))
        if self.toggle.update(paused_pose, now, present=mine is not None):
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
            # Same reasoning, worse consequence: a mouse button held by a
            # fist nobody is watching outlives the pause.
            self._drag_since = None
            if self._dragging:
                self._dragging = False
                self._emit(Command.DRAG, active=False)
            return

        # NEW_PANE: both hands in the L-pose. The rect is captured live so the
        # release commits what the preview showed, not a post-release slump.
        both = snap.left is not None and snap.right is not None
        framing = (both and is_frame_pose(snap.left)
                   and is_frame_pose(snap.right))
        if framing:
            self._rect = frame_rect(snap.left, snap.right)
        if self.pane.update(framing, now, present=both):
            self._emit(Command.NEW_PANE, rect=self._rect)
        if not framing and not self.pane.armed:
            self._rect = None

        # MISSION: the OK pose, one hand, never while framing or in the
        # shadow of a click-pinch it could be opening out of.
        if not self.minimal:
            ok = (not framing and not pinch_shadow and mine is not None
                  and is_ok_pose(mine, self.pinch_on_mm))
            if self.mission.update(ok, now, present=mine is not None):
                self._emit(Command.MISSION_CONTROL)

        # DICTATE: thumbs-up, a TOGGLE. One short
        # thumbs-up opens the mic; between toggles the hand is entirely free
        # — rest it, point, leave the frame — nothing here closes the mic
        # except another thumbs-up, the ILY pause, or the driver's watchdog.
        # The driver holds the dictation hotkey while _dictating is true.
        # Minimal mode has no cursor hand, so the mic answers to EITHER hand
        # — one less thing to get right while holding a phone-sized idea.
        # `present` is "a hand is being tracked", NEVER "the pose is showing".
        # PoseHold treats absence as a tracking loss that CANCELS, and a
        # deliberate release as a fire — conflating them means the hold can
        # never complete.
        seen = snap.left is not None or snap.right is not None
        thumb = (not framing and not fist_shadow
                 and (_either(snap, is_thumbs_up) is not None if self.minimal
                      else (mine is not None and is_thumbs_up(mine))))
        if self.dictate.update(thumb, now,
                               present=seen if self.minimal
                               else mine is not None):
            self._dictating = not self._dictating
            self._emit(Command.DICTATE, active=self._dictating)

        # PASTE and ENTER. In minimal mode either hand fires them: with no
        # cursor there is no "free" hand to be free OF, and the whole
        # lone-hand adoption ruleset existed to protect a cursor that no
        # longer moves. COPY stays behind --legacy: Cmd+C is React Grab's
        # trigger, and firing it from a resting pinch would grab components
        # nobody asked for.
        other = snap.left if self.hand == "Right" else snap.right
        if not self.minimal:
            copying = (not framing and other is not None
                       and is_pinch_hold(other, self.pinch_on_mm))
            if self.copy.update(copying, now, present=other is not None):
                self._emit(Command.COPY)
        pasting = (not framing
                   and (_either(snap, is_v_pose) is not None if self.minimal
                        else (other is not None and is_v_pose(other))))
        if self.paste.update(pasting, now,
                             present=seen if self.minimal
                             else other is not None):
            self._emit(Command.PASTE)
        # ILY is the one pose whose MEANING depends on which hand makes it —
        # cursor hand pauses, free hand submits — so it keeps the hand routing
        # in both modes. Everything else in minimal answers to either hand;
        # this one cannot, and splitting it is what pays for having a pause at
        # all without spending a second pose on it.
        entering = (not framing and other is not None and is_ily_pose(other))
        if self.enter.update(entering, now, present=other is not None):
            self._emit(Command.ENTER)

        # DRAG: a free-hand FIST holds the mouse button while the cursor hand
        # keeps pointing — one hand holds, the other moves, which is how a
        # mouse has always worked. This is the ONLY drag: the pinch is pinned
        # to a single pixel (Mapping.pinch_drag), because a pinch that dragged
        # selected text every time it drifted.
        #
        # A HOLD, not a dwell-toggle: rotating a figure wants the button down
        # for exactly as long as the fist is closed. Arming costs
        # DRAG_ARM_S so a hand passing through a fist cannot press; RELEASE IS
        # NEVER GATED — an opened hand, a vanished hand and a disabled engine
        # all drop the button on the same frame, because a stuck mouse button
        # is the worst failure this project has.
        fisted = (not self.minimal and not framing and other is not None
                  and is_fist(other))
        if not fisted:
            self._drag_since = None
            if self._dragging:
                self._dragging = False
                self._emit(Command.DRAG, active=False)
        else:
            if self._drag_since is None:
                self._drag_since = now
            if not self._dragging and now - self._drag_since >= self.DRAG_ARM_S:
                self._dragging = True
                self._emit(Command.DRAG, active=True)
