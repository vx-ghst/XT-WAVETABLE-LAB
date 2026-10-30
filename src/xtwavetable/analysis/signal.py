"""M2.3 deterministic, bounded signal analysis without third-party DSP dependencies.

Acoustic descriptors are HEURISTICS. They are not a perceptual-quality score,
not proof of monophony, and not a claim of hardware/emulator equivalence.

No implicit channel mixing, resampling, audio processing, file I/O or XT export.
The channel must be explicitly selected (0 by default). Analysis windows may
be sparsely distributed across long inputs: spectral flux describes differences
between consecutive *analyzed* windows, not guaranteed adjacent STFT hops.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics

from xtwavetable.audio.preprocess import ProcessedAudio
from xtwavetable.audio.wav_reader import WavAudio


class SignalAnalysisError(ValueError):
    """Invalid analysis parameters or inconsistent input audio."""


@dataclass(frozen=True, slots=True)
class FrameFeatures:
    start_frame: int
    center_seconds: float
    rms: float
    peak_abs: float
    f0_hz: float | None
    periodicity: float
    spectral_centroid_hz: float
    spectral_flux: float  # positive spectral change vs preceding analyzed window


@dataclass(frozen=True, slots=True)
class SignalAnalysis:
    sample_rate: int
    channel: int
    source_frames: int
    window_size: int
    hop_size: int
    sparse_windows: bool
    min_f0_hz: float
    max_f0_hz: float
    features: tuple[FrameFeatures, ...]
    median_f0_hz: float | None
    tonal_fraction: float
    median_spectral_centroid_hz: float
    mean_spectral_flux: float
    max_crest_factor: float
    heuristic_label: str  # silence, dc_only, tonal, transient_like, noise_or_complex, or mixed


def _power_of_two_at_least(x: int) -> int:
    return 1 << (x - 1).bit_length()


def _fft(values: list[complex], *, inverse: bool = False) -> list[complex]:
    """Unnormalized radix-2 DFT; inverse divides by N (pure deterministic Python)."""
    n = len(values)
    if not n or n & (n - 1):
        raise SignalAnalysisError("FFT size must be a positive power of two")
    a = list(values)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        angle = (2.0 if inverse else -2.0) * math.pi / length
        rot = complex(math.cos(angle), math.sin(angle))
        half = length // 2
        for start in range(0, n, length):
            w = 1.0 + 0j
            for k in range(half):
                u = a[start + k]
                v = a[start + k + half] * w
                a[start + k] = u + v
                a[start + k + half] = u - v
                w *= rot
        length <<= 1
    if inverse:
        a = [v / n for v in a]
    return a


def _window_features(samples: tuple[float, ...], sample_rate: int,
                     f0_min: float, f0_max: float) -> tuple[float, float, float | None, float, float, tuple[float, ...]]:
    size = len(samples)
    peak = max(abs(v) for v in samples)
    rms = math.sqrt(math.fsum(v * v for v in samples) / size)
    average = math.fsum(samples) / size
    centered = [v - average for v in samples]
    energy = math.fsum(v * v for v in centered)
    if energy < 1e-16 or rms < 1e-8:
        return rms, peak, None, 0.0, 0.0, (0.0,) * (size // 2 + 1)

    # Hann-window FFT for spectral descriptors; DC is excluded from centroid.
    taper = [centered[i] * 0.5 * (1.0 - math.cos(2.0 * math.pi * i / (size - 1)))
             for i in range(size)]
    bins = _fft([complex(value) for value in taper])
    mags = tuple(abs(bins[k]) for k in range(size // 2 + 1))
    total_magnitude = math.fsum(mags[1:])
    centroid = (math.fsum(k * mags[k] for k in range(1, len(mags)))
                / total_magnitude * (sample_rate / size) if total_magnitude > 1e-12 else 0.0)

    # Exact linear autocorrelation through zero-padded FFT (no circular wrap).
    nfft = size * 2
    spectrum = _fft([complex(value) for value in centered] + [0j] * size)
    power = [complex(z.real * z.real + z.imag * z.imag) for z in spectrum]
    autocorrelation = _fft(power, inverse=True)
    energies = [0.0]
    for value in centered:
        energies.append(energies[-1] + value * value)
    min_lag = max(2, math.floor(sample_rate / f0_max))
    max_lag = min(size // 2, math.ceil(sample_rate / f0_min))
    scores: dict[int, float] = {}
    if min_lag <= max_lag:
        for lag in range(min_lag, max_lag + 1):
            norm = math.sqrt(max(0.0, energies[size - lag]) *
                             max(0.0, energies[size] - energies[lag]))
            if norm > 1e-12:
                scores[lag] = max(-1.0, min(1.0, autocorrelation[lag].real / norm))
    peaks = [(lag, score) for lag, score in scores.items()
             if score >= 0.80
             and score >= scores.get(lag - 1, -1.0)
             and score >= scores.get(lag + 1, -1.0)]
    if not peaks:
        return rms, peak, None, max((max(0.0, s) for s in scores.values()), default=0.0), centroid, mags
    best_score = max(v for _, v in peaks)
    # Favor shortest convincing period: suppress integer-multiple/subharmonic ambiguity.
    lag = min(l for l, s in peaks if s >= max(0.80, best_score - 0.03))
    periodicity = scores[lag]
    left, middle, right = (scores.get(lag - 1, periodicity), periodicity,
                            scores.get(lag + 1, periodicity))
    denominator = left - 2.0 * middle + right
    offset = (0.5 * (left - right) / denominator if denominator < -1e-10 else 0.0)
    offset = max(-0.5, min(0.5, offset))
    frequency = sample_rate / (lag + offset)
    if not f0_min <= frequency <= f0_max:
        return rms, peak, None, periodicity, centroid, mags
    return rms, peak, frequency, periodicity, centroid, mags


def analyze_signal(
    audio: WavAudio | ProcessedAudio,
    *,
    channel: int = 0,
    window_size: int | None = None,
    hop_size: int | None = None,
    max_windows: int = 12,
    min_f0_hz: float = 55.0,
    max_f0_hz: float = 2000.0,
) -> SignalAnalysis:
    """Analyze selected channel in non-mutating, frequency-native windows.

    Adaptive default FFT window covers >=3 periods of min_f0_hz, rounded up
    to a power of two, with limits 1024..16384 samples. Very short inputs
    (<1024 samples) are rejected. Sparse windows are selected deterministically
    across the entire source, with an explicit flag in the report.
    """
    if not isinstance(audio, (WavAudio, ProcessedAudio)):
        raise TypeError("audio must be WavAudio or ProcessedAudio")
    rate = audio.sample_rate
    channels = audio.channels
    frames = audio.frame_count
    if (type(rate) is not int or not 1 <= rate <= 384_000
            or type(channels) is not int or channels not in (1, 2)
            or type(frames) is not int or frames < 1024
            or len(audio.samples) != frames * channels):
        raise SignalAnalysisError("invalid audio shape or less than 1024 frames")
    if type(channel) is not int or not 0 <= channel < channels:
        raise SignalAnalysisError("selected channel is unavailable")
    if not all(math.isfinite(v) for v in audio.samples):
        raise SignalAnalysisError("input contains non-finite samples")
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
           for x in (min_f0_hz, max_f0_hz)):
        raise SignalAnalysisError("pitch boundaries must be finite numbers")
    if not 20 <= min_f0_hz < max_f0_hz < rate / 2:
        raise SignalAnalysisError("invalid pitch search range")
    if type(max_windows) is not int or not 1 <= max_windows <= 64:
        raise SignalAnalysisError("max_windows must be in 1..64")
    if window_size is None:
        window_size = _power_of_two_at_least(max(1024, math.ceil(3.0 * rate / min_f0_hz)))
    if type(window_size) is not int or window_size < 1024 or window_size > 16384 or window_size & (window_size - 1):
        raise SignalAnalysisError("window_size must be a power of two in 1024..16384")
    if window_size > frames:
        raise SignalAnalysisError("audio is shorter than the requested analysis window")
    if math.ceil(rate / min_f0_hz) > window_size // 2:
        raise SignalAnalysisError("analysis window cannot resolve requested minimum f0")
    if hop_size is None:
        hop_size = window_size // 2
    if type(hop_size) is not int or not 1 <= hop_size <= window_size:
        raise SignalAnalysisError("hop_size must be an integer in 1..window_size")

    last = frames - window_size
    regular_count = last // hop_size + 1
    has_tail = last % hop_size != 0
    count = regular_count + int(has_tail)
    sparse = count > max_windows

    def position(index: int) -> int:
        return last if has_tail and index == count - 1 else index * hop_size

    if sparse:
        # No range(count) allocation: even hop_size=1 is bounded in memory.
        if max_windows == 1:
            starts = [0]
        else:
            starts = [position((i * (count - 1)) // (max_windows - 1))
                      for i in range(max_windows)]
    else:
        starts = [position(i) for i in range(count)]

    reports: list[FrameFeatures] = []
    last_mags: tuple[float, ...] | None = None
    for start in starts:
        window = tuple(audio.samples[(start + i) * channels + channel]
                       for i in range(window_size))
        rms, peak, f0, periodicity, centroid, mags = _window_features(
            window, rate, float(min_f0_hz), float(max_f0_hz))
        # First flux is zero by convention, since no previous frame exists.
        flux = 0.0
        if last_mags is not None:
            denominator = math.fsum(mags)
            if denominator > 1e-12:
                flux = math.fsum(max(0.0, x - prev) for x, prev in zip(mags, last_mags)) / denominator
        reports.append(FrameFeatures(start, (start + window_size / 2) / rate,
                                     rms, peak, f0, periodicity, centroid, flux))
        last_mags = mags
    audible = [feature for feature in reports if feature.rms >= 1e-8]
    pitched = [feature.f0_hz for feature in audible if feature.f0_hz is not None]
    tonal_fraction = len(pitched) / len(audible) if audible else 0.0
    max_crest_factor = max((f.peak_abs / f.rms for f in audible), default=0.0)
    largest_flux = max((f.spectral_flux for f in reports), default=0.0)
    if not audible:
        label = "silence"
    elif all(f.spectral_centroid_hz == 0.0 and f.f0_hz is None for f in audible):
        label = "dc_only"
    elif (tonal_fraction < 0.5 and max_crest_factor > 8.0
          and (len(audible) * 2 < len(reports) or largest_flux > 0.6)):
        label = "transient_like"
    elif tonal_fraction >= 0.75:
        label = "tonal"
    elif tonal_fraction <= 0.25:
        label = "noise_or_complex"
    else:
        label = "mixed"
    return SignalAnalysis(
        sample_rate=rate, channel=channel, source_frames=frames,
        window_size=window_size, hop_size=hop_size, sparse_windows=sparse,
        min_f0_hz=float(min_f0_hz), max_f0_hz=float(max_f0_hz),
        features=tuple(reports),
        median_f0_hz=statistics.median(pitched) if pitched else None,
        tonal_fraction=tonal_fraction,
        median_spectral_centroid_hz=statistics.median(f.spectral_centroid_hz for f in reports),
        mean_spectral_flux=statistics.fmean(f.spectral_flux for f in reports),
        max_crest_factor=max_crest_factor,
        heuristic_label=label,
    )
