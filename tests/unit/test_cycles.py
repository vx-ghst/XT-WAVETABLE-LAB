"""M2.4 synthetic extraction: deterministic XT geometry and failure diagnostics."""

import math
import random
import unittest

from xtwavetable.analysis.signal import analyze_signal
from xtwavetable.audio.preprocess import preprocess_audio
from xtwavetable.audio.wav_reader import WavAudio
from xtwavetable.codec_xt.sysex import encode_wave_dump, decode_wave_dump
from xtwavetable.converter.cycles import CycleExtractionError, extract_wave_candidates
from xtwavetable.model import Wave


def sine(rate=48000, freq=440.0, *, duration=0.55, amp=0.62, dc=0.0):
    n = round(rate * duration)
    return WavAudio(rate, 1, "float", 32, n, tuple(
        dc + amp * math.sin(2.0 * math.pi * freq * i / rate) for i in range(n)))


class CycleTests(unittest.TestCase):
    def test_rate_independent_sine_with_xt_geometry(self):
        for rate in (44100, 48000, 88200, 96000, 192000):
            with self.subTest(rate=rate):
                src = sine(rate)
                result = extract_wave_candidates(src, pitch_hz=440.0, count=8)
                self.assertEqual(result.sample_rate, rate)
                self.assertEqual(len(result.candidates), 8)
                for c in result.candidates:
                    self.assertIsInstance(c.wave, Wave)
                    self.assertEqual(len(c.wave.samples), 128)
                    self.assertAlmostEqual(c.period_frames, rate / 440.0, places=9)
                    self.assertLess(c.projection_rms_error, 0.01)
                    self.assertLessEqual(c.quantized_peak, 127)
                    self.assertGreater(c.quantized_peak, 55)

    def test_two_location_methods_are_deterministic(self):
        src = sine()
        for method in ("uniform", "energy_peak"):
            with self.subTest(method=method):
                first = extract_wave_candidates(src, pitch_hz=440, count=16, method=method)
                second = extract_wave_candidates(src, pitch_hz=440, count=16, method=method)
                self.assertEqual(first, second)
                self.assertEqual(first.method, method)
                self.assertEqual([c.index for c in first.candidates], list(range(16)))

    def test_supported_counts(self):
        src = sine()
        for count in (1, 8, 16, 32, 61):
            with self.subTest(count=count):
                result = extract_wave_candidates(src, pitch_hz=440, count=count)
                self.assertEqual(len(result.candidates), count)

    def test_repeatable_wire_encoder(self):
        src = sine()
        out = extract_wave_candidates(src, pitch_hz=440, count=1).candidates[0]
        packet = encode_wave_dump(1000, out.wave)
        self.assertEqual(len(packet), 137)
        self.assertEqual(decode_wave_dump(packet).wave, out.wave)
        self.assertEqual(packet, encode_wave_dump(1000, out.wave))

    def test_projection_diagnostics_when_second_half_is_not_antisymmetric(self):
        rate = 48000
        src = WavAudio(rate, 1, "float", 32, rate // 2,
                       tuple(0.45 * math.sin(2 * math.pi * 440 * i / rate) +
                             0.22 * math.cos(2 * math.pi * 880 * i / rate)
                             for i in range(rate // 2)))
        c = extract_wave_candidates(src, pitch_hz=440, count=1).candidates[0]
        self.assertGreater(c.projection_rms_error, 0.03)
        self.assertLessEqual(c.projected_peak, 1.0)

    def test_no_implicit_peak_normalization(self):
        src = sine(amp=0.25)
        c = extract_wave_candidates(src, pitch_hz=440, count=1).candidates[0]
        self.assertEqual(c.gain_linear, 1.0)
        self.assertLess(c.quantized_peak, 40)
        normalized = extract_wave_candidates(src, pitch_hz=440, count=1, normalize_peak=True)
        self.assertEqual(normalized.candidates[0].quantized_peak, 127)
        self.assertGreater(normalized.candidates[0].gain_linear, 3.0)

    def test_float_above_full_scale_requires_opt_in(self):
        src = sine(amp=1.5)
        with self.assertRaisesRegex(CycleExtractionError, "exceeds 0 dBFS"):
            extract_wave_candidates(src, pitch_hz=440)
        result = extract_wave_candidates(src, pitch_hz=440, normalize_peak=True)
        self.assertEqual(result.candidates[0].quantized_peak, 127)

    def test_dc_reference_is_exposed(self):
        src = sine(dc=0.28)
        candidate = extract_wave_candidates(src, pitch_hz=440, count=1).candidates[0]
        self.assertAlmostEqual(candidate.dc_reference, 0.28, delta=0.02)
        self.assertLess(candidate.projection_rms_error, 0.02)

    def test_source_immutability(self):
        src = sine()
        before = src.samples
        extract_wave_candidates(src, pitch_hz=440, count=8, method="energy_peak")
        self.assertIs(src.samples, before)

    def test_stereo_channel_selection_explicit(self):
        src = sine()
        stereo = WavAudio(48000, 2, "float", 32, src.frame_count,
                          tuple(v for value in src.samples for v in (value, -value)))
        left = extract_wave_candidates(stereo, pitch_hz=440, count=1, channel=0)
        right = extract_wave_candidates(stereo, pitch_hz=440, count=1, channel=1)
        self.assertIsNotNone(left.candidates[0].wave)
        self.assertIsNotNone(right.candidates[0].wave)
        averaged = preprocess_audio(stereo, channel_mode="average")
        with self.assertRaisesRegex(CycleExtractionError, "no rising zero crossing|silent"):
            extract_wave_candidates(averaged, pitch_hz=440)

    def test_processedaudio_supported(self):
        source = sine(dc=0.08)
        p = preprocess_audio(source, remove_dc=True, normalize_peak_dbfs=-3.0)
        result = extract_wave_candidates(p, pitch_hz=440, count=8)
        self.assertEqual(len(result.candidates), 8)
        self.assertEqual(result.source_frames, p.frame_count)

    def test_pitch_from_m23_analysis(self):
        src = sine(rate=48000, duration=0.4)
        a = analyze_signal(src)
        result = extract_wave_candidates(src, analysis=a, count=8)
        self.assertEqual(result.pitch_source, "m2.3_analysis")
        for c in result.candidates:
            self.assertAlmostEqual(c.pitch_hz, 440.0, delta=2.0)

    def test_explicit_pitch_overrides_analysis_pitch(self):
        src = sine(rate=48000, duration=0.4)
        a = analyze_signal(src)
        result = extract_wave_candidates(src, pitch_hz=220, analysis=a, count=1)
        self.assertEqual(result.pitch_source, "explicit")
        self.assertEqual(result.candidates[0].pitch_hz, 220.0)

    def test_noise_analysis_requires_explicit_frequency(self):
        rng = random.Random(55)
        data = tuple(rng.uniform(-0.3, 0.3) for _ in range(16384))
        src = WavAudio(48000, 1, "float", 32, len(data), data)
        report = analyze_signal(src)
        with self.assertRaisesRegex(CycleExtractionError, "tonal analysis"):
            extract_wave_candidates(src, analysis=report)

    def test_missing_frequency_rejected(self):
        with self.assertRaisesRegex(CycleExtractionError, "tonal analysis"):
            extract_wave_candidates(sine())

    def test_incompatible_analysis_rejected(self):
        src = sine(rate=48000, duration=0.4)
        a = analyze_signal(src)
        other = sine(rate=44100, duration=0.4)
        with self.assertRaisesRegex(CycleExtractionError, "metadata"):
            extract_wave_candidates(other, analysis=a)

    def test_invalid_frequency(self):
        src = sine()
        for freq in (-1, 0, float("nan"), float("inf"), True, 5, 24000):
            with self.subTest(freq=freq), self.assertRaises(CycleExtractionError):
                extract_wave_candidates(src, pitch_hz=freq)

    def test_bad_parameters(self):
        src = sine()
        for count in (True, 0, 62, 1.5):
            with self.subTest(count=count), self.assertRaises(CycleExtractionError):
                extract_wave_candidates(src, pitch_hz=440, count=count)
        for method in (None, "energy", "random"):
            with self.subTest(method=method), self.assertRaises(CycleExtractionError):
                extract_wave_candidates(src, pitch_hz=440, method=method)
        with self.assertRaises(CycleExtractionError):
            extract_wave_candidates(src, pitch_hz=440, normalize_peak=1)
        with self.assertRaises(CycleExtractionError):
            extract_wave_candidates(src, pitch_hz=440, channel=True)

    def test_invalid_shape_and_nan(self):
        good = sine()
        invalid = WavAudio(48000, 1, "float", 32, good.frame_count + 1, good.samples)
        with self.assertRaises(CycleExtractionError):
            extract_wave_candidates(invalid, pitch_hz=440)
        samples = list(good.samples)
        samples[10] = float("nan")
        bad = WavAudio(48000, 1, "float", 32, good.frame_count, tuple(samples))
        with self.assertRaises(CycleExtractionError):
            extract_wave_candidates(bad, pitch_hz=440)

    def test_silence_and_dc_rejected(self):
        for value in (0.0, 0.35):
            src = WavAudio(48000, 1, "float", 32, 8000, (value,) * 8000)
            with self.subTest(value=value), self.assertRaises(CycleExtractionError):
                extract_wave_candidates(src, pitch_hz=440)

    def test_too_short_input(self):
        src = sine(duration=0.008)
        with self.assertRaisesRegex(CycleExtractionError, "too short"):
            extract_wave_candidates(src, pitch_hz=440)

    def test_low_pitch_longer_cycle_requires_data(self):
        src = sine(duration=0.04)
        with self.assertRaisesRegex(CycleExtractionError, "too short"):
            extract_wave_candidates(src, pitch_hz=55)

    def test_antisymmetry_constraint_all_candidates(self):
        src = sine()
        result = extract_wave_candidates(src, pitch_hz=440, count=61)
        for c in result.candidates:
            self.assertEqual(c.wave, Wave.from_half_cycle(c.wave.half_cycle))
            self.assertEqual(c.wave.samples[127], -c.wave.samples[0])


if __name__ == "__main__":
    unittest.main()
