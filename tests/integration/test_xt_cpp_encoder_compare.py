"""Synthetic checks for the isolated Gearmulator C++ reference-harness mechanism.

Full upstream comparison is run explicitly with scripts/audit/xt_cpp_encoder_compare.py
when the pinned Gearmulator clone and native compiler exist on the host.
"""
import unittest

from scripts.audit.xt_cpp_encoder_compare import (
    create_harness, extract_cpp_function, synthetic_vectors,
)


class OracleHarnessTests(unittest.TestCase):
    def test_missing_original_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_cpp_function("", "State::createWaveData(")

    def test_brace_balanced_extraction(self):
        example = "SysEx State::createWaveData() { if (true) { return {}; } return {}; }"
        self.assertEqual(extract_cpp_function(example, "State::createWaveData("), example)

    def test_deterministic_synthetic_cases_and_edge_values(self):
        a,b=synthetic_vectors(),synthetic_vectors()
        self.assertEqual(a,b)
        self.assertEqual(len(a),30)
        self.assertTrue(any(-128 in x for k,_,x in a if k=='W'))
        self.assertTrue(any(65535 in x for k,_,x in a if k=='T'))

    def test_full_extracted_methods_inserted_verbatim(self):
        state = '''SysEx State::createWaveData(const WaveData&, uint16_t, bool) {return {};}
SysEx State::createTableData(const TableData&, uint32_t, bool) {return {};}'''
        header = 'static bool updateChecksum(SysEx& _src, const uint32_t _startIndex) { return true; }'
        cpp = create_harness(state,header)
        self.assertIn(state.splitlines()[0],cpp)
        self.assertIn(state.splitlines()[1],cpp)
        self.assertIn(header,cpp)
        self.assertIn('int main()',cpp)


if __name__ == '__main__':
    unittest.main()
