"""Capture backend #2: a plain webcam through MediaPipe HandLandmarker.

Emits the same framework-free HandFrame/Snapshot as the Leap source, so gestures,
driver and actions run unchanged. Only this module knows about MediaPipe, and the
heavy imports (mediapipe, cv2) happen inside CameraSource.open(), so importing the
package costs nothing and the conversion maths below is testable without either.

What a webcam can and cannot give, compared to the Leap:

  rate/latency   ~30 fps and one camera exposure of lag, vs 111 fps. Dwells in
                 gestures.Config are in seconds, so they still work — they just
                 quantise to fewer frames.
  depth          monocular, so there is no trustworthy Z. The interaction plane is
                 the IMAGE plane (--plane xy): hand left/right and up/down. All
                 emitted Z coordinates are 0.
  pinch          MediaPipe has no pinch_strength/grab_strength. Both are synthesised
                 below from world-landmark geometry (metres, hand-scaled), which is
                 exactly the mm-distance signal the gesture layer prefers anyway.

Coordinate contract (matches capture.py): +X right, +Y up, +Z toward the user, mm.
Frames are processed MIRRORED (selfie view): move your hand right and X grows,
which is also the orientation HandLandmarker assumes when labelling handedness.
"""

from __future__ import annotations

import dataclasses
import json
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .capture import HandFrame, Snapshot, Vec3

# MediaPipe hand landmark indices (21 points).
WRIST = 0
THUMB_MCP, THUMB_TIP = 2, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MCPS = (5, 9, 13, 17)              # index, middle, ring, pinky knuckles
PINKY_MCP = 17
# (MCP, PIP, TIP) chains for the four fingers; bend is measured at the PIP.
FINGER_CHAINS = ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))

# The virtual interaction box, in the same mm units the Leap emits.
#
# Sized so frame geometry can never trip the Leap-specific guards downstream:
#   - eccentricity = atan2(hypot(x,z), y) stays under Mapping.edge_ok_deg (40)
#     everywhere: worst corner is atan2(160, 200) = 38.7 deg, so the edge guard
#     never damps camera motion. The camera has no "edge of the cone" — a hand is
#     either detected or it is not.
#   - Y spans 200..440, always above Config.engage_y_xy (40). Presence is the
#     gate: hand in view = engaged, hand out of view = hard disengage. Same
#     dead-man philosophy the Leap measurements settled on, delivered the same way.
#
# ISOTROPIC by construction: PLANE_Y_MM = PLANE_X_MM * 480/640, so one physical
# centimetre of hand travel maps to the same virtual mm on both axes. The old
# 320x300 pair over a 4:3 frame made vertical motion ~25% hotter (and noisier)
# than horizontal for the same real movement.
# Worst-corner eccentricity is atan2(hypot(160, 0), 200) = 38.7 deg, still under
# Mapping.edge_ok_deg (40), so the edge guard never damps camera motion.
PLANE_X_MM = 320.0                 # image width maps to +/-160mm
PLANE_Y_MM = 240.0                 # image height, same mm-per-pixel as X
PLANE_Y_BASE = 200.0               # bottom of image = 200mm

# Depth gate, in normalized image units of knuckle span: a hand's image size
# scales with 1/distance (its world span stays hand-sized), so span is a free
# monocular range check. Below this the hand is beyond ~1.2m — a person in the
# background, or too far to control precisely — and is ignored entirely rather
# than allowed to grab the cursor. (The idea a full Depth Anything integration
# would buy, at zero model cost; see TouchDesigner's TDDepthAnything.)
MIN_SPAN_IMG = 0.04

# pinch_strength synthesised from thumb-index tip distance (world landmarks, mm).
# Anchored to gestures.Config: at pinch_on_mm (50) this yields 0.6, clearing
# pinch_min_strength (0.5); at pinch_off_mm (68) it yields 0.24, well clear.
STRENGTH_OPEN_MM = 80.0
STRENGTH_SPAN_MM = 50.0

# MediaPipe's world-landmark scale is re-estimated every frame from a monocular
# view, so absolute distances between two frames of the SAME pose jitter by tens
# of percent. Distances are therefore measured relative to the knuckle span
# (index MCP -> pinky MCP), which jitters identically and cancels in the ratio,
# then converted back to pseudo-mm via a nominal adult span so the mm thresholds
# in gestures.Config keep their meaning.
NOMINAL_SPAN_MM = 55.0

TUNING_PATH = Path(__file__).resolve().parents[2] / "camera_tuning.json"


