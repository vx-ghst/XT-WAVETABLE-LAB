"""M3.3 CLI full offline synthetic M2.8 -> M3.2 A/B tests.

No real audio, ROM, dump or MIDI data. All workspaces are temporary.
"""
from __future__ import annotations

from argparse import Namespace
import contextlib
from dataclasses import replace
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from xtwavetable.cli.convert import CLIError, run_convert
from xtwavetable.cli.preview_ab import (
    PreviewCLIError, _job, load_m2_export, make_parser, main, run_compare, run_verify,
)
from xtwavetable.preview.oscillator import PreviewError
from xtwavetable.preview.compare import compare_bundle_previews
from tests.integration.test_m2_pipeline import synthetic_backup, wav_fixture


class PreviewABCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = synthetic_backup()
        cls.wav = wav_fixture(frames=12000)

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs').mkdir()
        (self.root / 'docs' / 'ARCHITECTURE.md').write_text('synthetic fixture', encoding='utf-8')
        (self.root / '.gitignore').write_text('/private/\n/runs/\n', encoding='utf-8')
        (self.root / 'private').mkdir()
        (self.root / 'runs').mkdir()
        (self.root / 'private' / 'source.wav').write_bytes(self.wav)
        (self.root / 'private' / 'snapshot.syx').write_bytes(self.snapshot)

    def _m2(self, name, pitch=220.0):
        args = Namespace(root=str(self.root), wav='private/source.wav',
            snapshot='private/snapshot.syx', job=name,
            wave_ids=(1200,1201), approve_wave_ids=(1200,1201),
            table_id=96, authorize_table_replacement=True,
            acknowledge_cross_table_references=False, device_id=127,
            start_frame=0, end_frame=None, channel_mode='preserve', channel=0,
            remove_dc=False, normalize_peak_dbfs=None, pitch_hz=pitch,
            analysis_max_windows=12, candidate_count=3,
            extraction_method='uniform', normalize_cycle_peak=False,
            requested_waves=2, selection_strategy='uniform',
            shortfall='reuse', max_projection_rms_error=None)
        return run_convert(args)

    def _sources(self):
        self._m2('sourceA')
        self._m2('sourceB', 330.0)

    def args(self, **kwargs):
        data = dict(root=str(self.root), job='previewAB', source_a='sourceA',
                    source_b='sourceB', sample_rate=48000,
                    frequency_hz=220.0, duration_seconds=0.005,
                    start_position=0.0, end_position=60.0,
                    table_interpolation='linear', phase_interpolation='linear',
                    amplitude=0.8, initial_phase=0.0,
                    jump_threshold=0.5, cancellation_threshold=0.5)
        data.update(kwargs)
        return Namespace(**data)

    def _compare(self, **kwargs):
        self._sources()
        return run_compare(self.args(**kwargs))

    def _files(self, job='previewAB'):
        return tuple(sorted((self.root/'runs'/job).iterdir()))

    def test_two_existing_m2_jobs_produce_three_files(self):
        result = self._compare()
        self.assertEqual(result['job'], 'previewAB')
        self.assertTrue(result['same_source_snapshot'])
        self.assertEqual(result['frames'],240)
        self.assertEqual([p.name for p in self._files()],
                         ['preview_A.wav','preview_AB_report.json','preview_B.wav'])

    def test_synthetic_audio_valid_mono_pcm16(self):
        self._compare()
        for name in ('preview_A.wav','preview_B.wav'):
            with wave.open(str(self.root/'runs/previewAB'/name),'rb') as audio:
                self.assertEqual(audio.getnchannels(),1)
                self.assertEqual(audio.getsampwidth(),2)
                self.assertEqual(audio.getframerate(),48000)
                self.assertEqual(audio.getnframes(),240)

    def test_individual_m2_export_can_be_loaded(self):
        self._sources()
        bundle=load_m2_export(self.root,'sourceA')
        self.assertEqual(bundle.table_id,96)
        self.assertEqual(bundle.wave_ids,(1200,1201))
        self.assertEqual(bundle.source_dump_sha256,sha256(self.snapshot).hexdigest())
        self.assertEqual(len(bundle.sysex),2*137+265)

    def test_loaded_bundles_match_direct_compare(self):
        self._sources()
        a=load_m2_export(self.root,'sourceA')
        b=load_m2_export(self.root,'sourceB')
        direct=compare_bundle_previews(a,b,duration_seconds=0.005)
        run_compare(self.args())
        self.assertEqual((self.root/'runs/previewAB/preview_A.wav').read_bytes(),direct.wav_a)
        self.assertEqual((self.root/'runs/previewAB/preview_B.wav').read_bytes(),direct.wav_b)
        self.assertEqual((self.root/'runs/previewAB/preview_AB_report.json').read_bytes(),direct.report_json)

    def test_different_pitch_can_generate_different_audio(self):
        self._compare()
        self.assertNotEqual((self.root/'runs/previewAB/preview_A.wav').read_bytes(),
                            (self.root/'runs/previewAB/preview_B.wav').read_bytes())

    def test_report_no_auto_winner(self):
        self._compare()
        report=json.loads((self.root/'runs/previewAB/preview_AB_report.json').read_bytes())
        self.assertIsNone(report['comparison']['winner'])
        self.assertTrue(report['offline_only'])
        self.assertFalse(report['hardware_upload_authorized'])
        self.assertEqual(len(report['A']['transitions']),60)

    def test_verify_existing_readonly(self):
        self._compare()
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self._files()}
        result=run_verify(Namespace(root=str(self.root),job='previewAB'))
        after={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self._files()}
        self.assertEqual(before,after)
        self.assertEqual(result['job'],'previewAB')

    def test_repeated_job_refuses_overwrite(self):
        self._compare()
        before={p.name:p.read_bytes() for p in self._files()}
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self._files()})

    def test_second_new_job_bit_identical(self):
        self._compare()
        run_compare(self.args(job='again'))
        for name in ('preview_A.wav','preview_B.wav','preview_AB_report.json'):
            self.assertEqual((self.root/'runs/previewAB'/name).read_bytes(),
                             (self.root/'runs/again'/name).read_bytes())

    def test_no_mutation_of_m2_source_jobs(self):
        self._sources()
        before={str(p):p.read_bytes() for job in ('sourceA','sourceB')
                for p in (self.root/'runs'/job).iterdir()}
        run_compare(self.args())
        self.assertEqual(before,{str(p):p.read_bytes() for job in ('sourceA','sourceB')
                for p in (self.root/'runs'/job).iterdir()})

    def test_same_source_job_is_allowed_control(self):
        self._sources()
        result=run_compare(self.args(source_b='sourceA'))
        self.assertTrue(result['same_pcm16_wav'])

    def test_output_same_as_source_job_rejected(self):
        self._sources()
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args(job='sourceA'))
        self.assertFalse((self.root/'runs/sourceA/preview_A.wav').exists())

    def test_invalid_job_names_programmatic_rejected(self):
        self._sources()
        for bad in ('../bad','bad/name','bad space','à','', '.hidden'):
            with self.subTest(bad=bad),self.assertRaises(PreviewCLIError):
                run_compare(self.args(job=bad))
        self.assertEqual(sorted(p.name for p in (self.root/'runs').iterdir()),['sourceA','sourceB'])

    def test_missing_source_job_rejected_before_write(self):
        self._m2('sourceA')
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_missing_source_export_json_rejected(self):
        self._sources()
        (self.root/'runs/sourceA/xt_candidate.json').unlink()
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_modified_source_sysex_rejected(self):
        self._sources()
        f=self.root/'runs/sourceA/xt_candidate.syx'
        data=f.read_bytes();f.write_bytes(data[:-1]+b'\x00')
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_modified_source_audit_rejected(self):
        self._sources()
        f=self.root/'runs/sourceA/xt_audit.json'
        f.write_bytes(f.read_bytes()+b'bad')
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_manifest_editable_mapping_mismatch_rejected(self):
        self._sources()
        f=self.root/'runs/sourceA/xt_candidate.json'
        payload=json.loads(f.read_bytes());payload['editable_wave_indices']=[0]*61
        f.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaises(PreviewCLIError):
            load_m2_export(self.root,'sourceA')

    def test_reserved_refs_mismatch_rejected(self):
        self._sources()
        f=self.root/'runs/sourceA/xt_candidate.json'
        payload=json.loads(f.read_bytes());payload['reserved_table_references_preserved']=[1,2,3]
        f.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaises(PreviewCLIError):
            load_m2_export(self.root,'sourceA')

    def test_mixed_snapshot_blocked(self):
        self._sources()
        f=self.root/'runs/sourceB/xt_candidate.json'
        payload=json.loads(f.read_bytes());payload['source_snapshot_sha256']='0'*64
        f.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_render_invalid_rate_fail_before_write(self):
        self._sources()
        with self.assertRaises(PreviewError):
            run_compare(self.args(sample_rate=1))
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_render_invalid_interp_fail_before_write(self):
        self._sources()
        with self.assertRaises(PreviewError):
            run_compare(self.args(table_interpolation='wrong'))
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_modify_preview_wav_detected(self):
        self._compare()
        f=self.root/'runs/previewAB/preview_B.wav'
        b=f.read_bytes();f.write_bytes(b[:-1]+b'\x01')
        with self.assertRaises(PreviewError):
            run_verify(Namespace(root=str(self.root),job='previewAB'))

    def test_verify_missing_preview_report_rejected(self):
        self._compare()
        (self.root/'runs/previewAB/preview_AB_report.json').unlink()
        with self.assertRaises(PreviewError):
            run_verify(Namespace(root=str(self.root),job='previewAB'))

    def test_no_private_path_in_cli_error(self):
        buf=io.StringIO()
        with contextlib.redirect_stderr(buf):
            result=main(['compare','--root',str(self.root),'--job','previewAB',
                        '--source-a','sourceA','--source-b','sourceB'])
        self.assertEqual(result,2)
        self.assertNotIn(str(self.root),buf.getvalue())
        self.assertNotIn('private/',buf.getvalue())

    def test_main_verify_success(self):
        self._compare()
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            result=main(['verify','--root',str(self.root),'--job','previewAB'])
        self.assertEqual(result,0)
        self.assertIn('[PASS]',buf.getvalue())

    def test_main_compare_success(self):
        self._sources()
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            result=main(['compare','--root',str(self.root),'--job','previewAB',
                        '--source-a','sourceA','--source-b','sourceB',
                        '--duration-seconds','0.005'])
        self.assertEqual(result,0)
        self.assertEqual(len(self._files()),3)

    def test_help_documented_commands(self):
        parser=make_parser()
        self.assertIn('M3.3',parser.description)
        for action in ('compare','verify'):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    parser.parse_args([action,'--help'])
            self.assertEqual(caught.exception.code,0)

    def test_source_symlink_rejected(self):
        self._sources()
        orig=self.root/'runs/sourceA'
        other=self.root/'outside';orig.rename(other)
        try:
            orig.symlink_to(other,target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertFalse((self.root/'runs/previewAB').exists())

    def test_input_artifact_symlink_rejected(self):
        self._sources()
        f=self.root/'runs/sourceA/xt_candidate.json'
        other=self.root/'outside.json';other.write_bytes(f.read_bytes());f.unlink()
        try:
            f.symlink_to(other)
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())

    def test_missing_gitignore_gate(self):
        self._sources()
        (self.root/'.gitignore').write_text('/private/\n',encoding='utf-8')
        with self.assertRaises(CLIError):
            run_compare(self.args())

    def test_missing_m2_job_no_input_files_written(self):
        with self.assertRaises(PreviewCLIError):
            run_compare(self.args())
        self.assertEqual(tuple((self.root/'runs').iterdir()),())


if __name__=='__main__':
    unittest.main()
