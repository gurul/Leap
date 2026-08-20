# The depth companion: iPhone 17 Pro LiDAR/TrueDepth as a native source

> **Phase 1 only, and the phone path it attaches to is `--legacy` as of
> 2026-08-20** ([../decisions.md](../decisions.md)). Phase 2
> (`DepthPhoneSource`) was never built. Not a dead end — it is the roadmap
> unlock that would retire every monocular workaround at once. Note the dated
> item: free-team signing on the phone expired ~2026-08-25.

Status 2026-08-18: scaffolded. `ios/LeapDepth/` holds the Swift app,
`src/leapinput/phonedepth.py` the Mac receiver. This is the deliberate
exception to the no-install principle — real metric depth is the one thing
the web path can never provide (Safari exposes no depth API), and it
retires every monocular workaround at once: span-as-depth, world-scale
jitter, motion_scale, the ChArUco hand assumption.

## Decisions (and why)

- **AVFoundation, not ARKit.** `AVCaptureDevice.builtInLiDARDepthCamera`
  (rear) and `.builtInTrueDepthCamera` (front) deliver synchronized,
  pixel-aligned RGB+depth with intrinsics via
  `AVCaptureDataOutputSynchronizer` — exactly what landmark-depth fusion
  needs. ARKit adds world tracking/meshing we don't want on the hot path.
  (Reference repos surveyed: arvos = the sensor-node shape we follow;
  apple-lidar-stream = streaming precedent; TokyoYoshida/ExampleOfiOSLiDAR
  = API sandbox; the scanner repos target mesh export, not our problem.)
- **Streaming to the Mac, not on-device processing.** MediaPipe, the
  calibrated Tuning, the gesture engine and 240 tests live on the Mac; the
  phone stays a dumb, cool, replaceable sensor. (Variant B — on-device
  Vision hand pose streaming landmarks — noted and rejected: different
  landmark topology, loses the calibrated stack.)
- **Front vs rear:** at desk range (30-60cm) the front TrueDepth is denser
  and purpose-built for close range; rear LiDAR (min ~0.25m, 576 zones
  upsampled to ~320x240) is the wide-range option. The app offers both.
- **Camera exclusivity:** a native capture session cannot coexist with
  Safari's getUserMedia. The app REPLACES the web page while active:
  `--source phone-depth` vs the existing `--source phone`.
- **Transport: plain TCP, phone connects to the Mac.** One-hop LAN, no
  congestion control needed (the WebRTC path earned that lesson); freshest-
  frame-wins backpressure ON THE PHONE (drop, never queue — the receiver
  must never read stale frames).

## Wire protocol (LPD1)

Little-endian. Stream = repeated messages:

    u8   type            0x01 = frame, 0x02 = imu
    -- type 0x01 (frame):
    u64  timestamp_us    capture time, phone monotonic
    u8   camera          0 = front TrueDepth, 1 = rear LiDAR
    f32  fx, fy, cx, cy  RGB intrinsics at the streamed resolution
    u16  depth_w, depth_h
    u32  rgb_len         JPEG bytes following
    u32  depth_len       zlib bytes following: depth_w*depth_h uint16, mm
    [rgb_len bytes JPEG] [depth_len bytes zlib(u16 mm, row-major)]
    -- type 0x02 (imu):
    u64  timestamp_us
    f32  gx, gy, gz      accelerationIncludingGravity, m/s^2

Depth in millimetres as uint16 (0 = invalid), zlib level 1 — depth maps
are smooth, ~3-5x compression at trivial CPU. RGB 640x480 JPEG q~0.5.

## Mac-side phases

1. `python -m leapinput.phonedepth` — receiver + live stats (fps, center
   depth, IMU). Proves the pipe. [scaffolded]
2. `DepthPhoneSource(CameraSource)`: feed JPEG frames into the existing
   MediaPipe loop; at dispatch, sample the aligned depth map at each
   landmark pixel (median of a 3x3 patch, ignore zeros) -> metric 3D
   landmarks -> HandFrame with REAL z and metric x/y via intrinsics.
3. Retire the monocular stack for this source: motion_scale = 1 (true
   depth), dynamic box sized in real cm, pinch distance in true mm (refit
   thresholds once), optional true --plane xz on a desk-facing camera.

## Phone-side app (ios/LeapDepth)

SwiftUI shell: Mac IP field (the receiver prints it), front/rear picker,
Start/Stop, live stats. Capture: AVCaptureSession at 640x480 +
depth output, synchronizer callback converts depth to u16 mm, JPEG-encodes
color, hands both to the streamer. Streamer: NWConnection TCP with a
one-slot outbox (newest frame wins). Build: open the folder's project
via XcodeGen (`brew install xcodegen && xcodegen`) or create an iOS App
template named LeapDepth and drop the three Swift files in; set camera
usage description; sign with a free personal team; run on the phone once —
it stays installed.
