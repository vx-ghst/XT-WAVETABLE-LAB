"""Canonical 64-position Microwave II/XT wavetable references.

Positions 61-63 are reserved. We preserve their raw 16-bit reference values
without assuming the vendor's exact sentinel encoding. Semantic checks for
user-editable positions are separate from lossless parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

POSITIONS_PER_TABLE = 64
USER_POSITIONS = 61
FIRST_USER_WAVE_ID = 1000
LAST_USER_WAVE_ID = 1249
FIRST_USER_TABLE_ID = 96
LAST_USER_TABLE_ID = 127


def is_standard_wave_reference(wave_id: int) -> bool:
    return type(wave_id) is int and (0 <= wave_id <= 505 or 1000 <= wave_id <= 1249)


def is_user_wave_id(wave_id: int) -> bool:
    return type(wave_id) is int and FIRST_USER_WAVE_ID <= wave_id <= LAST_USER_WAVE_ID


def is_user_table_id(table_id: int) -> bool:
    return type(table_id) is int and FIRST_USER_TABLE_ID <= table_id <= LAST_USER_TABLE_ID


@dataclass(frozen=True, slots=True)
class Table:
    """Raw 64-entry table; entry values are preserved losslessly (uint16)."""

    wave_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        entries = tuple(self.wave_ids)
        if len(entries) != POSITIONS_PER_TABLE:
            raise ValueError("XT table requires exactly 64 references")
        if any(type(n) is not int or not 0 <= n <= 0xFFFF for n in entries):
            raise ValueError("XT table reference must be a 16-bit unsigned integer")
        object.__setattr__(self, "wave_ids", entries)

    @property
    def user_positions(self) -> tuple[int, ...]:
        return self.wave_ids[:USER_POSITIONS]

    @property
    def reserved_positions(self) -> tuple[int, int, int]:
        return (self.wave_ids[61], self.wave_ids[62], self.wave_ids[63])

    def invalid_user_references(self) -> tuple[tuple[int, int], ...]:
        """Identify nonstandard references in editable positions; never mutate."""
        return tuple((i, n) for i, n in enumerate(self.user_positions)
                     if not is_standard_wave_reference(n))

    def with_user_positions(self, wave_ids: Iterable[int]) -> Table:
        """Replace positions 0..60, retaining reserved 61..63 byte-for-byte."""
        entries = tuple(wave_ids)
        if len(entries) != USER_POSITIONS:
            raise ValueError("expected exactly 61 editable table positions")
        if any(not is_standard_wave_reference(n) for n in entries):
            raise ValueError("editable positions must reference known ROM or user waves")
        return Table(entries + self.reserved_positions)
