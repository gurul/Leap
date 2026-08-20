"""Menu bar switch: the one-click on/off the always-on session deserves.

✋ in the menu bar = hand control running; 🤟 = paused (the icon shows the
ILY pose that resumes it); ✊ = off. The menu toggles the session (via
scripts/leapctl, the single owner of start/stop), pauses/resumes without
stopping (SIGUSR1 — the ILY pose's terminal-side twin), and opens the log.
"Turn on" starts the built-in webcam. The phone/WebRTC source moved to legacy
on 2026-08-20 — its menu item now EXPLAINS how to start it and starts nothing,
because a menu click that quietly stands up a TLS server and a signalling loop
is the background machinery this tool was stripped of (docs/decisions.md).
Built on rumps, which is a thin layer over the PyObjC we already ship.

Run it with `leapinput-menubar` (keep it in the background: `nohup ... &`).
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import rumps

LEAPCTL = str(Path(__file__).resolve().parents[2] / "scripts" / "leapctl")
RUN_DIR = Path.home() / ".leapinput"
LOG = RUN_DIR / "leapinput.log"
PID_FILE = RUN_DIR / "leapinput.pid"


def ctl(*args: str) -> str:
    try:
        out = subprocess.run([LEAPCTL, *args], capture_output=True, text=True,
                             timeout=15)
        return out.stdout.strip()
    except Exception as exc:
        return f"error: {exc}"


class LeapMenuBar(rumps.App):
    def __init__(self):
        super().__init__("✊", quit_button=None)
        self.status = rumps.MenuItem("checking…")
        self.status.set_callback(None)          # informational, not clickable
        self.toggle_item = rumps.MenuItem("Turn on", callback=self.toggle)
        # The phone/WebRTC source moved to legacy 2026-08-20: a menu item that
        # silently starts a TLS server and a signalling loop is exactly the
        # background machinery this tool was stripped of. The code is intact —
        # `leapctl on --legacy --source phone` still runs it — but it no longer
        # sits one careless click away.
        self.phone_item = rumps.MenuItem("Phone camera (legacy) — how to",
                                         callback=self.phone)
        self.pause_item = rumps.MenuItem("Pause / resume  (or hold ILY)",
                                         callback=self.pause)
        self.menu = [
            self.status, None,
            self.toggle_item, self.phone_item, self.pause_item, None,
            rumps.MenuItem("Show log", callback=self.show_log),
            rumps.MenuItem("Quit menu bar", callback=rumps.quit_application),
        ]
        self.refresh()
        rumps.Timer(self.refresh, 3).start()    # follow leapctl/pose changes

    def state(self) -> str:
        """'running', 'paused', or 'off' — parsed from `leapctl status`."""
        s = ctl("status")
        if s.startswith("running (paused"):
            return "paused"
        return "running" if s.startswith("running") else "off"

    def source(self) -> str | None:
        """Which source the live session opened, read from its own argv — a
        session started from the CLI describes itself honestly too."""
        try:
            pid = PID_FILE.read_text().strip()
            argv = subprocess.run(["ps", "-o", "command=", "-p", pid],
                                  capture_output=True, text=True,
                                  timeout=5).stdout
        except Exception:
            return None
        m = re.search(r"--source\s+(\S+)", argv)
        return m.group(1) if m else None

    def refresh(self, _=None) -> None:
        state = self.state()
        self.title = {"running": "✋", "paused": "🤟", "off": "✊"}[state]
        on_phone = state != "off" and self.source() == "phone"
        # Name the source in the status line: "ON" alone left no way to tell a
        # webcam session from a phone one without opening the log.
        where = " (phone camera)" if on_phone else ""
        self.status.title = {
            "running": f"Hand control: ON{where}",
            "paused": f"Hand control: paused{where} (hold ILY to resume)",
            "off": "Hand control: off"}[state]
        self.toggle_item.title = ("Turn on (built-in camera)" if state == "off"
                                  else "Turn off")
        self.phone_item.title = ("Phone camera (legacy) — streaming" if on_phone
                                 else "Phone camera (legacy) — how to")

    def toggle(self, _) -> None:
        if self.state() == "off":
            # Default source (built-in camera): on and tracking with zero
            # ceremony, and no server listening on the LAN. The phone/WebRTC
            # path only ever starts from its own menu item.
            ctl("on")
        else:
            ctl("off")
        self.refresh()

    def phone(self, _) -> None:
        """Legacy path: tell, do not do. Starting a LAN server from a menu
        click is the kind of background machinery this tool dropped."""
        rumps.alert("Phone camera (legacy)",
                    "The phone/WebRTC source still works, but it starts a TLS "
                    "server, a signalling loop and a token — background "
                    "machinery the four-gesture tool does not need.\n\n"
                    "To use it:\n"
                    "    scripts/leapctl on --legacy --source phone\n\n"
                    "The stream URL is printed to the session log.")

    def phone_url(self, offset: int = 0) -> str | None:
        """The session's WebRTC URL, read from the log past `offset` bytes so
        a previous session's dead token can never be handed out."""
        for _ in range(20):                     # ~10s: TLS setup is not instant
            try:
                # Binary: a byte offset from stat() is not a valid text-mode
                # seek cookie, and the log can hold partial UTF-8 mid-write.
                with LOG.open("rb") as fh:
                    fh.seek(offset)
                    tail = fh.read().decode("utf-8", "replace")
                hits = re.findall(r"https://\S+", tail)
            except OSError:
                hits = []
            if hits:
                return hits[-1]
            time.sleep(0.5)
        return None

    def pause(self, _) -> None:
        ctl("pause")                            # chime says which way it went
        time.sleep(0.3)                         # USR1 is async; let the flag land
        self.refresh()

    def show_log(self, _) -> None:
        subprocess.Popen(["open", str(LOG)])


def main() -> None:
    LeapMenuBar().run()


if __name__ == "__main__":
    main()
