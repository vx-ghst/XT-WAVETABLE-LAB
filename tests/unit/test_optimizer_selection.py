"""M2.5 entirely synthetic selection and editable XT table reference plans."""

import dataclasses
import math
import unittest

from xtwavetable.audio.wav_reader import WavAudio
from xtwavetable.codec_xt.sysex import decode_wave_dump, encode_wave_dump
from xtwavetable.converter.cycles import (CycleCandidate, CycleExtraction,
                                          extract_wave_candidates)
from xtwavetable.model import Wave
from xtwavetable.optimizer.selection import (EDITABLE_TABLE_POSITIONS,
                                              WaveSelection, WaveSelectionError,
                                              select_wave_plan,
                                              wave_rms_distance)


def make_candidate(index, number, *, error=0.001, frames=10000):
    # Constant half-cycles are legitimate XT wire vectors; all values are
    # distinct after 8-bit quantization for numbers 0..60.
    wave = Wave.from_half_cycle([number - 30] * 64)
    return CycleCandidate(index=index, anchor_frame=index * (frames / 80),
                          phase_start_frame=0., period_frames=100., pitch_hz=480.,
                          dc_reference=0., source_cycle_rms=0.5,
                          source_cycle_peak=0.7, projection_rms_error=error,
                          projected_peak=0.5, gain_linear=1.,
                          quantized_peak=abs(number - 30), wave=wave)


def source(*numbers, errors=None):
    items = tuple(make_candidate(i, number,
                                 error=(errors[i] if errors is not None else 0.001))
                  for i, number in enumerate(numbers))
    return CycleExtraction(48000, 0, 10000, "explicit", "uniform", False, items)


