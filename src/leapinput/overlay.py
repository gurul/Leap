"""On-screen frame overlay: the Cmd+Shift+4 feedback the finger-frame lacked.

The camera preview already draws the framed rectangle — but the always-on
session runs headless, so the user framed a region blind and only the shutter
sound proved anything happened. This module puts the rectangle on the actual
screen while the pose is held: amber while the dwell ring fills, green when
releasing will fire, with a progress bar along the bottom edge.

Two halves, one file:

  ScreenOverlay   the client the session holds. Spawns the helper below as a
                  subprocess and streams it JSON lines from the snapshot
                  thread (~30Hz). Every failure is swallowed — feedback must
                  never take down the control loop.
  __main__        the helper: a tiny AppKit app owning a transparent,
                  click-through, all-Spaces window at screen-saver level.
                  AppKit demands the process's main thread and a run loop,
                  which the session's control loop cannot give it — hence a
                  separate process rather than a thread.

The window sets sharingType = NSWindowSharingNone, so the overlay is invisible
to `screencapture`: the frame shot can never contain its own viewfinder.
(Set LEAPINPUT_OVERLAY_CAPTURABLE=1 to disable that, which is how the overlay
itself gets screenshot-tested.)

Protocol (one JSON object per line on the helper's stdin):
    {"rect": [x0, y0, x1, y1], "progress": 0.4, "done": false}   show/update
    {"rect": null}                                               hide
    EOF                                                          quit
Rect is normalized 0..1, y down from the top-left of the main screen — the
same convention as CommandEngine's overlay dict.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading


class ScreenOverlay:
    """Session-side handle. update() is called from the snapshot thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: str | None = None
        self._proc: subprocess.Popen | None = None
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "leapinput.overlay"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print(f"[overlay] helper failed to start: {exc}", file=sys.stderr)

    def update(self, overlay: dict) -> None:
        """Feed CommandEngine.overlay. Deduplicated, quantized, non-blocking-ish
        (a 60-byte line into a 64KB pipe buffer never blocks in practice)."""
        if self._proc is None or self._proc.stdin is None:
            return
        rect = overlay.get("rect")
        if rect is None:
            msg = '{"rect": null}'
        else:
            progress = round(overlay.get("progress", 0.0), 2)
            msg = json.dumps({"rect": [round(v, 3) for v in rect],
                              "progress": progress,
                              "done": progress >= 1.0})
        with self._lock:
            if msg == self._last:
                return
            self._last = msg
            try:
                self._proc.stdin.write((msg + "\n").encode())
                self._proc.stdin.flush()
            except Exception:
                # Helper died: stop trying, once, quietly. The session keeps
                # running — the overlay is feedback, not function.
                self._proc = None
                print("[overlay] helper gone; continuing without the on-screen "
                      "rectangle", file=sys.stderr)

    def close(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()          # EOF = quit
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# --- helper process ----------------------------------------------------------

def _helper_main() -> None:
    import AppKit
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyProhibited)

    screen = AppKit.NSScreen.mainScreen().frame()

    class FrameView(AppKit.NSView):
        state = None            # dict from the wire, or None

        def drawRect_(self, _dirty):
            st = self.state
            if not st or st.get("rect") is None:
                return
            x0, y0, x1, y1 = st["rect"]
            w, h = screen.size.width, screen.size.height
            # Normalized y-down -> AppKit y-up.
            r = AppKit.NSMakeRect(x0 * w, h - y1 * h,
                                  (x1 - x0) * w, (y1 - y0) * h)
            done = st.get("done", False)
            color = (AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                         0.0, 0.86, 0.20, 1.0) if done else
                     AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                         1.0, 0.78, 0.0, 1.0))
            color.colorWithAlphaComponent_(0.12).setFill()
            AppKit.NSBezierPath.fillRect_(r)
            color.setStroke()
            path = AppKit.NSBezierPath.bezierPathWithRect_(r)
            path.setLineWidth_(3.0)
            path.stroke()
            # Dwell progress along the bottom edge: the headless twin of the
            # preview's ring. Full width + green = releasing now fires.
            progress = st.get("progress", 0.0)
            if progress > 0.0:
                color.setFill()
                AppKit.NSBezierPath.fillRect_(AppKit.NSMakeRect(
                    r.origin.x, r.origin.y, r.size.width * progress, 5.0))

    window = AppKit.NSWindow.alloc() \
        .initWithContentRect_styleMask_backing_defer_(
            screen, AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered, False)
    window.setOpaque_(False)
    window.setBackgroundColor_(AppKit.NSColor.clearColor())
    window.setIgnoresMouseEvents_(True)
    window.setHasShadow_(False)
    window.setLevel_(AppKit.NSScreenSaverWindowLevel)
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
    if not os.environ.get("LEAPINPUT_OVERLAY_CAPTURABLE"):
        window.setSharingType_(AppKit.NSWindowSharingNone)
    view = FrameView.alloc().initWithFrame_(screen)
    window.setContentView_(view)
    window.orderFrontRegardless()

    def apply(state) -> None:
        view.state = state
        view.setNeedsDisplay_(True)

    def reader() -> None:
        for line in sys.stdin.buffer:
            try:
                state = json.loads(line)
            except ValueError:
                continue
            AppHelper.callAfter(apply, state)
        AppHelper.callAfter(app.terminate_, None)   # session closed the pipe

    threading.Thread(target=reader, name="overlay-stdin", daemon=True).start()
    AppHelper.runEventLoop()


if __name__ == "__main__":
    _helper_main()
