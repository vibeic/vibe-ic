#!/usr/bin/env python3
"""Tests for l4_regmap_enumerated_values_typed_check.py (Wave 38 / B3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent / "l4_regmap_enumerated_values_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l4):
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L4_REGMAP.json").write_text(json.dumps(l4))
    return proj


def test_skip_when_no_l4(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_eligible_field(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "EN", "bits": "[0:0]"},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_multibit_enum_field_lacks_values(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "OCP_DLY", "bits": "[1:0]"},
            {"name": "RES_MODE", "bits": "[3:2]"},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "OCP_DLY" in r.stdout or "RES_MODE" in r.stdout


def test_pass_when_enum_present(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "OCP_DLY", "bits": "[1:0]",
             "enumerated_values": [
                 {"code": "00", "meaning": "idle"},
                 {"code": "01", "meaning": "wait"},
                 {"code": "10", "meaning": "stable"},
                 {"code": "11", "meaning": "release"},
             ]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_when_alias_key_used(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "MODE", "width": 2,
             "encoding": [
                 {"code": 0, "meaning": "off"},
                 {"code": 1, "meaning": "low"},
                 {"code": 2, "meaning": "high"},
             ]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0


# Wave 43 (v0.119.75) — ic_class_profile SKIP cases.
def test_skip_on_pure_analog(tmp_path):
    """Pure-analog parts have no command regmap."""
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "PMIC-X", "interface": "pure analog"})
    )
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(
        json.dumps({"ic_name": "PMIC-X", "interface": "pure analog"})
    )
    (proj / "phase1" / "generated_docs" / "L5_ADI_SPEC.json").write_text(
        json.dumps({"analog_blocks": [{"name": "BANDGAP_REF"}]})
    )
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=pure_analog" in r.stdout


def test_skip_on_bare_fpga(tmp_path):
    """Bare-FPGA scaffolds have no fab-side regmap."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "facts.yaml").write_text("name: my_fpga_eval\n")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=bare_fpga" in r.stdout


# ===========================================================================
# Layer-gate strengthening (batch: layergate-2) — S1/S2/S3.
#
# Each strengthening gets an explicit negative control (gutted layer =>
# FAIL) AND its positive control (well-formed => PASS). All fixtures are
# SYNTHESIZED neutral data: invented register/field names, invented
# codes, no vendor tokens.
# ===========================================================================

# --- S1: the gate was VACUOUS on the production emitter's field shape ---

