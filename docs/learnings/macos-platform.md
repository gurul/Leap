# macOS platform lore

None of this is gesture knowledge, and all of it is expensive to re-derive.
Coordinate spaces, event injection, permission attribution, and the two ways
this process's signal handlers get clobbered behind Python's back.

---

## Screen geometry: `CGDisplayBounds` only, never `NSScreen`

They disagree, and only one matches the space `CGEventPost` uses.

- CG global space: origin at the **top-left of the main display**, y increasing
  **downward**.
- NSScreen: bottom-left, y up.

Measured on this machine: the second display sits at CG `(−541, −1440)` but
NSScreen calls it `(−541, +982)`.

Two bugs hid in this. The cursor was clamped to the main display only; and a
monitor placed **above or left has negative CG coordinates**, so it was
unreachable by construction. Feeding NSScreen numbers to `CGEventPost` is wrong
on any multi-display layout. (02a08a1, `actions.py:165-196`)

**Clamp to the nearest display rect, not the union.** An L-shaped layout has a
void *inside* its union rectangle, and clamping into the union strands the
cursor in unreachable space. `QuartzBackend` exposes per-display rects via
`CGGetActiveDisplayList`. (`driver.py:236-247`)

**Open, unfixed (SI-3):** display geometry is cached once at init, so a
mid-session display change clamps into stale rects.

---

## Event injection

**macOS builds double and triple clicks from a field, not from timing.** Two
down/up pairs posted without `kCGMouseEventClickState` are two single clicks no
matter how fast. `next_click_state` mirrors the system defaults (0.5 s, 25 px),
and the same click state must be set on **both** events of the pair or the up
cancels it. (`actions.py:48-59, 222-246`)

**macOS resolves the click target on mouse-UP.** So a release with <12 px of
held-button travel is pinned back to the down pixel. (`driver.py:534-545`)

**HID event source for held keys, NULL event source for plain taps.** Both
learned the hard way:

- Events built with a NULL source carry no keyboard state, and apps watching
  for a **held** modifier (dictation) drop them — so `key_hold` uses
  `CGEventSourceCreate(kCGEventSourceStateHIDSystemState)`.
- But plain taps must keep the NULL source: with a real HID source, some
  terminals' global key handling swallows Return before it reaches the focused
  app (measured in Warp).
- Third rule: **flags describe the state after the event**, so a release must
  *always* clear the modifier mask. An up event still asserting `alternate`
  tells macOS the key is still held, and it sticks down system-wide.

(`actions.py:157-163, 264-274`, `driver.py:598-612`)

**`fn` cannot be synthesized; Option can.** Apps that read `fn` (Willow Voice's
stock push-to-talk key) take it straight from raw HID, so a synthesized `fn` is
simply not seen. Option synthesizes reliably — which is why dictation is bound
to a **bare Option hold** (`KEY_OPTION = 58`) and why Willow must be rebound to
match. (`driver.py:607-612`)

`kCGAnnotatedSessionEventTap` does not move the pointer.
([plan.md §8](../plan.md))

---

## Permissions are attributed to the process tree, and fail silently

**macOS grants Camera to the app responsible for the process tree**, not to the
process that opens the device. A session started from the menu bar is a
grandchild of `~/Applications/Leap Menubar.app`, so that bundle is what System
Settings lists — and its `Info.plist` **must declare
`NSCameraUsageDescription`** or macOS refuses the request **outright** instead
of prompting.

Nothing raises. OpenCV logs one line —

```
OpenCV: not authorized to capture video (status 0), requesting...
```

— and `cap.read()` then fails forever, so "Turn on" started a session that
opened a camera which never delivered a frame.

The wrapper existed only in `~/Applications`, which is why this was unfixable
from the repo. `install-menubar-app.sh` now **builds** it — usage string,
ad-hoc signature and all — and `menubar-launcher.c` documents why the main
executable has to be a Mach-O rather than a shell script.

**Editing the bundle changes its ad-hoc signature, which invalidates existing
grants.** Expect to re-approve after any rebuild:

