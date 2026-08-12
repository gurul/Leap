"""Guided capture: record real hand data so thresholds come from measurement.

The defaults in `gestures.Config` are educated guesses. Hands differ, desks differ,
and a v1 controller's noise floor is not the same as an LMC2's. This walks the user
through a short scripted protocol, saves every frame as JSONL, and reports the
distributions needed to set each threshold.

    python -m leapinput.record capture  -o session.jsonl
    python -m leapinput.record analyze  session.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import time
from collections import defaultdict
from typing import Optional

from .capture import HandFrame, LeapSource, Snapshot
from .viz import BOLD, DIM, GREEN, RED, RESET, LivePanel, _safe


@dataclasses.dataclass
class Step:
    label: str
    instruction: str
    seconds: float
    # Signature the captured frames must satisfy, as (description, predicate over
    # the step's median frame). A timed protocol silently records the *previous*
    # pose if the user is slower than the countdown — that produced a full
    # one-step label shift on 2026-08-12, and every threshold derived from it was
    # wrong in a way that looked plausible. Each step now proves it captured what
    # it claims, and says so at record time rather than in analysis.
    expect: Optional[tuple] = None


# Predicates take a HandFrame so the same check drives the live panel and the
# post-capture validation. One definition, so what you watch is what is enforced.
PROTOCOL = [
    Step("rest", "Rest your hand flat on the desk, in front of the device", 3),
    Step("hover", "Hold your hand still at a comfortable working height", 4,
         ("hand in view, steady", lambda f: f.position.y > 80)),
    Step("roam", "Move your hand around the whole area you'd want to reach", 6,
         ("hand in view", lambda f: f.position.y > 60)),
    Step("pinch", "Pinch thumb+index firmly together and HOLD", 4,
         ("thumb+index close", lambda f: f.pinch_distance < 40)),
    Step("open", "Open your hand flat, fingers spread wide", 4,
         ("4+ fingers extended", lambda f: sum(f.extended) >= 4)),
    Step("fist", "Close a tight fist and HOLD", 4,
         ("fingers curled", lambda f: sum(f.extended) <= 1 and f.grab_strength > 0.5)),
    Step("two_finger", "Index + middle extended, others curled. Move up and down", 5,
         ("index+middle only", lambda f: f.extended[1] and f.extended[2]
          and not f.extended[3] and not f.extended[4])),
    Step("swipe", "Swipe left and right, briskly, about 4 times", 6,
         ("fast sideways motion", lambda f: abs(f.palm_velocity.x) > 150)),
]


def _flatten(frame: HandFrame) -> dict:
    d = dataclasses.asdict(frame)
    for key in ("palm", "palm_stable", "palm_velocity", "palm_normal", "palm_direction"):
        v = d.pop(key)
        d[f"{key}_x"], d[f"{key}_y"], d[f"{key}_z"] = v["x"], v["y"], v["z"]
    d.pop("fingertips", None)
    d["extended"] = list(d["extended"])
    return d


def _await_pose(source: LeapSource, hand: str, step: Step, gate: str,
                hold: float = 0.6, timeout: float = 45.0) -> bool:
    """Block until the user is actually in the pose, then return.

    This is what removes the whole class of bug that wrecked the first session.
    A countdown makes the human race the protocol; waiting for the pose makes the
    protocol wait for the human. The step cannot start early, so it cannot record
    the previous pose.
    """
    if gate == "enter":
        input("    press Enter when ready > ")
        return True

    if step.expect is None:                 # steps with no signature (rest) just pause
        print("    ...", end="", flush=True)
        time.sleep(2.0)
        print(" go")
        return True

    desc, predicate = step.expect
    deadline = time.monotonic() + timeout
    steady_since: Optional[float] = None

    while time.monotonic() < deadline:
        frame = source.latest.get(hand)
        ok = frame is not None and _safe(predicate, frame)
        now = time.monotonic()
        if ok:
            steady_since = now if steady_since is None else steady_since
            if now - steady_since >= hold:
                print(f"\r    {GREEN}✓{RESET} {desc}"
                      f"{' ' * 40}")
                return True
        else:
            steady_since = None
        held = 0.0 if steady_since is None else now - steady_since
        print(f"\r    {_status_line(frame, desc, ok, held, hold)}",
              end="", flush=True)
        time.sleep(0.05)

    print(f"\r    {RED}✗ TIMEOUT{RESET} waiting for {desc}{' ' * 30}")
    return False


def _status_line(frame: Optional[HandFrame], desc: str, ok: bool,
                 held: float, hold: float) -> str:
    """One line of live feedback. Compact enough to update in place without
    fighting the scrolling step log, unlike the full panel."""
    if frame is None:
        return f"{RED}no hand{RESET}  waiting for: {desc}{' ' * 20}"
    p = frame.position
    bar = "▰" * int(held / hold * 6) + "▱" * (6 - int(held / hold * 6))
    mark = f"{GREEN}✓{RESET}" if ok else f"{DIM}·{RESET}"
    return (f"{mark} x{p.x:>+5.0f} y{p.y:>+5.0f} z{p.z:>+5.0f}  "
            f"{DIM}pinch{RESET}{frame.pinch_distance:>3.0f} "
            f"{DIM}grab{RESET}{frame.grab_strength:>4.2f} "
            f"{DIM}ext{RESET}{sum(frame.extended)}  "
            f"{bar} {desc}{' ' * 8}")


def capture(path: str, hand: str, gate: str = "auto") -> int:
    rows: list[dict] = []
    frames: dict[str, list[HandFrame]] = {}
    current: Optional[str] = None

    def on_snapshot(snap: Snapshot) -> None:
        frame = snap.get(hand)
        if frame is not None and current is not None:
            rows.append({"step": current, **_flatten(frame)})
            frames.setdefault(current, []).append(frame)

    source = LeapSource()
    source.subscribe(on_snapshot)

    print(f"Recording {hand.lower()} hand.")
    if gate == "enter":
        print("Get into each pose, wait for the green ✓ MATCH, then press Enter.\n")
    else:
        print("Just get into each pose and hold it. Recording starts by itself.\n")
    warnings: list[str] = []

    with source.open():
        panel = LivePanel(source, hand)
        if gate == "enter":
            panel.start()          # nothing scrolls while we block on input()
        try:
            for step in PROTOCOL:
                panel.target = step.expect
                print(f"\n  {BOLD}{step.instruction}{RESET}")

                if not _await_pose(source, hand, step, gate):
                    warnings.append(f"{step.label}: timed out waiting for the pose")
                    print("    !! timed out waiting for the pose — skipping")
                    continue

                current = step.label
                print(f"    recording {step.seconds:.0f}s ...", end="", flush=True)
                time.sleep(step.seconds)
                current = None

                captured = frames.get(step.label, [])
                expected_frames = step.seconds * 100
                print(f" {len(captured)} frames")

                if step.label == "rest":
                    # The device cannot see a hand resting on the desk — it sits below
                    # the tracking volume. Zero frames is the expected, useful result.
                    print("      (0 expected — a resting hand is invisible to the"
                          " device, which is what makes it a free disengage)"
                          if not captured else
                          f"      note: {len(captured)} frames seen while 'resting'")
                    continue

                if not captured:
                    warnings.append(f"{step.label}: NO FRAMES — hand not seen")
                    print("      !! no frames captured")
                    continue
                if len(captured) < expected_frames * 0.6:
                    rate = len(captured) / step.seconds
                    warnings.append(f"{step.label}: only {len(captured)} frames "
                                    f"(~{rate:.0f} fps) — hand kept leaving view")
                    print(f"      !! sparse: ~{rate:.0f} fps, expected ~100")

                if step.expect:
                    desc, predicate = step.expect
                    hits = sum(1 for f in captured if _safe(predicate, f))
                    ratio = hits / len(captured)
                    if ratio < 0.7:
                        warnings.append(f"{step.label}: pose held for only "
                                        f"{ratio*100:.0f}% of frames ({desc})")
                        print(f"      !! pose check FAILED — {desc} true for only "
                              f"{ratio*100:.0f}% of frames")
                    else:
                        print(f"      pose check ok — {desc} "
                              f"({ratio*100:.0f}% of frames)")
        finally:
            panel.stop()

    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"\nwrote {len(rows)} frames to {path}")

    if warnings:
        print("\n=== PROBLEMS — thresholds from this session would be wrong ===")
        for w in warnings:
            print(f"  {w}")
        print("Re-run the affected steps before trusting `analyze`.")
        return 2
    print("all steps validated")
    return 0 if rows else 1


def _pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]


def analyze(path: str) -> int:
    by_step: dict[str, list[dict]] = defaultdict(list)
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            by_step[row["step"]].append(row)

    if not by_step:
        print("no data", file=sys.stderr)
        return 1

    def col(step: str, key: str) -> list[float]:
        return [r[key] for r in by_step.get(step, [])]

    print(f"{'step':<12} {'n':>5}  {'palm_y (mm)':>22}  {'pinch_dist':>18}  {'grab':>12}")
    print("-" * 78)
    for step in (s.label for s in PROTOCOL):
        rows = by_step.get(step, [])
        if not rows:
            print(f"{step:<12} {0:>5}  (no frames)")
            continue
        y, pd, gs = col(step, "palm_y"), col(step, "pinch_distance"), col(step, "grab_strength")
        print(f"{step:<12} {len(rows):>5}  "
              f"{_pct(y,5):>6.0f} {statistics.median(y):>6.0f} {_pct(y,95):>6.0f}  "
              f"{_pct(pd,5):>5.0f} {statistics.median(pd):>5.0f} {_pct(pd,95):>5.0f}  "
              f"{statistics.median(gs):>11.2f}")
    print("\n(columns show p5 / median / p95)\n")

    print("=== recommended thresholds ===")
    rest_y = col("rest", "palm_y")
    hover_y = col("hover", "palm_y") + col("roam", "palm_y")
    if rest_y and hover_y:
        # Engage above where the hand rests, release below where it works.
        engage = (_pct(rest_y, 95) + _pct(hover_y, 5)) / 2
        print(f"  engage_y      = {engage:>6.0f}   (rest p95 {_pct(rest_y,95):.0f}, "
              f"hover p5 {_pct(hover_y,5):.0f})")
        print(f"  release_y     = {engage * 0.7:>6.0f}")

    pinch_d, open_d = col("pinch", "pinch_distance"), col("open", "pinch_distance")
    if pinch_d and open_d:
        print(f"  pinch_on_mm   = {_pct(pinch_d,95):>6.0f}   "
              f"(pinched p95; open p5 is {_pct(open_d,5):.0f})")
        print(f"  pinch_off_mm  = {(_pct(pinch_d,95)+_pct(open_d,5))/2:>6.0f}")

    fist_g, open_g = col("fist", "grab_strength"), col("open", "grab_strength")
    if fist_g and open_g:
        print(f"  grab_on       = {_pct(fist_g,5):>6.2f}   "
              f"(fist p5; open p95 is {_pct(open_g,95):.2f})")
        print(f"  grab_off      = {(_pct(fist_g,5)+_pct(open_g,95))/2:>6.2f}")

    swipe_v = [abs(r["palm_velocity_x"]) for r in by_step.get("swipe", [])]
    roam_v = [abs(r["palm_velocity_x"]) for r in by_step.get("roam", [])]
    if swipe_v and roam_v:
        # A swipe is a transient burst, so compare its PEAK against roaming's
        # ceiling. Comparing medians or quartiles compares a burst's average to a
        # sustained motion's average and spuriously reports overlap — that false
        # alarm nearly got swipes cut on 2026-08-12.
        peak, ceiling = _pct(swipe_v, 95), max(roam_v)
        print(f"  swipe_speed   = {(peak + ceiling) / 2:>6.0f}   "
              f"(swipe peak p95 {peak:.0f}, roam ceiling {ceiling:.0f})")
        if ceiling >= peak:
            print("    WARNING: roaming reaches swipe speed — swipes will misfire.")
        else:
            print(f"    headroom {peak - ceiling:.0f} mm/s between roam and swipe")

    # The interaction box should be what the hand actually reached, not a guess.
    rx = col("roam", "palm_x")
    rz = col("roam", "palm_z")
    if rx and rz:
        print(f"  Mapping x_min = {_pct(rx,5):>6.0f} , x_max = {_pct(rx,95):>6.0f}")
        print(f"  Mapping z_far = {_pct(rz,5):>6.0f} , z_near = {_pct(rz,95):>6.0f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput.record")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("-o", "--out", default="session.jsonl")
    cap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    cap.add_argument("--gate", choices=("auto", "enter"), default="auto",
                     help="auto waits until you hold the pose; enter waits for a keypress")
    ana = sub.add_parser("analyze")
    ana.add_argument("path")
    args = ap.parse_args(argv)
    return (capture(args.out, args.hand, args.gate) if args.cmd == "capture"
            else analyze(args.path))


if __name__ == "__main__":
    raise SystemExit(main())