def test_s1_negative_control_field_name_alias_is_seen(tmp_path):
    """The production Phase-1 L4 emitter writes a field's name as
    ``field_name``. Before S1 the gate resolved every such name to ""
    and reported SKIP — it could not fail on real output at all.
    A gate that cannot fire proves nothing, so this must now FAIL."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_ctrl", "fields": [
            {"field_name": "OPT_SEL", "bits": "3:2", "access": "RW"},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OPT_SEL" in r.stdout


def test_s1_positive_control_field_name_alias_with_enum_passes(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_ctrl", "fields": [
            {"field_name": "OPT_SEL", "bits": "3:2", "access": "RW",
             "enumerated_values": [
                 {"code": "2'b00", "meaning": "bypass"},
                 {"code": "2'b01", "meaning": "engaged"},
             ]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# --- S2: token-presence _has_enum accepted a bare list ---

def test_s2_negative_control_bare_token_list_is_not_a_binding(tmp_path):
    """``enumerated_values: ["alpha", "beta"]`` used to PASS: two members,
    no code, no meaning. A decoder cannot be built from a token list, so
    this must FAIL."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_ctrl", "fields": [
            {"name": "OPT_MODE", "bits": "1:0",
             "enumerated_values": ["alpha", "beta"]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "code->meaning binding" in r.stdout


def test_s2_negative_control_code_without_meaning_fails(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_ctrl", "fields": [
            {"name": "OPT_MODE", "bits": "1:0",
             "enumerated_values": [{"code": "00"}, {"code": "01"}]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr


def test_s2_positive_control_mapping_form_is_a_binding(tmp_path):
    """The mapping shape {"00": "idle", "01": "busy"} binds code to
    meaning just as well as a list of dicts — it must PASS."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_ctrl", "fields": [
            {"name": "OPT_MODE", "bits": "1:0",
             "enumerated_values": {"00": "idle", "01": "busy"}},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


# --- S3: hardcoded ">= 2" forced fabrication ---

def test_s3_negative_control_declared_code_must_be_captured(tmp_path):
    """The field's own description declares one code. L4 captured none.
    That is a real capture gap and must FAIL — with the code named, so
    the fix is mechanical rather than inventive."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_vec", "fields": [
            {"field_name": "OPT_MODE", "bits": "1:0",
             "description": "Always set to 2'b01 to select vectored mode."},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "2'b01" in r.stdout


def test_s3_positive_control_single_declared_code_is_enough(tmp_path):
    """THE anti-fabrication control. The input declares exactly ONE legal
    code. Under the old flat ">= 2 entries" rule, passing would have
    required INVENTING a second code. Capturing the one code the input
    states must now be sufficient."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_vec", "fields": [
            {"field_name": "OPT_MODE", "bits": "1:0",
             "description": "Always set to 2'b01 to select vectored mode.",
             "enumerated_values": [
                 {"code": "2'b01", "meaning": "vectored mode"},
             ]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_s3_all_declared_codes_must_be_captured(tmp_path):
    """Two codes declared, one captured => still incomplete."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_vec", "fields": [
            {"field_name": "OPT_MODE", "bits": "1:0",
             "description": "0x0 = direct, 0x1 = vectored.",
             "enumerated_values": [{"code": "0x0", "meaning": "direct"}]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr


def test_s3_codes_in_description_trigger_even_without_name_keyword(tmp_path):
    """Eligibility is now also DERIVED from the design's own text: a
    multi-bit field whose description declares codes is enum-eligible
    even if its name matches no keyword."""
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_x", "fields": [
            {"field_name": "ZZQ", "bits": "1:0",
             "description": "0b00 = low, 0b11 = high."},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ZZQ" in r.stdout


# --- the waiver the docstring promised but no code ever read ---

def test_waiver_now_actually_suppresses(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "reg_ctrl", "fields": [
            {"name": "OPT_MODE", "bits": "1:0"},
        ]}
    ]})
    (proj / "waivers.json").write_text(json.dumps({
        "l4_regmap_enum_intentional_simplification":
            "This synthesized fixture intentionally omits the enum so the "
            "documented waiver path is exercised end to end in test.",
    }))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "waived" in r.stdout


def test_both_directions_on_one_edit(tmp_path):
    """Same field, same declared code. Only the capture differs."""
    field = {"field_name": "OPT_MODE", "bits": "1:0",
             "description": "Always set to 2'b01 to select vectored mode."}
    bad = _make(tmp_path / "b", {"registers": [
        {"name": "reg_vec", "fields": [dict(field)]}]})
    good_field = dict(field)
    good_field["enumerated_values"] = [
        {"code": "2'b01", "meaning": "vectored mode"}]
    good = _make(tmp_path / "g", {"registers": [
        {"name": "reg_vec", "fields": [good_field]}]})

    r_bad, r_good = _run(bad), _run(good)
    assert r_bad.returncode == 1, r_bad.stdout
    assert r_good.returncode == 0, r_good.stdout
    assert r_bad.returncode != r_good.returncode


def test_json_report_carries_the_leafs_actual_nonenum_census(tmp_path):
    proj = _make(tmp_path, {"registers": [{"name": "DATA", "fields": [
        {"field_name": "payload", "bits": "[7:0]"},
        {"field_name": "enabled", "bits": "0"},
    ]}]})
    normal = _run(proj)
    report = tmp_path / "reports" / "enum.json"
    result = subprocess.run(
        [sys.executable, str(PROG), str(proj), "--json", str(report)],
        capture_output=True, text=True,
    )
    assert result.returncode == normal.returncode == 2
    assert result.stdout == normal.stdout
    assert result.stdout.count("enumerated 2") == 1
    summary = json.loads(report.read_text())["summary"]
    assert summary["reason_class"] == "NOT_APPLICABLE_BY_STRUCTURE"
    assert summary["structural_absence"] == {
        "population": "register field(s) L4 carries", "scanned": 2, "found": 0,
        "detail": "none of them is multi-bit and enum-eligible",
    }


@pytest.mark.parametrize("case,rc", [
    ("missing", 2), ("empty", 2), ("malformed", 1),
    ("bad_mode", 1), ("typed_mode", 0),
])
def test_json_report_does_not_claim_absence_without_a_census(tmp_path, case, rc):
    field = {"field_name": "MODE", "bits": "[1:0]"}
    if case == "typed_mode":
        field["enumerated_values"] = [
            {"code": "2'b00", "meaning": "idle"},
            {"code": "2'b01", "meaning": "active"},
        ]
    proj = _make(tmp_path, {"registers": []} if case == "empty" else {
        "registers": [{"name": "CONTROL", "fields": [field]}]})
    l4 = proj / "phase1/generated_docs/L4_REGMAP.json"
    if case == "missing":
        l4.unlink()
    elif case == "malformed":
        l4.write_text("{not-json")
    report = tmp_path / "enum.json"
    result = subprocess.run(
        [sys.executable, str(PROG), str(proj), "--json", str(report)],
        capture_output=True, text=True,
    )
    assert result.returncode == rc, result.stdout + result.stderr
    payload = json.loads(report.read_text())
    assert payload["passed"] is (rc == 0)
    assert "structural_absence" not in payload["summary"]
    assert "NOT_APPLICABLE_BY_STRUCTURE" not in result.stdout


def test_real_p0_dispatch_transports_the_nonempty_leaf_census(tmp_path, monkeypatch):

    proj = _make(tmp_path, {"registers": [{"name": "DATA", "fields": [
        {"field_name": "payload", "bits": "[7:0]"},
        {"field_name": "enabled", "bits": "0"},
    ]}]})
    rtl = proj / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "neutral.v").write_text(
        "module neutral(input clk,d,output reg q); "
        "always @(posedge clk) q<=d; endmodule\n")
    # Only narrow the roster: use the real argv, subprocess, report and guard.
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    records = []
    assert len(records) == 1, records
    record = records[0]
    assert record["verdict"] == "SKIP", record
    assert record["reason_class"] == "NOT_APPLICABLE_BY_STRUCTURE", record
    assert record["evidence"]["exit_code"] == 2
    assert record["evidence"]["structural_absence"] == {
        "population": "register field(s) L4 carries", "scanned": 2, "found": 0,
        "detail": "none of them is multi-bit and enum-eligible",
    }
