"""M1 standard XT SysEx codec tests (synthetic, reproducible, no hardware)."""

import random
import unittest

from xtwavetable.codec_xt import (TABLE_DUMP_LENGTH, WAVE_DUMP_LENGTH,
    XTChecksumError, XTFormatError, checksum, decode_table_dump,
    decode_wave_dump, encode_table_dump, encode_wave_dump)
from xtwavetable.model import Table, Wave


def wave_fixture():
    return Wave.from_half_cycle((i - 32 for i in range(64)))


def table_fixture():
    return Table(tuple(1000 + i for i in range(61)) + (0xDEAD, 0xBEEF, 0xFFFF))


class WaveCodecTests(unittest.TestCase):
    def test_exact_wire_geometry_and_header(self):
        raw = encode_wave_dump(1000, Wave.from_half_cycle([0] * 64))
        self.assertEqual(len(raw), WAVE_DUMP_LENGTH)
        self.assertEqual(raw[:7], bytes.fromhex("F0 3E 0E 7F 12 07 68"))
        self.assertEqual(raw[7:135], bytes([8, 0]) * 64)
        self.assertEqual(raw[-2:], bytes.fromhex("00 F7"))

    def test_boundary_ids(self):
        for wave_id in (1000, 1249):
            with self.subTest(wave_id=wave_id):
                packet = encode_wave_dump(wave_id, wave_fixture())
                self.assertEqual(decode_wave_dump(packet).wave_id, wave_id)
        for wave_id in (999, 1250, 506, 9999, -1):
            with self.subTest(wave_id=wave_id), self.assertRaises(XTFormatError):
                encode_wave_dump(wave_id, wave_fixture())

    def test_rom_dump_parse_and_explicit_override(self):
        with self.assertRaises(XTFormatError):
            encode_wave_dump(0, wave_fixture())
        raw = encode_wave_dump(0, wave_fixture(), require_user_slot=False)
        self.assertEqual(decode_wave_dump(raw).wave_id, 0)

    def test_roundtrip_fixed_min_max(self):
        for value in (-128, -127, 0, 127):
            with self.subTest(value=value):
                wave = Wave.from_half_cycle([value] * 64)
                raw = encode_wave_dump(1000, wave)
                obj = decode_wave_dump(raw)
                self.assertEqual(obj.wave, wave)
                self.assertEqual(encode_wave_dump(obj.wave_id, obj.wave,
                                                  device_id=obj.device_id), raw)

    def test_roundtrip_seeded_random(self):
        rng = random.Random(20261030)
        for _ in range(500):
            wave_id = rng.randrange(1000, 1250)
            half = [rng.randrange(-128, 128) for _ in range(64)]
            wave = Wave.from_half_cycle(half)
            packet = encode_wave_dump(wave_id, wave, device_id=17)
            decoded = decode_wave_dump(packet, expected_device_id=17)
            self.assertEqual(decoded.wave, wave)
            self.assertEqual(encode_wave_dump(decoded.wave_id, decoded.wave,
                                              device_id=decoded.device_id), packet)

    def test_reject_corrupt_checksum(self):
        raw = bytearray(encode_wave_dump(1000, wave_fixture()))
        raw[-2] ^= 1
        with self.assertRaises(XTChecksumError):
            decode_wave_dump(bytes(raw))

    def test_reject_bad_length(self):
        raw = encode_wave_dump(1000, wave_fixture())
        for packet in (raw[:-1], raw + b"\x00", b""):
            with self.subTest(n=len(packet)), self.assertRaises(XTFormatError):
                decode_wave_dump(packet)

    def test_reject_wrong_header_and_command(self):
        raw = encode_wave_dump(1000, wave_fixture())
        for idx, value in ((0, 1), (1, 0), (2, 0), (4, 0x19), (136, 0)):
            tampered = bytearray(raw)
            tampered[idx] = value
            with self.subTest(idx=idx), self.assertRaises(XTFormatError):
                decode_wave_dump(bytes(tampered))

    def test_reject_non_nibble_even_with_recomputed_checksum(self):
        raw = bytearray(encode_wave_dump(1000, wave_fixture()))
        raw[7] = 0x10
        raw[-2] = checksum(raw[7:-2])
        with self.assertRaises(XTFormatError):
            decode_wave_dump(bytes(raw))

    def test_reject_non_midi_7_bit(self):
        raw = bytearray(encode_wave_dump(1000, wave_fixture()))
        raw[8] = 0x80
        with self.assertRaises(XTFormatError):
            decode_wave_dump(bytes(raw))

    def test_reject_outside_index(self):
        raw = bytearray(encode_wave_dump(1000, wave_fixture()))
        raw[5], raw[6] = 0x07, 0x67  # 999
        with self.assertRaises(XTFormatError):
            decode_wave_dump(bytes(raw))

    def test_device_identity_is_optional_but_enforceable(self):
        raw = encode_wave_dump(1000, wave_fixture(), device_id=11)
        self.assertEqual(decode_wave_dump(raw).device_id, 11)
        with self.assertRaises(XTFormatError):
            decode_wave_dump(raw, expected_device_id=12)
        with self.assertRaises(XTFormatError):
            encode_wave_dump(1000, wave_fixture(), device_id=128)


