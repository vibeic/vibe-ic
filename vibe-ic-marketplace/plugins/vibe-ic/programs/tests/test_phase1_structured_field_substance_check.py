"""tests/test_phase1_structured_field_substance_check.py — v1.6.55

Closes the detection half of GitHub issue #4 (the partial-fix scope
landing in this commit). Tier-2 audit of structured-field substance:
catches L-docs that satisfy Tier-1 (token-presence-anywhere) but
ship every mandatory field at template default."""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_structured_field_substance_check import audit


def _w(p: Path, layer: str, payload: dict) -> None:
    """Write `payload` to `<project>/phase1/generated_docs/<layer>.json`."""
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / f"{layer}.json").write_text(json.dumps(payload, ensure_ascii=False))


def _ic_name_real(name: str) -> dict:
    return {"ic_name": name, "pin_table": [
        {"name": "VDD", "function": "supply"},
        {"name": "GND", "function": "ground"}],
        "electrical_specs": [{"VDD": 3.3, "unit": "V"}]}


# ---------------------------------------------------------------------------
# VACUOUS_PASS — Phase 2a not yet run.
# ---------------------------------------------------------------------------

def test_vacuous_pass_no_generated_docs(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings, _ = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


# ---------------------------------------------------------------------------
# PASS — every audited field has substance.
# ---------------------------------------------------------------------------

def test_pass_with_substantive_fields(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET", _ic_name_real("EXAMPLE_CHIP"))
    _w(p, "L2_FRS", {
        "protocol_overview": {
            "half_duplex": True,
            "wire_count": 1,
            "byte_order": "MSB-first",
        }})
    _w(p, "L3_CMD_PROTOCOL", {
        "opcodes": [
            {"hex": "0x70", "name": "GET_ID"},
            {"hex": "0x72", "name": "GET_STATE"},
        ]})
    _w(p, "L6_CONTROL_LOGIC", {
        "fsm_states": [
            {"name": "INIT"}, {"name": "AUTHENTICATING"},
            {"name": "AUTHENTICATED"}, {"name": "ERROR"},
            {"name": "TIMEOUT"}, {"name": "RECOVERY"},
            {"name": "POWERSAVE"},  # 7 distinct states, not the
                                     # canonical-5-placeholder shape
        ]})
    verdict, findings, summary = audit(p)
    assert verdict == "PASS", findings
    assert findings == []
    assert summary["fields_at_default"] == 0


# ---------------------------------------------------------------------------
# FAIL — every audited field at default (the v10648 + GitHub-issue
# scenario reproduced).
# ---------------------------------------------------------------------------

def test_fail_when_all_fields_at_template_default(tmp_path: Path) -> None:
    """The exact scaffolding pattern issue #4 documents."""
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET", {
        "ic_name": "UNKNOWN_IC",
        "pin_table": [{"name": "__TODO__",
                       "function": "__TODO__"}],
        "electrical_specs": [],
    })
    _w(p, "L2_FRS", {
        "protocol_overview": {
            "half_duplex": False,
            "wire_count": 2,
            "byte_order": "LSB-first",
            "wake_required_pre_command": True,
        }})
    _w(p, "L3_CMD_PROTOCOL", {
        "opcodes": [
            {"hex": "0x00", "name": "RESERVED",
             "description": "placeholder"}
        ]})
    _w(p, "L6_CONTROL_LOGIC", {
        "fsm_states": [
            {"name": "S0"}, {"name": "S1"}, {"name": "S2"},
            {"name": "S3"}, {"name": "S4"},
        ]})
    verdict, findings, summary = audit(p)
    assert verdict == "FAIL", (summary, findings)
    assert summary["fields_at_default"] >= 4
    # All four flagged: ic_name, pin_table, electrical_specs,
    # protocol_overview, opcodes, fsm_states.
    flagged_paths = {f.field_path for f in findings}
    assert "ic_name" in flagged_paths
    assert "protocol_overview" in flagged_paths
    assert "opcodes" in flagged_paths


# ---------------------------------------------------------------------------
# Escape valve: `no_<field>_in_input` flag suppresses the finding.
# ---------------------------------------------------------------------------

