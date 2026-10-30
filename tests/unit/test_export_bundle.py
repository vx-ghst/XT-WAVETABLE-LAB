"""M2.6 offline export: synthetic Everything snapshots and fail-closed gates."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from xtwavetable.codec_xt import (decode_table_dump, decode_wave_dump,
                                  encode_table_dump, encode_wave_dump)
from xtwavetable.converter.cycles import CycleCandidate, CycleExtraction
from xtwavetable.export import (DumpSnapshot, ExportPlanError, build_export_bundle,
                                inspect_snapshot, write_export_bundle)
from xtwavetable.model import Table, Wave
from xtwavetable.optimizer import select_wave_plan


def selected(n=8):
    frames = 10000
    items = tuple(CycleCandidate(
        index=i, anchor_frame=100. + 80.*i, phase_start_frame=10.,
        period_frames=100., pitch_hz=480., dc_reference=0.,
        source_cycle_rms=0.4, source_cycle_peak=0.6,
        projection_rms_error=0.001 + i * 0.00001,
        projected_peak=0.5, gain_linear=1., quantized_peak=100,
        wave=Wave.from_half_cycle([i - 30] * 64)) for i in range(n))
    source = CycleExtraction(48000, 0, frames, "explicit", "uniform", False, items)
    return select_wave_plan(source, requested_waves=n)


def make_messages(*, special=False):
    # 250 unique user wave IDs: even unreferenced slots contain existing data.
    waves = tuple(encode_wave_dump(1000 + i,
                  Wave.from_half_cycle([i % 250 - 125] * 64)) for i in range(250))
    tables = []
    for number in range(96, 128):
        first = ([0x12DE, 0xC0DE] + [1000] * 59) if (special and number == 96) else [1000] * 61
        table = Table(tuple(first) + (0xDEAD, 0xBEEF, 0xFFFF))
        tables.append(encode_table_dump(number, table))
    return waves, tuple(tables)


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.waves, cls.tables = make_messages()
        cls.blob = b"".join(cls.waves + cls.tables)

    def test_exact_complete_backup(self):
        snap = inspect_snapshot(self.blob)
        self.assertIsInstance(snap, DumpSnapshot)
        self.assertEqual(len(snap.wave_dumps), 250)
        self.assertEqual(len(snap.table_dumps), 32)
        self.assertEqual(snap.unvalidated_other_messages, 0)
        self.assertEqual(snap.input_sha256, hashlib.sha256(self.blob).hexdigest())
        self.assertEqual((snap.wave_dumps[0].wave_id, snap.wave_dumps[-1].wave_id), (1000, 1249))
        self.assertEqual((snap.table_dumps[0].table_id, snap.table_dumps[-1].table_id), (96, 127))

    def test_other_commands_not_certified(self):
        other = b"\xf0\x3e\x0e\x7f\x10\xf7"
        snap = inspect_snapshot(other + self.blob)
        self.assertEqual(snap.unvalidated_other_messages, 1)
        self.assertEqual(snap.input_sha256, hashlib.sha256(other + self.blob).hexdigest())

    def test_missing_wave_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, "complete backup"):
            inspect_snapshot(b"".join(self.waves[:-1] + self.tables))

    def test_missing_table_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, "complete backup"):
            inspect_snapshot(b"".join(self.waves + self.tables[:-1]))

    def test_duplicate_wave_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, "duplicate"):
            inspect_snapshot(self.blob + self.waves[0])

    def test_duplicate_table_rejected(self):
        with self.assertRaisesRegex(ExportPlanError, "duplicate"):
            inspect_snapshot(self.blob + self.tables[0])

    def test_corrupt_wave_checksum_rejected(self):
        bad = bytearray(self.waves[0]); bad[-2] ^= 1
        with self.assertRaisesRegex(ExportPlanError, "invalid standard XT"):
            inspect_snapshot(bytes(bad) + b"".join(self.waves[1:] + self.tables))

    def test_non_user_wave_rejected(self):
        rom = encode_wave_dump(500, Wave.from_half_cycle([0]*64), require_user_slot=False)
        with self.assertRaisesRegex(ExportPlanError, "non-user"):
            inspect_snapshot(self.blob + rom)

    def test_unterminated_and_nested_and_stray(self):
        for payload in (b"", b"\x00" + self.blob, self.blob[:-1],
                        b"\xf0\x01\xf0\xf7" + self.blob, 5, "abc"):
            with self.subTest(value=str(payload)[:10]), self.assertRaises(ExportPlanError):
                inspect_snapshot(payload)

    def test_snapshot_no_input_mutation(self):
        before = hashlib.sha256(self.blob).digest()
        inspect_snapshot(self.blob)
        self.assertEqual(before, hashlib.sha256(self.blob).digest())


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        waves, tables = make_messages()
        cls.dump = b"".join(waves + tables)
        cls.snapshot = inspect_snapshot(cls.dump)
        cls.plan = selected()

    def args(self, **kwargs):
        base = dict(selection=self.plan, snapshot=self.snapshot,
                    wave_ids=tuple(range(1200, 1208)), table_id=96,
                    authorized_replacement_wave_ids=tuple(range(1200, 1208)),
                    authorize_table_replacement=True)
        base.update(kwargs)
        return base

    def test_emitted_packet_count_and_exact_decode(self):
        result = build_export_bundle(**self.args())
        self.assertEqual(result.sysex.count(b"\xf0"), 9)
        self.assertEqual(len(result.sysex), 8 * 137 + 265)
        for i in range(8):
            part = result.sysex[i*137:(i+1)*137]
            self.assertEqual(decode_wave_dump(part).wave_id, 1200 + i)
            self.assertEqual(decode_wave_dump(part).wave, self.plan.waves[i])
        last = decode_table_dump(result.sysex[-265:])
        self.assertEqual(last.table_id, 96)
        self.assertEqual(last.table, result.table)

    def test_reserved_positions_exact(self):
        result = build_export_bundle(**self.args())
        self.assertEqual(result.table.reserved_positions, (0xDEAD, 0xBEEF, 0xFFFF))
        self.assertEqual(result.table.user_positions,
                         tuple(result.wave_ids[i] for i in self.plan.editable_wave_indices))

    def test_manifest_reproducible_canonical(self):
        first = build_export_bundle(**self.args())
        second = build_export_bundle(**self.args())
        self.assertEqual(first, second)
        data = json.loads(first.manifest_json)
        self.assertEqual(data["schema"], "xtwavetable.m2.6.offline_export.v1")
        self.assertEqual(data["source_snapshot_sha256"], hashlib.sha256(self.dump).hexdigest())
        self.assertEqual(data["output_sysex_sha256"], hashlib.sha256(first.sysex).hexdigest())
        self.assertEqual(data["actual_distinct_waves"], 8)
        self.assertEqual(data["reserved_table_references_preserved"], [0xDEAD, 0xBEEF, 0xFFFF])
        self.assertEqual(data["unvalidated_snapshot_commands"], 0)
        self.assertNotIn("C:\\", first.manifest_json.decode())

    def test_requires_authorize_every_replaced_wave(self):
        for auth in ((), (1200,), tuple(range(1200, 1209)),
                     tuple(range(1200, 1207)) + (1200,), (True,) + tuple(range(1201, 1208))):
            with self.subTest(auth=auth), self.assertRaisesRegex(ExportPlanError, "authorization"):
                build_export_bundle(**self.args(authorized_replacement_wave_ids=auth))

    def test_requires_table_authorization(self):
        for value in (False, 1, None, "true"):
            with self.subTest(value=value), self.assertRaisesRegex(ExportPlanError, "table replacement"):
                build_export_bundle(**self.args(authorize_table_replacement=value))

    def test_bad_slot_ids_and_counts(self):
        for ids in ((999,) + tuple(range(1201, 1208)), (1250,) + tuple(range(1201, 1208)),
                    (1200,)*8, tuple(range(1200, 1207)), (True,) + tuple(range(1201, 1208)),
                    list(range(1200, 1208))):
            with self.subTest(ids=ids), self.assertRaisesRegex(ExportPlanError, "wave_ids"):
                build_export_bundle(**self.args(wave_ids=ids))

    def test_bad_table_id(self):
        for n in (95, 128, 1000, True, "96", None):
            with self.subTest(n=n), self.assertRaisesRegex(ExportPlanError, "table_id"):
                build_export_bundle(**self.args(table_id=n))

    def test_known_external_refs_reject_by_default(self):
        ids = tuple(range(1000, 1008))
        with self.assertRaisesRegex(ExportPlanError, "other tables"):
            build_export_bundle(**self.args(wave_ids=ids, authorized_replacement_wave_ids=ids))

    def test_known_external_refs_explicit_ack(self):
        ids = tuple(range(1000, 1008))
        bundle = build_export_bundle(**self.args(wave_ids=ids, authorized_replacement_wave_ids=ids,
                                                 acknowledge_cross_table_references=True))
        self.assertEqual(bundle.known_cross_table_ids, tuple(range(97, 128)))
        self.assertEqual(json.loads(bundle.manifest_json)["known_cross_table_references"], list(range(97, 128)))

    def test_invalid_cross_table_acknowledge(self):
        with self.assertRaisesRegex(ExportPlanError, "boolean"):
            build_export_bundle(**self.args(acknowledge_cross_table_references=1))

    def test_special_destination_table_rejected(self):
        waves, tables = make_messages(special=True)
        bad = inspect_snapshot(b"".join(waves + tables))
        with self.assertRaisesRegex(ExportPlanError, "special table"):
            build_export_bundle(**self.args(snapshot=bad))

    def test_61_waves_and_full_editable_table(self):
        p = selected(61)
        ids = tuple(range(1160, 1221))
        result = build_export_bundle(**self.args(selection=p, wave_ids=ids,
                                    authorized_replacement_wave_ids=ids))
        self.assertEqual(len(result.sysex), 61*137 + 265)
        self.assertEqual(result.table.user_positions, ids)

    def test_single_wave_with_repeated_reference(self):
        p = selected(1)
        result = build_export_bundle(**self.args(selection=p, wave_ids=(1249,),
                                    authorized_replacement_wave_ids=(1249,)))
        self.assertEqual(result.table.user_positions, (1249,) * 61)
        self.assertEqual(result.sysex.count(b"\xf0"), 2)

    def test_selection_map_invalid_rejected(self):
        for values in ((0,)*60, (0,)*60 + (200,), (0,)*61):
            with self.subTest(values=values[:4]), self.assertRaisesRegex(ExportPlanError, "selection map|every wave"):
                p = replace(self.plan, editable_wave_indices=values)
                build_export_bundle(**self.args(selection=p))

    def test_invalid_types_and_device_id(self):
        with self.assertRaises(TypeError):
            build_export_bundle(**self.args(selection=None))
        with self.assertRaises(TypeError):
            build_export_bundle(**self.args(snapshot=None))
        for d in (True, -1, 128, 1.0, None):
            with self.subTest(d=d), self.assertRaisesRegex(ExportPlanError, "device_id"):
                build_export_bundle(**self.args(device_id=d))

    def test_incomplete_forged_snapshot_rejected(self):
        bad = replace(self.snapshot, wave_dumps=self.snapshot.wave_dumps[:-1])
        with self.assertRaisesRegex(ExportPlanError, "complete"):
            build_export_bundle(**self.args(snapshot=bad))

    def test_original_snapshot_unchanged(self):
        before = hashlib.sha256(self.dump).digest()
        build_export_bundle(**self.args())
        self.assertEqual(before, hashlib.sha256(self.dump).digest())

    def test_explicit_no_overwrite_file_export(self):
        bundle = build_export_bundle(**self.args())
        with tempfile.TemporaryDirectory() as tmp:
            syx, report = write_export_bundle(bundle, tmp)
            self.assertEqual(syx.read_bytes(), bundle.sysex)
            self.assertEqual(report.read_bytes(), bundle.manifest_json)
            with self.assertRaises(FileExistsError):
                write_export_bundle(bundle, tmp)
            self.assertEqual(syx.read_bytes(), bundle.sysex)
            self.assertEqual(report.read_bytes(), bundle.manifest_json)

    def test_existing_json_guard_even_if_syx_absent(self):
        bundle = build_export_bundle(**self.args())
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "xt_candidate.json"
            original.write_bytes(b"DO NOT MODIFY")
            with self.assertRaises(FileExistsError):
                write_export_bundle(bundle, tmp)
            self.assertEqual(original.read_bytes(), b"DO NOT MODIFY")
            self.assertFalse((Path(tmp)/"xt_candidate.syx").exists())

    def test_file_write_validates_destination_and_stem(self):
        bundle = build_export_bundle(**self.args())
        with tempfile.TemporaryDirectory() as tmp:
            for stem in ("", "../bad", "my:file", "odd space", ".hidden", "à"):
                with self.subTest(stem=stem), self.assertRaises(ExportPlanError):
                    write_export_bundle(bundle, tmp, stem=stem)
            with self.assertRaises(ExportPlanError):
                write_export_bundle(bundle, str(Path(tmp)/"nonexistent"))

    def test_multiple_user_table_slots(self):
        for table_id in (96, 108, 127):
            with self.subTest(table_id=table_id):
                result = build_export_bundle(**self.args(table_id=table_id))
                self.assertEqual(result.table_id, table_id)
                self.assertEqual(result.table.reserved_positions, (0xDEAD, 0xBEEF, 0xFFFF))


if __name__ == "__main__":
    unittest.main()
