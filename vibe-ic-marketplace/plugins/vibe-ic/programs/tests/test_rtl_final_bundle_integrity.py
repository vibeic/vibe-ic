#!/usr/bin/env python3
"""The scorer-bound RTL bundle remains exactly the reviewed module set."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import rtl_final_bundle_integrity as gate  # noqa: E402


def _reviewed(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "reviewed.sv"
    path.write_text(text)
    return path


def test_exact_repartitioned_reviewed_modules_pass(tmp_path):
    reviewed = _reviewed(
        tmp_path,
        "module leaf(input x, output y); assign y=x; endmodule\n"
        "module top(input x, output y); leaf u(.x(x), .y(y)); endmodule\n")
    result = gate.check_final_bundle(
        [reviewed], {
            "rtl/top.sv":
                "module top(input x, output y); leaf u(.x(x), .y(y)); endmodule",
            "rtl/leaf.sv":
                "module leaf(input x, output y); assign y=x; endmodule",
        }, declared_top="top")
    expected = "PASS" if gate.shutil.which("iverilog") else "NOT_MEASURED"
    assert result["status"] == expected
    assert result["reviewed_modules"] == ["leaf", "top"]
    assert result["final_modules"] == ["leaf", "top"]


def test_changed_module_bytes_are_blocked(tmp_path):
    reviewed = _reviewed(
        tmp_path, "module top(input x, output y); assign y=x; endmodule\n")
    result = gate.check_final_bundle(
        [reviewed], {
            "rtl/top.sv":
                "module top(input x, output y); assign y=~x; endmodule\n"})
    assert result["status"] == "BLOCKED"
    assert any("byte" in reason and "top" in reason
               for reason in result["reasons"])


def test_duplicate_final_module_ownership_is_blocked(tmp_path):
    reviewed = _reviewed(tmp_path, "module top; endmodule\n")
    result = gate.check_final_bundle(
        [reviewed], {
            "rtl/a.sv": "module top; endmodule\n",
            "rtl/b.sv": "module top; endmodule\n",
        })
    assert result["status"] == "BLOCKED"
    assert any("duplicate module ownership" in reason
               for reason in result["reasons"])


def test_only_prompt_derived_declared_top_is_enforced(tmp_path):
    reviewed = _reviewed(tmp_path, "module leaf; endmodule\n")
    result = gate.check_final_bundle(
        [reviewed], {"rtl/arbitrary_filename.sv": "module leaf; endmodule\n"},
        declared_top="public_prompt_top")
    assert result["status"] == "BLOCKED"
    assert any("public_prompt_top" in reason for reason in result["reasons"])


def test_unresolved_dependency_fails_exact_final_compile(tmp_path):
    if gate.shutil.which("iverilog") is None:
        pytest.skip("NOT_MEASURED: iverilog is unavailable")
    text = "module top; missing_dependency u(); endmodule\n"
    reviewed = _reviewed(tmp_path, text)
    result = gate.check_final_bundle(
        [reviewed], {"rtl/top.sv": text})
    assert result["status"] == "BLOCKED"
    assert result["compile"]["status"] == "BLOCKED"
    assert "missing_dependency" in "; ".join(result["reasons"])


def test_missing_compiler_is_not_measured(tmp_path, monkeypatch):
    text = "module top; endmodule\n"
    reviewed = _reviewed(tmp_path, text)
    monkeypatch.setattr(gate.shutil, "which", lambda _name: None)
    result = gate.check_final_bundle(
        [reviewed], {"rtl/top.sv": text})
    assert result["status"] == "NOT_MEASURED"
    assert "iverilog" in result["compile"]["reason"]
