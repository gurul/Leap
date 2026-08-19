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
from typing import Callable, Optional

from .actions import Backend
from .camera import plane_norm
from .oneeuro import OneEuroPlane
from .capture import HandFrame, Vec3
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

    # Touch-mode precision (2026-08-19): slow hand = small target. People
    # decelerate on final approach (Fitts), so speed is the free, implicit
    # precision trigger — the same insight TiltReduction (Chang et al.,
    # CHI 2015) exploited with natural device tilt, and the mechanism is
    # PRISM (Frees & Kessler): below precision_full_speed the mapped target's
    # motion is scaled down toward precision_gain_min, accumulating a BOUNDED
    # offset; at speed the mapping is 1:1 and each frame bleeds the offset
    # away by precision_recover, so the touch sheet stays position-faithful
    # for ballistic motion and gains sub-target precision exactly when the
    # hand says it is aiming (macOS traffic-light buttons are ~12px).
    # precision_gain_min=1.0 disables the whole layer.
    precision_gain_min: float = 0.35
    precision_full_speed: float = 700.0   # px/s of the mapped target
    precision_offset_max_px: float = 60.0
    precision_recover: float = 0.10       # offset bleed per full-speed frame

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

    # Absolute mapping: the virtual plane IS the main screen — hand position
    # maps to cursor position directly, no clutch ratchet, no speed gain. Only
    # sane for a camera source with a fitted reach box (python -m
    # leapinput.reach map): the box makes the comfortable reach exactly one
    # screen, which is what made absolute unusable on the Leap's lopsided
    # reachable slab. The screen floats in hand space; point at a spot to put
    # the cursor there.
    absolute: bool = False

    # 1 euro filter seeds for the pointer. Defaults tuned for the Leap at 111fps;
    # the camera source lowers min_cutoff and raises beta (see camera.tune_for_camera)
    # because its landmarks are noisier and arrive at a quarter of the rate.
    pointer_min_cutoff: float = 1.0
    pointer_beta: float = 0.007
    # Cutoff for the 1€ speed estimate. Raising it makes beta open on motion
    # onset sooner (fewer frames of lag before the filter trusts the speed).
    pointer_d_cutoff: float = 1.0


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
        # Per-display rects: the union of an L-shaped layout contains a VOID,
        # and clamping into it strands the cursor in unreachable space.
        self.rects = list(getattr(backend, "rects", None) or [backend.bounds])
        # Seed from where the cursor ACTUALLY is, not screen center: the first
        # move must continue from what the user sees, never teleport.
        self.x, self.y = self._contain(*backend.pos())
        self._filter = OneEuroPlane(freq=110.0, min_cutoff=self.map.pointer_min_cutoff,
                                    beta=self.map.pointer_beta,
                                    d_cutoff=self.map.pointer_d_cutoff)
        self._last: tuple[float, float] | None = None   # last filtered hand x/z
        self._warned: set[str] = set()
        self._button_down = False
        # Where the cursor was when the pinch STARTED forming, plus when it was
        # armed. Selection motion displaces the pointer at the exact moment it
        # must hold still — the "Heisenberg effect", measured at 30% of all
        # mid-air pointing errors, and backdating the click to gesture onset cut
        # errors 25% (Wolf et al., CHI 2020). The settle ramp already slows the
        # drift; this pins the click itself to where the user was aiming before
        # the pinch moved it. The timestamp and a distance bound keep a STALE
        # anchor from teleporting a click back to somewhere seconds old.
        self._click_anchor: tuple[float, float, float] | None = None
        # Where the button went down, and pixels travelled since: a release
        # within a click's worth of travel posts AT the down position, because
        # macOS resolves the click target on mouse-up.
        self._down_pos: tuple[float, float] | None = None
        self._travel = 0.0
        # Absolute (touch) mode only: the live hand target of the last frame,
        # and the offset that pins the cursor to the anchor-warped commit
        # position for the whole button hold. Without it the first full-settle
        # frame after the warp lerps straight back to the live target, the
        # snap accrues into _travel, and the <12px pin-back refuses — turning
        # a corrected click into an accidental drag.
        self._abs_target: tuple[float, float] | None = None
        self._touch_offset: tuple[float, float] | None = None
        # Touch precision (PRISM): last raw mapped target + its time, and the
        # accumulated slow-motion offset. See Mapping.precision_gain_min.
        self._prec_last: tuple[float, float, float] | None = None
        self._prec_off: tuple[float, float] = (0.0, 0.0)

    def _contain(self, x: float, y: float) -> tuple[float, float]:
        """Clamp to the NEAREST real display, not the union of all of them."""
        best, best_d = None, None
        for x0, y0, x1, y1 in self.rects:
            cx = max(x0, min(x1 - 1.0, x))
            cy = max(y0, min(y1 - 1.0, y))
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best_d is None or d < best_d:
                best, best_d = (cx, cy), d
                if d == 0.0:
                    break
        return best

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
        """Anchor here. The cursor does NOT jump — that is the whole point.

        Re-sync with the REAL cursor: the user may have used the trackpad since
        the last clutch, and integrating from our phantom position would
        teleport the cursor back to wherever we last left it.
        """
        self._filter.reset()
        self._last = None
        self.x, self.y = self._contain(*self.backend.pos())

    def _on_clutch_up(self, event: IntentEvent) -> None:
        self._last = None
        self._click_anchor = None

    def _on_disengage(self, event: IntentEvent) -> None:
        self._last = None
        self._click_anchor = None
        self._up()                  # never disengage holding the button

    # --- pointer ------------------------------------------------------------

    def _on_point_move(self, event: IntentEvent) -> None:
        frame = event.frame
        settle = event.data.get("settle", 1.0)
        if settle >= 1.0 and not self._button_down:
            self._click_anchor = None       # pinch fully open again: re-arm
        elif self._click_anchor is None and not self._button_down:
            # Pinch starts forming: aim is HERE, and remember when.
            self._click_anchor = (self.x, self.y, event.at)
        # Only the two plane axes are read, filtered or integrated. The off-plane
        # axis gates (engage floor, edge guard) but never contributes to position.
        p = frame.track_point(self.map.tracking_point)
        if self.map.absolute:
            self._move_absolute(p, frame.timestamp, settle)
            return
        raw_v = -p.y if self.map.plane == "xy" else p.z
        fx, vertical = self._filter(p.x, raw_v, frame.timestamp / 1e6)

        if self._last is None:              # first frame of this clutch: anchor only
            self._last = (fx, vertical)
            return

        dx_mm, dz_mm = fx - self._last[0], vertical - self._last[1]

        if abs(dx_mm) < self.map.deadzone_mm and abs(dz_mm) < self.map.deadzone_mm:
            # Sub-threshold: KEEP the anchor. Advancing it here consumed slow
            # motion frame by frame, so any hand moving under ~deadzone/frame
            # produced zero cursor motion forever — precise aiming was
            # structurally impossible. Held back, the deltas accumulate against
            # the stale anchor and release as one honest step.
            return
        self._last = (fx, vertical)

        if self.map.invert_x:
            dx_mm = -dx_mm
        if self.map.invert_z:
            dz_mm = -dz_mm

        v = frame.palm_velocity
        # Distance compensation (camera sources): motion_scale restores the
        # physical meaning of both the delta and the speed the gain curve
        # reads, so sensitivity feels the same near the camera and far from
        # it. Applied AFTER the deadzone check — image-space noise does not
        # grow with distance, so the noise floor must not be magnified.
        gain = self._gain(math.hypot(v.x, v.y if self.map.plane == "xy" else v.z)
                          * frame.motion_scale)
        gain *= frame.motion_scale
        # Freeze progressively as a click forms, so the pinch cannot drag the
        # cursor off the target it was aimed at.
        gain *= event.data.get("settle", 1.0)
        gain *= self._edge_factor(frame)
        if gain == 0.0:
            return
        px, py = self.x, self.y
        self.x, self.y = self._contain(self.x + dx_mm * gain, self.y + dz_mm * gain)
        if self._button_down:
            self._travel += math.hypot(self.x - px, self.y - py)
        self.backend.move(self.x, self.y)

    def _move_absolute(self, p: Vec3, timestamp_us: int, settle: float) -> None:
        """Hand position -> cursor position on the main screen.

        Filtered in plane mm (where the 1 euro seeds were tuned), then scaled
        to pixels. The settle ramp lerps toward the target instead of scaling
        a delta — same freeze-as-the-pinch-forms behaviour, absolute flavour.
        A reach-box clamp upstream means an overreached hand pins the cursor
        at the screen edge rather than losing it.
        """
        fx, fy = self._filter(p.x, p.y, timestamp_us / 1e6)
        nx, ny = plane_norm(Vec3(fx, fy, 0.0))
        tx, ty = nx * (self.w - 1.0), ny * (self.h - 1.0)
        # PRISM precision: sub-1:1 gain while the hand moves slowly (final
        # approach on a small target), 1:1 with offset bleed at speed. Speed
        # and offset accrual come from the RAW target — measuring the filtered
        # one would read the 1-euro convergence tail after a flick as a slow
        # hand and park the cursor short of a corner the hand already reached.
        # The offset is applied INSIDE _abs_target so the click-pin math below
        # keeps measuring only the settle-lerp gap.
        now_s = timestamp_us / 1e6
        rnx, rny = plane_norm(Vec3(p.x, p.y, 0.0))
        rtx, rty = rnx * (self.w - 1.0), rny * (self.h - 1.0)
        g = 1.0
        if self._prec_last is not None:
            ltx, lty, lt = self._prec_last
            dt = now_s - lt
            if 0.0 < dt <= 0.2:             # continuous stream only: a gap
                dx, dy = rtx - ltx, rty - lty  # (reacquire) must not read as
                speed = math.hypot(dx, dy) / dt      # an infinite-speed frame
                g = min(1.0, max(self.map.precision_gain_min,
                                 speed / self.map.precision_full_speed))
                ox = self._prec_off[0] + dx * (g - 1.0)
                oy = self._prec_off[1] + dy * (g - 1.0)
                if g >= 1.0:
                    ox *= 1.0 - self.map.precision_recover
                    oy *= 1.0 - self.map.precision_recover
                mag = math.hypot(ox, oy)
                cap = self.map.precision_offset_max_px
                if mag > cap:
                    ox, oy = ox * cap / mag, oy * cap / mag
                self._prec_off = (ox, oy)
        self._prec_last = (rtx, rty, now_s)
        tx += self._prec_off[0]
        ty += self._prec_off[1]
        self._abs_target = (tx, ty)
        if self._touch_offset is not None:
            # Button held: keep aiming at the anchor-warped commit position.
            # Hand deltas still move the cursor 1:1 through the offset, so a
            # real drag drags; the offset-clear snap lands after the click.
            tx += self._touch_offset[0]
            ty += self._touch_offset[1]
        if settle <= 0.0:
            return
        px, py = self.x, self.y
        self.x, self.y = self._contain(px + (tx - px) * settle,
                                       py + (ty - py) * settle)
        # Touch deadband, scaled with the precision gain: residual filter
        # noise must not paint pixels, but at sub-1:1 gain that noise is
        # already scaled down — a fixed 1.5px band would eat the slow
        # deliberate crawl precision mode exists for. Floor keeps rest quiet.
        if math.hypot(self.x - px, self.y - py) < max(0.8, 1.5 * g):
            self.x, self.y = px, py
            return
        if self._button_down:
            self._travel += math.hypot(self.x - px, self.y - py)
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

    # Anchor trust bounds: past either, the warp does more harm than good and
    # the click posts where the cursor actually is.
    ANCHOR_MAX_AGE_S = 0.75
    ANCHOR_MAX_DIST_PX = 75.0
    # Under this much held-button travel the gesture was a CLICK, not a drag,
    # and mouse-up is pinned back to the down position.
    CLICK_TRAVEL_PX = 12.0

    def _warp_to_anchor(self, event: IntentEvent) -> None:
        """Warp only to a FRESH, NEARBY anchor. A slow-forming pinch or a
        second click in a row used to teleport the cursor back to a
        position seconds old."""
        if self._click_anchor is None:
            return
        ax, ay, armed_at = self._click_anchor
        if (event.at - armed_at <= self.ANCHOR_MAX_AGE_S
                and math.hypot(self.x - ax, self.y - ay) <= self.ANCHOR_MAX_DIST_PX):
            self.x, self.y = ax, ay
            self.backend.move(self.x, self.y)

    def _on_select_down(self, event: IntentEvent) -> None:
        self._warp_to_anchor(event)
        self._down(event)

    def _on_select_up(self, event: IntentEvent) -> None:
        self._up()
        self._click_anchor = None       # every click cycle re-arms fresh

    # A fist IS the button in the finger-ladder vocabulary. These were missing
    # while the vocabulary moved off pinch, so the fist emitted grab.down into
    # nothing and the click silently did nothing at all.
    def _on_grab_down(self, event: IntentEvent) -> None:
        # A fresh fist gets the same Heisenberg correction a pinch does. But
        # the pinch-into-fist handover emits grab.down while the button is
        # already held (no select.up in between), and warping there would
        # teleport a live drag back to the original click anchor.
        if not self._button_down:
            self._warp_to_anchor(event)
        self._down(event)

    def _on_grab_up(self, event: IntentEvent) -> None:
        self._up()
        self._click_anchor = None       # every click cycle re-arms fresh

    def _down(self, event: IntentEvent) -> None:
        if (self.map.absolute and not self._button_down
                and self._abs_target is not None):
            # Touch mode: lock the commit position for the whole hold. The
            # anchor warp just moved the cursor off the live hand target;
            # without the offset the next full-settle frame snaps it back.
            self._touch_offset = (self.x - self._abs_target[0],
                                  self.y - self._abs_target[1])
        self._down_pos = (self.x, self.y)
        self._travel = 0.0
        self._press(True)
        # Any button-down consumes the anchor. A pinch-to-fist handover is
        # deliberately silent (no select.up), so a fist-drag used to leave the
        # pre-drag anchor alive and warp the NEXT pinch-click back to it.
        self._click_anchor = None

    def _up(self) -> None:
        # macOS resolves the click target on mouse-UP. If the button barely
        # travelled, this was a click: land the up on the same pixel as the
        # down so late pinch-opening drift cannot drop it on a neighbour.
        if (self._button_down and self._down_pos is not None
                and self._travel < self.CLICK_TRAVEL_PX
                and (self.x, self.y) != self._down_pos):
            self.x, self.y = self._down_pos
            self.backend.move(self.x, self.y)
        self._down_pos = None
        self._touch_offset = None
        self._press(False)

    def _on_scroll(self, event: IntentEvent) -> None:
        self.backend.scroll(event.data.get("dy", 0.0) * self.map.scroll_gain)


