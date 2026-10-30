"""M3.6 hardware/manual-derived profile labels; synthetic-only regressions."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import math
import unittest

from xtwavetable.preview.profiles import PROFILES, ProfileError, resolve_profile, validate_report_profile
from xtwavetable.preview.oscillator import render_preview
from xtwavetable.preview.compare import _canonical, _verify_payloads, compare_bundle_previews
from xtwavetable.preview.batch import analyze_batch_previews, _verify_payloads as verify_batch
from xtwavetable.cli.preview_ab import make_parser as make_ab_parser
from xtwavetable.cli.preview_batch import make_parser as make_batch_parser
from xtwavetable.model.wave import Wave
from xtwavetable.codec_xt.sysex import encode_wave_dump, decode_wave_dump, WAVE_DUMP_LENGTH
from tests.unit.test_preview_oscillator import setup_data
from tests.integration.test_m3_preview_ab import _bundle


class ProfileContractTests(unittest.TestCase):
    def test_exact_four_profiles(self):
        self.assertEqual(set(PROFILES), {
            'legacy-linear-approx','xt233-discrete-approx',
            'tallent-e352-approx','tallent-honda-approx'})

    def test_stock_table_axis_is_discrete_not_crossfade(self):
        table, waves = setup_data()
        a=render_preview(table,waves,duration_seconds=.01,
                         render_profile='xt233-discrete-approx')
        b=render_preview(table,waves,duration_seconds=.01,
                         table_interpolation='nearest',phase_interpolation='linear')
        self.assertEqual(a,b)
        self.assertEqual(a.table_interpolation,'nearest')

    def test_e352_equals_explicit_linear_linear_proxy(self):
        table,waves=setup_data()
        x=render_preview(table,waves,start_position=29.5,duration_seconds=.01,
                         render_profile='tallent-e352-approx')
        y=render_preview(table,waves,start_position=29.5,duration_seconds=.01,
                         table_interpolation='linear',phase_interpolation='linear')
        self.assertEqual(x.samples,y.samples)

    def test_honda_phase_is_nearest_proxy(self):
        table,waves=setup_data()
        x=render_preview(table,waves,duration_seconds=.01,render_profile='tallent-honda-approx')
        y=render_preview(table,waves,duration_seconds=.01,table_interpolation='linear',phase_interpolation='nearest')
        self.assertEqual(x,y)

    def test_legacy_default_keeps_original_preview(self):
        table,waves=setup_data()
        a=render_preview(table,waves,duration_seconds=.01)
        b=render_preview(table,waves,duration_seconds=.01,table_interpolation='linear',phase_interpolation='linear')
        self.assertEqual(a,b)

    def test_unknown_invalid_and_bool_profiles_fail_closed(self):
        for bad in ('XT233','xt233','',False,1,[],{}):
            with self.subTest(bad=repr(bad)), self.assertRaises(ProfileError):
                resolve_profile(bad)

    def test_explicit_mismatched_mode_fails_closed(self):
        for name,field in [('xt233-discrete-approx','table_interpolation'),
                           ('tallent-honda-approx','phase_interpolation')]:
            value='linear' if field=='table_interpolation' else 'linear'
            with self.subTest(name=name), self.assertRaises(ProfileError):
                resolve_profile(name,**{field:value})

    def test_nearest_stock_midpoint_not_claimed_exact(self):
        self.assertIn('NOT firmware-verified',PROFILES['xt233-discrete-approx'].table_position_claim)
        self.assertFalse(PROFILES['xt233-discrete-approx'].dsp_parity_certified)

    def test_sparse_table_generation_never_claimed(self):
        self.assertTrue(all(not p.sparse_table_interpolation_supported for p in PROFILES.values()))

    def test_all_hardware_parity_unverified(self):
        self.assertTrue(all(not p.dsp_parity_certified for p in PROFILES.values()))

    def test_profile_report_ab_sanitized_and_verified(self):
        a,b=_bundle('harmonic'),_bundle('negative')
        out=compare_bundle_previews(a,b,duration_seconds=.01,render_profile='xt233-discrete-approx')
        report=json.loads(out.report_json)
        self.assertEqual(report['render_settings']['table_interpolation'],'nearest')
        self.assertFalse(report['render_profile']['crossfade_midpoint_applicable'])
        self.assertIn('COUNTERFACTUAL ONLY',str(report['limitations']))
        self.assertEqual(report["A"]["possible_cancellation_positions"],[])
        self.assertTrue(all(t["crossfade_midpoint_rms_ratio"] is None and
                            not t["possible_midpoint_cancellation"] for t in report["A"]["transitions"]))
        self.assertEqual(_verify_payloads(out.wav_a,out.wav_b,out.report_json),report)

    def test_profile_report_e352_true_cancellation_applicability(self):
        out=compare_bundle_previews(_bundle('harmonic'),_bundle('negative'),
                                    duration_seconds=.005,render_profile='tallent-e352-approx')
        report=json.loads(out.report_json)
        self.assertTrue(report['render_profile']['crossfade_midpoint_applicable'])
        self.assertEqual(report['render_settings']['phase_interpolation'],'linear')

    def test_profile_report_rejects_altered_claim(self):
        out=compare_bundle_previews(_bundle(),_bundle(),duration_seconds=.005,
                                    render_profile='xt233-discrete-approx')
        report=json.loads(out.report_json)
        report['render_profile']['dsp_parity_certified']=True
        with self.assertRaises(ProfileError):
            _verify_payloads(out.wav_a,out.wav_b,_canonical(report))

    def test_profile_report_rejects_mismatch(self):
        out=compare_bundle_previews(_bundle(),_bundle(),duration_seconds=.005,
                                    render_profile='tallent-honda-approx')
        report=json.loads(out.report_json)
        report['render_settings']['phase_interpolation']='linear'
        with self.assertRaises(ProfileError):
            _verify_payloads(out.wav_a,out.wav_b,_canonical(report))

    def test_old_report_bytes_unchanged(self):
        a,b=_bundle('harmonic'),_bundle('negative')
        old=compare_bundle_previews(a,b,duration_seconds=.005,table_interpolation='linear',phase_interpolation='linear')
        omitted=compare_bundle_previews(a,b,duration_seconds=.005)
        self.assertEqual(old.report_json,omitted.report_json)
        self.assertNotIn('render_profile',json.loads(old.report_json))

    def test_named_profile_direct_unsupported_override(self):
        with self.assertRaises(ProfileError):
            compare_bundle_previews(_bundle(),_bundle(),duration_seconds=.005,
                                    render_profile='xt233-discrete-approx',table_interpolation='linear')

    def test_batch_explicit_profile_and_integrity(self):
        b=_bundle('harmonic')
        out=analyze_batch_previews((b,b),duration_seconds=.005,render_profile='xt233-discrete-approx')
        report=json.loads(out.report_json)
        self.assertFalse(report['render_profile']['crossfade_midpoint_applicable'])
        self.assertEqual(report['render_settings']['table_interpolation'],'nearest')
        self.assertTrue(all(t["crossfade_midpoint_rms_ratio"] is None
                            for t in report["candidates"][0]["transitions"]))
        self.assertEqual(verify_batch(out),report)

    def test_batch_profile_tamper_rejected(self):
        b=_bundle('harmonic')
        out=analyze_batch_previews((b,b),duration_seconds=.005,render_profile='xt233-discrete-approx')
        report=json.loads(out.report_json)
        report['render_profile']['phase_claim']='FALSE'
        from xtwavetable.preview.batch import _canonical as can
        forged_report=can(report)
        forged_audit=json.loads(out.audit_json)
        forged_audit['batch_report_sha256']=sha256(forged_report).hexdigest()
        tampered=replace(out,report_json=forged_report,audit_json=can(forged_audit))
        from xtwavetable.preview.oscillator import PreviewError
        with self.assertRaises(PreviewError):
            verify_batch(tampered)

    def test_old_batch_report_bytes_unchanged(self):
        b=_bundle('harmonic')
        x=analyze_batch_previews((b,b),duration_seconds=.005)
        y=analyze_batch_previews((b,b),duration_seconds=.005,
                                 table_interpolation='linear',phase_interpolation='linear')
        self.assertEqual(x.report_json,y.report_json)
        self.assertEqual(x.audit_json,y.audit_json)

    def test_cli_both_have_named_profile_option(self):
        for make,command,source_args in [
            (make_ab_parser,'compare',['--source-a','one','--source-b','two']),
            (make_batch_parser,'batch',['--sources','one','two'])]:
            args=make().parse_args([command,'--job','out',*source_args,
                                    '--render-profile','xt233-discrete-approx'])
            self.assertEqual(args.render_profile,'xt233-discrete-approx')
            self.assertIsNone(args.table_interpolation)
            self.assertIsNone(args.phase_interpolation)

    def test_manual_64_half_sample_shift_formula_all_harmonic_orders(self):
        # The .5 offset enforces reflection-antisymmetry even for EVEN k;
        # normalized output must stay in [-127,127] to avoid the -128 wrap.
        coeffs={1:1.0,2:0.5,3:0.25,4:0.12}
        half=[sum(a*math.sin(2*math.pi*k*(n+.5)/128)
                   for k,a in coeffs.items()) for n in range(64)]
        largest=max(abs(v) for v in half)
        q=[round(127*v/largest) for v in half]
        wave=Wave.from_half_cycle(q)
        self.assertEqual(tuple(-v for v in reversed(q)),wave.samples[64:])
        self.assertTrue(all(-127<=v<=127 for v in q))
        syx=encode_wave_dump(1200,wave)
        self.assertEqual(len(syx),WAVE_DUMP_LENGTH)
        self.assertEqual(decode_wave_dump(syx).wave,wave)

    def test_wire_payload_is_nibbles_not_raw_64_bytes(self):
        wave=Wave.from_half_cycle([(-63+i) for i in range(64)])
        syx=encode_wave_dump(1200,wave)
        self.assertEqual(len(syx[7:-2]),128)
        self.assertTrue(all(0<=n<=15 for n in syx[7:-2]))

    def test_full_cycle_nonantisymmetric_not_wire_supported(self):
        with self.assertRaises(ValueError):
            Wave(tuple([10]*128))

if __name__=='__main__': unittest.main()
