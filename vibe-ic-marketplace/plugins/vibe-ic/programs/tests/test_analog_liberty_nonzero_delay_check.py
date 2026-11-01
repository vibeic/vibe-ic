"""Unit tests for analog_liberty_nonzero_delay_check.py.

Pins the deterministic Liberty non-degeneracy gate extracted from the
analog-hardmacro-gen "Do not generate Liberty with zero delays" rule.
Covers PASS (real non-zero timing), FAIL (area-only stub / all-zero /
missing / garbage), and the honest SKIP edge (no analog blocks).
"""
import importlib
import hashlib
from pathlib import Path
import json

import pytest

mod = importlib.import_module("analog_liberty_nonzero_delay_check")


# --------------------------------------------------------------------------
# Pure analyzer unit tests
# --------------------------------------------------------------------------

LIB_REAL = """library(ldo_lib) {
  cell(ldo) {
    area : 10000 ;
    pin(vout) {
      timing() {
        related_pin : "en" ;
        cell_rise(scalar) { values("0.42"); }
        cell_fall(scalar) { values("0.51"); }
      }
    }
    cell_leakage_power : 0.0031 ;
  }
}"""

LIB_AREA_ONLY = """library(ldo_stub) {
  cell(ldo) {
    area : 10000 ;
    pin(out) { direction : output; }
  }
}"""

LIB_ALL_ZERO = """library(ldo_lib) {
  cell(ldo) {
    pin(vout) {
      timing() {
        cell_rise(scalar) { values("0.0"); }
        cell_fall(scalar) { values("0"); }
      }
    }
    cell_leakage_power : 0.0 ;
  }
}"""

LIB_SETTLING_AS_ARC = """library(controlled_analog) {
  time_unit : "1us";
  cell(controlled_analog) {
    pin(out) {
      timing() {
        related_pin : "enable";
        cell_rise(scalar) { values("2.97"); }
        cell_fall(scalar) { values("4.50"); }
      }
    }
    cell_leakage_power : 0.0031;
  }
}"""

LIB_LEAKAGE_AND_CAPS_ONLY = """library(controlled_analog) {
  time_unit : "1ns";
  cell(controlled_analog) {
    cell_leakage_power : 0.0031;
    pin(enable) { direction : input; capacitance : 0.02; }
    pin(out) { direction : output; capacitance : 0.40; }
  }
}"""


def _clock(root, period_ns):
    l8 = root / "phase1" / "generated_docs" / "L8_TIMING_WAVEFORM.json"
    l8.parent.mkdir(parents=True, exist_ok=True)
    l8.write_text(json.dumps({
        "fields": {"clocks": [{"name": "clk", "period_ns": period_ns}]}
    }))


class TestAnalyzer:
    def test_real_has_nonzero(self):
        has_timing, values, cell = mod.analyze_liberty(LIB_REAL)
        assert has_timing is True
        assert cell == "ldo"
        assert any(v != 0.0 for v in values)
        assert 0.42 in values and 0.51 in values

    def test_area_only_has_no_timing(self):
        has_timing, values, cell = mod.analyze_liberty(LIB_AREA_ONLY)
        assert has_timing is False
        assert values == []
        assert cell == "ldo"

    def test_all_zero_detected(self):
        has_timing, values, cell = mod.analyze_liberty(LIB_ALL_ZERO)
        assert has_timing is True
        assert all(v == 0.0 for v in values)

    def test_arc_delay_parser_scopes_values_and_normalises_units(self):
        samples, unit = mod.liberty_arc_delays_ns(LIB_SETTLING_AS_ARC)
        assert unit == "1us"
        assert [(s["kind"], s["delay_ns"]) for s in samples] == [
            ("cell_rise", 2970.0), ("cell_fall", 4500.0)]

        # A power-table values() group is not a propagation-delay arc.
        power_only = """library(x) { time_unit : "1ns";
          cell(x) { internal_power() { rise_power(t) { values("9000"); } }
                    cell_leakage_power : 1.0; } }"""
        assert mod.liberty_arc_delays_ns(power_only)[0] == []

        commented = """library(x) { time_unit : "1ns";
          /* cell_rise(t) { values("9000"); } */
          // intrinsic_fall : 8000;
          cell(x) { cell_leakage_power : 1.0; } }"""
        assert mod.liberty_arc_delays_ns(commented)[0] == []


# --------------------------------------------------------------------------
# End-to-end fixtures
# --------------------------------------------------------------------------

def _mk(root, block, lib_text=None, corner=None, spec=True):
    a = root / "phase3" / "analog" / block
    a.mkdir(parents=True, exist_ok=True)
    if spec:
        (a / "spec.json").write_text(json.dumps({"block": block}))
    if corner is not None:
        (a / "corner_results.json").write_text(json.dumps(corner))
    if lib_text is not None:
        h = root / "phase3" / "analog" / "hardmacro" / block
        h.mkdir(parents=True, exist_ok=True)
        (h / f"{block}.lib").write_text(lib_text)