class ShortcutDriver:
    """Discrete commands -> macOS actions.

    Consumes CommandEvents from commands.CommandEngine (static pose-holds — the
    replacement for the cut swipes, which carried the hand out of view). The
    cursor never moves here; these are the actions a keyboard shortcut would do.
    """

    # macOS virtual keycodes (kVK_*): ANSI N, T, C, V, Return, Option, up.
    KEY_N, KEY_T, KEY_C, KEY_V = 45, 17, 8, 9
    KEY_RETURN, KEY_UP, KEY_OPTION = 36, 126, 58

    # Force-release the dictation hold if the stop edge never arrives (camera
    # died, user walked away with the mic open): a stuck system-wide Option
    # breaks typing everywhere. Sized for toggle-mode dictations, which run
    # long by design.
    MAX_DICTATION_S = 180.0

    def __init__(self, backend: Backend, pane_action: str = "screenshot"):
        self.backend = backend
        self.pane_action = pane_action      # "screenshot" | "window" | "tab"
        import threading
        self._dict_lock = threading.Lock()
        self._dictating = False
        self._dict_timer: object | None = None
        # Invoked when the watchdog force-releases the hold, so the layer that
        # tracks dictation state (the CLI's snapshot gate) can re-sync instead
        # of silently inverting its next toggle. Wired by cli.py.
        self.on_forced_release: Optional[Callable[[], None]] = None

    def on_command(self, event) -> None:
        name = event.command.value
        if name == "pane.new":
            self._new_pane(event.data.get("rect"))
        elif name == "mission_control":
            self.backend.key(self.KEY_UP, ctrl=True)
        elif name == "dictate":
            self._dictate(event.data.get("active", False))
        elif name == "copy":
            self.backend.key(self.KEY_C, cmd=True)
        elif name == "paste":
            self.backend.key(self.KEY_V, cmd=True)
        elif name == "enter":
            # Plain tap, NULL event source: with a real HID source, some
            # terminals' global key handling swallows Return before it
            # reaches the focused app (measured in claude-pet, in Warp).
            self.backend.key(self.KEY_RETURN)
        # "toggle" is handled by the CLI's snapshot gate; nothing to press.

    def _dictate(self, active: bool) -> bool:
        """Hold/release the dictation hotkey: a bare Option, the modifier every
        push-to-talk app can be rebound to (Willow Voice here). fn — Willow's
        stock key — is read straight from raw HID by these apps, so a
        synthesized fn is simply not seen; Option synthesizes reliably
        (both verified in claude-pet's voice trigger)."""
        import threading
        with self._dict_lock:
            if active == self._dictating:
                return False                # idempotent on both edges
            self._dictating = active
            if self._dict_timer is not None:
                self._dict_timer.cancel()
                self._dict_timer = None
            self.backend.key_hold(self.KEY_OPTION, active, alt=True)
            if active:
                self._dict_timer = threading.Timer(
                    self.MAX_DICTATION_S, self._dictation_watchdog)
                self._dict_timer.daemon = True
                self._dict_timer.start()
            return True

    def _dictation_watchdog(self) -> None:
        if not self.release_dictation():
            return                          # the stop edge won the race
        print(f"[command] dictation force-released after "
              f"{self.MAX_DICTATION_S:.0f}s — stop edge never arrived",
              file=sys.stderr)
        # Tell the state-tracking layer, or its next chime plays inverted. A
        # callback error must never kill the Timer thread mid-cleanup.
        if self.on_forced_release is not None:
            try:
                self.on_forced_release()
            except Exception as exc:
                print(f"[command] on_forced_release failed: {exc}",
                      file=sys.stderr)

    def release_dictation(self) -> bool:
        """Idempotent; the CLI calls it unconditionally on exit so the session
        can never die holding Option down. True when it actually released."""
        return self._dictate(False)

    def _new_pane(self, rect) -> None:
        """Act on the framed region: capture it, or spawn a window over it."""
        if self.pane_action == "screenshot":
            region = frame_region_px(rect, self.backend.screen, min_frac=0.05)
            if region is not None:
                _screenshot_region(*region)
            return
        self.backend.key(self.KEY_T if self.pane_action == "tab" else self.KEY_N,
                         cmd=True)
        if self.pane_action == "tab":
            return
        # Meaningful frames only for window placement: under ~15% per side the
        # user was almost certainly just releasing sloppily.
        region = frame_region_px(rect, self.backend.screen, min_frac=0.15)
        if region is not None:
            _place_front_window(*region)


