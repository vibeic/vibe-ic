"""Unit tests for analog_hardmacro_pinname_consistency_check.py.

Pins the deterministic 3-way (spec.json interface <-> LEF PINs <->
Verilog ports) pin-name set-equality gate extracted from the
analog-hardmacro-gen skill Step-5 validation. Covers PASS, FAIL
(mismatch / foreign-pin / portless / missing-file), and the honest
SKIP edges (no analog at all, no-interface block, garbage spec).
"""
import importlib
import json

import pytest

mod = importlib.import_module("analog_hardmacro_pinname_consistency_check")


# --------------------------------------------------------------------------
# Pure parser unit tests
# --------------------------------------------------------------------------

class TestParsers:
    def test_lef_pins(self):
        lef = """MACRO ldo
  PIN vdd
  END vdd
  PIN vout
  END vout
END ldo"""
        assert mod.parse_lef_pins(lef) == {"vdd", "vout"}

    def test_lef_no_pins(self):
        lef = "MACRO ldo\n  SIZE 100 BY 100 ;\nEND ldo"
        assert mod.parse_lef_pins(lef) == set()

    def test_verilog_ansi_ports(self):
        v = "module ldo (input vdd, input en, input [2:0] trim, output vout);\nendmodule"
        assert mod.parse_verilog_ports(v) == {"vdd", "en", "trim", "vout"}

    def test_verilog_no_module(self):
        assert mod.parse_verilog_ports("// just a comment") == set()

    def test_spec_pins(self):
        data = {"interface": {"pins": [{"name": "vdd"}, {"name": "Vout"}]}}
        assert mod.parse_spec_pins(data) == {"vdd", "vout"}

    def test_spec_no_interface(self):
        assert mod.parse_spec_pins({"specs": []}) == set()


# --------------------------------------------------------------------------
# End-to-end fixtures
# --------------------------------------------------------------------------

def _mk_block(root, block, spec, lef=None, v=None):
    a = root / "phase3" / "analog" / block
    a.mkdir(parents=True, exist_ok=True)
    (a / "spec.json").write_text(json.dumps(spec))
    if lef is not None or v is not None:
        h = root / "phase3" / "analog" / "hardmacro" / block
        h.mkdir(parents=True, exist_ok=True)
        if lef is not None:
            (h / f"{block}.lef").write_text(lef)
        if v is not None:
            (h / f"{block}.v").write_text(v)


SPEC_LDO = {
    "block": "ldo",
    "interface": {"pins": [
        {"name": "vdd", "direction": "input"},
        {"name": "en", "direction": "input"},
        {"name": "vout", "direction": "output"},
    ]},
}


def test_pass_consistent(tmp_path):
    _mk_block(
        tmp_path, "ldo", SPEC_LDO,
        lef="MACRO ldo\n PIN vdd\n END vdd\n PIN en\n END en\n PIN vout\n END vout\nEND ldo",
        v="module ldo (input vdd, input en, output vout);\nendmodule",
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert res.summary["checked"] == 1
    assert res.summary["failed_blocks"] == []


def test_fail_verilog_mismatch(tmp_path):
    # Verilog renamed vout -> out_v: LVS-integration hazard.
    _mk_block(
        tmp_path, "ldo", SPEC_LDO,
        lef="MACRO ldo\n PIN vdd\n END vdd\n PIN en\n END en\n PIN vout\n END vout\nEND ldo",
        v="module ldo (input vdd, input en, output out_v);\nendmodule",
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    rules = {f.rule for f in res.findings}
    assert "VERILOG_SPEC_MISMATCH" in rules


def test_fail_lef_foreign_pin(tmp_path):
    _mk_block(
        tmp_path, "ldo", SPEC_LDO,
        lef="MACRO ldo\n PIN vdd\n END vdd\n PIN en\n END en\n PIN vout\n END vout\n PIN scan\n END scan\nEND ldo",
        v="module ldo (input vdd, input en, output vout);\nendmodule",
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LEF_FOREIGN_PIN" in {f.rule for f in res.findings}


def test_fail_lef_no_pins_but_spec_has_interface(tmp_path):
    # The real A7 stub LEF: MACRO with no PIN section -> FAIL (earned).
    _mk_block(
        tmp_path, "ldo", SPEC_LDO,
        lef="MACRO ldo\n SIZE 100 BY 100 ;\n CLASS BLOCK ;\nEND ldo",
        v="module ldo (input vdd, input en, output vout);\nendmodule",
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LEF_NO_PINS" in {f.rule for f in res.findings}


def test_fail_missing_verilog(tmp_path):
    _mk_block(
        tmp_path, "ldo", SPEC_LDO,
        lef="MACRO ldo\n PIN vdd\n END vdd\nEND ldo",
        v=None,
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "VERILOG_MISSING" in {f.rule for f in res.findings}


def test_skip_no_analog(tmp_path):
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert res.summary.get("skipped") is True


def test_skip_block_no_interface(tmp_path):
    # spec with no interface, no LEF/V -> nothing to compare (honest skip,
    # NOT a vacuous PASS-with-content).
    _mk_block(tmp_path, "ldo", {"block": "ldo", "specs": []})
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert "ldo" in res.summary["skipped_blocks"]
    assert res.summary["checked"] == 0


def test_fail_garbage_spec(tmp_path):
    a = tmp_path / "phase3" / "analog" / "ldo"
    a.mkdir(parents=True)
    (a / "spec.json").write_text("{ this is not json")
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "SPEC_UNPARSEABLE" in {f.rule for f in res.findings}


def test_fail_portless_lef_with_ported_verilog_no_spec(tmp_path):
    # Real A7 stub: spec has no interface, LEF is portless, but the
    # behavioral Verilog declares 3 ports -> PnR has nothing to route to.
    _mk_block(
        tmp_path, "ldo", {"block": "ldo", "specs": []},
        lef="MACRO ldo\n SIZE 100 BY 100 ;\n CLASS BLOCK ;\nEND ldo",
        v="module ldo (input vdd, input vss, output vout);\nassign vout=1'b0;\nendmodule",
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LEF_NO_PINS" in {f.rule for f in res.findings}


def test_lef_verilog_agree_without_spec(tmp_path):
    # No spec interface but LEF & Verilog both expose pins; they must agree.
    _mk_block(
        tmp_path, "buf", {"block": "buf"},
        lef="MACRO buf\n PIN a\n END a\n PIN y\n END y\nEND buf",
        v="module buf (input a, output z);\nendmodule",
    )
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LEF_VERILOG_MISMATCH" in {f.rule for f in res.findings}


def test_main_cli_json(tmp_path):
    _mk_block(
        tmp_path, "ldo", SPEC_LDO,
        lef="MACRO ldo\n PIN vdd\n END vdd\n PIN en\n END en\n PIN vout\n END vout\nEND ldo",
        v="module ldo (input vdd, input en, output vout);\nendmodule",
    )
    out = tmp_path / "rep.json"
    rc = mod.main([str(tmp_path), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["passed"] is True


def test_main_cli_not_a_dir(tmp_path):
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2
