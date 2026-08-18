"""Action layer: how we actually touch the machine.

`Backend` is the seam. `QuartzBackend` drives macOS for real; `DryRunBackend` prints
what would have happened. Develop gesture thresholds against DryRun — a half-tuned
Schmitt trigger wired to the real cursor will fight you for control of the machine
you are using to fix it.
"""

from __future__ import annotations

import sys
import time
from typing import Protocol


class Backend(Protocol):
    def move(self, x: float, y: float) -> None: ...
    @property
    def bounds(self) -> tuple[float, float, float, float]: ...
    @property
    def rects(self) -> list[tuple[float, float, float, float]]: ...
    def pos(self) -> tuple[float, float]: ...
    def down(self, x: float, y: float) -> None: ...
    def up(self, x: float, y: float) -> None: ...
    def scroll(self, dy: float) -> None: ...
    def key(self, keycode: int, *, cmd=False, shift=False, alt=False, ctrl=False) -> None: ...
    def key_hold(self, keycode: int, down: bool, *, alt=False) -> None: ...
    @property
    def screen(self) -> tuple[float, float]: ...


# macOS builds double- and triple-clicks from the click-state FIELD on the
# events, not from timing alone: two down/up pairs posted without it are two
# single clicks no matter how fast. 0.5s / 25px mirror the system defaults.
def next_click_state(prev_state: int, prev_up_at: float | None,
                     prev_xy: tuple[float, float] | None,
                     now: float, xy: tuple[float, float]) -> int:
    if prev_up_at is None or prev_xy is None:
        return 1
    dx, dy = xy[0] - prev_xy[0], xy[1] - prev_xy[1]
    if now - prev_up_at < 0.5 and dx * dx + dy * dy <= 25.0 * 25.0:
        return prev_state + 1
    return 1


class DryRunBackend:
    """Logs instead of acting. The default, deliberately."""

    def __init__(self, screen: tuple[float, float] = (1512.0, 982.0),
                 bounds: tuple[float, float, float, float] | None = None,
                 verbose: bool = False):
        self._screen = screen
        self._bounds = bounds or (0.0, 0.0, screen[0], screen[1])
        self._pos = (screen[0] / 2.0, screen[1] / 2.0)
        self.verbose = verbose
        self.calls: list[tuple] = []

    @property
    def screen(self) -> tuple[float, float]:
        return self._screen

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self._bounds

    @property
    def rects(self) -> list[tuple[float, float, float, float]]:
        return [self._bounds]

    def pos(self) -> tuple[float, float]:
        """Where the cursor 'is': the last point moved to, seeded at center."""
        return self._pos

    def _record(self, *call) -> None:
        self.calls.append(call)
        if self.verbose or call[0] != "move":
            print(f"  [dry-run] {call[0]}{call[1:]}", file=sys.stderr)

    def move(self, x, y): self._pos = (x, y); self._record("move", round(x), round(y))
    def down(self, x, y): self._pos = (x, y); self._record("down", round(x), round(y))
    def up(self, x, y): self._pos = (x, y); self._record("up", round(x), round(y))
    def scroll(self, dy): self._record("scroll", round(dy))
    def key(self, keycode, **mods): self._record("key", keycode, mods)
    def key_hold(self, keycode, down, **mods): self._record("key_hold", keycode, down, mods)


