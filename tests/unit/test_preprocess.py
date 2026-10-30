"""M2.2 deterministic frame-domain preprocessing, synthetic samples only."""

import math
import unittest
from decimal import Decimal

from xtwavetable.audio.preprocess import (
    AudioProcessingError, frame_bounds_from_seconds, preprocess_audio,
)
from xtwavetable.audio.wav_reader import WavAudio


def make_audio(samples, channels=1, rate=48000, encoding="float", bits=32):
    return WavAudio(rate, channels, encoding, bits, len(samples) // channels, tuple(samples))


class PreprocessTests(unittest.TestCase):
    def test_defaults_preserve_samples_and_metadata(self):
        src = make_audio((0.4, -0.3, 0.2, 0.8), channels=2)
        out = preprocess_audio(src)
        self.assertEqual(out.samples, src.samples)
        self.assertEqual(out.channels, 2)
        self.assertEqual(out.source_start_frame, 0)
        self.assertEqual(out.source_end_frame, 2)
        self.assertEqual(out.dc_offsets, (0.0, 0.0))
        self.assertEqual(out.gain_linear, 1.0)

    def test_crop_is_frame_aligned_and_end_exclusive(self):
        src = make_audio((0, 1, 2, 3, 4, 5, 6, 7), channels=2)
        out = preprocess_audio(src, start_frame=1, end_frame=3)
        self.assertEqual(out.samples, (2, 3, 4, 5))
        self.assertEqual(out.frame_count, 2)
        self.assertEqual(src.samples, (0, 1, 2, 3, 4, 5, 6, 7))

    def test_crop_boundaries_and_invalid_ranges(self):
        src = make_audio((0.0, 1.0, 2.0))
        self.assertEqual(preprocess_audio(src, start_frame=2).samples, (2.0,))
        for a, b in ((0, 0), (3, None), (-1, 2), (2, 1), (0, 4), (True, 2), (0, False), (0.5, None)):
            with self.subTest(start=a, end=b), self.assertRaises(AudioProcessingError):
                preprocess_audio(src, start_frame=a, end_frame=b)

    def test_modes_stereo_left_right_average(self):
        src = make_audio((0.8, 0.2, -0.6, 0.4), channels=2)
        self.assertEqual(preprocess_audio(src, channel_mode="left").samples, (0.8, -0.6))
        self.assertEqual(preprocess_audio(src, channel_mode="right").samples, (0.2, 0.4))
        avg = preprocess_audio(src, channel_mode="average")
        self.assertEqual(avg.channels, 1)
        self.assertAlmostEqual(avg.samples[0], 0.5)
        self.assertAlmostEqual(avg.samples[1], -0.1)

    def test_antiphase_average_cancels_as_expected(self):
        src = make_audio((0.7, -0.7, -0.5, 0.5), channels=2)
        self.assertEqual(preprocess_audio(src, channel_mode="average").samples, (0.0, 0.0))

    def test_mono_modes_and_invalid_right(self):
        src = make_audio((0.1, 0.2))
        for mode in ("preserve", "left", "average"):
            with self.subTest(mode=mode):
                self.assertEqual(preprocess_audio(src, channel_mode=mode).samples, src.samples)
        with self.assertRaises(AudioProcessingError):
            preprocess_audio(src, channel_mode="right")

    def test_dc_removal_after_selection(self):
        src = make_audio((0.1, 0.3, 0.4, 0.6, 0.5, 0.7, 0.8, 1.0))
        out = preprocess_audio(src, start_frame=1, end_frame=3, remove_dc=True)
        self.assertAlmostEqual(out.samples[0], -0.05)
        self.assertAlmostEqual(out.samples[1], 0.05)
        self.assertAlmostEqual(out.dc_offsets[0], 0.35)

    def test_dc_per_channel_preserves_stereo_differences(self):
        src = make_audio((0.5, -0.2, 0.7, 0.0, 0.9, 0.2), channels=2)
        out = preprocess_audio(src, remove_dc=True)
        self.assertEqual(out.channels, 2)
        self.assertAlmostEqual(out.dc_offsets[0], 0.7)
        self.assertAlmostEqual(out.dc_offsets[1], 0.0)
        self.assertAlmostEqual(math.fsum(out.channel_samples(0)), 0.0)
        self.assertAlmostEqual(math.fsum(out.channel_samples(1)), 0.0)

    def test_dc_removal_after_downmix(self):
        src = make_audio((0.4, -0.2, 0.8, 0.2), channels=2)
        out = preprocess_audio(src, channel_mode="average", remove_dc=True)
        self.assertAlmostEqual(out.dc_offsets[0], 0.3)
        self.assertAlmostEqual(out.samples[0], -0.2)
        self.assertAlmostEqual(out.samples[1], 0.2)

    def test_peak_normalize_minus_three_db(self):
        src = make_audio((0.1, -0.25, 0.125))
        out = preprocess_audio(src, normalize_peak_dbfs=-3.0)
        self.assertAlmostEqual(out.peak_after_gain, 10 ** (-3.0 / 20.0))
        self.assertAlmostEqual(out.gain_linear, 10 ** (-3.0 / 20.0) / 0.25)
        self.assertEqual(src.samples, (0.1, -0.25, 0.125))

    def test_normalization_one_gain_across_stereo_channels(self):
        src = make_audio((0.1, 0.5, -0.25, -0.5), channels=2)
        out = preprocess_audio(src, normalize_peak_dbfs=-6)
        self.assertAlmostEqual(out.samples[0] / src.samples[0], out.samples[1] / src.samples[1])
        self.assertAlmostEqual(out.peak_after_gain, 10**(-6/20))

    def test_normalize_float_above_zero_dbfs_without_clipping(self):
        src = make_audio((1.5, -2.0, 0.5))
        out = preprocess_audio(src, normalize_peak_dbfs=0)
        self.assertEqual(out.peak_after_gain, 1.0)
        self.assertEqual(out.samples, (0.75, -1.0, 0.25))

    def test_silence_no_divide_by_zero(self):
        src = make_audio((0.0, 0.0, 0.0))
        out = preprocess_audio(src, remove_dc=True, normalize_peak_dbfs=-3)
        self.assertEqual(out.samples, src.samples)
        self.assertEqual(out.gain_linear, 1.0)
        self.assertEqual(out.peak_after_gain, 0.0)

    def test_dc_constant_input_yields_silence(self):
        src = make_audio((0.5, 0.5, 0.5))
        out = preprocess_audio(src, remove_dc=True, normalize_peak_dbfs=-3)
        self.assertEqual(out.samples, (0.0, 0.0, 0.0))
        self.assertEqual(out.gain_linear, 1.0)

    def test_no_hidden_resampling_at_rates(self):
        for rate in (44100, 48000, 88200, 96000, 192000):
            with self.subTest(rate=rate):
                a = make_audio((0.0, 0.2, -0.3), rate=rate)
                b = preprocess_audio(a, remove_dc=True)
                self.assertEqual(b.sample_rate, rate)
                self.assertEqual(b.frame_count, 3)
                self.assertEqual(b.duration_seconds, 3 / rate)

    def test_frame_bounds_seconds_cover_partial_frames(self):
        self.assertEqual(frame_bounds_from_seconds(1000, 2000, start_seconds=0.0012, end_seconds=0.0101), (1, 11))
        self.assertEqual(frame_bounds_from_seconds(48000, 96000, start_seconds=Decimal('0.5'), end_seconds=Decimal('1.25')), (24000, 60000))
        self.assertEqual(frame_bounds_from_seconds(44100, 1000), (0, 1000))

    def test_frame_bounds_bad_ranges_rejected(self):
        cases = ((-0.01, 0.1), (0.5, 0.1), (0.0, 0.0), (0.0, 2.0), (float('nan'), None), (0.0, float('inf')),
                 (True, None), ('0.1', None))
        for start, end in cases:
            with self.subTest(start=start, end=end), self.assertRaises(AudioProcessingError):
                frame_bounds_from_seconds(100, 100, start_seconds=start, end_seconds=end)

    def test_option_errors_rejected(self):
        src = make_audio((0.3, 0.5))
        for kw in (dict(channel_mode='side'), dict(remove_dc=1), dict(normalize_peak_dbfs=1),
                   dict(normalize_peak_dbfs=-121), dict(normalize_peak_dbfs=True),
                   dict(normalize_peak_dbfs=float('nan')), dict(normalize_peak_dbfs=float('inf'))):
            with self.subTest(kw=kw), self.assertRaises(AudioProcessingError):
                preprocess_audio(src, **kw)

    def test_invalid_audio_shape_and_nonfinite_rejected(self):
        bad = [WavAudio(48000, 2, 'float', 32, 3, (0.1, 0.2)),
               WavAudio(48000, 1, 'float', 32, 1, (float('nan'),)),
               WavAudio(48000, 1, 'float', 32, 1, (float('inf'),))]
        for a in bad:
            with self.subTest(a=a), self.assertRaises(AudioProcessingError):
                preprocess_audio(a)

    def test_source_is_immutable_and_output_is_frozen(self):
        src = make_audio((0.1, 0.2))
        out = preprocess_audio(src, remove_dc=True)
        with self.assertRaises((AttributeError, TypeError)):
            out.samples = (1.0,)
        self.assertEqual(src.samples, (0.1, 0.2))

    def test_channel_accessor(self):
        src = make_audio((0.1, -0.2, 0.3, -0.4), channels=2)
        out = preprocess_audio(src)
        self.assertEqual(out.channel_samples(0), (0.1, 0.3))
        self.assertEqual(out.channel_samples(1), (-0.2, -0.4))
        with self.assertRaises(IndexError):
            out.channel_samples(2)
        with self.assertRaises(IndexError):
            out.channel_samples(True)


if __name__ == '__main__':
    unittest.main()