@dataclass(frozen=True)
class Tuning:
    """Per-user pose thresholds. The defaults are educated guesses; YOUR hand is
    the ground truth. `python -m leapinput.calibrate capture` records it and
    `analyze` fits these values from the measured distributions, writing
    camera_tuning.json (gitignored — it describes a hand, not the project),
    which CameraSource and tune_for_camera then load automatically.

    extend_*: per-finger Schmitt band on the PIP bend. Straight fingers measure
    near 0 deg, a fist folds them past 120; a single threshold flaps for
    half-curled fingers, and a flapping finger count is exactly what the gesture
    layer's Debounce cannot fix fast (it must wait out its hold every flip).
    Below extend_on = extended, above extend_off = curled, in between = keep the
    previous reading. extended_max is the prev-less first-frame cut.

    thumb_*: same idea for the thumb's positional ratio
    (tip-to-pinky-knuckle over thumb-knuckle-to-pinky-knuckle).

    pinch_*: applied onto gestures.Config by tune_for_camera, in the same
    span-normalized pseudo-mm the camera emits.
    """

    extend_on_deg: float = 55.0
    extend_off_deg: float = 75.0
    extended_max_deg: float = 65.0
    thumb_on_ratio: float = 1.08
    thumb_off_ratio: float = 0.92
    pinch_on_mm: float = 50.0
    pinch_off_mm: float = 68.0
    # Which pinch signal drives clicks: "world" (3D tip distance) or "image"
    # (2D pixel-space). calibrate.analyze picks whichever separates better on
    # YOUR data; measured 2026-08-12 the 3D clouds overlapped by 18mm while the
    # 2D signal is immune to the occlusion-inflated depth guess.
    pinch_source: str = "world"

    @classmethod
    def load(cls, path=None) -> "Tuning":
        p = Path(path) if path else TUNING_PATH
        if not p.exists():
            return cls()
        data = json.loads(p.read_text())
        defaults = cls()
        kwargs = {}
        for f in dataclasses.fields(cls):
            if f.name in data:
                kwargs[f.name] = type(getattr(defaults, f.name))(data[f.name])
        return cls(**kwargs)

    def save(self, path=None) -> Path:
        p = Path(path) if path else TUNING_PATH
        p.write_text(json.dumps(dataclasses.asdict(self), indent=2) + "\n")
        return p

# grab_strength ramps over this bend range, averaged across the four fingers.
GRAB_BEND_LO_DEG = 40.0
GRAB_BEND_HI_DEG = 110.0

# Pose-signal EMA: fraction of the NEW sample kept. One frame of extra latency
# (~33ms) in exchange for the Schmitt triggers seeing a signal, not the noise.
POSE_BLEND = 0.6

# Skeleton edges between the 21 landmarks, for the preview overlay.
HAND_CONNECTIONS = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7),
                    (7, 8), (5, 9), (9, 10), (10, 11), (11, 12), (9, 13),
                    (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19),
                    (19, 20), (0, 17))
FINGERTIPS = (4, 8, 12, 16, 20)    # thumb..pinky, matching HandFrame.extended

DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "vendor" / "hand_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")


# --- pure geometry: landmark lists in, HandFrame out -------------------------

def _leap_axes(lm) -> Vec3:
    """MediaPipe axes (x right, y down, z away from camera) -> Leap axes."""
    return Vec3(lm.x, -lm.y, -lm.z)


def resolve_side(category_name: str, n_detected: int,
                 assume: Optional[str] = None) -> str:
    """Which HandFrame side a detected hand belongs to.

    MediaPipe 1.0.0 labels handedness for the UN-mirrored image, so on the
    selfie view we always process, the label is swapped. Worse, the label FLAPS
    on fists and pinches — and a flap makes the configured hand vanish for a
    frame, which reads downstream as tracking loss and releases everything
    mid-gesture. When only ONE hand is visible and the caller told us whose it
    is, identity beats classification: it is the configured hand, whatever the
    label claims this frame. (A deliberate single-user tradeoff.)
    """
    if n_detected == 1 and assume is not None:
        return assume
    return "Right" if category_name == "Left" else "Left"


