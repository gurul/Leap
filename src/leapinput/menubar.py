"""Menu bar switch: the one-click on/off the always-on session deserves.

✋ in the menu bar = hand control running; ✊ = off. The menu toggles the
session (via scripts/leapctl, the single owner of start/stop), pauses/resumes
without stopping (SIGUSR1 — the ILY pose's terminal-side twin), and opens the
log. Built on rumps, which is a thin layer over the PyObjC we already ship.

Run it with `leapinput-menubar` (keep it in the background: `nohup ... &`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import rumps

LEAPCTL = str(Path(__file__).resolve().parents[2] / "scripts" / "leapctl")
LOG = Path.home() / ".leapinput" / "leapinput.log"


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
        self.pause_item = rumps.MenuItem("Pause / resume  (or hold ILY)",
                                         callback=self.pause)
        self.menu = [
            self.status, None,
            self.toggle_item, self.pause_item, None,
            rumps.MenuItem("Show log", callback=self.show_log),
            rumps.MenuItem("Quit menu bar", callback=rumps.quit_application),
        ]
        self.refresh()
        rumps.Timer(self.refresh, 3).start()    # follow leapctl/pose changes

    def running(self) -> bool:
        return ctl("status").startswith("running")

    def refresh(self, _=None) -> None:
        on = self.running()
        self.title = "✋" if on else "✊"
        self.status.title = "Hand control: ON" if on else "Hand control: off"
        self.toggle_item.title = "Turn off" if on else "Turn on"

    def toggle(self, _) -> None:
        ctl("off" if self.running() else "on")
        self.refresh()

    def pause(self, _) -> None:
        ctl("pause")                            # chime says which way it went

    def show_log(self, _) -> None:
        subprocess.Popen(["open", str(LOG)])


def main() -> None:
    LeapMenuBar().run()


if __name__ == "__main__":
    main()
