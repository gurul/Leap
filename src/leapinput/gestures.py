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

import math
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .capture import HandFrame, Snapshot


# Where the palm must face for the clutch to engage, per interaction plane.
#   xz — hand hovering FLAT over the device: palm faces down.
#   xy — hand held UPRIGHT, drawing on a vertical plane: palm faces away from you.
# The clutch reference has to follow the plane. A palm-down clutch is unreachable
# when the hand is deliberately held vertical — the posture that defines xy mode is
# exactly the posture that releases an xz clutch.
CLUTCH_REFERENCE = {
    "xz": (0.0, -1.0, 0.0),     # straight down
    "xy": (0.0, 0.0, -1.0),     # away from the user, toward the screen
}


def palm_angle_degrees(frame: HandFrame, reference: tuple) -> float:
    """Angle between the palm normal and `reference`, in degrees.

    0 deg = palm squarely facing the reference direction; 90 deg = edge-on.
    """
    n = frame.palm_normal
    mag = math.sqrt(n.x * n.x + n.y * n.y + n.z * n.z)
    if mag == 0.0:
        return 180.0                    # unusable normal: treat as clutch-off
    dot = (n.x * reference[0] + n.y * reference[1] + n.z * reference[2]) / mag
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def palm_down_degrees(frame: HandFrame) -> float:
    """Angle from straight down. Retained for the xz plane and its tests."""
    return palm_angle_degrees(frame, CLUTCH_REFERENCE["xz"])


class Intent(str, Enum):
    """What the user meant. Deliberately device- and action-agnostic — this is the
    seam a CUA driver subscribes to instead of the raw frames."""

    ENGAGE = "engage"
    DISENGAGE = "disengage"
    CLUTCH_DOWN = "clutch.down"     # pointer starts moving, anchored here
    CLUTCH_UP = "clutch.up"         # pointer parks; hand free to reposition
    POINT_MOVE = "point.move"
    SELECT_DOWN = "select.down"
    SELECT_UP = "select.up"
    GRAB_DOWN = "grab.down"
    GRAB_UP = "grab.up"
    SCROLL = "scroll"

    # Swipes are CUT. Measured 2026-08-12: velocity separation is real (roam peaks
    # at 419 mm/s, a swipe at 803) but irrelevant, because the swipe motion carries
    # the hand out of the tracking volume and trips the dead-man's switch. A live
    # 60s session fired swipe.right and swipe.down unintentionally, and swipe.down
    # landed immediately before a disengage — the gesture destroying the tracking it
    # depends on. Kept as names only so recorded sessions still decode.
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


