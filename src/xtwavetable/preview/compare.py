"""M3.2 offline A/B preview and transition QA (APPROXIMATION ONLY).

Uses the *same* M3.1 rendering settings for candidates A and B. Reports
mathematical characteristics of the approximate waveform, not listening
quality, Waldorf interpolation semantics, or firmware/hardware equivalence.
No source files, ROMs, firmware or hardware MIDI are read/written here.

Files are written only by explicit opt-in into a NEW runs/<job>/ directory.
The report contains hashes and numerical diagnostics, never private paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import struct
from typing import Any

from xtwavetable.codec_xt.sysex import WAVE_DUMP_LENGTH, decode_wave_dump
from xtwavetable.export.bundle import ExportBundle
from xtwavetable.model.wave import Wave
from xtwavetable.preview.profiles import resolve_profile, validate_report_profile
from xtwavetable.preview.oscillator import (
    PreviewError, PreviewResult, render_export_bundle_preview,
    encode_preview_pcm16_wav,
)


_SCHEMA = "xtwavetable.m3.2.approx_ab.v1"
_FILES = ("preview_A.wav", "preview_B.wav", "preview_AB_report.json")
_JOB = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
_MAX_WAV_BYTES = 1_000_044  # M3.1 max 500,000 mono PCM16 frames + RIFF header


@dataclass(frozen=True, slots=True)
class ABPreview:
    """Portable, in-memory candidate comparison and its generated artifacts."""
    a: PreviewResult
    b: PreviewResult
    wav_a: bytes
    wav_b: bytes
    report_json: bytes


def _canonical(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _unique_waves(bundle: ExportBundle) -> dict[int, Wave]:
    """Decode only the transmitted waves; M3.1 separately validates packets."""
    result = {}
    for index, wave_id in enumerate(bundle.wave_ids):
        packet = bundle.sysex[index * WAVE_DUMP_LENGTH:(index + 1) * WAVE_DUMP_LENGTH]
        result[wave_id] = decode_wave_dump(packet).wave
    return result


def _rms(values: tuple[float, ...]) -> float:
    return math.sqrt(math.fsum(x * x for x in values) / len(values))


def _transitions(bundle: ExportBundle, *, jump_threshold: float,
                 cancellation_threshold: float,
                 crossfade_applicable: bool = True) -> list[dict[str, Any]]:
    waves = _unique_waves(bundle)
    refs = bundle.table.user_positions
    rows = []
    for pos in range(60):
        a = waves[refs[pos]].samples
        b = waves[refs[pos + 1]].samples
        diff = math.sqrt(math.fsum((x-y)**2 for x,y in zip(a,b))/128) / 128
        norm_a = _rms(tuple(x / 128 for x in a))
        norm_b = _rms(tuple(x / 128 for x in b))
        mid = _rms(tuple((x+y)/256 for x,y in zip(a,b)))
        mean_end = (norm_a+norm_b)/2
        cancellation = (mid/mean_end if mean_end > 1e-12 else None) if crossfade_applicable else None
        rows.append({
            "from_position": pos,
            "to_position": pos+1,
            "adjacent_wave_rms_difference": diff,
            "crossfade_midpoint_rms_ratio": cancellation,
            "large_numerical_change": diff >= jump_threshold,
            # Do not flag two near-silent waves as phase cancellation.
            "possible_midpoint_cancellation": (
                cancellation is not None and cancellation < cancellation_threshold
                and min(norm_a, norm_b) > 0.05),
        })
    return rows


def compare_bundle_previews(a: ExportBundle, b: ExportBundle, *,
                            sample_rate: int = 48000,
                            frequency_hz: float = 220.0,
                            duration_seconds: float = 1.0,
                            start_position: float = 0.0,
                            end_position: float = 60.0,
                            table_interpolation: str | None = None,
                            phase_interpolation: str | None = None,
                            render_profile: str | None = None,
                            amplitude: float = 0.8,
                            initial_phase: float = 0.0,
                            jump_threshold: float = 0.5,
                            cancellation_threshold: float = 0.5) -> ABPreview:
    """Render matching A/B tests and explain all 60 editable transitions.

    All thresholds are user-controlled numerical heuristics; there is
    deliberately no ``winner`` or subjective/perceptual quality score.
    A/B candidates must refer to the same original snapshot SHA-256.
    """
    if not isinstance(a, ExportBundle) or not isinstance(b, ExportBundle):
        raise PreviewError("A and B must be offline ExportBundle objects")
    if a.source_dump_sha256 != b.source_dump_sha256:
        raise PreviewError("A/B source snapshots differ: comparison requires one backup")
    # The M3.1 renderer checks SYX geometry, SHA-256, table and wave IDs.
    # Also ensure that both M2.6 export manifests identify the SAME backup.
    for side in (a, b):
        try:
            metadata = json.loads(side.manifest_json)
            if (metadata.get("schema") != "xtwavetable.m2.6.offline_export.v1"
                    or metadata.get("source_snapshot_sha256") != side.source_dump_sha256):
                raise PreviewError("A/B export snapshot provenance is inconsistent")
        except (ValueError, AttributeError, TypeError) as exc:
            raise PreviewError("A/B export manifest is invalid") from exc
    for name, value, maximum in (("jump_threshold",jump_threshold,2),
                                  ("cancellation_threshold",cancellation_threshold,1)):
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise PreviewError(f"{name} must be finite and in [0,{maximum}]")
    table_interpolation, phase_interpolation, profile = resolve_profile(
        render_profile, table_interpolation=table_interpolation,
        phase_interpolation=phase_interpolation)
    settings = dict(sample_rate=sample_rate, frequency_hz=frequency_hz,
                    duration_seconds=duration_seconds, start_position=start_position,
                    end_position=end_position, table_interpolation=table_interpolation,
                    phase_interpolation=phase_interpolation, amplitude=amplitude,
                    initial_phase=initial_phase)
    preview_a = render_export_bundle_preview(a, **settings)
    preview_b = render_export_bundle_preview(b, **settings)
    wav_a = encode_preview_pcm16_wav(preview_a)
    wav_b = encode_preview_pcm16_wav(preview_b)
    if len(preview_a.samples) != len(preview_b.samples):
        raise PreviewError("A/B rendered different frame counts")
    delta = tuple(x - y for x, y in zip(preview_a.samples,preview_b.samples))
    energy_a = math.fsum(x*x for x in preview_a.samples)
    energy_b = math.fsum(x*x for x in preview_b.samples)
    similarity = (math.fsum(x*y for x,y in zip(preview_a.samples,preview_b.samples)) /
                  math.sqrt(energy_a*energy_b)) if energy_a > 0 and energy_b > 0 else None
    applies = profile.crossfade_midpoint_applicable if profile is not None else True
    ta = _transitions(a,jump_threshold=jump_threshold,cancellation_threshold=cancellation_threshold,
                      crossfade_applicable=applies)
    tb = _transitions(b,jump_threshold=jump_threshold,cancellation_threshold=cancellation_threshold,
                      crossfade_applicable=applies)
    report = {
        "schema": _SCHEMA,
        "engine": "M3.1_APPROX_LINEAR_OR_NEAREST_NOT_WALDORF_DSP",
        "offline_only": True,
        "hardware_upload_authorized": False,
        "same_source_snapshot": True,
        "source_snapshot_sha256": a.source_dump_sha256,
        "render_settings": settings,
        "thresholds_are_uncalibrated_heuristics": {
            "jump_threshold": jump_threshold,
            "cancellation_threshold": cancellation_threshold,
        },
        "A": {
            "sysex_sha256": sha256(a.sysex).hexdigest(),
            "preview_samples_sha256": preview_a.samples_sha256,
            "wav_sha256": sha256(wav_a).hexdigest(),
            "peak": preview_a.peak, "rms": preview_a.rms,
            "transitions": ta,
            "large_change_positions": [r["from_position"] for r in ta if r["large_numerical_change"]],
            "possible_cancellation_positions": [r["from_position"] for r in ta if r["possible_midpoint_cancellation"]],
        },
        "B": {
            "sysex_sha256": sha256(b.sysex).hexdigest(),
            "preview_samples_sha256": preview_b.samples_sha256,
            "wav_sha256": sha256(wav_b).hexdigest(),
            "peak": preview_b.peak, "rms": preview_b.rms,
            "transitions": tb,
            "large_change_positions": [r["from_position"] for r in tb if r["large_numerical_change"]],
            "possible_cancellation_positions": [r["from_position"] for r in tb if r["possible_midpoint_cancellation"]],
        },
        "comparison": {
            "same_pcm16_wav": wav_a == wav_b,
            "rms_sample_difference": _rms(delta),
            "peak_sample_difference": max(abs(x) for x in delta),
            "cosine_similarity": similarity,
            "winner": None,
        },
        "limitations": [
            "Heuristic numbers are not listening judgements and give no automatic winner.",
            "Crossfade is a deliberately approximate time-domain model, not Waldorf DSP.",
            "Wave quantization and phase alignment can cause loss and aliasing.",
            "Actual XT interpolation and perceptual parity require M4/M7 validation.",
            "Reserved table positions 61..63 are not auditioned.",
        ],
    }
    if profile is not None:
        report["render_profile"] = profile.metadata()
        report["limitations"].append("Named M3.6 profile is a numerical model; no firmware or Xenia waveform parity certified.")
        if not profile.crossfade_midpoint_applicable:
            report["limitations"].append("Crossfade midpoint metrics are COUNTERFACTUAL ONLY in stock XT discrete mode; do not rank by them.")
    return ABPreview(preview_a,preview_b,wav_a,wav_b,_canonical(report))


def _root(root: str | Path) -> Path:
    """Mimic the M2.8 root policy: real private/runs dirs and Git ignore gates."""
    if not isinstance(root, (str, Path)):
        raise PreviewError("root must be a filesystem path")
    try:
        resolved = Path(root).resolve(strict=True)
    except (OSError,RuntimeError) as exc:
        raise PreviewError("workspace root is unavailable") from exc
    if not resolved.is_dir() or not (resolved/"docs"/"ARCHITECTURE.md").is_file():
        raise PreviewError("expected XT-WAVETABLE-LAB workspace root")
    ignore = resolved/".gitignore"
    if not ignore.is_file():
        raise PreviewError("workspace .gitignore missing")
    rules = {line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()}
    if not {"/runs/", "/private/"}.issubset(rules):
        raise PreviewError("private/ and runs/ must be Git-ignored")
    for name in ("private", "runs"):
        folder = resolved/name
        if folder.is_symlink() or not folder.is_dir() or folder.resolve() != folder:
            raise PreviewError("private/ and runs/ must be real directories")
    return resolved


def _job_dir(root: str | Path, job: str) -> Path:
    if not isinstance(job,str) or _JOB.fullmatch(job) is None:
        raise PreviewError("job must be 1..64 ASCII letters/digits/_/-; no traversal")
    return _root(root)/"runs"/job


def write_ab_previews(root: str | Path, job: str, pair: ABPreview) -> tuple[Path, Path, Path]:
    """Explicitly write new, ignored runs/<job>/ WAV A, WAV B, JSON. No overwrite."""
    if not isinstance(pair, ABPreview):
        raise PreviewError("pair must be an ABPreview")
    # Always validate in-memory report/payload consistency before any writes.
    _verify_payloads(pair.wav_a, pair.wav_b, pair.report_json)
    folder = _job_dir(root,job)
    folder.mkdir(mode=0o700,exist_ok=False)
    created: list[Path] = []
    try:
        for name, payload in zip(_FILES, (pair.wav_a,pair.wav_b,pair.report_json)):
            path = folder/name
            with path.open("xb") as stream:
                created.append(path)
                stream.write(payload)
        verify_ab_previews(root,job)
    except BaseException:
        for path in reversed(created):
            if path.is_file() and not path.is_symlink():
                path.unlink()
        try:
            folder.rmdir()
        except OSError:
            pass
        raise
    return tuple(folder/name for name in _FILES)


def _verify_payloads(a: bytes, b: bytes, raw: bytes) -> dict[str, Any]:
    if any(not isinstance(item, bytes) for item in (a,b,raw)):
        raise PreviewError("A/B output and JSON must be bytes")
    if not 44 <= len(a) <= _MAX_WAV_BYTES or not 44 <= len(b) <= _MAX_WAV_BYTES:
        raise PreviewError("A/B WAV size exceeds renderer bounds")
    if len(raw) > 200_000:
        raise PreviewError("A/B JSON report exceeds expected size")
    try:
        report = json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise PreviewError("A/B report is not JSON") from exc
    if not isinstance(report,dict) or report.get("schema") != _SCHEMA or raw != _canonical(report):
        raise PreviewError("A/B report schema or canonicalization invalid")
    validate_report_profile(report)
    if report.get("offline_only") is not True or report.get("hardware_upload_authorized") is not False:
        raise PreviewError("A/B report lacks offline safety declaration")
    if not all(isinstance(report.get(part),dict) for part in ("A","B","comparison","render_settings")):
        raise PreviewError("A/B report has invalid sections")
    for payload, side in ((a,"A"),(b,"B")):
        if (payload[:4] != b"RIFF" or payload[8:12] != b"WAVE"
                or payload[12:16] != b"fmt " or payload[36:40] != b"data"
                or struct.unpack_from("<I",payload,4)[0] != len(payload)-8
                or struct.unpack_from("<I",payload,40)[0] != len(payload)-44
                or struct.unpack_from("<I",payload,16)[0] != 16
                or struct.unpack_from("<H",payload,20)[0] != 1
                or struct.unpack_from("<H",payload,22)[0] != 1
                or struct.unpack_from("<H",payload,34)[0] != 16
                or struct.unpack_from("<I",payload,24)[0] != report["render_settings"].get("sample_rate")):
            raise PreviewError("A/B audio is not valid expected PCM16 mono RIFF/WAVE")
        if report.get(side,{}).get("wav_sha256") != sha256(payload).hexdigest():
            raise PreviewError("A/B WAV hash differs from the report")
    if report.get("comparison",{}).get("same_pcm16_wav") is not (a==b):
        raise PreviewError("A/B equality check differs from the report")
    return report


def verify_ab_previews(root: str | Path, job: str) -> dict[str, Any]:
    """Nonmutating integrity check: not an authenticated signature or DSP QA."""
    folder = _job_dir(root,job)
    if folder.is_symlink() or not folder.is_dir():
        raise PreviewError("job directory is missing or a symbolic link")
    values = []
    for name in _FILES:
        path = folder/name
        if path.is_symlink() or not path.is_file():
            raise PreviewError("output file missing or a symbolic link")
        if path.stat().st_size > (_MAX_WAV_BYTES if name.endswith(".wav") else 200_000):
            raise PreviewError("output file exceeds bounds")
        values.append(path.read_bytes())
    report = _verify_payloads(*values)
    return {"job":job,"A_wav_sha256":report["A"]["wav_sha256"],
            "B_wav_sha256":report["B"]["wav_sha256"],
            "same_pcm16_wav":report["comparison"]["same_pcm16_wav"]}
