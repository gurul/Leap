"""Menu bar switch: the one-click on/off the always-on session deserves.

✋ in the menu bar = hand control running; 🤟 = paused (the icon shows the
ILY pose that resumes it); ✊ = off. The menu toggles the session (via
scripts/leapctl, the single owner of start/stop), pauses/resumes without
stopping (SIGUSR1 — the ILY pose's terminal-side twin), and opens the log.
"Turn on" starts the default camera source (the built-in webcam — chosen as
the daily driver 2026-08-19). The phone/WebRTC server never starts on its
own: "Use phone camera" in the menu starts it explicitly, then puts the
session URL on the clipboard and in a dialog so it can be opened on the
device that will stream.
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
        self.phone_item = rumps.MenuItem("Use phone camera (starts server)",
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
        self.phone_item.title = ("Phone camera: streaming — show URL" if on_phone
                                 else "Use phone camera (starts server)")

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
        """Explicit opt-in to the phone/WebRTC source: start (or switch) the
        session with --source phone, then hand over the URL to open on the
        phone. Copying it beats retyping a LAN IP with a token from a dialog."""
        already = self.state() != "off" and self.source() == "phone"
        if already:
            # Already streaming: the live session's URL is the last one in the
            # log, so read the whole tail rather than waiting for a new line
            # that will never come.
            offset = 0
        else:
            if self.state() != "off":
                ctl("off")
            # Where the log ends BEFORE the start. The token is per-session, so
            # a URL from an earlier phone run is worse than none — it looks
            # valid and never connects.
            try:
                offset = LOG.stat().st_size
            except OSError:
                offset = 0
            ctl("on", "--source", "phone")
        url = self.phone_url(offset)
        self.refresh()
        if url:
            subprocess.run(["pbcopy"], input=url, text=True, timeout=5)
            rumps.alert("Phone camera ready",
                        f"Open this on the phone (copied to the clipboard):\n\n"
                        f"{url}\n\nAccept the certificate warning once, "
                        f"then tap Start.")
        else:
            rumps.alert("Phone camera",
                        "No stream URL in the log yet — open Show log in a "
                        "moment to see how startup went.")

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
