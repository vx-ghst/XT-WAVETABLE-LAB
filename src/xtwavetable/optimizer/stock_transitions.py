"""M3.5: source-grounded, IN-MEMORY XT 2.33 DISCRETE transition analysis.

Sources (2026-10-30 audit; pin commits in docs/spec/08_M3_5_SOURCE_AUDIT.md):
Tallent morph.asm branches XT integer-index selection away from E352/Honda
fractional blending. Gearmulator Xenia emulates the firmware/DSP; its UI wave
preview's octave reduction is explicitly NOT a verified hardware algorithm.

Our wave-to-wave RMS at *aligned oscillator phase* is ONLY a geometric proxy,
not an exact time-domain hardware switch transient, perceptual metric or DSP
model. Never produce a sound, SysEx, ROM, hardware I/O or write a file here.

The optional 2-opt proposal keeps the initial and final Waves fixed, preserves
all chosen wave payloads and original 61-position dwell lengths, but MAY ALTER
THE MUSIC'S TIMBRE CHRONOLOGY. Nothing is committed to an M2 export automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math

from xtwavetable.optimizer.selection import WaveSelection
from xtwavetable.model.wave import Wave


class StockTransitionError(ValueError):
    """Unsupported source plan or malformed analysis request."""


@dataclass(frozen=True, slots=True)
class Edge:
    position: int
    from_selected_index: int
    to_selected_index: int
    change: bool
    aligned_phase_rms_difference: float
    aligned_phase_peak_difference: float


@dataclass(frozen=True, slots=True)
class StockTransitionAnalysis:
    source_order: tuple[int, ...]
    proposed_order: tuple[int, ...]
    source_position_indices: tuple[int, ...]
    proposed_position_indices: tuple[int, ...]
    source_edges: tuple[Edge, ...]
    proposed_edges: tuple[Edge, ...]
    source_total_aligned_rms: float
    proposal_total_aligned_rms: float
    source_max_aligned_peak: float
    proposal_max_aligned_peak: float
    reordering_requested: bool
    chronology_changed: bool
    report_json: bytes

    @property
    def numerically_improved(self) -> bool:
        return self.proposal_total_aligned_rms < self.source_total_aligned_rms - 1e-12


def _validate(plan: WaveSelection, max_passes: int, allow_reordering: bool) -> tuple[Wave, ...]:
    if not isinstance(plan, WaveSelection):
        raise StockTransitionError("expected a validated M2.5 WaveSelection")
    if type(max_passes) is not int or not 1 <= max_passes <= 32:
        raise StockTransitionError("max_passes must be an integer in 1..32")
    if type(allow_reordering) is not bool:
        raise StockTransitionError("allow_reordering must be boolean")
    n = len(plan.selected)
    if not 1 <= n <= 61:
        raise StockTransitionError("expected 1..61 selected Waves")
    waves = tuple(item.wave for item in plan.selected)
    if any(not isinstance(w, Wave) for w in waves):
        raise StockTransitionError("selected item is not an XT Wave")
    positions = plan.editable_wave_indices
    if (not isinstance(positions, tuple) or len(positions) != 61
            or any(type(i) is not int or i < 0 or i >= n for i in positions)
            or positions[0] != 0 or positions[-1] != n - 1
            or any(a > b for a, b in zip(positions, positions[1:]))
            or set(positions) != set(range(n))):
        raise StockTransitionError("non-chronological or incomplete 61-position source mapping")
    return waves


def _wave_difference(a: Wave, b: Wave) -> tuple[float, float]:
    values = tuple(x - y for x, y in zip(a.samples, b.samples))
    return (math.sqrt(math.fsum(v * v for v in values) / 128.0) / 128.0,
            max(abs(v) for v in values) / 128.0)


def _edge_rows(positions: tuple[int, ...], waves: tuple[Wave, ...]) -> tuple[Edge, ...]:
    cache: dict[tuple[int, int], tuple[float, float]] = {}
    result = []
    for k, (a, b) in enumerate(zip(positions, positions[1:])):
        if (a, b) not in cache:
            cache[(a, b)] = _wave_difference(waves[a], waves[b])
        rms, peak = cache[a, b]
        result.append(Edge(k, a, b, a != b, rms, peak))
    return tuple(result)


def _cost(order: tuple[int, ...], distances: tuple[tuple[float, ...], ...]) -> float:
    return math.fsum(distances[a][b] for a, b in zip(order, order[1:]))


def _bounded_two_opt(waves: tuple[Wave, ...], passes: int) -> tuple[int, ...]:
    """Deterministic best-improvement anchored path, never increases objective."""
    n = len(waves)
    order = tuple(range(n))
    if n < 4:
        return order
    dist = tuple(tuple(_wave_difference(a, b)[0] for b in waves) for a in waves)
    for _ in range(passes):
        current = _cost(order, dist)
        best = order
        best_cost = current
        # Both endpoints are locked. Reversing [i,j] preserves the wave set.
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                new = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                value = _cost(new, dist)
                if value < best_cost - 1e-12:
                    best, best_cost = new, value
        if best == order:
            break
        order = best
    return order


def analyze_stock_transitions(plan: WaveSelection, *,
                              allow_reordering: bool = False,
                              max_passes: int = 12) -> StockTransitionAnalysis:
    """Analyze 60 discrete transitions and optionally propose an offline 2-opt order.

    IMPORTANT: ``allow_reordering=True`` is explicit because reversing interior
    musical timbres can destroy the source's chronology. The candidate is
    REPORT-ONLY; it does not mutate M2.5, M2.6 or an existing table.
    """
    waves = _validate(plan, max_passes, allow_reordering)
    n = len(waves)
    source_order = tuple(range(n))
    candidate_order = (_bounded_two_opt(waves, max_passes)
                       if allow_reordering else source_order)
    source = plan.editable_wave_indices
    proposal = tuple(candidate_order[i] for i in source)
    old_edges = _edge_rows(source, waves)
    new_edges = _edge_rows(proposal, waves)
    baseline = math.fsum(row.aligned_phase_rms_difference for row in old_edges)
    candidate = math.fsum(row.aligned_phase_rms_difference for row in new_edges)
    # Explicit fallback handles any floating point discrepancy or forged plan.
    if candidate > baseline + 1e-12:
        candidate_order, proposal, new_edges, candidate = source_order, source, old_edges, baseline
    def peak(edges: tuple[Edge, ...]) -> float:
        return max(row.aligned_phase_peak_difference for row in edges)
    wave_hashes = [sha256(bytes(v & 255 for v in w.half_cycle)).hexdigest() for w in waves]
    notes = [
        "XT v2.33 selects whole Wave positions per Tallent's stock branch; precise modulation threshold/timing not validated.",
        "Aligned-phase 128-sample wave RMS/peak is a geometric proxy only, not a measured audible click.",
        "Per-wave sample interpolation, pitch antialiasing, and DSP timing require Xenia/real XT tests.",
        "No interpolation-between-Waves or midpoint-crossfade cancellation is assumed for stock XT.",
        "All 61 user positions are modeled; reserved 61..63 are untouched and excluded.",
        "A reordered proposal changes the timbre chronology even when it improves numerical distance.",
        "No MIDI, file writing, hardware access, source mutation or upload authorization.",
    ]
    report = {
        "schema": "xtwavetable.m3.5.discrete_transition_audit.v1",
        "engine": "XT233_DISCRETE_POSITION_SWITCH_APPROX_PHASE_UNVERIFIED",
        "source_evidence": {
            "tallent_repo_commit": "fc02c58ded5ef2f8e4f853a8e4530326787fd0a6",
            "gearmulator_repo_commit": "7f9a9806b7b3326379a39a2008c6dc92519191df",
        },
        "offline_only": True,
        "hardware_upload_authorized": False,
        "objective": "sum_aligned_phase_wave_rms_at_discrete_position_changes",
        "reordering_requested": allow_reordering,
        "chronology_changed": candidate_order != source_order,
        "source_order": source_order,
        "proposed_order": candidate_order,
        "source_61_positions": source,
        "proposal_61_positions": proposal,
        "input_half_wave_sha256": wave_hashes,
        "source_total_aligned_rms": baseline,
        "proposal_total_aligned_rms": candidate,
        "source_max_aligned_peak": peak(old_edges),
        "proposal_max_aligned_peak": peak(new_edges),
        "source_60_transitions": [{"position": e.position, "from_index": e.from_selected_index,
                                   "to_index": e.to_selected_index, "rms": e.aligned_phase_rms_difference,
                                   "peak": e.aligned_phase_peak_difference, "changes_wave": e.change}
                                  for e in old_edges],
        "proposal_60_transitions": [{"position": e.position, "from_index": e.from_selected_index,
                                     "to_index": e.to_selected_index, "rms": e.aligned_phase_rms_difference,
                                     "peak": e.aligned_phase_peak_difference, "changes_wave": e.change}
                                    for e in new_edges],
        "musical_winner": None,
        "limitations": notes,
    }
    canonical = (json.dumps(report, sort_keys=True, ensure_ascii=True,
                            allow_nan=False, separators=(",", ":")) + "\n").encode("ascii")
    return StockTransitionAnalysis(
        source_order, candidate_order, source, proposal, old_edges, new_edges,
        baseline, candidate, peak(old_edges), peak(new_edges), allow_reordering,
        candidate_order != source_order, canonical,
    )
