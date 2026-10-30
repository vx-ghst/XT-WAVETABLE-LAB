"""Strict, read-only/offline Waldorf Microwave II/XT wave and table SysEx.

Only standard commands 0x12 (wave dump) and 0x13 (table dump) are supported.
Emulator-specific commands 0x19/0x1A are intentionally rejected.

Reference: Gearmulator 7f9a9806b7b3326379a39a2008c6dc92519191df,
source/waldi/xt/xtLib/xtState.cpp and xtMidiTypes.h.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from xtwavetable.model import Table, Wave, is_standard_wave_reference, is_user_wave_id, is_user_table_id

WALDORF_MANUFACTURER = 0x3E
MW2_MODEL = 0x0E
OMNI_DEVICE_ID = 0x7F
WAVE_DUMP = 0x12
TABLE_DUMP = 0x13
WAVE_DUMP_LENGTH = 137
TABLE_DUMP_LENGTH = 265


class XTFormatError(ValueError):
    """Unsupported or malformed standard XT SysEx."""


class XTChecksumError(XTFormatError):
    """SysEx payload checksum does not match its transmitted value."""


@dataclass(frozen=True, slots=True)
class WaveDump:
    wave_id: int
    wave: Wave
    device_id: int


@dataclass(frozen=True, slots=True)
class TableDump:
    table_id: int
    table: Table
    device_id: int


def checksum(data: Iterable[int]) -> int:
    """The XT dump checksum is sum(payload) modulo 128."""
    return sum(data) & 0x7F


def _signed_int8(value: int) -> int:
    return value - 256 if value >= 128 else value


def _check_device(device_id: int) -> None:
    if type(device_id) is not int or not 0 <= device_id <= 127:
        raise XTFormatError("MIDI device ID must be in 0..127")


def _validate_frame(raw: bytes, command: int, expected_size: int,
                    expected_device_id: int | None) -> int:
    if not isinstance(raw, bytes):
        raise XTFormatError("SysEx message must be bytes")
    if len(raw) != expected_size:
        raise XTFormatError(f"expected {expected_size} bytes, got {len(raw)}")
    if raw[0] != 0xF0 or raw[-1] != 0xF7:
        raise XTFormatError("SysEx framing must be F0 ... F7")
    if any(b > 127 for b in raw[1:-1]):
        raise XTFormatError("SysEx body contains a non-7-bit MIDI byte")
    if raw[1] != WALDORF_MANUFACTURER or raw[2] != MW2_MODEL:
        raise XTFormatError("not a Waldorf Microwave II/XT message")
    if raw[4] != command:
        raise XTFormatError("unexpected or emulator-private SysEx command")
    if expected_device_id is not None:
        _check_device(expected_device_id)
        if raw[3] != expected_device_id:
            raise XTFormatError("unexpected device ID")
    if any(b > 0x0F for b in raw[7:-2]):
        raise XTFormatError("payload contains a non-nibble value")
    if checksum(raw[7:-2]) != raw[-2]:
        raise XTChecksumError("invalid XT checksum")
    return (raw[5] << 7) | raw[6]


def _make_frame(command: int, item_id: int, payload: bytes, device_id: int) -> bytes:
    _check_device(device_id)
    return (bytes((0xF0, WALDORF_MANUFACTURER, MW2_MODEL, device_id,
                   command, item_id >> 7, item_id & 0x7F)) + payload
            + bytes((checksum(payload), 0xF7)))


def encode_wave_dump(wave_id: int, wave: Wave, *, device_id: int = OMNI_DEVICE_ID,
                     require_user_slot: bool = True) -> bytes:
    """Encode a standard wave dump. Default destination policy is user RAM only.

    ``require_user_slot=False`` is for lossless ROM/read-only dump roundtrips;
    it does not grant permission to write physical hardware.
    """
    if not isinstance(wave, Wave):
        raise TypeError("wave must be a Wave model")
    if not is_standard_wave_reference(wave_id):
        raise XTFormatError("wave index is outside standard XT ranges")
    if require_user_slot and not is_user_wave_id(wave_id):
        raise XTFormatError("wave target is not a user RAM slot")
    payload = bytearray()
    for sample in wave.half_cycle:
        transmitted = (sample & 0xFF) ^ 0x80
        payload.extend((transmitted >> 4, transmitted & 0x0F))
    return _make_frame(WAVE_DUMP, wave_id, bytes(payload), device_id)


def decode_wave_dump(raw: bytes, *, expected_device_id: int | None = None) -> WaveDump:
    """Validate and decode one complete standard wave dump."""
    wave_id = _validate_frame(raw, WAVE_DUMP, WAVE_DUMP_LENGTH, expected_device_id)
    if not is_standard_wave_reference(wave_id):
        raise XTFormatError("wave index is outside standard XT ranges")
    half = []
    for i in range(7, 135, 2):
        encoded = (raw[i] << 4) | raw[i + 1]
        half.append(_signed_int8(encoded ^ 0x80))
    return WaveDump(wave_id, Wave.from_half_cycle(half), raw[3])


def encode_table_dump(table_id: int, table: Table, *, device_id: int = OMNI_DEVICE_ID,
                      require_user_slot: bool = True) -> bytes:
    """Encode a standard table dump while preserving all reserved references."""
    if not isinstance(table, Table):
        raise TypeError("table must be a Table model")
    if type(table_id) is not int or not 0 <= table_id <= 127:
        raise XTFormatError("table index is outside standard XT ranges")
    if require_user_slot and not is_user_table_id(table_id):
        raise XTFormatError("table target is not a user table slot")
    payload = bytearray()
    for ref in table.wave_ids:
        payload.extend(((ref >> 12) & 0x0F, (ref >> 8) & 0x0F,
                        (ref >> 4) & 0x0F, ref & 0x0F))
    return _make_frame(TABLE_DUMP, table_id, bytes(payload), device_id)


def decode_table_dump(raw: bytes, *, expected_device_id: int | None = None) -> TableDump:
    """Validate one table dump. Semantic checks are separate from wire decoding.

    In particular, entries 61..63 may contain vendor sentinel references: a
    strict wire decoder must preserve rather than normalize them.
    """
    table_id = _validate_frame(raw, TABLE_DUMP, TABLE_DUMP_LENGTH, expected_device_id)
    if table_id > 127:
        raise XTFormatError("table index is outside standard XT ranges")
    refs = []
    for i in range(7, 263, 4):
        refs.append((raw[i] << 12) | (raw[i + 1] << 8) |
                    (raw[i + 2] << 4) | raw[i + 3])
    return TableDump(table_id, Table(tuple(refs)), raw[3])
