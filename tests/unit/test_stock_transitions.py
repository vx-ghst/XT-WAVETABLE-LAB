"""M3.5: anchored, immutable, honest discrete-position transition analysis."""
import dataclasses
import json
import unittest

from xtwavetable.model import Wave
from xtwavetable.converter.cycles import CycleCandidate, CycleExtraction
from xtwavetable.optimizer.selection import select_wave_plan
from xtwavetable.optimizer.stock_transitions import (
    StockTransitionError, analyze_stock_transitions,
)


def plan_from(values):
    items = tuple(CycleCandidate(
        index=i, anchor_frame=float(i*100), phase_start_frame=float(i*100),
        period_frames=100.0, pitch_hz=480.0, dc_reference=0.0,
        source_cycle_rms=0.5, source_cycle_peak=0.5,
        projection_rms_error=0.01, projected_peak=0.5,
        gain_linear=1.0, quantized_peak=abs(v),
        wave=Wave.from_half_cycle([v]*64),
    ) for i, v in enumerate(values))
    source = CycleExtraction(48000, 0, 10000, "explicit", "uniform", False, items)
    return select_wave_plan(source, requested_waves=len(values))


class StockTransitionTests(unittest.TestCase):
    def setUp(self):
        self.selection = plan_from([0, 70, -60, 80])

    def test_read_only_default_keeps_chronology(self):
        original = self.selection
        r = analyze_stock_transitions(original)
        self.assertEqual(r.proposed_order, (0, 1, 2, 3))
        self.assertEqual(r.source_position_indices, r.proposed_position_indices)
        self.assertFalse(r.chronology_changed)
        self.assertIs(original, self.selection)

    def test_opt_in_finds_strict_improvement(self):
        r = analyze_stock_transitions(self.selection, allow_reordering=True)
        self.assertEqual(r.proposed_order, (0, 2, 1, 3))
        self.assertTrue(r.numerically_improved)
        self.assertTrue(r.chronology_changed)
        self.assertLess(r.proposal_total_aligned_rms, r.source_total_aligned_rms)

    def test_anchors_preserved(self):
        r = analyze_stock_transitions(self.selection, allow_reordering=True)
        self.assertEqual(r.proposed_order[0], 0)
        self.assertEqual(r.proposed_order[-1], 3)
        self.assertEqual(r.proposed_position_indices[0], 0)
        self.assertEqual(r.proposed_position_indices[-1], 3)

    def test_preserve_exact_multiset_of_references(self):
        r = analyze_stock_transitions(self.selection, allow_reordering=True)
        self.assertEqual(sorted(r.proposed_order), list(range(4)))
        original_counts = sorted(r.source_position_indices.count(i) for i in range(4))
        proposal_counts = sorted(r.proposed_position_indices.count(i) for i in range(4))
        self.assertEqual(original_counts, proposal_counts)

    def test_nonincreasing_numeric_objective(self):
        for values in ([0,70,-60,80],[0,1,2,3,4,5],[10,40,-40,20,-70,75],[-70,-30,0,20,70]):
            with self.subTest(values=values):
                r=analyze_stock_transitions(plan_from(values),allow_reordering=True)
                self.assertLessEqual(r.proposal_total_aligned_rms,r.source_total_aligned_rms+1e-12)

    def test_60_edges_and_correct_contiguous_positions(self):
        r=analyze_stock_transitions(self.selection,allow_reordering=True)
        for edges in (r.source_edges,r.proposed_edges):
            self.assertEqual(len(edges),60)
            self.assertEqual(tuple(e.position for e in edges),tuple(range(60)))
        self.assertEqual(r.source_edges[0].from_selected_index,0)

    def test_same_wave_edges_cost_zero(self):
        r=analyze_stock_transitions(self.selection)
        edges=[e for e in r.source_edges if not e.change]
        self.assertTrue(edges)
        self.assertTrue(all(e.aligned_phase_rms_difference==0 for e in edges))
        self.assertTrue(all(e.aligned_phase_peak_difference==0 for e in edges))

    def test_source_wave_unchanged(self):
        plan=self.selection
        before=tuple(c.wave.samples for c in plan.selected)
        analyze_stock_transitions(plan,allow_reordering=True)
        self.assertEqual(before,tuple(c.wave.samples for c in plan.selected))

    def test_explicitly_no_midpoint_crossfade(self):
        data=json.loads(analyze_stock_transitions(self.selection).report_json)
        self.assertNotIn("crossfade_midpoint_rms_ratio",str(data))
        self.assertEqual(data["engine"],"XT233_DISCRETE_POSITION_SWITCH_APPROX_PHASE_UNVERIFIED")

    def test_provenance_and_user_only_scope(self):
        data=json.loads(analyze_stock_transitions(self.selection).report_json)
        self.assertEqual(len(data["input_half_wave_sha256"]),4)
        self.assertEqual(len(data["source_61_positions"]),61)
        self.assertTrue(data["offline_only"])
        self.assertFalse(data["hardware_upload_authorized"])
        self.assertIsNone(data["musical_winner"])

    def test_deterministic_json_byte_for_byte(self):
        a=analyze_stock_transitions(self.selection,allow_reordering=True).report_json
        b=analyze_stock_transitions(self.selection,allow_reordering=True).report_json
        self.assertEqual(a,b)

    def test_reject_non_plan(self):
        with self.assertRaises(StockTransitionError):
            analyze_stock_transitions("not a plan")

    def test_reject_wrong_params(self):
        for kwargs in ({"allow_reordering":1},{"allow_reordering":None},{"max_passes":0},
                       {"max_passes":33},{"max_passes":True},{"max_passes":1.0}):
            with self.subTest(kwargs=kwargs),self.assertRaises(StockTransitionError):
                analyze_stock_transitions(self.selection,**kwargs)

    def test_reject_altered_mapping(self):
        bad=dataclasses.replace(self.selection,editable_wave_indices=(0,)*61)
        with self.assertRaises(StockTransitionError):
            analyze_stock_transitions(bad)

    def test_reject_nonmonotone_mapping(self):
        positions=list(self.selection.editable_wave_indices)
        positions[0]=1
        bad=dataclasses.replace(self.selection,editable_wave_indices=tuple(positions))
        with self.assertRaises(StockTransitionError):
            analyze_stock_transitions(bad)

    def test_reject_wrong_position_count(self):
        bad=dataclasses.replace(self.selection,editable_wave_indices=(0,1))
        with self.assertRaises(StockTransitionError):
            analyze_stock_transitions(bad)

    def test_reject_empty_selection(self):
        bad=dataclasses.replace(self.selection,selected=())
        with self.assertRaises(StockTransitionError):
            analyze_stock_transitions(bad)

    def test_one_wave_plan(self):
        p=plan_from([25]); r=analyze_stock_transitions(p,allow_reordering=True)
        self.assertEqual(r.proposed_order,(0,))
        self.assertEqual(r.source_total_aligned_rms,0)
        self.assertEqual(r.proposal_total_aligned_rms,0)
        self.assertFalse(r.chronology_changed)

    def test_two_wave_plan(self):
        r=analyze_stock_transitions(plan_from([20,-10]),allow_reordering=True)
        self.assertEqual(r.proposed_order,(0,1))
        self.assertFalse(r.numerically_improved)

    def test_three_wave_plan(self):
        r=analyze_stock_transitions(plan_from([-30,0,30]),allow_reordering=True)
        self.assertEqual(r.proposed_order,(0,1,2))

    def test_absolute_bounds_and_symmetric_proxy(self):
        a=plan_from([-127,127]); r=analyze_stock_transitions(a)
        self.assertLessEqual(r.source_max_aligned_peak,2)
        self.assertGreater(r.source_max_aligned_peak,1)

    def test_report_sha_only_no_private_paths(self):
        r=analyze_stock_transitions(self.selection)
        self.assertNotIn(b"C:\\Users",r.report_json)
        self.assertNotIn(b"private/",r.report_json)
        self.assertNotIn(b".syx",r.report_json)

    def test_61_selected_waves(self):
        vals=list(range(-30,31))
        r=analyze_stock_transitions(plan_from(vals),allow_reordering=True,max_passes=2)
        self.assertEqual(len(r.source_order),61)
        self.assertEqual(len(r.proposed_order),61)
        self.assertLessEqual(r.proposal_total_aligned_rms,r.source_total_aligned_rms+1e-12)


if __name__=='__main__':
    unittest.main()
