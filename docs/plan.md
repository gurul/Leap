# Leap Gesture → macOS Computer Use — Build Plan (FINAL)

**Target:** this MacBook Pro (M5 Pro, macOS 26.5.2 / 25F84, arm64), this controller (original 2013 LMC, `LP20006680004`, type `LMC`, PID `0x3`), Hyperion 6.2.0.0, `libLeapC.6.dylib`.

**What changed from the draft plan, in one paragraph.** Pointer control is **relative with a clutch ratchet**, not absolute — the draft specified both and they are mutually exclusive. The `VirtualScreen` port is deleted and the union-rect mapping problem with it. The clutch is a **palm-orientation** pose, digit-disjoint from every click, because the draft's peace-sign clutch shared fingers with its own click gesture. **AirPush is the primary click and pinch is the fallback** — the ranking was inverted; pinch is model-inferred exactly where thumb and index occlude. **Swipes and the fist-disengage are cut** (swipe exits the tracking volume and trips the dead-man; fist-disengage collides with scroll). Scroll is **position control from an anchor**, not rate control. A **panic/release-all path with an external supervisor** is Phase 0, not an afterthought — it is the only uncovered failure class in the draft. The **agent tier is descoped to a socket seam**. TouchFree is reclassified **REFERENCE, not ADOPT**. A **concurrency model** is specified, because five components each demand a run loop and the draft assigned none.

---

## 1. Architecture

Six layers plus a supervisor and a test harness. Data flows one way; every layer has a typed boundary so any layer replays in isolation.

```
                    ┌─ GUARD (separate process) ──────────────┐
                    │ pipe-EOF watch → release-all            │  WRITE ~150 LOC
                    │ panic hotkey (registered OUTSIDE app)   │  Phase 0
                    └─────────────────────────────────────────┘
 ┌─ L0 CAPTURE ─────────────────────────────────────────────────┐
 │ Source protocol: {LeapCFFISource | LeapCtypesSource |         │  ADOPT (upstream, vendored)
 │                   ReplaySource}                               │  + adapter WRITE ~150 LOC
 │   → HandFrame (raw, LeapC clock domain, hand-id bound)        │
 └──────────────────────────┬───────────────────────────────────┘
                            │  TWO TAPS, index-aligned (see §7 R12)
        ┌───────────────────┴────────────────────┐
        ▼ filtered (cursor)                       ▼ raw (recognition)
 ┌─ L1 CONDITION ──────────┐            ┌─ L2 RECOGNIZE ──────────────────┐
 │ 1€ filter (VENDORED,     │  WRITE    │ ONE exclusive-state FSM:        │  WRITE
 │  bugs fixed, vectorised) │  ~90 LOC  │ IDLE|POINT|DRAG|SCROLL|COMMIT   │  ~700 LOC
 │ gain curve · deadzone    │           │ force accumulator · Schmitt ·   │
 │ cursor integrator        │           │ pose matcher · progress timer   │
 └──────────┬───────────────┘           └──────────────┬──────────────────┘
            └──────────────┬─────────────────────────────┘
                           ▼
 ┌─ L3 INTENT ──────────────────────────────────────────────────┐
 │ typed intent bus · gate machine · deadman · policy deny-list   │  WRITE ~500 LOC
 │ + Unix-socket publish seam (the ONLY external coupling)        │
 └──────────────────────────┬───────────────────────────────────┘
       ┌───────────────────┼────────────────────┐
       ▼ continuous         ▼ discrete            ▼ presentation
 ┌─ L4a CGEvent ─────┐ ┌─ L4b AX / AS ─────┐ ┌─ L5 HUD ───────────────┐
 │ pyobjc Quartz     │ │ pyobjc AppServices│ │ NSStatusItem +          │
 │ WRITE ~250 LOC    │ │ WRITE ~350 LOC    │ │ overlay progress ring   │  WRITE ~250 LOC
 │ (frame thread)    │ │ (worker thread)   │ │ (main thread, AppKit)   │
 └───────────────────┘ └───────────────────┘ └─────────────────────────┘
```

### Layer-by-layer decisions

| Layer | Choice | Verdict | Why |
|---|---|---|---|
| **L0 Capture** | `ultraleap/leapc-python-bindings` **upstream**, vendored, editable-installed, + the SDK's bundled `leapc_cffi` | **ADOPT** | Verified running on this hardware at 111 fps, 9.03 ms median interval, p95 9.46 ms, zero drops. We take **upstream, not the `DDlabAU` fork** — the fork's entire delta is 2 string literals in CFFI *build* scripts our prebuilt path never executes. A fork whose delta you bypass is pure supply-chain liability. |
| **L0 second backend** | `LeapCtypesSource` — direct `ctypes` binding of `libLeapC.6.dylib` | **WRITE, spike in week 1** | The 3.12 pin is **self-imposed**: it exists only because we use the prebuilt ABI-mode CFFI `.so`. `libLeapC.6.dylib` is a plain C library; `ctypes` binds it from any CPython with no build step. This deletes the "CPython 3.12 will break" risk outright rather than mitigating it. Honest cost: ~350 LOC of struct/union definitions for the subset we need (`LEAP_CONNECTION`, poll, `LEAP_TRACKING_EVENT`, `LEAP_HAND`, `LEAP_DIGIT`, `LEAP_BONE`), and struct layout must match `LeapC.h` byte-for-byte — validated by asserting known-good frames from the CFFI path against the ctypes path in the replay harness. Not on the Phase 0 critical path. |
| **L0 adapter** | `capture/frame.py` — `HandFrame` dataclass | **WRITE ~150 LOC** | Normalise once: drop `hand.confidence` (`LeapC.h`: *"Not currently used (always 1.0)"*), drop `hand.flags` (dead, §2), carry `visible_time`, carry `hand.id` for driver binding, and stamp **one canonical clock** (§7 R11). |
| **L1 1€ filter** | **Vendor** `casiez/OneEuroFilter` math into `condition/oneeuro.py` | **WRITE ~90 LOC** | We had already documented two bugs and a limitation in PyPI `OneEuroFilter==0.2.1` (falsy-`0.0` timestamp silently skips the frequency update; `reset()` does not restore the constructor frequency; scalar-only). It is ~40 lines of BSD-3 math. Carrying a dependency we work around twice is worse than owning it. Ships with a test against the project's own cross-language ground truth (draft measured max deviation 2.45e-05). |
| **L1 Deadzone, gain, integrator** | `condition/pointer.py` — clutch-anchored relative integrator, non-linear CD gain, growing deadzone | **WRITE ~180 LOC** | Replaces the `VirtualScreen.cs` port entirely. We keep TouchFree's *idea* of a deadzone that grows during click progress (3 mm → 20 mm) so the cursor cannot drift off target mid-commit; the absolute-mapping machinery around it is not needed. |
| **L2 Recognition** | `recognize/` — one exclusive-state FSM. Structure informed by TouchFree `Interactions/` and UnityPlugin `HandPoseDetector`; **every constant derived from our own corpus** | **WRITE ~700 LOC (REFERENCE, not port)** | See §2 and §7 R14. TouchFree is archived, has no macOS target, ships `libLeapC.so.5`, its `PositionFilter.cs` is a fake 1€ filter, its production flags all default to `false`, and its constants were tuned for kiosk-distance Gemini hardware. We read it for the **shape** of the algorithms (force accumulator, progress timer, hysteresis) and throw away the numbers. We do **not** port `TouchFreeTests` — they are NUnit fixtures over `System.Numerics`/Unity types and were never verified extractable. |
| **L3 Intent** | `intent/` — typed bus, gate FSM, deadman, policy deny-list, Unix-socket publisher | **WRITE ~500 LOC** | Nothing exists. Confirmed across three independent surveys; prior art is academic only. |
| **L4a Injection (continuous)** | `inject/quartz.py` over `pyobjc-framework-Quartz==12.2.2` | **WRITE ~250 LOC** | Justified below. |
| **L4b Injection (discrete)** | `pyobjc-framework-ApplicationServices==12.2.2` (AXUIElement) + `NSAppleScript` | **ADOPT fw / WRITE ~350 LOC** | Verified in-process here: attribute read median **0.026 ms**; `AXPress` fired a real TextEdit menu item; `kAXValue` write replaced document text with **zero event synthesis**; Safari scrollbar `kAXValue` write scrolled; Slack window moved via `kAXPosition`. Coordinate-free, focus-race-free, needs no permission we lack. **All AX runs on a worker thread with a 0.25 s messaging timeout** (§7 R9). |
| **L5 HUD** | `ui/` — `NSStatusItem` + a borderless `NSWindow` overlay for the progress ring, pyobjc AppKit | **WRITE ~250 LOC** | The draft left this the only layer with no verdict, no library, and no LOC estimate, while calling it un-retrofittable. Decided: `NSWindow` with `styleMask=.borderless`, `backgroundColor=.clear`, `isOpaque=false`, `level = CGWindowLevelForKey(.statusWindow)+1`, `ignoresMouseEvents=true`, `collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]`. No permission required (we draw, we do not capture). It redraws at **≤60 Hz and only while a commit is in progress** — I reject the critique's premise that it must sustain 111 Hz; progress is a human-perception signal, not a control signal. |
| **Agent tier** | **DESCOPED.** `intent/socket.py` publishes typed intents on a Unix socket; nothing subscribes in v1. | **CUT** | See §5 Phase 3 and §7 rejections. |

