"""LPD1 protocol tests: the framing seam between the LeapDepth iOS app and
the Mac. Framing bugs must die here, not as mid-stream corruption."""

import struct
import zlib

import pytest

from leapinput.phonedepth import (DepthFrame, ImuSample, LPD1Parser,
                                  encode_frame, encode_imu)


def deflate_raw(payload: bytes) -> bytes:
    """Apple's Compression 'ZLIB' is raw DEFLATE — mirror it exactly."""
    c = zlib.compressobj(1, zlib.DEFLATED, -15)
    return c.compress(payload) + c.flush()


def make_frame(t_us=1_000_000, camera="front", w=4, h=3):
    depth = struct.pack(f"<{w * h}H", *range(100, 100 + w * h))
    return DepthFrame(t_us, camera, 500.0, 500.0, 320.0, 240.0,
                      w, h, b"\xff\xd8fakejpeg\xff\xd9", deflate_raw(depth))


def test_frame_roundtrips_through_the_parser():
    frame = make_frame()
    [out] = LPD1Parser().feed(encode_frame(frame))
    assert out == frame
    rows = out.depth_mm()
    assert len(rows) == 3 and len(rows[0]) == 4
    assert rows[0][0] == 100 and rows[2][3] == 111


def test_messages_survive_arbitrary_tcp_chunking():
    """TCP has no message boundaries: byte-at-a-time must still parse."""
    stream = (encode_imu(ImuSample(5, 0.1, 9.7, 1.2))
              + encode_frame(make_frame())
              + encode_frame(make_frame(t_us=2_000_000, camera="rear")))
    parser = LPD1Parser()
    out = []
    for i in range(len(stream)):
        out.extend(parser.feed(stream[i:i + 1]))
    assert [type(m).__name__ for m in out] == \
        ["ImuSample", "DepthFrame", "DepthFrame"]
    assert out[2].camera == "rear"


def test_corrupt_stream_raises_instead_of_wandering():
    with pytest.raises(ValueError, match="unknown LPD1"):
        LPD1Parser().feed(b"\x7fgarbage")
    huge = b"\x01" + struct.pack("<QB4fHHII", 0, 0, 0, 0, 0, 0, 1, 1,
                                 1 << 30, 0)
    with pytest.raises(ValueError, match="implausible"):
        LPD1Parser().feed(huge)


def test_zero_depth_reads_as_invalid():
    w, h = 2, 1
    depth = struct.pack("<2H", 0, 450)
    frame = DepthFrame(1, "front", 1.0, 1.0, 0.0, 0.0, w, h,
                       b"j", deflate_raw(depth))
    [out] = LPD1Parser().feed(encode_frame(frame))
    assert out.depth_mm() == [[0, 450]]