def lone_hand_side(label_side: str, assume: Optional[str],
                   prev_wrist: Optional[tuple[float, float]],
                   wrist: tuple[float, float], elapsed_us: float,
                   max_gap_us: float = 500_000, max_jump: float = 0.18) -> str:
    """Refined side for a LONE detection, when free-hand poses are in play.

    resolve_side's blanket "a lone hand is the configured hand" makes the free
    hand's own poses (clipboard) unreachable: raise only the left hand and it
    is labelled Right. But the assumption exists for a real reason — labels
    flap on fists and pinches. Continuity separates the two cases: the
    configured hand wins only when the detection is where that hand just WAS
    (the flap, mid-gesture); a hand appearing fresh, away from it, is believed
    to be what the label says. Wrist positions are normalized image coords, so
    the jump threshold is a fraction of the frame."""
    if assume is None:
        return label_side
    if prev_wrist is not None and elapsed_us <= max_gap_us:
        dx, dy = wrist[0] - prev_wrist[0], wrist[1] - prev_wrist[1]
        if dx * dx + dy * dy <= max_jump * max_jump:
            return assume
    return label_side


def _dist(a, b) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _bend_degrees(mcp, pip, tip) -> float:
    """Angle at the PIP between the proximal and distal segments. 0 = straight."""
    ux, uy, uz = pip.x - mcp.x, pip.y - mcp.y, pip.z - mcp.z
    vx, vy, vz = tip.x - pip.x, tip.y - pip.y, tip.z - pip.z
    mu = math.sqrt(ux * ux + uy * uy + uz * uz)
    mv = math.sqrt(vx * vx + vy * vy + vz * vz)
    if mu == 0.0 or mv == 0.0:
        return 180.0
    dot = (ux * vx + uy * vy + uz * vz) / (mu * mv)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


@dataclass(frozen=True)
class PoseSignals:
    """The raw scalars behind the derived HandFrame fields — what calibrate.py
    records, so thresholds can be fitted to distributions instead of guessed."""

    bends: tuple[float, float, float, float]   # PIP bend deg, index..pinky
    thumb_ratio: float                          # tip/knuckle distance ratio
    pinch_mm: float                             # 3D world, span-normalized
    span_mm: float                              # raw world knuckle span
    # 2D image-space pinch, same pseudo-mm scale. MEASURED to matter
    # (2026-08-12 session): during a HELD pinch the occluded tips inflate the
    # world reconstruction to p95 47.5mm while a ready-to-pinch hover dips to
    # 29.3mm — the 3D clouds overlap by 18mm. In pixel space the held tips
    # merge regardless of the depth guess, so this is the separable signal.
    pinch_img_mm: Optional[float] = None
    # Knuckle span in NORMALIZED IMAGE units — the free monocular depth proxy:
    # image size scales with 1/distance while the world span stays hand-sized.
    span_img: Optional[float] = None


def _dist2d(a, b, aspect: float) -> float:
    return math.hypot(a.x - b.x, (a.y - b.y) * aspect)


def pose_signals(world, image=None, aspect: float = 0.75) -> PoseSignals:
    """`aspect` = frame height/width, to undo the anisotropy of normalized
    image coordinates before measuring 2D distances."""
    span = _dist(world[INDEX_MCP], world[PINKY_MCP])
    pinch_img = span_img = None
    if image is not None:
        span_img = _dist2d(image[INDEX_MCP], image[PINKY_MCP], aspect)
        pinch_img = (_dist2d(image[THUMB_TIP], image[INDEX_TIP], aspect)
                     / max(1e-9, span_img)) * NOMINAL_SPAN_MM
    return PoseSignals(
        bends=tuple(_bend_degrees(world[m], world[p], world[t])
                    for m, p, t in FINGER_CHAINS),
        thumb_ratio=_dist(world[THUMB_TIP], world[PINKY_MCP])
        / max(1e-9, _dist(world[THUMB_MCP], world[PINKY_MCP])),
        pinch_mm=(_dist(world[THUMB_TIP], world[INDEX_TIP])
                  / max(1e-9, span)) * NOMINAL_SPAN_MM,
        span_mm=span * 1000.0,
        pinch_img_mm=pinch_img,
        span_img=span_img,
    )


