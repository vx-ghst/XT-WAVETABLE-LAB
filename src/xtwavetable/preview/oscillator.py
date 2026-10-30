"""M3.1: explicit APPROXIMATE XT wavetable oscillator, not Waldorf DSP.

Reads canonical 128-sample Wave data and the 61 editable Table references.
A continuous table position crossfades *in the time domain* between the
adjacent waves at a shared phase. Separately, phase interpolation can be
nearest-sample or linear. The approximation is NOT the verified Waldorf
hardware interpolation algorithm and NOT an Xenia/Gearmulator render.

No band-limiting, filter, envelopes, waveshaping, effects, stereo or hardware
MIDI. Aliasing, including ultrasonic harmonics folding into the spectrum,
is expected. Numerical diagnostics are heuristic, not perceptual scores.
All outputs are in-memory; there is no path, file or MIDI write here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import struct
from typing import Mapping

from xtwavetable.codec_xt.sysex import (WAVE_DUMP_LENGTH, TABLE_DUMP_LENGTH,
                                       decode_wave_dump, decode_table_dump)
from xtwavetable.export.bundle import ExportBundle
from xtwavetable.model.table import Table, USER_POSITIONS
from xtwavetable.model.wave import Wave
from xtwavetable.preview.profiles import resolve_profile


class PreviewError(ValueError):
    """Invalid source/reference or unsupported approximate rendering parameter."""


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Immutable mono, full-scale [-1,1] samples plus reproducible diagnostics."""
    samples: tuple[float, ...]
    sample_rate: int
    frequency_hz: float
    start_position: float
    end_position: float
    phase_interpolation: str
    table_interpolation: str
    peak: float
    rms: float
    max_adjacent_wave_rms_difference: float
    samples_sha256: str

    @property
    def frames(self) -> int:
        return len(self.samples)


def _real(value: object, label: str) -> float:
    if type(value) not in (float, int) or not math.isfinite(value):
        raise PreviewError(f"{label} must be finite and numeric")
    return float(value)


def _wave_at(wave: Wave, phase: float, mode: str) -> float:
    # A cyclic 128-sample oscillator with exact wrapping, unlike the table axis.
    coordinate = (phase % 1.0) * 128
    first = int(coordinate) % 128
    if mode == "nearest":
        return wave.samples[int(math.floor(coordinate + 0.5)) % 128] / 128.0
    fraction = coordinate - int(coordinate)
    return ((1.0 - fraction) * wave.samples[first] +
            fraction * wave.samples[(first + 1) % 128]) / 128.0


def render_preview(table: Table, waves: Mapping[int, Wave], *,
                   sample_rate: int = 48000, frequency_hz: float = 220.0,
                   duration_seconds: float = 1.0,
                   start_position: float = 0.0, end_position: float | None = None,
                   table_interpolation: str | None = None,
                   phase_interpolation: str | None = None,
                   render_profile: str | None = None,
                   amplitude: float = 0.8, initial_phase: float = 0.0) -> PreviewResult:
    """Render bounded mono float preview, with 61 editable positions only.

    Position sweep includes both endpoints; `end_position=None` means a
    stationary oscillator. All editable IDs must be present in `waves`.
    No ROM waves are inferred; callers must explicitly provide their data.
    """
    if not isinstance(table, Table):
        raise PreviewError("table must be a Table")
    if not isinstance(waves, Mapping):
        raise PreviewError("waves must be a mapping of IDs to Wave objects")
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
        raise PreviewError("sample_rate must be an integer in 8000..192000")
    frequency_hz = _real(frequency_hz, "frequency_hz")
    if not 0 < frequency_hz < sample_rate / 2:
        raise PreviewError("frequency_hz must be above zero and below Nyquist")
    duration_seconds = _real(duration_seconds, "duration_seconds")
    if not 0 < duration_seconds <= 10.0:
        raise PreviewError("duration_seconds must be in (0,10]")
    count = round(duration_seconds * sample_rate)
    if not 1 <= count <= 500_000:
        raise PreviewError("preview must contain 1..500000 frames")
    start_position = _real(start_position, "start_position")
    end_position = start_position if end_position is None else _real(end_position, "end_position")
    if not (0 <= start_position <= 60 and 0 <= end_position <= 60):
        raise PreviewError("table positions must be in the editable range 0..60")
    table_interpolation, phase_interpolation, _ = resolve_profile(
        render_profile, table_interpolation=table_interpolation,
        phase_interpolation=phase_interpolation)
    if table_interpolation not in ("linear", "nearest"):
        raise PreviewError("table_interpolation must be 'linear' or 'nearest'")
    if phase_interpolation not in ("linear", "nearest"):
        raise PreviewError("phase_interpolation must be 'linear' or 'nearest'")
    amplitude = _real(amplitude, "amplitude")
    if not 0 < amplitude <= 1:
        raise PreviewError("amplitude must be in (0,1]")
    initial_phase = _real(initial_phase, "initial_phase")
    if not 0 <= initial_phase < 1:
        raise PreviewError("initial_phase must be in [0,1)")
    required = table.user_positions
    for wave_id in required:
        if type(wave_id) is not int or wave_id not in waves or not isinstance(waves[wave_id], Wave):
            raise PreviewError("all editable table references require explicit Wave data")
    wave_list = tuple(waves[n] for n in required)
    difference = 0.0
    for first, second in zip(wave_list, wave_list[1:]):
        difference = max(difference, math.sqrt(math.fsum(
            (x-y)**2 for x,y in zip(first.samples,second.samples)
        ) / 128) / 128.0)
    step = frequency_hz / sample_rate
    samples: list[float] = []
    for index in range(count):
        t = index / (count-1) if count > 1 else 0.0
        position = start_position + (end_position-start_position) * t
        if table_interpolation == "nearest":
            sample = _wave_at(wave_list[min(60, math.floor(position + 0.5))],
                              initial_phase + index*step, phase_interpolation)
        else:
            lower = min(60, int(position))
            upper = min(60, lower+1)
            weight = position - lower
            phase = initial_phase + index*step
            if lower == upper or weight == 0.0 or wave_list[lower] == wave_list[upper]:
                # Do not manufacture floating-point roundoff when no morph occurs.
                sample = _wave_at(wave_list[lower], phase, phase_interpolation)
            else:
                sample = ((1-weight) * _wave_at(wave_list[lower], phase, phase_interpolation)
                          + weight * _wave_at(wave_list[upper], phase, phase_interpolation))
        samples.append(amplitude*sample)
    pcm = struct.pack("<" + "d"*len(samples), *samples)
    return PreviewResult(
        tuple(samples), sample_rate, frequency_hz, start_position, end_position,
        phase_interpolation, table_interpolation,
        max(abs(x) for x in samples),
        math.sqrt(math.fsum(x*x for x in samples)/len(samples)),
        difference, sha256(pcm).hexdigest())


