# Latency and the camera pipeline

What each source actually delivers, where the time goes, and which
optimisations were worth it. The phone/WebRTC engineering here is behind
`--legacy` as of 2026-08-20 but is intact and is still the fastest source this
project has.

---

## The three sources, measured

| | webcam | phone (WebRTC) | Leap Motion |
|---|---|---|---|
| frame rate | 29.4 fps at 640×480 (449 frames / 15.3 s) | 57.2 fps at 640×480 (1,137 frames / 19.9 s) | 111 fps (667 frames / 6.0 s) |
| latency | one extra camera exposure | ~40–80 ms glass-to-glass | sub-frame |
| depth | none — image plane only | none — image plane only | real Z |
| pinch / grab | synthesized from world-landmark geometry | same | reported by the SDK |

([sources.md:17-23](../sources.md)) With the command layer running, the webcam
path measures **29.8 fps at ~29% CPU** (31297f3).

---

## CPU was never the constraint on the gesture pipeline

Measured **before** optimising: the gesture + driver pipeline runs at
**0.9 µs/frame against a 9,090 µs budget at 110 fps — 0.009%**. So the perf
pass was about the frame carrying only what is read, not about speed:
`HandFrame` went 16 fields → 13 (0.95 → 0.73 µs), 14 `Vec3` allocations → 8,
and the 1-euro filter runs two axes instead of three (the off-plane axis gates
but never contributes to cursor position) at 0.956 → 0.649 µs per call. Cursor
position now provably depends on exactly two axes. (6399aaa)

**All measurable cost is in MediaPipe detection (~9 ms/frame at VGA on the
M5).** Which is why the detection-rate cap was the only CPU lever worth
trying — and why it was reverted.

---

## The detection-rate cap: measured well, and reverted anyway

With only pose *holds* wired, per-frame position buys nothing and a 0.6 s dwell
does not care about 33 ms. Detection ran on a 20 Hz budget for about an hour:
**~30% CPU → ~17%**, 14.4 fps effective, still ~6 frames on the shortest dwell.

**Reverted, because it made the two-hand frame shot flicker** — the one feature
the strip exists to serve. The likely mechanism: MediaPipe seeds each detection
from the previous frame's region, so starving it degrades landmark quality,
which shows up as an unstable `extended` tuple, which is exactly what the
L-pose test reads. Full rate is 29.8 fps at ~29% CPU.

**Also learned:** a first attempt at 15 Hz measured **9.2 fps**, because the
skip loop's fixed `sleep(0.004)` per skipped frame cost more rate than the
budget did. It now sleeps the remainder (capped at 20 ms) — worth knowing if
the cap is ever reached for again.

Opt back in with `--detect-hz 20`. It would still be wrong for the frame shot.
(757adb2 → 31297f3, [decisions.md:71-96](../decisions.md))

---

## Camera-loop discipline that is not optional

**Buffers must be shallow, and stale frames drained.** A deep capture buffer
serves *stale* frames when detection falls behind, which reads as cursor lag no
filter tuning can fix. `CAP_PROP_BUFFERSIZE` is set to 1, and when
`stats['realtime']` is false the loop calls `cap.grab()` to drain the stalest
buffered frame before reading — so the pipeline degrades to a lower **rate**
rather than a growing **delay**. The phone shim gets this for free: `read()`
blocks until a frame newer than the last served arrives.
(`camera.py:952-1004`)

**Timestamp the capture, not the end of processing.** `now_us` is taken
immediately after `cap.read()`, before flip and colour conversion, because
downstream dwells and velocities should measure when the hand moved, not how
long the thread took to get around to it. Velocity is 50/50 blended with the
previous estimate, because a raw 30 fps finite difference is too spiky for the
speed→gain curve it feeds. (`camera.py:1021-1025`)

**Dwells had to be re-derived for 30 fps.** The measured `Config` dwells are
frame-count guards expressed in seconds: at 111 fps, 0.03 s is 3 frames; at
30 fps it is no guard at all. `tune_for_camera` restores 2–3 frames of the rate
actually achieved — engage 0.10, pinch 0.07, grab 0.10, finger_hold 0.10 —
trading ~60 ms of gesture latency for stability. Without it, one noisy landmark
frame clicks the mouse. (`camera.py:576-591`)

**macOS parks non-main threads on E-cores.** Default-QoS threads are E-core
eligible on Apple silicon, where a 9 ms detect becomes 20 ms+. The capture
thread asks for P-cores via `pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE)`,
a no-op wherever it fails. (`camera.py:669-680`)

