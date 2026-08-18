#!/usr/bin/env python3
"""Tests for assertion_covers_l3_constraints_check (Wave 39 / D3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "assertion_covers_l3_constraints_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_proj(tmp_path: Path, l3: dict, rtl_text: str = "",
               waiver: str | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps(l3))
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(rtl_text or "module x; endmodule")
    if waiver is not None:
        (proj / "waivers.json").write_text(json.dumps(
            {"sva_constraint_coverage_partial_intentional": waiver}))
    return proj


def test_skip_when_no_l3(tmp_path):
    proj = tmp_path / "p"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_constraints(tmp_path):
    proj = _make_proj(tmp_path,
                      {"opcodes": [{"hex": "0x74"}]})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_no_assertions(tmp_path):
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    proj = _make_proj(tmp_path, l3,
                      rtl_text="module x; endmodule")
    r = _run(proj)
    assert r.returncode == 1


def test_pass_when_assertion_matches(tmp_path):
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    rtl = (
        "module main_fsm();\n"
        "  // SVA: when opcode 8'hE2, addr must be <= 8'h7F\n"
        "  assert property (@(posedge clk)\n"
        "    (cmd_buf[0] == 8'hE2) |-> (cmd_buf[1] <= 8'h7F));\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0


def test_pre_wake_assertion_match(tmp_path):
    l3 = {"opcodes": [
        {"hex": "0x70", "pre_wake_allowed": False},
    ]}
    rtl = (
        "module main_fsm();\n"
        "  assert property (@(posedge clk)\n"
        "    (cmd_buf[0] == 8'h70 && !awake_latch) |-> "
        "    (state == S_IDLE));\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0


def test_waiver_pass(tmp_path):
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    waiver_text = ("Assertions deferred to formal-pass-2 milestone; "
                   "documented in ENG-DECISION-W39-V11 — over forty chars")
    proj = _make_proj(tmp_path, l3, waiver=waiver_text)
    r = _run(proj)
    assert r.returncode == 0
    assert "waived" in r.stdout


# ---------------------------------------------------------------
# Wave 43 (v0.119.75) — D3 synonym extension tests.
# ---------------------------------------------------------------
def test_strict_comparator_neighbour_bound_match(tmp_path):
    """`<= 0x7F` is functionally equivalent to `< 0x80`. Wave 43
    accepts the neighbour literal as a bound match."""
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    rtl = (
        "module main_fsm();\n"
        "  // SVA written as strict less-than against bound+1\n"
        "  assert property (@(posedge clk)\n"
        "    (cmd_buf[0] == 8'hE2) |-> (cmd_buf[1] < 8'h80));\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_immediate_assert_form_recognised(tmp_path):
    """`assert(...)` immediate form (not `assert property`) must be
    recognised as an assertion site by Wave 43."""
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    rtl = (
        "module main_fsm();\n"
        "  always @(posedge clk) begin\n"
        "    assert (!(cmd_buf[0] == 8'hE2 && cmd_buf[1] > 8'h7F));\n"
        "  end\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_assume_property_form_recognised(tmp_path):
    """`assume property` form must also count as an assertion site."""
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    rtl = (
        "module main_fsm();\n"
        "  assume property (@(posedge clk)\n"
        "    (cmd_buf[0] == 8'hE2) |-> (cmd_buf[1] <= 8'h7F));\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_macro_assert_form_recognised(tmp_path):
    """`ASSUME_*` / `COVER_*` macros should also be picked up by the
    broadened regex (Wave 43)."""
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    rtl = (
        "module main_fsm();\n"
        "  `ASSUME_RANGE(cmd_buf[0] == 8'hE2, cmd_buf[1], 8'h7F);\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_operator_synonym_exceed_matches_max(tmp_path):
    """When the SVA carries an `exceed` operator-synonym next to the
    opcode, even without a literal bound the constraint matches."""
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""}
        ]
    }]}
    rtl = (
        "module main_fsm();\n"
        "  // operator synonym 'overflow' (Wave 43 widening)\n"
        "  assert property (@(posedge clk)\n"
        "    (cmd_buf[0] == 8'hE2) |-> !addr_overflow);\n"
        "endmodule\n"
    )
    proj = _make_proj(tmp_path, l3, rtl_text=rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
