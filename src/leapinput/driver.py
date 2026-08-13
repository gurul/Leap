"""Driver layer: Intent stream -> Backend calls.

`DirectDriver` is the low-latency path — the hand *is* the cursor. A future CUA driver
consumes the same Intent stream but treats gestures as high-level commands handed to
an agent rather than as pointer motion. Both subscribe to `GestureEngine`; they are
interchangeable, and can run side by side (direct pointing, agent-dispatched swipes).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

from .actions import Backend
from .oneeuro import OneEuroVec3
from .capture import HandFrame
from .gestures import Intent, IntentEvent


@dataclass
class Mapping:
    """The interaction box, in millimetres, in Leap device coordinates.

    MEASURED, not assumed — and the measurement overturned the obvious guess. Across
    3639 frames (docs/context/session.jsonl) the reachable volume is a wide, shallow,
    strongly right-shifted slab, not the symmetric box you would design from the
    datasheet:

        x   p2 -24 .. p98 +214   (median +42)   238mm wide
        z   p2 +15 .. p98  +84   (median +45)    69mm deep

    A symmetric +/-110 box would have been unusable: z never went negative at all in
    the entire session, so the whole top half of the screen would have been physically
    unreachable, and the left edge needs x=-110 when the hand never passed -97.

    CAVEAT: z is under-sampled. The roam step spanned only 39mm at p5-p95 because the
    hand mostly swept sideways. 69mm of depth mapped onto 982px is ~14 px/mm versus
    ~6 px/mm horizontally, so vertical control is twice as twitchy as horizontal.
    Re-capture a roam that deliberately explores near/far before trusting z.
    """

    x_min: float = -24.0
    x_max: float = 214.0
    z_far: float = 15.0      # away from you -> top of screen
    z_near: float = 84.0     # toward you   -> bottom of screen

    # Non-linear control-display gain, px per mm of hand travel. Slow deliberate
    # motion gets sub-pixel precision; a fast flick crosses the display in ~50mm.
    # Never 1:1 — that is what forces the big arm movements this design exists to
    # avoid. Seeds, to be refit against a Fitts-law harness.
    # Tuned by use, in both directions. 1->30 px/mm was hyper-responsive (a 50mm
    # movement swept the whole screen); 0.25->5 was then too slow. 0.5->10 sits
    # between them: still ~1:2 at slow speed for fine aiming, crossing the 1512px
    # display in ~150mm of fast travel. Note the index fingertip also raises
    # effective sensitivity for free, since the tip travels further than the palm
    # for the same wrist rotation.
    # Raised by use. Low control-display gain measurably HURTS pointing — more
    # clutching, higher limb speeds — and pointer acceleration beats constant gain
    # by 3.3-5.6%, most on small targets. A low floor is not "precision", it is
    # just slow; the non-linear RATIO is what buys precision, so both ends move
    # together and the ~11x slow-to-fast ratio is preserved.
    #
    # This also matters for tracking: a hand that has to travel less stays in the
    # reliable centre of the cone, where LMC1 error is ~8mm rather than the >20mm
    # RMS it reaches at the extremes. Higher gain is a dropout mitigation, not
    # only a comfort setting.
    gain_min: float = 2.12
    gain_max: float = 23.32
    speed_lo: float = 25.0       # mm/s at or below which gain_min applies
    speed_hi: float = 380.0      # mm/s at or above which gain_max applies
    deadzone_mm: float = 0.12    # below this per-frame delta, don't move at all

    # Scales both gain ends together, so --gain retunes overall sensitivity
    # without disturbing the slow/fast ratio that makes fine aiming possible.
    gain_scale: float = 1.0

    # Axis direction. Leap desktop mode is +x right, +y up, +z TOWARD the user, and
    # CG screen space is +y DOWN, so the raw signs already line up: push the hand
    # away and the cursor goes up. Confirmed correct in live use 2026-08-12 — an
    # earlier invert_z=True default was my misreading of a vaguer bug report, and
    # it made up/down wrong.
    #
    # Kept as config rather than hardcoded because the controller's physical
    # rotation decides this, not the datasheet: turn it 180 degrees so the cable
    # faces you and z flips. Exposed as --invert-x / --invert-z so it can be
    # settled by trying it rather than by reasoning about sign conventions.
    invert_x: bool = True       # confirmed by use 2026-08-12
    invert_z: bool = False      # applies to the vertical axis in both planes

    # "xz" (default, measured best) = the desk plane. Hand left/right drives the
    # cursor horizontally; hand FORWARD/BACK drives it vertically. "xy" reads the
    # vertical axis from hand height instead, for an upright posture.
    # Must match Config.plane, which also moves the clutch reference, cone width
    # and engagement floor.
    plane: str = "xz"

    # Which point the cursor follows: "index" | "knuckles" | "palm".
    #
    # The index fingertip is the natural pointer and the most expressive — it
    # travels further than the palm for the same wrist rotation. The tradeoff is
    # real and worth knowing: pinching curls the index toward the thumb, so the
    # tracked point moves during a click. The 1 euro filter and the click's own
    # dwell absorb some of it; if clicks land off-target, "knuckles" is the
    # rigid alternative, or move the click to a grab which leaves the index alone.
    tracking_point: str = "index"

    # Edge guard. Tracking degrades toward the edge of the cone — LMC1 palm error
    # rises from ~8mm centrally to RMS >20mm at the extremes — so raw motion out
    # there is mostly noise, and at high gain that noise becomes cursor jumps and
    # the "goes beyond the plane" behaviour. Damp toward the edge instead of
    # trusting it: full speed inside edge_ok_deg, fading to zero by edge_max_deg.
    edge_ok_deg: float = 40.0
    edge_max_deg: float = 62.0

    scroll_gain: float = 1.0


def _remap(value: float, lo: float, hi: float, out_hi: float) -> float:
    t = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, t)) * out_hi


class DirectDriver:
    """Hand as mouse, RELATIVE with a clutch ratchet.

    Absolute mapping was tried and abandoned on measured evidence. The reachable
    volume is a wide, shallow, right-shifted slab, so mapping it onto the display
    pushes the hand to the edge of tracking to reach the screen edge — a live 60s
    session lost tracking five times. Relative control decouples the two: move,
    release the clutch, reposition anywhere comfortable, re-engage. Exactly what
    lifting a mouse does.

    The cursor only moves between CLUTCH_DOWN and CLUTCH_UP, and it moves by
    integrated hand delta from the anchor — never by absolute position, which
    would teleport on every re-clutch and void the whole mechanism.
    """

    def __init__(self, backend: Backend, mapping: Mapping | None = None):
        self.backend = backend
        self.map = mapping or Mapping()
        self.w, self.h = backend.screen
        # Clamp to every display, not just the main one. Displays above or left of
        # the main have negative CG origins, so clamping at 0 traps the cursor on
        # the main screen — measured here: the second display lives at (-541,-1440).
        self.min_x, self.min_y, self.max_x, self.max_y = backend.bounds
        self.x, self.y = self.w / 2.0, self.h / 2.0
        self._filter = OneEuroVec3(freq=110.0, min_cutoff=1.0, beta=0.007)
        self._last: tuple[float, float] | None = None   # last filtered hand x/z
        self._warned: set[str] = set()
        self._button_down = False

    def _gain(self, speed: float) -> float:
        lo, hi = self.map.speed_lo, self.map.speed_hi
        t = 0.0 if speed <= lo else 1.0 if speed >= hi else (speed - lo) / (hi - lo)
        base = self.map.gain_min + t * (self.map.gain_max - self.map.gain_min)
        return base * self.map.gain_scale

    def _edge_factor(self, frame: HandFrame) -> float:
        """1.0 in the reliable core, fading to 0.0 at the edge of the cone."""
        ecc = frame.eccentricity
        ok, cap = self.map.edge_ok_deg, self.map.edge_max_deg
        if ecc <= ok:
            return 1.0
        if ecc >= cap:
            return 0.0
        return (cap - ecc) / (cap - ok)

    #: Intents this driver deliberately does not act on. Anything NOT listed here
    #: and NOT handled is a wiring bug, and gets reported rather than swallowed.
    IGNORED = frozenset({"engage", "scroll",
                         "swipe.left", "swipe.right", "swipe.up", "swipe.down"})

    def on_intent(self, event: IntentEvent) -> None:
        handler = getattr(self, f"_on_{event.intent.name.lower()}", None)
        if handler:
            handler(event)
        elif event.intent.value not in self.IGNORED:
            # Silent getattr dispatch is how a fist emitted grab.down for a whole
            # session with no mouse button behind it. An unrouted intent is a bug,
            # so say so once instead of doing nothing forever.
            if event.intent.value not in self._warned:
                self._warned.add(event.intent.value)
                print(f"  [driver] no handler for intent {event.intent.value!r} "
                      f"— this gesture does nothing", file=sys.stderr)

    # --- clutch: the ratchet ------------------------------------------------

    def _on_clutch_down(self, event: IntentEvent) -> None:
        """Anchor here. The cursor does NOT jump — that is the whole point."""
        self._filter.reset()
        self._last = None

    def _on_clutch_up(self, event: IntentEvent) -> None:
        self._last = None

    def _on_disengage(self, event: IntentEvent) -> None:
        self._last = None
        self._press(False)          # never disengage holding the button

    # --- pointer ------------------------------------------------------------

    def _on_point_move(self, event: IntentEvent) -> None:
        frame = event.frame
        p = frame.track_point(self.map.tracking_point)
        fx, fy, fz = self._filter(p.x, p.y, p.z, frame.timestamp / 1e6)

        # In xy the vertical screen axis comes from hand HEIGHT, and it is negated
        # because hand +y is up while CG screen +y is down: raise the hand, the
        # cursor rises. In xz it comes from hand depth.
        vertical = -fy if self.map.plane == "xy" else fz

        if self._last is None:              # first frame of this clutch: anchor only
            self._last = (fx, vertical)
            return

        dx_mm, dz_mm = fx - self._last[0], vertical - self._last[1]
        self._last = (fx, vertical)

        if abs(dx_mm) < self.map.deadzone_mm and abs(dz_mm) < self.map.deadzone_mm:
            return                          # resting-hand tremor, not intent

        if self.map.invert_x:
            dx_mm = -dx_mm
        if self.map.invert_z:
            dz_mm = -dz_mm

        v = frame.palm_velocity
        gain = self._gain(math.hypot(v.x, v.y if self.map.plane == "xy" else v.z))
        # Freeze progressively as a click forms, so the pinch cannot drag the
        # cursor off the target it was aimed at.
        gain *= event.data.get("settle", 1.0)
        gain *= self._edge_factor(frame)
        if gain == 0.0:
            return
        self.x = max(self.min_x, min(self.max_x - 1.0, self.x + dx_mm * gain))
        self.y = max(self.min_y, min(self.max_y - 1.0, self.y + dz_mm * gain))
        self.backend.move(self.x, self.y)

    # --- buttons ------------------------------------------------------------

    def _press(self, down: bool) -> None:
        """Idempotent button state.

        Select and grab are distinct intents that drive ONE physical button, so a
        gesture passing through both would otherwise post down/down/up/up and
        leave macOS confused about whether a drag is in progress. The driver owns
        the truth about the button rather than trusting the intent stream.
        """
        if down == self._button_down:
            return
        self._button_down = down
        (self.backend.down if down else self.backend.up)(self.x, self.y)

    def _on_select_down(self, event: IntentEvent) -> None:
        self._press(True)

    def _on_select_up(self, event: IntentEvent) -> None:
        self._press(False)

    # A fist IS the button in the finger-ladder vocabulary. These were missing
    # while the vocabulary moved off pinch, so the fist emitted grab.down into
    # nothing and the click silently did nothing at all.
    def _on_grab_down(self, event: IntentEvent) -> None:
        self._press(True)

    def _on_grab_up(self, event: IntentEvent) -> None:
        self._press(False)

    def _on_scroll(self, event: IntentEvent) -> None:
        self.backend.scroll(event.data.get("dy", 0.0) * self.map.scroll_gain)


class ShortcutDriver:
    """Placeholder for discrete commands.

    Previously mapped swipes to Spaces and the app switcher. Swipes are cut — the
    motion leaves the tracking volume — so there is nothing to map yet. The next
    discrete command should be a static pose held briefly, which cannot carry the
    hand out of view. Kept so the wiring in cli.py stays honest about the gap.
    """

    def __init__(self, backend: Backend):
        self.backend = backend

    def _edge_factor(self, frame: HandFrame) -> float:
        """1.0 in the reliable core, fading to 0.0 at the edge of the cone."""
        ecc = frame.eccentricity
        ok, cap = self.map.edge_ok_deg, self.map.edge_max_deg
        if ecc <= ok:
            return 1.0
        if ecc >= cap:
            return 0.0
        return (cap - ecc) / (cap - ok)

    def on_intent(self, event: IntentEvent) -> None:
        return None
