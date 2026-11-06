"""Native IR/PSM report consumers compare engineering numbers without passports."""
from pathlib import Path
import csv
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import em_current_density_check as em


@pytest.fixture
def density(tmp_path):
    rpt = tmp_path / "reports/phase3"
    rpt.mkdir(parents=True)
    lef = rpt / "native.tlef"
    lef.write_text("LAYER met1\n TYPE ROUTING ;\n WIDTH 0.14 ;\n THICKNESS 0.35 ;\n DCCURRENTDENSITY AVERAGE 2.8 ;\nEND met1\n")
    table, _ = em.native_jmax_table(lef.read_text())
    limit = table["met1"]["jmax_areal_A_per_um2"] * (1-em._DEFAULT_MARGIN)
    subject = {"tool": "openroad-psm", "verdict": "MEASURED", "nets_analysed": ["VDD"], "native_rc": 0}
    doc = {"verdict": "MEASURED", "execution": {"native_rc": 0}, "authority": {"snapshot": str(lef)},
           "pdk": {"name": "neutral"}, "power_basis": {"complete": True}, "nets": {"VDD": {}}}
    (rpt / "em.json").write_text(json.dumps(subject))
    (rpt / "em_openroad_density.json").write_text(json.dumps(doc))
    psm = rpt / "em_segments_VDD.csv"
    psm.write_text("Node0 Layer,Node0 X location,Node0 Y location,Node1 Layer,Node1 X location,Node1 Y location,Current\nmet1,0,0,met1,1,0,0.00001\n")
    native = rpt / "em_openroad_density_VDD.csv"
    row = {"Layer": "met1", "Status": "OK", "Basis": "AREAL", "Node0 X": 0, "Node0 Y": 0,
           "Node1 X": 1, "Node1 Y": 0, "Current(A)": 1e-5, "Jlimit(A/um^2)": limit,
           "Ratio": .1, "J(A/um^2)": limit*.1, "Area(um^2)": .049, "Cuts": 0}
    write_rows(native, [row])
    return tmp_path, rpt, doc, row


def write_rows(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def update_doc(density, **fields):
    _, rpt, doc, _ = density
    doc.update(fields)
    (rpt / "em_openroad_density.json").write_text(json.dumps(doc))


def test_psm_density_pass_needs_no_input_hashes_or_log_stamps(density):
    project, _, _, _ = density
    result = em.validate_native_density(project, segment_geometry={})
    assert result["valid"] and result["verdict"] == "PASS"
    assert result["nets"]["VDD"]["checked"] == 1
    assert "authority_sha256" not in result


def test_native_overlimit_segment_keeps_fail(density):
    project, rpt, _, row = density
    row.update(Status="VIOLATED", Ratio=2)
    write_rows(rpt / "em_openroad_density_VDD.csv", [row])
    result = em.validate_native_density(project, segment_geometry={})
    assert result["valid"] and result["verdict"] == "FAIL"
    assert result["violations"] == 1


def test_native_failure_is_not_diluted_by_missing_power_coverage(density):
    project, _, _, _ = density
    update_doc(density, verdict="FAIL", power_basis={"complete": False})
    result = em.validate_native_density(project)
    assert result["valid"] and result["verdict"] == "FAIL"


@pytest.mark.parametrize("damage", ["rc", "missing_csv", "psm_row_missing", "missing_supply", "no_limit", "incomplete_power", "wrong_limit"])
def test_native_missing_or_invalid_measurements_do_not_pass(density, damage):
    project, rpt, _, row = density
    if damage == "rc":
        update_doc(density, execution={"native_rc": 127})
    elif damage == "missing_csv":
        (rpt / "em_openroad_density_VDD.csv").unlink()
    elif damage == "psm_row_missing":
        (rpt / "em_segments_VDD.csv").write_text("Current\n")
    elif damage == "missing_supply":
        subject = json.loads((rpt / "em.json").read_text())
        subject["nets_analysed"].append("VSS")
        (rpt / "em.json").write_text(json.dumps(subject))
    elif damage == "no_limit":
        row["Status"] = "NO_LIMIT"
        write_rows(rpt / "em_openroad_density_VDD.csv", [row])
    elif damage == "incomplete_power":
        update_doc(density, power_basis={"complete": False})
    elif damage == "wrong_limit":
        row["Jlimit(A/um^2)"] *= 2
        write_rows(rpt / "em_openroad_density_VDD.csv", [row])
    result = em.validate_native_density(project, segment_geometry={})
    assert result["verdict"] == "NOT_MEASURED"


def test_old_identity_metadata_cannot_invalidate_native_numbers(density):
    project, _, _, _ = density
    update_doc(density, schema="old", source_identity="changed", inputs={"layout": {"sha256": "wrong"}},
               outputs={"old": "wrong"}, step24_primary={"valid": False}, librelane_ir={"adopted": False})
    result = em.validate_native_density(project)
    assert result["valid"] and result["verdict"] == "PASS"


@pytest.mark.parametrize("drop,verdict", [(49999, "PASS"), (50000, "PASS"), (50001, "FAIL")])
def test_ir_native_number_uses_original_five_percent_limit(tmp_path, drop, verdict):
    rpt = tmp_path / "reports/phase3"
    rpt.mkdir(parents=True)
    (rpt / "ir_drop.json").write_text(json.dumps({"verdict": "PASS", "native_rc": 0, "worst_ir_uv": drop, "vdd_v": 1.0}))
    result = em.validate_primary_ir(tmp_path)
    assert result["valid"] and result["verdict"] == verdict
    assert result["budget_uv"] == 50000


@pytest.mark.parametrize("fields", [{"native_rc": 127}, {"unconnected_supply_pins": 1},
    {"nets_analysis_failed": ["VSS"]}, {"worst_ir_uv": None}, {"vdd_v": None}])
def test_ir_missing_tool_or_supply_measurement_remains_unmeasured(tmp_path, fields):
    rpt = tmp_path / "reports/phase3"
    rpt.mkdir(parents=True)
    native = {"verdict": "PASS", "native_rc": 0, "worst_ir_uv": 1, "vdd_v": 1.0}
    native.update(fields)
    (rpt / "ir_drop.json").write_text(json.dumps(native))
    result = em.validate_primary_ir(tmp_path)
    assert not result["valid"] and result["verdict"] == "NOT_MEASURED"


def test_malformed_old_ir_receipt_does_not_hide_current_native_result(tmp_path):
    rpt = tmp_path / "reports/phase3"
    rpt.mkdir(parents=True)
    (rpt / "ir_drop_librelane.json").write_text("not a receipt")
    (rpt / "ir_drop.json").write_text(json.dumps({"verdict": "FAIL", "worst_ir_uv": 100, "vdd_v": 1.0}))
    result = em.validate_primary_ir(tmp_path)
    assert result["valid"] and result["verdict"] == "FAIL"
