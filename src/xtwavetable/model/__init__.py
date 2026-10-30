"""Microwave II/XT firmware-neutral wave and table models."""

from .wave import Wave, negate_int8_modular
from .table import (Table, is_standard_wave_reference, is_user_wave_id,
                    is_user_table_id)

__all__ = ["Wave", "Table", "negate_int8_modular", "is_standard_wave_reference",
           "is_user_wave_id", "is_user_table_id"]
