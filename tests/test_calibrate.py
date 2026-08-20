"""Calibration fitting tests: synthetic corpora with known separations in,
thresholds inside the measured gaps out."""

from pathlib import Path
import random

import pytest

from leapinput.calibrate import fit
from leapinput.camera import Tuning


def rows_for(step, n, bends, thumb, pinch, pinch_img=None, jitter=2.0, seed=7):
    rng = random.Random(seed + hash(step) % 1000)
    out = []
    for _ in range(n):
        row = {
            "step": step, "round": 1, "t_us": 0,
            "bends": [b + rng.uniform(-jitter, jitter) for b in bends],
            "thumb_ratio": thumb + rng.uniform(-0.02, 0.02),
            "pinch_mm": pinch + rng.uniform(-3.0, 3.0),
            "span_mm": 55.0,
        }
        if pinch_img is not None:
            row["pinch_img_mm"] = pinch_img + rng.uniform(-3.0, 3.0)
        out.append(row)
    return out


def clean_corpus():
    """A hand with obvious separations: straight ~10 deg, curled ~130 deg,
    thumb 1.3 out / 0.6 tucked, pinch 18mm held / 70mm hovering."""
    return (
        rows_for("open", 100, [10, 10, 12, 14], 1.30, 95.0)
        + rows_for("point", 100, [12, 128, 132, 125], 0.60, 72.0)
        + rows_for("apart", 100, [15, 125, 130, 122], 0.62, 68.0)
        + rows_for("pinch", 100, [40, 120, 128, 120], 0.70, 18.0)
        + rows_for("fist", 100, [130, 140, 138, 135], 0.55, 25.0)
    )


def test_fit_places_bands_inside_the_measured_gaps():
    tuning, report = fit(clean_corpus())
    # Finger band: between the extended cloud (~<45 with pinch index) and the
    # curled cloud (~>118).
    assert 47.0 < tuning.extend_on_deg < tuning.extend_off_deg < 120.0
    # Thumb: on above off, both between tucked (~0.72 max) and open (~1.28 min).
    assert 0.70 < tuning.thumb_off_ratio < tuning.thumb_on_ratio < 1.30
    # Pinch: band between held (~21 max) and hover (~65 min), on below off.
    assert 21.0 < tuning.pinch_on_mm < tuning.pinch_off_mm < 66.0
    assert tuning.pinch_source == "world"      # only signal present in corpus


def test_fit_prefers_the_image_pinch_when_the_world_signal_overlaps():
    # 3D world pinch inflated by occlusion: held ~38mm vs hover ~40-45 —
    # overlapping, like the measured 2026-08-12 session. Image signal clean.
    corpus = (
        rows_for("open", 80, [10, 10, 12, 14], 1.30, 95.0, pinch_img=90.0)
        + rows_for("point", 80, [12, 128, 132, 125], 0.60, 45.0, pinch_img=60.0)
        + rows_for("apart", 80, [15, 125, 130, 122], 0.62, 40.0, pinch_img=55.0)
        + rows_for("pinch", 80, [40, 120, 128, 120], 0.70, 38.0, pinch_img=6.0)
        + rows_for("fist", 80, [130, 140, 138, 135], 0.55, 25.0, pinch_img=15.0)
    )
    tuning, report = fit(corpus)
    assert tuning.pinch_source == "image"
    assert 9.0 < tuning.pinch_on_mm < tuning.pinch_off_mm < 53.0
    assert any("pinch world" in line and "OVERLAP" in line for line in report)


def test_fit_reports_high_reclassification_on_a_clean_corpus():
    _, report = fit(clean_corpus())
    accuracies = [line for line in report if "reclassified" in line]
    assert len(accuracies) == 4
    assert all("100.0%" in line for line in accuracies), accuracies


def test_fit_keeps_defaults_when_populations_overlap():
    # Same bends everywhere: no finger separation exists, so the finger band
    # must stay at the defaults instead of fitting garbage.
    corpus = (
        rows_for("open", 50, [60, 60, 60, 60], 1.30, 95.0)
        + rows_for("point", 50, [60, 60, 60, 60], 0.60, 72.0)
        + rows_for("pinch", 50, [60, 60, 60, 60], 0.70, 18.0)
        + rows_for("fist", 50, [60, 60, 60, 60], 0.55, 25.0)
    )
    tuning, report = fit(corpus)
    d = Tuning()
    assert tuning.extend_on_deg == d.extend_on_deg
    assert tuning.extend_off_deg == d.extend_off_deg
    assert any("OVERLAP" in line for line in report)


def test_fit_requires_the_core_steps():
    with pytest.raises(ValueError, match="missing steps"):
        fit(rows_for("open", 10, [10, 10, 10, 10], 1.3, 95.0))


def test_tuning_round_trips_through_json(tmp_path):
    t = Tuning(extend_on_deg=48.5, pinch_on_mm=31.0)
    p = t.save(tmp_path / "tuning.json")
    loaded = Tuning.load(p)
    assert loaded == t
    assert Tuning.load(tmp_path / "missing.json") == Tuning()


def test_fit_preserves_setup_calibration(tmp_path):
    """Refitting pose thresholds must never wipe the reach box, working
    distance, hand span, or anchor mode — the live bug this pins: fit()
    built its result from DEFAULT Tuning, so one `calibrate analyze` would
    have silently destroyed the whole setup calibration."""
    import json as _json

    from leapinput.calibrate import fit

    # This corpus is gitignored (it describes a hand, not the project) and was
    # opened by a bare relative path, so the test failed on a fresh clone and
    # from any cwd but the repo root — the one test in the suite that needed
    # a machine to have been used before. Resolve it from the repo, and skip
    # rather than fail when it is genuinely absent.
    corpus = Path(__file__).resolve().parents[1] / "camera_session.jsonl"
    if not corpus.exists():
        pytest.skip(f"no recorded camera corpus at {corpus} "
                    f"(python -m leapinput.calibrate capture)")
    rows = [_json.loads(line) for line in corpus.open()]
    base = Tuning(reach_x0=0.55, reach_y0=0.48, reach_x1=0.85, reach_y1=0.79,
                  ref_span_img=0.058, hand_span_mm=72.0, reach_center="palm")
    tuning, _ = fit(rows, base=base)
    assert tuning.reach == (0.55, 0.48, 0.85, 0.79)
    assert tuning.ref_span_img == 0.058
    assert tuning.hand_span_mm == 72.0
    assert tuning.reach_center == "palm"
    assert tuning.pinch_on_mm != Tuning().pinch_on_mm    # thresholds DID refit
