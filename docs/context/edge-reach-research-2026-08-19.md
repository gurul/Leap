# 2026-08-19 edge-reach research — perspective, insets, and what shipped

> **Dated finding, entirely in the cursor path, which is `--legacy` as of
> 2026-08-20** ([../decisions.md](../decisions.md)). The (C-lite) ρ diagnostic
> below has **never been run with a working instrument** — the first attempt
> read `motion_scale`, which the dynamic box absorbs to a flat 1.000. Summary:
> [../learnings/screen-mapping.md](../learnings/screen-mapping.md#edge-reach).

The user cannot comfortably reach screen edges through the dynamic palm box.
A literature pass (alphaXiv/arXiv, CHI/UIST, OSS webcam-mouse practice)
evaluated four candidate fixes against the drag-along-sheet design and the
audited jitter budget. Full citations at the bottom.

## Shipped: (A) comfort inset — `Tuning.reach_inset = 0.10`

The dynamic palm box is shrunk 10 % per side (`inset_scale = 1 − 2·inset`), so
the box maps to MORE than the screen: the cursor hits the screen edge while
the hand is still comfortably inside the box, instead of exactly at its
boundary — where the drag-along slide and the edge noise-ratchet (MD-1) live.
This is the classic webcam-mouse active-region trick (`frameR = 100` on
640×480 ⇒ 16–21 % per side in reTerminal-virtual-mouse and the canonical
GeeksforGeeks AI-mouse) and Kinect's ergonomic "PhIZ" (US8659658,
US20150035750); 10 % here because the fitted box is already a comfort fit.
Effective zoom rises by 1/inset_scale ≈ 1.25×; `tune_for_camera` folds that
into every zoom-anchored knob (deadzone, gain knees, pinch arm speed, the
gain-boost top-up), keeping noise anchored to the physical hand.

## Shipped: frame-edge margin — `FRAME_EDGE_MARGIN = 0.04`

Live telemetry (2026-08-19, first session) found the actual wall: in 255
right-edge samples the drag-along box sat flush at the camera frame boundary
(`box_x1 = 1.000`), so reaching the screen edge demanded knuckles AT the
image border — fingers out of frame, extrapolated landmarks (garbage
finger-state sequences and the session's only frozen-landmark run were all
there), cursor topping out ~14px short. Both `_resolve_reach` clamps now keep
the box `FRAME_EDGE_MARGIN` clear of the boundary, so the screen edge maps to
a hand position that is still fully trackable. Trackability is the truth
gate; the frame boundary was violating it exactly at the pixels the user was
aiming for.

## Next, if edges still starve: (C-lite) span-gradient perspective correction

Hypothesis: the hand plane is tilted relative to the camera, so depth varies
across the box and equal physical steps foreshorten toward the far edge
(1D inverse perspective mapping). Free diagnostic from data telemetry already
collects: regress apparent span (`motion_scale`) against box-relative
position; ρ = span(far edge)/span(near edge). ρ ≥ ~0.9 ⇒ tilt is not the
mechanism; ρ ≤ ~0.8 ⇒ apply the Möbius unwarp per axis after box
normalization, before the [0,1] clamp:

    s = ρ·n / (1 − (1−ρ)·n)      (n = box-normalized coord; ρ=1 ⇒ identity)

~20 lines in `_to_plane`; composes with the inset and the drag-along sheet.
ρ can update online from the live span-vs-position regression (survives stand
bumps, zero ceremony).

## Held in reserve

- **(C-full) gravity-vector homography**: the phone's IMU gravity (already
  EMA-tracked in `PhoneSource.imu_gravity`) gives the desk-plane normal;
  K⁻¹-ray / plane-basis projection rectifies landmarks before
  `_resolve_reach`, leaving the box machinery unchanged. Only worth it if
  C-lite residuals show a rolled/oblique tilt axis (Ding et al. gravity
  homography; GravCal arXiv 2603.19654; MRTouch as the HCI precedent).
- **(B) 4-corner DLT homography**: `reach corners` already collects the
  points; the right role is a VALIDATION harness for C (fit H, compare its
  projective part), not the shipped mapping — a static H fights the
  drag-along sheet unless factored into fixed-projective ∘ dynamic-similarity.
- **(D) edge-zone gain boost**: rejected. Nonlinear stretch breaks the touch
  model's position-faithfulness and puts maximum noise gain where MediaPipe
  is worst; the gain literature (Nancel TOCHI 2015, CHI 2013) is about
  relative techniques, and Vogel & Balakrishnan's absolute ray-casting was
  abandoned at 22 % error. Once edges are reachable, the existing clamp makes
  edge targets effectively infinite (the "magic pixel" effect; Kasahara
  arXiv 2603.23865).

## Sources

Vogel & Balakrishnan, Distant Freehand Pointing (UIST 2005) ·
Nancel et al., Mid-Air Pointing on Ultra-Walls (TOCHI 2015) ·
Nancel et al., High-Precision Pointing on Large Walls (CHI 2013) ·
Malik & Laszlo, Visual Touchpad (ICMI 2004) · MRTouch (IEEE VR 2018) ·
Kasahara et al. arXiv 2603.23865 (edge targets) · GravCal arXiv 2603.19654 ·
Ding et al., gravity-based homography (SZTAKI) · arXiv 2212.04224 (ground
normal) · Kinect PhIZ patents US8659658, US20150035750 ·
reTerminal-virtual-mouse / GeeksforGeeks AI-mouse (frameR practice) ·
inverse perspective mapping overviews (emergentmind; vanishing-point IPM).
