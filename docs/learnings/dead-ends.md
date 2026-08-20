# Dead ends

Already tried, already measured, already rejected. Read this before proposing
anything — several of these look obviously right and were reverted with
numbers.

This is different from [restoring.md](restoring.md): those things are shelved
and expected to come back. These are not.

---

## In the vocabulary

**Swipes.** Velocity separation is real — roaming peaks at 419 mm/s, a swipe at
803 — and irrelevant, because the swipe motion carries the hand out of the
tracking volume and trips the dead-man. A live 60 s session fired `swipe.right`
and `swipe.down` unintentionally, and `swipe.down` landed immediately before a
disengage. The enum names are kept so recorded sessions still decode. **Do not
re-propose without a tracking volume that survives the motion.** (a2059a7)

**Rate-controlled scroll.** One event per tracking frame at 110 Hz, and it kept
firing for as long as the fist was held: measured at **~7,700 px/sec** — about
seven pages a second, 447 events in one 60 s session. Displacement control from
an anchor cannot run away: move the hand 10 mm and the page moves a fixed
amount; hold still and it stops. (37d923a)

**Scroll on the index+middle pose.** Near-identical to natural pointing once
the index fingertip drives the cursor: **61 scroll events fired inside a single
clutch** purely from pointing. Pointing and scrolling cannot be made
digit-disjoint while the index is the pointer. Scroll then moved to the fist,
and was removed from the fist too, because a fist is a drag. **Scroll has no
home, and one pose must not carry two meanings.** (63161f2, caa53ad)

**The palm-angle clutch.** It works — 18.9° median against a 30° cone — but it
drifts: observed at 66° in another session, freezing the cursor with no
recourse. Finger count is the more stable signal. Still available via
`clutch_mode="palm"`. ([interaction.md:147-149](../context/interaction.md))

**Sustained pose holds for dictation.** Shaka-hold cramped; thumbs-up-hold was
unsustainable and drifted the hand out of view. The ergonomics literature
prescribes short deliberate poses over sustained static holds. It is a toggle
now. (`commands.py:23-30`)

---

## In the mapping

**Absolute mapping on the Leap.** The measured envelope is a wide, shallow,
right-shifted slab (x −24..+214 mm, z +15..+84 mm) — z never went negative
once, so the top half of the screen was unreachable by construction, and
reaching a screen edge pushed the hand to the edge of tracking. One 60 s live
run **lost tracking five times**. Absolute only became viable on the camera,
where a *fitted* box supplies one comfortable screen-shaped region. (a2059a7)

**Fixed-position reach boxes.** Died in first contact — the user had to return
the hand to one spot in space. Kept as `reach anchor fixed` because it is the
only way to get a **learnable** projection, but it is not the default.
(f819df5)

**Slack coordinates beyond the box** (the alternative to the drag-along sheet).
A three-agent audit found it required disabling the eccentricity edge guard
(slack corners reach 82° against the 62° freeze), created a disengage foot-gun
under `--plane xz`, and let phantom overshoot accumulate in the absolute filter
state. All structurally absent under the drag.

**Edge-zone gain boost.** Rejected in the 2026-08-19 edge-reach research:
nonlinear stretch breaks the touch model's position-faithfulness and puts
maximum noise gain exactly where MediaPipe is worst. Vogel & Balakrishnan's
absolute ray-casting was abandoned at 22% error.

**A low gain floor as "precision".** Four tuning passes settled it: low
control-display gain measurably *hurts* pointing — more clutching, higher limb
speeds — and pointer acceleration beats constant gain by 3.3–5.6%, most on
small targets. *A low floor is not precision, it is just slow.* (a0d07da)

**A 0.3 Hz 1-euro floor at 30 fps.** ~530 ms of group delay at slow speed — the
"syrup then overshoot" mode `plan.md` had explicitly warned about. The shipped
answer is `min_cutoff 1.5` with `beta 0.03` and `d_cutoff 2.0`.

**An unconditional 2× camera DPI boost.** It stacked multiplicatively on the
reach-box zoom, reaching ~14 px per *physical* mm at rest — landmark noise
painted as 8–12 px cursor hops. The zoom **is** the DPI at a fitted box:
`boost = max(1, BOOST/zoom)`.

**A velocity gate on pinch commit.** Rejected on data: one deliberate pinch
descended at 0.8 mm per 5 frames and still bottomed at 13.8 pseudo-mm, so a
velocity gate would break real slow clicks. **Depth** separates deliberate
pinches from rest-band drift; speed does not.
([phantom-clicks-2026-08-19.md](../context/phantom-clicks-2026-08-19.md))

