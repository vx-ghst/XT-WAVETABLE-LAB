"""Deterministic, non-destructive preprocessing of decoded WAV sample frames.

M2.2 only: explicit frame selection, stereo channel selection/downmix, optional
per-channel DC removal, and optional peak normalization. No resampling,
limiting, filtering, filesystem writes, or XT SysEx generation.

All sample arrays are interleaved, frame-major, in float full-scale units.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import math

from .wav_reader import WavAudio


class AudioProcessingError(ValueError):
    """Invalid signal, range, or M2.2 processing option."""


@dataclass(frozen=True, slots=True)
class ProcessedAudio:
    """Immutable float-domain output, carrying reproducible processing metadata."""

    sample_rate: int
    channels: int
    samples: tuple[float, ...]
    source_start_frame: int
    source_end_frame: int  # exclusive
    channel_mode: str
    dc_offsets: tuple[float, ...]  # removed per output channel; zeros if disabled
    gain_linear: float  # applied equally to all output channels; 1 if disabled/silent
    peak_before_gain: float  # measured after optional DC removal
    peak_after_gain: float

    @property
    def frame_count(self) -> int:
        return len(self.samples) // self.channels

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate

    def channel_samples(self, channel: int) -> tuple[float, ...]:
        if type(channel) is not int or not 0 <= channel < self.channels:
            raise IndexError("channel index out of range")
        return self.samples[channel::self.channels]


def _decimal_seconds(value: int | float | Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise AudioProcessingError("times must be finite numeric seconds")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise AudioProcessingError("invalid time") from error
    if not result.is_finite() or result < 0:
        raise AudioProcessingError("times must be finite and nonnegative")
    return result


def frame_bounds_from_seconds(
    sample_rate: int,
    total_frames: int,
    *,
    start_seconds: int | float | Decimal = 0,
    end_seconds: int | float | Decimal | None = None,
) -> tuple[int, int]:
    """Map a nonempty half-open time interval to covering sample-frame bounds.

    Start uses floor and stop uses ceil so that partial boundary frames are
    included. For exact digital edits, pass frame indices to preprocess_audio.
    The end frame is EXCLUSIVE. Out-of-range times are rejected, not clamped.
    """
    if type(sample_rate) is not int or sample_rate <= 0:
        raise AudioProcessingError("sample_rate must be a positive integer")
    if type(total_frames) is not int or total_frames <= 0:
        raise AudioProcessingError("total_frames must be a positive integer")
    start = int((_decimal_seconds(start_seconds) * sample_rate).to_integral_value(rounding=ROUND_FLOOR))
    if end_seconds is None:
        end = total_frames
    else:
        end = int((_decimal_seconds(end_seconds) * sample_rate).to_integral_value(rounding=ROUND_CEILING))
    if not 0 <= start < end <= total_frames:
        raise AudioProcessingError("time selection is empty, inverted, or outside the input")
    return start, end


def preprocess_audio(
    audio: WavAudio,
    *,
    start_frame: int = 0,
    end_frame: int | None = None,
    channel_mode: str = "preserve",
    remove_dc: bool = False,
    normalize_peak_dbfs: float | None = None,
) -> ProcessedAudio:
    """Process a decoded signal with opt-in operations and zero source writes.

    Channel modes: preserve (default), left, right, average. For mono, right
    is invalid; preserve/left/average produce identical mono samples. The
    average mode uses 0.5*(L+R), which may cancel antiphase content.

    Optional DC removal subtracts the arithmetic mean independently from each
    output channel AFTER cropping/downmixing. If peak normalization is enabled,
    a single shared linear gain is used across all output channels; silence
    remains silent and is never divided by zero. Float WAV may exceed 0 dBFS
    before processing, but peak-normalization targets are limited to <= 0 dBFS.
    """
    if not isinstance(audio, WavAudio):
        raise TypeError("audio must be decoded WavAudio")
    if (type(audio.sample_rate) is not int or audio.sample_rate <= 0
            or type(audio.channels) is not int or audio.channels not in (1, 2)
            or type(audio.frame_count) is not int or audio.frame_count < 1
            or len(audio.samples) != audio.frame_count * audio.channels):
        raise AudioProcessingError("inconsistent audio dimensions")
    if not all(math.isfinite(x) for x in audio.samples):
        raise AudioProcessingError("non-finite input sample")

    stop = audio.frame_count if end_frame is None else end_frame
    if (type(start_frame) is not int or type(stop) is not int
            or not 0 <= start_frame < stop <= audio.frame_count):
        raise AudioProcessingError("invalid half-open frame range")
    if channel_mode not in ("preserve", "left", "right", "average"):
        raise AudioProcessingError("unsupported channel mode")
    if audio.channels == 1 and channel_mode == "right":
        raise AudioProcessingError("right channel requested for mono input")
    if type(remove_dc) is not bool:
        raise AudioProcessingError("remove_dc must be boolean")
    if normalize_peak_dbfs is not None:
        if (isinstance(normalize_peak_dbfs, bool)
                or not isinstance(normalize_peak_dbfs, (int, float))
                or not math.isfinite(normalize_peak_dbfs)
                or not -120.0 <= normalize_peak_dbfs <= 0.0):
            raise AudioProcessingError("normalization target must be between -120 and 0 dBFS")

    channels = audio.channels if channel_mode == "preserve" else 1
    section = audio.samples[start_frame * audio.channels:stop * audio.channels]
    if audio.channels == 2 and channel_mode != "preserve":
        if channel_mode == "left":
            section = section[::2]
        elif channel_mode == "right":
            section = section[1::2]
        else:
            section = tuple(0.5 * section[i] + 0.5 * section[i + 1]
                            for i in range(0, len(section), 2))

    dc_offsets = tuple(0.0 for _ in range(channels))
    if remove_dc:
        frames = stop - start_frame
        dc_offsets = tuple(
            math.fsum(section[ch::channels]) / frames
            for ch in range(channels)
        )
        section = tuple(value - dc_offsets[i % channels]
                        for i, value in enumerate(section))

    peak_before = max(map(abs, section), default=0.0)
    gain = 1.0
    if normalize_peak_dbfs is not None and peak_before > 0.0:
        target = 10.0 ** (float(normalize_peak_dbfs) / 20.0)
        gain = target / peak_before
        section = tuple(value * gain for value in section)
    result_samples = tuple(section)
    if not all(math.isfinite(v) for v in result_samples):
        raise AudioProcessingError("processing produced non-finite samples")
    return ProcessedAudio(
        sample_rate=audio.sample_rate,
        channels=channels,
        samples=result_samples,
        source_start_frame=start_frame,
        source_end_frame=stop,
        channel_mode=channel_mode,
        dc_offsets=dc_offsets,
        gain_linear=gain,
        peak_before_gain=peak_before,
        peak_after_gain=max(map(abs, result_samples), default=0.0),
    )
