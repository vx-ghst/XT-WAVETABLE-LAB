"""M1 inventory tests with synthetic SysEx only: no firmware/dumps required."""
import tempfile
from pathlib import Path
import unittest

from scripts.audit.xt_codec_inventory import InventoryError, inspect_dump, main, split_messages
from xtwavetable.codec_xt import encode_wave_dump, encode_table_dump
from xtwavetable.model import Wave, Table


def make_wave(idx=1000):
    return encode_wave_dump(idx, Wave.from_half_cycle([idx % 25] * 64))


def make_table(idx=96, refs=None):
    if refs is None:
        refs = (1000,) * 61 + (0xDEAD, 0xBEEF, 0xFFFF)
    return encode_table_dump(idx, Table(tuple(refs)))


class SplitTests(unittest.TestCase):
    def test_split(self):
        a, b = make_wave(), make_table()
        self.assertEqual(split_messages(a+b), (a, b))

    def test_reject_nested_unterminated_stray_and_empty(self):
        for blob in (b"", b"\xf0\x01", b"x"+make_wave(), b"\xf0\xf0\xf7"):
            with self.subTest(blob=blob[:10]), self.assertRaises(InventoryError):
                split_messages(blob)


class InventoryTests(unittest.TestCase):
    def test_counts_and_byte_identical_roundtrip(self):
        report = inspect_dump(make_wave()+make_table())
        self.assertEqual(report["message_count"], 2)
        self.assertEqual(report["exact_wave_table_roundtrips"], 2)
        self.assertEqual(report["referenced_user_wave_ids"], [1000])
        self.assertEqual(report["unreferenced_dumped_user_wave_ids_not_proven_free"], [])
        self.assertFalse(report["complete_user_wave_table_set"])

    def test_reserved_signature_preserved_and_not_interpreted(self):
        report = inspect_dump(make_wave()+make_table())
        self.assertEqual(report["distinct_reserved_position_signatures"], 1)
        self.assertEqual(report["nonstandard_editable_reference_counts_not_necessarily_errors"], {})

    def test_nonstandard_placeholder_not_error(self):
        refs=(1000,)+(0xFFFF,)*60 + (0,0,0)
        report=inspect_dump(make_wave()+make_table(refs=refs))
        self.assertEqual(report["nonstandard_editable_reference_counts_not_necessarily_errors"],
                         {"0xFFFF":60})

    def test_nonstandard_upaw_special_not_misclassified(self):
        refs=(0x12DE,0xC0DE)+(0xFFFF,)*59+(0,0,0)
        report=inspect_dump(make_wave()+make_table(refs=refs))
        self.assertEqual(report["table_kind_counts"], {"upaw":1})
        self.assertEqual(report["nonstandard_editable_reference_counts_not_necessarily_errors"], {})

    def test_speech_references_eight_waves(self):
        refs=(0xDEAD,0xBEEF,1000)+(0xFFFF,)*58+(0,0,0)
        report=inspect_dump(make_wave()+make_table(refs=refs))
        self.assertEqual(report["table_kind_counts"], {"speech":1})
        self.assertEqual(report["referenced_user_wave_ids"], list(range(1000,1008)))
        self.assertEqual(report["referenced_user_waves_not_in_dump"], list(range(1001,1008)))

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(InventoryError, "duplicate wave"):
            inspect_dump(make_wave()+make_wave())
        with self.assertRaisesRegex(InventoryError, "duplicate table"):
            inspect_dump(make_table()+make_table())

    def test_bad_checksum_rejected(self):
        bad=bytearray(make_wave());bad[-2]^=1
        with self.assertRaisesRegex(InventoryError, "invalid wave/table"):
            inspect_dump(bytes(bad))

    def test_unsupported_is_only_counted(self):
        other=b"\xf0\x3e\x0e\x7f\x10\x00\xf7"
        report=inspect_dump(other+make_wave())
        self.assertEqual(report["other_command_counts_unvalidated"], {"0x10":1})
        self.assertEqual(report["exact_wave_table_roundtrips"], 1)

    def test_require_complete_fails_incomplete(self):
        with self.assertRaisesRegex(InventoryError, "incomplete"):
            inspect_dump(make_wave()+make_table(), require_complete=True)

    def test_cli_writes_once_and_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"test.syx";out=Path(d)/"inventory.json"
            raw=make_wave()+make_table();src.write_bytes(raw)
            self.assertEqual(main(["--input",str(src),"--out",str(out)]),0)
            self.assertEqual(src.read_bytes(),raw)
            self.assertTrue(out.is_file())
            with self.assertRaises(SystemExit):
                main(["--input",str(src),"--out",str(out)])
            self.assertEqual(src.read_bytes(),raw)


if __name__ == "__main__":
    unittest.main()