### Why we write `inject/quartz.py` instead of adopting `pynput`

`pynput` 1.8.2 was verified working here (8/8 absolute positions exact, including negative coords on the second display; correct `kCGMouseEventClickState`). We still write our own:

1. **Decisive:** pynput gives no access to the event's source fields, so we cannot tag events with `kCGEventSourceUserData`. That tag is how the physical-input-yield tap (§4) tells our synthetic events from the human's real trackpad. Without it the yield mechanism feedback-loops. Correctness requirement, not preference.
2. `_scroll` does `int(dx)` then `* 10`, so `scroll(0, 0.5)` is a **silent no-op** with a 10 px floor. Position-control scroll needs sub-line pixel deltas.
3. Injected pynput moves carry **zero** `kCGMouseEventDeltaX/Y`; some apps read deltas.
4. LGPL-3.0.

Measured cost of writing it: raw `CGEventPost` is **10.4 µs/call**, ~94,000 posts/s sustained. Against a 9 ms frame budget, ~865× headroom. **PyAutoGUI is disqualified** — a hardcoded `DARWIN_CATCH_UP_TIME` sleep caps it at **76 Hz, below our 111 fps stream**; it never sets `clickState`; its `size()` reports the main display only; last release 2023-05-24.

### Language and the 3.12 question

Python 3.12 for Phase 0, behind a `Source` protocol, with a ctypes backend spiked in week 1 to remove the pin.

- The bundled CFFI module is `_leapc_cffi.cpython-312-darwin.so` — **3.12 exactly**. System `python3` (3.14.6) does not work with it.
- Every hot-path operation is µs-scale: 1€ filter 0.74 µs, `CGEventPost` 10.4 µs, AX read 26 µs, against a 9,030 µs frame budget. The latency case for Swift does not survive measurement.
- **Rejected fallback:** rewriting the stack in Swift via `studiome/LeapSwift` / `studiome/leapgo`. Both verifiably work on this v1 (111.1 fps and 110.4–111.7 Hz measured; both READMEs falsely claim an LMC2 is required — neither filters on device type), but they are one author's two-week-old projects with a shared bus factor of one. If jitter ever forces a native hot loop, the ~200 LOC of capture→filter→pose→post is a direct `LeapC.h` + Swift shim we write in a day, talking to Python over the same socket seam. Splitting the stack on someone else's fortnight-old code is not the move.

### Concurrency model — assigned, not implied

Five components each demand a run loop or main-thread affinity. This is the layer the draft never assigned.

| Thread | Owns | Rules |
|---|---|---|
| **Main** | `NSApplication` (`.accessory`) run loop, `NSStatusItem`, HUD overlay, Carbon `RegisterEventHotKey`, `CGDisplayRegisterReconfigurationCallback` | AppKit only. Never blocks on AX or disk. Receives frame-derived state via a lock-free slot, redraws on a 60 Hz `CVDisplayLink`/timer, not per frame. |
| **T-frame** | LeapC poll (111 Hz), L1 condition, L2 FSM, `CGEventPost` for motion/click/drag/scroll | Highest priority. **No AX calls. No disk I/O. No AppKit.** Publishes intents and log records to bounded queues. Heartbeat timestamp updated every frame. |
| **T-tap** | Own `CFRunLoop` + `.listenOnly` `CGEventTap` at `kCGSessionEventTap` | Callback does **bounded work**: read `kCGEventSourceUserData`, compare to `0x4C454150`, accumulate motion, set an atomic. Returns immediately. Re-enables on `kCGEventTapDisabledByTimeout`. **I reject "allocation-free" as stated** — it is unachievable in CPython; the achievable and sufficient requirement is bounded, non-blocking, no-logging. |
| **T-action** | Intent queue consumer: AX, `NSAppleScript`, keystroke synthesis | All cross-process Mach IPC lives here. `AXUIElementSetMessagingTimeout(0.25)` on **every** element, without exception. |
| **T-watchdog** | Frame-thread heartbeat, tap health poll (5 s), Leap connection state | On a >250 ms heartbeat gap: release-all, DISENGAGE, log. |
| **T-log** | Drains the log/ring-buffer queues to disk | The only thread that touches the filesystem in steady state. |
| **Guard process** | Pipe-EOF watch, panic hotkey | Separate process. Survives our SIGKILL. |

`sys.setswitchinterval(0.001)` at boot — the 5 ms default lets any thread hold the GIL for half a frame. GIL contention here is a **stall** problem, not a throughput problem, and the stall source is AX; confining AX to T-action is the actual fix.

---

## 2. What is dead — stated plainly

Investigated, not available. Do not re-derive.

