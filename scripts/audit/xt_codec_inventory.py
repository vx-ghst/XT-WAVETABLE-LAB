#!/usr/bin/env python3
"""Read-only M1 inspection of XT WaveDump/TableDump messages in a .syx stream.

Run from repository root: python -m scripts.audit.xt_codec_inventory --input ... --out ...
Proprietary input data and resulting reports must remain outside public Git.
No MIDI I/O, firmware access, or write-back to input.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from xtwavetable.codec_xt import (
    XTFormatError, decode_wave_dump, decode_table_dump,
    encode_wave_dump, encode_table_dump,
)
from xtwavetable.model import is_standard_wave_reference, is_user_wave_id

EXPECTED_WAVE_IDS = set(range(1000, 1250))
EXPECTED_TABLE_IDS = set(range(96, 128))


class InventoryError(ValueError):
    """Cannot establish a valid read-only SysEx inventory."""


def split_messages(blob: bytes) -> tuple[bytes, ...]:
    """Split consecutive raw SysEx packets, rejecting stray/incomplete frames."""
    if not isinstance(blob, bytes) or not blob:
        raise InventoryError("input must be nonempty bytes")
    result = []
    i = 0
    while i < len(blob):
        if blob[i] != 0xF0:
            raise InventoryError(f"unexpected byte at offset {i}")
        end = blob.find(b"\xf7", i + 1)
        if end < 0:
            raise InventoryError(f"unterminated SysEx at offset {i}")
        msg = blob[i:end + 1]
        if b"\xf0" in msg[1:-1]:
            raise InventoryError(f"nested F0 at offset {i}")
        result.append(msg)
        i = end + 1
    return tuple(result)


def _table_kind(references: tuple[int, ...]) -> str:
    if references[:2] == (0xDEAD, 0xBEEF):
        return "speech"
    if references[:2] == (0x12DE, 0xC0DE):
        return "upaw"
    return "ordinary_or_unclassified"


def inspect_dump(blob: bytes, *, require_complete: bool = False) -> dict:
    """Inspect standard Wave/Table messages without changing data.

    Reports *referenced* IDs only. An unreferenced wave is not certified free.
    Other dump types are counted but not validated in this M1 codec inspector.
    """
    messages = split_messages(blob)
    wave_ids: set[int] = set()
    table_ids: set[int] = set()
    referenced_user_waves: set[int] = set()
    referenced_rom_waves: set[int] = set()
    special_kinds: Counter[str] = Counter()
    nonstandard_editable: Counter[int] = Counter()
    reserved_fingerprints: set[str] = set()
    other_commands: Counter[str] = Counter()
    wave_count = 0
    table_count = 0
    roundtrip_count = 0

    for ordinal, packet in enumerate(messages):
        if len(packet) < 5:
            raise InventoryError(f"message {ordinal} too short")
        cmd = packet[4]
        try:
            if cmd == 0x12:
                item = decode_wave_dump(packet)
                if item.wave_id in wave_ids:
                    raise InventoryError(f"duplicate wave ID {item.wave_id}")
                wave_ids.add(item.wave_id)
                if encode_wave_dump(item.wave_id, item.wave, device_id=item.device_id,
                                    require_user_slot=False) != packet:
                    raise InventoryError(f"wave roundtrip mismatch at message {ordinal}")
                wave_count += 1
                roundtrip_count += 1
            elif cmd == 0x13:
                item = decode_table_dump(packet)
                if item.table_id in table_ids:
                    raise InventoryError(f"duplicate table ID {item.table_id}")
                table_ids.add(item.table_id)
                if encode_table_dump(item.table_id, item.table, device_id=item.device_id,
                                     require_user_slot=False) != packet:
                    raise InventoryError(f"table roundtrip mismatch at message {ordinal}")
                table_count += 1
                roundtrip_count += 1
                refs = item.table.wave_ids
                kind = _table_kind(refs)
                special_kinds[kind] += 1
                reserved_bytes = b"".join(x.to_bytes(2, "big") for x in refs[61:])
                reserved_fingerprints.add(hashlib.sha256(reserved_bytes).hexdigest())
                if kind == "speech":
                    # Mirrors Xenia's special-table interpretation: 8 waves from entry 2.
                    valid_refs = range(refs[2], refs[2] + 8)
                elif kind == "upaw":
                    # uPAW is algorithmic; ordinary IDs in the payload are not a wave list.
                    valid_refs = ()
                else:
                    valid_refs = refs[:61]
                    nonstandard_editable.update(x for x in valid_refs
                                                if not is_standard_wave_reference(x))
                for ref in valid_refs:
                    if is_user_wave_id(ref):
                        referenced_user_waves.add(ref)
                    elif is_standard_wave_reference(ref):
                        referenced_rom_waves.add(ref)
            else:
                other_commands[f"0x{cmd:02X}"] += 1
        except XTFormatError as exc:
            raise InventoryError(f"invalid wave/table at message {ordinal}: {exc}") from exc

    missing_waves = EXPECTED_WAVE_IDS - wave_ids
    missing_tables = EXPECTED_TABLE_IDS - table_ids
    complete = not missing_waves and not missing_tables and (
        wave_ids <= EXPECTED_WAVE_IDS and table_ids <= EXPECTED_TABLE_IDS)
    if require_complete and not complete:
        raise InventoryError("incomplete or nonstandard Everything wave/table inventory")
    known_missing_refs = referenced_user_waves - wave_ids
    return {
        "schema": "xtwavetable.m1.readonly_inventory.v1",
        "input_sha256": hashlib.sha256(blob).hexdigest(),
        "input_bytes": len(blob),
        "message_count": len(messages),
        "wave_message_count": wave_count,
        "table_message_count": table_count,
        "other_command_counts_unvalidated": dict(sorted(other_commands.items())),
        "exact_wave_table_roundtrips": roundtrip_count,
        "complete_user_wave_table_set": complete,
        "missing_user_wave_ids": sorted(missing_waves),
        "missing_user_table_ids": sorted(missing_tables),
        "extra_wave_ids": sorted(wave_ids - EXPECTED_WAVE_IDS),
        "extra_table_ids": sorted(table_ids - EXPECTED_TABLE_IDS),
        "referenced_user_wave_ids": sorted(referenced_user_waves),
        "referenced_rom_wave_ids": sorted(referenced_rom_waves),
        "referenced_user_waves_not_in_dump": sorted(known_missing_refs),
        "unreferenced_dumped_user_wave_ids_not_proven_free": sorted((wave_ids & EXPECTED_WAVE_IDS) - referenced_user_waves),
        "table_kind_counts": dict(sorted(special_kinds.items())),
        "nonstandard_editable_reference_counts_not_necessarily_errors": {
            f"0x{k:04X}": v for k, v in sorted(nonstandard_editable.items())
        },
        "distinct_reserved_position_signatures": len(reserved_fingerprints),
        "limitations": [
            "Only standard WaveDump/TableDump (0x12/0x13) payloads are fully validated.",
            "Other command types are counted, not verified for semantic validity.",
            "Nonstandard references may be sentinels, special types, or unused data.",
            "Unreferenced does not mean free or safe to overwrite.",
            "No MIDI transport, physical XT upload, or firmware write occurs.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Read-only private .syx input")
    parser.add_argument("--out", required=True, type=Path, help="Private JSON report path")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error("input file does not exist")
    if args.out.exists():
        parser.error("output already exists; refusing overwrite")
    if args.out.resolve() == args.input.resolve():
        parser.error("output must not equal input")
    try:
        report = inspect_dump(args.input.read_bytes(), require_complete=args.require_complete)
    except InventoryError as exc:
        parser.exit(1, f"[FAIL] {exc}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
        output.write("\n")
    print(f"[PASS] {report['exact_wave_table_roundtrips']} exact wave/table roundtrips"
          f" out of {report['message_count']} SysEx messages")
    print(f"[INFO] Complete user wave/table set: {report['complete_user_wave_table_set']}")
    print(f"[INFO] Report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
