"""The phone's camera as a Leap source — Safari + WebRTC, no app, no driver.

The phone's browser IS the capture app: one HTTPS page (served from this Mac)
calls getUserMedia at 60fps and streams the camera over WebRTC to an in-process
aiortc receiver. Decoded frames drop into CameraSource's MediaPipe loop through
the same read()/grab() shim a webcam uses — no CoreMediaIO virtual camera, no
App Store, no paired Apple ID.

How the pieces fit (the "server" is only a doorman, video never touches it):
  1. GET /<token>        -> the capture page (getUserMedia + RTCPeerConnection)
  2. POST /<token>/offer -> SDP handshake: the page describes its stream, we
                            answer. One round trip, then HTTP is out of the loop.
  3. Video flows phone->Mac directly over UDP (DTLS-SRTP, hardware H.264),
     LAN-only, no STUN/TURN — host ICE candidates are enough on one network.

Security posture: a LAN convenience server. TLS is a self-signed cert (Safari
demands a secure context for getUserMedia; expect the one-time "not private"
warning). The random URL token is the only auth — enough to keep a roommate's
browser from streaming THEIR camera into your cursor, not more than that.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import socket
import ssl
import subprocess
import threading
from pathlib import Path

from .camera import CameraSource, set_thread_qos_user_interactive

STATE_DIR = Path.home() / ".leapinput"
DEFAULT_PORT = 8443
# Detection wants ~VGA; bigger frames only pay cvtColor/copy tax. The page
# requests 640x480@60 but Safari treats constraints as suggestions.
MAX_WIDTH = 1024

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Leap phone camera</title>
<style>
  body { margin: 0; font: 16px -apple-system, sans-serif; background: #111;
         color: #eee; text-align: center; }
  video { width: 100%; max-height: 60vh; background: #000; }
  button { font-size: 18px; margin: 8px; padding: 12px 20px; border-radius: 10px;
           border: none; background: #2b6cb0; color: white; }
  #stat { padding: 8px; color: #9ae6b4; min-height: 1.4em; }
</style>
<video id="v" playsinline autoplay muted></video>
<div id="stat">not streaming</div>
<div>
  <button onclick="start('environment')">Start (rear)</button>
  <button onclick="start('user')">Start (front)</button>
</div>
<script>
let pc = null;
const stat = (m) => document.getElementById('stat').textContent = m;

async function start(facing) {
  if (pc) { pc.close(); pc = null; }
  // IMU permission must be requested inside the tap gesture, before any
  // await breaks the gesture context. Denied or unavailable = no channel
  // data; everything else works unchanged.
  let imuOk = true;
  try {
    if (window.DeviceMotionEvent && DeviceMotionEvent.requestPermission)
      imuOk = (await DeviceMotionEvent.requestPermission()) === 'granted';
  } catch (e) { imuOk = false; }
  stat('asking for camera…');
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode: facing,
             width: { ideal: 640 }, height: { ideal: 480 },
             frameRate: { ideal: 60, max: 60 } },
  });
  document.getElementById('v').srcObject = stream;
  try { await navigator.wakeLock.request('screen'); } catch (e) {}
  // Second, independent maintain-framerate knob Safari reads (spec maps
  // contentHint 'motion' to frame-rate-preserving encoder behavior).
  stream.getVideoTracks().forEach(t => { try { t.contentHint = 'motion'; } catch (e) {} });

  pc = new RTCPeerConnection({ iceServers: [] });   // LAN: no STUN needed
  stream.getTracks().forEach(t => pc.addTrack(t, stream));
  // IMU side-channel: the accelerometer rides along at 5Hz so the Mac can
  // notice the STAND being bumped (a fixed-camera calibration guard) and
  // know the camera's tilt. Created before the offer so it lands in SDP.
  const imu = pc.createDataChannel('imu');
  if (imuOk && window.DeviceMotionEvent) {
    let last = null;
    window.addEventListener('devicemotion', (e) => { last = e; });
    setInterval(() => {
      if (imu.readyState !== 'open' || !last) return;
      const g = last.accelerationIncludingGravity || {};
      try { imu.send(JSON.stringify(
        { x: g.x || 0, y: g.y || 0, z: g.z || 0 })); } catch (e) {}
    }, 200);
  }
  // Frame rate over resolution when congestion control squeezes. 4 Mbps is
  // ~5x what VGA60 hand tracking needs; a LOWER cap also means fewer RTP
  // packets per frame, so one lost packet stalls less of the stream.
  const sender = pc.getSenders().find(s => s.track && s.track.kind === 'video');
  if (sender) {
    const p = sender.getParameters();
    p.degradationPreference = 'maintain-framerate';
    if (!p.encodings || !p.encodings.length) p.encodings = [{}];
    p.encodings[0].maxBitrate = 4_000_000;
    try { await sender.setParameters(p); } catch (e) {}
  }
  pc.onconnectionstatechange = () => report(stream);
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(r => {                 // aiortc is no-trickle: gather fully
    if (pc.iceGatheringState === 'complete') return r();
    pc.onicegatheringstatechange = () =>
      pc.iceGatheringState === 'complete' && r();
  });
  const resp = await fetch(location.pathname + '/offer', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sdp: pc.localDescription.sdp,
                           type: pc.localDescription.type }),
  });
  await pc.setRemoteDescription(await resp.json());
  report(stream);
  setInterval(() => report(stream), 2000);
}

function report(stream) {
  const t = stream.getVideoTracks()[0];
  const s = t ? t.getSettings() : {};
  stat(`${pc ? pc.connectionState : '-'} — ${s.width}x${s.height} ` +
       `@ ${s.frameRate ? s.frameRate.toFixed(0) : '?'} fps requested`);
}
</script>
"""


