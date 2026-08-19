"""LPD1 receiver: the LeapDepth iOS companion's RGB+depth stream, phase 1.

The phone (ios/LeapDepth) connects over plain TCP and sends synchronized,
pixel-aligned RGB (JPEG) + depth (u16 millimetres, raw DEFLATE) frames plus
IMU samples. This module is the proving ground for the pipe:

    python -m leapinput.phonedepth      # listen, print the address + live stats

Phase 2 (once the stream is proven) is DepthPhoneSource: JPEG frames into
the existing MediaPipe loop, landmark pixels sampled against the aligned
depth map -> HandFrames with REAL metric z — retiring span-as-depth,
motion_scale and the ChArUco-hand assumption for this source. See
docs/context/depth-companion-plan.md.

Wire format (little-endian), one byte of message type then:

  0x01 frame:  u64 t_us | u8 camera | f32 fx,fy,cx,cy | u16 dw,dh
               | u32 rgb_len | u32 depth_len | JPEG | DEFLATE(u16 mm)
  0x02 imu:    u64 t_us | f32 gx,gy,gz          (m/s^2, incl. gravity)

Depth inflates with zlib wbits=-15: Apple's Compression framework "ZLIB"
is raw DEFLATE — no zlib header or checksum.
"""

from __future__ import annotations

import socket
import struct
import sys
import time
import zlib
from dataclasses import dataclass
from typing import Optional, Union

DEFAULT_PORT = 8447

_FRAME_HEAD = struct.Struct("<QB4fHHII")
_IMU_HEAD = struct.Struct("<Q3f")


@dataclass(frozen=True)
class DepthFrame:
    timestamp_us: int
    camera: str                     # "front" | "rear"
    fx: float
    fy: float
    cx: float
    cy: float
    depth_w: int
    depth_h: int
    jpeg: bytes
    depth_deflate: bytes

    def depth_mm(self):
        """Inflated u16 depth map as a depth_h x depth_w list of rows.
        0 = invalid. Kept dependency-free; phase 2 will go straight to
        numpy for the per-landmark sampling."""
        raw = zlib.decompress(self.depth_deflate, -15)
        it = struct.iter_unpack("<H", raw)
        flat = [v for (v,) in it]
        return [flat[r * self.depth_w:(r + 1) * self.depth_w]
                for r in range(self.depth_h)]


@dataclass(frozen=True)
class ImuSample:
    timestamp_us: int
    gx: float
    gy: float
    gz: float


class LPD1Parser:
    """Incremental parser: feed() TCP chunks in, complete messages out.

    Pure and allocation-light — the seam every protocol needs so framing
    bugs surface in tests rather than as mysterious mid-stream corruption.
    """

    MAX_PAYLOAD = 32 * 1024 * 1024      # a frame beyond this is corruption

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Union[DepthFrame, ImuSample]]:
        self._buf.extend(chunk)
        out: list[Union[DepthFrame, ImuSample]] = []
        while True:
            msg = self._try_parse()
            if msg is None:
                return out
            out.append(msg)

    def _try_parse(self) -> Optional[Union[DepthFrame, ImuSample]]:
        buf = self._buf
        if not buf:
            return None
        kind = buf[0]
        if kind == 0x02:
            need = 1 + _IMU_HEAD.size
            if len(buf) < need:
                return None
            t_us, gx, gy, gz = _IMU_HEAD.unpack_from(buf, 1)
            del buf[:need]
            return ImuSample(t_us, gx, gy, gz)
        if kind == 0x01:
            head_end = 1 + _FRAME_HEAD.size
            if len(buf) < head_end:
                return None
            (t_us, cam, fx, fy, cx, cy, dw, dh,
             rgb_len, depth_len) = _FRAME_HEAD.unpack_from(buf, 1)
            if rgb_len > self.MAX_PAYLOAD or depth_len > self.MAX_PAYLOAD:
                raise ValueError(
                    f"implausible payload ({rgb_len}/{depth_len} bytes) — "
                    f"stream corrupt or not LPD1")
            total = head_end + rgb_len + depth_len
            if len(buf) < total:
                return None
            jpeg = bytes(buf[head_end:head_end + rgb_len])
            depth = bytes(buf[head_end + rgb_len:total])
            del buf[:total]
            return DepthFrame(t_us, "front" if cam == 0 else "rear",
                              fx, fy, cx, cy, dw, dh, jpeg, depth)
        raise ValueError(f"unknown LPD1 message type 0x{kind:02x} — "
                         f"stream corrupt or not LPD1")


def encode_frame(frame: DepthFrame) -> bytes:
    """Inverse of the parser, for tests and future replay tooling."""
    head = _FRAME_HEAD.pack(
        frame.timestamp_us, 0 if frame.camera == "front" else 1,
        frame.fx, frame.fy, frame.cx, frame.cy,
        frame.depth_w, frame.depth_h,
        len(frame.jpeg), len(frame.depth_deflate))
    return b"\x01" + head + frame.jpeg + frame.depth_deflate


def encode_imu(sample: ImuSample) -> bytes:
    return b"\x02" + _IMU_HEAD.pack(sample.timestamp_us, sample.gx,
                                    sample.gy, sample.gz)


def _center_depth_mm(frame: DepthFrame) -> Optional[int]:
    rows = frame.depth_mm()
    if not rows:
        return None
    v = rows[frame.depth_h // 2][frame.depth_w // 2]
    return v or None


def main(argv=None) -> int:
    import argparse
    from .phonecam import lan_ip

    ap = argparse.ArgumentParser(prog="leapinput.phonedepth")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print(f"LPD1 receiver listening on {lan_ip()}:{args.port}")
    print("On the phone, open LeapDepth, enter that IP, tap Start.")
    try:
        while True:
            conn, addr = srv.accept()
            print(f"phone connected: {addr[0]}")
            _serve(conn)
            print("phone disconnected")
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        srv.close()
    return 0


def _serve(conn: socket.socket) -> None:
    parser = LPD1Parser()
    frames = 0
    window = time.monotonic()
    last_imu: Optional[ImuSample] = None
    try:
        while True:
            chunk = conn.recv(1 << 16)
            if not chunk:
                return
            for msg in parser.feed(chunk):
                if isinstance(msg, ImuSample):
                    last_imu = msg
                    continue
                frames += 1
                now = time.monotonic()
                if now - window >= 1.0:
                    center = _center_depth_mm(msg)
                    imu = (f"  imu {last_imu.gx:+.1f}/{last_imu.gy:+.1f}/"
                           f"{last_imu.gz:+.1f}" if last_imu else "")
                    print(f"{frames / (now - window):5.1f} fps  "
                          f"{msg.camera:5s}  rgb {len(msg.jpeg) / 1024:5.1f}kB  "
                          f"depth {msg.depth_w}x{msg.depth_h}  "
                          f"center {center or '—'}mm{imu}", flush=True)
                    frames = 0
                    window = now
    except (ConnectionError, ValueError) as e:
        print(f"stream ended: {e}", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
