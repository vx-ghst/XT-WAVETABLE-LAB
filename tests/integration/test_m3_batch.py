"""M3.4 synthetic-only offline batch QA regressions; no real dump/WAV used."""
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

from xtwavetable.cli.convert import run_convert
from xtwavetable.cli.preview_ab import load_m2_export
from xtwavetable.cli.preview_batch import (
    BatchCLIError, make_parser, main, run_batch, run_verify,
)
from xtwavetable.preview.batch import (
    BatchPreview, analyze_batch_previews, verify_batch_previews, write_batch_previews,
    _verify_payloads, _canonical,
)
from xtwavetable.preview.oscillator import PreviewError
from tests.integration.test_m2_pipeline import synthetic_backup, wav_fixture


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = synthetic_backup()
        cls.wav = wav_fixture(frames=12000)

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'docs').mkdir()
        (self.root/'docs'/'ARCHITECTURE.md').write_text('synthetic',encoding='utf-8')
        (self.root/'.gitignore').write_text('/private/\n/runs/\n',encoding='utf-8')
        (self.root/'private').mkdir()
        (self.root/'runs').mkdir()
        (self.root/'private'/'s.wav').write_bytes(self.wav)
        (self.root/'private'/'backup.syx').write_bytes(self.snapshot)

    def _source(self, name, pitch=220.0):
        options = dict(root=str(self.root),wav='private/s.wav',
            snapshot='private/backup.syx',job=name,
            wave_ids=(1200,1201),approve_wave_ids=(1200,1201),
            table_id=96,authorize_table_replacement=True,
            acknowledge_cross_table_references=False,device_id=127,
            start_frame=0,end_frame=None,channel_mode='preserve',channel=0,
            remove_dc=False,normalize_peak_dbfs=None,pitch_hz=pitch,
            analysis_max_windows=12,candidate_count=3,
            extraction_method='uniform',normalize_cycle_peak=False,
            requested_waves=2,selection_strategy='uniform',
            shortfall='reuse',max_projection_rms_error=None)
        run_convert(Namespace(**options))

    def _sources(self, count=3):
        names = ('first','second','third','fourth','fifth','sixth')[:count]
        for n,name in enumerate(names):
            self._source(name,220.0+n*35)
        return names

    def _args(self, **kwargs):
        data=dict(root=str(self.root),job='batchQA',sources=('first','second','third'),
                  sample_rate=48000,frequency_hz=220.0,duration_seconds=0.005,
                  start_position=0.0,end_position=60.0,
                  table_interpolation='linear',phase_interpolation='linear',
                  amplitude=0.8,initial_phase=0.0,
                  jump_threshold=0.5,cancellation_threshold=0.5)
        data.update(kwargs)
        return Namespace(**data)

    def _run(self,n=3,**kwargs):
        self._sources(n)
        return run_batch(self._args(sources=('first','second','third','fourth','fifth','sixth')[:n],**kwargs))

    def _read(self, filename):
        return (self.root/'runs'/'batchQA'/filename).read_bytes()

    def test_three_candidates_three_pairs_and_five_files(self):
        result=self._run()
        self.assertEqual(result['candidates'],3)
        self.assertEqual(result['pairs'],3)
        self.assertEqual(sorted(p.name for p in (self.root/'runs'/'batchQA').iterdir()),
            ['batch_audit.json','batch_report.json','preview_C01.wav','preview_C02.wav','preview_C03.wav'])

    def test_two_candidates_one_pair(self):
        result=self._run(n=2)
        self.assertEqual((result['candidates'],result['pairs']),(2,1))

    def test_six_candidates_fifteen_pairs(self):
        result=self._run(n=6)
        self.assertEqual((result['candidates'],result['pairs']),(6,15))

    def test_report_no_winner_no_hardware(self):
        self._run()
        report=json.loads(self._read('batch_report.json'))
        self.assertTrue(report['offline_only'])
        self.assertFalse(report['hardware_upload_authorized'])
        self.assertIsNone(report['winner'])
        self.assertTrue(all(row['winner'] is None for row in report['pairwise']))
        self.assertEqual(len(report['candidates'][1]['transitions']),60)

    def test_pair_order_and_canonical_report(self):
        self._run()
        raw=self._read('batch_report.json')
        self.assertEqual(raw,_canonical(json.loads(raw)))
        pairs=json.loads(raw)['pairwise']
        self.assertEqual([(p['A'],p['B']) for p in pairs],
                         [('C01','C02'),('C01','C03'),('C02','C03')])

    def test_synthetic_wav_formats(self):
        self._run()
        for i in range(1,4):
            with wave.open(str(self.root/'runs'/'batchQA'/f'preview_C{i:02d}.wav'),'rb') as reader:
                self.assertEqual((reader.getnchannels(),reader.getsampwidth(),
                                  reader.getframerate(),reader.getnframes()),(1,2,48000,240))

    def test_provenance_and_audit_checksums(self):
        self._run()
        report=self._read('batch_report.json')
        audit=json.loads(self._read('batch_audit.json'))
        self.assertEqual(audit['batch_report_sha256'],sha256(report).hexdigest())
        self.assertEqual(json.loads(report)['source_snapshot_sha256'],sha256(self.snapshot).hexdigest())
        for i in range(1,4):
            name=f'preview_C{i:02d}.wav'
            self.assertEqual(audit['wav_sha256'][name],sha256(self._read(name)).hexdigest())

    def test_verify_readonly_and_no_source_mutation(self):
        self._sources()
        sources={str(p):(p.read_bytes(),p.stat().st_mtime_ns)
                 for name in ('first','second','third') for p in (self.root/'runs'/name).iterdir()}
        run_batch(self._args())
        before={str(p):(p.read_bytes(),p.stat().st_mtime_ns)
                for p in (self.root/'runs'/'batchQA').iterdir()}
        result=run_verify(Namespace(root=str(self.root),job='batchQA'))
        self.assertEqual(result['pairs'],3)
        self.assertEqual(before,{str(p):(p.read_bytes(),p.stat().st_mtime_ns)
                                  for p in (self.root/'runs'/'batchQA').iterdir()})
        self.assertEqual(sources,{str(p):(p.read_bytes(),p.stat().st_mtime_ns)
                                  for name in ('first','second','third')
                                  for p in (self.root/'runs'/name).iterdir()})

    def test_second_run_bit_identical_different_output_job(self):
        self._run()
        run_batch(self._args(job='batchAgain'))
        names=(p.name for p in (self.root/'runs'/'batchQA').iterdir())
        self.assertTrue(all(self._read(name)==(self.root/'runs'/'batchAgain'/name).read_bytes()
                            for name in names))

    def test_explicit_replacement_refused(self):
        self._run()
        before={p.name:p.read_bytes() for p in (self.root/'runs'/'batchQA').iterdir()}
        with self.assertRaises(BatchCLIError):
            run_batch(self._args())
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'runs'/'batchQA').iterdir()})

    def test_source_is_not_output_job(self):
        self._sources()
        with self.assertRaises(BatchCLIError):
            run_batch(self._args(job='first'))

    def test_duplicate_sources_rejected(self):
        self._source('first')
        with self.assertRaises(BatchCLIError):
            run_batch(self._args(sources=('first','first')))
        self.assertFalse((self.root/'runs'/'batchQA').exists())

    def test_one_or_seven_sources_rejected(self):
        for names in (('first',),tuple(f'x{i}' for i in range(7))):
            with self.subTest(names=names),self.assertRaises(BatchCLIError):
                run_batch(self._args(sources=names))

    def test_invalid_sources_type(self):
        for sources in (None,'first,second',{},()):
            with self.subTest(sources=sources),self.assertRaises(BatchCLIError):
                run_batch(self._args(sources=sources))

    def test_job_traversal_and_unicode_rejected(self):
        for job in ('../attack','a/b','é','', '.hidden','a'*65):
            with self.subTest(job=job),self.assertRaises(BatchCLIError):
                run_batch(self._args(job=job))

    def test_missing_job_rejected(self):
        self._source('first')
        with self.assertRaises(Exception):
            run_batch(self._args(sources=('first','missing')))
        self.assertFalse((self.root/'runs'/'batchQA').exists())

    def test_modified_m2_source_rejected_before_output(self):
        self._sources()
        f=self.root/'runs'/'second'/'xt_candidate.syx'
        data=f.read_bytes()
        f.write_bytes(data[:-1]+b'\x00')
        with self.assertRaises(Exception):
            run_batch(self._args())
        self.assertFalse((self.root/'runs'/'batchQA').exists())

    def test_modified_m2_audit_rejected(self):
        self._sources()
        (self.root/'runs'/'second'/'xt_audit.json').write_bytes(b'{}')
        with self.assertRaises(Exception):
            run_batch(self._args())

    def test_wrong_backup_rejected_in_memory(self):
        self._sources()
        inputs=[load_m2_export(self.root,j) for j in ('first','second')]
        wrong=replace(inputs[1],source_dump_sha256='0'*64)
        with self.assertRaises(PreviewError):
            analyze_batch_previews((inputs[0],wrong),duration_seconds=0.005)

    def test_manifest_backup_mismatch_rejected(self):
        self._sources()
        inputs=[load_m2_export(self.root,j) for j in ('first','second')]
        meta=json.loads(inputs[1].manifest_json)
        meta['source_snapshot_sha256']='0'*64
        fake=replace(inputs[1],manifest_json=_canonical(meta))
        with self.assertRaises(PreviewError):
            analyze_batch_previews((inputs[0],fake),duration_seconds=0.005)

    def test_invalid_render_settings_rejected(self):
        self._sources(2)
        inputs=tuple(load_m2_export(self.root,j) for j in ('first','second'))
        cases=({'sample_rate':True},{'frequency_hz':0},
               {'duration_seconds':float('nan')},{'duration_seconds':10},
               {'start_position':-1},{'end_position':61},
               {'amplitude':0},{'table_interpolation':'unknown'},
               {'phase_interpolation':'unknown'}, {'initial_phase':2},
               {'jump_threshold':2.01},{'cancellation_threshold':-0.01})
        for options in cases:
            with self.subTest(options=options),self.assertRaises(PreviewError):
                analyze_batch_previews(inputs,**(dict(duration_seconds=0.005) | options))

    def test_valid_other_modes(self):
        result=self._run(n=2,table_interpolation='nearest',phase_interpolation='nearest',
                         sample_rate=44100,frequency_hz=330.0)
        self.assertEqual(result['pairs'],1)

    def test_pairwise_identity_control_no_winner(self):
        self._sources(2)
        same=load_m2_export(self.root,'first')
        batch=analyze_batch_previews((same,same),duration_seconds=0.005)
        pair=json.loads(batch.report_json)['pairwise'][0]
        self.assertTrue(pair['same_pcm16_wav'])
        self.assertEqual(pair['rms_sample_difference'],0)
        self.assertIsNone(pair['winner'])

    def test_order_changes_report_but_not_candidate_audio(self):
        self._sources(2)
        a=load_m2_export(self.root,'first')
        b=load_m2_export(self.root,'second')
        one=analyze_batch_previews((a,b),duration_seconds=0.005)
        two=analyze_batch_previews((b,a),duration_seconds=0.005)
        self.assertEqual(one.wav_files[0][1],two.wav_files[1][1])
        self.assertNotEqual(one.report_json,two.report_json)

    def test_invalid_payload_tampered_wav(self):
        self._run()
        f=self.root/'runs'/'batchQA'/'preview_C02.wav'
        p=bytearray(f.read_bytes());p[-1]^=1;f.write_bytes(p)
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_invalid_payload_tampered_report(self):
        self._run()
        f=self.root/'runs'/'batchQA'/'batch_report.json'
        f.write_bytes(f.read_bytes()+b'\n')
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_invalid_payload_tampered_audit(self):
        self._run()
        f=self.root/'runs'/'batchQA'/'batch_audit.json'
        f.write_bytes(f.read_bytes()+b'!')
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_symlinked_output_file_rejected(self):
        self._run()
        f=self.root/'runs'/'batchQA'/'preview_C02.wav'
        target=self.root/'runs'/'batchQA'/'preview_C01.wav'
        f.unlink()
        try:
            f.symlink_to(target)
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_symlinked_job_directory_rejected(self):
        self._run()
        link=self.root/'runs'/'batchLink'
        try:
            link.symlink_to(self.root/'runs'/'batchQA',target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchLink')

    def test_extra_file_rejected_by_verify(self):
        self._run()
        (self.root/'runs'/'batchQA'/'unauthorized').write_text('bad')
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_verify_output_job_invalid_name(self):
        with self.assertRaises(BatchCLIError):
            run_verify(Namespace(root=str(self.root),job='../bad'))

    def test_cli_help_has_batch_and_verify(self):
        parser=make_parser()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as caught:
                parser.parse_args(['--help'])
        self.assertEqual(caught.exception.code,0)
        self.assertIn('batch',out.getvalue())
        self.assertIn('verify',out.getvalue())

    def test_cli_fail_does_not_echo_private_path(self):
        self._sources(2)
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            result=main(['batch','--root',str(self.root),'--job','out',
                         '--sources','first','missing','--duration-seconds','0.005'])
        self.assertEqual(result,2)
        self.assertNotIn(str(self.root),errors.getvalue())
        self.assertIn('[FAIL]',errors.getvalue())

    def test_in_memory_is_readonly(self):
        self._sources(2)
        inputs=tuple(load_m2_export(self.root,j) for j in ('first','second'))
        before={p.name:p.read_bytes() for p in (self.root/'runs'/'first').iterdir()}
        result=analyze_batch_previews(inputs,duration_seconds=0.005)
        self.assertEqual(len(result.wav_files),2)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'runs'/'first').iterdir()})
        self.assertFalse((self.root/'runs'/'batchQA').exists())

    def test_reject_forged_wav_filename(self):
        self._sources(2)
        inputs=tuple(load_m2_export(self.root,j) for j in ('first','second'))
        result=analyze_batch_previews(inputs,duration_seconds=0.005)
        forged=replace(result,wav_files=(('../escape.wav',result.wav_files[0][1]),result.wav_files[1]))
        with self.assertRaises(PreviewError):
            _verify_payloads(forged)

    def test_report_missing_render_setting_rejected_cleanly(self):
        self._run(n=2)
        f=self.root/'runs'/'batchQA'/'batch_report.json'
        meta=json.loads(f.read_bytes())
        del meta['render_settings']['duration_seconds']
        f.write_bytes(_canonical(meta))
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_forged_transition_summary_rejected(self):
        self._run(n=2)
        f=self.root/'runs'/'batchQA'/'batch_report.json'
        meta=json.loads(f.read_bytes())
        meta['candidates'][0]['large_change_positions']=[99]
        f.write_bytes(_canonical(meta))
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_forged_pair_numeric_rejected(self):
        self._run(n=2)
        f=self.root/'runs'/'batchQA'/'batch_report.json'
        meta=json.loads(f.read_bytes())
        meta['pairwise'][0]['rms_sample_difference']=-7
        f.write_bytes(_canonical(meta))
        with self.assertRaises(PreviewError):
            verify_batch_previews(self.root,'batchQA')

    def test_cli_main_success_with_synthetic_sources(self):
        self._sources(2)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['batch','--root',str(self.root),'--job','batchQA',
                                   '--sources','first','second',
                                   '--duration-seconds','0.005']),0)
        self.assertIn('[PASS]',out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['verify','--root',str(self.root),'--job','batchQA']),0)
        self.assertIn('[PASS]',out.getvalue())

    def test_symlinked_source_job_rejected_before_output(self):
        self._source('first')
        link=self.root/'runs'/'alias'
        try:
            link.symlink_to(self.root/'runs'/'first',target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(Exception):
            run_batch(self._args(sources=('first','alias')))
        self.assertFalse((self.root/'runs'/'batchQA').exists())

    def test_reject_forged_report_winner(self):
        self._sources(2)
        inputs=tuple(load_m2_export(self.root,j) for j in ('first','second'))
        result=analyze_batch_previews(inputs,duration_seconds=0.005)
        meta=json.loads(result.report_json)
        meta['winner']='C01'
        forged=replace(result,report_json=_canonical(meta))
        with self.assertRaises(PreviewError):
            _verify_payloads(forged)


if __name__ == '__main__':
    unittest.main()
