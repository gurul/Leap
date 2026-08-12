"""Which gate is blocking? Measures every stage of the pipeline against a live hand.

"It doesn't work" has at least four distinct causes — no tracking, no engagement,
no clutch, no motion — and they need different fixes. This reports each stage's
pass rate over a live sample, plus the clutch angle against BOTH plane references,
so the answer is a number rather than a theory.

    python -m leapinput.doctor            # 10s sample
"""

from __future__ import annotations

import argparse
import statistics
import time

from .capture import LeapSource, Snapshot
from .gestures import CLUTCH_REFERENCE, Config, palm_angle_degrees


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput.doctor")
    ap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args(argv)

    cfg = Config()
    samples: list = []
    total = {"frames": 0}

    def on_snapshot(snap: Snapshot) -> None:
        total["frames"] += 1
        frame = snap.get(args.hand)
        if frame is not None:
            samples.append(frame)

    source = LeapSource()
    source.subscribe(on_snapshot)

    print(f"Hold your hand over the device however you have been trying to use it.")
    print(f"Sampling {args.seconds:.0f}s ...\n")
    with source.open():
        time.sleep(args.seconds)

    frames, seen = total["frames"], len(samples)
    if not frames:
        print("FAIL: no tracking frames at all — the service is not delivering data.")
        return 1

    print(f"1. tracking      {frames} frames "
          f"({frames / args.seconds:.0f} fps)")
    pct = 100.0 * seen / frames
    print(f"2. hand visible  {seen}/{frames} frames ({pct:.0f}%)"
          + ("" if pct > 60 else "   <-- POOR: the pose is hard for the sensor to see"))
    if not seen:
        print("\nThe device never saw a", args.hand.lower(), "hand.")
        return 1

    ys = [f.position.y for f in samples]
    print(f"3. height        y median {statistics.median(ys):.0f}mm "
          f"(min {min(ys):.0f}, max {max(ys):.0f})")
    for plane, floor in (("xy", cfg.engage_y_xy), ("xz", cfg.engage_y)):
        ok = sum(1 for y in ys if y >= floor)
        print(f"     plane {plane}: {100.0*ok/len(ys):>3.0f}% above the {floor:.0f}mm floor")

    print("4. clutch angle  (needs <= "
          f"{cfg.clutch_on_deg:.0f} deg to engage, releases past "
          f"{cfg.clutch_off_deg:.0f})")
    best = None
    for plane, ref in CLUTCH_REFERENCE.items():
        angles = [palm_angle_degrees(f, ref) for f in samples]
        engageable = 100.0 * sum(1 for a in angles if a <= cfg.clutch_on_deg) / len(angles)
        print(f"     plane {plane} (palm {'forward' if plane == 'xy' else 'down'}): "
              f"median {statistics.median(angles):>5.1f} deg, "
              f"{engageable:>3.0f}% of frames could clutch")
        if best is None or engageable > best[1]:
            best = (plane, engageable)

    # Which hand axes actually carry signal, and what the driver makes of them.
    from .driver import DirectDriver, Mapping
    from .actions import DryRunBackend
    from .gestures import Intent, IntentEvent

    print("5. axis travel   how far each hand axis actually moved")
    for name, vals in (("x (left/right)", [f.track_point("index").x for f in samples]),
                       ("y (up/down)   ", [f.track_point("index").y for f in samples]),
                       ("z (depth)     ", [f.track_point("index").z for f in samples])):
        span = max(vals) - min(vals)
        flag = "" if span > 20 else "   <-- barely moved"
        print(f"     {name}  span {span:>6.0f}mm  "
              f"[{min(vals):>6.0f} .. {max(vals):>6.0f}]{flag}")

    print("6. cursor result what the driver produces from those frames")
    for plane in ("xy", "xz"):
        backend = DryRunBackend(bounds=(0.0, 0.0, 1512.0, 982.0))
        driver = DirectDriver(backend, Mapping(plane=plane))
        driver.on_intent(IntentEvent(Intent.CLUTCH_DOWN, 0.0, samples[0]))
        xs, ys = [], []
        for f in samples:
            driver.on_intent(IntentEvent(Intent.POINT_MOVE, f.timestamp / 1e6, f))
            xs.append(driver.x)
            ys.append(driver.y)
        print(f"     plane {plane}: cursor x moved {max(xs)-min(xs):>5.0f}px, "
              f"y moved {max(ys)-min(ys):>5.0f}px"
              + ("" if max(ys) - min(ys) > 30 else "   <-- UP/DOWN IS DEAD"))

    print("\n=== diagnosis ===")
    if pct < 60:
        print(f"  The sensor only sees your hand {pct:.0f}% of the time. The device")
        print("  looks UP from the desk, so a hand held edge-on presents a thin")
        print("  profile and tracking drops out. Angle the palm more toward the")
        print("  device, or use --plane xz with the hand flat above it.")
    if best and best[1] < 20:
        print(f"  No plane's clutch is reachable in this posture (best: {best[0]} at")
        print(f"  {best[1]:.0f}%). The cursor cannot move, because the clutch gates it.")
        print("  Rotate the palm to face the clutch direction, or raise")
        print(f"  --clutch-deg above the median angle shown above.")
    elif best:
        print(f"  Best plane for the posture you just used: --plane {best[0]} "
              f"({best[1]:.0f}% clutchable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
