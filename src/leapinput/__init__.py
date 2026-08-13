"""leapinput — Leap Motion hand tracking to macOS computer-use actions.

Layers, bottom up. Each one only knows about the layer below it:

    capture   Leap frames   -> HandFrame      (the only module importing `leap`)
    camera    webcam frames -> HandFrame      (the only module importing mediapipe)
    gestures  HandFrame     -> Intent         (Schmitt triggers, engagement state)
    driver    Intent        -> Backend calls  (DirectDriver, ShortcutDriver, CUA)
    actions   Backend       -> the machine    (QuartzBackend, DryRunBackend)
"""

from .actions import Backend, DryRunBackend, QuartzBackend, make_backend
from .camera import CameraSource, PoseSignals, Tuning, tune_for_camera
from .capture import HandFrame, LeapSource, Snapshot, Vec3, server_status
from .driver import DirectDriver, Mapping, ShortcutDriver
from .gestures import (Config, GestureEngine, Intent, IntentEvent, Schmitt,
                       palm_down_degrees)
from .oneeuro import OneEuro, OneEuroPlane

__all__ = [
    "Backend", "DryRunBackend", "QuartzBackend", "make_backend",
    "CameraSource", "HandFrame", "LeapSource", "Snapshot", "Vec3",
    "server_status", "tune_for_camera",
    "DirectDriver", "Mapping", "ShortcutDriver",
    "Config", "GestureEngine", "Intent", "IntentEvent", "Schmitt",
    "palm_down_degrees", "OneEuro", "OneEuroPlane",
]
