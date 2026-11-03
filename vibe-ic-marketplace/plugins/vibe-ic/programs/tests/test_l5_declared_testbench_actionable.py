"""A block with no built-in deck is actionable only through a declared testbench (#115)."""
import json
from pathlib import Path

import pytest

import l5_analog_block_spec_actionable_check as gate

SPEC = {"specs": [{"name": "capacitance", "unit": "pF", "typ": 25.0, "min": 22.5, "max": 27.5,
                   "target_raw": "25", "range_raw": "22.5-27.5"}]}
BENCH = {"block": "shared_cap", "ports": ["top", "vss"], "testbench": {
    "supply_exprs": ["1"], "stimulus": ["v1 top 0 {supply}"],
    "control": ["op", 'echo "MEAS capacitance=" 1']}}


def put(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))


def build(project, spec=SPEC, flow=None, bench=BENCH, btype="capacitor"):
    put(project, "phase1/generated_docs/L5_ADI_SPEC.json", {
        "analog_blocks": [{"name": "shared_cap", "type": btype, "spec": spec}]})
    if flow is not None:
        put(project, "input/analog_flow.json", flow)
    if bench is not None:
        put(project, "input/bench.json", bench)


DECLARED = {"blocks": {"shared_cap": {"testbench_inputs": "input/bench.json"}}}


def test_gate_has_no_builtin_capacitor_deck():
    consumer, _ = gate._load_consumer()
    assert "capacitor" not in gate._consumer_known_types(consumer)


def test_declared_testbench_makes_an_unknown_type_actionable(tmp_path):
    build(tmp_path, flow=DECLARED)
    result = gate.evaluate(tmp_path)
    assert result["verdict"] == "PASS" and result["failures"] == []
    assert result["blocks_actionable"] == 1


@pytest.mark.parametrize("flow,bench,named", [
    (None, None, "absent or not JSON"),
    ({"blocks": {}}, BENCH, "is not declared"),
    ({"blocks": {"shared_cap": {"testbench": "input/deck.sp"}}}, BENCH, "is not declared"),
    ({"blocks": {"shared_cap": {"testbench_inputs": ""}}}, BENCH, "is not declared"),
    ({"blocks": {"shared_cap": {"testbench_inputs": "input/missing.json"}}}, BENCH, "not a file"),
    ({"blocks": {"shared_cap": {"testbench_inputs": "../outside.json"}}}, BENCH, "not a file"),
    (DECLARED, "{not json", "is not JSON"),
    (DECLARED, {**BENCH, "block": "other"}, "must state block"),
    (DECLARED, {**BENCH, "ports": []}, "must state block"),
    (DECLARED, {**BENCH, "testbench": {"control": []}}, "must state block"),
    (DECLARED, {"block": "shared_cap", "ports": ["top"]}, "must state block"),
])
def test_block_with_neither_deck_nor_usable_declaration_still_fails(tmp_path, flow, bench, named):
    build(tmp_path, flow=flow, bench=bench)
    result = gate.evaluate(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "has no deck" in result["failures"][0] and named in result["failures"][0]


def test_another_blocks_declaration_does_not_count(tmp_path):
    build(tmp_path, flow={"blocks": {"other_cap": {"testbench_inputs": "input/bench.json"}}})
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"


@pytest.mark.parametrize("spec", [None, {"specs": []}, {"specs": [{"name": "capacitance", "unit": "pF"}]}, "25 pF"])
def test_declared_testbench_does_not_excuse_a_missing_spec(tmp_path, spec):
    build(tmp_path, spec=spec, flow=DECLARED)
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"
