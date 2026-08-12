"""Action layer: how we actually touch the machine.

`Backend` is the seam. `QuartzBackend` drives macOS for real; `DryRunBackend` prints
what would have happened. Develop gesture thresholds against DryRun — a half-tuned
Schmitt trigger wired to the real cursor will fight you for control of the machine
you are using to fix it.
"""

from __future__ import annotations

import sys
from typing import Protocol


class Backend(Protocol):
    def move(self, x: float, y: float) -> None: ...
    @property
    def bounds(self) -> tuple[float, float, float, float]: ...
    def down(self, x: float, y: float) -> None: ...
    def up(self, x: float, y: float) -> None: ...
    def scroll(self, dy: float) -> None: ...
    def key(self, keycode: int, *, cmd=False, shift=False, alt=False, ctrl=False) -> None: ...
    @property
    def screen(self) -> tuple[float, float]: ...


class DryRunBackend:
    """Logs instead of acting. The default, deliberately."""

    def __init__(self, screen: tuple[float, float] = (1512.0, 982.0),
                 bounds: tuple[float, float, float, float] | None = None,
                 verbose: bool = False):
        self._screen = screen
        self._bounds = bounds or (0.0, 0.0, screen[0], screen[1])
        self.verbose = verbose
        self.calls: list[tuple] = []

    @property
    def screen(self) -> tuple[float, float]:
        return self._screen

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self._bounds

    def _record(self, *call) -> None:
        self.calls.append(call)
        if self.verbose or call[0] != "move":
            print(f"  [dry-run] {call[0]}{call[1:]}", file=sys.stderr)

    def move(self, x, y): self._record("move", round(x), round(y))
    def down(self, x, y): self._record("down", round(x), round(y))
    def up(self, x, y): self._record("up", round(x), round(y))
    def scroll(self, dy): self._record("scroll", round(dy))
    def key(self, keycode, **mods): self._record("key", keycode, mods)


class QuartzBackend:
    """Synthetic input via CoreGraphics. Requires Accessibility permission.

    Without that permission CGEventPost returns no error and silently does nothing,
    so the constructor checks up front rather than letting you debug a dead cursor.
    """

    def __init__(self, *, require_permission: bool = True):
        from Quartz.CoreGraphics import (
            CGEventCreateMouseEvent, CGEventCreateScrollWheelEvent,
            CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
            kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
            kCGEventLeftMouseDragged, kCGMouseButtonLeft, kCGHIDEventTap,
            kCGScrollEventUnitPixel, kCGEventFlagMaskCommand, kCGEventFlagMaskShift,
            kCGEventFlagMaskAlternate, kCGEventFlagMaskControl,
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
        )
        self._mods = dict(
            cmd=kCGEventFlagMaskCommand, shift=kCGEventFlagMaskShift,
            alt=kCGEventFlagMaskAlternate, ctrl=kCGEventFlagMaskControl,
        )
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
        self._bounds = (
            min(float(r.origin.x) for r in rects),
            min(float(r.origin.y) for r in rects),
            max(float(r.origin.x + r.size.width) for r in rects),
            max(float(r.origin.y + r.size.height) for r in rects),
        )
        self._down = False

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

    def _mouse(self, event_type, x, y) -> None:
        cg = self._cg
        cg["post"](cg["tap"], cg["mouse"](None, event_type, (x, y), cg["button"]))

    def move(self, x, y) -> None:
        self._mouse(self._cg["ldrag"] if self._down else self._cg["moved"], x, y)

    def down(self, x, y) -> None:
        self._down = True
        self._mouse(self._cg["ldown"], x, y)

    def up(self, x, y) -> None:
        self._down = False
        self._mouse(self._cg["lup"], x, y)

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


def make_backend(name: str, **kwargs) -> Backend:
    if name == "quartz":
        return QuartzBackend(**kwargs)
    if name == "dry-run":
        return DryRunBackend(**kwargs)
    raise ValueError(f"unknown backend {name!r} (expected 'quartz' or 'dry-run')")
