"""M2.4: deterministic offline source-cycle extraction and XT wave projection.

An XT Wave is 128 signed 8-bit samples with a *mandatory* reversed,
modular-negated second half. Projecting a natural audio cycle into this
geometry is lossy in general: ``projection_rms_error`` exposes that loss.
No claim of perceptual fidelity, no interpolation/firmware emulation, no
SysEx/slot allocation, no file I/O, no source mutation, no implicit downmix,
resampling, gain normalization, or phase-independent frequency estimation.

Two deterministic candidate-location policies:
  uniform:      evenly spaced timeline regions
  energy_peak:  highest local one-period RMS among nine anchors per region

Pitch is either explicit or read from a compatible M2.3 SignalAnalysis.
The latter is only suitable for confidently tonal analyzed regions;
polyphonic/noisy inputs should use an explicit user-selected pitch or a
future improved extractor. Distinct candidates are not necessarily distinct
waveforms (e.g. a stationary sine wave).
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from xtwavetable.analysis.signal import SignalAnalysis
from xtwavetable.audio.preprocess import ProcessedAudio
from xtwavetable.audio.wav_reader import WavAudio
from xtwavetable.model import Wave


class CycleExtractionError(ValueError):
    """Invalid parameters or a candidate that cannot be reliably extracted."""


@dataclass(frozen=True, slots=True)
class CycleCandidate:
    """One XT-compatible candidate and interpretable reconstruction diagnostics."""

    index: int
    anchor_frame: float
    phase_start_frame: float
    period_frames: float
    pitch_hz: float
    dc_reference: float
    source_cycle_rms: float
    source_cycle_peak: float
    projection_rms_error: float
    projected_peak: float
    gain_linear: float
    quantized_peak: int
    wave: Wave


@dataclass(frozen=True, slots=True)
class CycleExtraction:
    sample_rate: int
    channel: int
    source_frames: int
    pitch_source: str  # explicit or m2.3_analysis
    method: str
    normalize_peak: bool
    candidates: tuple[CycleCandidate, ...]


def _validated_frequency(frequency: float, rate: int) -> float:
    if (isinstance(frequency, bool) or not isinstance(frequency, (int, float))
            or not math.isfinite(frequency)):
        raise CycleExtractionError("pitch_hz must be a finite positive number")
    hz = float(frequency)
    if hz < 20.0 or rate / hz < 4.0 or rate / hz > 16384.0:
        raise CycleExtractionError("pitch cannot be represented: require 4..16384 input frames per cycle and f0 >= 20 Hz")
    return hz


def _one_period_rms(values: tuple[float, ...], center: float, period: float) -> float:
    half = max(2, round(period / 2.0))
    center_index = round(center)
    lo = max(0, center_index - half)
    hi = min(len(values), center_index + half)
    return math.sqrt(math.fsum(v * v for v in values[lo:hi]) / (hi - lo))


def _anchor_for_region(values: tuple[float, ...], region: int, count: int,
                       period: float, method: str) -> float:
    frames = len(values)
    start = frames * region / count
    stop = frames * (region + 1) / count
    if method == "uniform":
        return (start + stop) * 0.5
    # Bounded deterministic search: nine probes in each region, no scanning
    # proportional to whole-file length or expensive sample-by-sample ranking.
    possibilities = [start + (stop - start) * k / 8.0 for k in range(9)]
    return max(possibilities, key=lambda c: _one_period_rms(values, c, period))


def _pitch_at_anchor(analysis: SignalAnalysis, center: float, rate: int) -> float:
    feature = min(analysis.features,
                  key=lambda f: abs((f.start_frame + analysis.window_size * 0.5) - center))
    if feature.f0_hz is None or feature.periodicity < 0.8:
        raise CycleExtractionError("no confident tonal pitch near candidate; specify pitch_hz explicitly")
    return _validated_frequency(feature.f0_hz, rate)


def _local_dc(values: tuple[float, ...], center: float, period: float) -> float:
    mid = round(center)
    span = max(4, math.ceil(period))
    lo = max(0, mid - span)
    hi = min(len(values), mid + span)
    return math.fsum(values[lo:hi]) / (hi - lo)


def _phase_lock(values: tuple[float, ...], center: float,
                period: float, dc: float) -> float:
    """Closest rising zero crossing allowing interpolation of one full cycle."""
    frames = len(values)
    radius = max(2, math.ceil(period * 1.5))
    lo = max(0, math.floor(center) - radius)
    hi = min(frames - 2, math.ceil(center) + radius)
    best: tuple[float, float] | None = None
    for i in range(lo, hi + 1):
        first, second = values[i] - dc, values[i + 1] - dc
        if first <= 0.0 < second:
            fraction = -first / (second - first)
            phase = i + fraction
            if phase + period >= frames - 1:
                continue
            score = (abs(phase - center), phase)
            if best is None or score < best:
                best = score
    if best is None:
        raise CycleExtractionError("no rising zero crossing with a complete cycle in search range")
    return best[1]


def _sample_linear(values: tuple[float, ...], at: float) -> float:
    left = math.floor(at)
    t = at - left
    return values[left] * (1.0 - t) + values[left + 1] * t


def _extract_one(values: tuple[float, ...], region: int, count: int,
                 rate: int, pitch_hz: float, method: str,
                 normalize_peak: bool) -> CycleCandidate:
    period = rate / pitch_hz
    anchor = _anchor_for_region(values, region, count, period, method)
    dc = _local_dc(values, anchor, period)
    phase = _phase_lock(values, anchor, period, dc)
    full = tuple(_sample_linear(values, phase + (i + 0.5) * period / 128.0) - dc
                 for i in range(128))
    raw_peak = max(abs(v) for v in full)
    raw_rms = math.sqrt(math.fsum(v * v for v in full) / 128.0)
    if raw_rms <= 1e-8:
        raise CycleExtractionError("cycle is silent or lacks sufficient AC energy")

    # Orthogonal per-pair projection onto the XT reverse-negation constraint.
    half = tuple(0.5 * (full[i] - full[127 - i]) for i in range(64))
    projected_peak = max(abs(v) for v in half)
    error = math.sqrt(math.fsum(
        (full[i] - half[i]) ** 2 + (full[127 - i] + half[i]) ** 2
        for i in range(64)) / 128.0)
    if projected_peak <= 1e-8:
        raise CycleExtractionError("antisymmetric XT projection cancels this cycle")
    if not normalize_peak and projected_peak > 1.0 + 1e-12:
        raise CycleExtractionError("projected cycle exceeds 0 dBFS; explicitly enable normalization or lower input gain")
    gain = 1.0 / projected_peak if normalize_peak else 1.0
    quantized = tuple(max(-127, min(127, round(sample * gain * 127.0))) for sample in half)
    wave = Wave.from_half_cycle(quantized)
    return CycleCandidate(
        index=region, anchor_frame=anchor, phase_start_frame=phase,
        period_frames=period, pitch_hz=pitch_hz, dc_reference=dc,
        source_cycle_rms=raw_rms, source_cycle_peak=raw_peak,
        projection_rms_error=error, projected_peak=projected_peak,
        gain_linear=gain, quantized_peak=max(abs(s) for s in quantized),
        wave=wave)


def extract_wave_candidates(
    audio: WavAudio | ProcessedAudio,
    *,
    pitch_hz: float | None = None,
    analysis: SignalAnalysis | None = None,
    channel: int = 0,
    count: int = 8,
    method: str = "uniform",
    normalize_peak: bool = False,
) -> CycleExtraction:
    """Create 1..61 XT waves from one explicitly selected audio channel.

    With ``pitch_hz=None``, ``analysis`` is mandatory. Every candidate takes
    its F0 from the nearest confidently tonal M2.3 analysis window. Passing
    both is permitted: explicit pitch takes precedence, while incompatible
    analysis metadata is still rejected.

    Source must contain >=4 periods at the chosen pitch for each extraction;
    candidate count is not a uniqueness guarantee. Positions/slot IDs and
    SysEx are intentionally deferred to later M2 stages. The function never
    modifies input samples or writes files.
    """
    if not isinstance(audio, (WavAudio, ProcessedAudio)):
        raise TypeError("audio must be WavAudio or ProcessedAudio")
    rate, channels, frames = audio.sample_rate, audio.channels, audio.frame_count
    if (type(rate) is not int or not 1 <= rate <= 384000
            or type(channels) is not int or channels not in (1, 2)
            or type(frames) is not int or frames < 4
            or len(audio.samples) != channels * frames):
        raise CycleExtractionError("invalid audio shape")
    if type(channel) is not int or not 0 <= channel < channels:
        raise CycleExtractionError("explicit channel index is out of range")
    if type(count) is not int or not 1 <= count <= 61:
        raise CycleExtractionError("candidate count must be in 1..61")
    if method not in ("uniform", "energy_peak"):
        raise CycleExtractionError("method must be uniform or energy_peak")
    if type(normalize_peak) is not bool:
        raise CycleExtractionError("normalize_peak must be boolean")
    if not all(math.isfinite(v) for v in audio.samples):
        raise CycleExtractionError("audio contains non-finite samples")
    if analysis is not None:
        if not isinstance(analysis, SignalAnalysis):
            raise TypeError("analysis must be M2.3 SignalAnalysis")
        if (analysis.sample_rate != rate or analysis.source_frames != frames
                or analysis.channel != channel or not analysis.features):
            raise CycleExtractionError("analysis metadata does not match this audio/channel")
    if pitch_hz is None:
        if analysis is None or analysis.tonal_fraction < 0.5:
            raise CycleExtractionError("confident M2.3 tonal analysis or explicit pitch_hz required")
        pitch_source = "m2.3_analysis"
    else:
        pitch_hz = _validated_frequency(pitch_hz, rate)
        pitch_source = "explicit"
    values = audio.channel_samples(channel)
    results: list[CycleCandidate] = []
    for i in range(count):
        center = (i + 0.5) * frames / count
        hz = pitch_hz if pitch_hz is not None else _pitch_at_anchor(analysis, center, rate)
        period = rate / hz
        if frames < math.ceil(period * 4.0) + 2:
            raise CycleExtractionError("audio too short to hold four periods of selected pitch")
        try:
            candidate = _extract_one(values, i, count, rate, hz, method, normalize_peak)
        except CycleExtractionError as error:
            raise CycleExtractionError(f"candidate {i}: {error}") from error
        results.append(candidate)
    return CycleExtraction(rate, channel, frames, pitch_source, method,
                           normalize_peak, tuple(results))
