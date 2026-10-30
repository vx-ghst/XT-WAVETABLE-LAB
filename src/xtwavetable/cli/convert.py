"""M2.8 OFFLINE, deterministic WAV -> XT CLI with explicit replacement gates.

Run from the repository root:
    python -m xtwavetable.cli.convert convert --help
    python -m xtwavetable.cli.convert verify --job NAME

All source data must be under private/; generated files stay under runs/.
No firmware, ROM, emulation, USB, MIDI or hardware operations are implemented.
All wave/table RAM IDs require explicit REPLACEMENT authorization, never a
claim that they are free. A successful job does not authorize hardware upload.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

from xtwavetable.audio.wav_reader import MAX_INPUT_BYTES
from xtwavetable.codec_xt import decode_table_dump, decode_wave_dump
from xtwavetable.converter.pipeline import ConversionOptions, convert_wav_to_offline_bundle
from xtwavetable.export.bundle import write_export_bundle

_JOB_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
_MANIFEST_FILE = "xt_pipeline.json"
_AUDIT_FILE = "xt_audit.json"
_EXPORT_STEM = "xt_candidate"
_FILES = ("xt_candidate.syx", "xt_candidate.json", _MANIFEST_FILE, _AUDIT_FILE)
_MAX_BACKUP_BYTES = 16 * 1024 * 1024


class CLIError(ValueError):
    """The requested offline operation violates validation or privacy policy."""


def _serialize(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _ids(value: str) -> tuple[int, ...]:
    """Parse positive integer IDs without ranges or implicit allocation."""
    tokens = value.split(",")
    if not tokens or any(not x.isascii() or not x.isdecimal() for x in tokens):
        raise argparse.ArgumentTypeError("IDs must be comma-separated decimal integers")
    result = tuple(int(x) for x in tokens)
    if len(result) != len(set(result)):
        raise argparse.ArgumentTypeError("duplicate RAM IDs are not allowed")
    return result


def _job(value: str) -> str:
    if not _JOB_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("job name must contain 1-64 ASCII letters, digits, '_' or '-'")
    return value


def _resolved_root(root: str | Path) -> Path:
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not (root / "docs" / "ARCHITECTURE.md").is_file():
        raise CLIError("root is not an XT-WAVETABLE-LAB workspace")
    # Explicitly demand private and runs ignore rules before any work.
    ignore = root / ".gitignore"
    if not ignore.is_file():
        raise CLIError("root .gitignore missing")
    directives = {line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()}
    if "/private/" not in directives or "/runs/" not in directives:
        raise CLIError("private/ and runs/ must be ignored in Git before running")
    for child in ("private", "runs"):
        path = root / child
        if path.is_symlink() or not path.is_dir() or path.resolve() != path:
            raise CLIError("workspace private/ and runs/ must be real directories")
    return root


def _input_path(root: Path, supplied: str | Path) -> Path:
    candidate = Path(supplied)
    if not candidate.is_absolute():
        candidate = root / candidate
    private = root / "private"
    # Preserve the lexical path to detect symlinks even when they point back
    # into private/; Path.resolve() alone would hide those components.
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(private):
        raise CLIError("input must be below workspace private/")
    current = private
    for component in lexical.relative_to(private).parts:
        current = current / component
        if current.is_symlink():
            raise CLIError("symbolic links in input paths are forbidden")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CLIError("private input file unavailable") from exc
    if not resolved.is_relative_to(private) or not resolved.is_file():
        raise CLIError("input must be a regular file below workspace private/")
    return resolved


def _read_input(path: Path, limit: int) -> bytes:
    if path.stat().st_size > limit:
        raise CLIError("private input exceeds in-memory size limit")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise CLIError("private input exceeds in-memory size limit")
    return data


def _audit(result) -> bytes:
    return _serialize({
        "schema": "xtwavetable.m2.8.offline_audit.v1",
        "reproducibility": "PASS_TWO_INDEPENDENT_CONVERSIONS",
        "source_wav_sha256": json.loads(result.manifest_json)["source_wav_sha256"],
        "sysex_sha256": sha256(result.sysex).hexdigest(),
        "export_manifest_sha256": sha256(result.bundle.manifest_json).hexdigest(),
        "pipeline_manifest_sha256": sha256(result.manifest_json).hexdigest(),
        "wave_packets": len(result.bundle.wave_ids),
        "table_id": result.bundle.table_id,
        "offline_only": True,
        "hardware_upload_authorized": False,
    })


def _verify_artifacts(job_dir: Path) -> dict:
    if not job_dir.is_dir() or job_dir.is_symlink():
        raise CLIError("offline job directory is missing or is a symbolic link")
    artifacts = {}
    for filename in _FILES:
        f = job_dir / filename
        if f.is_symlink() or not f.is_file():
            raise CLIError("job output is missing or replaced by a symbolic link")
        if f.stat().st_size > 16 * 1024 * 1024:
            raise CLIError("job output exceeds expected size limit")
        artifacts[filename] = f.read_bytes()
    try:
        export = json.loads(artifacts["xt_candidate.json"])
        pipeline = json.loads(artifacts[_MANIFEST_FILE])
        audit = json.loads(artifacts[_AUDIT_FILE])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CLIError("offline report is not valid JSON") from exc
    if (not isinstance(export, dict) or not isinstance(pipeline, dict)
            or not isinstance(audit, dict)):
        raise CLIError("offline reports must be JSON objects")
    if (export.get("schema") != "xtwavetable.m2.6.offline_export.v1"
            or pipeline.get("schema") != "xtwavetable.m2.7.pipeline.v1"
            or audit.get("schema") != "xtwavetable.m2.8.offline_audit.v1"):
        raise CLIError("unexpected offline manifest schema")
    if pipeline.get("offline_export") != export or pipeline.get("source_wav_sha256") != audit.get("source_wav_sha256"):
        raise CLIError("offline export and pipeline manifests disagree")
    sysex = artifacts["xt_candidate.syx"]
    if (sha256(sysex).hexdigest() != export.get("output_sysex_sha256")
            or sha256(sysex).hexdigest() != audit.get("sysex_sha256")
            or sha256(artifacts["xt_candidate.json"]).hexdigest() != audit.get("export_manifest_sha256")
            or sha256(artifacts[_MANIFEST_FILE]).hexdigest() != audit.get("pipeline_manifest_sha256")
            or audit.get("reproducibility") != "PASS_TWO_INDEPENDENT_CONVERSIONS"
            or audit.get("offline_only") is not True
            or audit.get("hardware_upload_authorized") is not False):
        raise CLIError("offline hash/metadata integrity check failed")
    ids = export.get("wave_ids")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 61
            or any(type(i) is not int for i in ids)
            or len(sysex) != len(ids) * 137 + 265):
        raise CLIError("invalid generated packet geometry")
    for index, wave_id in enumerate(ids):
        if decode_wave_dump(sysex[index * 137:(index + 1) * 137]).wave_id != wave_id:
            raise CLIError("generated wave IDs do not match manifest")
    if decode_table_dump(sysex[-265:]).table_id != export.get("table_id"):
        raise CLIError("generated table ID does not match manifest")
    if audit.get("wave_packets") != len(ids) or audit.get("table_id") != export.get("table_id"):
        raise CLIError("audit and export mismatch")
    return {"job": job_dir.name, "waves": len(ids), "sysex_sha256": sha256(sysex).hexdigest()}


def run_convert(args: argparse.Namespace) -> dict:
    if not isinstance(args.job, str) or not _JOB_PATTERN.fullmatch(args.job):
        raise CLIError("invalid job name")
    root = _resolved_root(args.root)
    wav = _read_input(_input_path(root, args.wav), MAX_INPUT_BYTES)
    snapshot = _read_input(_input_path(root, args.snapshot), _MAX_BACKUP_BYTES)
    opts = ConversionOptions(
        start_frame=args.start_frame, end_frame=args.end_frame,
        channel_mode=args.channel_mode, remove_dc=args.remove_dc,
        normalize_peak_dbfs=args.normalize_peak_dbfs,
        channel=args.channel, pitch_hz=args.pitch_hz,
        analysis_max_windows=args.analysis_max_windows,
        candidate_count=args.candidate_count,
        extraction_method=args.extraction_method,
        normalize_cycle_peak=args.normalize_cycle_peak,
        requested_waves=args.requested_waves,
        selection_strategy=args.selection_strategy,
        shortfall=args.shortfall,
        max_projection_rms_error=args.max_projection_rms_error,
    )
    kw = dict(options=opts, wave_ids=args.wave_ids, table_id=args.table_id,
              authorized_replacement_wave_ids=args.approve_wave_ids,
              authorize_table_replacement=args.authorize_table_replacement,
              acknowledge_cross_table_references=args.acknowledge_cross_table_references,
              device_id=args.device_id)
    first = convert_wav_to_offline_bundle(wav, snapshot, **kw)
    second = convert_wav_to_offline_bundle(wav, snapshot, **kw)
    if (first.sysex != second.sysex or first.manifest_json != second.manifest_json
            or first.bundle.manifest_json != second.bundle.manifest_json):
        raise CLIError("reproducibility check failed: nonidentical results")
    # Only now create the private output directory. No hidden overwrite.
    job_dir = root / "runs" / args.job
    job_dir.mkdir(mode=0o700, exist_ok=False)
    created = []
    try:
        syx, report = write_export_bundle(first.bundle, job_dir, stem=_EXPORT_STEM)
        created.extend((syx, report))
        pipe = job_dir / _MANIFEST_FILE
        with pipe.open("xb") as stream:
            created.append(pipe)
            stream.write(first.manifest_json)
        audit = job_dir / _AUDIT_FILE
        with audit.open("xb") as stream:
            created.append(audit)
            stream.write(_audit(first))
        verification = _verify_artifacts(job_dir)
    except BaseException:
        # Only remove the files we just created; never delete unknown files.
        for f in reversed(created):
            if f.is_file() and not f.is_symlink():
                f.unlink()
        try:
            job_dir.rmdir()
        except OSError:
            pass
        raise
    return verification


def run_verify(args: argparse.Namespace) -> dict:
    if not isinstance(args.job, str) or not _JOB_PATTERN.fullmatch(args.job):
        raise CLIError("invalid job name")
    root = _resolved_root(args.root)
    return _verify_artifacts(root / "runs" / args.job)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m xtwavetable.cli.convert",
                                     description="Strict offline WAV-to-XT exporter; no MIDI/hardware I/O")
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("convert", help="convert private WAV with a complete private XT snapshot")
    verify = sub.add_parser("verify", help="verify existing offline output integrity (not re-render)")
    for subparser in (conv, verify):
        subparser.add_argument("--root", default=".", help="XT-WAVETABLE-LAB repository root (default: cwd)")
        subparser.add_argument("--job", required=True, type=_job,
                               help="unique private runs/<job> name; existing jobs never overwritten")
    conv.add_argument("--wav", required=True, help="source WAV under private/")
    conv.add_argument("--snapshot", required=True, help="complete Everything SysEx dump under private/")
    conv.add_argument("--wave-ids", required=True, type=_ids, help="ordered explicit destination wave IDs")
    conv.add_argument("--approve-wave-ids", required=True, type=_ids,
                      help="explicit authorization to replace exactly those wave IDs")
    conv.add_argument("--table-id", required=True, type=int)
    conv.add_argument("--authorize-table-replacement", action="store_true")
    conv.add_argument("--acknowledge-cross-table-references", action="store_true")
    conv.add_argument("--device-id", type=int, default=127)
    conv.add_argument("--start-frame", type=int, default=0)
    conv.add_argument("--end-frame", type=int, default=None)
    conv.add_argument("--channel-mode", choices=("preserve", "left", "right", "average"), default="preserve")
    conv.add_argument("--channel", type=int, default=0)
    conv.add_argument("--remove-dc", action="store_true")
    conv.add_argument("--normalize-peak-dbfs", type=float, default=None)
    conv.add_argument("--pitch-hz", type=float, default=None)
    conv.add_argument("--analysis-max-windows", type=int, default=12)
    conv.add_argument("--candidate-count", type=int, default=8)
    conv.add_argument("--extraction-method", choices=("uniform", "energy_peak"), default="uniform")
    conv.add_argument("--normalize-cycle-peak", action="store_true")
    conv.add_argument("--requested-waves", type=int, default=8)
    conv.add_argument("--selection-strategy", choices=("uniform", "diversity"), default="uniform")
    conv.add_argument("--shortfall", choices=("reject", "reuse"), default="reject")
    conv.add_argument("--max-projection-rms-error", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        result = run_convert(args) if args.command == "convert" else run_verify(args)
    except (CLIError, ValueError, TypeError, OSError, OverflowError, ArithmeticError) as exc:
        # Don't print source paths, user filenames, stack traces or private hashes.
        message = str(exc)
        if args.command == "convert" and isinstance(exc, OSError):
            message = "private input or job output I/O failure"
        if isinstance(exc, FileExistsError):
            message = "job already exists; refusing overwrite"
        print("[FAIL] " + message, file=sys.stderr)
        return 2
    print(f"[PASS] offline {args.command}: runs/{result['job']}; waves={result['waves']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