def _extended(sig: PoseSignals, prev: Optional[tuple[bool, ...]],
              tuning: Tuning) -> tuple[bool, ...]:
    """(thumb, index, middle, ring, pinky), matching HandFrame.extended.

    Fingers: bend at the PIP, with hysteresis against the previous frame's flags.
    The thumb bends little even in a fist, so it gets a positional test instead:
    in a fist the thumb tip lies across the fingers, close to the pinky knuckle;
    extended, it points away from it.
    """
    if prev is None:
        thumb = sig.thumb_ratio > 1.0
    else:
        thumb = (sig.thumb_ratio > tuning.thumb_on_ratio or
                 (prev[0] and sig.thumb_ratio >= tuning.thumb_off_ratio))

    fingers = []
    for i, bend in enumerate(sig.bends):
        if prev is None:
            fingers.append(bend < tuning.extended_max_deg)
        elif bend < tuning.extend_on_deg:
            fingers.append(True)
        elif bend > tuning.extend_off_deg:
            fingers.append(False)
        else:
            fingers.append(prev[i + 1])     # in the band: keep the last reading
    return (thumb, *fingers)


def ily_shaped(sig: PoseSignals, tuning: Tuning) -> bool:
    """Prev-less ILY read (thumb + index + pinky out, middle + ring curled)
    for ROUTING, before a HandFrame (and its hysteresis) exists.

    Decides whether a LONE detection should trust the classifier's handedness
    label instead of the identity/continuity assumption. That assumption exists
    because labels flap on fists and pinches (curled, self-occluded) — but ILY
    is the most distinctive extended pose in the vocabulary, the one the
    classifier reads reliably, and the one pose whose left/right routing
    changes the command entirely: free-hand ILY is Enter, cursor-hand ILY is
    the pause toggle. Seen in live use: the left hand raised in ILY where the
    cursor hand just was gets adopted by continuity, and ~1.65s later the
    session pauses instead of submitting Enter.
    """
    thumb = sig.thumb_ratio > 1.0
    index, middle, ring, pinky = (b < tuning.extended_max_deg
                                  for b in sig.bends)
    return thumb and index and pinky and not middle and not ring


def _grab_strength(sig: PoseSignals) -> float:
    """Mean finger curl, 0 open .. 1 fist. Same shape as the Leap's signal."""
    total = sum(max(0.0, min(1.0, (bend - GRAB_BEND_LO_DEG)
                             / (GRAB_BEND_HI_DEG - GRAB_BEND_LO_DEG)))
                for bend in sig.bends)
    return total / len(sig.bends)


def _palm_normal(world, side: str) -> Vec3:
    """Out of the palm, in Leap axes. cross(index, pinky) spans the palm plane;
    the winding flips with handedness."""
    w = _leap_axes(world[WRIST])
    i = _leap_axes(world[INDEX_MCP])
    p = _leap_axes(world[PINKY_MCP])
    ax, ay, az = i.x - w.x, i.y - w.y, i.z - w.z
    bx, by, bz = p.x - w.x, p.y - w.y, p.z - w.z
    nx, ny, nz = ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx
    if side == "Right":
        nx, ny, nz = -nx, -ny, -nz
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag == 0.0:
        return Vec3(0.0, 0.0, 0.0)
    return Vec3(nx / mag, ny / mag, nz / mag)


def _to_plane(lm) -> Vec3:
    """Normalized image landmark -> virtual mm in Leap axes. Z is always 0."""
    return Vec3((lm.x - 0.5) * PLANE_X_MM,
                PLANE_Y_BASE + (1.0 - lm.y) * PLANE_Y_MM,
                0.0)


def handframe_of(image_lms, world_lms, side: str, frame_id: int,
                 timestamp_us: int, prev: Optional[HandFrame] = None,
                 tuning: Optional[Tuning] = None,
                 signals: Optional[PoseSignals] = None) -> HandFrame:
    """One detected hand -> HandFrame.

    Cursor-driving positions (palm, index tip, knuckles) come from the IMAGE
    landmarks — they carry the hand's position in the frame. Pose signals (pinch,
    curl, normal) come from the WORLD landmarks — metric, hand-centred, and
    independent of how far the hand is from the camera.
    """
    knuckles = tuple(_to_plane(image_lms[i]) for i in MCPS)
    wrist = _to_plane(image_lms[WRIST])
    n = len(knuckles) + 1
    palm = Vec3((wrist.x + sum(k.x for k in knuckles)) / n,
                (wrist.y + sum(k.y for k in knuckles)) / n, 0.0)

    velocity = Vec3(0.0, 0.0, 0.0)
    if prev is not None and timestamp_us > prev.timestamp:
        dt = (timestamp_us - prev.timestamp) / 1e6
        # Blend with the previous estimate: a raw 30fps finite difference is too
        # spiky for the speed->gain curve it feeds.
        velocity = Vec3(0.5 * (palm.x - prev.palm.x) / dt + 0.5 * prev.palm_velocity.x,
                        0.5 * (palm.y - prev.palm.y) / dt + 0.5 * prev.palm_velocity.y,
                        0.0)

    tuning = tuning or Tuning()
    sig = signals or pose_signals(world_lms, image_lms)
    pinch_mm = (sig.pinch_img_mm
                if tuning.pinch_source == "image" and sig.pinch_img_mm is not None
                else sig.pinch_mm)
    grab = _grab_strength(sig)
    if prev is not None:
        pinch_mm = POSE_BLEND * pinch_mm + (1.0 - POSE_BLEND) * prev.pinch_distance
        grab = POSE_BLEND * grab + (1.0 - POSE_BLEND) * prev.grab_strength
    strength = max(0.0, min(1.0, (STRENGTH_OPEN_MM - pinch_mm) / STRENGTH_SPAN_MM))

    return HandFrame(
        frame_id=frame_id,
        timestamp=timestamp_us,
        hand_id=0 if side == "Left" else 1,
        side=side,
        palm=palm,
        palm_velocity=velocity,
        palm_normal=_palm_normal(world_lms, side),
        pinch_strength=strength,
        pinch_distance=pinch_mm,
        grab_strength=grab,
        extended=_extended(sig, prev.extended if prev else None, tuning),
        index_tip=_to_plane(image_lms[INDEX_TIP]),
        knuckles=knuckles,
    )


