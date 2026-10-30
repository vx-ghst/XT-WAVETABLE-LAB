"""M3.4 bounded offline batch QA for M2.8 candidates (APPROXIMATIONS).

Reuses only validated M3.1 oscillator and M3.2 transition diagnostics. A
batch has 2..6 candidates from the SAME source XT backup, not necessarily
the same source WAV. Renders each candidate exactly once in each run and
computes pairwise metrics without automatically declaring a winner.

No MIDI, device, firmware, private path, network or original-file writes.
Explicit output is restricted to a new runs/<job>/ directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Sequence

from xtwavetable.export.bundle import ExportBundle
from xtwavetable.preview.compare import _job_dir, _transitions
from xtwavetable.preview.profiles import resolve_profile, validate_report_profile
from xtwavetable.preview.oscillator import (
    PreviewError, encode_preview_pcm16_wav, render_export_bundle_preview,
)

_SCHEMA = "xtwavetable.m3.4.approx_batch.v1"
_AUDIT_SCHEMA = "xtwavetable.m3.4.batch_audit.v1"
_MAX_ITEMS = 6
_MAX_FRAMES = 100_000
_MAX_REPORT_BYTES = 200_000
_MAX_WAV_BYTES = 44 + _MAX_FRAMES * 2


def _canonical(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _label(index: int) -> str:
    return f"C{index + 1:02d}"


def _wav_filename(index: int) -> str:
    return f"preview_{_label(index)}.wav"


def _hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class BatchPreview:
    wav_files: tuple[tuple[str, bytes], ...]
    report_json: bytes
    audit_json: bytes


def analyze_batch_previews(
    candidates: Sequence[ExportBundle], *,
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
    cancellation_threshold: float = 0.5,
) -> BatchPreview:
    """Run same-settings preview for 2..6 candidates; report numerical QA only."""
    if type(candidates) not in (tuple, list) or not 2 <= len(candidates) <= _MAX_ITEMS:
        raise PreviewError("batch requires an ordered list/tuple of 2..6 candidates")
    if any(not isinstance(candidate, ExportBundle) for candidate in candidates):
        raise PreviewError("every batch candidate must be an ExportBundle")
    backup = candidates[0].source_dump_sha256
    if not _hex(backup) or any(c.source_dump_sha256 != backup for c in candidates):
        raise PreviewError("all batch candidates must share one valid XT backup hash")
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
        raise PreviewError("sample_rate must be 8000..192000")
    if type(duration_seconds) not in (int, float) or not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise PreviewError("duration must be finite and positive")
    if round(duration_seconds * sample_rate) > _MAX_FRAMES:
        raise PreviewError("batch preview exceeds per-candidate 100000 frame budget")
    for key, value, maximum in (("jump_threshold", jump_threshold, 2.0),
                                ("cancellation_threshold", cancellation_threshold, 1.0)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise PreviewError(f"{key} must be finite and within [0,{maximum}]")
    table_interpolation, phase_interpolation, profile = resolve_profile(
        render_profile, table_interpolation=table_interpolation,
        phase_interpolation=phase_interpolation)
    settings = dict(sample_rate=sample_rate, frequency_hz=frequency_hz,
                    duration_seconds=duration_seconds, start_position=start_position,
                    end_position=end_position, table_interpolation=table_interpolation,
                    phase_interpolation=phase_interpolation, amplitude=amplitude,
                    initial_phase=initial_phase)
    rendered = []
    wavs: list[tuple[str, bytes]] = []
    rows = []
    for i, candidate in enumerate(candidates):
        # The M3.1 renderer validates packet geometry, IDs, checksum and hashes.
        # Additional provenance check stops mismatched backup metadata.
        try:
            export_meta = json.loads(candidate.manifest_json)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise PreviewError("batch export manifest is malformed") from exc
        if (not isinstance(export_meta, dict)
                or export_meta.get("schema") != "xtwavetable.m2.6.offline_export.v1"
                or export_meta.get("source_snapshot_sha256") != backup):
            raise PreviewError("batch export backup provenance mismatch")
        preview = render_export_bundle_preview(candidate, **settings)
        wav = encode_preview_pcm16_wav(preview)
        transitions = _transitions(candidate, jump_threshold=jump_threshold,
                                   cancellation_threshold=cancellation_threshold,
                                   crossfade_applicable=(profile.crossfade_midpoint_applicable
                                                         if profile is not None else True))
        if len(transitions) != 60:
            raise PreviewError("expected exactly 60 editable transitions")
        label = _label(i)
        rendered.append(preview)
        wavs.append((_wav_filename(i), wav))
        rows.append({
            "label": label,
            "wave_packets": len(candidate.wave_ids),
            "table_id": candidate.table_id,
            "sysex_sha256": sha256(candidate.sysex).hexdigest(),
            "samples_sha256": preview.samples_sha256,
            "wav_sha256": sha256(wav).hexdigest(),
            "frames": preview.frames,
            "peak": preview.peak,
            "rms": preview.rms,
            "max_adjacent_wave_rms_difference": preview.max_adjacent_wave_rms_difference,
            "large_change_positions": [t["from_position"] for t in transitions if t["large_numerical_change"]],
            "possible_cancellation_positions": [t["from_position"] for t in transitions if t["possible_midpoint_cancellation"]],
            "transitions": transitions,
        })
    pairs = []
    for i in range(len(rendered)):
        for j in range(i + 1, len(rendered)):
            a, b = rendered[i].samples, rendered[j].samples
            if len(a) != len(b):
                raise PreviewError("batch candidates have inconsistent rendered frame counts")
            deltas = [x-y for x, y in zip(a,b)]
            squared_diff = math.fsum(d*d for d in deltas)
            ea = math.fsum(x*x for x in a)
            eb = math.fsum(x*x for x in b)
            similarity = (math.fsum(x*y for x,y in zip(a,b))/math.sqrt(ea*eb)
                          if ea > 0 and eb > 0 else None)
            pairs.append({
                "A": _label(i), "B": _label(j),
                "same_pcm16_wav": wavs[i][1] == wavs[j][1],
                "rms_sample_difference": math.sqrt(squared_diff / len(a)),
                "peak_sample_difference": max(abs(d) for d in deltas),
                "cosine_similarity": similarity,
                "winner": None,
            })
    report = {
        "schema": _SCHEMA,
        "engine": "M3.1_APPROX_LINEAR_OR_NEAREST_NOT_WALDORF_DSP",
        "offline_only": True, "hardware_upload_authorized": False,
        "source_snapshot_sha256": backup,
        "render_settings": settings,
        "thresholds_are_uncalibrated_heuristics": {
            "jump_threshold": jump_threshold,
            "cancellation_threshold": cancellation_threshold,
        },
        "candidates": rows, "pairwise": pairs,
        "winner": None,
        "limitations": [
            "All numerical comparisons use a simplified, uncalibrated preview model.",
            "Different source WAVs may be represented; only XT backup hash is shared.",
            "No perceptual ranking, listening judgement, or automatic winner.",
            "XT hardware/firmware parity requires M4 and optionally M7.",
            "Reserved table positions 61..63 are not auditioned.",
        ],
    }
    if profile is not None:
        report["render_profile"] = profile.metadata()
        report["limitations"].append("Named M3.6 profile is a numerical model; no firmware/Xenia parity certified.")
        if not profile.crossfade_midpoint_applicable:
            report["limitations"].append("Crossfade cancellation metrics are COUNTERFACTUAL ONLY for stock XT discrete mode.")
    report_json = _canonical(report)
    audit_json = _canonical({
        "schema": _AUDIT_SCHEMA,
        "offline_only": True, "hardware_upload_authorized": False,
        "batch_report_sha256": sha256(report_json).hexdigest(),
        "wav_sha256": {name: sha256(blob).hexdigest() for name, blob in wavs},
        "authenticity": "UNSIGNED_INTEGRITY_ONLY",
    })
    result = BatchPreview(tuple(wavs), report_json, audit_json)
    _verify_payloads(result)
    return result


def _verify_payloads(result: BatchPreview) -> dict[str, Any]:
    """Validate canonical untrusted batch outputs without leaking raw exceptions."""
    try:
        return _verify_payloads_impl(result)
    except PreviewError:
        raise
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, ArithmeticError) as exc:
        raise PreviewError("batch output has malformed metadata") from exc


def _verify_payloads_impl(result: BatchPreview) -> dict[str, Any]:
    if not isinstance(result, BatchPreview):
        raise PreviewError("batch output has wrong type")
    if any(not isinstance(x, bytes) for x in (result.report_json, result.audit_json)):
        raise PreviewError("batch JSON payloads must be bytes")
    if len(result.report_json) > _MAX_REPORT_BYTES or len(result.audit_json) > 4096:
        raise PreviewError("batch report exceeds size budget")
    try:
        report = json.loads(result.report_json)
        audit = json.loads(result.audit_json)
    except (UnicodeError, ValueError) as exc:
        raise PreviewError("batch JSON is not decodable") from exc
    if isinstance(report, dict):
        validate_report_profile(report)
    if (not isinstance(report, dict) or not isinstance(audit, dict)
            or result.report_json != _canonical(report)
            or result.audit_json != _canonical(audit)
            or report.get("schema") != _SCHEMA or audit.get("schema") != _AUDIT_SCHEMA
            or report.get("offline_only") is not True or audit.get("offline_only") is not True
            or report.get("hardware_upload_authorized") is not False
            or audit.get("hardware_upload_authorized") is not False
            or report.get("winner", "INVALID") is not None
            or audit.get("authenticity") != "UNSIGNED_INTEGRITY_ONLY"):
        raise PreviewError("batch report or audit metadata is inconsistent")
    candidates = report.get("candidates")
    pairs = report.get("pairwise")
    if (not isinstance(candidates,list) or not 2 <= len(candidates) <= _MAX_ITEMS
            or not isinstance(pairs,list) or len(pairs) != len(candidates)*(len(candidates)-1)//2
            or not isinstance(result.wav_files,tuple) or len(result.wav_files) != len(candidates)
            or not isinstance(audit.get("wav_sha256"),dict)
            or audit.get("batch_report_sha256") != sha256(result.report_json).hexdigest()
            or not _hex(report.get("source_snapshot_sha256"))):
        raise PreviewError("batch geometry or report hash invalid")
    settings = report.get("render_settings")
    if (not isinstance(settings, dict) or type(settings.get("sample_rate")) is not int
            or not 8000 <= settings["sample_rate"] <= 192000
            or type(settings.get("duration_seconds")) not in (int, float)
            or not math.isfinite(settings["duration_seconds"])
            or not 0 < round(settings["duration_seconds"] * settings["sample_rate"]) <= _MAX_FRAMES):
        raise PreviewError("batch render settings invalid")
    names = tuple(_wav_filename(i) for i in range(len(candidates)))
    if set(audit["wav_sha256"]) != set(names):
        raise PreviewError("batch audit WAV listing mismatch")
    for i, (filename, wav) in enumerate(result.wav_files):
        candidate = candidates[i]
        if (not isinstance(candidate,dict) or candidate.get("label") != _label(i)
                or type(candidate.get("frames")) is not int
                or candidate.get("frames") != round(settings["duration_seconds"]*settings["sample_rate"])
                or type(candidate.get("wave_packets")) is not int
                or not 1 <= candidate["wave_packets"] <= 61
                or type(candidate.get("table_id")) is not int
                or not 96 <= candidate["table_id"] <= 127
                or not all(_hex(candidate.get(field)) for field in ("sysex_sha256","samples_sha256","wav_sha256"))
                or any(type(candidate.get(k)) not in (int,float) or not math.isfinite(candidate[k])
                       for k in ("peak","rms","max_adjacent_wave_rms_difference"))
                or not 0 <= candidate["peak"] <= 1
                or not 0 <= candidate["rms"] <= 1
                or not 0 <= candidate["max_adjacent_wave_rms_difference"] <= 2
                or not isinstance(candidate.get("transitions"),list)
                or len(candidate["transitions"]) != 60
                or not isinstance(candidate.get("large_change_positions"),list)
                or not isinstance(candidate.get("possible_cancellation_positions"),list)
                or filename != names[i] or not isinstance(wav,bytes)
                or not 46 <= len(wav) <= _MAX_WAV_BYTES
                or len(wav) != 44 + candidate["frames"]*2
                or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE"
                or wav[12:16] != b"fmt " or wav[36:40] != b"data"
                or wav[20:22] != b"\x01\x00" or wav[22:24] != b"\x01\x00"
                or wav[34:36] != b"\x10\x00"
                or int.from_bytes(wav[4:8],"little") != len(wav)-8
                or int.from_bytes(wav[40:44],"little") != len(wav)-44
                or int.from_bytes(wav[24:28],"little") != settings["sample_rate"]):
            raise PreviewError("batch preview WAV or report structure invalid")
        for pos, transition in enumerate(candidate["transitions"]):
            if (not isinstance(transition,dict)
                    or type(transition.get("from_position")) is not int
                    or transition["from_position"] != pos
                    or type(transition.get("to_position")) is not int
                    or transition["to_position"] != pos+1
                    or type(transition.get("large_numerical_change")) is not bool
                    or type(transition.get("possible_midpoint_cancellation")) is not bool
                    or type(transition.get("adjacent_wave_rms_difference")) not in (int,float)
                    or not math.isfinite(transition["adjacent_wave_rms_difference"])
                    or not 0 <= transition["adjacent_wave_rms_difference"] <= 2):
                raise PreviewError("batch transition diagnostics malformed")
            ratio = transition.get("crossfade_midpoint_rms_ratio")
            if ratio is not None and (type(ratio) not in (int,float) or not math.isfinite(ratio) or ratio < 0):
                raise PreviewError("batch cancellation diagnostic malformed")
        if (candidate["large_change_positions"] != [t["from_position"] for t in candidate["transitions"] if t["large_numerical_change"]]
                or candidate["possible_cancellation_positions"] != [t["from_position"] for t in candidate["transitions"] if t["possible_midpoint_cancellation"]]):
            raise PreviewError("batch transition flags do not match the summary")
        checksum = sha256(wav).hexdigest()
        if checksum != candidate.get("wav_sha256") or checksum != audit["wav_sha256"][filename]:
            raise PreviewError("batch WAV hash mismatch")
    expected_pairs = [(_label(i),_label(j))
                      for i in range(len(candidates)) for j in range(i+1,len(candidates))]
    for p, expected in zip(pairs, expected_pairs):
        i, j = int(expected[0][1:]) - 1, int(expected[1][1:]) - 1
        if (not isinstance(p, dict) or (p.get("A"),p.get("B")) != expected
                or p.get("winner", "INVALID") is not None
                or type(p.get("same_pcm16_wav")) is not bool
                or p["same_pcm16_wav"] != (result.wav_files[i][1] == result.wav_files[j][1])
                or any(type(p.get(field)) not in (int,float) or not math.isfinite(p[field])
                       or p[field] < 0 or p[field] > 2
                       for field in ("rms_sample_difference", "peak_sample_difference"))):
            raise PreviewError("batch pairwise report is inconsistent")
        similarity = p.get("cosine_similarity")
        if similarity is not None and (type(similarity) not in (int,float)
                                       or not math.isfinite(similarity)
                                       or not -1.0000000001 <= similarity <= 1.0000000001):
            raise PreviewError("batch pairwise similarity is invalid")
    return report


def write_batch_previews(root: str | Path, job: str, batch: BatchPreview) -> tuple[Path, ...]:
    """Write N WAV and two JSON files only into a new, ignored runs/<job>/."""
    _verify_payloads(batch)
    folder = _job_dir(root,job)
    folder.mkdir(mode=0o700, exist_ok=False)
    paths: list[Path] = []
    try:
        for filename, payload in (*batch.wav_files,
                                  ("batch_report.json",batch.report_json),
                                  ("batch_audit.json",batch.audit_json)):
            target = folder / filename
            with target.open("xb") as handle:
                paths.append(target)
                handle.write(payload)
        verify_batch_previews(root, job)
    except BaseException:
        for path in reversed(paths):
            if path.is_file() and not path.is_symlink():
                path.unlink()
        try:
            folder.rmdir()
        except OSError:
            pass
        raise
    return tuple(paths)


def verify_batch_previews(root: str | Path, job: str) -> dict[str, Any]:
    """Read-only, UNSIGNED integrity and geometry check for generated batch."""
    folder = _job_dir(root, job)
    if folder.is_symlink() or not folder.is_dir():
        raise PreviewError("batch job is missing or a symlink")
    report_file = folder / "batch_report.json"
    audit_file = folder / "batch_audit.json"
    for p in (report_file,audit_file):
        if p.is_symlink() or not p.is_file() or p.stat().st_size > _MAX_REPORT_BYTES:
            raise PreviewError("batch report is missing or unsafe")
    raw_report, raw_audit = report_file.read_bytes(), audit_file.read_bytes()
    try:
        metadata = json.loads(raw_report)
    except (UnicodeError,ValueError) as exc:
        raise PreviewError("batch report is invalid JSON") from exc
    if not isinstance(metadata,dict) or not isinstance(metadata.get("candidates"),list):
        raise PreviewError("batch report has invalid candidates")
    count = len(metadata["candidates"])
    if not 2 <= count <= _MAX_ITEMS:
        raise PreviewError("batch candidate count invalid")
    wavs = []
    for index in range(count):
        filename = _wav_filename(index)
        f = folder / filename
        if f.is_symlink() or not f.is_file() or f.stat().st_size > _MAX_WAV_BYTES:
            raise PreviewError("batch WAV missing or unsafe")
        wavs.append((filename, f.read_bytes()))
    if {f.name for f in folder.iterdir()} != {"batch_report.json","batch_audit.json",*(n for n,_ in wavs)}:
        raise PreviewError("unexpected files in batch output directory")
    checked = _verify_payloads(BatchPreview(tuple(wavs),raw_report,raw_audit))
    return {"job": job,"candidates":count,"pairs":len(checked["pairwise"]),
            "batch_report_sha256":sha256(raw_report).hexdigest(),"winner":None}
