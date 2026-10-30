"""M2.7 offline integration: synthetic PCM WAV + synthetic complete XT backup.

No private files, hardware, ROM, MIDI, or network. Source immutable and all
wave/table replacement permissions explicitly provided in each successful case.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import math
import struct
import unittest

from xtwavetable.codec_xt import (decode_table_dump, decode_wave_dump,
                                  encode_table_dump, encode_wave_dump)
from xtwavetable.converter.pipeline import (ConversionOptions,
                                             convert_wav_to_offline_bundle)
from xtwavetable.export.bundle import ExportPlanError
from xtwavetable.model import Table, Wave
from xtwavetable.optimizer.selection import WaveSelectionError
from xtwavetable.converter.cycles import CycleExtractionError
from xtwavetable.analysis.signal import SignalAnalysisError
from xtwavetable.audio.preprocess import AudioProcessingError
from xtwavetable.audio.wav_reader import WavFormatError


def wav_fixture(rate=44100, channels=1, frames=None, *, antiphase=False,
                zero=False, dc=0.0, constant_harmonics=False) -> bytes:
    """Synthetic evolving 220 Hz tone with odd harmonics, within PCM16 bounds."""
    if frames is None:
        frames = rate // 2
    frame_bytes = bytearray()
    for i in range(frames):
        phase = 2 * math.pi * 220 * i / rate
        blend = 0.18 if constant_harmonics else 0.08 + 0.24 * i / frames
        val = (0.0 if zero else 0.43 * math.sin(phase) + blend * math.sin(3 * phase)) + dc
        val = min(0.999, max(-1.0, val))
        x = int(round(val * 32767))
        if channels == 1:
            frame_bytes.extend(struct.pack('<h', x))
        else:
            frame_bytes.extend(struct.pack('<hh', x, -x if antiphase else x))
    audio = bytes(frame_bytes)
    fmt = struct.pack('<HHIIHH', 1, channels, rate, rate * channels * 2, channels * 2, 16)
    return (b'RIFF' + struct.pack('<I', 4+8+len(fmt)+8+len(audio))
            + b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt
            + b'data' + struct.pack('<I', len(audio)) + audio)


def synthetic_backup(*, cross_table_reference=False, bad_special=False) -> bytes:
    waves = b''.join(encode_wave_dump(1000 + i, Wave.from_half_cycle([i-125]*64))
                     for i in range(250))
    tables = []
    for n in range(96, 128):
        editable = [1000]*61
        if cross_table_reference and n == 97:
            editable[0] = 1200
        if bad_special and n == 96:
            editable[0:2] = [0xDEAD, 0xBEEF]
        table = Table(tuple(editable) + (0xDEAD, 0xBEEF, 0xFFFF))
        tables.append(encode_table_dump(n, table))
    return waves + b''.join(tables)


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backup = synthetic_backup()
        cls.wav = wav_fixture()

    def opts(self, **updates):
        base = ConversionOptions(pitch_hz=220.0, candidate_count=8,
                                 requested_waves=8, shortfall='reuse')
        return replace(base, **updates)

    def run_pipeline(self, wav=None, backup=None, options=None, **overrides):
        args = dict(options=self.opts() if options is None else options,
                    wave_ids=tuple(range(1200,1208)), table_id=96,
                    authorized_replacement_wave_ids=tuple(range(1200,1208)),
                    authorize_table_replacement=True)
        args.update(overrides)
        return convert_wav_to_offline_bundle(
            self.wav if wav is None else wav,
            self.backup if backup is None else backup,
            **args)

    def test_pcm_wav_to_valid_exact_xt_packets(self):
        result = self.run_pipeline()
        self.assertEqual(result.source.sample_rate, 44100)
        self.assertEqual(result.bundle.table_id, 96)
        self.assertEqual(result.bundle.wave_ids, tuple(range(1200,1208)))
        self.assertEqual(result.sysex.count(b'\xf0'), len(result.selection.waves)+1)
        n = len(result.selection.waves)
        self.assertEqual(len(result.sysex), n*137+265)
        for i in range(n):
            wave_dump = decode_wave_dump(result.sysex[137*i:137*(i+1)])
            self.assertEqual(wave_dump.wave_id, 1200+i)
            self.assertEqual(wave_dump.wave, result.selection.waves[i])
        table_dump = decode_table_dump(result.sysex[-265:])
        self.assertEqual(table_dump.table, result.bundle.table)
        self.assertEqual(table_dump.table.reserved_positions, (0xDEAD,0xBEEF,0xFFFF))
        self.assertEqual(table_dump.table_id, 96)

    def test_bit_identical_reproducibility(self):
        a = self.run_pipeline()
        b = self.run_pipeline()
        self.assertEqual(a.sysex, b.sysex)
        self.assertEqual(a.manifest_json, b.manifest_json)
        self.assertEqual(a.bundle.manifest_json, b.bundle.manifest_json)

    def test_manifest_hashes_source_and_output(self):
        r = self.run_pipeline()
        data = json.loads(r.manifest_json)
        self.assertEqual(data['schema'], 'xtwavetable.m2.7.pipeline.v1')
        self.assertEqual(data['source_wav_sha256'], sha256(self.wav).hexdigest())
        self.assertEqual(data['offline_export']['source_snapshot_sha256'], sha256(self.backup).hexdigest())
        self.assertEqual(data['offline_export']['output_sysex_sha256'], sha256(r.sysex).hexdigest())
        self.assertEqual(data['source_wav']['sample_rate'], 44100)
        self.assertEqual(data['processing']['output_frames'], 22050)
        self.assertEqual(data['analysis'], None)
        self.assertEqual(data['extraction']['pitch_source'], 'explicit')
        self.assertTrue(r.manifest_json.endswith(b'\n'))

    def test_44_48_96khz_without_resampling(self):
        for rate in (44100, 48000, 96000):
            with self.subTest(rate=rate):
                r = self.run_pipeline(wav=wav_fixture(rate=rate))
                self.assertEqual(r.source.sample_rate, rate)
                self.assertEqual(r.processed.sample_rate, rate)
                self.assertEqual(r.extraction.sample_rate, rate)
                self.assertEqual(r.processed.frame_count, rate // 2)

    def test_other_rates_88200_192000_explicit(self):
        for rate in (88200, 192000):
            with self.subTest(rate=rate):
                r = self.run_pipeline(wav=wav_fixture(rate=rate),
                                      options=self.opts(candidate_count=2, requested_waves=2),
                                      wave_ids=(1200,1201),
                                      authorized_replacement_wave_ids=(1200,1201))
                self.assertEqual(r.extraction.sample_rate, rate)

    def test_native_stereo_left_right_and_antiphase_differ(self):
        wav = wav_fixture(channels=2, antiphase=True)
        left = self.run_pipeline(wav=wav, options=self.opts(channel=0))
        right = self.run_pipeline(wav=wav, options=self.opts(channel=1))
        self.assertNotEqual(left.sysex, right.sysex)
        self.assertEqual(left.processed.channels, 2)
        self.assertEqual(right.processed.channels, 2)
        with self.assertRaises(CycleExtractionError):
            self.run_pipeline(wav=wav, options=self.opts(channel_mode='average'))

    def test_preprocess_crop_and_gain_metadata(self):
        wav = wav_fixture(dc=0.10)
        opt = self.opts(start_frame=2000, end_frame=15000,
                        channel_mode='left', remove_dc=True,
                        normalize_peak_dbfs=-3.0)
        result = self.run_pipeline(wav=wav, options=opt)
        report = json.loads(result.manifest_json)
        self.assertEqual(result.processed.frame_count, 13000)
        self.assertEqual(report['processing']['start_frame'], 2000)
        self.assertEqual(report['processing']['end_frame_exclusive'], 15000)
        self.assertEqual(report['processing']['normalize_peak_dbfs'], -3.0)
        self.assertAlmostEqual(result.processed.peak_after_gain, 10**(-3/20), places=9)

    def test_auto_pitch_via_m23_analysis(self):
        result = self.run_pipeline(options=self.opts(pitch_hz=None, candidate_count=4,
                                                     requested_waves=4),
                                   wave_ids=(1200,1201,1202,1203),
                                   authorized_replacement_wave_ids=(1200,1201,1202,1203))
        self.assertIsNotNone(result.analysis)
        self.assertEqual(result.extraction.pitch_source, 'm2.3_analysis')
        self.assertEqual(json.loads(result.manifest_json)['analysis']['heuristic_label'], 'tonal')

    def test_no_implicit_pitch_for_noise_or_silence(self):
        with self.assertRaises((SignalAnalysisError, CycleExtractionError)):
            self.run_pipeline(wav=wav_fixture(zero=True),
                              options=self.opts(pitch_hz=None))

    def test_missing_wave_ack_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, 'authorization'):
            self.run_pipeline(authorized_replacement_wave_ids=())

    def test_missing_table_ack_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, 'authorization'):
            self.run_pipeline(authorize_table_replacement=False)

    def test_cross_table_refs_fail_closed(self):
        backup = synthetic_backup(cross_table_reference=True)
        with self.assertRaisesRegex(ExportPlanError, 'other tables'):
            self.run_pipeline(backup=backup)
        success = self.run_pipeline(backup=backup, acknowledge_cross_table_references=True)
        self.assertEqual(success.bundle.known_cross_table_ids, (97,))

    def test_special_table_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, 'special table'):
            self.run_pipeline(backup=synthetic_backup(bad_special=True))

    def test_incomplete_snapshot_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, 'complete backup'):
            self.run_pipeline(backup=self.backup[:-265])

    def test_snapshot_corruption_rejected(self):
        bad = bytearray(self.backup)
        bad[135] ^= 1
        with self.assertRaises(ExportPlanError):
            self.run_pipeline(backup=bytes(bad))

    def test_source_bytes_not_mutated(self):
        wav, snapshot = self.wav, self.backup
        h1, h2 = sha256(wav).hexdigest(), sha256(snapshot).hexdigest()
        self.run_pipeline()
        self.assertEqual(sha256(wav).hexdigest(), h1)
        self.assertEqual(sha256(snapshot).hexdigest(), h2)

    def test_types_rejected(self):
        for bad in (bytearray(self.wav), 'audio'):
            with self.subTest(bad=type(bad)), self.assertRaises(TypeError):
                self.run_pipeline(wav=bad)
        with self.assertRaises(TypeError):
            self.run_pipeline(options={})
        with self.assertRaises(TypeError):
            convert_wav_to_offline_bundle(None, self.backup, options=self.opts(),
                wave_ids=(1200,), table_id=96)
        with self.assertRaises(TypeError):
            self.run_pipeline(backup=bytearray(self.backup))

    def test_noise_or_silent_explicit_pitch_still_rejected(self):
        with self.assertRaises(CycleExtractionError):
            self.run_pipeline(wav=wav_fixture(zero=True))

    def test_insufficient_unique_requires_opt_in_reuse(self):
        wav = wav_fixture(constant_harmonics=True)
        with self.assertRaises(WaveSelectionError):
            self.run_pipeline(wav=wav, options=self.opts(candidate_count=1, shortfall='reject'))
        r = self.run_pipeline(wav=wav, options=self.opts(candidate_count=1, shortfall='reuse'),
                              wave_ids=(1200,), authorized_replacement_wave_ids=(1200,))
        self.assertTrue(r.selection.has_shortfall)
        self.assertEqual(r.selection.actual_distinct_waves, 1)

    def test_diff_cfg_produces_different_manifest(self):
        a = self.run_pipeline()
        b = self.run_pipeline(options=self.opts(selection_strategy='diversity'))
        self.assertNotEqual(a.manifest_json, b.manifest_json)

    def test_incorrect_slot_count_rejected(self):
        with self.assertRaises(ExportPlanError):
            self.run_pipeline(wave_ids=(1200,), authorized_replacement_wave_ids=(1200,))

    def test_read_only_no_writes_even_without_file_paths(self):
        result = self.run_pipeline()
        self.assertIsInstance(result.sysex, bytes)
        self.assertIsInstance(result.manifest_json, bytes)
        self.assertIn(b'hardware', result.manifest_json)


if __name__ == '__main__':
    unittest.main()
