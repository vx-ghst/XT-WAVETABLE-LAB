"""M1 model invariants; strictly synthetic fixtures."""

import unittest

from xtwavetable.model import Table, Wave, negate_int8_modular


class WaveModelTests(unittest.TestCase):
    def test_half_cycle_constructs_128_samples(self):
        wave = Wave.from_half_cycle(range(-32, 32))
        self.assertEqual(len(wave.samples), 128)
        self.assertEqual(wave.half_cycle, tuple(range(-32, 32)))
        self.assertEqual(wave.samples[-1], 32)

    def test_signed_minimum_is_modular(self):
        wave = Wave.from_half_cycle([-128] * 64)
        self.assertEqual(wave.samples, (-128,) * 128)
        self.assertEqual(negate_int8_modular(-128), -128)

    def test_signed_maximum(self):
        wave = Wave.from_half_cycle([127] * 64)
        self.assertEqual(wave.samples[64:], (-127,) * 64)

    def test_reject_wrong_size(self):
        for n in (0, 63, 65, 128):
            with self.subTest(n=n), self.assertRaises(ValueError):
                Wave.from_half_cycle([0] * n)

    def test_reject_out_of_range_or_bool(self):
        for sample in (-129, 128, True, 1.5):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                Wave.from_half_cycle([sample] + [0] * 63)

    def test_reject_broken_mirror(self):
        valid = list(Wave.from_half_cycle(range(64)).samples)
        valid[127] = valid[126]
        with self.assertRaises(ValueError):
            Wave(tuple(valid))


class TableModelTests(unittest.TestCase):
    def test_raw_references_and_reserved_preserved(self):
        table = Table((1000,) * 61 + (0xDEAD, 0xBEEF, 0xFFFF))
        self.assertEqual(table.reserved_positions, (0xDEAD, 0xBEEF, 0xFFFF))
        changed = table.with_user_positions(range(1000, 1061))
        self.assertEqual(changed.user_positions, tuple(range(1000, 1061)))
        self.assertEqual(changed.reserved_positions, table.reserved_positions)

    def test_semantic_check_does_not_mutate(self):
        table = Table((999, 1250, 0xDEAD) + (1000,) * 58 + (0xFFFF,) * 3)
        self.assertEqual(table.invalid_user_references(),
                         ((0, 999), (1, 1250), (2, 0xDEAD)))
        self.assertEqual(table.wave_ids[0], 999)

    def test_wrong_size_and_range(self):
        for entries in ((1000,) * 63, (1000,) * 65, (0x10000,) * 64, (-1,) * 64):
            with self.subTest(entries=entries[:1]), self.assertRaises(ValueError):
                Table(entries)

    def test_boolean_reference_rejected(self):
        with self.assertRaises(ValueError):
            Table((True,) + (1000,) * 63)

    def test_reserved_positions_cannot_be_edited_via_user_api(self):
        table = Table((1000,) * 61 + (0xDEAD, 0xBEEF, 0xFFFF))
        with self.assertRaises(ValueError):
            table.with_user_positions((1000,) * 64)
        with self.assertRaises(ValueError):
            table.with_user_positions((999,) * 61)


if __name__ == "__main__":
    unittest.main()
