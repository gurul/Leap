"""Driver layer: Intent stream -> Backend calls.

`DirectDriver` is the low-latency path — the hand *is* the cursor. A future CUA driver
consumes the same Intent stream but treats gestures as high-level commands handed to
an agent rather than as pointer motion. Both subscribe to `GestureEngine`; they are
interchangeable, and can run side by side (direct pointing, agent-dispatched swipes).
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

from .actions import Backend
from .oneeuro import OneEuroPlane
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
        gain = self._gain(math.hypot(v.x, v.y if self.map.plane == "xy" else v.z))
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

    def _on_select_down(self, event: IntentEvent) -> None:
        if self._click_anchor is not None:
            ax, ay, armed_at = self._click_anchor
            # Warp only to a FRESH, NEARBY anchor. A slow-forming pinch or a
            # second click in a row used to teleport the cursor back to a
            # position seconds old.
            if (event.at - armed_at <= self.ANCHOR_MAX_AGE_S
                    and math.hypot(self.x - ax, self.y - ay) <= self.ANCHOR_MAX_DIST_PX):
                self.x, self.y = ax, ay
                self.backend.move(self.x, self.y)
        self._down(event)

    def _on_select_up(self, event: IntentEvent) -> None:
        self._up()
        self._click_anchor = None       # every click cycle re-arms fresh

    # A fist IS the button in the finger-ladder vocabulary. These were missing
    # while the vocabulary moved off pinch, so the fist emitted grab.down into
    # nothing and the click silently did nothing at all.
    def _on_grab_down(self, event: IntentEvent) -> None:
        self._down(event)

    def _on_grab_up(self, event: IntentEvent) -> None:
        self._up()

    def _down(self, event: IntentEvent) -> None:
        self._down_pos = (self.x, self.y)
        self._travel = 0.0
        self._press(True)

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
        self._press(False)

    def _on_scroll(self, event: IntentEvent) -> None:
        self.backend.scroll(event.data.get("dy", 0.0) * self.map.scroll_gain)


class ShortcutDriver:
    """Discrete commands -> macOS actions.

    Consumes CommandEvents from commands.CommandEngine (static pose-holds — the
    replacement for the cut swipes, which carried the hand out of view). The
    cursor never moves here; these are the actions a keyboard shortcut would do.
    """

    # macOS virtual keycodes (kVK_*): ANSI N, ANSI T, up arrow.
    KEY_N, KEY_T, KEY_UP = 45, 17, 126

    def __init__(self, backend: Backend, pane_action: str = "screenshot"):
        self.backend = backend
        self.pane_action = pane_action      # "screenshot" | "window" | "tab"

    def on_command(self, event) -> None:
        name = event.command.value
        if name == "pane.new":
            self._new_pane(event.data.get("rect"))
        elif name == "mission_control":
            self.backend.key(self.KEY_UP, ctrl=True)
        # "toggle" is handled by the CLI's snapshot gate; nothing to press.

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
    """Capture the region like Cmd+Shift+4 would: PNG on the Desktop, with the
    system shutter sound as the success feedback (matters when headless)."""
    import subprocess
    import time

    path = os.path.expanduser(time.strftime(
        "~/Desktop/Frame Shot %Y-%m-%d at %H.%M.%S.png"))
    try:
        subprocess.Popen(["screencapture", f"-R{x},{y},{w},{h}", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


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