def frame_region_px(rect, screen: tuple[float, float],
                    min_frac: float) -> tuple[int, int, int, int] | None:
    """Normalized frame rect -> (x, y, w, h) main-screen pixels, or None when
    the frame is too small on either side to be a deliberate region."""
    if rect is None:
        return None
    x0, y0, x1, y1 = rect
    if (x1 - x0) < min_frac or (y1 - y0) < min_frac:
        return None
    w, h = screen
    return (int(x0 * w), int(y0 * h), int((x1 - x0) * w), int((y1 - y0) * h))


def _screenshot_region(x: int, y: int, w: int, h: int) -> None:
    """Capture the region to the CLIPBOARD (like Cmd+Ctrl+Shift+4), with the
    system shutter sound as the success feedback (matters when headless).
    Clipboard, not a Desktop file: the frame shot exists to be pasted
    somewhere next, and V-sign-on-the-free-hand does exactly that.

    Failure must be as audible as success: without Screen Recording permission
    for the app that launched the session, `screencapture` dies with "could not
    create image from rect" — and swallowing that leaves the user framing
    rectangles at a control that silently does nothing. Error chime + a log
    line naming the fix instead. Runs on a thread so the wait for the exit
    code never stalls the control loop."""
    import subprocess
    import threading

    def run() -> None:
        try:
            out = subprocess.run(["screencapture", "-c",
                                  f"-R{x},{y},{w},{h}"],
                                 capture_output=True, text=True, timeout=10.0)
            if out.returncode == 0 and not out.stderr.strip():
                return
            print(f"[command] frame shot FAILED: "
                  f"{out.stderr.strip() or 'nothing captured'} — grant Screen "
                  f"Recording to the app that runs the session (System "
                  f"Settings > Privacy & Security > Screen & System Audio "
                  f"Recording), then restart that app", file=sys.stderr)
        except Exception as exc:
            print(f"[command] frame shot FAILED: {exc}", file=sys.stderr)
        try:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Basso.aiff"],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass

    threading.Thread(target=run, name="frame-shot", daemon=True).start()


def _place_front_window(x: int, y: int, w: int, h: int) -> None:
    """Best-effort: move/resize the frontmost window via System Events.

    Runs detached — window creation needs a moment to settle, and a failure
    (no Accessibility for osascript, an app with no settable windows) must
    never take the control loop down with it.
    """
    import subprocess
    import threading

    script = (
        'delay 0.4\n'
        'tell application "System Events"\n'
        '  set p to first process whose frontmost is true\n'
        f'  set position of front window of p to {{{x}, {y}}}\n'
        f'  set size of front window of p to {{{w}, {h}}}\n'
        'end tell'
    )

    def run() -> None:
        try:
            subprocess.run(["osascript", "-e", script], timeout=5.0,
                           capture_output=True)
        except Exception:
            pass

    threading.Thread(target=run, name="pane-place", daemon=True).start()