def tune_for_camera(gesture_cfg, mapping, tuning: Optional[Tuning] = None) -> None:
    """Rescale rate-dependent constants from 111 fps Leap to ~30 fps camera.

    The measured Config dwells are FRAME-count guards expressed in seconds: at
    111 fps, 0.03s of dwell is ~3 corroborating frames; at 30 fps it is a single
    frame, i.e. no guard at all — one noisy landmark frame clicks the mouse.
    These keep the guards at 2-3 frames of the rate we actually get, trading
    ~60ms of gesture latency for stability. The 1 euro filter opens up the same
    way: camera landmarks are noisier and slower, so smooth harder when still
    (lower min_cutoff) and let speed cut through sooner (higher beta).
    """
    tuning = tuning or Tuning.load()
    gesture_cfg.engage_dwell = 0.10
    gesture_cfg.pinch_dwell = 0.07       # 2 frames at 30fps (was <1)
    gesture_cfg.grab_dwell = 0.10
    gesture_cfg.finger_hold = 0.10       # 3 frames to change the ladder state
    # Calibrated (or default) pinch band, in the camera's span-normalized mm.
    gesture_cfg.pinch_on_mm = tuning.pinch_on_mm
    gesture_cfg.pinch_off_mm = tuning.pinch_off_mm
    # Freeze completes AT the firing threshold (see gestures.Config): the ramp
    # spans the last 8mm of approach and reaches 0.0 exactly when the Schmitt
    # can fire, so the click posts on a stopped cursor — never after it.
    gesture_cfg.settle_start_mm = tuning.pinch_on_mm + 8.0
    gesture_cfg.settle_full_mm = tuning.pinch_on_mm
    # Vogel & Balakrishnan (UIST 2005) interpolate the cutoff 0.25->5 Hz as
    # hand speed goes 10->200 mm/s. A 0.3 Hz floor was tried first and is a
    # trap at 30fps: ~530ms of group delay in exactly the slow-speed regime of
    # final target approach — the "syrup then overshoot" docs/plan.md warns
    # about. 1.5 Hz rests at ~106ms; beta 0.03 reaches ~4.5 Hz at 100 mm/s and
    # 7.5 Hz at 200 — the same band, without the syrup.
    mapping.pointer_min_cutoff = 1.5
    mapping.pointer_beta = 0.03
    # Open the speed estimate too: at d_cutoff 1.0 the derivative that drives
    # beta is itself ~5 frames late at 30fps, so the cutoff opened only after
    # the motion it was reacting to. 2.0 halves that.
    mapping.pointer_d_cutoff = 2.0
    # Landmark noise at rest is ~1-3px; at 640px->320mm that is up to ~1.5mm of
    # per-frame delta the Leap's 0.12mm deadzone happily amplifies into cursor
    # shiver. Swallow it: intent at these gains is never sub-half-millimetre.
    mapping.deadzone_mm = 0.6


# --- the source ---------------------------------------------------------------

