"""Guided camera calibration: record YOUR hand, fit YOUR thresholds.

The pose thresholds in camera.Tuning default to educated guesses. This walks you
through a short scripted protocol in the preview window (each pose prompted on
screen, several rounds), records the RAW pose signals for every frame — per-finger
PIP bends, thumb ratio, span-normalized pinch distance — then fits the thresholds
from the measured distributions, exactly the way the Leap thresholds in
gestures.Config were derived from a recorded corpus.

    python -m leapinput.calibrate capture            # record + fit + save
    python -m leapinput.calibrate analyze session.jsonl   # refit an old session

Fitting rule, per signal: take the two populations that must be separated (e.g.
finger bends when a finger should read extended vs curled), find the gap between
the 95th percentile of one and the 5th of the other, and place the Schmitt band
inside that gap. No gap = that signal stays at its default, loudly.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from collections import defaultdict
from pathlib import Path

from .camera import CameraSource, Tuning

SESSION_PATH = Path(__file__).resolve().parents[2] / "camera_session.jsonl"

# label, on-screen instruction, seconds of recording. "apart" exists because the
# pinch Schmitt's OFF threshold lives between a held pinch and a ready-to-pinch
# hover — the two postures a real click cycles between. Without it the release
# threshold would be fitted against a wide-open hand it never sees in practice.
STEPS = (
    ("open",  "Spread all FIVE fingers wide. Move slowly around the frame", 6.0),
    ("point", "INDEX finger only, curl the rest. Move slowly around", 6.0),
    ("apart", "Thumb and index apart ~3cm, ready to pinch. Hold steady", 5.0),
    ("pinch", "PINCH thumb+index firmly. HOLD. Move slowly around", 6.0),
    ("fist",  "Close a TIGHT fist. HOLD. Move slowly around", 6.0),
)
READY_SECONDS = 2.5


# --- capture -------------------------------------------------------------------

def _banner(cv2, bgr, phase: str, instruction: str, left: float,
            rnd: int, rounds: int, collected: int) -> None:
    h, w = bgr.shape[:2]
    cv2.rectangle(bgr, (0, 0), (w, 78), (30, 30, 30), -1)
    if phase == "record":
        cv2.circle(bgr, (18, 22), 8, (0, 0, 230), -1)
        head, color = f"RECORDING  {left:3.1f}s", (0, 0, 230)
    else:
        head, color = f"get ready  {left:3.1f}s", (0, 200, 255)
    cv2.putText(bgr, head, (34, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
                cv2.LINE_AA)
    cv2.putText(bgr, f"round {rnd}/{rounds}   {collected} frames",
                (w - 230, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200),
                1, cv2.LINE_AA)
    cv2.putText(bgr, instruction, (10, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1, cv2.LINE_AA)


def capture(out_path: Path, rounds: int, hand: str, camera_index: int) -> int:
    import cv2

    source = CameraSource(camera=camera_index, preview=True)
    state = {"label": None, "round": 0}
    rows: list[dict] = []

    def on_snapshot(snap) -> None:      # capture thread; keep it short
        if state["label"] is None:
            return
        sig = source.latest_signals.get(hand)
        frame = snap.get(hand)
        if sig is None or frame is None:
            return
        row = {
            "step": state["label"], "round": state["round"],
            "t_us": frame.timestamp,
            "bends": [round(b, 2) for b in sig.bends],
            "thumb_ratio": round(sig.thumb_ratio, 4),
            "pinch_mm": round(sig.pinch_mm, 2),
            "span_mm": round(sig.span_mm, 2),
        }
        if sig.pinch_img_mm is not None:
            row["pinch_img_mm"] = round(sig.pinch_img_mm, 2)
        rows.append(row)

    source.subscribe(on_snapshot)
    win = "leapinput calibrate (q aborts)"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    print(f"Calibrating your {hand.lower()} hand: {rounds} rounds x "
          f"{len(STEPS)} poses. Watch the window, follow the prompts.")

    aborted = False
    with source.open():
        for rnd in range(1, rounds + 1):
            for label, instruction, secs in STEPS:
                for phase, dur in (("ready", READY_SECONDS), ("record", secs)):
                    state["label"] = label if phase == "record" else None
                    state["round"] = rnd
                    end = time.monotonic() + dur
                    while time.monotonic() < end and not aborted:
                        bgr = source.preview_frame
                        if bgr is not None:
                            _banner(cv2, bgr, phase, instruction,
                                    end - time.monotonic(), rnd, rounds,
                                    len(rows))
                            cv2.imshow(win, bgr)
                        if cv2.waitKey(30) & 0xFF in (27, ord("q")):
                            aborted = True
                    if aborted:
                        break
                if aborted:
                    break
            if aborted:
                break
        state["label"] = None
    cv2.destroyAllWindows()
    cv2.waitKey(1)

    if aborted:
        print("aborted — nothing written")
        return 1
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"{len(rows)} frames -> {out_path}")
    return 0


# --- fitting -------------------------------------------------------------------

def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    i = (len(s) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _band(low_pop: list[float], high_pop: list[float], min_gap: float,
          name: str, report: list[str]):
    """Fit a Schmitt band inside the gap between two populations.

    low_pop must sit BELOW high_pop for the signal to separate. Returns
    (on, off, gap) with on at 35% and off at 70% of the gap, or None if the
    populations overlap (caller keeps its default).
    """
    lo_hi, hi_lo = _pct(low_pop, 0.95), _pct(high_pop, 0.05)
    gap = hi_lo - lo_hi
    report.append(f"  {name:12s} low p50/p95 {_pct(low_pop, .5):6.1f}/{lo_hi:6.1f}"
                  f"   high p5/p50 {hi_lo:6.1f}/{_pct(high_pop, .5):6.1f}"
                  f"   gap {gap:5.1f}")
    if gap < min_gap:
        report.append(f"  {name:12s} OVERLAP (gap < {min_gap}) — no fit")
        return None
    return lo_hi + 0.35 * gap, lo_hi + 0.70 * gap, gap


def fit(rows: list[dict]) -> tuple[Tuning, list[str]]:
    """Rows -> fitted Tuning + a human-readable report. Pure, for tests."""
    by = defaultdict(list)
    for r in rows:
        by[r["step"]].append(r)
    missing = {"open", "point", "pinch", "fist"} - set(by)
    if missing:
        raise ValueError(f"session is missing steps: {sorted(missing)}")

    report: list[str] = [f"frames per step: "
                         f"{ {s: len(v) for s, v in sorted(by.items())} }"]
    defaults = Tuning()
    fitted = {}

    # Finger bends: extended cloud = open (all four) + point (index);
    # curled cloud = fist (all four) + point (middle/ring/pinky).
    ext = [b for r in by["open"] for b in r["bends"]] \
        + [r["bends"][0] for r in by["point"]]
    curl = [b for r in by["fist"] for b in r["bends"]] \
        + [b for r in by["point"] for b in r["bends"][1:]]
    band = _band(ext, curl, 8.0, "finger bend", report)
    if band:
        fitted["extend_on_deg"], fitted["extend_off_deg"] = band[0], band[1]
        fitted["extended_max_deg"] = (band[0] + band[1]) / 2.0

    # Thumb ratio: HIGH = extended, so the populations swap roles: curled cloud
    # (fist + point, tucked thumb) must sit below the open cloud.
    t_curl = [r["thumb_ratio"] for r in by["fist"] + by["point"]]
    t_ext = [r["thumb_ratio"] for r in by["open"]]
    band = _band(t_curl, t_ext, 0.06, "thumb ratio", report)
    if band:
        # on/off are crossed for a high-means-on signal: engage above the top
        # of the band, release below the bottom.
        fitted["thumb_off_ratio"], fitted["thumb_on_ratio"] = band[0], band[1]

    # Pinch: pinched cloud must sit below the ready-to-pinch hover ("apart" +
    # point). Open-hand frames are deliberately excluded — a release threshold
    # fitted against a wide-open hand is never exercised by a real click cycle.
    # Both candidate signals are fitted — 3D world distance and 2D image
    # distance — and the wider measured gap wins (the 3D one is inflated by the
    # occluded-fingertip depth guess during a held pinch).
    apart_rows = by.get("apart", []) + by["point"]
    pinch_key = "pinch_mm"
    candidates = [("world", "pinch_mm")]
    if all(r.get("pinch_img_mm") is not None for r in by["pinch"] + apart_rows):
        candidates.append(("image", "pinch_img_mm"))
    best = None
    for source, key in candidates:
        band = _band([r[key] for r in by["pinch"]],
                     [r[key] for r in apart_rows], 10.0,
                     f"pinch {source}", report)
        if band and (best is None or band[2] > best[1][2]):
            best = ((source, key), band)
    if best:
        (source, pinch_key), band = best
        fitted["pinch_on_mm"], fitted["pinch_off_mm"] = band[0], band[1]
        fitted["pinch_source"] = source
        report.append(f"  pinch signal: {source} (wider gap)")

    tuning = dataclasses.replace(defaults, **fitted)

    # Sanity: reclassify the corpus with the fitted single-frame thresholds.
    mid_thumb = (tuning.thumb_on_ratio + tuning.thumb_off_ratio) / 2.0
    ok_open = sum(all(b < tuning.extended_max_deg for b in r["bends"])
                  and r["thumb_ratio"] > mid_thumb for r in by["open"])
    ok_fist = sum(all(b > tuning.extended_max_deg for b in r["bends"])
                  and r["thumb_ratio"] < mid_thumb for r in by["fist"])
    ok_point = sum(r["bends"][0] < tuning.extended_max_deg
                   and all(b > tuning.extended_max_deg for b in r["bends"][1:])
                   for r in by["point"])
    ok_pinch = sum(r[pinch_key] < tuning.pinch_on_mm for r in by["pinch"])
    for name, ok, total in (("open", ok_open, len(by["open"])),
                            ("fist", ok_fist, len(by["fist"])),
                            ("point", ok_point, len(by["point"])),
                            ("pinch", ok_pinch, len(by["pinch"]))):
        report.append(f"  reclassified {name:6s} {ok}/{total} "
                      f"({100.0 * ok / max(1, total):.1f}%)")
    return tuning, report


def analyze(path: Path, write: bool = True) -> int:
    rows = [json.loads(line) for line in open(path)]
    tuning, report = fit(rows)
    print("\n".join(report))
    if write:
        out = tuning.save()
        print(f"\nwrote {out}")
        print("camera source and tune_for_camera now pick this up automatically.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leapinput.calibrate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="guided recording, then fit and save")
    cap.add_argument("-o", "--out", type=Path, default=SESSION_PATH)
    cap.add_argument("--rounds", type=int, default=3)
    cap.add_argument("--hand", choices=("Left", "Right"), default="Right")
    cap.add_argument("--camera", type=int, default=0)
    cap.add_argument("--no-analyze", action="store_true",
                     help="record only; fit later with `analyze`")
    ana = sub.add_parser("analyze", help="refit thresholds from a session file")
    ana.add_argument("session", type=Path, nargs="?", default=SESSION_PATH)
    ana.add_argument("--dry-run", action="store_true",
                     help="report only, do not write camera_tuning.json")
    args = ap.parse_args(argv)

    if args.cmd == "capture":
        rc = capture(args.out, args.rounds, args.hand, args.camera)
        if rc == 0 and not args.no_analyze:
            return analyze(args.out)
        return rc
    return analyze(args.session, write=not args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