- **Server-side gesture detection is dead on this hardware.** Hyperion 6.2 added `eLeapHandFlag_GesturePinch` / `MovingPinchOpening` / `MovingPinchClosing` to `LEAP_HAND.flags`. Measured over **2,419 real hand-frames** (with and without the hint): `flags` is **always 0** — even bit 0, `GestureDetectionAvailable`, never sets. The `microgestures` hint is *recognised* but matches no model available to this device (`tracker_log.txt`: `"Hint received in core layer: microgestures"` → `"HintResolver did not accept any hints"`, vs the control `low_resource_usage` → `"HintResolver accepted hints"`). Vendor docs list the Microgestures model as **HMD-only**. Of 13 installed `.ldat` models only 2 are viable for `calibration leap`. **We write the entire gesture layer.**
- **`LeapCheckLicenseFlag` is a permissive stub.** Returns `enabled=True` for `"Hyperion"`, `"microgestures"`, **and** for `"zzz_not_a_real_flag_12345"`, `"__nope__"`, and the empty string. Never gate a capability on it.
- **`LEAP_HAND.confidence` is inert** — header says *"Not currently used (always 1.0)"*. Use `visible_time`.
- **TouchFree the product is dead.** Archived 2023-04-21 (final commit is the archive ticket), zero releases, all 11 forks dead on the archive date, app+service closed-source. Its only OS-input code is Windows `User32.InjectTouchInput`, and it injects *touchscreen contacts* — not scroll, not keyboard, not app control. Read it as a specification; do not depend on it, do not port its tests, do not keep its constants.
- **MediaPipe Gesture Recognizer cannot be reused.** Google's task is image-in only; classification "cannot run independently" of hand detection. There is no landmark-in entry point. "Keep Google's gesture layer, swap the camera for a Leap" is structurally impossible.
- **`ISUE/Jackknife` is licence- and patent-blocked.** LICENSE is the UCF Research Foundation **non-commercial academic** licence — "BUT NOT TO DISTRIBUTE THE WORK", licensee defined as academic faculty/researchers/students. Its GPSR synthetic-data method is **US 10,133,949 B2**, active to 2037, assignee UCF Research Foundation.
- **`HandVector` cannot be linked** — `Package.swift` declares `platforms: [.visionOS(.v1)]`, core types `import ARKit`.
- **`Heliox-OS` has zero Leap support** (0 hits for leap/ultraleap across 56 MB), its macOS build cannot authenticate to its own daemon (`get_auth_token()` in `commands.rs` has no darwin branch, hardcodes `/run/user/1000/`), and its gesture RPC is self-documented as "the degraded fallback path" that cannot sustain 30 fps. We need 111.
- **`Hammerspoon` is skipped.** ADOPT-quality, but adds a Lua runtime and a **second TCC identity**, and `hs.mouse.absolutePosition` calls `CGWarpMouseCursorPosition` with no suppression-interval reset (issue #3332, open 3.5 years), killing the physical trackpad for 250 ms per call. At 111 Hz the trackpad never comes back. Window management is available from AX in-process.
- **`yabai`/`skhd` are avoided** — both transferred from `koekeishiya` to `asmvik`, and yabai's interesting features require partial SIP disable. No tiling-manager fallback is named in this plan; `AeroSpace` was floated in the draft with **zero verification** and is removed rather than carried as an unverified claim.
- **No OSS bridges hand tracking to computer-use agents.** Closest prior art is academic (GestureGPT 2024, SIAgent 2026). The draft called this "our gap"; a gap nobody has filled in a decade is more often absence of demand than absence of ability. See §5 Phase 3.

---

## 3. Ergonomics — designed in, not bolted on

Gorilla arm killed this category. Three mechanisms, all load-bearing.

**1. The Leap sits behind the keyboard, facing up. The elbow never leaves the desk.** Interaction volume is a box roughly **150 × 100 × 80 mm** centred ~120 mm above the device — the space the hand already occupies at the desk edge. If a gesture requires lifting the elbow, the gesture is wrong. This also means **hands cross the volume constantly while typing**, which is the dominant false-positive source and is why §5 Phase 0.5 mandates an ambient negative corpus.

**2. Ratcheting via a clutch pose — and therefore relative pointer control.** The pointer moves **only while the clutch is held**, and it moves by *integrated hand delta from the position at clutch engage*, not by absolute hand position. Release the clutch, drop the hand, reposition comfortably, re-engage — the cursor stays where it was. This is exactly what lifting a mouse does. Absolute mapping teleports the cursor on every re-clutch and voids the entire mitigation; the draft specified both and could not have both.

**3. The clutch is a rest posture with no finger state.** CLUTCH = **driver palm normal within 30° of straight down** (palm-down, the neutral hand-on-desk orientation), held 5 frames. Release at >45°, 8 frames — rotate the palm toward vertical, as if turning a doorknob, and the pointer parks. This is:
- **digit-disjoint** from every click pose, so clicking cannot break the clutch (the draft's peace-sign clutch required an extended index, and its click required a flexed index — every click broke the clutch);
- **low-tension**, requiring no active flexion (the peace sign requires simultaneous ring/pinky flexion and index/middle extension — the most fatiguing hold available);
- **free of `pinky.is_extended`**, the least reliable boolean the v1 produces palm-down. **Nothing in this vocabulary is load-bearing on ring or pinky extension.**

**Rejected alternative:** "left hand is the clutch, right hand clicks." It is digit-disjoint, but it makes two-hand tracking mandatory for all pointing, doubling the tracking-failure surface on a 640×240 2013 sensor, and it consumes the modifier hand.

**4. High, non-linear control-display gain.** Seeds: `g_min = 1.0 px/mm` below 40 mm/s hand speed, ramping to `g_max = 30 px/mm` above 400 mm/s, linear in between. A slow deliberate move gets sub-pixel precision; a fast flick crosses the display in ~50 mm. Never 1:1. All four numbers are Phase 0.5 outputs from the Fitts harness, not assertions.

Supporting rules, enforced in code:
- **No dwell > 600 ms** anywhere in the vocabulary.
- **No gesture above shoulder height**, no full arm extension; hard z-cutoff at 250 mm.
- **Default state is DISENGAGED.** Gesture control is a mode you enter for seconds, not a persistent input device.
- **Instrument from Phase 0.** Log clutch duty cycle and median continuous clutch-hold. **If median continuous hold exceeds 4 s, the vocabulary is wrong and we change it, not the user.** This is a measured gate, not a judgement call.

---

## 4. Gesture vocabulary, mutual exclusion, and the dead-man's switch

### 4.1 Hand binding

- **Driver hand** = the `hand.id` bound at CLUTCH engage. The binding survives momentary pose changes and is released on `hand.id` loss, SESSION exit, or panic.
- **Modifier hand** = any tracked hand of opposite chirality that is *not* the driver.
- **Chirality flips** are common on the v1 with a single hand. The driver binding keys on `id`, not on `type`; a chirality flip on the bound id logs a warning and does **not** reassign the driver.
- **Re-ID after occlusion:** a new `id` is a new hand. There is no re-identification heuristic — a driver hand that is lost is lost, and DISENGAGE fires. This is deliberate: silently re-adopting a hand is exactly how a freshly reacquired skeleton snaps through poses the user never made.
- **Two-hand dead-man correctness:** the removal check is on the **bound driver id**, not on "any tracked hand". The draft's "no tracked hand for 15 frames" never fires if the non-driving hand is still in the volume — a silent defeat of the primary kill.

### 4.2 Gates, nested

| Gate | Scope | Enters | Exits |
|---|---|---|---|
| **SESSION** | system may inject at all | menu-bar toggle or global hotkey | hotkey, menu-bar, 5 min idle, SIGTERM/SIGINT, guard-detected process death |
| **CLUTCH** | pointer is live, driver bound | palm-down ≤30°, `visible_time ≥ 200 ms`, 5 frames | palm >45° for 8 frames, driver-id loss, SESSION off, physical-input yield |
| **COMMIT** | a discrete intent fires | FSM enters COMMIT with visible 0→1 progress | progress abandoned, or intent dispatched |

### 4.3 The FSM — mutual exclusion by construction

The draft's vocabulary was a set of independent Schmitt triggers, which is why SCROLL (`grab_strength ≥ 0.8`) and DISENGAGE (`grab_strength > 0.9`) could both fire, and why SWIPE (velocity only, no pose gate) fired on any fast MOVE. The recognizer is now **one FSM with exclusive states**. At most one state is active; there is no configuration in which two intents can be simultaneously satisfied, because there is only one state variable.

```
                 driver lost / palm>45° / yield / panic
   ┌────────────────────────── any state ───────────────────────► IDLE
   │
IDLE ──clutch engage──► POINT ──force≥1.0 or pinch engage──► ARMED
                          │                                    │
                          │◄──────── release (<unclick) ────────┤ (fires CLICK, latched pos)
                          │                                    │
                          │                        held + Δ>30mm│
                          │                                    ▼
                          │                                  DRAG ──release──► POINT
                          │
                          ├──grab_strength≥0.8──► SCROLL ──<0.7──► POINT
                          │
                          └──pinch held 500ms──► COMMIT ──release──► POINT (dispatch)
```

Transitions out of POINT are evaluated in a fixed priority order (SCROLL > COMMIT > ARMED) and the first match wins; no other transition is considered that frame. That priority order plus single-state-ownership *is* the mutual-exclusion proof.

### 4.4 Vocabulary

All thresholds are hysteretic (engage tighter than release). Every number below is a **seed to be replaced by a Phase 0.5 measurement**, and is tagged with its provenance.

| Gesture | Signal | Engage | Release | Notes / provenance |
|---|---|---|---|---|
| **CLUTCH** | driver `palm.normal` angle from world-down | ≤30°, 5 frames | >45°, 8 frames | ours; finger-free, rest posture |
| **MOVE** | Δ`palm.stabilized_position` since last frame → 1€ (`mincutoff=3.0, beta=0.02`) → gain curve → integrate onto our own float cursor | only in POINT/DRAG | — | **relative**. Cursor seeded from `CGEventGetLocation` at clutch engage. 3 mm resting deadzone, grows to 20 mm during commit progress (TouchFree shape, our numbers). |
| **CLICK — primary** | AirPush force accumulator over `palm.velocity` toward the screen | force ≥ 1.0 | 0.97 | **Whole-hand, occlusion-immune.** Structure from TouchFree `AirPushInteraction`; `SpeedMin/Max`, `DistAtSpeedMin/MaxMm`, `HorizontalDecayDistMm`, `ThetaOne/Two`, `ForceDecayTime` all re-derived in Phase 0.5. Cursor **frozen for ±100 ms around commit**; the click posts at the **latched** position from the triggering frame index. |
| **CLICK — fallback** | thumb↔index `pinch_distance` (mm) | <22 mm | >30 mm, 120 ms debounce | **Adopted only if Phase 0.5 shows a clean bimodal distribution with non-overlapping p05/p95 bands.** On a desk-mounted v1 palm-down, thumb and index tips occlude each other exactly as the pinch closes, so below ~20 mm the model is extrapolating from invisible tips — the noisiest region of the signal is precisely where the threshold sits. `pinch_distance` in mm rescues us from hand-size drift (`pinch_strength` normalises against an inferred hand size that re-estimates mid-session); it does not rescue us from occlusion. |
| **RIGHT CLICK** | modifier hand present in-volume at CLICK commit; if no second hand, CLICK held 400 ms without displacement | — | — | **Thumb–middle pinch is cut.** The index follows the middle in most hands, so a thumb–middle pinch also collapses `pinch_distance` below the left-click threshold, double-firing; and the middle fingertip is *more* occluded palm-down, where the v1 model is prone to digit-swap. |
| **DRAG** | ARMED held + displacement | >30 mm | click release | deadzone → 20 mm, shrink factor 0.8 |
| **SCROLL** | `grab_strength` Schmitt gates the state; scroll amount ∝ (`palm.position` − anchor captured at fist close) | 0.8 | 0.7 | **Position control, not rate control.** Rate control from `palm.velocity` has no natural zero — the hand is never still, so the page creeps forever. 5 mm null zone, 100 ms grace after engage (forming a fist translates the palm 5–15 mm), both x and y axes, `kCGScrollEventUnitPixel`, sign flipped per `com.apple.swipescrolldirection` read from `NSUserDefaults` at session start and on `NSUserDefaultsDidChangeNotification`. **No momentum** — see §7 rejections. |
| **COMMIT** | thumb+index pinch held 500 ms with progress ring; **fires on release**, not on contact | — | — | ours. Firing on release gives an escape hatch (slide out before releasing = cancel), matching Ultraleap's own microgesture rationale. Phase 1: renders progress and dispatches nothing. Phase 2: opens the cursor-anchored command palette. |
| **KEYSTROKE / SHORTCUT** | never a raw pose — only an intent dispatched from COMMIT | — | — | Realised preferentially as `AXUIElementPerformAction(kAXPress)` on a menu item discovered by name (menu items expose `AXMenuItemCmdChar`/`AXMenuItemCmdModifiers`, so shortcuts are discoverable and invocable *semantically*). Falls back to `CGEvent` key down/up with our source tag. **Refused entirely under Secure Event Input.** |
| **DISENGAGE** | rotate palm to vertical (clutch release), or remove the hand, or panic hotkey | — | — | **The fist-disengage is cut** — it collided with SCROLL. |
| **SWIPE** | **CUT from v1.** | — | — | The volume is 150 mm wide; a 625 mm/s swipe crosses it in 240 ms and exits the tracked volume, where the driver hand is lost, where the primary dead-man fires. Every successful swipe would trip the kill switch. Special-casing it means weakening the primary dead-man to enable the lowest-value gesture. TouchFree's `VelocitySwipe` constants were tuned for kiosk arm sweeps in a far larger volume and do not transfer at any threshold. |
| **Left-hand modifiers** | modifier hand `grab_strength` / extension state → `Cmd`/`Shift` flags on the next click | — | — | Covers cmd-click and shift-click multi-select. **Middle-click is cut** — no use case named, pure scope. |
| **Double-click** | a distinct dwell, never two rapid pinches | — | — | Two rapid mid-air pinches is a bad interaction independent of detector quality. Not a Phase 0 exit criterion (see §5). |

### 4.5 Dead-man's switch — three honest classes, not seven paths

The draft claimed seven independent paths. Three of them (hand loss, young-hand rejection, watchdog) all depend on the same frame loop and the same LeapC connection; if that thread blocks, only the watchdog evaluates. SEI refusal is a policy, not a kill. **The overcount was dangerous because it made the one genuinely missing path — process death — look redundant.** Honest inventory:

**Class A — frame-loop liveness (one mechanism, several triggers).**
- Driver-hand id absent for 15 frames (~135 ms) → DISENGAGE + release all held buttons and modifiers.
- `visible_time < 200,000 µs` (~22 frames) → hand is ineligible to drive anything. Kills the dominant false-positive class: a freshly reacquired skeleton snapping through poses.
- **T-watchdog** is the actual backstop: heartbeat gap > 250 ms → release-all + DISENGAGE. Protects against a stalled LeapC read, a blocked AX call that escaped T-action, or a GC pause.

**Class B — human override.**
- **Panic hotkey, registered in the guard process**, not in ours. Posts button-up ×3 and key-up for all modifiers regardless of our state.
- **Menu-bar status item**: always-visible state indicator plus kill. Never ship `LSUIElement` without one.
- **Physical-input yield**: `.listenOnly` `CGEventTap` at `kCGSessionEventTap`, filtering our own events by `kCGEventSourceUserData == 0x4C454150` (verified round-trippable). **Debounced: requires ≥3 events *and* >5 mm of accumulated real motion within 200 ms**, because a single stray trackpad brush, another app warping the cursor, or a screen-sharing session would otherwise disengage the user constantly. Its false-positive rate is instrumented in Phase 0 before it is trusted. It goes blind under SEI — which is why it is not the only override.

**Class C — process death. This is the highest-severity risk in the design and the draft did not list it.**
A crash, SIGKILL, OOM, or GIL deadlock mid-drag leaves left-button-down at the WindowServer level. The machine becomes unusable: you cannot click the menu bar to fix it, and you cannot click Terminal to fix it. Every path in Class A and B assumes our process is alive.
- **`leapinput-guard`**, a separate process launched as our parent or sibling, holding a pipe to us. On EOF from any cause — including `kill -9` — it posts button-up for all three buttons and key-up for every modifier, then exits.
- `atexit` + `SIGTERM`/`SIGINT` handlers + `NSApplicationWillTerminate` in-process for the graceful cases.
- **`leapinput panic` ships as a standalone script in Phase 0** and is tested by `kill -9`-ing ourselves mid-drag on day one.

**Policy refusals (not kills, but enforced):**
- **Secure Event Input** → refuse all keyboard/typing intents. Note this is policy, not capability: measured, synthetic keydowns **are** delivered under SEI (3/3, in all three configurations, including when the frontmost app asserted SEI on itself). SEI only blinds *taps* to keyboard. We refuse anyway — we must never type into a password field.
- **AX deny-list** (`intent/policy.py`). `AXPress` and `kAXValue` writes bypass SEI entirely, so SEI refusal does not protect them. Hard-deny by bundle id (`com.apple.SecurityAgent`, `com.apple.systempreferences` privacy panes, Keychain Access, TCC prompts, `loginwindow`) and by role (`AXSecureTextField`, and any element whose window subrole marks it a system alert). Every discrete action is written to an append-only action log with target bundle id, role, and action.

---

## 5. Phased delivery

### Phase 0 — thin vertical slice + panic path (target: 1–2 days)

```
leap frames → palm-down clutch → relative 1€-smoothed cursor → AirPush click
            → driver-hand removal = disengage + release-all
            → leapinput-guard = release-all on process death
```

Scope: `capture/`, `condition/oneeuro.py`, `condition/pointer.py`, clutch gate, AirPush accumulator, `inject/quartz.py`, **`guard/`**. Terminal readout only. Single display.

**Exit criteria (all measurable):**
1. **Hand-to-photon latency measured and reported.** 240 fps phone slow-mo with hand and screen in one frame; count frames from hand-motion onset to cursor-motion onset. Twenty minutes of work. The draft's "injected-move p95 < 15 ms" criterion measured the one segment already known to be free (post→tap: min 0.159 / median 0.428 / p95 3.117 ms) and excluded the expensive legs — sensor exposure, Leap service inference on a v1 over USB 2.0, and IPC. Expect 40–70 ms total. **If it lands above ~60 ms, the vocabulary shifts toward discrete/committed actions and away from continuous pointing — and we need to know that on day one.**
2. Cursor tracks the hand; **re-clutching after repositioning does not move the cursor** (proves relative control).
3. A single AirPush click activates a real button in a real app.
4. Removing the driver hand stops all motion within 135 ms and releases any held button. Verify with a deliberately interrupted drag.
5. **`kill -9` mid-drag leaves no stuck button.** Non-negotiable.
6. Clutch duty cycle and median continuous clutch-hold are being logged.

**Explicitly not a Phase 0 criterion:** the draft's "a pinch opens a Finder item, i.e. `clickState=2` produces a real double-click." Two pinch cycles within 500 ms with <4 px drift, on the noisiest signal the v1 produces, with click-drag unsolved, is not a day-one gate. Double-click becomes a dwell in Phase 1.

### Phase 0.5 — record/replay, measurement, and the negative corpus (target: 3 days)

**Non-negotiable, and it is the first thing schedule pressure will try to cut.**

- **Record/replay.** Raw `HandFrame` streams to JSONL; deterministic replay through L1/L2 with a synthetic clock in the canonical LeapC domain (§7 R11). Labelled `should-fire` / `should-not-fire`.
- **Ambient negative corpus — the part that actually matters.** The device sits *behind the keyboard*, so hands cross the volume constantly. Record real typing, reaching for coffee, gesturing while talking on a call, adjusting the display, scratching. **Acceptance metric: ≤1 unintended commit per 10 minutes of ambient hand presence.** §2's entire argument for hand-writing the gesture layer is that Ultraleap deleted its own built-in gestures over false-positive rates; shipping without an FP budget repeats their mistake.
- **Signal measurement.** `pinch_distance` p05/p95 and bimodality; per-joint jitter at the intended volume; `pinch_strength` quantisation level count (if heavily quantised, hysteresis bands must straddle quantisation steps or the trigger chatters); palm-velocity distribution for the AirPush tuning; palm-normal stability for the clutch.
- **Fitts harness.** Target-acquisition task driving the gain curve and the 1€ parameters. `mincutoff=1.0` (the draft's seed) has a group delay of ≈1/(2π·1) ≈ **160 ms** at low hand speed — 15× the entire injection path. Kiosks tolerate it because targets are 200 px; a 1512 px desktop with 20 px targets will feel like syrup and will overshoot-oscillate with a human in the loop. We start at `mincutoff=3.0, beta=0.02` and tune against the harness, not by feel. (For the record: the draft's claim that "beta buys sub-pixel precision at slow speeds" is backwards — beta *reduces lag at high speed*; low-speed precision comes from a low `mincutoff`, and lag is what it costs.)
- **Config layer lands here.** A versioned `profiles/*.toml`, each pinned to the corpus commit hash it was tuned against, so replay results are reproducible across tuning rounds.

### Phase 1 — full vocabulary, safety envelope, HUD (target: 2–3 weeks)

The draft gave Phase 0 "1 day" and Phase 1 no number at all, which set a false pace. This is the big phase.

- The full FSM: AirPush, pinch fallback (if it survived measurement), grab detector, drag, position-control scroll, progress timer.
- **Pose-authoring tool** (`tools/pose_author.py`) — record a held pose, derive per-joint tolerances, write a versioned pose file. Phase 1 cannot start without it: UnityPlugin's shipped `HandPoseDetector` thresholds do not transfer (Unity is LH-Y-up ZXY; LeapC is RH), so every threshold must be recorded here.
- HUD: `NSStatusItem` + cursor-anchored progress ring. **Emit continuous 0→1 progress alongside every discrete event from day one** — mid-air clicking without accumulating visual commitment feels like a coin flip regardless of detector quality, and retrofitting progress later means rewriting every consumer.
- Multi-display: `CGGetActiveDisplayList` at startup + `CGDisplayRegisterReconfigurationCallback`. Cursor containment projects to the **nearest real display rect**, never to the union — the union of `1512×982 @(0,0)` and `2560×1440 @(-541,-1440)` is ~2053×2422 with a large void, and a cursor in the void is unrecoverable.
- All dead-man classes; sleep/wake and fast-user-switch recovery (both kill event taps and can drop the LeapC connection); Leap reconnect on `LEAP_CONNECTION_LOST` and device-state events.
- **Observability**: structured logging to a queue-backed sink, plus a **rolling ring buffer of the last 10 s of raw frames, auto-dumped on every commit and every user-flagged misfire**. This is the cheapest high-value item in the plan — it is how the corpus grows from real use instead of staged sessions.
- **CI**: pure-math layers (L1/L2, FSM, filter, corpus regression) run headless on every push; hardware-dependent tests carry a skip marker.

### Phase 2 — intent bus + deterministic actions (target: 2–3 weeks). **This tier carries the product.**

Typed intents resolved in-process, zero model calls, on T-action:
- `AXUIElementPerformAction(kAXPress)` on menu items found by name — verified working.
- `AXUIElementSetAttributeValue(kAXValue)` for text and scrollbars.
- `kAXPosition`/`kAXSize` for window management.
- `NSAppleScript`/JXA for the scriptable-app subset (Mail, Calendar, Finder, Notes, Safari) — deterministic, invisible to the cursor, cannot mis-click. **Gated on Automation TCC** (§7 R13); this is the only Phase 2 path that can hard-fail on a fresh machine, so it degrades to the AX path rather than erroring.
- `open -g 'url://'` for cooperating apps — ~0 ms, needs no permission at all.
- `intent/policy.py` deny-list and the action log, per §4.5.
- COMMIT opens a cursor-anchored command palette listing context-appropriate intents.

Latency 10–50 ms with zero tokens.

### Phase 3 — agent tier: **DESCOPED to a seam**

The stated project goal includes "plausibly driving an LLM computer use agent loop", so I do not delete the possibility — but I reject building it in this plan.

**What ships:** `intent/socket.py` publishes typed intents on a Unix domain socket, and accepts nothing. That is the entire coupling. Anything — an MCP server, an agent loop, a logger — can subscribe later without touching L0–L4.

**Why it is not built now:** it adds a second TCC identity, a 0.x daemon on daily nightlies holding full Accessibility, an MCP server, an LLM loop, and an unsolved Screen Recording permission — none of which is about hand tracking, and all of which is the largest attack surface in the design attached to the least-validated feature. The interaction model is also incoherent on its own terms: if every agent invocation requires explicit human confirmation (correct), and the agent drives a background cursor, then the hand is idle for the entire loop — a hotkey and a text prompt beat a gesture for "start an agent."

**Preserved facts if we ever revisit:** `trycua/cua-driver` 0.19.3 was verified live (`universal2` wheel into 3.12, 54 tools, `get_screen_size` → `1512x982 @1.0`). Its unique property is background AX delivery with its own agent cursor and no focus steal. `check_permissions` returns `accessibility:false, screen_recording:false` — our terminal's grant does not transfer to `com.trycua.driver`. `move_cursor` measured **p50 166.9 ms in-process** (it is a glided cursor with `glide_duration_ms`/spring/arc) — a semantic tool, never a transport. Its telemetry must be disabled. The world model would be the **AX tree, not screenshots**, and would need a pruning/diff serializer that does not exist (a 4,000-node walk is ~2.5 s at 0.64 ms/node) — plus an ownership rule for the two AX trees (ours in-process, the daemon's).

### Phase 4 — user-enrolled dynamic gestures: **DEFERRED, unscoped**

If it happens: DTW template matching reimplemented from the CHI 2017 paper (never vendored — §2), gated behind a cheap motion-burst segmenter, reduced to a low-dimensional trajectory before matching (60-D multivariate DTW is too slow). `dtaidistance` 2.4.0 does publish `cp312-macosx_11_0_arm64` and `cp312 universal2` wheels (PyPI, checked 2026-08-12), so the C-accelerated core is available. Not planned, not estimated.

---

## 6. Repo layout & dependencies

Extend the existing working tree at `/Users/joerup/era/leap-input`.

```
leap-input/
├── pyproject.toml                 # requires-python = ">=3.12"  (3.12 only while CFFI is the source)
├── vendor/
│   └── leapc-python-bindings/     # UPSTREAM ultraleap, pinned; .5→.6 patch pre-applied
├── src/leapinput/
│   ├── capture/    source.py  cffi_source.py  ctypes_source.py  frame.py  record.py  replay.py
│   ├── condition/  oneeuro.py  pointer.py  deadzone.py  displays.py
│   ├── recognize/  fsm.py  schmitt.py  airpush.py  grab.py  pose.py  progress.py
│   ├── intent/     types.py  bus.py  gates.py  deadman.py  policy.py  socket.py
│   ├── inject/     quartz.py  ax.py  applescript.py  keys.py
│   ├── ui/         statusitem.py  ring.py  palette.py
│   ├── obs/        log.py  ringbuffer.py  metrics.py
│   ├── config/     schema.py  load.py
│   └── cli.py                     # run | panic | record | replay | probe
├── guard/          leapinput_guard.py            # separate process, Phase 0
├── tools/          pose_author.py  fitts.py  latency_probe.py
├── profiles/       *.toml                        # thresholds, each pinned to a corpus hash
├── corpus/         fire/*.jsonl  ambient/*.jsonl  labels.yaml
├── tests/          unit (headless) + corpus regression + FP-budget assertion
└── docs/
```

**Dependencies** (all verified installable on arm64 / CPython 3.12.13):

| Package | Pin | Licence | Note |
|---|---|---|---|
| `leap` | editable from `vendor/leapc-python-bindings/leapc-python-api` | Apache-2.0 | + SDK's bundled `leapc_cffi` copied into site-packages |
| `cffi` | latest | MIT | removable once `ctypes_source.py` lands |
| `pyobjc-framework-Quartz` | `==12.2.2` | MIT | already present in the venv |
| `pyobjc-framework-ApplicationServices` | `==12.2.2` | MIT | AXUIElement |
| `pyobjc-framework-Cocoa` | `==12.2.2` | MIT | status item, overlay, `NSAppleScript` |
| `numpy` | latest | BSD-3 | pose math, vectorised filter |

**Removed from the draft's list:** `OneEuroFilter` (vendored into `condition/oneeuro.py` with the two bugs fixed), `cua-driver` (Phase 3 descoped), `dtaidistance` (Phase 4 deferred).

**Referenced, not depended on or ported wholesale** — attribution in `NOTICE`: TouchFree `Interactions/` (algorithm shape only, Apache-2.0), UnityPlugin `HandPoseDetector.cs` (matching strategy only, Apache-2.0), `casiez/OneEuroFilter` (BSD-3, vendored).

---

## 7. Risks & open questions

| # | Risk | Resolution |
|---|---|---|
| **R1** | **v1 pinch quality.** 640×240 2013 sensor; thumb/index occlude exactly as the pinch closes. | Already resolved structurally: **AirPush is primary**, pinch is fallback. Phase 0.5 admits pinch only on a clean bimodal distribution with non-overlapping p05/p95. If it fails, we lose nothing. |
| **R2** | **Event-tap location conflict.** One measurement says posting `mouseMoved` to `kCGHIDEventTap` applies pointer acceleration (first move ~7 px off); another says HID and session both land exact. | 30-minute A/B at 111 Hz: HID vs session vs `CGWarpMouseCursorPosition` vs warp-then-post. **Known-bad: `kCGAnnotatedSessionEventTap` (2) does not move the pointer at all** (700/380/850 px error). Warp alone emits no move event, so hover-tracking apps miss it; the hybrid measured 4/4 at 0.0 px if we need both. |
| **R3** | **Display topology.** Two displays: `1512×982 @(0,0)` and `2560×1440 @(-541,-1440)`. The union is non-rectangular with a large void. | Relative control removes the mapping problem. Containment projects to the **nearest real display rect**; the cursor can never be in the void. `CGDisplayRegisterReconfigurationCallback` on the main thread rebuilds the rect list on hot-plug or rearrange. |
| **R4** | **Yield tap silently disabled.** >~4 s callback → `kCGEventTapDisabledByTimeout`; tap reports enabled but delivers nothing. | Subscribe to the tap-disabled event types and `CGEvent.tapEnable(true)` on receipt; 5 s `tapIsEnabled` health poll on T-watchdog; callback is bounded and non-blocking; and it is never the sole override. |
| **R5** | **Screen Recording is NOT granted**, and on Tahoe 26.1+ a non-bundled Unix executable does not appear in the privacy UI at all. | We never need pixels. Window identity and app state come from **AX**, not the window server — note that `kCGWindowName` from `CGWindowListCopyWindowInfo` requires Screen Recording on modern macOS, so no code may reach for window titles that way. |
| **R6** | **TCC identity moves.** Grants belong to the terminal, not to a future `.app`. **And the Accessibility grant follows `.venv/bin/python3.12`** — a `uv` venv recreate or a 3.12.13→3.12.14 patch bump replaces that binary and silently drops (or staleley retains) the grant. | Gate startup on `CGPreflightPostEventAccess()` **now**, not only when bundled, with `CGRequestPostEventAccess()` as the prompt path. Record the interpreter's realpath + inode in the log so a silent grant loss is diagnosable in one line. Bare Unix executables could not register for Accessibility at all on macOS 26.0–26.2 (fixed in 26.3; we are on 26.5.2). |
| **R7** | **Electron apps are AX-opaque.** VS Code exposed 12 nodes / depth 6. | Set `AXManualAccessibility=true` per app — grows the tree to ~595 nodes, but **asynchronously** (still 13 nodes at t+2 s, populated by t+6 s), so a naive probe reports failure. Do it once at session start, settle, cache, refresh via `AXObserver`. `AXEnhancedUserInterface` returns `-25208` on VS Code — do not use it. Slack and Notion need no opt-in. |
| **R8** | **Gorilla arm — the actual product risk.** | Instrumented from Phase 0. Median continuous clutch-hold > 4 s → redesign the vocabulary. Measured gate. |
| **R9** | **GIL stalls, and AX is the stall.** AX calls are synchronous cross-process Mach IPC; the 0.026 ms median is a *responsive* target. A busy or beachballing app blocks until the AX messaging timeout, which defaults to multiple seconds — which is also exactly the >4 s condition that kills the event tap (R4). | `AXUIElementSetMessagingTimeout(0.25)` on every element without exception; all AX on T-action, never on T-frame; `sys.setswitchinterval(0.001)`; T-frame allocates minimally and logs to a queue, never to disk; the tap callback sets a flag and returns. |
| **R10** | **Leap service loss, unplug, or a silent Hyperion update.** A 6.3 push could ship `libLeapC.7.dylib` or a non-3.12 CFFI and break the stack between sessions. | **Boot-time assertion** on `get_server_status()` version and on the resolved `libLeapC` SONAME; mismatch fails loudly with the expected/actual pair rather than crashing mid-session. Reconnect loop on `LEAP_CONNECTION_LOST` and device-state events, with DISENGAGE on entry to the disconnected state. **I reject "pin or disable the vendor updater"** — we cannot reliably suppress Ultraleap's updater, and a detection that fails loudly is strictly better than a suppression that fails silently. |
| **R11** | **Mixed clock domains.** The draft said "`time.monotonic()` *or* the LeapC frame timestamp" — different domains, so recorded corpora and live runs are not comparable. | **Canonical domain is the LeapC clock** (`LeapGetNow()` µs, same domain as `frame.timestamp`). Measure the `LeapGetNow()`→`time.monotonic()` offset once at boot, store it in the session header, and stamp every `HandFrame` in the LeapC domain. The replay harness's synthetic clock runs in that domain. Never pass elapsed-since-start into the 1€ filter — a timestamp of exactly `0.0` is falsy and silently skips the frequency update. |
| **R12** | **Filtered-vs-raw misalignment.** L2 recognises on raw frames; L4a moves on filtered frames. A click fires at a cursor position lagging the pose by the filter's group delay — the "click landed 10 px off" bug. | Every filtered cursor position is stored with its source frame index in a small ring. On a trigger at frame *n*, the click posts at the **latched** filtered position for frame *n*, and the cursor is frozen ±100 ms around the commit. |
| **R13** | **Automation / Apple Events TCC was entirely absent from the ledger.** The Phase 2 `NSAppleScript`/JXA tier requires a **separate consent prompt per (source, target) pair**, granted to the terminal, first-use-blocking, non-scriptable via TCC. `NSAppleEventsUsageDescription` becomes mandatory once bundled. | Probe each target once at session start with a harmless `get name` and cache the result; on denial, that app's intents route through AX only, silently. AppleScript is never a hard dependency for any intent. |
| **R14** | **TouchFree parity was an unverified gate.** `TouchFreeTests` was called "portable oracles" with no evidence — they are .NET/NUnit fixtures possibly bound to Unity types, and the draft's LOC estimates (190 for stabiliser+screen+utilities) are light by ~3–5× once NUnit/`System.Numerics`/Unity types are unwound. | Reclassified **REFERENCE**. Port the structure, derive every constant from our corpus, write our own tests against our own labelled clips. Phase 1 is gated on *our* corpus regression, not on parity with archived code whose numbers we discard. Same for `HandPoseDetector` — its shipped thresholds provably do not transfer. |
| **R15** | **CPython 3.12 pin.** Bundled CFFI `.so` is 3.12-only; Ultraleap has not pushed upstream since 2024-06-24, and the documented rebuild escape hatch is **broken as shipped** (`No libLeapC.5.dylib found`). | Two layers. (a) Preemptively patch the vendored copy — `leapc-cffi/setup.py:40` and `leapc-cffi/src/scripts/cffi_build.py:95`, `.5` → `.6` — so the rebuild path exists before we need it. (b) The real fix: `LeapCtypesSource`, which needs no build step and no matched `.so`, spiked in week 1 behind the `Source` protocol and validated frame-for-frame against the CFFI path in the replay harness. |
| **R16** | **False positives from typing.** The device sits behind the keyboard; hands cross the volume constantly. | The ambient negative corpus and the ≤1 unintended commit / 10 min budget are Phase 0.5 exit criteria, enforced in CI as a regression assertion. |

### Critique points explicitly rejected

- **"Allocation-free event-tap handler."** Unachievable in CPython; the requirement is restated as bounded, non-blocking, no-I/O — which is sufficient, since the failure mode is a >4 s callback, not a malloc.
- **"The HUD must draw at 111 Hz."** Rejected. Progress is a perception signal; ≤60 Hz, only during a commit, on the main thread, is correct and cheaper.
- **"Delete Phase 3 entirely."** Partially rejected. The reasoning is sound and the *build* is cut, but the stated project goal includes an agent loop, so the Unix-socket seam ships and the verified `cua-driver` facts are preserved in §5 for a future revisit.
- **"Add scroll momentum."** Rejected. Momentum keeps the page moving after the hand disengages, which directly fights the dead-man's switch; position control already provides the feel momentum was meant to give.
- **"Add middle-click."** Rejected as scope with no named use case.
- **"Left hand is the clutch."** Rejected in favour of the palm-orientation clutch: mandatory two-hand tracking doubles the failure surface on a v1 and consumes the modifier hand.
- **"Pin or disable the Ultraleap background updater."** Rejected; replaced by a loud boot-time version + SONAME assertion, because suppression that fails silently is worse than detection that fails loudly.
- **"Port and run `TouchFreeTests` as oracles."** Rejected; they were never verified extractable and they encode constants we are discarding.
- **`AeroSpace` as a verified tiling fallback.** Rejected; it was floated with zero verification and is removed rather than carried as an unverified claim.
- **A Phase 3 AX-tree serializer and a two-tree cache-coherency rule.** Correct critique of the draft, but moot under the descope; noted in §5 as a prerequisite if the agent tier is ever revived.

---

## 8. Context space — durable facts for future sessions

**Do not re-derive any of this.**

### Hardware / OS
- MacBook Pro, M5 Pro, 48 GB, macOS **26.5.2 (25F84)**, arm64.
- **Two displays**: `id 1` = 1512×982 @ (0,0), built-in main; `id 2` = 2560×1440 @ **(-541,-1440)**. The global space has negative x *and* y, and their union is non-rectangular with a large void.
- Leap: **original 2013 LMC**, serial `LP20006680004`, service type `LMC`, `LeapGetDeviceInfo` pid `0x3` (`eLeapDevicePID_Peripheral`), caps `0`, USB 2.0. Camera 640×240, calibration profile `leap`.
- On the v1, `DeviceInfo` returns `HorizontalFOV=0, VerticalFOV=0, Range=0`; only `Baseline=37000` µm is populated. **Do not build calibration on those fields.**

### Software pins
- Ultraleap Hyperion **6.2.0.0** (`v6.2.0-c98d293a`), `/Applications/Ultraleap Hand Tracking.app`, arm64-native, binaries dated 2025-09-19. **6.2 is the first v6 that re-added v1 support** — 6.0/6.1 were LMC2-only. Version floor is 6.2.
- SDK: `Contents/LeapSDK/`. `lib/libLeapC.6.dylib` — **SONAME `.6`**; Gemini-era code expects `.5`.
- Bundled CFFI: `_leapc_cffi.cpython-312-darwin.so`, universal `[x86_64 + arm64]`, links `@rpath/libLeapC.6.dylib` with `LC_RPATH @loader_path`. **CPython 3.12 ONLY.** System `python3` 3.14.6 does not work. **This pin is an artifact of using the prebuilt ABI-mode CFFI module, not of LeapC — `ctypes` binds `libLeapC.6.dylib` from any CPython.**
- Working install: `/Users/joerup/era/leap-input/.venv` (3.12.13, arm64), `leap` editable from the vendored bindings, SDK's `leapc_cffi/` copied into site-packages. `LeapMotion-Python-Hyperion`'s entire delta vs upstream is 2 string literals in build scripts the prebuilt path bypasses — **use upstream**.
- `pyobjc` 12.2.2 (published 2026-08-11) works on 3.12/arm64: Quartz, ApplicationServices, Cocoa.

### Measured performance (re-verify only after an OS point update)
- Leap stream: **111 fps**, frame interval median **9.03 ms**, p95 9.46 ms, max 10.48 ms, zero drops.
- `CGEventPost`: **10.4 µs/post**, 93,930 posts/s sustained. Post→tap round trip: min 0.159 / median **0.428** / p95 3.117 ms. **This is the cheap leg; it is not where the latency is.**
- AX attribute read: median **0.026 ms** *on a responsive app*. 4-attribute batch over 417 elements: 0.086 ms/element. Full-tree walk: 0.64 ms/node warm (a 4,000-node walk ≈ 2.5 s — cannot run per frame; cache + `AXObserver`). **On a busy app an AX call blocks until the messaging timeout, which defaults to multiple seconds.**
- 1€ filter: **0.74 µs/call**. Group delay of a 1st-order lowpass ≈ 1/(2π·f_c) — `mincutoff=1.0` costs ~160 ms at low hand speed; `mincutoff=3.0` costs ~53 ms.
- `pyautogui.moveTo`: **12.84 ms** (76 Hz) — below our frame rate.
- `osascript ... keystroke` via System Events: **100–140 ms** — ~10,000× slower than `CGEventPost`. Banned.
- `cua-driver move_cursor`: CLI p50 ~50 ms, **in-process p50 167 ms** (glided by design).
- `shortcuts run`: **3.87 s**. Fire-and-forget tier only.
- `open -g 'url://'`: ~0 ms to fire, **needs no permissions at all**.

### Permission ledger (as measured)
- `AXIsProcessTrusted()` = **true**; `CGPreflightPostEventAccess()` = **true**; `CGPreflightListenEventAccess()` = **true**; `CGPreflightScreenCaptureAccess()` = **FALSE**.
- `IsSecureEventInputEnabled()` = false (checked via `ioreg -l -w 0 | grep kCGSSessionSecureInputPID`, empty).
- **Automation / Apple Events (`kTCCServiceAppleEvents`) is a separate grant per (source, target) pair**, granted to the terminal, first-use-blocking, non-scriptable via TCC. `NSAppleEventsUsageDescription` is mandatory once bundled.
- **`kCGWindowName` from `CGWindowListCopyWindowInfo` requires Screen Recording.** Get window identity from AX instead.
- Grants belong to the **terminal** and, for Accessibility, effectively to the venv's `python3.12` binary — a venv recreate or patch bump can silently drop them.
- Rule of thumb: `.listenOnly` taps → Input Monitoring; `.defaultTap` and all `CGEventPost` → Accessibility; AX → Accessibility. Accessibility supersedes Input Monitoring.

### API gotchas
- `LEAP_HAND.confidence` — **always 1.0**, inert. Use `visible_time` (µs since acquisition).
- `LEAP_HAND.flags` — **always 0 on this hardware** (2,419 hand-frames measured). Gesture flags never fire, not even bit 0.
- `LeapCheckLicenseFlag` — **permissive stub**, returns true for garbage.
- `LeapSetDeviceHints` requires an `eLeapConnectionConfig_MultiDeviceAware` connection; the Python binding does not wrap it (needs raw CFFI). The `microgestures` hint is accepted-then-rejected by `HintResolver` on this device.
- `pinch_strength` is documented as "a pinch between the thumb **and any other finger**" — it cannot distinguish thumb–index from thumb–middle, which is one reason the two-pinch scheme was cut.
- `kCGAnnotatedSessionEventTap` (2) **does not move the pointer**. Use HID (0) or session (1).
- `CGWarpMouseCursorPosition` sets exactly with no acceleration but emits **no move event**, and does not reset the suppression interval (which is what makes Hammerspoon's `hs.mouse.absolutePosition` kill the trackpad for 250 ms — issue #3332).
- `CGEventPostToPid` **failed** to deliver keyboard events to a background TextEdit. Do not rely on per-process delivery.
- `kCGEventSourceUserData` round-trips intact — tag our events `0x4C454150`.
- `CGEventTap` is silently disabled by a >~4 s callback (`kCGEventTapDisabledByTimeout`). A tap that exists is not a tap that works.
- **Secure Event Input does NOT block posting** — synthetic keys land 3/3 even when the frontmost app asserts SEI on itself. It only blinds *taps* to keyboard. `IsSecureEventInputEnabled` is not declared in any macOS 26.5 SDK header (only in `.tbd` stubs) — write your own `extern`. Its Apple doc URL 404s; the surviving reference is TN2150 (archived 2007). **SEI does not protect AX at all** — `AXPress`/`kAXValue` bypass it entirely, which is why a deny-list is required.
- Synthetic hotkeys **do** reach Carbon `RegisterEventHotKey` handlers on Tahoe. The widely-cited claim they do not is caused by a missing `NSApplication` event pump in a bare CLI process, not by WindowServer filtering.
- `com.apple.swipescrolldirection` (`NSUserDefaults`, global domain) inverts scroll for natural-scrolling users. Read at session start and on `NSUserDefaultsDidChangeNotification`.
- `OneEuroFilter` (PyPI 0.2.1): a timestamp of exactly `0.0` is **falsy** and silently skips the frequency update; `reset()` does not restore the constructor frequency; scalar-only, one instance per axis. **Vendored and fixed rather than depended on.**
- TouchFree's `PositionFilter.cs` is **not** a real 1€ filter — hardcoded 60 Hz `CalculateAlpha`, ignores per-sample dt. A literal port is mis-tuned by 1.85× at 111 Hz.
- TouchFree ships `EnableOneEuroFilter`, `EnableExtrapolation`, `EnableInteractionConfidence`, `EnableAirClickWithAirPush` all defaulting to **false** — experimental paths, not production-hardened.
- UnityPlugin `HandPoseDetector`: metacarpals are **skipped from comparison but retained as the rotation reference**; Y-euler is checked **only on proximals**; Z is never used; differences use `Mathf.DeltaAngle` (naive subtraction breaks at 0/360). Unity is LH-Y-up ZXY, LeapC is RH — **shipped pose thresholds do not transfer**, record our own.
- `pynput`: injected moves carry **zero** `kCGMouseEventDeltaX/Y`; `scroll` does `int()` then `×10`, so fractional scroll is a silent no-op with a 10 px floor; no access to the event source, so no `kCGEventSourceUserData` tagging.
- `sys.setswitchinterval` defaults to **5 ms** — half a frame at 111 Hz. Set it to 0.001.
- `AXUIElementSetMessagingTimeout` default is multiple seconds. Set 0.25 on every element.
- `dtaidistance` 2.4.0 publishes `cp312-macosx_11_0_arm64` and `cp312 universal2` wheels (PyPI, 2026-08-12).
- The `anthropics/anthropic-quickstarts` repo is now **`anthropics/claude-quickstarts`**. Its macOS-native reference lives at `computer-use-best-practices/`, uses tool type `computer_20250124` (beta `computer-use-2025-01-24`), and its README strongly discourages running outside a VM.

### Known dead ends (do not re-propose)
Ultraleap TouchFree binary (Windows-only, archived, all 11 forks dead); BetterTouchTool (dropped Leap at v1.89, 2018); the Airspace/V2-SDK ecosystem; MediaPipe Gesture Recognizer (image-in only); PyAutoGUI (dead + 76 Hz ceiling); Jackknife (UCF non-commercial licence + US 10,133,949 B2); HandVector (visionOS-only `Package.swift`); Heliox-OS (no Leap, broken macOS auth); Hammerspoon (second TCC identity + warp bug #3332); yabai/skhd (ownership transfer + SIP); `leaprs`/`leap-sys` (Gemini 5.6.1, Linux/Windows); `LeapJna` (caps at SDK 5.6.1.0); `LeapCxx` (LeapSDK 4.0 shim); `google/project-gameface` (archived, face-based); `campoy/leap` (2014, dead WebSocket API); the entire pre-2015 GitHub Leap-gesture corpus (targets the removed V2 Gesture API — Ultraleap deleted it because fixed built-in gestures had unacceptable false-positive rates, which is itself the argument for the layered heuristic design above **and** for the false-positive budget in Phase 0.5).