def set_thread_qos_user_interactive() -> None:
    """Ask the macOS scheduler for P-cores. Non-main threads default to a QoS
    that is E-core eligible on Apple silicon, where a 9ms detect becomes 20ms+
    whenever the machine is busy. QOS_CLASS_USER_INTERACTIVE = 0x21. No-op
    anywhere this fails (non-macOS, sandbox).
    """
    try:
        import ctypes
        libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libsystem.pthread_set_qos_class_self_np(0x21, 0)
    except Exception:
        pass


def camera_names() -> list[str]:
    """Attached camera names, in AVFoundation enumeration order.

    system_profiler reports cameras in the same order AVFoundation (and so
    cv2.VideoCapture) enumerates them, which lets us pick by name without
    opening devices. Empty anywhere the probe fails (non-macOS, no cameras).
    """
    import json
    import subprocess
    try:
        out = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True, text=True, timeout=10, check=True).stdout
        return [c.get("_name", "") for c in json.loads(out)["SPCameraDataType"]]
    except Exception:
        return []


def pick_camera_index() -> int:
    """AVFoundation index of the built-in camera.

    Virtual cameras (Camo, OBS, ...) register ahead of the built-in one, so
    index 0 stops meaning "the webcam" the day one of those apps is installed —
    opening it yields a black feed unless that app is actively streaming.
    Falls back to 0 when no built-in camera is recognized.
    """
    for i, name in enumerate(camera_names()):
        if any(k in name.lower() for k in ("macbook", "facetime", "built-in")):
            return i
    return 0


def find_camera_index(name: str) -> int:
    """Index of the first camera whose name contains `name`, case-insensitive.

    This is how you deliberately target a virtual or external camera —
    e.g. --camera-name iphone for Continuity Camera, or --camera-name camo.
    """
    names = camera_names()
    for i, n in enumerate(names):
        if name.lower() in n.lower():
            return i
    raise RuntimeError(
        f"no camera matching {name!r} — attached cameras: "
        f"{', '.join(repr(n) for n in names) or 'none found'}")


