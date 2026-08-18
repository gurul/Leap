"""CLI flag resolution — pinning that what the flags SAY is what ships.

The bug this guards: Mapping's invert_x default is the measured Leap truth
(True, confirmed by use), and building Mapping straight from a store_true
argparse default silently overwrote it with False on every default run.
"""

import argparse

from leapinput.cli import resolve_source_defaults


def parse(source: str, *extra: str) -> argparse.Namespace:
    ns = argparse.Namespace(source=source, plane=None, point=None,
                            invert_x=None, invert_z=None, drag=None)
    for flag in extra:
        key, _, val = flag.partition("=")
        setattr(ns, key, val == "True")
    resolve_source_defaults(ns)
    return ns


def test_leap_defaults_keep_the_measured_inversion():
    ns = parse("leap")
    assert ns.invert_x is True      # confirmed by use 2026-08-12
    assert ns.invert_z is False
    assert ns.plane == "xz"
    assert ns.point == "index"
    assert ns.drag is True          # grab_strength is clean on the Leap


def test_camera_defaults():
    ns = parse("camera")
    assert ns.invert_x is False     # mirrored view already matches
    assert ns.invert_z is False
    assert ns.plane == "xy"
    assert ns.point == "knuckles"
    assert ns.drag is False         # camera: pinch is the only button


def test_explicit_flags_override_both_directions():
    assert parse("leap", "invert_x=False").invert_x is False
    assert parse("camera", "invert_x=True").invert_x is True
    assert parse("leap", "invert_z=True").invert_z is True
