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


@dataclasses.dataclass
class Step:
    label: str
    instruction: str
    seconds: float


PROTOCOL = [
    Step("rest", "Rest your hand flat on the desk, in front of the device", 4),
    Step("hover", "Hold your hand at a comfortable working height, still", 4),
    Step("roam", "Move your hand around the whole area you'd want to reach", 6),
    Step("pinch", "Pinch thumb+index together and HOLD", 4),
    Step("open", "Open your hand flat, fingers spread", 4),
    Step("fist", "Close a full fist and HOLD", 4),
    Step("two_finger", "Index + middle extended, others curled. Move up and down", 5),
    Step("swipe", "Swipe left and right, briskly, about 4 times", 6),
]


def _flatten(frame: HandFrame) -> dict:
    d = dataclasses.asdict(frame)
    for key in ("palm", "palm_stable", "palm_velocity", "palm_normal", "palm_direction"):
        v = d.pop(key)
        d[f"{key}_x"], d[f"{key}_y"], d[f"{key}_z"] = v["x"], v["y"], v["z"]
    d.pop("fingertips", None)
    d["extended"] = list(d["extended"])
    return d


def capture(path: str, hand: str) -> int:
    rows: list[dict] = []
    current: Optional[str] = None

    def on_snapshot(snap: Snapshot) -> None:
        frame = snap.get(hand)
        if frame is not None and current is not None:
            rows.append({"step": current, **_flatten(frame)})

    source = LeapSource()
    source.subscribe(on_snapshot)

    print(f"Recording {hand.lower()} hand. Follow each prompt.\n")
    with source.open():
        for step in PROTOCOL:
            print(f"  {step.instruction}")
            for n in (3, 2, 1):
                print(f"    starting in {n}...", end="\r", flush=True)
                time.sleep(1)
            current = step.label
            print(f"    RECORDING {step.seconds:.0f}s ......", end="", flush=True)
            time.sleep(step.seconds)
            current = None
            got = sum(1 for r in rows if r["step"] == step.label)
            print(f" {got} frames" + ("  <-- NO HAND SEEN" if got == 0 else ""))

    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"\nwrote {len(rows)} frames to {path}")
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
        y, pd, gs = col(step, "palm_stable_y"), col(step, "pinch_distance"), col(step, "grab_strength")
        print(f"{step:<12} {len(rows):>5}  "
              f"{_pct(y,5):>6.0f} {statistics.median(y):>6.0f} {_pct(y,95):>6.0f}  "
              f"{_pct(pd,5):>5.0f} {statistics.median(pd):>5.0f} {_pct(pd,95):>5.0f}  "
              f"{statistics.median(gs):>11.2f}")
    print("\n(columns show p5 / median / p95)\n")

    print("=== recommended thresholds ===")
    rest_y = col("rest", "palm_stable_y")
    hover_y = col("hover", "palm_stable_y") + col("roam", "palm_stable_y")
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
        print(f"  swipe_speed   = {(_pct(swipe_v,75)+_pct(roam_v,99))/2:>6.0f}   "
              f"(swipe p75 {_pct(swipe_v,75):.0f}, roam p99 {_pct(roam_v,99):.0f})")
        if _pct(roam_v, 99) > _pct(swipe_v, 75):
            print("    WARNING: roaming is as fast as swiping — swipes will misfire.")

    # The interaction box should be what the hand actually reached, not a guess.
    rx = col("roam", "palm_stable_x")
    rz = col("roam", "palm_stable_z")
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
    ana = sub.add_parser("analyze")
    ana.add_argument("path")
    args = ap.parse_args(argv)
    return capture(args.out, args.hand) if args.cmd == "capture" else analyze(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