class CameraSource:
    """Same shape as LeapSource: open(), subscribe(), latest, frames.

    Owns a capture thread reading the webcam and running HandLandmarker in VIDEO
    mode. Callbacks run on that thread — keep them short, exactly as with the Leap.
    """

    def __init__(self, camera: Optional[int] = None, model_path=None,
                 mirror: bool = True,
                 preview: bool = False, tuning: Optional[Tuning] = None,
                 hand: Optional[str] = None, two_hands: bool = False,
                 min_detection_confidence: float = 0.5,
                 min_presence_confidence: float = 0.5,
                 min_tracking_confidence: float = 0.5):
        self._camera = camera
        self._model_path = Path(model_path) if model_path else DEFAULT_MODEL
        self._mirror = mirror
        self._preview = preview
        self._tuning = tuning or Tuning.load()
        # The hand this session drives. Set, it buys two robustness wins: the
        # detector only looks for ONE hand (fewer spurious second-hand blobs),
        # and a lone detection is assigned to this side regardless of the
        # per-frame handedness label (see resolve_side).
        self._hand = hand
        # Two-hand gestures (the finger-frame pane) need the detector looking
        # for both hands even when a cursor hand is configured; a lone
        # detection is still assigned to the configured side (resolve_side).
        self._two_hands = two_hands
        self._confidences = (min_detection_confidence,
                             min_presence_confidence,
                             min_tracking_confidence)
        self._subscribers: list[Callable[[Snapshot], None]] = []
        self._lock = threading.Lock()
        # Last wrist position per side (normalized image coords + t_us), the
        # continuity signal lone_hand_side uses to tell a label flap from the
        # free hand raised alone.
        self._last_wrist: dict[str, tuple[float, float, int]] = {}
        self.latest = Snapshot()
        self.frames = 0
        # Latest annotated BGR frame (numpy), written by the capture thread. On
        # macOS cv2 windows must live on the MAIN thread, so this source only
        # draws — whoever owns the main loop displays it (see cli --preview).
        self.preview_frame = None
        # Raw pose scalars for the most recent frame, per side; written by the
        # capture thread just before the matching Snapshot is dispatched, so a
        # subscriber reading them inside its callback sees the same frame.
        self.latest_signals: dict[str, Optional[PoseSignals]] = {
            "Left": None, "Right": None}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._prev: dict[str, Optional[HandFrame]] = {"Left": None, "Right": None}
        self._frame_id = 0
        # Pipeline health, written by the capture thread: measured camera fps,
        # EMA of detection time, and whether detection kept up with the camera
        # last frame. Read by the CLI overlay to make lag visible instead of
        # mysterious.
        self.stats: dict = {"fps": 0.0, "detect_ms": 0.0, "realtime": True}

    def subscribe(self, fn: Callable[[Snapshot], None]) -> None:
        self._subscribers.append(fn)

    def _dispatch(self, snap: Snapshot) -> None:
        with self._lock:
            self.latest = snap
            self.frames += 1
        for fn in self._subscribers:
            fn(snap)

    def open(self):
        # Heavy imports and permission prompts happen here, not at module import.
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision

        if not self._model_path.exists():
            raise RuntimeError(
                f"hand landmarker model missing at {self._model_path} — fetch it "
                f"with: curl -L -o '{self._model_path}' '{MODEL_URL}'")

        cap = self._open_capture(cv2)

        detect_c, presence_c, track_c = self._confidences
        landmarker = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self._model_path)),
                running_mode=vision.RunningMode.VIDEO,
                # Cursor control needs exactly one hand; asking for two invites
                # a face or a background person in as a phantom second hand.
                # Explicit confidences so the tunables are visible, not implied.
                num_hands=1 if self._hand and not self._two_hands else 2,
                min_hand_detection_confidence=detect_c,
                min_hand_presence_confidence=presence_c,
                min_tracking_confidence=track_c))

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(cv2, mp, cap, landmarker),
            name="camera-capture", daemon=True)
        self._thread.start()
        return _CameraSession(self, cap, landmarker)

    def _open_capture(self, cv2):
        """The frame producer: anything shaped like cv2.VideoCapture
        (read/grab/release). Subclasses swap in non-device producers here —
        phonecam.PhoneSource feeds WebRTC frames through the same loop.
        """
        index = self._camera if self._camera is not None else pick_camera_index()
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            raise RuntimeError(
                f"cannot open camera {index} — check the terminal has "
                "Camera permission (System Settings > Privacy & Security > Camera)")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        # Ask for the shallowest capture buffer the backend allows: a deep
        # buffer serves STALE frames when detection falls behind, which reads
        # as cursor lag no filter tuning can fix. Honored on some backends,
        # harmless where ignored (the grab()-drain below covers those).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run(self, cv2, mp, cap, landmarker) -> None:
        set_thread_qos_user_interactive()
        last_ms = 0
        frame_budget_us = None          # measured from the frame cadence below
        prev_capture_us = None
        while not self._stop.is_set():
            # Detection slower than the camera means frames queue and every
            # snapshot describes the past. Drain the stalest buffered frame
            # before reading, so the pipeline degrades to a lower rate instead
            # of a growing delay.
            if not self.stats["realtime"]:
                cap.grab()
            ok, bgr = cap.read()
            # Timestamp CAPTURE, not the end of flip+convert: downstream dwells
            # and velocities should measure when the hand moved, not how long
            # this thread took to get around to it.
            now_us = time.monotonic_ns() // 1_000
            if not ok:
                time.sleep(0.05)
                continue
            if prev_capture_us is not None:
                interval = now_us - prev_capture_us
                fps = self.stats["fps"]
                self.stats["fps"] = (0.9 * fps + 0.1 * (1e6 / interval)
                                     if fps else 1e6 / interval)
                frame_budget_us = interval
            prev_capture_us = now_us
            if self._mirror:
                bgr = cv2.flip(bgr, 1)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            # detect_for_video requires strictly increasing timestamps.
            ms = max(last_ms + 1, now_us // 1_000)
            last_ms = ms
            try:
                result = landmarker.detect_for_video(image, ms)
            except Exception:
                if self._stop.is_set():     # racing a close(); not an error
                    return
                raise
            detect_us = time.monotonic_ns() // 1_000 - now_us
            ema = self.stats["detect_ms"]
            self.stats["detect_ms"] = (0.9 * ema + 0.1 * (detect_us / 1000.0)
                                       if ema else detect_us / 1000.0)
            if frame_budget_us:
                self.stats["realtime"] = detect_us <= frame_budget_us

            snap = Snapshot()
            self._frame_id += 1
            for handedness, img_lms, wld_lms in zip(
                    result.handedness, result.hand_landmarks,
                    result.hand_world_landmarks):
                n = len(result.handedness)
                sig = pose_signals(wld_lms, img_lms,
                                   aspect=bgr.shape[0] / bgr.shape[1])
                side = resolve_side(handedness[0].category_name,
                                    n, self._hand)
                if n == 1 and self._hand is not None and self._two_hands:
                    label_side = resolve_side(
                        handedness[0].category_name, 2, None)
                    if ily_shaped(sig, self._tuning):
                        # ILY: the label decides Enter (free hand) vs pause
                        # (cursor hand), and the classifier is reliable on
                        # this maximally-extended pose — the flap-defense
                        # below stands down so left-hand ILY is always Enter.
                        side = label_side
                    else:
                        # Free-hand poses exist: a lone detection may genuinely
                        # be the OTHER hand. Identity wins only on continuity.
                        lw = self._last_wrist.get(self._hand)
                        side = lone_hand_side(
                            label_side,
                            self._hand,
                            None if lw is None else lw[:2],
                            (img_lms[0].x, img_lms[0].y),
                            now_us - (lw[2] if lw is not None else 0))
                if sig.span_img is not None and sig.span_img < MIN_SPAN_IMG:
                    continue        # beyond working distance: not our hand
                frame = handframe_of(img_lms, wld_lms, side, self._frame_id,
                                     now_us, prev=self._prev.get(side),
                                     tuning=self._tuning, signals=sig)
                self._prev[side] = frame
                self._last_wrist[side] = (img_lms[0].x, img_lms[0].y, now_us)
                self.latest_signals[side] = sig
                setattr(snap, side.lower(), frame)
            # MediaPipe occlusion failures are binary whole-hand dropouts of a
            # few frames, not gradual noise (arXiv 2604.24609). Hold the last
            # frame through sub-150ms flickers so a mid-pinch dropout cannot
            # release the button; a hand deliberately removed still hard-
            # disengages ~5 frames later.
            for side in ("Left", "Right"):
                if snap.get(side) is None:
                    held = self._prev.get(side)
                    if held is not None and now_us - held.timestamp < 150_000:
                        # RESTAMP the held frame and freeze its velocity. The
                        # engine clocks off frame timestamps, so re-serving the
                        # old stamp froze the engine's clock and stalled every
                        # pending release dwell for the dropout's duration;
                        # the stale velocity would spike the gain curve.
                        # _prev keeps the ORIGINAL frame: the 150ms age check
                        # still expires, and reappearance velocity uses true dt.
                        setattr(snap, side.lower(), dataclasses.replace(
                            held, timestamp=now_us,
                            palm_velocity=Vec3(0.0, 0.0, 0.0)))
                    else:
                        self._prev[side] = None
                        self.latest_signals[side] = None
            if self._preview:
                self._annotate(cv2, bgr, result, snap)
                self.preview_frame = bgr
            self._dispatch(snap)

    def _annotate(self, cv2, bgr, result, snap: Snapshot) -> None:
        """Skeleton + per-hand signal readout, drawn on the mirrored frame."""
        h, w = bgr.shape[:2]
        for img_lms in result.hand_landmarks:
            pts = [(int(lm.x * w), int(lm.y * h)) for lm in img_lms]
            for a, b in HAND_CONNECTIONS:
                cv2.line(bgr, pts[a], pts[b], (200, 200, 200), 1)
            for p in pts:
                cv2.circle(bgr, p, 2, (160, 160, 160), -1)
        for row, frame in enumerate(f for f in (snap.left, snap.right) if f):
            y0 = 22 + row * 40
            cv2.putText(
                bgr,
                f"{frame.side}  fingers={frame.extended_count} "
                f"[{''.join('x' if e else '.' for e in frame.extended)}]  "
                f"pinch={frame.pinch_distance:5.1f}mm  grab={frame.grab_strength:.2f}",
                (8, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1,
                cv2.LINE_AA)
        # Fingertips: green = read as extended, red = read as curled.
        for img_lms, hand in zip(result.hand_landmarks,
                                 result.handedness):
            side = resolve_side(hand[0].category_name,
                                len(result.handedness), self._hand)
            frame = snap.get(side)
            if frame is None:
                continue
            for tip_i, ext in zip(FINGERTIPS, frame.extended):
                p = (int(img_lms[tip_i].x * w), int(img_lms[tip_i].y * h))
                cv2.circle(bgr, p, 6, (0, 200, 0) if ext else (0, 0, 230), -1)


class _CameraSession:
    def __init__(self, source: CameraSource, cap, landmarker):
        self._source = source
        self._cap = cap
        self._landmarker = landmarker

    def close(self):
        self._source._stop.set()
        if self._source._thread is not None:
            self._source._thread.join(timeout=2.0)
        self._cap.release()
        self._landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