class QuartzBackend:
    """Synthetic input via CoreGraphics. Requires Accessibility permission.

    Without that permission CGEventPost returns no error and silently does nothing,
    so the constructor checks up front rather than letting you debug a dead cursor.
    """

    def __init__(self, *, require_permission: bool = True):
        from Quartz.CoreGraphics import (
            CGEventCreateMouseEvent, CGEventCreateScrollWheelEvent,
            CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
            CGEventCreate, CGEventGetLocation, CGEventSetIntegerValueField,
            kCGMouseEventClickState,
            kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
            kCGEventLeftMouseDragged, kCGMouseButtonLeft, kCGHIDEventTap,
            kCGScrollEventUnitPixel, kCGEventFlagMaskCommand, kCGEventFlagMaskShift,
            kCGEventFlagMaskAlternate, kCGEventFlagMaskControl,
            CGEventSourceCreate, kCGEventSourceStateHIDSystemState,
        )
        from Quartz.CoreGraphics import (
            CGGetActiveDisplayList, CGDisplayBounds, CGMainDisplayID,
        )
        from ApplicationServices import AXIsProcessTrusted

        if require_permission and not AXIsProcessTrusted():
            raise PermissionError(
                "No Accessibility permission — synthetic events would be silently "
                "dropped. Grant it to this process's parent application in "
                "System Settings > Privacy & Security > Accessibility."
            )

        self._cg = dict(
            mouse=CGEventCreateMouseEvent, scroll=CGEventCreateScrollWheelEvent,
            keyboard=CGEventCreateKeyboardEvent, post=CGEventPost, flags=CGEventSetFlags,
            moved=kCGEventMouseMoved, ldown=kCGEventLeftMouseDown, lup=kCGEventLeftMouseUp,
            ldrag=kCGEventLeftMouseDragged, button=kCGMouseButtonLeft, tap=kCGHIDEventTap,
            pixel=kCGScrollEventUnitPixel,
            create=CGEventCreate, location=CGEventGetLocation,
            set_field=CGEventSetIntegerValueField, click_state=kCGMouseEventClickState,
        )
        self._mods = dict(
            cmd=kCGEventFlagMaskCommand, shift=kCGEventFlagMaskShift,
            alt=kCGEventFlagMaskAlternate, ctrl=kCGEventFlagMaskControl,
        )
        # For key_hold only: a real HID event source. Events built with a NULL
        # source carry no keyboard state, and apps watching for a *held*
        # modifier (dictation) drop them. Plain taps keep the NULL source —
        # with a real one, some apps' global handlers swallow the key before
        # it reaches the focused app (both learned the hard way in claude-pet).
        try:
            self._hid_src = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
        except Exception:
            self._hid_src = None
        # Geometry comes from CGDisplayBounds, NOT NSScreen.
        #
        # They disagree, and only one matches the coordinate space CGEventPost
        # actually uses. CG global space has its origin at the top-left of the main
        # display with y increasing DOWNWARD; NSScreen uses bottom-left with y up.
        # Measured on this machine: the second display is at CG (-541,-1440) but
        # NSScreen calls it (-541,+982). Feeding NSScreen numbers to CGEventPost
        # puts the cursor in the wrong place on any multi-display layout.
        main = CGDisplayBounds(CGMainDisplayID())
        self._screen = (float(main.size.width), float(main.size.height))

        err, ids, count = CGGetActiveDisplayList(16, None, None)
        rects = [CGDisplayBounds(d) for d in ids[:count]] if not err else [main]
        # Per-display rects, not just the union: an L-shaped layout has a VOID
        # inside the union rectangle, and clamping into it strands the cursor
        # in unreachable space. The driver clamps to the nearest real display.
        self._rects = [
            (float(r.origin.x), float(r.origin.y),
             float(r.origin.x + r.size.width), float(r.origin.y + r.size.height))
            for r in rects
        ]
        self._bounds = (
            min(r[0] for r in self._rects),
            min(r[1] for r in self._rects),
            max(r[2] for r in self._rects),
            max(r[3] for r in self._rects),
        )
        self._down = False
        # Double/triple-click bookkeeping for kCGMouseEventClickState.
        self._click_state = 1
        self._last_up_at: float | None = None
        self._last_up_xy: tuple[float, float] | None = None

    @property
    def screen(self) -> tuple[float, float]:
        return self._screen

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Union of every active display, in CG global coordinates.

        Displays above or left of the main one have NEGATIVE origins, so clamping
        to (0,0,w,h) silently traps the cursor on the main display — which is
        exactly what it did before this existed.
        """
        return self._bounds

    @property
    def rects(self) -> list[tuple[float, float, float, float]]:
        return list(self._rects)

    def pos(self) -> tuple[float, float]:
        """Where the cursor ACTUALLY is, from the window server — the user may
        have moved it with the trackpad since we last did."""
        p = self._cg["location"](self._cg["create"](None))
        return (float(p.x), float(p.y))

    def _mouse(self, event_type, x, y, click_state: int | None = None) -> None:
        cg = self._cg
        event = cg["mouse"](None, event_type, (x, y), cg["button"])
        if click_state is not None and click_state > 1:
            # Without this FIELD, two fast clicks are two single clicks: macOS
            # builds double/triple-clicks from click state, not timing alone.
            cg["set_field"](event, cg["click_state"], click_state)
        cg["post"](cg["tap"], event)

    def move(self, x, y) -> None:
        self._mouse(self._cg["ldrag"] if self._down else self._cg["moved"], x, y)

    def down(self, x, y) -> None:
        self._click_state = next_click_state(
            self._click_state, self._last_up_at, self._last_up_xy,
            time.monotonic(), (x, y))
        self._down = True
        self._mouse(self._cg["ldown"], x, y, self._click_state)

    def up(self, x, y) -> None:
        self._down = False
        # Same click state on BOTH events of the pair, or the up cancels it.
        self._mouse(self._cg["lup"], x, y, self._click_state)
        self._last_up_at = time.monotonic()
        self._last_up_xy = (x, y)

    def scroll(self, dy) -> None:
        cg = self._cg
        cg["post"](cg["tap"], cg["scroll"](None, cg["pixel"], 1, int(dy)))

    def key(self, keycode, **mods) -> None:
        cg = self._cg
        flags = 0
        for name, on in mods.items():
            if on:
                flags |= self._mods[name]
        for pressed in (True, False):
            event = cg["keyboard"](None, keycode, pressed)
            if flags:
                cg["flags"](event, flags)
            cg["post"](cg["tap"], event)

    def key_hold(self, keycode, down, *, alt=False) -> None:
        """One edge of a held key (down=True presses, down=False releases).

        Flags describe the modifier state AFTER the event, so the press
        asserts the modifier mask and the release ALWAYS clears it — an up
        event still asserting alternate tells macOS the key is still held,
        and it sticks down system-wide (claude-pet shipped that bug once)."""
        cg = self._cg
        event = cg["keyboard"](self._hid_src, keycode, down)
        cg["flags"](event, self._mods["alt"] if (down and alt) else 0)
        cg["post"](cg["tap"], event)


def make_backend(name: str, **kwargs) -> Backend:
    if name == "quartz":
        return QuartzBackend(**kwargs)
    if name == "dry-run":
        return DryRunBackend(**kwargs)
    raise ValueError(f"unknown backend {name!r} (expected 'quartz' or 'dry-run')")
