"""M2.1 deterministic synthetic WAV fixtures: no private audio or firmware."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct
import tempfile
import unittest

from xtwavetable.audio import WavFormatError, decode_wav, read_wav

PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
FLOAT_GUID = bytes.fromhex("0300000000001000800000aa00389b71")


def chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def make_wav(*, frames: bytes, sample_rate: int = 44100, channels: int = 1,
             bits: int = 16, format_tag: int = 1, extensible: bool = False,
             custom_chunks: tuple[bytes, ...] = ()) -> bytes:
    align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 0xFFFE if extensible else format_tag,
                      channels, sample_rate, sample_rate * align, align, bits)
    if extensible:
        fmt += struct.pack("<HHI", 22, bits, 0) + (FLOAT_GUID if format_tag == 3 else PCM_GUID)
    body = b"WAVE" + chunk(b"fmt ", fmt) + b"".join(custom_chunks) + chunk(b"data", frames)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def pcm24(value: int) -> bytes:
    return value.to_bytes(3, "little", signed=True)


class WavReaderTests(unittest.TestCase):
    def test_pcm16_rates_and_native_sample_count(self):
        for rate in (44100, 48000, 96000, 88200, 192000):
            with self.subTest(rate=rate):
                data = make_wav(frames=struct.pack("<hhh", -32768, 0, 32767), sample_rate=rate)
                audio = decode_wav(data)
                self.assertEqual((audio.sample_rate, audio.frame_count, audio.channels), (rate, 3, 1))
                self.assertEqual(audio.samples, (-1.0, 0.0, 32767 / 32768))
                self.assertEqual(audio.duration_seconds, 3 / rate)

    def test_synthetic_sine_440_hz_across_rates(self):
        # Known signal at native sample rate; no hidden resampling or normalization.
        for rate in (44100, 48000, 96000):
            with self.subTest(rate=rate):
                frames = [int(round(0.75 * 32767 * math.sin(2 * math.pi * 440 * i / rate)))
                          for i in range(rate // 10)]
                raw = make_wav(frames=struct.pack("<" + "h" * len(frames), *frames),
                               sample_rate=rate)
                audio = decode_wav(raw)
                self.assertEqual(audio.frame_count, len(frames))
                self.assertEqual(audio.sample_rate, rate)
                self.assertAlmostEqual(audio.duration_seconds, 0.1)
                for i in range(0, len(frames), max(1, len(frames) // 40)):
                    self.assertEqual(audio.samples[i], frames[i] / 32768.0)
                self.assertLess(audio.peak_abs, 0.76)

    def test_pcm24_signed_min_max(self):
        data = make_wav(frames=b"".join(map(pcm24, (-8388608, -1, 0, 8388607))), bits=24)
        self.assertEqual(decode_wav(data).samples, (-1.0, -1 / 8388608, 0.0, 8388607 / 8388608))

    def test_pcm32_signed_min_max(self):
        data = make_wav(frames=struct.pack("<ii", -2147483648, 2147483647), bits=32)
        audio = decode_wav(data)
        self.assertEqual(audio.samples, (-1.0, 2147483647 / 2147483648))

    def test_float32_exact_values_and_over_zero_dbfs(self):
        data = make_wav(frames=struct.pack("<fff", -1.25, 0.25, 1.5), bits=32, format_tag=3)
        audio = decode_wav(data)
        self.assertEqual(audio.encoding, "float")
        self.assertEqual(audio.samples, (-1.25, 0.25, 1.5))
        self.assertEqual(audio.peak_abs, 1.5)

    def test_stereo_interleaving_and_channel_access(self):
        data = make_wav(frames=struct.pack("<hhhh", -32768, 32767, 0, 16384), channels=2)
        audio = decode_wav(data)
        self.assertEqual(audio.frame_count, 2)
        self.assertEqual(audio.channel_samples(0), (-1.0, 0.0))
        self.assertEqual(audio.channel_samples(1), (32767 / 32768, 0.5))
        for bad in (-1, 2, True):
            with self.subTest(bad=bad), self.assertRaises(IndexError):
                audio.channel_samples(bad)

    def test_extensible_pcm24(self):
        raw = make_wav(frames=pcm24(-1), bits=24, extensible=True)
        self.assertEqual(decode_wav(raw).samples, (-1 / 8388608,))

    def test_extensible_float32(self):
        raw = make_wav(frames=struct.pack("<f", 0.5), bits=32, format_tag=3, extensible=True)
        self.assertEqual(decode_wav(raw).samples, (0.5,))

    def test_odd_junk_chunk_and_nonstandard_chunk_order(self):
        raw = make_wav(frames=struct.pack("<h", 1234), custom_chunks=(chunk(b"JUNK", b"xyz"),))
        self.assertEqual(decode_wav(raw).samples, (1234 / 32768,))
        # fmt after data is permitted by this RIFF parser (chunk order independent).
        fmt_start = raw.index(b"fmt ")
        data_start = raw.index(b"data")
        fmt_part = raw[fmt_start:data_start]
        data_part = raw[data_start:]
        body = b"WAVE" + data_part + fmt_part
        reversed_order = b"RIFF" + struct.pack("<I", len(body)) + body
        self.assertEqual(decode_wav(reversed_order).samples, (1234 / 32768,))

    def test_missing_or_truncated_header(self):
        for raw in (b"", b"RIFF", b"RIFX" + b"\0" * 32, b"RIFF\x00\x00\x00\x00WAVE"):
            with self.subTest(raw=raw[:8]), self.assertRaises(WavFormatError):
                decode_wav(raw)

    def test_bad_riff_declared_size(self):
        raw = bytearray(make_wav(frames=struct.pack("<h", 1)))
        struct.pack_into("<I", raw, 4, len(raw) + 100)
        with self.assertRaises(WavFormatError):
            decode_wav(bytes(raw))

    def test_truncated_chunk_header_or_payload(self):
        orig = make_wav(frames=struct.pack("<h", 1))
        for tail in (b"abc", b"ABCD" + struct.pack("<I", 100) + b"x"):
            raw = orig + tail
            raw = raw[:4] + struct.pack("<I", len(raw) - 8) + raw[8:]
            with self.subTest(tail=tail), self.assertRaises(WavFormatError):
                decode_wav(raw)

    def test_missing_padding_byte(self):
        raw = make_wav(frames=struct.pack("<h", 1), custom_chunks=(chunk(b"JUNK", b"x"),))
        p = raw.index(b"JUNK")
        broken = raw[:p+9] + raw[p+10:]
        broken = broken[:4] + struct.pack("<I", len(broken)-8) + broken[8:]
        with self.assertRaises(WavFormatError):
            decode_wav(broken)

    def test_duplicate_fmt_and_data_rejected(self):
        raw = make_wav(frames=struct.pack("<h", 1))
        for duplicate in (chunk(b"fmt ", raw[20:36]), chunk(b"data", b"\x00\x00")):
            broken = raw + duplicate
            broken = broken[:4] + struct.pack("<I", len(broken) - 8) + broken[8:]
            with self.subTest(tag=duplicate[:4]), self.assertRaises(WavFormatError):
                decode_wav(broken)

    def test_unsupported_channels_formats_and_sample_rates(self):
        for params in ({"channels": 3}, {"channels": 0}, {"sample_rate": 0},
                       {"sample_rate": 500000}, {"bits": 8},
                       {"format_tag": 6}, {"bits": 16, "format_tag": 3}):
            with self.subTest(params=params), self.assertRaises(WavFormatError):
                decode_wav(make_wav(frames=b"\0" * 12, **params))

    def test_invalid_byte_rate_and_block_align(self):
        for offset in (28, 32):
            raw = bytearray(make_wav(frames=struct.pack("<h", 1)))
            raw[offset] = 0
            with self.subTest(offset=offset), self.assertRaises(WavFormatError):
                decode_wav(bytes(raw))

    def test_float_nan_and_inf_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(WavFormatError):
                decode_wav(make_wav(frames=struct.pack("<f", value), bits=32, format_tag=3))

    def test_empty_and_misaligned_data_rejected(self):
        for data in (b"", b"\x00", b"\0" * 3):
            with self.subTest(data=data), self.assertRaises(WavFormatError):
                decode_wav(make_wav(frames=data))

    def test_extensible_mismatched_valid_bits_rejected(self):
        raw = bytearray(make_wav(frames=pcm24(1), bits=24, extensible=True))
        # fmt starts at byte 20; extensible valid bits is fmt offset 18.
        struct.pack_into("<H", raw, 20 + 18, 20)
        with self.assertRaises(WavFormatError):
            decode_wav(bytes(raw))

    def test_max_size_bound_and_input_types(self):
        raw = make_wav(frames=struct.pack("<h", 1))
        with self.assertRaises(WavFormatError):
            decode_wav(raw, max_input_bytes=20)
        with self.assertRaises(TypeError):
            decode_wav(bytearray(raw))
        with self.assertRaises(ValueError):
            decode_wav(raw, max_input_bytes=True)

    def test_readonly_file_byte_identity(self):
        raw = make_wav(frames=struct.pack("<hhh", 1, 2, 3), sample_rate=96000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.wav"
            path.write_bytes(raw)
            initial_hash = hashlib.sha256(path.read_bytes()).digest()
            audio = read_wav(path)
            self.assertEqual(audio.frame_count, 3)
            self.assertEqual(audio.sample_rate, 96000)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), initial_hash)


if __name__ == "__main__":
    unittest.main()