class Debounce:
    """Hysteresis for a DISCRETE signal, where Schmitt thresholds do not apply.

    Finger count is an integer, so there is no band to sit inside — the guard has
    to be time: a new value must persist for `hold` before it is believed. Without
    it, one dropped frame of finger tracking flips the whole interaction state.
    """

    def __init__(self, initial, hold: float = 0.08):
        self.value = initial
        self.hold = hold
        self._candidate = initial
        self._since: Optional[float] = None

    def update(self, value, now: float):
        """Returns the new value on a confirmed change, else None."""
        if value == self.value:
            self._candidate, self._since = value, None
            return None
        if value != self._candidate:
            self._candidate, self._since = value, now
            return None
        if self._since is None or now - self._since < self.hold:
            return None
        self.value, self._since = value, None
        return value


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
    """Thresholds measured from 3639 frames of this user's hand on this v1
    controller (docs/context/session.jsonl, 2026-08-12). Every value below cites
    the separation it was derived from — do not "tidy" them without re-measuring.
    """

    hand: str = "Right"

    # Which plane the hand works in. "xz" = flat over the device (top-down);
    # "xy" = upright, as if drawing on a vertical screen.
    #
    # MEASURED, 2026-08-12, 590 tracked frames of this user actually trying to
    # drive the cursor (leapinput.doctor). xz wins on every axis that matters:
    #
    #   clutch reachable   xz 100% of frames (palm 18.9 deg off down)
    #                      xy   0% of frames (palm 85.4 deg off forward)
    #   cursor travel      xz  1313px horizontal, 816px vertical
    #                      xy  1318px horizontal, 410px vertical
    #
    # The misconception this settles: "up/down" here means moving the hand FORWARD
    # AND BACK across the desk (z span 178mm), not raising and lowering it (y span
    # 76mm). Over a device lying flat that is the natural gesture, and it is a
    # horizontal plane. Flipping invert_* could never have fixed it, because the
    # vertical axis was being read from the wrong hand axis entirely.
    plane: str = "xz"

    # Height is a SANITY FLOOR, not the engagement gate.
    #
    # Measured: hand resting on the desk produces NO TRACKING AT ALL (the rest step
    # captured 12 stray transition frames out of 3639). Resting height 145-183mm and
    # working height 137-242mm overlap completely, so height cannot separate the two.
    # The real gate is hand presence, which the device gives for free and which no
    # threshold can get wrong. This floor only rejects implausibly low readings —
    # session y-minimum was 124mm, p2 was 131mm.
    # In xy mode HEIGHT IS THE CONTROL AXIS, so a meaningful floor would fight the
    # gesture — lowering the hand to move the cursor down would disengage. The
    # floor drops to a bare sanity check there; hand presence remains the real gate.
    engage_y: float = 115.0
    release_y: float = 100.0
    engage_dwell: float = 0.08
    engage_y_xy: float = 40.0
    release_y_xy: float = 25.0

    # Select = thumb/index pinch, measured in mm rather than pinch_strength: on a v1
    # controller the strength curve is coarse, but the distance separation is huge —
    # pinched 17-18mm vs open 83-87mm, a 65mm gap. These sit well inside it.
    # SENSITIVE pinch — fires on intent, not on a perfect gesture.
    #
    # Measured separation is wide: pinched 17-18mm vs open 83-87mm, a 65mm gap.
    # Firing at 50mm sits in the middle of that gap, so a light, partial pinch
    # registers while an open hand still cannot reach it. pinch_strength only has
    # to clear 0.5, enough to reject a hand that is merely closing rather than
    # pinching, without demanding the model be confident at the moment thumb and
    # index occlude — which is exactly when it is least confident.
    pinch_on_mm: float = 50.0
    pinch_off_mm: float = 68.0
    pinch_dwell: float = 0.03
    pinch_min_strength: float = 0.50

    # Cursor stabilisation while a click is forming.
    #
    # Measured failure mode for HAND pointing is misses, not slips: 95.7% spatial
    # targeting failures vs 4.3% unintended activation (arXiv 2603.15991). Midas
    # touch is a gaze problem. So the payoff is in landing the click, not in more
    # gating — and we know exactly why ours drift: pinching curls the index, which
    # is the tracked point.
    #
    # Between these distances the click is "forming", and the cursor is
    # progressively frozen so the last millimetres of the pinch cannot drag it off
    # target. Mirrors TouchFree's growing click deadzone.
    # settle_full == pinch_on: the freeze completes exactly at the Schmitt's
    # firing threshold, so mouse-down posts on a fully-stopped cursor. The old
    # 38.0 sat 12mm past the trigger — the click fired at ~71% gain and the
    # freeze arrived after the event it was meant to protect.
    settle_start_mm: float = 55.0   # begin stabilising
    settle_full_mm: float = 50.0    # fully frozen AT the click threshold

    # Grab = fist. The cleanest signal on this hardware: grab_strength was >0.5 on
    # 100% of fist frames and 0% of every other pose. Effectively binary.
    grab_on: float = 0.75
    grab_off: float = 0.35
    grab_dwell: float = 0.06

    # The vocabulary is a monotonic ladder on EXTENDED FINGER COUNT.
    #
    #   0 fingers (fist)  -> grab: button down, cursor still moves (drag)
    #   1 finger  (point) -> cursor moves, no button
    #   2+ fingers        -> mouse LIFTED: cursor parked, reposition freely
    #
    # Why this and not pinch: pinch is model-INFERRED precisely where the thumb and
    # index occlude each other, which is the moment it must be exact. Measured on
    # this corpus, a deliberate pinch never produced a distinct finger state at all
    # — it read as 3 extended, indistinguishable from a partly-open hand. Finger
    # count separates perfectly on the same data: fist 100% at 0, two-finger 100%
    # at 2, open and roaming 100% at 5.
    #
    # It is also one signal for the whole vocabulary, so the states cannot collide
    # the way pose-based scroll collided with pose-based pointing.
    clutch_mode: str = "fingers"    # "fingers" | "palm"
    # 4, not 2: a deliberate pinch reads as THREE extended fingers on this
    # hardware (100% of 443 corpus frames), so a lower threshold would lift the
    # mouse at the exact moment the user is trying to click. Lifting is now an
    # unmistakable open hand.
    #   0 fist        -> grab / drag
    #   1-3           -> engaged; pinch within this range clicks
    #   4-5 open hand -> lifted
    lift_at_fingers: int = 4

    # ASYMMETRIC debounce. Engaging is cheap and should feel instant; LIFTING
    # interrupts what you are doing, so it must be deliberate. A symmetric 80ms
    # window produced ~28 clutch cycles in one 60s session, because finger count
    # flaps between 1 and 2 while pointing and either direction was equally easy.
    finger_hold: float = 0.05       # engage: ~6 frames at 110fps
    finger_lift_hold: float = 0.25  # lift: ~28 frames — a deliberate open hand

    # Clutch = palm rotation, the ratchet that makes relative pointing possible.
    #
    # Palm-down (normal within 30 deg of straight down) is the neutral hand-on-desk
    # posture, so holding it costs nothing. Rotate the palm toward vertical, like
    # turning a doorknob, and the pointer parks while you reposition.
    #
    # Deliberately DIGIT-DISJOINT from every click pose: a clutch that needs
    # specific fingers gets broken by the click it is supposed to survive. It also
    # avoids ring/pinky extension entirely — the least reliable booleans this v1
    # sensor produces palm-down.
    clutch_on_deg: float = 30.0
    clutch_off_deg: float = 45.0
    # Wider in xy: an upright palm is closer to edge-on to a device that looks up,
    # so its normal is noisier, and 30 deg proved too tight to hold.
    clutch_on_deg_xy: float = 50.0
    clutch_off_deg_xy: float = 70.0

    # Bypass the clutch entirely: the pointer moves whenever a hand is tracked.
    # The clutch gates ALL pointer motion, so a posture that cannot reach it looks
    # exactly like total failure. This makes that recoverable without a diagnosis,
    # at the cost of the ratchet (no repositioning without moving the cursor).
    clutch_enabled: bool = True
    clutch_dwell: float = 0.045     # ~5 frames at 110fps
    clutch_release_dwell: float = 0.072

    # Scroll = FIST + move, not the old index+middle pose.
    #
    # That pose was index+middle extended with the rest curled — which is very
    # nearly the natural pointing posture now that the index fingertip drives the
    # cursor. A live session emitted 61 scroll events inside a single clutch just
    # from pointing. Pointing and scrolling cannot be made digit-disjoint while the
    # index is the pointer, so scroll moves to the one channel that is perfectly
    # separable here: grab_strength was >0.5 on 100% of fist frames and 0% of every
    # other pose. Grab the page and drag it.
    # Scroll is POSITION control from the grab anchor, not rate control.
    #
    # Rate control (velocity -> scroll speed) emitted one event per frame at 110Hz;
    # measured at ~7700 px/sec, roughly seven pages a second, and it kept scrolling
    # for as long as the fist was held. Displacement control cannot run away: move
    # the hand 10mm and the page moves a fixed amount, hold still and it stops.
    scroll_gain: float = 3.0        # px of scroll per mm of hand travel
    scroll_min_mm: float = 0.5      # ignore tremor while simply holding a fist
    scroll_interval: float = 0.03   # emit at ~33Hz, not once per tracking frame


