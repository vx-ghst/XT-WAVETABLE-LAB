"""M3.4 CLI for bounded, offline approximate batch preview of M2.8 jobs."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from xtwavetable.cli.convert import CLIError, _resolved_root
from xtwavetable.cli.preview_ab import PreviewCLIError, _job, load_m2_export
from xtwavetable.preview.batch import (
    analyze_batch_previews, verify_batch_previews, write_batch_previews,
)
from xtwavetable.preview.profiles import PROFILES, ProfileError, resolve_profile
from xtwavetable.preview.oscillator import PreviewError


class BatchCLIError(ValueError):
    """Sanitized batch CLI failure (no filesystem paths)."""


def run_batch(args: argparse.Namespace) -> dict:
    if not isinstance(args,argparse.Namespace):
        raise BatchCLIError("invalid batch arguments")
    if not isinstance(getattr(args,"job",None),str) or not _job_pattern(args.job):
        raise BatchCLIError("invalid output job name")
    source_names = getattr(args,"sources",None)
    if (type(source_names) not in (tuple,list) or not 2 <= len(source_names) <= 6
            or any(not isinstance(name,str) or not _job_pattern(name) for name in source_names)
            or len(set(source_names)) != len(source_names)
            or args.job in source_names):
        raise BatchCLIError("use 2..6 distinct source jobs, excluding the output job")
    root = _resolved_root(args.root)
    candidates = tuple(load_m2_export(root,name) for name in source_names)
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
        first = analyze_batch_previews(candidates,**settings)
        second = analyze_batch_previews(candidates,**settings)
        if first != second:
            raise BatchCLIError("batch output is not deterministic")
        write_batch_previews(root,args.job,first)
        return verify_batch_previews(root,args.job)
    except FileExistsError as exc:
        raise BatchCLIError("batch job exists; refusing overwrite") from exc


def _job_pattern(value: str) -> bool:
    import re
    return re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}",value) is not None


def run_verify(args: argparse.Namespace) -> dict:
    if (not isinstance(args,argparse.Namespace)
            or not isinstance(getattr(args,"job",None),str)
            or not _job_pattern(args.job)):
        raise BatchCLIError("invalid batch job name")
    root = _resolved_root(args.root)
    return verify_batch_previews(root,args.job)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m xtwavetable.cli.preview_batch",
        description="M3.4 offline, approximate 2..6-way QA (NO XT hardware/MIDI)")
    sub = parser.add_subparsers(dest="command",required=True)
    cmp = sub.add_parser("batch",help="compare 2..6 verified M2 jobs into NEW runs/<job>/")
    ver = sub.add_parser("verify",help="verify an existing M3.4 batch, read-only")
    for p in (cmp,ver):
        p.add_argument("--root",default=".")
        p.add_argument("--job",type=_job,required=True)
    cmp.add_argument("--sources",nargs="+",type=_job,required=True,
                     help="ordered names of 2..6 distinct M2.8 jobs")
    cmp.add_argument("--sample-rate",type=int,default=48000)
    cmp.add_argument("--frequency-hz",type=float,default=220.0)
    cmp.add_argument("--duration-seconds",type=float,default=1.0)
    cmp.add_argument("--start-position",type=float,default=0.0)
    cmp.add_argument("--end-position",type=float,default=60.0)
    cmp.add_argument("--render-profile", choices=tuple(PROFILES), default=None,
                     help="named M3.6 APPROX profile; omit for legacy v1 compatible output")
    cmp.add_argument("--table-interpolation",choices=("linear","nearest"),default=None)
    cmp.add_argument("--phase-interpolation",choices=("linear","nearest"),default=None)
    cmp.add_argument("--amplitude",type=float,default=0.8)
    cmp.add_argument("--initial-phase",type=float,default=0.0)
    cmp.add_argument("--jump-threshold",type=float,default=0.5)
    cmp.add_argument("--cancellation-threshold",type=float,default=0.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command == "batch" and args.render_profile is None:
        print("[WARN] Legacy linear preview: NOT native XT 2.33; use --render-profile",file=sys.stderr)
    try:
        result = run_batch(args) if args.command == "batch" else run_verify(args)
    except (BatchCLIError, PreviewCLIError) as exc:
        print("[FAIL] " + str(exc),file=sys.stderr)
        return 2
    except (PreviewError,ProfileError,CLIError,OSError,ValueError,TypeError,ArithmeticError,OverflowError) as exc:
        # Avoid exposing private user paths or exception provenance on the CLI.
        print("[FAIL] offline batch QA rejected",file=sys.stderr)
        return 2
    print(f"[PASS] offline batch {args.command}: runs/{result['job']} ({result['candidates']} candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