**Cyclic GC contributed surprise 10–50 ms pauses.** Once the heavy object
graphs (mediapipe, cv2, aiortc) are built, per-frame garbage dies by refcount,
so cyclic GC only costs latency. The session does `gc.collect()`,
`gc.freeze()`, `gc.set_threshold(50_000, 10, 10)` — frozen, not disabled,
because aiortc's asyncio does create reference cycles. (`cli.py:729-738`)

---

## The phone path (legacy): the median is physics, the rest is tail

Restore: `scripts/leapctl on --legacy --source phone`.

Baseline, 2026-08-18, iPhone → M5 MacBook Pro over LAN Wi-Fi:

| | |
|---|---|
| delivered | 57.2 fps |
| median inter-frame gap | 16.7 ms — exact 60 Hz |
| p95 | 29.5 ms |
| worst | 130 ms |
| gaps >25 ms | 74 per 20 s |
| MediaPipe detect | ~9 ms at VGA |

The median is the camera's own cadence, so everything else is a **tail-latency
problem**. Perception research gives the finish line: an **indirect** cursor is
indistinguishable from zero latency below **~50 ms**; direct-touch's ~10 ms
does not apply.
([latency-research-2026-08-18.md](../context/latency-research-2026-08-18.md))

### Eight fixes, worth ~17 ms/frame in fixed taxes

1. **The aiortc jitter-buffer marker-bit bug (~16.7 ms every frame).**
   `JitterBuffer._remove_frame` groups packets by RTP timestamp and only emits
   frame N when frame N+1's *first packet* arrives — it never reads the marker
   bit senders set on a frame's last packet. Verified in aiortc 1.15.0 source.
   Patched to emit on marker, with the different-timestamp path kept as
   fallback. **This is a general aiortc lesson, not a phone-specific one.**
2. **Jitter capacity 128 → 64.** Capacity-128 head-of-line blocks ~30 frames
   (~250–500 ms freeze) behind one unrecovered loss. Freshness beats
   completeness for a cursor.
3. **H.264 pinned** via `setCodecPreferences` — hardware VideoToolbox on
   iPhone, and RFC 7742 constrained-baseline forbids B-frames. Decoder gets
   FFmpeg's `low_delay`.
4. **REMB/abs-send-time stripped from the offer SDP.** aiortc's receive-side
   estimator initializes from Safari's conservative startup throughput and its
   REMB became a hard send ceiling — the measured 640×480 → 452×338 downscale
   at t=2 s. On a one-hop LAN the governor only hurts.
5. **Drain-to-latest at the ingress** — conflate at the ingress, not the
   egress.
6. **`contentHint='motion'` + a 4 Mbps cap** — a lower cap also means fewer RTP
   packets per frame, so one lost packet stalls less of the stream.
7. **Thread QoS pinned to USER_INTERACTIVE.**
8. **`gc.freeze()` after warmup.**

### Not applied — the roadmap, in the order it was ranked

- **Kill AWDL for the session** (`sudo ifconfig awdl0 down`). AirDrop/Handoff
  share the radio and channel-hop — the classic cause of exactly the observed
  30–130 ms periodic spikes. Cheapest big tail win; needs sudo.
- **USB-C tethering.** The Mac sees an `iPhone USB` NIC at 172.20.10.x. Deletes
  the jittery medium instead of tuning it.
- **Prediction.** A ~30–40 ms lead erases the remaining perceived latency.
  DESP (~10 lines, 135× cheaper than Kalman at equal accuracy) or TurboTouch
  (validated 32–48 ms artifact-free). Scale the horizon with hand speed,
  low-pass the *predicted* output, and blend back over ~100 ms on reacquisition
  rather than snapping — Quest's shipped pattern.
- **120 Hz cursor coasting** (a timewarp analogue).
- **Measure glass-to-cursor properly** before optimising further: the academic
  breakdowns warn that the *camera pipeline* (exposure + readout + sampling)
  can dominate everything.

**Skipped deliberately:** L4S/SCReAM (no queue on one LAN hop), RTMP/SRT/NDI
(unreachable from a browser), busy-polling (GIL fights), allocator swaps (GC
was the pause source), MediaPipe GPU delegate (marginal on macOS + a known
M-series leak), aiortc VideoToolbox decode (software VGA decode is ~2 ms).

### Measurement doctrine, worth keeping regardless

Dual-timestamp every hop and report **p99, not means**. A tight p50 with a wild
tail means *your* queue, not the network. And the 16.7 ms median inter-arrival
is the sender's cadence quantizing the measurement — real network jitter lives
in the residual around n×16.667 ms.

**Unheeded and important:** keep the hand **well lit**. Low light silently
extends exposure and can halve the delivered frame rate; no web API can lock
exposure on Safari.
