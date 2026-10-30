"""M2.5: deterministic, read-only XT wave selection and 61-position planning.

Select at most 61 *distinct* XT waves from the M2.4 cycle candidates.
A table's editable positions (0..60) are expressed as indices into the
selected-wave tuple. They are NOT XT RAM slot IDs or a wire-format Table.
Reserved positions (61..63) and existing RAM contents are not touched.
Actual slot allocation, dump-collision policy and SysEx are deferred to M2.6.

``uniform`` covers the source timeline; ``diversity`` greedily maximizes the
minimum pairwise RMS distance between signed 8-bit transmitted half-cycles.
This time-domain metric is NOT a spectral/perceptual quality claim. Candidates
with the exact same transmitted 64 samples are deduplicated, selecting the
representative with lower measured XT projection error.

A shortfall of distinct waves fails closed by default; ``shortfall='reuse'``
explicitly permits fewer waves, with references reused across 61 positions.
No hidden normalization, resampling, file I/O, or source modification.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from xtwavetable.converter.cycles import CycleCandidate, CycleExtraction
from xtwavetable.model import Wave


EDITABLE_TABLE_POSITIONS = 61


class WaveSelectionError(ValueError):
    """Invalid selection parameters or unmet distinct-wave requirements."""


@dataclass(frozen=True, slots=True)
class WaveSelection:
    """Immutable candidate plan without physical XT slot allocation.

    ``editable_wave_indices`` is 61 integers indexing ``selected``; no
    reserved positions, device IDs, or existing table metadata are present.
    """

    requested_waves: int
    strategy: str
    shortfall: str
    available_candidates: int
    excluded_by_projection: int
    exact_duplicates: int
    available_distinct_waves: int
    selected: tuple[CycleCandidate, ...]
    editable_wave_indices: tuple[int, ...]
    minimum_selected_distance: float | None

    @property
    def actual_distinct_waves(self) -> int:
        return len(self.selected)

    @property
    def has_shortfall(self) -> bool:
        return len(self.selected) < self.requested_waves

    @property
    def waves(self) -> tuple[Wave, ...]:
        return tuple(candidate.wave for candidate in self.selected)


def wave_rms_distance(first: Wave, second: Wave) -> float:
    """Normalized [0,2] RMS separation on the 64 transmitted int8 samples."""
    if not isinstance(first, Wave) or not isinstance(second, Wave):
        raise TypeError("wave_rms_distance needs two XT Wave objects")
    return math.sqrt(math.fsum(
        (a - b) ** 2 for a, b in zip(first.half_cycle, second.half_cycle)
    ) / 64.0) / 127.0


def _unique_representatives(candidates: tuple[CycleCandidate, ...]
                            ) -> tuple[CycleCandidate, ...]:
    best: dict[tuple[int, ...], CycleCandidate] = {}
    for candidate in candidates:
        key = candidate.wave.half_cycle
        previous = best.get(key)
        if (previous is None or
                (candidate.projection_rms_error, candidate.index)
                < (previous.projection_rms_error, previous.index)):
            best[key] = candidate
    return tuple(sorted(best.values(), key=lambda c: c.index))


def _uniform_pick(candidates: tuple[CycleCandidate, ...], count: int
                  ) -> tuple[CycleCandidate, ...]:
    if count == 1:
        return (candidates[(len(candidates) - 1) // 2],)
    if count == len(candidates):
        return candidates
    # Integer arithmetic and inclusive endpoints, no platform-dependent float ties.
    last = len(candidates) - 1
    return tuple(candidates[(i * last * 2 + count - 1) // (2 * (count - 1))]
                 for i in range(count))


def _diversity_pick(candidates: tuple[CycleCandidate, ...], count: int
                    ) -> tuple[CycleCandidate, ...]:
    if count == len(candidates):
        return candidates
    picked = [candidates[0]]
    remaining = list(candidates[1:])
    while len(picked) < count:
        # Strictly stable tie-breaking: largest min distance, lowest projection
        # error, then earliest source region. Distances are deterministic.
        chosen = max(remaining, key=lambda c: (
            min(wave_rms_distance(c.wave, p.wave) for p in picked),
            -c.projection_rms_error,
            -c.index,
        ))
        picked.append(chosen)
        remaining.remove(chosen)
    return tuple(sorted(picked, key=lambda c: c.index))


def select_wave_plan(
    extraction: CycleExtraction,
    *,
    requested_waves: int = 8,
    strategy: str = "uniform",
    shortfall: str = "reject",
    max_projection_rms_error: float | None = None,
) -> WaveSelection:
    """Select distinct waves and plan references for the 61 editable slots.

    Select ``requested_waves`` in 1..61. By default insufficient *distinct*
    candidates cause an explicit error, rather than silently inventing waves.
    ``shortfall='reuse'`` returns as many distinct waves as exist and reuses
    their indices across the 61-position timeline. This does not allocate RAM
    wave IDs and must NOT be interpreted as a hardware-safe upload plan.

    ``max_projection_rms_error`` is a voluntary gate on M2.4's dimensionless
    raw-source projection RMS (not a listening or timbral preservation score).
    No candidate is excluded by this metric unless the caller sets the gate.
    """
    if not isinstance(extraction, CycleExtraction):
        raise TypeError("extraction must be M2.4 CycleExtraction")
    if type(requested_waves) is not int or not 1 <= requested_waves <= 61:
        raise WaveSelectionError("requested_waves must be an integer in 1..61")
    if type(strategy) is not str or strategy not in ("uniform", "diversity"):
        raise WaveSelectionError("strategy must be uniform or diversity")
    if type(shortfall) is not str or shortfall not in ("reject", "reuse"):
        raise WaveSelectionError("shortfall must be reject or reuse")
    if max_projection_rms_error is not None:
        if (isinstance(max_projection_rms_error, bool)
                or not isinstance(max_projection_rms_error, (int, float))
                or not math.isfinite(max_projection_rms_error)
                or max_projection_rms_error < 0):
            raise WaveSelectionError("max_projection_rms_error must be finite and nonnegative")
    candidates = extraction.candidates
    if (not isinstance(candidates, tuple) or not 1 <= len(candidates) <= 61
            or any(not isinstance(c, CycleCandidate) for c in candidates)):
        raise WaveSelectionError("nonempty M2.4 candidate tuple (max 61) required")
    if (type(extraction.source_frames) is not int or extraction.source_frames < 1
            or type(extraction.sample_rate) is not int or extraction.sample_rate < 1
            or len({c.index for c in candidates}) != len(candidates)):
        raise WaveSelectionError("invalid source metadata or duplicate candidate index")
    for c in candidates:
        if (not isinstance(c.wave, Wave) or type(c.index) is not int
                or not 0 <= c.index < len(candidates)
                or not math.isfinite(c.projection_rms_error)
                or c.projection_rms_error < 0
                or not math.isfinite(c.anchor_frame)
                or not 0 <= c.anchor_frame <= extraction.source_frames):
            raise WaveSelectionError("candidate index, wave or diagnostic is invalid")
    if tuple(c.index for c in candidates) != tuple(range(len(candidates))):
        raise WaveSelectionError("candidates must be in M2.4 chronological index order")
    accepted = tuple(c for c in candidates
                     if max_projection_rms_error is None
                     or c.projection_rms_error <= max_projection_rms_error)
    if not accepted:
        raise WaveSelectionError("all candidates excluded by projection error threshold")
    unique = _unique_representatives(accepted)
    if len(unique) < requested_waves and shortfall == "reject":
        raise WaveSelectionError(
            f"insufficient distinct XT waves: requested {requested_waves}, "
            f"available {len(unique)}; explicitly set shortfall='reuse' to share wave references")
    n = min(len(unique), requested_waves)
    chosen = (_uniform_pick(unique, n) if strategy == "uniform"
              else _diversity_pick(unique, n))
    # 61 editable references; integer round-half-up; all selected waves are used.
    # This maps an ordered selection to a time-evolving table timeline without
    # fabricating or touching reserved values 61..63.
    index_map = tuple((pos * (n - 1) + 30) // 60 for pos in range(61))
    smallest = (min(wave_rms_distance(a.wave, b.wave)
                    for idx, a in enumerate(chosen) for b in chosen[idx + 1:])
                if n > 1 else None)
    return WaveSelection(
        requested_waves=requested_waves,
        strategy=strategy,
        shortfall=shortfall,
        available_candidates=len(candidates),
        excluded_by_projection=len(candidates) - len(accepted),
        exact_duplicates=len(accepted) - len(unique),
        available_distinct_waves=len(unique),
        selected=chosen,
        editable_wave_indices=index_map,
        minimum_selected_distance=smallest,
    )