class GestureEngine:
    """Consumes Snapshots, emits IntentEvents. Holds all the temporal state."""

    def __init__(self, config: Optional[Config] = None):
        self.cfg = config or Config()
        xy = self.cfg.plane == "xy"
        self.clutch_ref = CLUTCH_REFERENCE[self.cfg.plane]
        self.engaged = Schmitt(
            self.cfg.engage_y_xy if xy else self.cfg.engage_y,
            self.cfg.release_y_xy if xy else self.cfg.release_y,
            self.cfg.engage_dwell)
        self.pinch = Schmitt(self.cfg.pinch_on_mm, self.cfg.pinch_off_mm, self.cfg.pinch_dwell)
        self.grab = Schmitt(self.cfg.grab_on, self.cfg.grab_off, self.cfg.grab_dwell)
        # on_at < off_at: a SMALL angle means palm-down means engaged.
        self.clutch = Schmitt(
            self.cfg.clutch_on_deg_xy if xy else self.cfg.clutch_on_deg,
            self.cfg.clutch_off_deg_xy if xy else self.cfg.clutch_off_deg,
            self.cfg.clutch_dwell)
        # "no swipe has ever happened" — not 0.0, which reads as "a swipe just
        # happened at t=0" and silently suppresses every swipe until the refractory
        # elapses. Invisible against real sensor timestamps (large microsecond
        # counts) but fatal on any timebase that starts near zero.
        self._last_swipe = float("-inf")
        self._now = 0.0
        self.last_clutch_angle: Optional[float] = None
        self.fingers = Debounce(5, self.cfg.finger_hold)
        self._scroll_anchor: Optional[float] = None
        self._scroll_emitted_at = 0.0
        self._subscribers: list[Callable[[IntentEvent], None]] = []

    def _clock(self, frame: Optional[HandFrame]) -> float:
        """Time comes from the sensor, not the wall.

        Every frame carries the tracking service's own microsecond timestamp. Using
        it means dwell and refractory windows measure when the motion happened rather
        than when Python got around to the callback — so a GC pause or a slow
        subscriber cannot stretch a dwell. It also makes the engine deterministic:
        a recorded session replays to exactly the same intents at any speed, which
        is how these thresholds are regression-tested.
        """
        if frame is not None:
            self._now = frame.timestamp / 1e6
        return self._now

    def subscribe(self, fn: Callable[[IntentEvent], None]) -> None:
        self._subscribers.append(fn)

    def _emit(self, intent: Intent, frame: Optional[HandFrame] = None, **data) -> None:
        event = IntentEvent(intent, self._now, frame, data)
        for fn in self._subscribers:
            fn(event)

    def _release_buttons(self, frame: Optional[HandFrame]) -> None:
        """Drop held buttons, leaving the clutch alone.

        Kept separate from _release_all for a reason that cost a debugging cycle:
        force_off() clears a Schmitt's pending-dwell timer, so calling it on the
        clutch every un-clutched frame means the dwell can never accumulate and the
        clutch can NEVER engage. Only reach for the clutch when the hand is
        genuinely gone.
        """
        if self.pinch.force_off():
            self._emit(Intent.SELECT_UP, frame)
        if self.grab.force_off():
            self._emit(Intent.GRAB_UP, frame)

    def _release_all(self, frame: Optional[HandFrame]) -> None:
        self._release_buttons(frame)
        if self.clutch.force_off():
            self._emit(Intent.CLUTCH_UP, frame)

    def on_snapshot(self, snap: Snapshot) -> None:
        frame = snap.get(self.cfg.hand)
        now = self._clock(frame)

        # Tracking lost: release everything held, then disengage. Order matters —
        # a held button must come up before the pointer stops being driven.
        if frame is None:
            self._release_all(None)
            if self.engaged.force_off():
                self._emit(Intent.DISENGAGE, None)
            return

        edge = self.engaged.update(frame.position.y, now)
        if edge is True:
            self._emit(Intent.ENGAGE, frame)
        elif edge is False:
            self._release_all(frame)
            self._emit(Intent.DISENGAGE, frame)

        if not self.engaged.state:
            return

        # The clutch decides whether the pointer moves at all. Palm angle is
        # independent of every finger, so clicking never breaks it.
        angle = palm_angle_degrees(frame, self.clutch_ref)
        self.last_clutch_angle = angle

        # Bypass FIRST: --no-clutch is the advertised stuck-cursor escape
        # hatch, and checking the mode before it made the flag dead code in the
        # default finger vocabulary. Under bypass the pointer moves whenever a
        # hand is tracked; pinch still clicks, but fist-drag and open-hand lift
        # are unavailable (the ladder is what drives them).
        if not self.cfg.clutch_enabled:
            if not self.clutch.state:        # latch on and stay on
                self.clutch.state = True
                self._emit(Intent.CLUTCH_DOWN, frame)
        elif self.cfg.clutch_mode == "fingers":
            self._update_finger_ladder(frame, now)
        else:
            edge = self.clutch.update(angle, now)
            if edge is True:
                self._emit(Intent.CLUTCH_DOWN, frame)
            elif edge is False:
                self._emit(Intent.CLUTCH_UP, frame)

        if self.clutch.state:
            self._emit(Intent.POINT_MOVE, frame,
                       settle=self._settle_factor(frame))

        if self.cfg.clutch_mode == "fingers":
            if self.clutch.state and not self.grab.state:
                self._update_pinch(frame, now)
            return      # a fist is a DRAG, not a scroll: one pose, one meaning.

        # Buttons only exist while the clutch is held. Releasing the clutch is the
        # equivalent of lifting a mouse — pressing its button mid-air does nothing.
        # A live session fired select.down/up after clutch.up while the hand was
        # simply being repositioned.
        if not self.clutch.state:
            self._release_buttons(frame)
            return

        # Pinch to select. Guarded on the LATCHED grab state, not the instantaneous
        # reading: a fist collapses pinch_distance to ~15mm, so a momentary dip in
        # grab_strength was enough to latch a pinch on top of a grab. The live log
        # shows grab.down then select.down with no release between them, leaving the
        # mouse button held down through hundreds of scroll events.
        if not self.grab.state and frame.grab_strength < self.cfg.grab_on:
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

    def _update_finger_ladder(self, frame: HandFrame, now: float) -> None:
        """One signal drives clutch and grab, so they cannot contradict."""
        # Hold longer to lift than to engage: lifting interrupts the user.
        self.fingers.hold = (self.cfg.finger_lift_hold
                             if frame.extended_count >= self.cfg.lift_at_fingers
                             else self.cfg.finger_hold)
        self.fingers.update(frame.extended_count, now)
        count = self.fingers.value

        lifted = count >= self.cfg.lift_at_fingers
        if lifted and self.clutch.state:
            if self.pinch.force_off():
                self._emit(Intent.SELECT_UP, frame)
            if self.grab.force_off():
                self._emit(Intent.GRAB_UP, frame)
            self.clutch.state = False
            self._emit(Intent.CLUTCH_UP, frame)
        elif not lifted and not self.clutch.state:
            self.clutch.state = True
            self._emit(Intent.CLUTCH_DOWN, frame)

        if not self.clutch.state:
            return

        # A fist is the button, and it is driven by the DEBOUNCED finger count
        # alone. Gating it additionally on a raw grab_strength threshold gave the
        # button no hysteresis at all, so a momentary dip dropped it mid-drag —
        # the live log shows grab.down/grab.up pairs firing repeatedly.
        # count == 0 was 100% accurate across 444 real fist frames, so it is
        # sufficient on its own.
        # A pinch closing into a fist passes through both states, and both drive
        # the same physical button — so when the debounced count says FIST, the
        # pinch latch hands over silently: no SELECT_UP (that would release the
        # physical button mid-gesture; _press idempotency makes the following
        # GRAB_DOWN a physical no-op) and the drag is thereafter owned by the
        # deliberate debounced open hand, not two noisy frames of pinch distance.
        if count == 0 and self.pinch.state:
            self.pinch.force_off()
        fisted = count == 0 and not self.pinch.state
        if fisted and not self.grab.state:
            self.grab.state = True
            self._emit(Intent.GRAB_DOWN, frame)
        elif not fisted and self.grab.state:
            self.grab.state = False
            self._emit(Intent.GRAB_UP, frame)

    def _update_pinch(self, frame: HandFrame, now: float) -> None:
        """Click on a high-confidence pinch: distance AND strength must agree.

        A CLOSING FIST also collapses thumb-index distance on its way shut, so a
        fist-shaped frame (raw count 0) may not START a pinch — that race let the
        noisy pinch latch first and steal the drag from the debounced count
        (corpus: fist reads count 0 on 541/542 frames; a held pinch reads 1-2).
        An already-latched pinch still releases on distance alone.
        """
        confident = (frame.pinch_strength >= self.cfg.pinch_min_strength
                     and (self.pinch.state or frame.extended_count > 0))
        # Feed the Schmitt a value it will reject unless the corroborating signal
        # agrees, so hysteresis still governs the transition.
        value = frame.pinch_distance if confident else self.cfg.pinch_off_mm + 1.0
        edge = self.pinch.update(value, now)
        if edge is True:
            self._emit(Intent.SELECT_DOWN, frame)
        elif edge is False:
            self._emit(Intent.SELECT_UP, frame)

    def _settle_factor(self, frame: HandFrame) -> float:
        """1.0 = move freely, 0.0 = frozen. Ramps as a pinch closes.

        Only while the click is FORMING. Once either button latches, the hand
        is dragging and needs full gain back — a held pinch (~15mm) and a fist
        (~18mm) both sit below settle_full for their whole duration, so gating
        on the raw distance froze every drag the vocabulary promises.
        """
        if self.pinch.state or self.grab.state:
            return 1.0
        start, full = self.cfg.settle_start_mm, self.cfg.settle_full_mm
        d = frame.pinch_distance
        if d >= start:
            return 1.0
        if d <= full:
            return 0.0
        return (d - full) / (start - full)

    def _maybe_scroll(self, frame: HandFrame) -> None:
        if not self.grab.state:
            self._scroll_anchor = None
            return
        z = frame.position.z
        if self._scroll_anchor is None:          # first frame of this grab
            self._scroll_anchor = z
            self._scroll_emitted_at = self._now
            return
        if self._now - self._scroll_emitted_at < self.cfg.scroll_interval:
            return
        travel = z - self._scroll_anchor
        if abs(travel) < self.cfg.scroll_min_mm:
            return
        self._scroll_anchor = z                  # consume it; only NEW travel scrolls
        self._scroll_emitted_at = self._now
        self._emit(Intent.SCROLL, frame, dy=travel * self.cfg.scroll_gain)

