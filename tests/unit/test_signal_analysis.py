"""M2.3 pure-synthetic repeatable FFT, pitch, periodicity, spectral evolution."""

import math
import random
import struct
import unittest

from xtwavetable.audio.preprocess import preprocess_audio
from xtwavetable.audio.wav_reader import WavAudio, decode_wav
from xtwavetable.analysis.signal import (
    SignalAnalysisError, _fft, analyze_signal,
)


def make_sine(rate=48000, f0=440.0, *, duration=0.30, amp=0.5, dc=0.0):
    frames = int(duration * rate)
    return WavAudio(rate, 1, "float", 32, frames,
                    tuple(dc + amp * math.sin(2.0 * math.pi * f0 * i / rate)
                          for i in range(frames)))


class SignalAnalysisTests(unittest.TestCase):
    def test_fft_forward_inverse(self):
        values = [complex(i % 3 - 1, (i * 3) % 7 - 2) for i in range(16)]
        actual = _fft(_fft(values), inverse=True)
        for x, y in zip(actual, values):
            self.assertAlmostEqual(x.real, y.real, places=10)
            self.assertAlmostEqual(x.imag, y.imag, places=10)

    def test_fft_rejects_non_power_of_two(self):
        for n in (0, 3, 7, 17):
            with self.subTest(n=n), self.assertRaises(SignalAnalysisError):
                _fft([0j] * n)

    def test_440_hz_across_sample_rates(self):
        for rate in (44100, 48000, 96000, 192000):
            with self.subTest(rate=rate):
                report = analyze_signal(make_sine(rate))
                self.assertEqual(report.sample_rate, rate)
                self.assertEqual(report.heuristic_label, "tonal")
                self.assertEqual(report.tonal_fraction, 1.0)
                self.assertAlmostEqual(report.median_f0_hz, 440.0, delta=2.0)
                self.assertGreater(report.features[0].periodicity, 0.95)
                self.assertAlmostEqual(report.median_spectral_centroid_hz, 440.0, delta=6.0)

    def test_other_notes_at_48k(self):
        for freq in (110.0, 220.0, 880.0, 1760.0):
            with self.subTest(freq=freq):
                report = analyze_signal(make_sine(48000, freq))
                self.assertAlmostEqual(report.median_f0_hz, freq, delta=3.0)

    def test_all_zero_silence(self):
        src = WavAudio(48000, 1, "float", 32, 8192, (0.0,) * 8192)
        result = analyze_signal(src)
        self.assertEqual(result.heuristic_label, "silence")
        self.assertIsNone(result.median_f0_hz)
        self.assertEqual(result.median_spectral_centroid_hz, 0.0)
        self.assertEqual(result.mean_spectral_flux, 0.0)

    def test_constant_dc_not_misidentified_as_pitch(self):
        src = WavAudio(48000, 1, "float", 32, 8192, (0.25,) * 8192)
        result = analyze_signal(src)
        self.assertEqual(result.heuristic_label, "dc_only")
        self.assertIsNone(result.median_f0_hz)
        self.assertEqual(result.median_spectral_centroid_hz, 0.0)

    def test_dc_offset_does_not_corrupt_f0(self):
        result = analyze_signal(make_sine(48000, 440, dc=0.4))
        self.assertAlmostEqual(result.median_f0_hz, 440.0, delta=2.0)

    def test_noise_fundamental_not_forced(self):
        random_gen = random.Random(721)
        data = tuple(random_gen.uniform(-0.5, 0.5) for _ in range(16384))
        result = analyze_signal(WavAudio(48000, 1, "float", 32, len(data), data))
        self.assertIsNone(result.median_f0_hz)
        self.assertEqual(result.heuristic_label, "noise_or_complex")

    def test_spectral_change_tone_switch(self):
        rate = 48000
        half = 8192
        first = tuple(0.5 * math.sin(2 * math.pi * 220 * i / rate) for i in range(half))
        second = tuple(0.5 * math.sin(2 * math.pi * 880 * i / rate) for i in range(half))
        audio = WavAudio(rate, 1, "float", 32, half * 2, first + second)
        result = analyze_signal(audio, window_size=4096, hop_size=2048, max_windows=12)
        self.assertLess(result.features[0].spectral_centroid_hz, 250)
        self.assertGreater(result.features[-1].spectral_centroid_hz, 800)
        self.assertGreater(max(x.spectral_flux for x in result.features), 0.1)
        self.assertAlmostEqual(result.features[0].f0_hz, 220, delta=2)
        self.assertAlmostEqual(result.features[-1].f0_hz, 880, delta=3)

    def test_transient_like_single_impulse(self):
        samples = [0.0] * 16384
        samples[50] = 0.8
        src = WavAudio(48000, 1, "float", 32, len(samples), tuple(samples))
        result = analyze_signal(src)
        self.assertEqual(result.heuristic_label, "transient_like")
        self.assertGreater(result.max_crest_factor, 8)
        self.assertIsNone(result.median_f0_hz)

    def test_centroid_tracks_frequency(self):
        low = analyze_signal(make_sine(44100, 220))
        high = analyze_signal(make_sine(44100, 1320))
        self.assertLess(low.median_spectral_centroid_hz, high.median_spectral_centroid_hz)

    def test_f0_evolution_for_tonal_sections(self):
        rate = 48000
        n = 10000
        low = tuple(0.5 * math.sin(2 * math.pi * 330 * i / rate) for i in range(n))
        high = tuple(0.5 * math.sin(2 * math.pi * 660 * i / rate) for i in range(n))
        result = analyze_signal(WavAudio(rate, 1, "float", 32, 2 * n, low + high), max_windows=10)
        self.assertAlmostEqual(result.features[0].f0_hz, 330, delta=2)
        self.assertAlmostEqual(result.features[-1].f0_hz, 660, delta=2)

    def test_stereo_channels_explicit_and_antiphase(self):
        mono = make_sine(48000)
        data = tuple(v for s in mono.samples for v in (s, -s))
        stereo = WavAudio(48000, 2, "float", 32, mono.frame_count, data)
        left = analyze_signal(stereo, channel=0)
        right = analyze_signal(stereo, channel=1)
        self.assertAlmostEqual(left.median_f0_hz, right.median_f0_hz, delta=0.01)
        cancelled = preprocess_audio(stereo, channel_mode="average")
        avg = analyze_signal(cancelled)
        self.assertEqual(avg.heuristic_label, "silence")

    def test_processedaudio_fed_in_and_immutable(self):
        original = make_sine(48000, dc=0.15)
        processed = preprocess_audio(original, remove_dc=True, normalize_peak_dbfs=-3.0)
        before = processed.samples
        one = analyze_signal(processed)
        two = analyze_signal(processed)
        self.assertEqual(one, two)
        self.assertEqual(processed.samples, before)
        self.assertEqual(original.samples[0], 0.15)

    def test_window_coverage_and_sparse_flag(self):
        src = make_sine(48000, duration=1.0)
        report = analyze_signal(src, max_windows=4)
        self.assertEqual(len(report.features), 4)
        self.assertTrue(report.sparse_windows)
        self.assertEqual(report.features[0].start_frame, 0)
        self.assertEqual(report.features[-1].start_frame, src.frame_count - report.window_size)
        self.assertEqual(sorted(f.start_frame for f in report.features),
                         [f.start_frame for f in report.features])

    def test_dense_window_coverage(self):
        src = make_sine(48000, duration=0.2)
        report = analyze_signal(src, window_size=4096, hop_size=2048, max_windows=20)
        self.assertFalse(report.sparse_windows)
        self.assertEqual(report.features[-1].start_frame, src.frame_count - 4096)

    def test_one_window_deterministic_start(self):
        src = make_sine(48000)
        report = analyze_signal(src, max_windows=1)
        self.assertEqual(len(report.features), 1)
        self.assertEqual(report.features[0].start_frame, 0)
        self.assertTrue(report.sparse_windows)
        self.assertEqual(report.features[0].spectral_flux, 0.0)

    def test_sparse_one_frame_hop_is_bounded(self):
        # O(1) window selection even if millions of theoretical hops.
        src = make_sine(48000, duration=0.4)
        result = analyze_signal(src, window_size=4096, hop_size=1, max_windows=3)
        self.assertEqual(len(result.features), 3)
        self.assertTrue(result.sparse_windows)

    def test_invalid_channel_and_shape(self):
        audio = make_sine()
        for ch in (True, -1, 1, 1.2):
            with self.subTest(ch=ch), self.assertRaises(SignalAnalysisError):
                analyze_signal(audio, channel=ch)
        invalid = WavAudio(48000, 1, "float", 32, 2000, (0.0,) * 1000)
        with self.assertRaises(SignalAnalysisError):
            analyze_signal(invalid)

    def test_nonfinite_rejected(self):
        src = make_sine()
        for value in (float("inf"), float("-inf"), float("nan")):
            samples = list(src.samples)
            samples[0] = value
            bad = WavAudio(src.sample_rate, 1, "float", 32, src.frame_count, tuple(samples))
            with self.subTest(value=value), self.assertRaises(SignalAnalysisError):
                analyze_signal(bad)

    def test_invalid_pitch_range(self):
        audio = make_sine()
        for pair in ((55, 55), (10, 2000), (55, 25000), (float("nan"), 2000),
                     (True, 2000), (55, float("inf"))):
            with self.subTest(pair=pair), self.assertRaises(SignalAnalysisError):
                analyze_signal(audio, min_f0_hz=pair[0], max_f0_hz=pair[1])

    def test_invalid_window_and_hop_sizes(self):
        audio = make_sine()
        for w in (True, 0, 256, 1500, 32768):
            with self.subTest(w=w), self.assertRaises(SignalAnalysisError):
                analyze_signal(audio, window_size=w)
        for h in (True, -1, 0, 8193):
            with self.subTest(h=h), self.assertRaises(SignalAnalysisError):
                analyze_signal(audio, window_size=4096, hop_size=h)

    def test_unresolvable_min_pitch_rejected(self):
        audio = make_sine(48000)
        with self.assertRaises(SignalAnalysisError):
            analyze_signal(audio, window_size=1024, min_f0_hz=55)

    def test_invalid_max_windows_and_audio_type(self):
        audio = make_sine()
        for maxw in (0, 65, True, 1.5):
            with self.subTest(maxw=maxw), self.assertRaises(SignalAnalysisError):
                analyze_signal(audio, max_windows=maxw)
        with self.assertRaises(TypeError):
            analyze_signal([0.0] * 4096)

    def test_too_short_audio_rejected(self):
        wav = WavAudio(48000, 1, "float", 32, 1000, (0.0,) * 1000)
        with self.assertRaises(SignalAnalysisError):
            analyze_signal(wav)

    def test_end_to_end_pcm_wav_decode_and_analysis(self):
        rate = 48000
        data = [int(16000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(12000)]
        payload = struct.pack("<" + "h" * len(data), *data)
        fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
        content = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        content += b"data" + struct.pack("<I", len(payload)) + payload
        wav = decode_wav(b"RIFF" + struct.pack("<I", len(content)) + content)
        processed = preprocess_audio(wav, remove_dc=True)
        result = analyze_signal(processed)
        self.assertAlmostEqual(result.median_f0_hz, 440, delta=2)
        self.assertEqual(result.sample_rate, rate)


if __name__ == "__main__":
    unittest.main()