```bash
scripts/install-menubar-app.sh --restart
tccutil reset Camera world.era.leapinput.menubar   # forces the prompt back
```

**A CLI run is a different grantee** (your terminal), which is why
`leapctl on` from a terminal can work on the same machine where the menu bar
switch does nothing. (2a16f35,
[troubleshooting.md:16-48](../troubleshooting.md))

Sibling rules: **Accessibility** failures are also silent — `CGEventPost`
returns no error and does nothing — so the CLI gates on `AXIsProcessTrusted()`
and refuses to start. **Screen Recording** failures kill `screencapture` with
"could not create image from rect", so the frame shot now chimes Basso and logs
the fix.

---

## This process's signal handlers get clobbered — twice, two different ways

**1. Inherited `SIG_IGN`.** `leapctl on` launches the session via
`nohup ... &` from a non-interactive shell, which hands it SIGINT as `SIG_IGN`
— and **Python honors an inherited ignore**. So `leapctl off` did nothing and
the session (and the camera light) outlived the switch.

**2. Something in camera/mediapipe startup resets SIGUSR1's `sigaction` to
`SIG_IGN` behind Python's back.** Verified by reading `sigaction` from the
**live** process, where the OS said `SIG_IGN` while Python still showed the
handler. That silently killed `leapctl pause` and the menu bar pause.

The cure for both: `signal.signal()` always overwrites the OS disposition, so
handlers are **re-asserted every 2 seconds** from the main loop. At a few
syscalls per second it is free. (`cli.py:544-579`)

---

## Two shell traps that repeatedly read as "the code hangs"

**Backgrounded processes never receive SIGINT here.** Running `cmd &` from a
**non-interactive** shell — which is what tool-driven shells are — sets SIGINT
to `SIG_IGN` and the child inherits it. `kill -INT <pid>` then does nothing and
the process looks hung. This has nothing to do with Leap; a bare
`time.sleep(30)` script behaves identically. Do **not** conclude "the shutdown
path hangs" from this.

**Redirected stdout is block-buffered.** `python -m leapinput.cli > log 2>&1`
shows nothing until the buffer flushes, which reads as "it hung before
printing". Use `python -u`.

To actually diagnose: `PYTHONFAULTHANDLER=1` and `kill -ABRT <pid>` dumps every
thread's stack. For reference, the CLI exits cleanly on a genuine SIGINT
(`rc=0`, teardown in ~0.01 s), and `Connection.close()` measures 0.01 s — if
teardown appears to block, suspect the harness first.
([testing.md:25-52](../context/testing.md), verified 2026-08-12)

---

## The overlay must be invisible to `screencapture`

The always-on session is headless, so the user framed a region blind and only
the shutter sound proved anything happened. The frame overlay is a **separate
process** — AppKit demands the process's main thread and a run loop, which the
control loop cannot give it — owning a transparent, click-through, all-Spaces
window at `NSScreenSaverWindowLevel`, fed one JSON line per update over stdin
at ~30 Hz.

It sets `sharingType = NSWindowSharingNone`, so the frame shot can never
contain its own viewfinder. `LEAPINPUT_OVERLAY_CAPTURABLE=1` is the escape
hatch that lets the overlay itself be screenshot-tested. (`overlay.py:1-32,
156-157`)

---

## Measured platform costs, for sizing decisions

From the 2026-08-12 probe pass ([plan.md §8](../plan.md)):

| | |
|---|---|
| `CGEventPost` | 10.4 µs/post (93,930/s) |
| AX attribute read | median 0.026 ms; 0.64 ms/node warm |
| `pyautogui.moveTo` | 12.84 ms — a 76 Hz ceiling |
| `osascript keystroke` | 100–140 ms |

Also measured and worth knowing if the Leap path is revived:
`LEAP_HAND.flags` is always 0 across 2,419 hand-frames, and
`LeapCheckLicenseFlag` returns `enabled=True` for
`"zzz_not_a_real_flag_12345"`.
