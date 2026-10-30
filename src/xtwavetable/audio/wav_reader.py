"""Deterministic, read-only RIFF/WAVE decoder for M2.1.

Supported: little-endian RIFF PCM 16/24/32-bit or IEEE float 32-bit,
mono/stereo, including standard WAVE_FORMAT_EXTENSIBLE headers with matching
container and valid bit depths. Other layouts are explicitly rejected.

No resampling, downmix, gain changes, or writing. A bounded in-memory reader
is intentional for this initial milestone; streaming large files is future work.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import struct

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_INTERLEAVED_SAMPLES = 8_000_000
_PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
_FLOAT_GUID = bytes.fromhex("0300000000001000800000aa00389b71")


class WavFormatError(ValueError):
    """Malformed or unsupported RIFF/WAVE input."""


@dataclass(frozen=True, slots=True)
class WavAudio:
    """Decoded interleaved samples in normalized float units (no gain changes).

    Integer PCM is converted to [-1.0, 1.0) using its signed full-scale
    divisor. Float WAV samples retain their actual values, including peaks
    exceeding 1.0; non-finite float samples are rejected.
    """

    sample_rate: int
    channels: int
    encoding: str  # 'pcm' or 'float'
    bits_per_sample: int
    frame_count: int
    samples: tuple[float, ...]  # interleaved, frame-major

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate

    @property
    def peak_abs(self) -> float:
        return max(map(abs, self.samples), default=0.0)

    def channel_samples(self, channel: int) -> tuple[float, ...]:
        if type(channel) is not int or not 0 <= channel < self.channels:
            raise IndexError("channel index out of range")
        return self.samples[channel::self.channels]


def _read_fmt(payload: bytes) -> tuple[int, int, str, int, int]:
    if len(payload) < 16:
        raise WavFormatError("fmt chunk is shorter than 16 bytes")
    tag, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", payload)
    if len(payload) == 17:
        raise WavFormatError("fmt chunk extension length is truncated")
    if len(payload) >= 18:
        cb_size = struct.unpack_from("<H", payload, 16)[0]
        if cb_size > len(payload) - 18:
            raise WavFormatError("fmt extension exceeds chunk bounds")
    else:
        cb_size = 0

    if tag == 0xFFFE:
        if len(payload) < 40 or cb_size < 22:
            raise WavFormatError("truncated WAVE_FORMAT_EXTENSIBLE fmt")
        valid_bits = struct.unpack_from("<H", payload, 18)[0]
        guid = payload[24:40]
        if valid_bits != bits:
            raise WavFormatError("packed valid-bit-depth differs from container; unsupported")
        if guid == _PCM_GUID:
            tag = 1
        elif guid == _FLOAT_GUID:
            tag = 3
        else:
            raise WavFormatError("unsupported extensible subformat GUID")

    if type(channels) is not int or channels not in (1, 2):
        raise WavFormatError("only mono and stereo WAV are supported")
    if rate <= 0 or rate > 384_000:
        raise WavFormatError("invalid or unsupported sample rate")
    if tag == 1 and bits in (16, 24, 32):
        encoding = "pcm"
    elif tag == 3 and bits == 32:
        encoding = "float"
    else:
        raise WavFormatError("unsupported WAV encoding or bit depth")

    expected_align = channels * (bits // 8)
    if align != expected_align or byte_rate != rate * align:
        raise WavFormatError("inconsistent byte rate or block alignment")
    return channels, rate, encoding, bits, align


def decode_wav(data: bytes, *, max_input_bytes: int = MAX_INPUT_BYTES) -> WavAudio:
    """Decode an entire RIFF/WAVE byte stream without writing to it.

    Raises WavFormatError on malformed, truncated, unsupported, or oversized
    input. Rate is preserved exactly; no hidden interpolation/resampling.
    """
    if not isinstance(data, bytes):
        raise TypeError("WAV input must be bytes")
    if type(max_input_bytes) is not int or max_input_bytes < 12:
        raise ValueError("max_input_bytes must be an integer >= 12")
    if len(data) > max_input_bytes:
        raise WavFormatError("WAV exceeds in-memory byte limit")
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavFormatError("expected little-endian RIFF/WAVE header")
    declared_length = struct.unpack_from("<I", data, 4)[0] + 8
    if declared_length != len(data):
        raise WavFormatError("RIFF declared size does not equal file size")

    pos = 12
    fmt: bytes | None = None
    audio_data: bytes | None = None
    while pos < len(data):
        if len(data) - pos < 8:
            raise WavFormatError("truncated RIFF chunk header")
        name = data[pos:pos + 4]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        start = pos + 8
        end = start + length
        if end > len(data):
            raise WavFormatError("RIFF chunk exceeds file bounds")
        if name == b"fmt ":
            if fmt is not None:
                raise WavFormatError("duplicate fmt chunk")
            fmt = data[start:end]
        elif name == b"data":
            if audio_data is not None:
                raise WavFormatError("duplicate data chunk")
            audio_data = data[start:end]
        pos = end
        if length & 1:
            if pos >= len(data):
                raise WavFormatError("missing RIFF padding byte")
            pos += 1

    if fmt is None or audio_data is None:
        raise WavFormatError("missing fmt or data chunk")
    channels, rate, encoding, bits, align = _read_fmt(fmt)
    if len(audio_data) == 0 or len(audio_data) % align:
        raise WavFormatError("data chunk empty or not frame-aligned")
    count = len(audio_data) // (bits // 8)
    if count > MAX_INTERLEAVED_SAMPLES:
        raise WavFormatError("WAV exceeds in-memory decoded-sample limit")

    if encoding == "float":
        samples = tuple(value for (value,) in struct.iter_unpack("<f", audio_data))
        if not all(math.isfinite(x) for x in samples):
            raise WavFormatError("non-finite IEEE float audio sample")
    elif bits == 16:
        samples = tuple(value / 32768.0 for (value,) in struct.iter_unpack("<h", audio_data))
    elif bits == 24:
        samples = tuple(int.from_bytes(audio_data[i:i + 3], "little", signed=True) / 8388608.0
                        for i in range(0, len(audio_data), 3))
    else:
        samples = tuple(value / 2147483648.0 for (value,) in struct.iter_unpack("<i", audio_data))

    return WavAudio(rate, channels, encoding, bits, len(audio_data) // align, samples)


def read_wav(path: str | Path, *, max_input_bytes: int = MAX_INPUT_BYTES) -> WavAudio:
    """Read a local file once, without writing or modifying its contents."""
    file = Path(path)
    if file.stat().st_size > max_input_bytes:
        raise WavFormatError("WAV exceeds in-memory byte limit")
    return decode_wav(file.read_bytes(), max_input_bytes=max_input_bytes)
