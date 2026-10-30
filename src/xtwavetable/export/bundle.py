"""M2.6: conservative, deterministic, offline Microwave XT export planning.

No automatic 'free' RAM allocation: even unreferenced wave IDs contain data.
Require a complete, validated Wave/Table backup snapshot and explicit IDs
for every replacement. Other SysEx commands (Single/Multi/Global) are NOT
semantically parsed. A successful export is NOT hardware-upload approval.

An export is a byte sequence of standard 0x12 WaveDumps followed by one
0x13 TableDump, plus canonical JSON provenance. No MIDI I/O, ROM, or firmware.
A file-writing helper is opt-in and creates files without overwriting them.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from xtwavetable.codec_xt import (TableDump, WaveDump, decode_table_dump,
                                  decode_wave_dump, encode_table_dump,
                                  encode_wave_dump)
from xtwavetable.model import Table, is_user_table_id, is_user_wave_id
from xtwavetable.optimizer.selection import WaveSelection

_EXPECTED_WAVES = frozenset(range(1000, 1250))
_EXPECTED_TABLES = frozenset(range(96, 128))
_SPECIAL_TABLE_PREFIXES = ((0xDEAD, 0xBEEF), (0x12DE, 0xC0DE))


class ExportPlanError(ValueError):
    """Invalid inventory, ambiguous replacement authorization, or bad plan."""


@dataclass(frozen=True, slots=True)
class DumpSnapshot:
    """Immutable, complete validated *user* wave/table snapshot in memory.

    Any original dump that contains only some user waves/tables is rejected.
    Contents are private; do not publish or stage serialized snapshots.
    """
    input_sha256: str
    wave_dumps: tuple[WaveDump, ...]
    table_dumps: tuple[TableDump, ...]
    unvalidated_other_messages: int


@dataclass(frozen=True, slots=True)
class ExportBundle:
    """In-memory offline product; source data is untouched."""
    sysex: bytes
    manifest_json: bytes
    wave_ids: tuple[int, ...]
    table_id: int
    table: Table
    known_cross_table_ids: tuple[int, ...]
    source_dump_sha256: str


def _messages(blob: bytes) -> tuple[bytes, ...]:
    if not isinstance(blob, bytes) or not blob:
        raise ExportPlanError("snapshot must be nonempty SysEx bytes")
    result = []
    cursor = 0
    while cursor < len(blob):
        if blob[cursor] != 0xF0:
            raise ExportPlanError("stray byte outside a SysEx message")
        stop = blob.find(b"\xf7", cursor + 1)
        if stop < 0:
            raise ExportPlanError("unterminated SysEx message")
        msg = blob[cursor:stop + 1]
        if len(msg) < 5 or b"\xf0" in msg[1:-1]:
            raise ExportPlanError("invalid or nested SysEx frame")
        result.append(msg)
        cursor = stop + 1
    return tuple(result)


def inspect_snapshot(blob: bytes) -> DumpSnapshot:
    """Validate all 250 user WaveDumps and 32 user TableDumps, read-only.

    The remaining commands in a complete Everything dump are counted but
    NOT validated: they may reference the same waves through presets.
    """
    waves: dict[int, WaveDump] = {}
    tables: dict[int, TableDump] = {}
    other = 0
    for ordinal, packet in enumerate(_messages(blob)):
        try:
            if packet[4] == 0x12:
                item = decode_wave_dump(packet)
                if not is_user_wave_id(item.wave_id):
                    raise ExportPlanError(f"unexpected non-user wave in snapshot message {ordinal}")
                if item.wave_id in waves:
                    raise ExportPlanError(f"duplicate user wave {item.wave_id}")
                if encode_wave_dump(item.wave_id, item.wave, device_id=item.device_id) != packet:
                    raise ExportPlanError(f"non-exact wave round-trip at message {ordinal}")
                waves[item.wave_id] = item
            elif packet[4] == 0x13:
                item = decode_table_dump(packet)
                if not is_user_table_id(item.table_id):
                    raise ExportPlanError(f"unexpected non-user table in snapshot message {ordinal}")
                if item.table_id in tables:
                    raise ExportPlanError(f"duplicate user table {item.table_id}")
                if encode_table_dump(item.table_id, item.table, device_id=item.device_id) != packet:
                    raise ExportPlanError(f"non-exact table round-trip at message {ordinal}")
                tables[item.table_id] = item
            else:
                other += 1
        except ExportPlanError:
            raise
        except ValueError as exc:
            raise ExportPlanError(f"invalid standard XT dump at message {ordinal}: {exc}") from exc
    if frozenset(waves) != _EXPECTED_WAVES or frozenset(tables) != _EXPECTED_TABLES:
        raise ExportPlanError("complete backup required: expected all 250 user waves and 32 user tables")
    return DumpSnapshot(sha256(blob).hexdigest(),
                        tuple(waves[i] for i in sorted(waves)),
                        tuple(tables[i] for i in sorted(tables)), other)


def build_export_bundle(
    selection: WaveSelection,
    *,
    snapshot: DumpSnapshot,
    wave_ids: tuple[int, ...],
    table_id: int,
    authorized_replacement_wave_ids: tuple[int, ...] = (),
    authorize_table_replacement: bool = False,
    acknowledge_cross_table_references: bool = False,
    device_id: int = 0x7F,
) -> ExportBundle:
    """Prepare a deterministic, strictly offline replacement bundle.

    Every RAM ID must be provided explicitly, with an equally explicit list
    authorizing replacement. This does not assert physical safety and does
    not authorize sending the resulting packets to any actual instrument.
    """
    if not isinstance(selection, WaveSelection):
        raise TypeError("selection must be M2.5 WaveSelection")
    if not isinstance(snapshot, DumpSnapshot):
        raise TypeError("snapshot must be an inspected DumpSnapshot")
    if (len(snapshot.wave_dumps) != 250 or len(snapshot.table_dumps) != 32
            or tuple(w.wave_id for w in snapshot.wave_dumps) != tuple(range(1000, 1250))
            or tuple(t.table_id for t in snapshot.table_dumps) != tuple(range(96, 128))):
        raise ExportPlanError("snapshot does not contain the complete ordered user dataset")
    if not selection.waves or len(selection.waves) > 61:
        raise ExportPlanError("selection must have 1..61 waves")
    if (not isinstance(wave_ids, tuple) or len(wave_ids) != len(selection.waves)
            or any(not is_user_wave_id(n) for n in wave_ids)
            or len(set(wave_ids)) != len(wave_ids)):
        raise ExportPlanError("wave_ids must be a unique, explicit tuple of user RAM slots")
    if not is_user_table_id(table_id):
        raise ExportPlanError("table_id must be a user table ID 96..127")
    if (not isinstance(authorized_replacement_wave_ids, tuple)
            or any(not is_user_wave_id(n) for n in authorized_replacement_wave_ids)
            or len(set(authorized_replacement_wave_ids)) != len(authorized_replacement_wave_ids)
            or set(authorized_replacement_wave_ids) != set(wave_ids)):
        raise ExportPlanError("explicit replacement authorization required for every selected wave ID")
    if authorize_table_replacement is not True:
        raise ExportPlanError("explicit table replacement authorization required")
    if type(acknowledge_cross_table_references) is not bool:
        raise ExportPlanError("acknowledgement must be boolean")
    if type(device_id) is not int or not 0 <= device_id <= 127:
        raise ExportPlanError("device_id must be a MIDI 7-bit integer")
    if len(selection.editable_wave_indices) != 61 or any(
            type(i) is not int or not 0 <= i < len(wave_ids)
            for i in selection.editable_wave_indices):
        raise ExportPlanError("invalid 61-position selection map")
    if set(selection.editable_wave_indices) != set(range(len(selection.waves))):
        raise ExportPlanError("every wave must be represented in editable table positions")

    template = snapshot.table_dumps[table_id - 96].table
    if template.wave_ids[:2] in _SPECIAL_TABLE_PREFIXES:
        raise ExportPlanError("special table format (speech/uPAW): cannot safely replace")
    external = []
    targets = set(wave_ids)
    for existing in snapshot.table_dumps:
        if existing.table_id == table_id:
            continue
        if (existing.table.wave_ids[:2] in _SPECIAL_TABLE_PREFIXES):
            # A nonstandard table cannot be proved independent of overwritten waves.
            # Do not make any positive statement about its private dependencies.
            continue
        if targets.intersection(existing.table.user_positions):
            external.append(existing.table_id)
    if external and not acknowledge_cross_table_references:
        raise ExportPlanError(
            "target wave IDs are referenced by other tables; explicit acknowledgement required")

    mapped = tuple(wave_ids[i] for i in selection.editable_wave_indices)
    table = template.with_user_positions(mapped)
    packets = tuple(encode_wave_dump(wave_id, wave, device_id=device_id)
                    for wave_id, wave in zip(wave_ids, selection.waves))
    table_packet = encode_table_dump(table_id, table, device_id=device_id)
    # Defence in depth: each emitted packet must decode to the exact source model.
    for wave_id, wave, packet in zip(wave_ids, selection.waves, packets):
        decoded = decode_wave_dump(packet)
        if decoded.wave_id != wave_id or decoded.wave != wave:
            raise ExportPlanError("wave codec round-trip failed")
    parsed_table = decode_table_dump(table_packet)
    if parsed_table.table != table or parsed_table.table_id != table_id:
        raise ExportPlanError("table codec round-trip failed")
    output = b"".join(packets) + table_packet
    manifest = {
        "schema": "xtwavetable.m2.6.offline_export.v1",
        "source_snapshot_sha256": snapshot.input_sha256,
        "output_sysex_sha256": sha256(output).hexdigest(),
        "table_id": table_id,
        "wave_ids": list(wave_ids),
        "editable_wave_indices": list(selection.editable_wave_indices),
        "reserved_table_references_preserved": list(template.reserved_positions),
        "selected_candidate_indices": [c.index for c in selection.selected],
        "selection_strategy": selection.strategy,
        "requested_waves": selection.requested_waves,
        "actual_distinct_waves": selection.actual_distinct_waves,
        "projection_rms_errors": [c.projection_rms_error for c in selection.selected],
        "known_cross_table_references": external,
        "cross_table_references_acknowledged": acknowledge_cross_table_references,
        "unvalidated_snapshot_commands": snapshot.unvalidated_other_messages,
        "device_id": device_id,
        "limitations": [
            "OFFLINE artifact only. No hardware-upload permission or transport.",
            "Every existing user wave/table slot contains data; none is certified free.",
            "Other dump commands, preset references and special-table semantics are unvalidated.",
            "Hardware protection requires a separate backup, readback and consent gate in M7.",
            "Transition/interpolation sound quality has not been assessed (M3/M4).",
        ],
    }
    canonical = (json.dumps(manifest, sort_keys=True, ensure_ascii=True,
                            separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    return ExportBundle(output, canonical, wave_ids, table_id, table,
                        tuple(external), snapshot.input_sha256)


def write_export_bundle(bundle: ExportBundle, directory: str | Path, *,
                        stem: str = "xt_candidate") -> tuple[Path, Path]:
    """Opt-in local export of SYX+JSON, no overwrite, no MIDI/hardware I/O.

    Only writes into an existing directory. If the second write fails, the
    newly created SYX is deleted; no pre-existing file can be overwritten.
    Calling code remains responsible for selecting a private runs/ folder.
    """
    if not isinstance(bundle, ExportBundle):
        raise TypeError("bundle must be an ExportBundle")
    if (not isinstance(stem, str) or not stem or any(c not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in stem)):
        raise ExportPlanError("stem must contain only ASCII letters, digits, '_' or '-'")
    folder = Path(directory)
    if not folder.is_dir():
        raise ExportPlanError("export directory must already exist")
    syx = folder / (stem + ".syx")
    report = folder / (stem + ".json")
    if syx.exists() or report.exists():
        raise FileExistsError("export exists; refusing overwrite")
    with syx.open("xb") as f:
        f.write(bundle.sysex)
    try:
        with report.open("xb") as f:
            f.write(bundle.manifest_json)
    except BaseException:
        syx.unlink()
        raise
    return syx, report