class TableCodecTests(unittest.TestCase):
    def test_exact_wire_geometry_and_header(self):
        raw = encode_table_dump(96, table_fixture())
        self.assertEqual(len(raw), TABLE_DUMP_LENGTH)
        self.assertEqual(raw[:7], bytes.fromhex("F0 3E 0E 7F 13 00 60"))
        self.assertEqual(raw[7:11], bytes.fromhex("00 03 0E 08"))
        self.assertEqual(raw[251:263], bytes.fromhex("0D 0E 0A 0D 0B 0E 0E 0F 0F 0F 0F 0F"))

    def test_user_table_bounds(self):
        for table_id in (96, 127):
            self.assertEqual(decode_table_dump(encode_table_dump(table_id, table_fixture())).table_id,
                             table_id)
        for table_id in (95, 128, -1, 200):
            with self.assertRaises(XTFormatError):
                encode_table_dump(table_id, table_fixture())

    def test_allow_rom_table_on_explicit_roundtrip(self):
        raw = encode_table_dump(0, table_fixture(), require_user_slot=False)
        self.assertEqual(decode_table_dump(raw).table_id, 0)

    def test_roundtrip_seeded_random(self):
        rng = random.Random(314159)
        for _ in range(500):
            table_id = rng.randrange(96, 128)
            # Include all possible uint16 values in reserved positions,
            # and deliberately preserve arbitrary raw values on the wire.
            table = Table(tuple(rng.randrange(0, 65536) for _ in range(64)))
            raw = encode_table_dump(table_id, table, device_id=3)
            decoded = decode_table_dump(raw, expected_device_id=3)
            self.assertEqual(decoded.table, table)
            self.assertEqual(encode_table_dump(decoded.table_id, decoded.table,
                                               device_id=decoded.device_id), raw)

    def test_reject_table_corrupt_checksum(self):
        raw = bytearray(encode_table_dump(96, table_fixture()))
        raw[-2] ^= 1
        with self.assertRaises(XTChecksumError):
            decode_table_dump(bytes(raw))

    def test_reject_wrong_table_length(self):
        raw = encode_table_dump(96, table_fixture())
        with self.assertRaises(XTFormatError):
            decode_table_dump(raw + b"\xf7")

    def test_reject_table_non_nibble(self):
        raw = bytearray(encode_table_dump(96, table_fixture()))
        raw[8] = 0x10
        raw[-2] = checksum(raw[7:-2])
        with self.assertRaises(XTFormatError):
            decode_table_dump(bytes(raw))

    def test_reject_emulator_preview_command(self):
        raw = bytearray(encode_table_dump(96, table_fixture()))
        raw[4] = 0x1A
        with self.assertRaises(XTFormatError):
            decode_table_dump(bytes(raw))

    def test_reject_table_id_128(self):
        raw = bytearray(encode_table_dump(96, table_fixture()))
        raw[5], raw[6] = 1, 0  # 128
        with self.assertRaises(XTFormatError):
            decode_table_dump(bytes(raw))


if __name__ == "__main__":
    unittest.main()
