# What is shelved, and how to bring it back

Nothing was deleted. Everything below is in the tree, wired off behind a flag.
This page is the register: what it is, the exact command, and where the
knowledge about it lives.

The *reasoning* for each 2026-08-20 move — the evidence, and what would make us
reverse it — is in [decisions.md](../decisions.md). This page is the mechanics.

---

## The master switch

```bash
leapinput --legacy
```

**The entire strip is one line** (`cli.py:442`):

```python
if args.legacy:
    engine.subscribe(direct.on_intent)
```

Without that subscription no `Intent` reaches `DirectDriver`: no pointer
motion, no mouse buttons, no clutch, no drag. The `GestureEngine` still runs —
telemetry and the command layer read its state — and every module above it is
untouched. A second gated line (`cli.py:467-470`) re-subscribes
`direct.on_command` so the free-hand fist **drag** can own the button.

`--legacy` also flips `CommandEngine(minimal=...)`, which is what restores
copy, Mission Control and the legacy free-hand routing.

---

## The register

| Shelved | Restore | Why it moved | The knowledge |
|---|---|---|---|
| **Cursor control** — pointing, clicking, the clutch, lift | `leapinput --legacy` | a mouse points better, and every expensive bug lived in the pointing path | [screen-mapping.md](screen-mapping.md), [gesture-vocabulary.md](gesture-vocabulary.md) |
| **Fist drag** (free hand and cursor hand) | `--legacy`; cursor-hand fist additionally `--drag` on camera | the drag is a mouse command; the cursor driver owns the button | [gesture-vocabulary.md](gesture-vocabulary.md#free-hand-routing-and-the-drag) |
| **Pinch-as-drag** | `--pinch-drag` | `_up()` pinned only the mouse-*up*; macOS had already been dragging for the whole hold | [decisions.md:124-138](../decisions.md) |
| **Copy** (free-hand pinch-hold → Cmd+C) | `--legacy` | Cmd+C **is** React Grab's trigger; a resting pinch would grab components nobody asked for | `commands.py:633-644` |
| **Mission Control** (OK pose → Ctrl+↑) | `--legacy` | released pinches pass through the OK shape | [gesture-vocabulary.md](gesture-vocabulary.md#poses-you-pass-through-are-not-poses) |
| **Phone / WebRTC source** (60 fps) | `scripts/leapctl on --legacy --source phone` | a TLS server, signalling loop, per-session token and aiortc receive path in service of four poses | [latency-and-pipeline.md](latency-and-pipeline.md#the-phone-path-legacy-the-median-is-physics-the-rest-is-tail) |
| **The reach box** | fitted by default under `--legacy`; `--no-reach` disables, `--reach-center fixed` pins it, `--reach-inset 0` removes the comfort inset | only affects the cursor path | [screen-mapping.md](screen-mapping.md#the-reach-box) |
| **PRISM precision** | on by default under `--legacy`; `--no-precision` or `precision_gain_min = 1.0` | only affects the cursor path | [screen-mapping.md](screen-mapping.md#prism-speed-adaptive-precision--and-the-hypothesis-it-refuted) |
| **The accuracy bench** | served at `http://127.0.0.1:8788/bench` in **any** session; scores are only meaningful with `--legacy` | measures cursor accuracy under a projection nothing now consumes | [measurement-method.md](measurement-method.md#feel-is-not-evidence--the-scored-bench) |
| **The 20 Hz detection cap** | `--detect-hz 20` | saved ~13% CPU and made the frame shot flicker | [latency-and-pipeline.md](latency-and-pipeline.md#the-detection-rate-cap-measured-well-and-reverted-anyway) |
| **The frame shadow** (guard, not a feature) | `FRAME_SHADOW_S = 0.0` disables it | — | [gesture-vocabulary.md](gesture-vocabulary.md#poses-you-pass-through-are-not-poses) |
| **Framing-fingertip smoothing** | raise `TIP_MIN_CUTOFF` for less | — | [decisions.md:189-200](../decisions.md) |
| **Leap Motion source** | `--source leap` (works, but the vocabulary above it is the minimal one unless you add `--legacy`) | the built-in webcam became the daily driver 2026-08-19 | [hand-tracking.md](hand-tracking.md#the-hardware-for-the-record) |

---

## Not shelved, though it looks like it might be

**Grab mode** works in the stripped tool: `--pane grab` gates only on the
command layer, and `ShortcutDriver._grab_component` presses Cmd+C itself on a
background thread, reads the pasteboard back, screenshots the framed region and
files a JSON record. The agent-side queue is `leapinput-grab list|next|done`.

What it *lost* is the free-hand COPY pose, so the "point at a component with a
pinch" half of the loop is gone; framing still works. Test bed: `mock-ui/`
(Vite + React with React Grab installed). Untrusted-content rules:
[safety-and-failure-modes.md](safety-and-failure-modes.md#untrusted-content-grab-modes-rule).

**The two-hand framing rect fix** (`index_tip_frame`) is live and load-bearing,
even though the reach box it corrects for is a legacy concern — the frame shot
depends on it.
([screen-mapping.md](screen-mapping.md#one-box-per-hand--so-hands-are-not-comparable-in-box-coordinates))

**`--tutorial`** still runs, and still teaches the legacy vocabulary (its first
three steps are point, pinch-to-click, fist-to-drag). It forces dry-run.

---

## What you inherit if you restore the cursor

Three verified, unfixed mechanisms producing ~2,300 px/min of uncommanded
cursor travel, plus four deferred findings from the 2026-08-19 sign-off
(MD-1, MD-3, MD-4, SI-3). None of them are theories — each was measured, and
the jitter three were each re-derived by a verifier told to refute them.

Read [screen-mapping.md#the-unfixed-list](screen-mapping.md#the-unfixed-list)
before you start, and re-run the bench with one flag at a time rather than
attributing a score to "the new mapping" as a lump.

Also: **changing camera or camera position invalidates the calibration.**
`calibrate capture` (~3 min) + `reach corners` (10 s) rebuild it entirely. The
last camera switch made every span-scaled quantity ~2× wrong. (85b7564)

---

## Restoring something not on this list

The reversal conditions are recorded per entry in
[decisions.md](../decisions.md), and the "already tried, do not re-propose"
list is [dead-ends.md](dead-ends.md). If something is on neither, the git log
is complete and nothing has been deleted from the tree — `git log --oneline`
covers 58 commits (as of 2026-08-20), and the feature commits are named for
what they did.