class OptimizerTests(unittest.TestCase):
    def test_uniform_61_unique(self):
        plan = select_wave_plan(source(*range(61)), requested_waves=61)
        self.assertEqual(len(plan.waves), 61)
        self.assertEqual(plan.editable_wave_indices, tuple(range(61)))
        self.assertEqual([c.index for c in plan.selected], list(range(61)))
        self.assertFalse(plan.has_shortfall)
        self.assertEqual(plan.exact_duplicates, 0)

    def test_8_16_32_61_wave_budgets(self):
        original = source(*range(61))
        for budget in (8, 16, 32, 61):
            with self.subTest(budget=budget):
                plan = select_wave_plan(original, requested_waves=budget)
                self.assertEqual(plan.actual_distinct_waves, budget)
                self.assertEqual(plan.requested_waves, budget)
                self.assertEqual(len(plan.editable_wave_indices), 61)
                self.assertEqual(set(plan.editable_wave_indices), set(range(budget)))
                self.assertTrue(all(0 <= i < budget for i in plan.editable_wave_indices))

    def test_uniform_source_endpoints_covered(self):
        plan = select_wave_plan(source(*range(61)), requested_waves=8)
        self.assertEqual(plan.selected[0].index, 0)
        self.assertEqual(plan.selected[-1].index, 60)
        self.assertEqual([c.index for c in plan.selected], sorted(c.index for c in plan.selected))

    def test_uniform_single_selects_center(self):
        plan = select_wave_plan(source(*range(7)), requested_waves=1)
        self.assertEqual(plan.selected[0].index, 3)
        self.assertIsNone(plan.minimum_selected_distance)
        self.assertEqual(plan.editable_wave_indices, (0,) * 61)

    def test_more_requested_than_unique_rejected_default(self):
        with self.assertRaisesRegex(WaveSelectionError, "insufficient distinct"):
            select_wave_plan(source(*([3] * 61)), requested_waves=8)

    def test_shortfall_reuse_is_explicit_and_auditable(self):
        plan = select_wave_plan(source(*([3] * 61)), requested_waves=61, shortfall="reuse")
        self.assertTrue(plan.has_shortfall)
        self.assertEqual(plan.actual_distinct_waves, 1)
        self.assertEqual(plan.exact_duplicates, 60)
        self.assertEqual(plan.editable_wave_indices, (0,) * 61)
        self.assertEqual(plan.requested_waves, 61)

    def test_reuse_distribution_two_waves(self):
        plan = select_wave_plan(source(1, 2), requested_waves=8, shortfall="reuse")
        self.assertEqual(plan.actual_distinct_waves, 2)
        self.assertEqual(plan.editable_wave_indices[:30], (0,) * 30)
        self.assertEqual(plan.editable_wave_indices[31:], (1,) * 30)
        self.assertTrue(plan.has_shortfall)

    def test_representative_with_lower_error_selected(self):
        plan = select_wave_plan(source(7, 7, 3, errors=[0.7, 0.01, 0.02]),
                                requested_waves=2)
        self.assertEqual([c.index for c in plan.selected], [1, 2])
        self.assertEqual(plan.exact_duplicates, 1)

    def test_equal_error_keeps_first_chronological(self):
        plan = select_wave_plan(source(4, 4, 5), requested_waves=2)
        self.assertEqual([c.index for c in plan.selected], [0, 2])

    def test_diversity_selects_maximin_distinct_waves(self):
        plan = select_wave_plan(source(0, 1, 2, 20, 40, 60),
                                requested_waves=3, strategy="diversity")
        self.assertEqual([c.index for c in plan.selected], [0, 3, 5])
        self.assertGreater(plan.minimum_selected_distance, 0)
        self.assertEqual(len(plan.editable_wave_indices), 61)

    def test_diversity_ties_by_error_then_index(self):
        plan = select_wave_plan(source(0, 40, 20, 60, errors=[0, 0.5, 0.1, 0.3]),
                                requested_waves=2, strategy="diversity")
        self.assertEqual([c.index for c in plan.selected], [0, 3])
        # candidates 40 and 20 are irrelevant because 60 is farthest

    def test_diversity_full_selection_preserves_order(self):
        plan = select_wave_plan(source(*range(8)), requested_waves=8, strategy="diversity")
        self.assertEqual([c.index for c in plan.selected], list(range(8)))

    def test_diversity_reproducibility(self):
        s = source(*range(61))
        first = select_wave_plan(s, requested_waves=16, strategy="diversity")
        self.assertEqual(first, select_wave_plan(s, requested_waves=16, strategy="diversity"))

    def test_projection_gate_excludes_only_when_requested(self):
        s = source(0, 1, 2, 3, errors=[0.05, 0.5, 0.01, 0.8])
        plan = select_wave_plan(s, requested_waves=2, max_projection_rms_error=0.1)
        self.assertEqual(plan.excluded_by_projection, 2)
        self.assertEqual([c.index for c in plan.selected], [0, 2])
        plain = select_wave_plan(s, requested_waves=4)
        self.assertEqual(plain.excluded_by_projection, 0)

    def test_projection_gate_all_excluded(self):
        with self.assertRaisesRegex(WaveSelectionError, "all candidates"):
            select_wave_plan(source(1, 2), max_projection_rms_error=0.0001)

    def test_projection_gate_shortfall_rejected(self):
        with self.assertRaisesRegex(WaveSelectionError, "insufficient distinct"):
            select_wave_plan(source(1, 2, 3, errors=[0.0001, 0.002, 0.003]), requested_waves=2,
                             max_projection_rms_error=0.0005)

    def test_invalid_requested_count_bool_float_and_range(self):
        for count in (True, False, 0, -1, 62, 1.5, "8", None):
            with self.subTest(count=count), self.assertRaises(WaveSelectionError):
                select_wave_plan(source(1, 2), requested_waves=count)

    def test_invalid_modes(self):
        for strategy in ("random", None, True, 5):
            with self.subTest(strategy=strategy), self.assertRaises(WaveSelectionError):
                select_wave_plan(source(1), strategy=strategy)
        for shortfall in ("fill", None, True, 6):
            with self.subTest(shortfall=shortfall), self.assertRaises(WaveSelectionError):
                select_wave_plan(source(1), shortfall=shortfall)

    def test_invalid_projection_gate(self):
        for value in (True, -0.01, math.nan, math.inf, -math.inf, "0.2"):
            with self.subTest(value=value), self.assertRaises(WaveSelectionError):
                select_wave_plan(source(1), max_projection_rms_error=value)

    def test_invalid_extraction_type_and_empty(self):
        with self.assertRaises(TypeError):
            select_wave_plan(None)
        with self.assertRaises(WaveSelectionError):
            select_wave_plan(source())

    def test_corrupt_candidate_diagnostics(self):
        s = source(1)
        c = s.candidates[0]
        for change in ({"projection_rms_error": math.nan}, {"projection_rms_error": -1.},
                       {"anchor_frame": math.inf}, {"anchor_frame": -1.},
                       {"index": True}, {"index": 99}):
            with self.subTest(change=change), self.assertRaises(WaveSelectionError):
                select_wave_plan(dataclasses.replace(s, candidates=(dataclasses.replace(c, **change),)))

    def test_bad_candidate_chronology(self):
        s = source(1, 2)
        with self.assertRaises(WaveSelectionError):
            select_wave_plan(dataclasses.replace(s, candidates=tuple(reversed(s.candidates))))

    def test_bad_duplicate_index(self):
        s = source(1, 2)
        with self.assertRaises(WaveSelectionError):
            select_wave_plan(dataclasses.replace(s, candidates=(s.candidates[0],
                                                               dataclasses.replace(s.candidates[1], index=0))))

    def test_raw_wave_distance_symmetry_and_boundaries(self):
        low = Wave.from_half_cycle([-127] * 64)
        high = Wave.from_half_cycle([127] * 64)
        self.assertEqual(wave_rms_distance(low, low), 0.0)
        self.assertAlmostEqual(wave_rms_distance(low, high), 2.0)
        self.assertEqual(wave_rms_distance(low, high), wave_rms_distance(high, low))
        with self.assertRaises(TypeError):
            wave_rms_distance(low, None)

    def test_reserved_positions_untouched_by_plan(self):
        plan = select_wave_plan(source(*range(61)), requested_waves=8)
        self.assertEqual(EDITABLE_TABLE_POSITIONS, 61)
        self.assertEqual(len(plan.editable_wave_indices), 61)
        self.assertFalse(hasattr(plan, "reserved_positions"))
        self.assertFalse(hasattr(plan, "table_id"))

    def test_source_immutability(self):
        original = source(*range(61))
        before = tuple(original.candidates)
        select_wave_plan(original, requested_waves=16, strategy="diversity")
        self.assertEqual(before, original.candidates)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            original.candidates[0].index = 123

    def test_synthetic_codec_roundtrip_for_selected_waves(self):
        plan = select_wave_plan(source(*range(8)), requested_waves=8)
        for index, c in enumerate(plan.selected):
            packet = encode_wave_dump(1000 + index, c.wave)
            self.assertEqual(decode_wave_dump(packet).wave, c.wave)

    def test_end_to_end_real_m24_candidates_with_explicit_reuse(self):
        rate = 48000
        audio = WavAudio(rate, 1, "float", 32, 24000, tuple(
            0.5 * math.sin(2 * math.pi * 440 * i / rate) for i in range(24000)))
        extracted = extract_wave_candidates(audio, pitch_hz=440, count=8)
        plan = select_wave_plan(extracted, requested_waves=8, shortfall="reuse")
        self.assertIsInstance(plan, WaveSelection)
        self.assertEqual(len(plan.editable_wave_indices), 61)
        self.assertEqual(plan.available_candidates, 8)
        self.assertGreaterEqual(plan.actual_distinct_waves, 1)
        self.assertLessEqual(plan.actual_distinct_waves, 8)

    def test_wave_set_not_memory_aliases_to_mutable_list(self):
        selected = select_wave_plan(source(2, 5), requested_waves=2)
        self.assertIsInstance(selected.waves, tuple)
        self.assertIsInstance(selected.editable_wave_indices, tuple)
        self.assertEqual(selected.waves[0], selected.selected[0].wave)


if __name__ == "__main__":
    unittest.main()
