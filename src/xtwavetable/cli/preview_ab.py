"""M3.3 CLI: compare two already-verified M2 offline jobs (APPROX ONLY).

Requires M2.8 candidate artifacts in two existing runs/<job>/ directories,
checks hashes and packet IDs before reconstructing in-memory ExportBundles.
Explicitly writes only three M3.2 preview files to a NEW runs/<job>/.
No private source reads, ROMs, hardware/MIDI, or automatic XT uploads.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from xtwavetable.cli.convert import CLIError, _resolved_root, _verify_artifacts
from xtwavetable.codec_xt.sysex import TABLE_DUMP_LENGTH, WAVE_DUMP_LENGTH, decode_table_dump
from xtwavetable.export.bundle import ExportBundle
from xtwavetable.preview.compare import (
    compare_bundle_previews, verify_ab_previews, write_ab_previews,
)
from xtwavetable.preview.profiles import PROFILES, ProfileError, resolve_profile
from xtwavetable.preview.oscillator import PreviewError

_JOB = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
_EXPORT = ("xt_candidate.syx", "xt_candidate.json")


class PreviewCLIError(ValueError):
    """M3 CLI validation or user action failed (never includes private paths)."""


def _job(value: str) -> str:
    if not isinstance(value, str) or _JOB.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("job must be 1..64 ASCII letters, digits, '_' or '-'")
    return value


def load_m2_export(root: Path, job: str) -> ExportBundle:
    """Read an existing M2.8 job, never private/ or an unverified loose SYX.

    Hashes establish internal consistency, NOT an authenticated signature.
    Invalid inputs raise a sanitized error rather than exposing private paths.
    """
    if not isinstance(root, Path) or not isinstance(job, str) or _JOB.fullmatch(job) is None:
        raise PreviewCLIError("invalid source job")
    folder = root / "runs" / job
    try:
        _verify_artifacts(folder)
        syx_file, metadata_file = (folder / name for name in _EXPORT)
        sysex = syx_file.read_bytes()
        manifest_json = metadata_file.read_bytes()
        meta = json.loads(manifest_json)
        ids = meta["wave_ids"]
        table_id = meta["table_id"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 61
                or any(type(item) is not int or not 1000 <= item <= 1249 for item in ids)
                or len(set(ids)) != len(ids)
                or type(table_id) is not int or not 96 <= table_id <= 127):
            raise ValueError("invalid source IDs")
        if len(sysex) != len(ids) * WAVE_DUMP_LENGTH + TABLE_DUMP_LENGTH:
            raise ValueError("incorrect source packet sizes")
        table_packet = decode_table_dump(sysex[len(ids)*WAVE_DUMP_LENGTH:])
        if table_packet.table_id != table_id:
            raise ValueError("incorrect source table ID")
        table = table_packet.table
        editable = meta["editable_wave_indices"]
        if (not isinstance(editable, list) or len(editable) != 61
                or any(type(i) is not int or i < 0 or i >= len(ids) for i in editable)
                or tuple(ids[i] for i in editable) != table.user_positions):
            raise ValueError("source table references are inconsistent")
        if meta["reserved_table_references_preserved"] != list(table.reserved_positions):
            raise ValueError("source reserved positions differ")
        cross = meta["known_cross_table_references"]
        if (not isinstance(cross, list)
                or any(type(i) is not int or not 96 <= i <= 127 for i in cross)
                or len(set(cross)) != len(cross)):
            raise ValueError("source cross-table metadata invalid")
        backup_hash = meta["source_snapshot_sha256"]
        if (not isinstance(backup_hash, str) or len(backup_hash) != 64
                or any(c not in "0123456789abcdef" for c in backup_hash)
                or sha256(sysex).hexdigest() != meta["output_sysex_sha256"]):
            raise ValueError("source hash/metadata invalid")
        return ExportBundle(sysex, manifest_json, tuple(ids), table_id, table,
                            tuple(cross), backup_hash)
    except (CLIError, ValueError, TypeError, KeyError, IndexError, OSError, OverflowError) as exc:
        raise PreviewCLIError("source M2 job failed offline artifact verification") from exc


def run_compare(args: argparse.Namespace) -> dict:
    """Verify two M2 jobs and render/write three files in a new M3 job."""
    if not isinstance(args, argparse.Namespace):
        raise PreviewCLIError("invalid preview settings")
    for name in ("job", "source_a", "source_b"):
        value = getattr(args, name, None)
        if not isinstance(value, str) or _JOB.fullmatch(value) is None:
            raise PreviewCLIError("invalid job name")
    if args.job in (args.source_a, args.source_b):
        raise PreviewCLIError("output job must differ from source jobs")
    root = _resolved_root(args.root)
    a = load_m2_export(root, args.source_a)
    b = load_m2_export(root, args.source_b)
    profile_name = getattr(args, "render_profile", None)
    table_mode, phase_mode, _ = resolve_profile(
        profile_name, table_interpolation=args.table_interpolation,
        phase_interpolation=args.phase_interpolation)
    settings = dict(sample_rate=args.sample_rate, frequency_hz=args.frequency_hz,
                    duration_seconds=args.duration_seconds,
                    start_position=args.start_position, end_position=args.end_position,
                    table_interpolation=table_mode,
                    phase_interpolation=phase_mode,
                    render_profile=profile_name,
                    amplitude=args.amplitude, initial_phase=args.initial_phase,
                    jump_threshold=args.jump_threshold,
                    cancellation_threshold=args.cancellation_threshold)
    try:
        first = compare_bundle_previews(a, b, **settings)
        # Check deterministic output before writing any file. No hidden seed/state.
        second = compare_bundle_previews(a, b, **settings)
        if ((first.wav_a, first.wav_b, first.report_json) !=
                (second.wav_a, second.wav_b, second.report_json)):
            raise PreviewCLIError("approximate A/B result is not deterministic")
        write_ab_previews(root, args.job, first)
        result = verify_ab_previews(root, args.job)
        result["frames"] = first.a.frames
        result["same_source_snapshot"] = True
        return result
    except FileExistsError as exc:
        raise PreviewCLIError("output job exists; refusing overwrite") from exc


def run_verify(args: argparse.Namespace) -> dict:
    if not isinstance(args, argparse.Namespace) or not isinstance(getattr(args, "job", None), str):
        raise PreviewCLIError("invalid preview job")
    if _JOB.fullmatch(args.job) is None:
        raise PreviewCLIError("invalid preview job")
    root = _resolved_root(args.root)
    return verify_ab_previews(root, args.job)


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m xtwavetable.cli.preview_ab",
        description="M3.3 approximate A/B renderer for existing M2.8 offline jobs; NO hardware/MIDI")
    sub = p.add_subparsers(dest="command", required=True)
    cmp = sub.add_parser("compare", help="render two verified M2.8 jobs to a new runs/<job>/")
    ver = sub.add_parser("verify", help="verify hashes and structure of existing M3.3 preview")
    for target in (cmp, ver):
        target.add_argument("--root", default=".", help="repository root (default: cwd)")
        target.add_argument("--job", type=_job, required=True, help="output/verification job name")
    cmp.add_argument("--source-a", type=_job, required=True, help="existing runs/<job> M2.8 candidate A")
    cmp.add_argument("--source-b", type=_job, required=True, help="existing runs/<job> M2.8 candidate B")
    cmp.add_argument("--sample-rate", type=int, default=48000)
    cmp.add_argument("--frequency-hz", type=float, default=220.0)
    cmp.add_argument("--duration-seconds", type=float, default=1.0)
    cmp.add_argument("--start-position", type=float, default=0.0)
    cmp.add_argument("--end-position", type=float, default=60.0)
    cmp.add_argument("--render-profile", choices=tuple(PROFILES), default=None,
                     help="named M3.6 APPROX profile; omit for byte-identical legacy linear output")
    cmp.add_argument("--table-interpolation", choices=("linear", "nearest"), default=None)
    cmp.add_argument("--phase-interpolation", choices=("linear", "nearest"), default=None)
    cmp.add_argument("--amplitude", type=float, default=0.8)
    cmp.add_argument("--initial-phase", type=float, default=0.0)
    cmp.add_argument("--jump-threshold", type=float, default=0.5)
    cmp.add_argument("--cancellation-threshold", type=float, default=0.5)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command == "compare" and args.render_profile is None:
        print("[WARN] Legacy linear preview: NOT native XT 2.33; use --render-profile",file=sys.stderr)
    try:
        result = run_compare(args) if args.command == "compare" else run_verify(args)
    except PreviewCLIError as exc:
        print("[FAIL] " + str(exc), file=sys.stderr)
        return 2
    except (PreviewError, ProfileError, CLIError, OSError, ValueError, TypeError,
            OverflowError, ArithmeticError) as exc:
        # Sanitized: low-level errors may contain private filesystem paths.
        print("[FAIL] offline A/B verification or rendering rejected", file=sys.stderr)
        return 2
    print(f"[PASS] offline A/B {args.command}: runs/{result['job']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
