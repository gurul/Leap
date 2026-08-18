# Low-latency research pass — 2026-08-18

Seven parallel research streams (aiortc internals, Safari sender behavior,
academic real-time-video literature, alternative transports, tracking-side
latency compensation, the HFT/quant low-latency playbook, and the measurement
doctrine from the owner's latency-arbitrage research corpus) on one question:
how low can phone→Mac glass-to-cursor latency go, and what actually matters.

Baseline that day: 57.2 fps delivered, median inter-frame gap 16.7 ms (exact
60 Hz), p95 29.5 ms, worst 130 ms, 74 gaps >25 ms per 20 s; MediaPipe ~9 ms at
VGA on the M5.

## Framing (the one-paragraph version)

The median is physics — 16.7 ms is the camera's own cadence. Everything else
is a **tail-latency problem**, the regime HFT engineering targets: fixed taxes
hiding in the receive path, and Wi-Fi jitter owning the p95/p99. Perception
research gives the finish line: an *indirect* cursor (remote hand moving a
pointer) is indistinguishable from zero latency below ~50 ms; direct-touch
research (~10 ms) does not apply to us.

## Applied (in `phonecam.py` / `camera.py` / `cli.py`, tested)

1. **JitterBuffer marker-bit patch (~16.7 ms/frame).** aiortc's
   `JitterBuffer._remove_frame` groups packets by RTP timestamp and only emits
   frame N when frame N+1's *first packet* arrives — it never reads the marker
   bit senders set on a frame's last packet. Verified in aiortc 1.15.0 source.
   Patched to emit on marker; the different-timestamp path remains as fallback.
2. **Video jitter capacity 128 → 64.** Capacity-128 head-of-line blocks up to
   ~30 frames behind one unrecovered loss (~250–500 ms freeze) before
   `smart_remove` + PLI force recovery. 64 quarters the worst stall and still
   fits a keyframe at our bitrate. NACK itself is already immediate/event-driven
   in aiortc — loss recovery needed no tuning.
3. **H.264 pinned via `setCodecPreferences`.** VP8/VP9 are software-encoded on
   iPhone; H.264 is hardware VideoToolbox, and RFC 7742 constrained-baseline
   forbids B-frames (no reorder delay). Decoder gets FFmpeg's `low_delay` flag
   as free insurance (PyAV 17 already defaults to SLICE threading — no
   frame-threading delay existed).
4. **REMB/abs-send-time stripped from the offer SDP.** aiortc's receive-side
   bandwidth estimator initializes from Safari's conservative startup
   throughput and its REMB becomes a hard send ceiling — the measured
   640×480 → 452×338 downscale at t=2 s. On a one-hop LAN the governor only
   hurts; without the abs-send-time extension it never engages.
5. **Drain-to-latest at the ingress.** `RemoteStreamTrack._queue` is unbounded;
   `_consume` now conflates to the newest queued frame *before* paying
   conversion cost ("conflate at the ingress, not the egress").
6. **Sender knobs:** `contentHint='motion'` (second, independent
   maintain-framerate signal Safari reads) and `maxBitrate` 10 → 4 Mbps —
   fewer RTP packets per frame means one lost packet stalls less stream, and
   VGA60 hand tracking doesn't need more.
7. **Thread QoS pinned to USER_INTERACTIVE** (capture thread + receiver
   thread): macOS has no CPU affinity; default-QoS threads are E-core-eligible
   on Apple silicon, where the 9 ms detect becomes 20 ms+ under load.
8. **GC discipline:** `gc.freeze()` after the object graphs are built, then
   thresholds (50 000, 10, 10) — per-frame garbage dies by refcount; cyclic GC
   only contributed surprise 10–50 ms pauses.

## Not applied — ranked roadmap

- **Kill AWDL for the session** (`sudo ifconfig awdl0 down`): AirDrop/Handoff
  share the Mac's radio and hop channels; this is the classic cause of exactly
  our 30–130 ms periodic spikes. Needs sudo, breaks AirDrop while down —
  user's call. Cheapest big tail win on Wi-Fi.
- **USB-C tethering (Personal Hotspot over cable)**: the true "kernel bypass" —
  deletes the jittery medium instead of tuning it. The Mac sees an `iPhone
  USB` NIC (172.20.10.x); bind the server there and every >25 ms gap should
  vanish. Also: put the Mac on Ethernet regardless — phone→AP→Mac crosses the
  air twice today.
- **Prediction (the perception win).** A ~30–40 ms lead erases the remaining
  perceived latency for an indirect cursor. Order of preference: DESP (double
  exponential smoothing predictor — ~10 lines, 135× cheaper than Kalman at
  equal accuracy), or TurboTouch from the 1€-filter authors (validated
  32–48 ms artifact-free). Key details from the VR literature: scale the
  horizon with hand speed (zero at rest), low-pass the *predicted* output, and
  on reacquiring after a gap blend back over ~100 ms instead of snapping
  (Meta Quest's shipped pattern).
- **120 Hz cursor coasting (timewarp analog).** Decouple cursor emission from
  frame arrival: a 120 Hz timer extrapolates from the last (position,
  velocity, timestamp) so Wi-Fi gaps coast instead of freezing.
- **Measure glass-to-cursor properly.** 240 fps slo-mo of hand + screen
  together (~4 ms resolution), or the phone filming a millisecond clock on the
  Mac screen for capture-stage latency. The academic breakdowns warn the
  *camera pipeline* (exposure + readout + sampling) can dominate everything —
  measure before optimizing further. Also try `frameRate: {ideal: 120}`
  capture (halves average sampling delay even when sending 60) and keep the
  hand **well lit**: low light silently extends exposure and can halve the
  delivered frame rate; no web API can lock exposure on Safari.
- **WebCodecs + WebSocket/WebTransport** (Safari 16.4+/26.4+): owns the whole
  path — no jitter buffer, no congestion controller. The clean rewrite if
  WebRTC ever feels limiting; MJPEG-over-WebSocket is the 100-line fallback.
- **Skipped deliberately:** L4S/SCReAM (no queue to manage on one LAN hop),
  RTMP/SRT/NDI (unreachable from a browser), busy-polling (µs wins, GIL
  fights), allocator swaps (GC was the pause source, not obmalloc), MediaPipe
  GPU delegate (marginal on macOS + known M-series leak), aiortc VideoToolbox
  decode (SW VGA decode is ~2 ms).

## Measurement doctrine (from the latency-arbitrage corpus)

Worth keeping even without new code: dual-timestamp every hop (capture, wire,
decode, detect, post) and report p99, not means; a tight p50 with a wild tail
means *your* queue, not the network — the corpus's headline case was a 6-second
p99 the author blamed on the venue that was actually collector backpressure.
Min-transport-delay envelopes bound clock drift between unsynced devices; a
per-minute minimum of (recv − capture) is the zero-offset baseline. And the
16.7 ms median inter-arrival is the sender's cadence quantizing the
measurement — real network jitter lives in the residual around n×16.667 ms.