**Disabling PRISM to fix the bench x-bias.** Refuted with prejudice by an
adversarial verifier: *"the stated mechanism is arithmetically false; the
claimed numbers do not reproduce; and the proposed fix would CREATE the exact
symptom under investigation."*

---

## In the pipeline

**Capping the detection rate.** A 20 Hz budget measured ~30% CPU → ~17% and was
reverted anyway: it made the two-hand frame shot flicker, because MediaPipe
seeds each detection from the previous frame's region. `--detect-hz N` is still
there; it would still be wrong for the frame shot. (757adb2 → 31297f3)

**Depth Anything (TDDepthAnything) for a Z axis.** Rejected as a dependency:
PyTorch plus tens of ms/frame against a 30 fps budget, and relative-not-metric
output. Apparent knuckle span gives the same benefit for free.

**PyAutoGUI for injection.** A hardcoded `DARWIN_CATCH_UP_TIME` sleep caps
`moveTo` at **76 Hz** — below the 111 fps stream. It never sets `clickState`,
and its `size()` reports the main display only. `osascript ... keystroke` is
100–140 ms, ~10,000× slower than `CGEventPost`. ([plan.md §5, §8](../plan.md))

**`kCGAnnotatedSessionEventTap`.** Does not move the pointer at all (measured
700/380/850 px error). Use HID (0) or session (1).

**Server-side gesture detection on this hardware.** Hyperion 6.2 exposes
`eLeapHandFlag_GesturePinch` and friends, but `LEAP_HAND.flags` is **always 0**
across 2,419 real hand-frames — even bit 0, `GestureDetectionAvailable`, never
sets. The `microgestures` hint is recognised but matches no model available to
this device (vendor docs list it as HMD-only). **The entire gesture layer is
ours to write.** ([plan.md:104](../plan.md))

**`LeapCheckLicenseFlag` as a capability check.** A permissive stub: it returns
`enabled=True` for `"zzz_not_a_real_flag_12345"`, `"__nope__"` and the empty
string. Never gate a capability on it.

**Rewriting the hot loop in Swift.** Every hot-path operation is µs-scale —
1-euro 0.74 µs, `CGEventPost` 10.4 µs, AX read 26 µs — against a 9,030 µs frame
budget. The latency case does not survive measurement.

**Skipped deliberately in the latency pass:** L4S/SCReAM (no queue on one LAN
hop), RTMP/SRT/NDI (unreachable from a browser), busy-polling (GIL fights),
allocator swaps (GC was the pause source, not obmalloc), the MediaPipe GPU
delegate (marginal on macOS plus a known M-series leak), aiortc VideoToolbox
decode (software VGA decode is ~2 ms).

---

## The Leap ecosystem

Verified 2026-08-12. Re-verify before trusting after any Hyperion or macOS
update. ([environment.md:82-92](../context/environment.md))

| Thing | Status |
|---|---|
| Ultraleap **TouchFree** (the official touchless-cursor product) | Windows only, v2.6.1 (20.05.2024). No Mac build exists; the repo was archived 2023-04-21 with all 11 forks dead by 2023 |
| **BetterTouchTool** Leap support | Removed in v1.89 (2018); developer cited an unsupported framework and near-zero usage. Never restored |
| Airspace / V2-SDK apps (PyLeapMouse, GameWAVE) | Target the dead 32-bit-era V2 SDK; will not run on modern macOS |
| Ultraleap **Gemini 5.x** | Superseded and no longer distributed. 6.2 is better on Apple Silicon (though *worse* than 5.2 on Intel) |
| `ultraleap/leapc-python-bindings` | Gemini-era, links `libLeapC.5`; Hyperion ships `.6`. Use the DDlabAU fork |

**Also:** `system_profiler SPUSBDataType | grep -i leap` returns **nothing**
while the tracking service holds the device open. Do not use it as a presence
check — use `leap.get_server_status()`.

One unresolved disagreement in the docs, flagged rather than settled:
[sources.md:140-142](../sources.md) and
[environment.md:71](../context/environment.md) tell you to use the DDlabAU
fork, while [plan.md:397](../plan.md) argues for upstream on the grounds that
"the fork's entire delta is 2 string literals in build scripts the prebuilt
path bypasses". The fork is what is verified working here.

---

## Things that are *not* dead ends, despite looking like them

- **Pinch as a click signal.** Weak on the Leap's `pinch_strength` — but pinch
  **distance** separates by 65 mm, which is what the thresholds use.
- **The reach box.** Its projection problem is real and unresolved, but the box
  itself is measured, guarded and reversible.
- **The phone source.** Shelved for background-machinery reasons, not
  technical ones. It is still the fastest source this project has.
- **The depth companion.** Scaffolded and proven live at phase 1; phase 2 was
  never built. It is the roadmap unlock, not a rejected idea.
