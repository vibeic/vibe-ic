#!/usr/bin/env python3
"""Tests for analog_meas_from_spec_gen.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_meas_from_spec_gen as generator

PROG = Path(__file__).resolve().parent.parent / "analog_meas_from_spec_gen.py"


def test_explicit_native_bindings_use_actual_branch_and_declared_frequency(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"specs": [
        {"name": "iq", "max": 50, "unit": "uA", "measurement": {
            "analysis": "OP", "expression": "(-i(v_supply)-0.0005)*1e6"}},
        {"name": "psrr", "min": 40, "unit": "dB", "measurement": {
            "analysis": "AC", "expression": "-vdb(vout)", "frequency_hz": 173}}]}))
    rc, report, deck = generator.run(path)
    assert rc == 0 and report["meas_lines"] == 2
    assert "(-i(v_supply)-0.0005)*1e6" in deck
    assert "meas AC psrr FIND bound_psrr AT=173" in deck
    assert "AT=1k" not in deck and "target=50" not in deck


@pytest.mark.parametrize("binding", [
    {"analysis": "AC", "expression": "-vdb(vout)"},
    {"analysis": "DC", "expression": "v(vout)"},
    {"analysis": "OP", "expression": "v(out)\nquit"}])
def test_incomplete_or_multicommand_explicit_binding_is_refused(binding):
    with pytest.raises(ValueError):
        generator.measurement_commands("output_metric", binding)


@pytest.mark.parametrize("statistic", ["AVG", "RMS", "MAX", "MIN", "INTEG"])
def test_explicit_transient_statistic_uses_native_time_window(statistic):
    lines, kind = generator.measurement_commands("idd", {"analysis": "TRAN",
        "expression": "-i(v_supply)", "statistic": statistic, "from_s": 7e-6, "to_s": 9e-6}, stop_s=9.1e-6)
    assert kind == "TRAN" and lines[0] == "let bound_idd = -i(v_supply)"
    assert lines[1] == f"meas TRAN idd {statistic} bound_idd FROM={7e-6:.17g} TO={9e-6:.17g}"
    assert not any("mean(" in line or "avg(" in line for line in lines)


@pytest.mark.parametrize("changed", [{"statistic": "mean"}, {"from_s": -1},
    {"from_s": True}, {"from_s": float("nan")}, {"to_s": float("inf")},
    {"to_s": 1e-6}, {"to_s": 12e-6}])
def test_invalid_transient_statistic_or_window_is_refused(changed):
    binding = {"analysis": "TRAN", "expression": "v(out)", "statistic": "AVG",
               "from_s": 1e-6, "to_s": 9e-6, **changed}
    with pytest.raises(ValueError):
        generator.measurement_commands("metric", binding, stop_s=9.1e-6)


def _run(spec_path: Path, out: Path = None, jpath: Path = None):
    cmd = [sys.executable, str(PROG), str(spec_path)]
    if out:
        cmd += ["--out", str(out)]
    if jpath:
        cmd += ["--json", str(jpath)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_pass_emits_dc_ac_tran(tmp_path):
    spec = {"specs": [
        {"name": "vout_dc", "value": 3.3, "unit": "V", "measurement":
            {"analysis": "DC", "expression": "v(result)", "at": "last"}},
        {"name": "gain_db", "value": 60, "unit": "dB", "measurement":
            {"analysis": "AC", "expression": "vdb(result)", "frequency_hz": 1700}},
        {"name": "tpd", "value": 5, "unit": "ns", "measurement":
            {"analysis": "TRAN", "expression": "v(result)", "statistic": "MAX",
             "from_s": 1e-9, "to_s": 5e-9}}],
        "name": "amp",          # non-measurable, ignored
    }
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    out = tmp_path / "meas.inc"
    jp = tmp_path / "r.json"
    r = _run(sp, out=out, jpath=jp)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(jp.read_text())
    assert rep["summary"]["pass"] is True
    assert rep["summary"]["meas_lines"] == 3
    deck = out.read_text()
    assert "let bound_vout_dc = v(result)" in deck
    assert "meas AC gain_db FIND bound_gain_db AT=1700" in deck
    assert "meas TRAN tpd MAX bound_tpd" in deck
    assert "V(vout)" not in deck and "AT=1k" not in deck and "VAL=vmid" not in deck


def test_pass_nested_specs_object(tmp_path):
    spec = {"specs": {
        "vref": {"value": 1.2, "unit": "V", "measurement":
                 {"analysis": "OP", "expression": "v(reference)"}},
        "ugbw": {"value": 1e6, "unit": "Hz", "measurement":
                 {"analysis": "AC", "expression": "vdb(result)",
                  "frequency_hz": 1e6}}}}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 0
    rep = json.loads(jp.read_text())
    kinds = {e["kind"] for e in rep["summary"]["emitted"]}
    assert kinds == {"OP", "AC"}


def test_pass_canonical_specs_list_preserves_declared_target_bounds_and_unit(
        tmp_path):
    spec = {"specs": [{"name": "tpd", "target": 5.0,
                        "min": 4.0, "max": 6.0, "unit": "ns",
                        "measurement": {"analysis": "TRAN",
                            "expression": "v(result)", "statistic": "MAX",
                            "from_s": 1e-9, "to_s": 5e-9}}]}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    out = tmp_path / "meas.inc"
    jp = tmp_path / "r.json"
    r = _run(sp, out=out, jpath=jp)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(jp.read_text())
    assert rep["summary"]["schema"] == "canonical_list"
    assert rep["summary"]["emitted"] == [{"key": "tpd", "kind": "TRAN"}]
    assert ("source_measurement tpd target=5.0 min=4.0 max=6.0 unit=ns row_sha256="
            in out.read_text())


def test_canonical_list_and_map_emit_the_same_measurement(tmp_path):
    map_spec = tmp_path / "map.json"
    list_spec = tmp_path / "list.json"
    map_spec.write_text(json.dumps(
        {"tpd": {"target": 5.0, "unit": "ns", "measurement":
                 {"analysis": "TRAN", "expression": "v(result)",
                  "statistic": "MAX", "from_s": 1e-9, "to_s": 5e-9}}}))
    list_spec.write_text(json.dumps(
        {"specs": [{"name": "tpd", "target": 5.0, "unit": "ns",
                    "measurement": {"analysis": "TRAN", "expression": "v(result)",
                                    "statistic": "MAX", "from_s": 1e-9,
                                    "to_s": 5e-9}}]}))
    map_result = _run(map_spec)
    list_result = _run(list_spec)
    assert map_result.returncode == list_result.returncode == 0
    assert map_result.stdout.splitlines()[2:] == list_result.stdout.splitlines()[2:]
    assert map_result.stdout.splitlines()[1] != list_result.stdout.splitlines()[1]


def test_refuses_entire_deck_when_enob_has_no_coherent_measurement_contract(
        tmp_path):
    spec = {"specs": [
        {"name": "tpd", "target": 5.0, "unit": "ns", "measurement":
            {"analysis": "TRAN", "expression": "v(result)", "statistic": "MAX",
             "from_s": 1e-9, "to_s": 5e-9}},
        {"name": "enob", "min": 14.0, "unit": "bit"},
    ]}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    out = tmp_path / "meas.inc"
    jp = tmp_path / "r.json"
    r = _run(sp, out=out, jpath=jp)
    assert r.returncode == 1
    assert not out.exists()
    rep = json.loads(jp.read_text())["summary"]
    assert rep["reason"] == "unsupported_measurements"
    assert rep["meas_lines"] == 0
    assert rep["unsupported"] == [{
        "name": "enob", "reason": "unsupported_measurement_template",
        "unit": "bit"}]


def test_refuses_explicit_window_instead_of_silently_dropping_it(tmp_path):
    spec = {"specs": [{"name": "settling", "max": 2.0, "unit": "us",
                        "measurement_window": {"from_s": 1e-6,
                                               "to_s": 3e-6}}]}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 1
    summary = json.loads(jp.read_text())["summary"]
    assert summary.get("reason") == "unsupported_measurements"
    assert summary.get("unsupported") == [{
        "name": "settling", "reason": "unsupported_measurement_window",
        "window": {"measurement_window": {"from_s": 1e-6,
                                             "to_s": 3e-6}}}]


def test_source_unit_mutation_refuses_instead_of_emitting_unbound_measurement(tmp_path):
    spec = {"specs": [{"name": "settling", "max": 4.0, "unit": "us",
        "measurement": {"analysis": "TRAN", "expression": "v(result)",
                        "statistic": "AVG", "from_s": 1e-6, "to_s": 3e-6}}]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    rc, summary, deck = generator.run(path)
    assert rc == 0
    assert summary["source_spec_sha256"] in deck
    del spec["specs"][0]["unit"]
    path.write_text(json.dumps(spec))
    rc, summary, deck = generator.run(path)
    assert rc == 1
    assert summary["unsupported"] == [{
        "name": "settling", "reason": "source_unit_not_declared"}]
    assert deck == ""


def test_recognizable_map_key_without_binding_refuses_instead_of_inventing_defaults(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"vout_dc": {"value": 1.7, "unit": "V"}}))
    rc, summary, deck = generator.run(path)
    assert rc == 1
    assert summary["unsupported"] == [{"name": "vout_dc",
        "reason": "measurement_binding_not_declared", "unit": "V"}]
    assert deck == ""


def test_duplicate_measurement_name_across_source_containers_is_ambiguous(tmp_path):
    bound = {"name": "response", "unit": "V", "measurement":
             {"analysis": "OP", "expression": "v(result)"}}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"specs": [bound], "targets": [bound]}))
    rc, summary, deck = generator.run(path)
    assert rc == 2
    assert summary["rows"] == [{"container": "targets", "index": 0,
                                 "name": "response", "reason": "duplicate_name"}]
    assert deck == ""


def test_custom_map_binding_requires_source_unit(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"custom_metric": {
        "measurement": {"analysis": "OP", "expression": "v(result)"}}}))
    rc, summary, deck = generator.run(path)
    assert rc == 1
    assert summary["unsupported"] == [{
        "name": "custom_metric", "reason": "source_unit_not_declared"}]
    assert deck == ""


def test_custom_map_binding_with_unit_remains_supported(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"custom_metric": {"unit": "V",
        "measurement": {"analysis": "OP", "expression": "v(result)"}}}))
    rc, summary, deck = generator.run(path)
    assert rc == 0
    assert summary["emitted"] == [{"key": "custom_metric", "kind": "OP"}]
    assert "source_measurement custom_metric unit=V row_sha256=" in deck


def test_casefold_duplicate_across_source_containers_is_ambiguous(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({
        "specs": [{"name": "Gain", "unit": "dB", "measurement":
                   {"analysis": "OP", "expression": "v(a)"}}],
        "targets": [{"name": "gain", "unit": "dB", "measurement":
                     {"analysis": "OP", "expression": "v(b)"}}]}))
    rc, summary, deck = generator.run(path)
    assert rc == 2
    assert summary["rows"] == [{"container": "targets", "index": 0,
                                 "name": "gain", "reason": "duplicate_name"}]
    assert deck == ""


def test_fail_missing_spec(tmp_path):
    r = _run(tmp_path / "nope.json")
    assert r.returncode == 1


def test_fail_no_measurable_keys(tmp_path):
    spec = {"author": "x", "revision": 3, "notes": "draft"}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 1
    rep = json.loads(jp.read_text())
    assert rep["summary"]["pass"] is False
    assert rep["summary"]["reason"] == "no_measurable_keys"


def test_edge_garbage_json_exit2(tmp_path):
    sp = tmp_path / "spec.json"
    sp.write_text("{ not valid json ")
    r = _run(sp)
    assert r.returncode == 2


def test_edge_non_object_json_exit2(tmp_path):
    sp = tmp_path / "spec.json"
    sp.write_text("[1, 2, 3]")
    r = _run(sp)
    assert r.returncode == 2
