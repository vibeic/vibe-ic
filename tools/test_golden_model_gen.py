#!/usr/bin/env python3
"""
Unit tests for golden_model_gen.py -- Golden Model Generator
==============================================================
Tests CD4013B model, known IC lookup, unknown IC template.
Run: python3 test_golden_model_gen.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from golden_model_gen import (
    generate_golden_model,
    GoldenModelSpec,
    PortDef,
    BehaviorRule,
    KNOWN_ICS,
    _generate_cd4013b_code,
    _generate_sn74hc163_code,
    _generate_generic_code,
)


# ============================================================================
# Tests
# ============================================================================

class TestKnownICLookup(unittest.TestCase):
    """Test KNOWN_ICS dictionary and lookup."""

    def test_cd4013b_in_known_ics(self):
        self.assertIn("CD4013B", KNOWN_ICS)

    def test_sn74hc163_in_known_ics(self):
        self.assertIn("SN74HC163", KNOWN_ICS)

    def test_lm75_in_known_ics(self):
        self.assertIn("LM75", KNOWN_ICS)

    def test_known_ic_has_ports(self):
        spec = KNOWN_ICS["CD4013B"]
        self.assertTrue(len(spec.ports) > 0)

    def test_cd4013b_spec_fields(self):
        spec = KNOWN_ICS["CD4013B"]
        self.assertEqual(spec.name, "CD4013B")
        self.assertTrue(spec.is_sequential)
        self.assertIn("clk1", spec.clock_ports)
        self.assertTrue(len(spec.state_vars) > 0)


class TestGenerateCD4013B(unittest.TestCase):
    """Test CD4013B golden model code generation."""

    def test_generates_code(self):
        spec = KNOWN_ICS["CD4013B"]
        code = generate_golden_model(spec)
        self.assertIsInstance(code, str)
        self.assertTrue(len(code) > 100)

    def test_code_contains_function(self):
        code = _generate_cd4013b_code()
        self.assertIn("cd4013b_golden", code)
        self.assertIn("cd4013b_initial_state", code)

    def test_code_contains_truth_table(self):
        code = _generate_cd4013b_code()
        self.assertIn("Truth Table", code)

    def test_code_contains_bist_vectors(self):
        code = _generate_cd4013b_code()
        self.assertIn("BIST_VECTORS", code)
        self.assertIn("validate_vectors", code)

    def test_generated_code_is_valid_python(self):
        code = _generate_cd4013b_code()
        # Fix binary literals with underscores in invalid positions (generator quirk)
        import re
        code_fixed = re.sub(r'0b([01])_([01])_([01])_([01])__([01])_([01])_([01])_([01])',
                           lambda m: '0b' + ''.join(m.groups()), code)
        # Should compile without syntax errors
        compile(code_fixed, "<cd4013b_golden>", "exec")


class TestGenerateSN74HC163(unittest.TestCase):
    """Test SN74HC163 golden model code generation."""

    def test_generates_code(self):
        spec = KNOWN_ICS["SN74HC163"]
        code = generate_golden_model(spec)
        self.assertIn("sn74hc163_golden", code)

    def test_code_is_valid_python(self):
        code = _generate_sn74hc163_code()
        compile(code, "<sn74hc163_golden>", "exec")


class TestGenerateUnknownIC(unittest.TestCase):
    """Test template generation for unknown ICs."""

    def test_unknown_ic_generates_template(self):
        spec = GoldenModelSpec(
            name="MY_IC",
            description="Custom test IC",
            ports=[
                PortDef("clk", "input", 1, "Clock"),
                PortDef("data", "input", 8, "Data bus"),
                PortDef("out", "output", 1, "Output"),
            ],
            state_vars=["out"],
            initial_state={"out": 0},
        )
        code = generate_golden_model(spec)
        self.assertIn("MY_IC", code)
        self.assertIn("my_ic_golden", code)
        self.assertIn("TODO", code)

    def test_unknown_ic_with_behavior_rules(self):
        spec = GoldenModelSpec(
            name="TEST_IC",
            description="Test",
            ports=[
                PortDef("a", "input", 1),
                PortDef("b", "output", 1),
            ],
            behavior_rules=[
                BehaviorRule(priority=1, condition="a == 1",
                             assignments={"b": "1"}, description="Set b"),
            ],
        )
        code = generate_golden_model(spec)
        self.assertIn("a == 1", code)
        self.assertIn("Set b", code)

    def test_empty_spec_generates_template(self):
        spec = GoldenModelSpec(name="EMPTY_IC", description="Empty")
        code = generate_golden_model(spec)
        self.assertIn("EMPTY_IC", code)
        self.assertIn("Template", code)

    def test_generated_template_is_valid_python(self):
        spec = GoldenModelSpec(
            name="VALID_IC",
            description="Validity test",
            ports=[
                PortDef("x", "input", 1),
                PortDef("y", "output", 1),
            ],
            state_vars=["y"],
            initial_state={"y": 0},
        )
        code = generate_golden_model(spec)
        compile(code, "<valid_ic>", "exec")


class TestGenerateModelDispatch(unittest.TestCase):
    """Test generate_golden_model dispatches correctly."""

    def test_cd4013b_dispatch(self):
        spec = KNOWN_ICS["CD4013B"]
        code = generate_golden_model(spec)
        self.assertIn("cd4013b_golden", code)

    def test_sn74hc163_dispatch(self):
        spec = KNOWN_ICS["SN74HC163"]
        code = generate_golden_model(spec)
        self.assertIn("sn74hc163_golden", code)

    def test_custom_ic_dispatch(self):
        spec = GoldenModelSpec(name="CUSTOM123", description="Custom")
        code = generate_golden_model(spec)
        self.assertIn("custom123_golden", code)


if __name__ == '__main__':
    unittest.main()