#: What the corner artefact these delays are derived from says its circuit
#: contains. `_provenance` says a real simulator ran; `design_content` says
#: what it was pointed at. Both PASS fixtures below now carry the second,
#: because this gate stopped signing off a Liberty for integration STA when
#: nothing on the tree names the circuit its delays model — and a fixture that
#: omitted it would be asserting that silence still signs off.
DESIGN_BOUND = "structure_and_geometry"


def test_pass_real_liberty(tmp_path):
    _mk(tmp_path, "ldo", LIB_REAL,
        corner={"_provenance": "real_ngspice",
                "design_content": DESIGN_BOUND})
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert "ldo" in res.summary["passed_blocks"]
    assert "ldo" in (res.summary.get("design_bound_blocks") or [])


def test_fail_area_only_stub(tmp_path):
    # The real A7 stub: area-only -> zero-delay defect -> FAIL.
    _mk(tmp_path, "ldo", LIB_AREA_ONLY)
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_NO_TIMING" in {f.rule for f in res.findings}


def test_fail_all_zero_delay(tmp_path):
    _mk(tmp_path, "ldo", LIB_ALL_ZERO)
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_ZERO_DELAY" in {f.rule for f in res.findings}


def test_fail_analog_settling_encoded_as_synchronous_arc(tmp_path):
    _clock(tmp_path, 1000.0)
    _mk(tmp_path, "controlled_analog", LIB_SETTLING_AS_ARC,
        corner={"_provenance": "real_ngspice",
                "design_content": DESIGN_BOUND})
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    finding = next(f for f in res.findings
                   if f.rule == "LIB_ARC_EXCEEDS_CLOCK_PERIOD")
    assert "cell_fall delay 4500 ns" in finding.message
    assert "design clock period 1000 ns" in finding.message
    assert ("an analog macro carries no synchronous cell arc; move the "
            "settling contract to interface.json timing_contract" in
            finding.message)
    assert res.summary["arc_period_violations"] == [{
        "block": "controlled_analog",
        "cell": "controlled_analog",
        "kind": "cell_fall",
        "delay_ns": 4500.0,
        "clock_period_ns": 1000.0,
        "time_unit": "1us",
        "samples_over_period": 2,
    }]


def test_output_without_arcs_still_requires_timing(tmp_path):
    _clock(tmp_path, 1000.0)
    _mk(tmp_path, "controlled_analog", LIB_LEAKAGE_AND_CAPS_ONLY,
        corner={"_provenance": "real_ngspice",
                "design_content": DESIGN_BOUND})
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_NO_TIMING" in {f.rule for f in res.findings}
    assert res.summary["arc_delay_samples_examined"] == 0
    assert res.summary["arc_period_violations"] == []


def test_pass_propagation_arc_at_or_below_clock_period(tmp_path):
    # The worst sample equals the period exactly; only strictly slower arcs
    # violate the rule.
    _clock(tmp_path, 4.5)
    lib = LIB_SETTLING_AS_ARC.replace('time_unit : "1us"',
                                     'time_unit : "1ns"')
    _mk(tmp_path, "controlled_analog", lib,
        corner={"_provenance": "real_ngspice",
                "design_content": DESIGN_BOUND})
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert res.summary["arc_delay_samples_examined"] == 2


def test_fail_clocked_arc_without_a_liberty_time_unit(tmp_path):
    _clock(tmp_path, 1000.0)
    lib = LIB_SETTLING_AS_ARC.replace('  time_unit : "1us";\n', '')
    _mk(tmp_path, "controlled_analog", lib,
        corner={"_provenance": "real_ngspice",
                "design_content": DESIGN_BOUND})
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_ARC_TIME_UNIT_UNDECLARED" in {f.rule for f in res.findings}


def test_fail_missing_lib(tmp_path):
    _mk(tmp_path, "ldo", lib_text=None)
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_MISSING" in {f.rule for f in res.findings}


def test_fail_no_cell(tmp_path):
    _mk(tmp_path, "ldo", "library(x) {\n  /* no cell */\n}")
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_NO_CELL" in {f.rule for f in res.findings}


def test_skip_no_analog(tmp_path):
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert res.summary.get("skipped") is True


def test_provenance_reported(tmp_path):
    _mk(tmp_path, "ldo", LIB_REAL,
        corner={"_provenance": "real_ngspice",
                "design_content": DESIGN_BOUND})
    res = mod.run_audit(tmp_path)
    ok = [f for f in res.findings if f.rule == "LIB_NONZERO_OK"]
    assert ok and "real_ngspice" in ok[0].message
    # ...and the finding says what the simulator was pointed AT, not only
    # that a simulator ran. The first was always true and always silent
    # about the subject, which is the defect one field along.
    assert "design-bound" in ok[0].message


