"""M3.1 pure approximate preview tests; no hardware, ROM, files or audio assets."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import io
import json
import math
import struct
import unittest
import wave

from xtwavetable.codec_xt import encode_wave_dump, encode_table_dump
from xtwavetable.export.bundle import ExportBundle
from xtwavetable.model import Table, Wave
from xtwavetable.preview import (PreviewError, render_preview,
                                 render_export_bundle_preview,
                                 encode_preview_pcm16_wav)


def make_wave(kind=0):
    if kind == 0:
        half = [int(round(100*math.sin(2*math.pi*i/128))) for i in range(64)]
    elif kind == 1:
        half = [int(round(100*math.sin(6*math.pi*i/128))) for i in range(64)]
    else:
        half = [int(round(50*math.cos(2*math.pi*i/128))) for i in range(64)]
    return Wave.from_half_cycle(half)


def setup_data():
    first, second = make_wave(0), make_wave(1)
    table = Table(tuple([1000]*30 + [1001]*31 + [0xDEAD, 0xBEEF, 0xFFFF]))
    return table, {1000:first, 1001:second}


def make_bundle():
    table,waves=setup_data()
    payload = (encode_wave_dump(1000,waves[1000]) +
               encode_wave_dump(1001,waves[1001]) + encode_table_dump(96,table))
    manifest = {"output_sysex_sha256":sha256(payload).hexdigest(),
                "wave_ids":[1000,1001],"table_id":96}
    raw = (json.dumps(manifest,sort_keys=True)+"\n").encode()
    return ExportBundle(payload,raw,(1000,1001),96,table,(),"0"*64)


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table,cls.waves=setup_data()

    def render(self,**kw):
        return render_preview(self.table,self.waves,**kw)

    def test_deterministic_bit_identical_replay(self):
        a=self.render(duration_seconds=.1)
        b=self.render(duration_seconds=.1)
        self.assertEqual(a,b)
        self.assertEqual(a.samples_sha256,sha256(struct.pack('<'+'d'*len(a.samples),*a.samples)).hexdigest())

    def test_sweep_has_both_endpoints(self):
        p=self.render(start_position=0,end_position=60,duration_seconds=.01)
        self.assertEqual((p.start_position,p.end_position),(0.,60.))
        self.assertEqual(len(p.samples),480)

    def test_static_end_position_default(self):
        a=self.render(start_position=7,duration_seconds=.01)
        b=self.render(start_position=7,end_position=7,duration_seconds=.01)
        self.assertEqual(a,b)

    def test_first_position_only_first_wave(self):
        a=self.render(start_position=0,duration_seconds=.01)
        b=self.render(start_position=29,duration_seconds=.01)
        self.assertEqual(a.samples,b.samples)

    def test_last_position_only_last_wave(self):
        a=self.render(start_position=30,duration_seconds=.01)
        b=self.render(start_position=60,duration_seconds=.01)
        self.assertEqual(a.samples,b.samples)

    def test_linear_half_crossfade_expected(self):
        table=Table(tuple([1000,1001]+[1001]*59+[0xDEAD,0xBEEF,0xFFFF]))
        x=render_preview(table,self.waves,start_position=.5,frequency_hz=120,
                         duration_seconds=.02)
        a=render_preview(table,self.waves,start_position=0,frequency_hz=120,
                         duration_seconds=.02)
        b=render_preview(table,self.waves,start_position=1,frequency_hz=120,
                         duration_seconds=.02)
        self.assertTrue(all(abs(m-(u+v)/2)<1e-12 for m,u,v in zip(x.samples,a.samples,b.samples)))

    def test_nearest_wave_transition_distinct(self):
        table=Table(tuple([1000,1001]+[1001]*59+[0xDEAD,0xBEEF,0xFFFF]))
        a=render_preview(table,self.waves,start_position=.49,table_interpolation='nearest',duration_seconds=.01)
        b=render_preview(table,self.waves,start_position=.51,table_interpolation='nearest',duration_seconds=.01)
        self.assertNotEqual(a.samples,b.samples)

    def test_nearest_and_linear_at_exact_integer_same(self):
        self.assertEqual(self.render(start_position=30,duration_seconds=.01).samples,
                         self.render(start_position=30,table_interpolation='nearest',duration_seconds=.01).samples)

    def test_phase_interpolation_selectable(self):
        a=self.render(phase_interpolation='nearest',frequency_hz=119,duration_seconds=.01)
        b=self.render(phase_interpolation='linear',frequency_hz=119,duration_seconds=.01)
        self.assertNotEqual(a.samples,b.samples)

    def test_amplitude_exact_scaling(self):
        a=self.render(amplitude=1,duration_seconds=.01)
        b=self.render(amplitude=.5,duration_seconds=.01)
        self.assertEqual(tuple(x*.5 for x in a.samples),b.samples)

    def test_phase_shift_changes_waveform(self):
        a=self.render(initial_phase=0,duration_seconds=.01)
        b=self.render(initial_phase=.25,duration_seconds=.01)
        self.assertNotEqual(a.samples,b.samples)

    def test_reserved_raw_values_ignored(self):
        table=self.table.with_user_positions(self.table.user_positions)
        modified=Table(table.user_positions+(1,2,3))
        self.assertEqual(render_preview(modified,self.waves,duration_seconds=.01).samples,
                         self.render(duration_seconds=.01).samples)

    def test_no_file_io_and_data_unchanged(self):
        ids=tuple(self.table.wave_ids)
        waves=dict(self.waves)
        self.render(duration_seconds=.01)
        self.assertEqual(self.table.wave_ids,ids)
        self.assertEqual(self.waves,waves)

    def test_cross_rate_frame_count(self):
        for rate in (44100,48000,96000):
            with self.subTest(rate=rate):
                p=self.render(sample_rate=rate,duration_seconds=.01)
                self.assertEqual(p.frames,rate//100)
                self.assertEqual(p.sample_rate,rate)

    def test_heuristics_with_identical_waves_zero(self):
        all_same=Table(tuple([1000]*61+[0xDEAD,0xBEEF,0xFFFF]))
        p=render_preview(all_same,{1000:self.waves[1000]},duration_seconds=.01)
        self.assertEqual(p.max_adjacent_wave_rms_difference,0.)

    def test_heuristics_with_change_positive(self):
        p=self.render(duration_seconds=.01)
        self.assertGreater(p.max_adjacent_wave_rms_difference,0)
        self.assertGreater(p.rms,0)
        self.assertLessEqual(p.peak,1)

    def test_missing_reference_rejected_even_out_of_sweep(self):
        with self.assertRaisesRegex(PreviewError,'explicit Wave'):
            render_preview(self.table,{1000:self.waves[1000]},start_position=0)

    def test_wrong_wave_object_rejected(self):
        with self.assertRaises(PreviewError):
            render_preview(self.table,{1000:self.waves[1000],1001:7})

    def test_bad_table_waves_types(self):
        for table,waves in ((7,self.waves),(self.table,7),(self.table,None)):
            with self.subTest(table=type(table).__name__,waves=type(waves).__name__):
                with self.assertRaises(PreviewError):
                    render_preview(table,waves)

    def test_invalid_sample_rates(self):
        for rate in (800,0,False,44100.0,192001):
            with self.subTest(rate=rate),self.assertRaises(PreviewError):
                self.render(sample_rate=rate)

    def test_invalid_pitch_nyquist(self):
        for hz in (0,-10,24000,1e9,float('nan'),float('inf'),True):
            with self.subTest(hz=hz),self.assertRaises(PreviewError):
                self.render(frequency_hz=hz)

    def test_invalid_length_and_frame_budget(self):
        for sec in (0,-1,11,10.01,float('nan'),True):
            with self.subTest(sec=sec),self.assertRaises(PreviewError):
                self.render(duration_seconds=sec)
        with self.assertRaisesRegex(PreviewError,'frames'):
            self.render(sample_rate=192000,duration_seconds=5)
        with self.assertRaisesRegex(PreviewError,'frames'):
            self.render(duration_seconds=.0000001)

    def test_invalid_position_bounds(self):
        for k, v in (('start_position',-1),('end_position',61),('start_position',float('nan')),('end_position',float('inf'))):
            with self.subTest(k=k,v=v),self.assertRaises(PreviewError):
                self.render(**{k:v})

    def test_invalid_interpolations(self):
        for k in ('table_interpolation','phase_interpolation'):
            with self.subTest(k=k),self.assertRaises(PreviewError):
                self.render(**{k:'cubic'})

    def test_invalid_gain_and_phase(self):
        for v in (0,1.1,-1,True,float('nan')):
            with self.subTest(v=v),self.assertRaises(PreviewError):
                self.render(amplitude=v)
        for v in (-.1,1,float('inf'),True):
            with self.subTest(v=v),self.assertRaises(PreviewError):
                self.render(initial_phase=v)

    def test_frame_limit_single_frame(self):
        p=self.render(duration_seconds=1/48000)
        self.assertEqual(p.frames,1)

    def test_repeat_wave_max_sweep(self):
        table=Table(tuple([1000]*61+[0xDEAD,0xBEEF,0xFFFF]))
        a=render_preview(table,{1000:self.waves[1000]},start_position=0,end_position=60,duration_seconds=.01)
        b=render_preview(table,{1000:self.waves[1000]},start_position=0,end_position=0,duration_seconds=.01)
        self.assertEqual(a.samples,b.samples)

    def test_pcm16_wav_structure(self):
        p=self.render(duration_seconds=.01)
        blob=encode_preview_pcm16_wav(p)
        self.assertEqual(len(blob),44+2*p.frames)
        with wave.open(io.BytesIO(blob),'rb') as wav:
            self.assertEqual(wav.getnchannels(),1)
            self.assertEqual(wav.getsampwidth(),2)
            self.assertEqual(wav.getframerate(),48000)
            self.assertEqual(wav.getnframes(),480)
            self.assertEqual(len(wav.readframes(480)),960)

    def test_pcm16_wav_deterministic(self):
        a=self.render(duration_seconds=.01)
        self.assertEqual(encode_preview_pcm16_wav(a),encode_preview_pcm16_wav(a))

    def test_pcm16_wav_reject_invalid(self):
        p=self.render(duration_seconds=.01)
        with self.assertRaises(PreviewError):
            encode_preview_pcm16_wav('wrong')
        with self.assertRaises(PreviewError):
            encode_preview_pcm16_wav(replace(p,samples=(float('nan'),)))
        with self.assertRaises(PreviewError):
            encode_preview_pcm16_wav(replace(p,samples=(2.0,)))

    def test_preview_export_bundle(self):
        p=render_export_bundle_preview(make_bundle(),duration_seconds=.01)
        self.assertEqual(p,self.render(duration_seconds=.01))

    def test_preview_export_bundle_reject_wrong_length(self):
        b=make_bundle()
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,sysex=b.sysex[:-1]))

    def test_preview_export_bundle_reject_checksum(self):
        b=make_bundle(); bts=bytearray(b.sysex); bts[-2]^=1
        manifest=json.loads(b.manifest_json)
        manifest['output_sysex_sha256']=sha256(bts).hexdigest()
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,sysex=bytes(bts),manifest_json=json.dumps(manifest).encode()))

    def test_preview_export_bundle_reject_manifest_mismatch(self):
        b=make_bundle()
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,manifest_json=b'{}'))
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,manifest_json=b'bad'))

    def test_preview_export_bundle_reject_ids(self):
        b=make_bundle()
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,wave_ids=(1001,1000)))
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,table_id=97))

    def test_preview_export_bundle_reject_table(self):
        b=make_bundle()
        changed=Table(tuple([1001]*61+[0xDEAD,0xBEEF,0xFFFF]))
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(replace(b,table=changed))

    def test_preview_export_bundle_bad_type(self):
        with self.assertRaises(PreviewError):
            render_export_bundle_preview(None)


if __name__=='__main__':
    unittest.main()
