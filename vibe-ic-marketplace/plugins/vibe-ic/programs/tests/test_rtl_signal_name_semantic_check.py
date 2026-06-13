#!/usr/bin/env python3
"""Tests for rtl_signal_name_semantic_check.py — active-low NAME vs
active-high VALUE polarity-trap linter.

Pins the canonical silicon-bite defect (which bit BENCH-A v5):

    assign id_bus_oe_low = id_bus_drive_low;

The NAME `*_oe_low` says active-LOW (=0 means drive); the VALUE
`*_drive_low` is active-HIGH by convention (=1 means drive low). A
downstream wrapper reading the name uses the WRONG polarity. The gate
must WARN on this and stay silent on clean polarity-consistent RTL.
"""
from __future__ import annotations

import json
from pathlib import Path

# programs/ is on sys.path via programs/tests/conftest.py. A plain import
# (rather than spec_from_file_location) is required here because the
# module defines an @dataclass, which resolves cls.__module__ through
# sys.modules — a file-spec load that skips sys.modules registration
# breaks dataclass construction.
import rtl_signal_name_semantic_check as mod  # noqa: E402


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


# ----------------------------------------------------------------------
# FAIL — the exact polarity trap the linter guards.
# ----------------------------------------------------------------------
def test_warn_active_low_name_active_high_value(tmp_path):
    f = _write(tmp_path, "bad.v",
               "module x;\n"
               "assign id_bus_oe_low = id_bus_drive_low;\n"
               "endmodule\n")
    findings = mod.audit(f)
    assert len(findings) == 1
    fnd = findings[0]
    assert fnd.severity == "WARN"
    assert fnd.rule == "active_low_name_vs_active_high_value"
    # line is computed on comment-stripped text; pin only that it is a
    # real positive line number, not the exact value.
    assert isinstance(fnd.line, int) and fnd.line >= 1
    assert fnd.lhs == "id_bus_oe_low"
    assert "id_bus_drive_low" in fnd.message  # the offending RHS token


def test_warn_literal_one_to_active_low_name(tmp_path):
    # 1'b1 driven onto an active-LOW name is the same polarity trap.
    f = _write(tmp_path, "lit.v",
               "module y;\nassign chip_cs_n = 1'b1;\nendmodule\n")
    findings = mod.audit(f)
    assert len(findings) == 1
    assert findings[0].rhs.strip() == "1'b1"


def test_cli_fail_on_warn_returns_1(tmp_path):
    f = _write(tmp_path, "bad.v",
               "module x;\nassign id_bus_oe_low = id_bus_drive_low;\nendmodule\n")
    # Without --fail-on-warn the WARN is non-fatal (rc 0).
    assert mod.main([str(f)]) == 0
    # With --fail-on-warn it becomes a CI failure (rc 1).
    assert mod.main([str(f), "--fail-on-warn"]) == 1


def test_cli_json_report(tmp_path):
    f = _write(tmp_path, "bad.v",
               "module x;\nassign id_bus_oe_low = id_bus_drive_low;\nendmodule\n")
    out = tmp_path / "rep.json"
    rc = mod.main([str(f), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "WARN"
    assert rep["warns"] == 1
    assert rep["findings"][0]["rule"] == "active_low_name_vs_active_high_value"


# ----------------------------------------------------------------------
# PASS — polarity-consistent RTL produces no finding.
# ----------------------------------------------------------------------
def test_pass_clean_polarity(tmp_path):
    f = _write(tmp_path, "ok.v",
               "module y;\n"
               "assign id_bus_oe_low = ~id_bus_drive_n;\n"  # inverted, OK
               "assign foo = bar;\n"
               "endmodule\n")
    assert mod.audit(f) == []
    assert mod.main([str(f), "--fail-on-warn"]) == 0


def test_pass_active_high_name_active_high_value(tmp_path):
    # Name and value agree (both active-high) -> no trap.
    f = _write(tmp_path, "ok2.v",
               "module z;\nassign drive_en = bus_drive_high;\nendmodule\n")
    assert mod.audit(f) == []


# ----------------------------------------------------------------------
# Edge / IO behavior.
# ----------------------------------------------------------------------
def test_comments_are_ignored(tmp_path):
    # The trap text inside a comment must NOT be flagged.
    f = _write(tmp_path, "c.v",
               "module x;\n"
               "// assign id_bus_oe_low = id_bus_drive_low;\n"
               "assign foo = bar;\n"
               "endmodule\n")
    assert mod.audit(f) == []


def test_directory_recursion(tmp_path):
    sub = tmp_path / "rtl"
    sub.mkdir()
    _write(sub, "a.v",
           "module x;\nassign id_bus_oe_low = id_bus_drive_low;\nendmodule\n")
    _write(sub, "b.sv",
           "module w;\nassign clean = other;\nendmodule\n")
    findings = mod.audit(tmp_path)
    assert len(findings) == 1
    assert findings[0].file.endswith("a.v")


def test_cli_missing_target_returns_2(tmp_path):
    assert mod.main([str(tmp_path / "nope.v")]) == 2