def render_export_bundle_preview(bundle: ExportBundle, **render_kwargs: object) -> PreviewResult:
    """Verify and preview an existing M2.6 offline candidate without writes.

    Only WaveDump/TableDump bytes already inside the bundle are used. Any ROM
    references (unsupported by the bundle) fail closed in render_preview.
    """
    if not isinstance(bundle, ExportBundle):
        raise PreviewError("bundle must be a validated ExportBundle")
    payload = bundle.sysex
    count = len(bundle.wave_ids)
    if len(payload) != count*WAVE_DUMP_LENGTH + TABLE_DUMP_LENGTH:
        raise PreviewError("SysEx packet geometry does not match bundle IDs")
    try:
        provenance = json.loads(bundle.manifest_json)
        if provenance.get("output_sysex_sha256") != sha256(payload).hexdigest():
            raise PreviewError("manifest/output SHA-256 mismatch")
        if tuple(provenance.get("wave_ids", ())) != bundle.wave_ids or provenance.get("table_id") != bundle.table_id:
            raise PreviewError("manifest destination IDs mismatch")
        actual: dict[int, Wave] = {}
        for i, expected in enumerate(bundle.wave_ids):
            part = payload[i*WAVE_DUMP_LENGTH:(i+1)*WAVE_DUMP_LENGTH]
            decoded = decode_wave_dump(part)
            if decoded.wave_id != expected or decoded.wave_id in actual:
                raise PreviewError("wave packet IDs mismatch")
            actual[expected] = decoded.wave
        result_table = decode_table_dump(payload[count*WAVE_DUMP_LENGTH:])
        if result_table.table_id != bundle.table_id or result_table.table != bundle.table:
            raise PreviewError("table packet mismatch")
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        raise PreviewError(f"invalid offline bundle: {exc}") from exc
    return render_preview(bundle.table, actual, **render_kwargs)


def encode_preview_pcm16_wav(preview: PreviewResult) -> bytes:
    """Produce a standard PCM16 mono RIFF/WAV in memory without file writes.

    Quantization is explicit and deterministic. Avoids a data-dependent
    peak normalizer that could conceal issues with the preview oscillator.
    """
    if not isinstance(preview, PreviewResult):
        raise PreviewError("preview must be a PreviewResult")
    frames = bytearray()
    for value in preview.samples:
        if not math.isfinite(value) or not -1.0 <= value <= 1.0:
            raise PreviewError("preview contains nonfinite/out-of-range samples")
        signed = max(-32768, min(32767, round(value * 32768)))
        frames.extend(struct.pack("<h", signed))
    payload = bytes(frames)
    header = (b"RIFF" + struct.pack("<I", 36+len(payload)) + b"WAVE" +
              b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1,
                                    preview.sample_rate, preview.sample_rate*2, 2, 16)
              + b"data" + struct.pack("<I", len(payload)))
    return header + payload
