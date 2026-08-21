#!/usr/bin/env python3
"""Tests for spec_context_sibling_detect — the context-sibling collision advisory."""
import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "spec_context_sibling_detect", _PROGRAMS / "spec_context_sibling_detect.py")
_M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_M)
detect = _M.detect_context_siblings


def test_fires_on_multi_file_context():
    # scrambler_0018 shape: two sibling RTL files, one is marked excluded
    prompt = ("Perform a review on the `inter_block` module. The `intra_block` "
              "module, which should be excluded from consideration during the "
              "review, stays its own file.")
    keys = ["rtl/inter_block.sv", "rtl/intra_block.sv"]
    r = detect(prompt, keys)
    assert r["has_siblings"] is True
    assert set(r["sibling_modules"]) == {"inter_block", "intra_block"}
    assert "intra_block" in r["prose_excluded"]
    # the TARGET module must NEVER be flagged 'do not emit'
    assert "inter_block" not in r["prose_excluded"], r["prose_excluded"]
    assert r["requirement"] and "already declared" in r["requirement"]


def test_single_context_file_does_not_fire():
    r = detect("modify the foo module", ["rtl/foo.sv"])
    assert r["has_siblings"] is False
    assert r["requirement"] is None


def test_no_context_does_not_fire():
    r = detect("Design an 8-bit counter.", [])
    assert r["has_siblings"] is False


def test_test_cases_provided_is_not_a_module_exclusion():
    # montgomery over-match guard: "failing test cases are provided below" must
    # NOT flag a sibling as excluded (it is about test vectors, not a module).
    prompt = ("Implement montgomery_redc and montgomery_top. A set of failing "
              "test cases are provided below: | a | b | N |")
    keys = ["rtl/montgomery_redc.sv", "rtl/montgomery_top.sv"]
    r = detect(prompt, keys)
    assert r["has_siblings"] is True
    assert r["prose_excluded"] == [], r["prose_excluded"]


def test_non_rtl_context_keys_ignored():
    # a docs/spec.md context entry is not a module → not counted
    r = detect("modify foo", ["rtl/foo.sv", "docs/spec.md"])
    assert r["sibling_modules"] == ["foo"]
    assert r["has_siblings"] is False


def test_requirement_names_the_siblings():
    keys = ["rtl/elevator_control_system.sv", "rtl/floor_to_seven_segment.sv",
            "rtl/Binary2BCD.sv"]
    r = detect("complete the elevator_control_system", keys)
    assert r["has_siblings"] is True
    for s in ("elevator_control_system", "floor_to_seven_segment", "Binary2BCD"):
        assert s in r["requirement"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