def test_a_nondegenerate_liberty_that_names_no_circuit_does_not_sign_off(
        tmp_path):
    """The rule the two fixtures above now state, asserted rather than left
    implicit. A non-zero delay taken from an unattributable circuit is a real
    number about nothing this project can name, and integration STA will
    consume it as this design's."""
    _mk(tmp_path, "ldo", LIB_REAL, corner={"_provenance": "real_ngspice"})
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_SUBJECT_UNDECLARED" in {f.rule for f in res.findings}


def test_a_disclosed_library_default_still_signs_off_in_its_own_tier(
        tmp_path, capsys):
    """Only silence costs. A Liberty whose corner artefact records a library
    default still signs off — in the structure-only tier, never as a
    design-bound pass — because failing an honest ceiling teaches the next run
    to stop being honest.

    Asserted through the VERDICT WORD first, deliberately: the tier has to
    reach the one line a reader reads, and a test whose first failure is a
    missing JSON key would report a shape change where the defect is a wrong
    certification.
    """
    _mk(tmp_path, "ldo", LIB_REAL,
        corner={"_provenance": "real_ngspice",
                "design_content": "structure_only"})
    rc = mod.main([str(tmp_path)])
    cap = capsys.readouterr()
    assert rc == 0, cap.out + cap.err
    assert "[PASS_STRUCTURE_ONLY]" in cap.out, cap.out
    assert "STRUCTURE_ONLY:" in cap.err, cap.err
    res = mod.run_audit(tmp_path)
    assert res.summary.get("structure_only_blocks") == ["ldo"]
    assert res.summary.get("design_bound_blocks") == []


def test_main_cli_fail_exit_1(tmp_path):
    _mk(tmp_path, "ldo", LIB_AREA_ONLY)
    out = tmp_path / "rep.json"
    rc = mod.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["passed"] is False


def test_main_cli_not_a_dir(tmp_path):
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2


PASSIVE_LIB = Path(__file__).parent / "fixtures/passive_pg_only.lib"
PASSIVE_LIB_SHA256 = "5e34ac0e49f92e72c1155a527b1985b37c66b3f1106985962d936dd464fa1918"


