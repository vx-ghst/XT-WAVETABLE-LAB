"""M2.8 offline CLI tests: entirely synthetic, private temporary workspace.

Never load user ROMs, MIDI devices, private WAV or proprietary hardware data.
"""
from __future__ import annotations

from argparse import Namespace
import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from xtwavetable.cli.convert import (CLIError, _ids, _job, make_parser, main,
                                      run_convert, run_verify)
from tests.integration.test_m2_pipeline import synthetic_backup, wav_fixture


class OfflineCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wav = wav_fixture(frames=12000)
        cls.snapshot = synthetic_backup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs').mkdir()
        (self.root / 'docs/ARCHITECTURE.md').write_text('synthetic fixture', encoding='utf-8')
        (self.root / '.gitignore').write_text('/private/\n/runs/\n', encoding='utf-8')
        (self.root / 'private').mkdir()
        (self.root / 'runs').mkdir()
        (self.root / 'private/source.wav').write_bytes(self.wav)
        (self.root / 'private/snapshot.syx').write_bytes(self.snapshot)
        self.source_hash = sha256(self.wav).hexdigest()
        self.snapshot_hash = sha256(self.snapshot).hexdigest()

    def args(self, **changes):
        base = dict(root=str(self.root), wav='private/source.wav',
                    snapshot='private/snapshot.syx', job='demo',
                    wave_ids=(1200,1201), approve_wave_ids=(1200,1201),
                    table_id=96, authorize_table_replacement=True,
                    acknowledge_cross_table_references=False, device_id=127,
                    start_frame=0, end_frame=None, channel_mode='preserve', channel=0,
                    remove_dc=False, normalize_peak_dbfs=None, pitch_hz=220.0,
                    analysis_max_windows=12, candidate_count=3,
                    extraction_method='uniform', normalize_cycle_peak=False,
                    requested_waves=2, selection_strategy='uniform',
                    shortfall='reuse', max_projection_rms_error=None)
        base.update(changes)
        return Namespace(**base)

    def _convert(self, **kwargs):
        return run_convert(self.args(**kwargs))

    def _all_outputs(self, job='demo'):
        return sorted(p.name for p in (self.root/'runs'/job).iterdir())

    def test_success_four_private_artifacts(self):
        r = self._convert()
        self.assertEqual(r['waves'], 2)
        self.assertEqual(r['job'], 'demo')
        self.assertEqual(self._all_outputs(), ['xt_audit.json','xt_candidate.json',
                                               'xt_candidate.syx','xt_pipeline.json'])

    def test_source_bytes_unchanged(self):
        self._convert()
        self.assertEqual((self.root/'private/source.wav').read_bytes(),self.wav)
        self.assertEqual((self.root/'private/snapshot.syx').read_bytes(),self.snapshot)

    def test_hashes_and_private_provenance(self):
        self._convert()
        job = self.root/'runs/demo'
        audit = json.loads((job/'xt_audit.json').read_bytes())
        pipeline = json.loads((job/'xt_pipeline.json').read_bytes())
        export = json.loads((job/'xt_candidate.json').read_bytes())
        self.assertEqual(audit['source_wav_sha256'],self.source_hash)
        self.assertEqual(pipeline['source_wav_sha256'],self.source_hash)
        self.assertEqual(export['source_snapshot_sha256'],self.snapshot_hash)
        self.assertEqual(audit['reproducibility'],'PASS_TWO_INDEPENDENT_CONVERSIONS')
        self.assertFalse(audit['hardware_upload_authorized'])
        for f in job.iterdir():
            self.assertNotIn(str(self.root),f.read_bytes().decode('latin-1'))

    def test_verify_existing_without_modifying(self):
        self._convert()
        root=self.root/'runs/demo'
        before={p.name: (p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
        result=run_verify(Namespace(root=str(self.root),job='demo'))
        after={p.name: (p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(result['waves'],2)

    def test_repeated_job_refuses_overwrite_without_mutating(self):
        self._convert()
        before={p.name:p.read_bytes() for p in (self.root/'runs/demo').iterdir()}
        with self.assertRaises(FileExistsError):self._convert()
        after={p.name:p.read_bytes() for p in (self.root/'runs/demo').iterdir()}
        self.assertEqual(before,after)

    def test_new_job_same_bit_identical_artifacts(self):
        self._convert()
        self._convert(job='demo2')
        for f in ('xt_candidate.syx','xt_candidate.json','xt_pipeline.json','xt_audit.json'):
            self.assertEqual((self.root/'runs/demo'/f).read_bytes(),
                             (self.root/'runs/demo2'/f).read_bytes())

    def test_missing_wave_approval_fail_closed_before_writes(self):
        with self.assertRaisesRegex(ValueError,'authorization'):
            self._convert(approve_wave_ids=())
        self.assertEqual(list((self.root/'runs').iterdir()),[])

    def test_missing_table_approval_fail_closed_before_writes(self):
        with self.assertRaisesRegex(ValueError,'authorization'):
            self._convert(authorize_table_replacement=False)
        self.assertEqual(list((self.root/'runs').iterdir()),[])

    def test_invalid_ids_fail_closed(self):
        for ids in ((1000,),(1200,1200),(1200,1201,1202)):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                self._convert(wave_ids=ids)
        self.assertFalse(list((self.root/'runs').iterdir()))

    def test_snapshot_corrupt_fail_closed(self):
        (self.root/'private/snapshot.syx').write_bytes(b'bad')
        with self.assertRaises(ValueError):self._convert()
        self.assertFalse(list((self.root/'runs').iterdir()))

    def test_bad_wav_fail_closed(self):
        (self.root/'private/source.wav').write_bytes(b'bad')
        with self.assertRaises(ValueError):self._convert()
        self.assertFalse(list((self.root/'runs').iterdir()))

    def test_outside_input_rejected(self):
        (self.root/'outsider.wav').write_bytes(self.wav)
        with self.assertRaises(CLIError):self._convert(wav='outsider.wav')
        self.assertFalse(list((self.root/'runs').iterdir()))

    def test_symlink_escape_rejected(self):
        link=self.root/'private/link.wav'
        try:link.symlink_to(self.root/'private/source.wav')
        except OSError:self.skipTest('symlink creation unavailable')
        with self.assertRaises(CLIError):self._convert(wav='private/link.wav')
        self.assertFalse(list((self.root/'runs').iterdir()))

    def test_nested_symlink_inside_private_rejected(self):
        inside = self.root/'private/audio'
        inside.mkdir()
        (inside/'input.wav').write_bytes(self.wav)
        link = self.root/'private/shortcut'
        try: link.symlink_to(inside, target_is_directory=True)
        except OSError: self.skipTest('symlink creation unavailable')
        with self.assertRaises(CLIError):
            self._convert(wav='private/shortcut/input.wav')

    def test_symlink_runs_rejected(self):
        (self.root/'runs').rmdir()
        real=self.root/'real'
        real.mkdir()
        try:(self.root/'runs').symlink_to(real, target_is_directory=True)
        except OSError:self.skipTest('symlink creation unavailable')
        with self.assertRaises(CLIError):self._convert()

    def test_gitignore_safety_required(self):
        (self.root/'.gitignore').write_text('/private/\n',encoding='utf-8')
        with self.assertRaises(CLIError):self._convert()

    def test_oversize_wav_rejected(self):
        with (self.root/'private/source.wav').open('ab') as f:
            f.truncate(64*1024*1024+1)
        with self.assertRaises(CLIError):self._convert()
        self.assertFalse(list((self.root/'runs').iterdir()))

    def test_no_success_when_tampered_syx(self):
        self._convert()
        p=self.root/'runs/demo/xt_candidate.syx'
        data=bytearray(p.read_bytes());data[10] ^= 1;p.write_bytes(data)
        with self.assertRaises(CLIError):run_verify(Namespace(root=str(self.root),job='demo'))

    def test_no_success_when_tampered_pipeline(self):
        self._convert()
        p=self.root/'runs/demo/xt_pipeline.json'
        data=json.loads(p.read_bytes());data['source_wav_sha256']='bad';p.write_text(json.dumps(data))
        with self.assertRaises(CLIError):run_verify(Namespace(root=str(self.root),job='demo'))

    def test_no_success_when_tampered_export(self):
        self._convert()
        p=self.root/'runs/demo/xt_candidate.json'
        data=json.loads(p.read_bytes());data['wave_ids']=[1200,1202];p.write_text(json.dumps(data))
        with self.assertRaises(CLIError):run_verify(Namespace(root=str(self.root),job='demo'))

    def test_no_success_when_tampered_audit(self):
        self._convert()
        p=self.root/'runs/demo/xt_audit.json'
        data=json.loads(p.read_bytes());data['offline_only']=False;p.write_text(json.dumps(data))
        with self.assertRaises(CLIError):run_verify(Namespace(root=str(self.root),job='demo'))

    def test_programmatic_job_path_traversal_rejected(self):
        with self.assertRaises(CLIError): self._convert(job='../escapes')
        with self.assertRaises(CLIError):
            run_verify(Namespace(root=str(self.root), job='../../bad'))
        self.assertFalse((self.root/'escapes').exists())

    def test_job_names_strict(self):
        for name in ('../oops','.hidden','bad/name','space name','é','a'*65):
            with self.subTest(name=name),self.assertRaises(Exception):_job(name)
        for name in ('a','abc-123','TEST_1','a'*64):self.assertEqual(_job(name),name)

    def test_id_parser(self):
        self.assertEqual(_ids('1000,1001'),(1000,1001))
        for data in ('','1,','1,,2','1-3','1,1','1.2','é','-1'):
            with self.subTest(data=data),self.assertRaises(Exception):_ids(data)

    def test_parser_defaults_fail_closed(self):
        parser=make_parser()
        p=parser.parse_args(['convert','--wav','a','--snapshot','b','--job','j','--wave-ids','1200',
                             '--approve-wave-ids','1200','--table-id','96'])
        self.assertFalse(p.authorize_table_replacement)
        self.assertEqual(p.shortfall,'reject')
        self.assertEqual(p.channel_mode,'preserve')

    def test_cli_main_prints_no_private_paths(self):
        args=['convert','--root',str(self.root),'--job','demo',
              '--wav','private/source.wav','--snapshot','private/snapshot.syx',
              '--pitch-hz','220','--candidate-count','3','--requested-waves','2',
              '--shortfall','reuse','--wave-ids','1200,1201',
              '--approve-wave-ids','1200,1201','--table-id','96',
              '--authorize-table-replacement']
        stdout=io.StringIO();stderr=io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            rc=main(args)
        self.assertEqual(rc,0,stderr.getvalue())
        self.assertIn('[PASS]',stdout.getvalue())
        self.assertNotIn(str(self.root),stdout.getvalue())
        self.assertEqual(stderr.getvalue(),'')
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            rc2=main(['verify','--root',str(self.root),'--job','demo'])
        self.assertEqual(rc2,0)

    def test_auto_pitch_synthetic_tonal(self):
        self._convert(pitch_hz=None, requested_waves=1, wave_ids=(1200,),
                      approve_wave_ids=(1200,), candidate_count=2)
        self.assertTrue((self.root/'runs/demo/xt_candidate.syx').exists())

    def test_no_hidden_cross_reference_ack(self):
        (self.root/'private/snapshot.syx').write_bytes(synthetic_backup(cross_table_reference=True))
        with self.assertRaisesRegex(ValueError,'other tables'):
            self._convert()
        self.assertFalse(list((self.root/'runs').iterdir()))
        self._convert(acknowledge_cross_table_references=True)

    def test_job_symlink_guard(self):
        self._convert()
        with tempfile.TemporaryDirectory() as temp:
            (self.root/'runs/demo/xt_candidate.json').unlink()
            try:(self.root/'runs/demo/xt_candidate.json').symlink_to(Path(temp)/'other')
            except OSError:self.skipTest('symlink creation unavailable')
            with self.assertRaises(CLIError):run_verify(Namespace(root=str(self.root),job='demo'))


if __name__ == '__main__':
    unittest.main()
