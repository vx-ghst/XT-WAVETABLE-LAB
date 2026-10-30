"""M2.7 deterministic, OFFLINE end-to-end WAV -> XT SysEx orchestration.

No automatic RAM allocation; replacing any XT user wave/table requires explicit
IDs and matching authorizations. No MIDI I/O, hardware writes, ROM or firmware.
This layer never writes files and never modifies its byte inputs. Returned
manifests contain private source hashes and are NOT intended for public Git.

Quality assessments are heuristic and M3/M4 interpolation rendering is NOT
implemented. Other dump commands (Single/Multi/Global) remain unvalidated.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from xtwavetable.analysis.signal import SignalAnalysis, analyze_signal
from xtwavetable.audio.preprocess import ProcessedAudio, preprocess_audio
from xtwavetable.audio.wav_reader import WavAudio, decode_wav
from xtwavetable.converter.cycles import CycleExtraction, extract_wave_candidates
from xtwavetable.export.bundle import (DumpSnapshot, ExportBundle, build_export_bundle,
                                         inspect_snapshot)
from xtwavetable.optimizer.selection import WaveSelection, select_wave_plan


@dataclass(frozen=True, slots=True)
class ConversionOptions:
    """Explicit, reproducible audio/candidate settings; no implicit processing."""

    start_frame: int = 0
    end_frame: int | None = None
    channel_mode: str = "preserve"
    remove_dc: bool = False
    normalize_peak_dbfs: float | None = None
    channel: int = 0
    pitch_hz: float | None = None  # None => M2.3 F0 estimation, which may fail
    analysis_max_windows: int = 12
    candidate_count: int = 8
    extraction_method: str = "uniform"
    normalize_cycle_peak: bool = False
    requested_waves: int = 8
    selection_strategy: str = "uniform"
    shortfall: str = "reject"
    max_projection_rms_error: float | None = None


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Complete immutable in-memory conversion, with separate provenance."""

    source: WavAudio
    processed: ProcessedAudio
    analysis: SignalAnalysis | None
    extraction: CycleExtraction
    selection: WaveSelection
    snapshot: DumpSnapshot
    bundle: ExportBundle
    manifest_json: bytes

    @property
    def sysex(self) -> bytes:
        return self.bundle.sysex


def convert_wav_to_offline_bundle(
    wav_bytes: bytes,
    snapshot_bytes: bytes,
    *,
    options: ConversionOptions,
    wave_ids: tuple[int, ...],
    table_id: int,
    authorized_replacement_wave_ids: tuple[int, ...] = (),
    authorize_table_replacement: bool = False,
    acknowledge_cross_table_references: bool = False,
    device_id: int = 0x7F,
) -> ConversionResult:
    """Integrate M2.1..M2.6 without touching any files or actual hardware.

    A complete dump snapshot is *required*. It proves what Wave/Table content
    existed in that private backup, but cannot prove other preset references
    or hardware safety. Every destination must be explicitly specified and
    explicitly authorized as REPLACEMENT, even if unreferenced by tables.

    The output is not an authorization to upload the generated SysEx.
    """
    if not isinstance(options, ConversionOptions):
        raise TypeError("options must be ConversionOptions")
    if not isinstance(wav_bytes, bytes) or not isinstance(snapshot_bytes, bytes):
        raise TypeError("WAV and snapshot must be immutable bytes")

    # Failure-closed snapshot parsing; no assumptions of 'free' RAM slots.
    snapshot = inspect_snapshot(snapshot_bytes)
    source = decode_wav(wav_bytes)
    processed = preprocess_audio(
        source,
        start_frame=options.start_frame,
        end_frame=options.end_frame,
        channel_mode=options.channel_mode,
        remove_dc=options.remove_dc,
        normalize_peak_dbfs=options.normalize_peak_dbfs,
    )
    # Explicit pitch bypasses heuristic F0; never silently replace user pitch.
    analysis = (analyze_signal(processed, channel=options.channel,
                               max_windows=options.analysis_max_windows)
                if options.pitch_hz is None else None)
    extraction = extract_wave_candidates(
        processed, channel=options.channel,
        pitch_hz=options.pitch_hz, analysis=analysis,
        count=options.candidate_count,
        method=options.extraction_method,
        normalize_peak=options.normalize_cycle_peak,
    )
    selection = select_wave_plan(
        extraction, requested_waves=options.requested_waves,
        strategy=options.selection_strategy,
        shortfall=options.shortfall,
        max_projection_rms_error=options.max_projection_rms_error,
    )
    bundle = build_export_bundle(
        selection, snapshot=snapshot,
        wave_ids=wave_ids, table_id=table_id,
        authorized_replacement_wave_ids=authorized_replacement_wave_ids,
        authorize_table_replacement=authorize_table_replacement,
        acknowledge_cross_table_references=acknowledge_cross_table_references,
        device_id=device_id,
    )

    manifest = {
        "schema": "xtwavetable.m2.7.pipeline.v1",
        "source_wav_sha256": sha256(wav_bytes).hexdigest(),
        "source_wav": {
            "sample_rate": source.sample_rate,
            "channels": source.channels,
            "encoding": source.encoding,
            "bits_per_sample": source.bits_per_sample,
            "frames": source.frame_count,
        },
        "processing": {
            "start_frame": processed.source_start_frame,
            "end_frame_exclusive": processed.source_end_frame,
            "output_channels": processed.channels,
            "output_frames": processed.frame_count,
            "channel_mode": processed.channel_mode,
            "remove_dc": options.remove_dc,
            "dc_offsets": list(processed.dc_offsets),
            "normalize_peak_dbfs": options.normalize_peak_dbfs,
            "gain_linear": processed.gain_linear,
            "peak_before_gain": processed.peak_before_gain,
            "peak_after_gain": processed.peak_after_gain,
        },
        "analysis": (None if analysis is None else {
            "heuristic_label": analysis.heuristic_label,
            "median_f0_hz": analysis.median_f0_hz,
            "tonal_fraction": analysis.tonal_fraction,
            "sparse_windows": analysis.sparse_windows,
            "analyzed_windows": len(analysis.features),
        }),
        "extraction": {
            "pitch_source": extraction.pitch_source,
            "explicit_pitch_hz": options.pitch_hz,
            "channel": extraction.channel,
            "candidate_count": len(extraction.candidates),
            "method": extraction.method,
            "normalize_cycle_peak": extraction.normalize_peak,
            "projection_rms_errors": [c.projection_rms_error for c in extraction.candidates],
        },
        "selection": {
            "requested_waves": selection.requested_waves,
            "actual_distinct_waves": selection.actual_distinct_waves,
            "selection_strategy": selection.strategy,
            "shortfall_policy": selection.shortfall,
            "has_shortfall": selection.has_shortfall,
            "max_projection_rms_error": options.max_projection_rms_error,
            "selected_candidate_indices": [c.index for c in selection.selected],
            "editable_wave_indices": list(selection.editable_wave_indices),
        },
        "offline_export": json.loads(bundle.manifest_json),
        "limitations": [
            "No interpolated XT wavetable audio or perceptual validation (M3/M4 pending).",
            "No MIDI transport, firmware or physical-device writes are implemented.",
            "Other snapshot commands and any preset dependencies are not certified.",
            "The WAV source, snapshot and this manifest are private; do not add to public Git.",
        ],
    }
    canonical = (json.dumps(manifest, sort_keys=True, ensure_ascii=True,
                            separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    return ConversionResult(source, processed, analysis, extraction,
                            selection, snapshot, bundle, canonical)
