#!/usr/bin/env python3
"""Smoke tests for l2_named_constant_resolvable_check.py.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every behaviour is asserted
in BOTH directions: an L2 gutted of the constant a sibling L-doc
dereferences BY NAME must FAIL (rc 1), and the same fixture with the
constant restored must PASS (rc 0). A test that cannot fail proves
nothing.

All fixtures are SYNTHESIZED neutral data — invented constant names on
an invented block. No real design's files are copied.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "l2_named_constant_resolvable_check.py"

_spec = importlib.util.spec_from_file_location(
    "l2_named_constant_resolvable_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _gen(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(project: Path, name: str, obj):
    (_gen(project) / name).write_text(json.dumps(obj, ensure_ascii=False),
                                      encoding="utf-8")


def _run(project: Path):
    out = project / "verdict.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# A sibling L-doc that dereferences an L2 constant BY NAME, in the shape
# l9_response_delay_schema_check mandates.
_L9_WITH_REF = {
    "modules": {
        "synth_dispatcher": {
            "role": "command dispatcher",
            "response_delay": {
                "required": True,
                "spec_constant": "turnaround_gap_us",
                "reference_event": "end_of_trailing_delimiter",
                "min_cycles": 4,
            },
        }
    }
}

_L2_RESOLVED = {
    "ic_name": "synth_block",
    "timing_parameters": [
        {"name": "turnaround_gap_us", "parameter": "turnaround_gap_us",
         "value": 30.0, "unit": "us", "evidence": "input/docs/iface.md"},
        {"name": "frame_period_us", "parameter": "frame_period_us",
         "value": 500.0, "unit": "us", "evidence": "input/docs/iface.md"},
    ],
}


# -------------------------------------------------- POSITIVE: well-formed
def test_pass_reference_resolves_to_a_number(tmp_path):
    _write(tmp_path, "L2_FRS.json", _L2_RESOLVED)
    _write(tmp_path, "L9_INTEGRATION_SPEC.json", _L9_WITH_REF)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    # The required name was DERIVED from the sibling L-doc, not hardcoded.
    assert rep["required_constants"] == 1
    assert rep["unresolved_constants"] == []


# ------------- NEGATIVE CONTROL: the constant is missing from the layer
def test_fail_gutted_layer_missing_the_referenced_constant(tmp_path):
    """The motivating shape: L9 names it, L2 contains it 0 times.

    L2 is NOT empty — it still publishes a numeric timing record, so
    `l2_timing_completeness_check` (key-presence shaped) would PASS.
    Only the consumer-contract check catches it.
    """
    gutted = {"ic_name": "synth_block", "timing_parameters": [
        {"name": "frame_period_us", "parameter": "frame_period_us",
         "value": 500.0, "unit": "us"}]}
    _write(tmp_path, "L2_FRS.json", gutted)
    _write(tmp_path, "L9_INTEGRATION_SPEC.json", _L9_WITH_REF)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"
    assert len(rep["unresolved_constants"]) == 1
    v = rep["unresolved_constants"][0]
    assert v["constant"] == "turnaround_gap_us"
    assert v["kind"] == "absent_from_l2"
    # Non-empty timing block proves a presence-shaped check would pass.
    assert rep["timing_records"] == 1


def test_fail_present_but_not_numeric(tmp_path):
    """Name present, value prose -> present but NOT actionable."""
    half = {"ic_name": "synth_block", "timing_parameters": [
        {"name": "turnaround_gap_us", "parameter": "turnaround_gap_us",
         "value": "see vendor timing appendix", "unit": "us"}]}
    _write(tmp_path, "L2_FRS.json", half)
    _write(tmp_path, "L9_INTEGRATION_SPEC.json", _L9_WITH_REF)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["unresolved_constants"][0]["kind"] == "present_but_not_numeric"


def test_pass_once_the_constant_is_restored(tmp_path):
    """Direction 2 of the same control."""
    _write(tmp_path, "L2_FRS.json", _L2_RESOLVED)
    _write(tmp_path, "L9_INTEGRATION_SPEC.json", _L9_WITH_REF)
    assert _run(tmp_path)[0] == 0


def test_dotted_reference_shape_also_derived(tmp_path):
    """`L2.<name>` as a whole-string value is a machine-readable ref."""
    _write(tmp_path, "L2_FRS.json", {"timing_parameters": []})
    _write(tmp_path, "L8_SUBMODULE.json",
           {"frame_end_gap": {"derived_from_ref": "L2.inter_byte_us"}})
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["unresolved_constants"][0]["constant"] == "inter_byte_us"


# --------------------------------- NEGATIVE CONTROL on limb 2 (records)
def test_fail_published_timing_record_without_a_number(tmp_path):
    _write(tmp_path, "L2_FRS.json", {"timing_parameters": [
        {"name": "settle_us", "parameter": "settle_us",
         "value": None, "unit": "us"}]})
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["unactionable_records"][0]["kind"] == \
        "timing_record_no_numeric_value"


def test_pass_same_record_with_a_number(tmp_path):
    _write(tmp_path, "L2_FRS.json", {"timing_parameters": [
        {"name": "settle_us", "parameter": "settle_us",
         "value": 12.5, "unit": "us"}]})
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"


# ------------------------------------------- FALSE-POSITIVE regressions
def test_prose_mentioning_l2_dot_something_is_not_a_reference(tmp_path):
    """Measured FP: this exact prose appears in 26/26 real Phase-1 runs.

    `L2.protocol_overview` is legitimately null under
    `no_protocol_overview_in_input`. An unanchored regex treats the
    sentence as a reference and fires on 100% of runs.
    """
    _write(tmp_path, "L2_FRS.json",
           {"protocol_overview": None, "no_protocol_overview_in_input": True})
    _write(tmp_path, "L3_CMD_PROTOCOL.json", {
        "opcodes": [],
        "opcode_synthesis_skipped_reason":
            "L2.protocol_overview.half_duplex is not True and no explicit "
            "opcode/command-table heading was found in input/docs/.",
    })
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["required_constants"] == 0


def test_min_max_range_record_counts_as_actionable(tmp_path):
    _write(tmp_path, "L2_FRS.json", {"timing_parameters": [
        {"name": "gap_us", "min": 20, "max": 40, "unit": "us"}]})
    rc, rep = _run(tmp_path)
    assert rc == 0, rep


# -------------------------------------------------------------- plumbing
def test_waiver_downgrades_fail(tmp_path):
    _write(tmp_path, "L2_FRS.json", {"timing_parameters": []})
    _write(tmp_path, "L9_INTEGRATION_SPEC.json", _L9_WITH_REF)
    (tmp_path / "waivers.json").write_text(json.dumps({
        mod.WAIVER_KEY: "turnaround_gap_us lives solely in L8 for this "
                        "design; L2 intentionally carries no copy."}))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS_WITH_WAIVER"


def test_rc2_when_l2_absent(tmp_path):
    _gen(tmp_path)
    assert _run(tmp_path)[0] == 2


def test_rc2_when_project_dir_absent(tmp_path):
    assert mod.main([str(tmp_path / "nope")]) == 2