def _patch_aiortc_low_latency() -> None:
    """Remove three receiver-side latency taxes in aiortc 1.x (verified against
    its source; research pass 2026-08-18, docs/context/latency-research doc).

    1. JitterBuffer._remove_frame only emits frame N when frame N+1's FIRST
       packet arrives — it groups packets by RTP timestamp and never reads the
       marker bit that senders set on a frame's last packet. At 60fps that is
       a built-in ~16.7ms delay on every frame. Patch: also emit when the
       contiguous run from _origin ends in a marker packet.
    2. Video capacity 128 head-of-line blocks up to ~30 frames behind one
       unrecovered loss (~250-500ms freeze before forced recovery). 64 still
       fits the largest keyframe at our bitrate while quartering the stall;
       overflow triggers smart_remove + PLI (a fresh keyframe) — the right
       trade for cursor control, where freshness beats completeness.
    3. The H264 decoder is created with default flags; low_delay guarantees
       FFmpeg never holds a picture for reordering (Safari sends constrained
       baseline, no B-frames, so this costs nothing).
    """
    import av
    from aiortc.codecs import h264
    from aiortc.jitterbuffer import JitterBuffer, JitterFrame

    if getattr(JitterBuffer, "_leap_patched", False):
        return
    JitterBuffer._leap_patched = True

    orig_remove_frame = JitterBuffer._remove_frame

    def _remove_frame(self, sequence_number):
        frame = orig_remove_frame(self, sequence_number)
        if frame is not None or not self._is_video or self._origin is None:
            return frame
        packets = []
        timestamp = None
        for count in range(self._capacity):
            pos = (self._origin + count) % self._capacity
            packet = self._packets[pos]
            if packet is None:
                break
            if timestamp is None:
                timestamp = packet.timestamp
            elif packet.timestamp != timestamp:
                return None         # complete frame; original path owns this
            packets.append(packet)
            if packet.marker:
                self.remove(count + 1)
                return JitterFrame(
                    data=b"".join(x._data for x in packets), timestamp=timestamp)
        return None

    JitterBuffer._remove_frame = _remove_frame

    orig_init = JitterBuffer.__init__

    def _init(self, capacity, prefetch=0, is_video=False):
        if is_video and capacity == 128:
            capacity = 64
        orig_init(self, capacity, prefetch=prefetch, is_video=is_video)

    JitterBuffer.__init__ = _init

    orig_dec_init = h264.H264Decoder.__init__

    def _dec_init(self):
        orig_dec_init(self)
        self.codec.flags |= av.codec.context.Flags.low_delay

    h264.H264Decoder.__init__ = _dec_init