def test_no_input_flag_exempts_field(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET", _ic_name_real("AES"))
    _w(p, "L2_FRS", {
        "no_protocol_overview_in_input": True,
        "protocol_overview": {
            "half_duplex": False,
            "wire_count": 2,
            "byte_order": "LSB-first",
            "wake_required_pre_command": True,
        }})
    _w(p, "L3_CMD_PROTOCOL", {
        "no_opcodes_in_input": True,
        "opcodes": [{"hex": "0x00", "name": "RESERVED"}]})
    verdict, findings, summary = audit(p)
    # All defaults are escaped by no_*_in_input flags → no findings.
    assert verdict == "PASS", findings
    assert summary["fields_with_no_input_flag"] >= 2


def test_no_input_flag_at_root_also_works(tmp_path: Path) -> None:
    """The canonical L5 / L11 escape uses top-level no_analog /
    no_calibration; verify the audit finds it at root too."""
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET", {
        "no_ic_name_in_input": True,
        "ic_name": "UNKNOWN_IC",
        "pin_table": [{"name": "VDD"}],
        "electrical_specs": [{"VDD": 3.3}]})
    verdict, findings, summary = audit(p)
    # ic_name escaped, pin_table + electrical_specs are real → PASS.
    assert verdict == "PASS", findings
    assert summary["fields_with_no_input_flag"] >= 1


# ---------------------------------------------------------------------------
# WARN — between 0 and 30% of fields at default.
# ---------------------------------------------------------------------------

def test_warn_when_some_fields_at_default(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    # 1 of ~6 audited fields at default → 16.7% < 30% → WARN.
    _w(p, "L1_DATASHEET", _ic_name_real("AES"))
    _w(p, "L2_FRS", {
        "protocol_overview": {"half_duplex": True, "wire_count": 1},
    })
    _w(p, "L3_CMD_PROTOCOL", {
        "opcodes": [
            {"hex": "0x10", "name": "READ"},
            {"hex": "0x11", "name": "WRITE"},
        ]})
    # L6 fsm_states deliberately at scaffolding-5 default.
    _w(p, "L6_CONTROL_LOGIC", {
        "fsm_states": [
            {"name": "S0"}, {"name": "S1"}, {"name": "S2"},
            {"name": "S3"}, {"name": "S4"},
        ]})
    verdict, findings, summary = audit(p)
    assert verdict == "WARN", (summary, findings)
    assert summary["fields_at_default"] >= 1


# ---------------------------------------------------------------------------
# Field absence (not even present in the L doc) treated as default.
# ---------------------------------------------------------------------------

def test_missing_field_treated_as_at_default(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    # L1 has only ic_name; pin_table + electrical_specs absent entirely.
    _w(p, "L1_DATASHEET", {"ic_name": "AES"})
    verdict, findings, _ = audit(p)
    assert verdict in ("WARN", "FAIL")
    rules = {f.rule for f in findings}
    assert "field_absent_no_flag" in rules


# ---------------------------------------------------------------------------
# Template-default rule sanity.
# ---------------------------------------------------------------------------

def test_default_protocol_rule_is_chip_agnostic(tmp_path: Path) -> None:
    """The canonical default protocol_overview is the v10627 +
    GitHub-issue scaffolding shape; any chip whose L2 differs in
    EVEN ONE field should NOT be flagged."""
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET", _ic_name_real("AES"))
    # Same shape but wire_count=8 (real value), should pass.
    _w(p, "L2_FRS", {
        "protocol_overview": {
            "half_duplex": False,
            "wire_count": 8,           # real, not 1 or 2
            "byte_order": "LSB-first",
            "wake_required_pre_command": True,
        }})
    _w(p, "L3_CMD_PROTOCOL", {
        "opcodes": [{"hex": "0x10", "name": "OP1"}]})
    verdict, findings, _ = audit(p)
    flagged_paths = {f.field_path for f in findings}
    assert "protocol_overview" not in flagged_paths


# ---------------------------------------------------------------------------
# Reachable from the CLI — generates canonical report.
# ---------------------------------------------------------------------------

def test_canonical_report_emitted_on_run(tmp_path: Path) -> None:
    import subprocess
    import sys as _sys
    p = tmp_path / "proj"
    _w(p, "L1_DATASHEET", _ic_name_real("AES"))
    _w(p, "L3_CMD_PROTOCOL",
       {"opcodes": [{"hex": "0x10", "name": "OP1"}]})
    PROG = (Path(__file__).resolve().parent.parent
            / "phase1_structured_field_substance_check.py")
    r = subprocess.run([_sys.executable, str(PROG), str(p)],
                       capture_output=True, text=True)
    assert r.returncode in (0, 1)
    out = (p / "reports" / "phase1"
           / "structured_field_substance.json")
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["gate"] == "phase1_structured_field_substance_check"
