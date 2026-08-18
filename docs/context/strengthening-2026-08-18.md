# The 2026-08-18 strengthening pass

A multi-agent assessment of this repo against [mediapipe-touchdesigner](https://github.com/torinmb/mediapipe-touchdesigner) — an installation-grade MediaPipe integration whose robustness patterns are battle-tested in live art — plus a survey of shipping mid-air UI vocabularies (Quest, Vision Pro, Ultraleap TouchFree, Project Gameface). The assessment found the architecture sound and the *integration seams* broken: five root causes made real control feel arbitrary. All are fixed and pinned by tests.

## The five root causes

1. **Drags were structurally frozen.** The click-settle factor was recomputed from raw pinch distance on every move frame and multiplied into pointer gain. A held pinch (~15 pseudo-mm) and a fist (~18) both sit below `settle_full` for their whole duration, so gain went to exactly 0 the moment the button latched — pinch-drag, fist-drag, text selection and window moves all silently froze, while the README promised the opposite. Fix: settle returns 1.0 once either button is latched, and the freeze band now *completes at the firing threshold* (`settle_full == pinch_on`), so mouse-down posts on a stopped cursor instead of at ~71% gain. `test_a_fist_drag_moves_the_real_cursor` replays the 444-fist-frame corpus through the actual driver and asserts nonzero displacement.

2. **Slow precise motion was discarded and lagged.** The deadzone advanced its anchor before the threshold check, permanently eating any motion under ~18 mm/s — precisely the speed of final target approach. And the camera path shipped a 0.3 Hz 1€ floor: ~530 ms of group delay at slow speed, the "syrup then overshoot" mode `docs/plan.md` explicitly warned about. Fix: the deadzone accumulates against a held anchor (tremor still nets to zero — `test_alternating_noise_nets_to_nothing`), the floor is 1.5 Hz with beta 0.03 and `d_cutoff` 2.0, and the virtual plane is isotropic (`PLANE_Y_MM = PLANE_X_MM * 480/640`; it was ~25% hotter vertically).

3. **Clicks teleported and drifted.** The Heisenberg click-anchor survived `select_up`, so a second quick click warped back to the first click's position, seconds stale. Fix: the anchor dies with its click and is trusted only fresh (≤0.75 s) and nearby (≤75 px). Mouse-up on a click (<12 px of held-button travel) is pinned to the down pixel, because macOS resolves the click target on *up*. The driver also seeds from `CGEventGetLocation` and re-syncs on every clutch, so trackpad use between clutches no longer teleports; clamping is to the *nearest display rect*, not the union (whose L-shaped void could strand the cursor); and `kCGMouseEventClickState` is set on both events, so two quick pinches are a real double-click.

4. **The camera source trusted per-frame classifier noise and froze time on dropouts.** MediaPipe's handedness label flaps on fists and pinches; each flap made the configured hand vanish, and >150 ms of flap released everything mid-drag. Fix: one visible hand + a configured `--hand` = that hand, whatever the label says (`resolve_side`); the detector runs `num_hands=1` for cursor-only use with the three confidences explicit (the mediapipe-touchdesigner pattern — minimal hands, tunables surfaced). Dropout holds are re-stamped with the current time and zero velocity, so pending dwells complete during a dropout instead of stalling the engine clock. Capture timestamps mark `cap.read()` return, the buffer is drained when detection falls behind, and `source.stats` (fps / detect-ms / realtime) surfaces in the preview so lag is visible instead of mysterious.

5. **Shipped configuration lied.** The CLI clobbered the measured `invert_x=True` Leap default with argparse's `store_true` False on every default run, and `--no-clutch` — the advertised stuck-cursor escape hatch — was dead code in the default finger mode. Fix: `resolve_source_defaults` resolves axis flags per source only when the user didn't pass them, and the bypass check now precedes the mode dispatch.

Also: a closing fist can no longer *start* a pinch latch (raw count 0 blocks new pinches; corpus: fist reads count 0 on 541/542 camera frames while a held pinch reads 1–2), and a pinch closing into a fist hands the button over silently — no release mid-gesture.

## The command layer (new)

`commands.py` adds discrete commands as **static pose-holds with fire-on-release** — the shape every shipping mid-air vocabulary converged on (Quest's system gesture, TouchFree's Hover & Hold; 800 ms dwell measured 0% selection errors in the ISS 2022 mid-air study). Swipes stay cut; nothing here can carry the hand out of frame.

| pose | hold | action |
|---|---|---|
| both hands framing a rectangle (thumb+index Ls) | ~0.8 s | **frame shot**: screenshot of the framed region to the Desktop, with the system shutter sound (`--pane window` places a `Cmd+N` window over the region instead; `--pane tab` for `Cmd+T`) |
| OK sign — pinch with middle+ring+pinky extended | ~0.6 s | Mission Control (`Ctrl+↑`) |
| ILY sign — thumb+index+pinky | ~1.65 s | pause / resume all gesture control |

Design rules, from the research: a pose must persist 0.15 s before the progress ring starts (single-frame label flicker never arms), sub-0.12 s dropouts don't cancel a hold, and release commits — holding past full keeps the abort window open. The preview draws the ring, the armed label, and the live pane rectangle. While a hold is armed the cursor engine receives an empty snapshot: framing a pane cannot also steer the pointer, and resume is jump-free because every clutch re-syncs from the real cursor.

The two-hand pane requires `num_hands=2` (`two_hands=True`); the ILY toggle still listens while paused — it is the way back in.

`--tutorial` (tutorial.py) is the visual test harness for all of it: a guided practice room over the preview that steps through the whole vocabulary and only advances when the real pipeline detects the real gesture. It forces dry-run — completing it is the end-to-end verification, with zero risk to the actual cursor.

## The depth gate (evaluated: TDDepthAnything)

[TDDepthAnything](https://github.com/TouchDesigner/TDDepthAnything) was assessed for restoring a Z axis: rejected as a dependency (PyTorch + ~tens of ms/frame against a 30 fps budget, relative-not-metric output). The one benefit it would buy is had for free: **image-space knuckle span scales with 1/distance** while world span stays hand-sized, so `MIN_SPAN_IMG` (0.04 ≈ beyond ~1.2 m) rejects background people and out-of-range hands with zero model cost.

## Verification

149 hardware-free tests (was 107), including: driver-level corpus replay for drags, deadzone accumulation vs. tremor, 1€ lag bounds at the camera operating point, click-anchor lifecycle, label-flap immunity, dwell completion through dropouts, nearest-rect containment (void grid), click-state sequences, CLI default resolution, pose-hold semantics, and the span gate. Live checks still owed on real hardware: pinch-drag a window, trackpad-interleave then re-point, double-pinch a Finder folder, frame a pane.