def lan_ip() -> str:
    """The Mac's LAN address, as the phone will reach it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 1))    # TEST-NET; nothing is sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _ensure_token() -> str:
    """Random URL path segment, persisted so the phone bookmark keeps working."""
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / "phonecam-token"
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(4)
    path.write_text(token)
    return token


def _ensure_cert() -> tuple[Path, Path]:
    """Self-signed TLS pair — getUserMedia only runs in a secure context."""
    STATE_DIR.mkdir(exist_ok=True)
    cert, key = STATE_DIR / "phonecam-cert.pem", STATE_DIR / "phonecam-key.pem"
    if not (cert.exists() and key.exists()):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-days", "3650", "-subj", "/CN=leapinput-phonecam",
             "-keyout", str(key), "-out", str(cert)],
            check=True, capture_output=True, timeout=30)
    return cert, key


class _PhoneCapture:
    """cv2.VideoCapture-shaped shim over the WebRTC receiver.

    read() blocks until a frame NEWER than the last one served arrives, so the
    pipeline always sees the freshest frame and slow detection drops frames
    instead of queueing them — grab()-draining is a no-op by construction.
    """

    def __init__(self, server: "_PhoneCamServer"):
        self._server = server
        self._last_seq = 0

    def isOpened(self) -> bool:  # noqa: N802 - matching cv2's camelCase
        return True

    def grab(self) -> bool:
        return True

    def read(self):
        srv = self._server
        with srv.cond:
            srv.cond.wait_for(lambda: srv.seq > self._last_seq, timeout=1.0)
            if srv.seq <= self._last_seq:
                return False, None          # nothing streaming right now
            self._last_seq = srv.seq
            return True, srv.frame

    def release(self) -> None:
        self._server.stop()


class _PhoneCamServer:
    """Owns the asyncio thread: HTTPS page + signaling + the receiving peer."""

    # A fixed-camera setup is a calibration resting on the assumption that
    # the camera does not move. The phone's own accelerometer checks that
    # assumption: gravity is tracked with an EMA, and a deviation past this
    # threshold (m/s^2) means the stand was BUMPED — worth telling the user,
    # because a nudged phone silently degrades the fitted reach geometry.
    BUMP_MS2 = 1.5
    BUMP_WARN_EVERY_S = 5.0

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.token = _ensure_token()
        self.url = f"https://{lan_ip()}:{port}/{self.token}"
        self.cond = threading.Condition()
        self.frame = None                  # BGR ndarray, newest wins
        self.seq = 0
        # IMU state (written by the datachannel handler on the asyncio
        # thread; read anywhere — tuple/float writes are atomic).
        self.imu_gravity: tuple[float, float, float] | None = None
        self.stand_moved_at = 0.0          # time.monotonic() of the last bump
        self._imu_warned_at = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pc = None
        self._runner = None
        self._ready = threading.Event()
        self._start_error: BaseException | None = None

    # -- thread plumbing --------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._thread_main, name="phonecam", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("phonecam server did not start within 10s")
        if self._start_error is not None:
            raise RuntimeError(
                f"phonecam server failed to start: {self._start_error}")

    def stop(self) -> None:
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._shutdown(), self._loop).result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _thread_main(self) -> None:
        set_thread_qos_user_interactive()
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as e:      # surface bind/TLS errors to start()
            self._start_error = e
            self._ready.set()
            return
        self._ready.set()
        self._loop.run_forever()

    # -- the doorman ------------------------------------------------------

    async def _serve(self) -> None:
        from aiohttp import web

        app = web.Application()
        app.router.add_get(f"/{self.token}", self._page)
        app.router.add_post(f"/{self.token}/offer", self._offer)
        cert, key = _ensure_cert()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port, ssl_context=ctx)
        await site.start()

    async def _page(self, request):
        from aiohttp import web
        return web.Response(text=PAGE, content_type="text/html")

    async def _offer(self, request):
        from aiohttp import web
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from aiortc.rtcrtpsender import RTCRtpSender

        _patch_aiortc_low_latency()
        params = await request.json()
        # Disable receive-side bandwidth estimation: on a one-hop LAN the REMB
        # governor only hurts — it initializes from Safari's conservative
        # startup throughput and becomes a hard send ceiling that downscales
        # the stream (measured: 640x480 -> 452x338 at t=2s). No abs-send-time
        # extension means the estimator never feeds, so no REMB is sent.
        sdp = re.sub(r"^a=extmap:\d+ [^\r\n]*abs-send-time[^\r\n]*\r?\n", "",
                     params["sdp"], flags=re.M)
        sdp = re.sub(r"^a=rtcp-fb:\d+ goog-remb\r?\n", "", sdp, flags=re.M)
        if self._pc is not None:           # page reloaded: newest phone wins
            await self._pc.close()
        pc = self._pc = RTCPeerConnection()

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                asyncio.ensure_future(self._consume(track))

        @pc.on("datachannel")
        def on_datachannel(channel):
            if channel.label != "imu":
                return

            @channel.on("message")
            def on_message(message):
                try:
                    self._on_imu(json.loads(message))
                except Exception:
                    pass        # sensor telemetry must never hurt the stream

        @pc.on("connectionstatechange")
        async def on_state():
            print(f"phonecam: peer {pc.connectionState}", flush=True)

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp, type=params["type"]))
        # Pin H.264: hardware VideoToolbox encode on the phone. Left to
        # negotiation, VP8 can win and put a software encoder on the hot path.
        h264_caps = [c for c in RTCRtpSender.getCapabilities("video").codecs
                     if c.mimeType.lower() in ("video/h264", "video/rtx")]
        for t in pc.getTransceivers():
            if t.kind == "video" and h264_caps:
                t.setCodecPreferences(h264_caps)
        await pc.setLocalDescription(await pc.createAnswer())
        return web.Response(
            content_type="application/json",
            text=json.dumps({"sdp": pc.localDescription.sdp,
                             "type": pc.localDescription.type}))

    def _on_imu(self, sample: dict) -> None:
        """One accelerometer sample -> gravity estimate + bump detection.

        Gravity is the EMA of accelerationIncludingGravity; a sample far
        from it is the stand being moved. The dynamic palm box re-anchors on
        the next hand appearance anyway, so a small nudge self-heals — the
        warning matters for the pieces that do NOT (working distance,
        anything assuming the calibrated viewpoint).
        """
        import time as _time
        v = (float(sample.get("x", 0.0)), float(sample.get("y", 0.0)),
             float(sample.get("z", 0.0)))
        g = self.imu_gravity
        if g is None:
            self.imu_gravity = v
            return
        delta = ((v[0] - g[0]) ** 2 + (v[1] - g[1]) ** 2
                 + (v[2] - g[2]) ** 2) ** 0.5
        self.imu_gravity = tuple(0.9 * a + 0.1 * b for a, b in zip(g, v))
        if delta > self.BUMP_MS2:
            now = _time.monotonic()
            self.stand_moved_at = now
            if now - self._imu_warned_at > self.BUMP_WARN_EVERY_S:
                self._imu_warned_at = now
                print("phonecam: the phone/stand just MOVED (IMU) — the "
                      "box re-anchors on your next hand appearance; if the "
                      "distance or angle changed, re-run "
                      "`python -m leapinput.reach corners`", flush=True)

    async def _consume(self, track) -> None:
        import cv2
        from aiortc.mediastreams import MediaStreamError

        while True:
            try:
                av_frame = await track.recv()
                # Conflate at the ingress: track._queue is UNBOUNDED, so any
                # stall lets frames pile up — drain to the newest before
                # paying conversion cost, instead of converting doomed frames.
                try:
                    while True:
                        newer = track._queue.get_nowait()
                        if newer is None:
                            raise MediaStreamError
                        av_frame = newer
                except asyncio.QueueEmpty:
                    pass
            except MediaStreamError:
                return
            bgr = av_frame.to_ndarray(format="bgr24")
            h, w = bgr.shape[:2]
            if w > MAX_WIDTH:
                bgr = cv2.resize(bgr, (MAX_WIDTH, int(h * MAX_WIDTH / w)),
                                 interpolation=cv2.INTER_AREA)
            with self.cond:
                self.frame = bgr
                self.seq += 1
                self.cond.notify_all()

    async def _shutdown(self) -> None:
        if self._pc is not None:
            await self._pc.close()
            self._pc = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None


class PhoneSource(CameraSource):
    """CameraSource whose frames arrive from the phone instead of a device."""

    def __init__(self, port: int = DEFAULT_PORT, **kwargs):
        super().__init__(camera=None, **kwargs)
        try:
            import aiohttp   # noqa: F401
            import aiortc    # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "--source phone needs the phone extra: "
                "VIRTUAL_ENV=$PWD/.venv uv pip install -e '.[phone]'") from e
        self._server = _PhoneCamServer(port=port)

    @property
    def url(self) -> str:
        return self._server.url

    @property
    def imu_gravity(self) -> tuple[float, float, float] | None:
        """Phone gravity vector (m/s^2), when the page granted DeviceMotion."""
        return self._server.imu_gravity

    @property
    def stand_moved_at(self) -> float:
        """time.monotonic() of the last IMU-detected stand bump (0 = never)."""
        return self._server.stand_moved_at

    def _open_capture(self, cv2):
        self._server.start()
        return _PhoneCapture(self._server)
