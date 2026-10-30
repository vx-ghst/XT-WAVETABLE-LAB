"""Canonical Microwave II/XT wave: 128 signed 8-bit samples.

The XT wire format transports 64 samples. The remaining 64 are a reversed,
8-bit modular negation. Specifically, -128 is its own inverse modulo 256.
This is intentional for lossless wire round trips; sound-generation policy
(e.g. clipping to +/-127) belongs to a later converter stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

SAMPLES_PER_WAVE = 128
TRANSMITTED_SAMPLES = 64


def negate_int8_modular(value: int) -> int:
    """Return the negation in signed 8-bit two's-complement arithmetic."""
    if type(value) is not int or not -128 <= value <= 127:
        raise ValueError("sample must be a signed 8-bit integer")
    unsigned = (-value) & 0xFF
    return unsigned - 256 if unsigned >= 128 else unsigned


@dataclass(frozen=True, slots=True)
class Wave:
    """Immutable XT wave with exact transmitted-half symmetry."""

    samples: tuple[int, ...]

    def __post_init__(self) -> None:
        values = tuple(self.samples)
        if len(values) != SAMPLES_PER_WAVE:
            raise ValueError("XT wave requires exactly 128 samples")
        if any(type(v) is not int or not -128 <= v <= 127 for v in values):
            raise ValueError("XT samples must be signed 8-bit integers")
        for i in range(TRANSMITTED_SAMPLES):
            if values[127 - i] != negate_int8_modular(values[i]):
                raise ValueError(f"non-canonical XT wave at mirrored sample {127 - i}")
        object.__setattr__(self, "samples", values)

    @classmethod
    def from_half_cycle(cls, samples: Iterable[int]) -> Wave:
        half = tuple(samples)
        if len(half) != TRANSMITTED_SAMPLES:
            raise ValueError("XT half-cycle requires exactly 64 samples")
        if any(type(v) is not int or not -128 <= v <= 127 for v in half):
            raise ValueError("XT samples must be signed 8-bit integers")
        return cls(half + tuple(negate_int8_modular(v) for v in reversed(half)))

    @property
    def half_cycle(self) -> tuple[int, ...]:
        return self.samples[:TRANSMITTED_SAMPLES]
