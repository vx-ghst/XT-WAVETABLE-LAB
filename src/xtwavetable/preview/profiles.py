"""M3.6 explicit render-profile policy, NOT a certified Waldorf DSP.

Primary references: Waldorf Microwave II/XT user manual (1998), pp. 32-35
(PDF pages 30-33), and Tallent OS 2.33 extended source + Xenia.
Legacy omission is allowed solely for byte-for-byte backwards compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass


class ProfileError(ValueError):
    """Incompatible, unknown, or ambiguous preview rendering profile."""


@dataclass(frozen=True, slots=True)
class RenderProfile:
    name: str
    table_interpolation: str
    phase_interpolation: str
    table_position_claim: str
    phase_claim: str
    crossfade_midpoint_applicable: bool
    sparse_table_interpolation_supported: bool = False
    dsp_parity_certified: bool = False

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "table_position_claim": self.table_position_claim,
            "phase_claim": self.phase_claim,
            "crossfade_midpoint_applicable": self.crossfade_midpoint_applicable,
            "sparse_table_interpolation_supported": self.sparse_table_interpolation_supported,
            "dsp_parity_certified": self.dsp_parity_certified,
            "profile_schema": "xtwavetable.m3.6.render_profile.v1",
        }


PROFILES: dict[str, RenderProfile] = {
    "legacy-linear-approx": RenderProfile(
        "legacy-linear-approx", "linear", "linear",
        "fractional crossfade (M3.1 original, NOT stock XT 2.33)",
        "linear within each 128-sample cycle, NOT DSP verified", True),
    "xt233-discrete-approx": RenderProfile(
        "xt233-discrete-approx", "nearest", "linear",
        "discrete table positions; rounding thresholds NOT firmware-verified",
        "linear phase interpolation is a proxy; DSP/anti-aliasing unverified", False),
    "tallent-e352-approx": RenderProfile(
        "tallent-e352-approx", "linear", "linear",
        "fractional blend, approximating Tallent E352 (NOT bit-exact)",
        "linear phase interpolation, NOT DSP verified", True),
    "tallent-honda-approx": RenderProfile(
        "tallent-honda-approx", "linear", "nearest",
        "fractional blend, approximating Tallent Honda (NOT bit-exact)",
        "sample-hold phase approximation, NOT DSP verified", True),
}


def resolve_profile(name: str | None, *, table_interpolation: str | None = None,
                    phase_interpolation: str | None = None) -> tuple[str, str, RenderProfile | None]:
    """Resolve mode policy without ever changing omitted/legacy v1 behavior.

    When name is None old mode flags are preserved (default: linear/linear).
    Named profiles fail closed on contradictory overrides.
    """
    if name is None:
        table = "linear" if table_interpolation is None else table_interpolation
        phase = "linear" if phase_interpolation is None else phase_interpolation
        return table, phase, None
    if not isinstance(name, str) or name not in PROFILES:
        raise ProfileError("unknown render profile")
    profile = PROFILES[name]
    if table_interpolation is not None and table_interpolation != profile.table_interpolation:
        raise ProfileError("table-interpolation contradicts the named profile")
    if phase_interpolation is not None and phase_interpolation != profile.phase_interpolation:
        raise ProfileError("phase-interpolation contradicts the named profile")
    return profile.table_interpolation, profile.phase_interpolation, profile


def validate_report_profile(report: dict) -> None:
    """Validate new signed-by-nothing profile metadata; old v1 remains accepted."""
    if "render_profile" not in report:
        return
    value = report["render_profile"]
    if not isinstance(value, dict) or value.get("name") not in PROFILES:
        raise ProfileError("invalid report render profile")
    profile = PROFILES[value["name"]]
    if value != profile.metadata():
        raise ProfileError("render profile metadata has been altered")
    settings = report.get("render_settings")
    if not isinstance(settings, dict) or (settings.get("table_interpolation"), settings.get("phase_interpolation")) != (profile.table_interpolation, profile.phase_interpolation):
        raise ProfileError("render settings do not match the named profile")
    if not profile.crossfade_midpoint_applicable:
        groups = ([report[key] for key in ("A", "B") if key in report] if "candidates" not in report
                  else report["candidates"])
        if not isinstance(groups, list):
            raise ProfileError("profile transition groups invalid")
        for group in groups:
            if (not isinstance(group, dict) or group.get("possible_cancellation_positions") != []
                    or not isinstance(group.get("transitions"), list)
                    or any(row.get("crossfade_midpoint_rms_ratio") is not None
                           or row.get("possible_midpoint_cancellation") is not False
                           for row in group["transitions"] if isinstance(row, dict))):
                raise ProfileError("stock discrete report includes inapplicable crossfade metrics")
