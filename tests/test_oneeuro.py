"""1€ filter behavior at the CAMERA operating point (~30fps).

These pin the tuning shipped by camera.tune_for_camera: the filter must track a
slow, deliberate aiming motion with bounded lag AND swallow resting-hand jitter.
The 0.3 Hz floor that shipped first failed the former by ~530ms of group delay —
the "syrup then overshoot" failure mode docs/plan.md warned about.
"""

import statistics

from leapinput.driver import Mapping
from leapinput.gestures import Config
from leapinput.oneeuro import OneEuro
from leapinput.camera import Tuning, tune_for_camera

FPS = 30.0
DT = 1.0 / FPS


def camera_mapping() -> Mapping:
    mapping = Mapping(plane="xy")
    tune_for_camera(Config(plane="xy"), mapping, Tuning())
    return mapping


def camera_filter() -> OneEuro:
    m = camera_mapping()
    return OneEuro(freq=FPS, min_cutoff=m.pointer_min_cutoff,
                   beta=m.pointer_beta, d_cutoff=m.pointer_d_cutoff)


def test_slow_aim_lag_is_bounded():
    """A 20mm/s ramp — final-target-approach speed — must lag < 130ms.

    Lag is measured as the positional deficit divided by the speed: how far the
    output trails where the hand actually is, expressed as time.
    """
    f = camera_filter()
    speed = 20.0                        # mm/s
    out = 0.0
    for i in range(90):                 # 3 seconds, past any transient
        t = i * DT
        out = f(speed * t, t)
    true = speed * (89 * DT)
    lag_s = (true - out) / speed
    assert lag_s < 0.130, f"slow-aim lag {lag_s*1000:.0f}ms — cursor is syrup"


def test_rest_jitter_stays_inside_the_deadzone():
    """Alternating ±0.5mm landmark noise at rest must come out with per-frame
    deltas under the 0.6mm deadzone, so a resting hand cannot shiver the cursor."""
    m = camera_mapping()
    f = camera_filter()
    outs = []
    for i in range(60):
        noise = 0.5 if i % 2 == 0 else -0.5
        outs.append(f(100.0 + noise, i * DT))
    deltas = [abs(b - a) for a, b in zip(outs[20:], outs[21:])]
    assert max(deltas) < m.deadzone_mm, \
        f"rest noise leaks {max(deltas):.2f}mm/frame past the filter"


def test_fast_motion_is_not_smoothed_away():
    """At flick speed (300mm/s) beta must open the cutoff: the filter tracks
    within ~1.5 frames of the true position."""
    f = camera_filter()
    speed = 300.0
    out = 0.0
    for i in range(30):
        t = i * DT
        out = f(speed * t, t)
    true = speed * (29 * DT)
    lag_s = (true - out) / speed
    assert lag_s < 1.5 * DT, f"fast-motion lag {lag_s*1000:.0f}ms"
