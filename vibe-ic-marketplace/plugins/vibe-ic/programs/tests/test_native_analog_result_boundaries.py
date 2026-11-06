"""Retained native data needs engineering checks without identity records."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a2_topology_emit as topology
import analog_incremental_capture as capture
import em_current_density_check as em
from test_native_em_result_cutover import density, write_rows


@pytest.fixture(scope="module")
def folded_design(tmp_path_factory):
    project = tmp_path_factory.mktemp("folded-circuit")
    directory = project / "phase3/analog/cell"
    directory.mkdir(parents=True)
    values = {"order": 2.0, "osr": 512.0, "enob": 14.0, "vref": 1.0,
              "vdd": 1.2, "vindiff": 1.0, "fclk": 1.0, "fclk_max": 1.0}
    measured = {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": 0.04,
                "rsheet_ohm_per_sq": 260.0, "k_prime_n_ua_per_v2": 328.0,
                "vth_n_extracted_v": 0.197}
    sizing = {"knobs": {"ota_folded_cascode_first_stage": True},
              "device_parameters": {}}
    stage_geometry = [("mn_tail", 8, 1), ("mn_in", 48, 1), ("mn_ref", 48, 1),
                      ("mp_fc_top_in", 192, 1), ("mp_fc_top_ref", 192, 1),
                      ("mp_fc_in", 64, 1), ("mp_fc_ref", 64, 1),
                      ("mn_fc_load_in", 48, 2), ("mn_fc_load_ref", 48, 2),
                      ("mn_fc_cas_in", 48, 2), ("mn_fc_cas_ref", 48, 2)]
    for stage in (1, 2):
        for name, width, length in stage_geometry:
            sizing["device_parameters"][name + str(stage)] = {"w": width, "l": length}
    for name, width, length in [("mp_fc_bias", 16, 1), ("mn_fc_bias_sink", .5, 1),
                                ("mp_fc_bias_source", 16, 1), ("mn_fc_bias", 12, 2),
                                ("r_fc_p_shift", .5, 56.11), ("r_fc_n_shift", .5, 56.11)]:
        sizing["device_parameters"][name] = {"w": width, "l": length}
    (directory / "sizing_inputs.json").write_text(json.dumps(sizing))
    (directory / "spec.json").write_text(json.dumps({"specs": [
        {"name": name, "target": value} for name, value in values.items()]}))
    ir = topology.build_ir("cell", "delta_sigma", {}, topology.LIBRARY["delta_sigma"],
                           values, None, project, None, {}, measured_params=measured)
    assert topology.folded_first_stage_problems(ir, project) == []
    return project, ir


@pytest.mark.parametrize("field", ["evidence", "input_view"])
def test_old_identity_metadata_does_not_reject_the_same_physical_circuit(folded_design, field):
    project, original = folded_design
    ir = copy.deepcopy(original)
    if field == "evidence":
        ir["folded_first_stage"][field] = {
            "references": {"decision": {"path": "missing-old-report.json", "sha256": "old"}},
            "parent_history_entries": 5}
    else:
        ir["folded_first_stage"][field]["sha256"] = "old"
    assert topology.folded_first_stage_problems(ir, project) == []


@pytest.mark.parametrize("changed", ["width", "body", "duplicate"])
def test_actual_folded_geometry_and_connectivity_still_fail(folded_design, changed):
    project, original = folded_design
    ir = copy.deepcopy(original)
    device = next(row for row in ir["devices"] if row["name"] == "mn_fc_load_in1")
    if changed == "width":
        device["w"] += 0.25
    elif changed == "body":
        device["nets"][-1] = "vdd"
    else:
        ir["devices"].append(copy.deepcopy(device))
    assert topology.folded_first_stage_problems(ir, project)


@pytest.fixture
def incomplete_native_record(tmp_path):
    netlist = tmp_path / "cell.sp"
    netlist.write_text(".subckt cell a b\nR1 a b 1k\n.ends cell\n")
    raw = tmp_path / "capture.dat"
    raw.write_text("time out reset input\n0 0 0 0\n")
    log = tmp_path / "native.log"
    log.write_text("native execution completed\n")
    return {"native_inputs": {"netlist": {"path": str(netlist)},
                              "include:" + str(netlist): {"path": str(netlist)}},
            "incremental_decode": {"native_timing": {
                "kind": "source_derived_sc_transfer_gates_v1", "groups": [{}]}},
            "capture": {"path": str(raw)}, "clock": [0, 1, 1],
            "settings": {"phase_index": 0},
            "executions": [{"returncode": 0, "log": str(log)}]}


@pytest.mark.parametrize("missing", ["clock", "settings"])
def test_missing_capture_metadata_is_unmeasured_without_a_crash(incomplete_native_record, missing):
    incomplete_native_record.pop(missing)
    valid, _ = capture.validate_point(incomplete_native_record)
    assert valid is False


def test_native_execution_failure_keeps_its_fail_verdict(incomplete_native_record):
    incomplete_native_record["executions"][0]["returncode"] = 1
    result = capture.coherent_sndr([incomplete_native_record], 4, 1, 12)
    assert result["status"] == "FAIL"


def test_measured_ir_overlimit_stays_fail_with_missing_supply_coverage(tmp_path):
    reports = tmp_path / "reports/phase3"
    reports.mkdir(parents=True)
    (reports / "ir_drop.json").write_text(json.dumps({
        "verdict": "PASS", "native_rc": 0, "worst_ir_uv": 60000,
        "vdd_v": 1.0, "unconnected_supply_pins": 1}))
    result = em.validate_primary_ir(tmp_path)
    assert result["verdict"] == "FAIL"


@pytest.mark.parametrize("missing", ["summary_only", "csv_first", "csv_last"])
def test_measured_em_violation_stays_fail_with_another_supply_missing(density, missing):
    project, reports, doc, row = density
    row.update(Status="VIOLATED", Ratio=2)
    write_rows(reports / "em_openroad_density_VDD.csv", [row])
    subject_path = reports / "em.json"
    subject = json.loads(subject_path.read_text())
    subject["nets_analysed"].append("VSS")
    subject_path.write_text(json.dumps(subject))
    if missing != "summary_only":
        nets = ["VSS", "VDD"] if missing == "csv_first" else ["VDD", "VSS"]
        doc["nets"] = {net: {} for net in nets}
        (reports / "em_openroad_density.json").write_text(json.dumps(doc))
    result = em.validate_native_density(project, segment_geometry={})
    assert result["verdict"] == "FAIL"
