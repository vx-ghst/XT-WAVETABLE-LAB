"""M3.2 synthetic A/B, deterministic reporting and safe opt-in exports."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import io
import json
from pathlib import Path
import math
import struct
from tempfile import TemporaryDirectory
import unittest
import wave

from xtwavetable.codec_xt import encode_wave_dump, encode_table_dump
from xtwavetable.export.bundle import ExportBundle
from xtwavetable.model import Table, Wave
from xtwavetable.preview.oscillator import PreviewError
from xtwavetable.preview.compare import (
    compare_bundle_previews,write_ab_previews,verify_ab_previews,
)


def _wave(kind: str) -> Wave:
    half = []
    for i in range(64):
        val = round(100*math.sin(2*math.pi*i/128))
        if kind == "harmonic":
            val = round(100*math.sin(6*math.pi*i/128))
        elif kind == "negative":
            val = -val
        elif kind == "silent":
            val = 0
        half.append(val)
    return Wave.from_half_cycle(half)


def _bundle(kind: str = "base", *, snapshot: str = "9"*64) -> ExportBundle:
    wa = _wave("base")
    wb = _wave("harmonic" if kind=="harmonic" else "negative" if kind=="negative" else "base")
    if kind == "silent":
        wb = _wave("silent")
    if kind == "all_same":
        refs = (1000,)*61
    else:
        refs = (1000,1001)+ (1001,)*59
    table = Table(refs+(0xDEAD,0xBEEF,0xFFFF))
    sysex = (encode_wave_dump(1000,wa)+encode_wave_dump(1001,wb)
             +encode_table_dump(96,table))
    info = {"schema":"xtwavetable.m2.6.offline_export.v1",
            "source_snapshot_sha256":snapshot,
            "output_sysex_sha256":sha256(sysex).hexdigest(),
            "wave_ids":[1000,1001],"table_id":96}
    raw = (json.dumps(info,sort_keys=True)+"\n").encode()
    return ExportBundle(sysex,raw,(1000,1001),96,table,(),snapshot)


def _pair(a=None,b=None, **kw):
    return compare_bundle_previews(a or _bundle("harmonic"),
                                   b or _bundle("negative"),
                                   duration_seconds=.01, **kw)


def _workspace(directory: Path) -> Path:
    (directory/"docs").mkdir()
    (directory/"docs"/"ARCHITECTURE.md").write_text("XT lab",encoding="utf-8")
    (directory/"private").mkdir()
    (directory/"runs").mkdir()
    (directory/".gitignore").write_text("/private/\n/runs/\n",encoding="utf-8")
    return directory


class ABTests(unittest.TestCase):
    def test_same_bundle_is_pcm_identical(self):
        a=_bundle("harmonic")
        p=_pair(a,a)
        self.assertEqual(p.wav_a,p.wav_b)
        self.assertEqual(p.a,p.b)
        self.assertEqual(json.loads(p.report_json)["comparison"]["rms_sample_difference"],0)

    def test_distinct_bundle_detects_difference(self):
        p=_pair()
        d=json.loads(p.report_json)
        self.assertNotEqual(p.wav_a,p.wav_b)
        self.assertGreater(d["comparison"]["rms_sample_difference"],0)
        self.assertFalse(d["comparison"]["same_pcm16_wav"])

    def test_determinism_full_pair(self):
        self.assertEqual(_pair(),_pair())

    def test_repeat_cross_sample_rates(self):
        for rate in (44100,48000,96000):
            with self.subTest(rate=rate):
                p=_pair(sample_rate=rate)
                self.assertEqual(p.a.frames,rate//100)
                self.assertEqual(p.b.frames,rate//100)

    def test_wav_headers_and_length(self):
        pair=_pair()
        for blob in (pair.wav_a,pair.wav_b):
            with wave.open(io.BytesIO(blob),'rb') as wav:
                self.assertEqual(wav.getnchannels(),1)
                self.assertEqual(wav.getsampwidth(),2)
                self.assertEqual(wav.getnframes(),pair.a.frames)
                self.assertEqual(wav.getframerate(),48000)
                self.assertEqual(len(wav.readframes(pair.a.frames)),2*pair.a.frames)

    def test_canonical_report_bytes(self):
        raw=_pair().report_json
        self.assertEqual(raw[-1:],b"\n")
        self.assertEqual(raw,(json.dumps(json.loads(raw),sort_keys=True,
                      ensure_ascii=True,separators=(",", ":"),allow_nan=False)+"\n").encode("ascii"))

    def test_no_automatic_winner(self):
        report=json.loads(_pair().report_json)
        self.assertIsNone(report["comparison"]["winner"])
        self.assertIn("NOT_WALDORF_DSP",report["engine"])
        self.assertTrue(report["offline_only"])
        self.assertFalse(report["hardware_upload_authorized"])

    def test_60_transition_rows_both(self):
        report=json.loads(_pair().report_json)
        for side in ("A","B"):
            rows=report[side]["transitions"]
            self.assertEqual(len(rows),60)
            self.assertEqual([(r["from_position"],r["to_position"]) for r in rows],
                             [(i,i+1) for i in range(60)])

    def test_detect_transition_jump(self):
        report=json.loads(_pair(jump_threshold=.1).report_json)
        self.assertEqual(report["A"]["large_change_positions"],[0])

    def test_no_jump_repeated_waves(self):
        bundle=_bundle("all_same")
        report=json.loads(_pair(bundle,bundle).report_json)
        self.assertEqual(report["A"]["large_change_positions"],[])
        self.assertTrue(all(row["adjacent_wave_rms_difference"]==0
                            for row in report["A"]["transitions"]))

    def test_negative_wave_cancellation_flagged(self):
        d=json.loads(_pair().report_json)
        self.assertIn(0,d["B"]["possible_cancellation_positions"])
        self.assertAlmostEqual(d["B"]["transitions"][0]["crossfade_midpoint_rms_ratio"],0.)

    def test_no_cancellation_when_same(self):
        b=_bundle("all_same")
        d=json.loads(_pair(b,b).report_json)
        self.assertEqual(d["A"]["possible_cancellation_positions"],[])

    def test_silence_no_false_cancellation(self):
        b=_bundle("silent")
        d=json.loads(_pair(b,b).report_json)
        self.assertEqual(d["A"]["possible_cancellation_positions"],[])

    def test_reserved_61_63_not_in_rows(self):
        d=json.loads(_pair().report_json)
        self.assertEqual(d["A"]["transitions"][-1]["to_position"],60)
        self.assertIn("not auditioned",d["limitations"][-1])

    def test_thresholds_control_flags_not_audio(self):
        base=_pair(jump_threshold=.1)
        high=_pair(jump_threshold=.95)
        self.assertEqual(base.wav_a,high.wav_a)
        self.assertNotEqual(base.report_json,high.report_json)

    def test_reject_invalid_thresholds(self):
        for value in (True,-.01,float('nan'),float('inf'),".5"):
            for key in ("jump_threshold","cancellation_threshold"):
                with self.subTest(key=key,value=value),self.assertRaises(PreviewError):
                    _pair(**{key:value})
        with self.assertRaises(PreviewError):
            _pair(jump_threshold=2.01)
        with self.assertRaises(PreviewError):
            _pair(cancellation_threshold=1.01)

    def test_reject_mixed_snapshots(self):
        with self.assertRaisesRegex(PreviewError,"source snapshots differ"):
            _pair(_bundle(snapshot="9"*64),_bundle(snapshot="8"*64))

    def test_reject_false_snapshot_manifest(self):
        a=_bundle()
        manifest=json.loads(a.manifest_json)
        manifest["source_snapshot_sha256"] = "8"*64
        forged=replace(a, manifest_json=(json.dumps(manifest)+"\n").encode())
        with self.assertRaises(PreviewError):
            _pair(forged,a)

    def test_reject_invalid_export_schema(self):
        a=_bundle()
        manifest=json.loads(a.manifest_json)
        manifest["schema"] = "unknown"
        forged=replace(a,manifest_json=(json.dumps(manifest)+"\n").encode())
        with self.assertRaises(PreviewError):
            _pair(forged,a)

    def test_jump_threshold_above_one_supported(self):
        pair=_pair(jump_threshold=1.5)
        self.assertEqual(json.loads(pair.report_json)["thresholds_are_uncalibrated_heuristics"]["jump_threshold"],1.5)

    def test_reject_invalid_bundle(self):
        with self.assertRaises(PreviewError):
            _pair(_bundle(),7)

    def test_reject_tampered_sysex(self):
        a=_bundle()
        with self.assertRaises(PreviewError):
            _pair(replace(a,sysex=a.sysex[:-1]+b"\x00"),a)

    def test_reject_invalid_render_params(self):
        with self.assertRaises(PreviewError):
            _pair(sample_rate=500)
        with self.assertRaises(PreviewError):
            _pair(start_position=-1)

    def test_source_does_not_mutate(self):
        a,b=_bundle(),_bundle("negative")
        before=(a.sysex,a.table.wave_ids,b.sysex,b.table.wave_ids)
        _pair(a,b)
        self.assertEqual(before,(a.sysex,a.table.wave_ids,b.sysex,b.table.wave_ids))

    def test_report_has_no_source_filename(self):
        raw=_pair().report_json
        self.assertNotIn(b"private/",raw)
        self.assertNotIn(b"D:\\",raw)
        self.assertNotIn(b"audio/sample",raw)

    def test_explicit_job_writes_three_files(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            pair=_pair()
            names=write_ab_previews(root,"TEST_A_B",pair)
            self.assertEqual(tuple(p.name for p in names),
                             ("preview_A.wav","preview_B.wav","preview_AB_report.json"))
            self.assertEqual(tuple(p.read_bytes() for p in names),
                             (pair.wav_a,pair.wav_b,pair.report_json))
            result=verify_ab_previews(root,"TEST_A_B")
            self.assertEqual(result["A_wav_sha256"],sha256(pair.wav_a).hexdigest())

    def test_second_job_identical_bytes(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            pair=_pair()
            first=write_ab_previews(root,"one",pair)
            second=write_ab_previews(root,"two",pair)
            self.assertEqual(tuple(p.read_bytes() for p in first),tuple(p.read_bytes() for p in second))

    def test_no_overwrite_existing_job(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            p=_pair()
            files=write_ab_previews(root,"job",p)
            before=tuple(x.read_bytes() for x in files)
            with self.assertRaises(FileExistsError):
                write_ab_previews(root,"job",p)
            self.assertEqual(before,tuple(x.read_bytes() for x in files))

    def test_existing_unknown_job_not_mutated(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            job=root/"runs"/"job"
            job.mkdir()
            (job/"keep.txt").write_text("KEEP")
            with self.assertRaises(FileExistsError):
                write_ab_previews(root,"job",_pair())
            self.assertEqual((job/"keep.txt").read_text(),"KEEP")

    def test_reject_job_path_traversal(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            for job in ("../bad",".hidden","bad space","bad/file","é", ""):
                with self.subTest(job=job),self.assertRaises(PreviewError):
                    write_ab_previews(root,job,_pair())
            self.assertEqual(list((root/"runs").iterdir()),[])

    def test_root_gitignore_required(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            (root/".gitignore").write_text("/private/\n")
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job",_pair())

    def test_reject_runs_symlink(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            (root/"runs").rmdir()
            other=root/"other";other.mkdir()
            try:
                (root/"runs").symlink_to(other,target_is_directory=True)
            except (OSError,NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job",_pair())
            self.assertEqual(list(other.iterdir()),[])

    def test_reject_job_symlink(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            other=root/"outside";other.mkdir()
            try:
                (root/"runs"/"job").symlink_to(other,target_is_directory=True)
            except (OSError,NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(FileExistsError):
                write_ab_previews(root,"job",_pair())
            self.assertEqual(list(other.iterdir()),[])

    def test_mutated_wav_fails_verify(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            a,b,j=write_ab_previews(root,"job",_pair())
            a.write_bytes(a.read_bytes()[:-1]+b"\x00")
            with self.assertRaises(PreviewError):
                verify_ab_previews(root,"job")

    def test_mutated_json_fails_verify(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            a,b,j=write_ab_previews(root,"job",_pair())
            j.write_bytes(j.read_bytes()+b"garbage")
            with self.assertRaises(PreviewError):
                verify_ab_previews(root,"job")

    def test_output_symlink_rejected_verify(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            a,b,j=write_ab_previews(root,"job",_pair())
            elsewhere=root/"outside"; elsewhere.write_bytes(a.read_bytes())
            a.unlink()
            try:
                a.symlink_to(elsewhere)
            except (OSError,NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(PreviewError):
                verify_ab_previews(root,"job")

    def test_json_tampering_rejected_before_write(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            pair=_pair()
            bad=replace(pair,report_json=pair.report_json+b"bad")
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job",bad)
            self.assertEqual(list((root/"runs").iterdir()),[])

    def test_invalid_report_sections_rejected(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            pair=_pair()
            report=json.loads(pair.report_json)
            report["A"] = []
            forged=replace(pair,report_json=(json.dumps(report,sort_keys=True,
                  ensure_ascii=True,separators=(",", ":"))+"\n").encode())
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job",forged)
            self.assertEqual(list((root/"runs").iterdir()),[])

    def test_reject_malformed_pcm_even_with_recomputed_hash(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            pair=_pair()
            broken=bytearray(pair.wav_a)
            broken[20:22]=b"\x03\x00"  # fake IEEE float rather than PCM
            report=json.loads(pair.report_json)
            report["A"]["wav_sha256"]=sha256(broken).hexdigest()
            forged=replace(pair,wav_a=bytes(broken),report_json=(json.dumps(
                report,sort_keys=True,ensure_ascii=True,
                separators=(",", ":"))+"\n").encode())
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job",forged)

    def test_wav_tampering_rejected_before_write(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            pair=_pair()
            bad=replace(pair,wav_b=pair.wav_b[:-1]+b"\x00")
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job",bad)
            self.assertEqual(list((root/"runs").iterdir()),[])

    def test_wrong_pair_type(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            with self.assertRaises(PreviewError):
                write_ab_previews(root,"job","not a pair")

    def test_missing_or_symlink_job_verify(self):
        with TemporaryDirectory() as tmp:
            root=_workspace(Path(tmp))
            with self.assertRaises(PreviewError):
                verify_ab_previews(root,"missing")

    def test_report_similarity_same_bundle_near_one(self):
        a=_bundle("all_same")
        p=_pair(a,a)
        d=json.loads(p.report_json)
        self.assertAlmostEqual(d["comparison"]["cosine_similarity"],1.,places=12)