def _native_passive_case(root, roles=("cap",), power=0.0):
    producer = importlib.import_module("analog_a8_hardmacro_emit")
    text = PASSIVE_LIB.read_text()
    block = mod.analyze_liberty(text)[2]
    _mk(root, block, text, corner={"design_content": DESIGN_BOUND})
    b = root / "phase3/analog" / block
    topology = {"ports": ["TOP", "VSS"],
                "rails": {"vdd": "TOP", "vss": "VSS"}}
    if roles is not None:
        topology["devices"] = [{"role": role} for role in roles]
    (b / "topology.json").write_text(json.dumps(topology))
    files = {"source_layout": "layout.mag", "source_gds": f"{block}.gds",
             "source_netlist": "post_layout_extracted.spice", "native_log": "op.log"}
    contents = {"source_layout": "magic\ntech fixture\n",
                "source_gds": "fixture layout bytes",
                "source_netlist": f".subckt {block} TOP VSS\n.ends {block}\n",
                "native_log": f"ngspice-47\npwr = {power:.12g}\n"}
    rec = {"schema": producer._A8_MEASUREMENT_SCHEMA,
           "status": "MEASURED", "block": block, "metric": "cell_leakage_power",
           "value": power, "unit": "W", "provenance": "real_ngspice",
           "simulator": "ngspice-47", "image_digest": "sha256:" + "a" * 64,
           "native_binary": {"path": "/fixture/ngspice", "sha256": "c" * 64,
                             "selection": "discovered"},
           "declared_ports": topology["ports"]}
    for field, name in files.items():
        path = b / name
        path.write_text(contents[field])
        rec[field] = str(path.relative_to(root))
        rec[field + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (b / "a8_measurement.json").write_text(json.dumps(rec))
    return b, root / "phase3/analog/hardmacro" / block / f"{block}.lib"


def test_r63_p1_retained_passive_native_zero_has_no_delay_defect(tmp_path):
    assert hashlib.sha256(PASSIVE_LIB.read_bytes()).hexdigest() == PASSIVE_LIB_SHA256
    _native_passive_case(tmp_path, roles=("cap",) * 56)
    result = mod.run_audit(tmp_path)
    assert result.passed, [(f.rule, f.message) for f in result.findings]
    assert not {"LIB_NO_TIMING", "LIB_ZERO_DELAY"}.intersection(f.rule for f in result.findings)
    assert result.summary["arc_delay_samples_examined"] == 0


@pytest.mark.parametrize("power", [0, 1e-6])
def test_r63_n1_zero_delay_is_not_hidden_by_leakage(tmp_path, power):
    _mk(tmp_path, "active", LIB_ALL_ZERO.replace(
        "cell_leakage_power : 0.0", f"cell_leakage_power : {power}"),
        corner={"design_content": DESIGN_BOUND})
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_ZERO_DELAY" in {f.rule for f in result.findings}


@pytest.mark.parametrize("roles", [("nmos",), ("bjt",), ("cap", "nmos"), (), None],
                         ids=["active", "bjt", "mixed", "empty", "missing"])
def test_r63_n2_zero_leakage_keeps_existing_inventory_refusals(tmp_path, roles):
    _native_passive_case(tmp_path, roles=roles)
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_LEAKAGE_UNMEASURED" in {f.rule for f in result.findings}


def test_r63_n3_signal_output_without_arcs_is_not_exempt(tmp_path):
    _, lib = _native_passive_case(tmp_path)
    lib.write_text(lib.read_text().replace('    pg_pin (TOP)',
        '    pin (out) { direction : output; }\n    pg_pin (TOP)'))
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_NO_TIMING" in {f.rule for f in result.findings}


def test_r63_n4_missing_leakage_attribute_is_rejected(tmp_path):
    _, lib = _native_passive_case(tmp_path)
    lib.write_text(lib.read_text().replace('    cell_leakage_power : 0;\n', ''))
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_LEAKAGE_UNMEASURED" in {f.rule for f in result.findings}


@pytest.mark.parametrize("mutation", ["missing_measurement", "failed_measurement", "stale_log", "mismatched_value"])
def test_r63_no_arc_model_still_requires_bound_native_leakage(tmp_path, mutation):
    b, lib = _native_passive_case(tmp_path)
    path = b / "a8_measurement.json"
    if mutation == "missing_measurement":
        path.unlink()
    elif mutation == "failed_measurement":
        doc = json.loads(path.read_text()); doc["status"] = "FAIL"
        path.write_text(json.dumps(doc))
    elif mutation == "stale_log":
        (b / "op.log").write_text("ngspice-47\npwr = 1\n")
    else:
        lib.write_text(lib.read_text().replace("cell_leakage_power : 0;", "cell_leakage_power : 1;"))
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_LEAKAGE_UNMEASURED" in {f.rule for f in result.findings}


def test_r63_power_attributes_are_not_delays():
    text = PASSIVE_LIB.read_text().replace('    cell_leakage_power : 0;',
        '    cell_leakage_power : 1;\n    leakage_power() { value : 2; }\n'
        '    internal_power() { rise_power(t) { values("3"); } }')
    has_timing, values, _ = mod.analyze_liberty(text)
    assert not has_timing
    assert values == []


@pytest.mark.parametrize("roles", [("nmos",), ("bjt",), ("cap", "nmos"), (), None],
                         ids=["active", "bjt", "mixed", "empty", "missing"])
def test_r63_n2_nonzero_arcs_cannot_hide_zero_leakage(tmp_path, roles):
    _, lib = _native_passive_case(tmp_path, roles=roles)
    lib.write_text(lib.read_text().replace('    pg_pin (TOP)',
        '    pin (out) { direction : output; timing() {\n'
        '      cell_rise(scalar) { values("0.5"); } } }\n    pg_pin (TOP)'))
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_LEAKAGE_UNMEASURED" in {f.rule for f in result.findings}


def test_r63_empty_timing_table_is_not_a_power_only_cell(tmp_path):
    _, lib = _native_passive_case(tmp_path)
    lib.write_text(lib.read_text().replace('    pg_pin (TOP)',
        '    pin (out) { direction : output; timing() {\n'
        '      cell_rise(scalar) { values(""); } } }\n    pg_pin (TOP)'))
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_NO_TIMING" in {f.rule for f in result.findings}


def test_r63_characterized_positive_active_power_only_cell(tmp_path):
    _, lib = _native_passive_case(tmp_path, roles=("nmos",), power=1e-6)
    lib.write_text(lib.read_text().replace('cell_leakage_power : 0;',
                                          'cell_leakage_power : 1;'))
    result = mod.run_audit(tmp_path)
    assert result.passed, [(f.rule, f.message) for f in result.findings]


def test_r63_power_only_cell_cannot_hide_unavailable_inventory(tmp_path):
    _, lib = _native_passive_case(tmp_path, roles=None, power=1e-6)
    lib.write_text(lib.read_text().replace('cell_leakage_power : 0;',
                                          'cell_leakage_power : 1;'))
    result = mod.run_audit(tmp_path)
    assert not result.passed
    assert "LIB_LEAKAGE_UNMEASURED" in {f.rule for f in result.findings}
