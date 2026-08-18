#!/usr/bin/env python3
"""ORGANIC #726 [P1, chip-AGNOSTIC] — iface_conformance_v2 must SCOPE prompt-named
identifiers to their OWNING module so it does not false-positive.

A v1.0.77 convergence forward-verify surfaced THREE false-positive classes, all
from one root cause: the gate treated every backtick / heading / given-code token
as a TOP-module interface signal without scoping to the owning module:

  (1) MODULE-NAME-CASE FP — a code-completion prompt whose RTL skeleton declares
      the module name verbatim (e.g. `FindFasterClock`) made the gate derive the
      lowercase canonical id (`findfasterclock`) and flag a case mismatch —
      pushing a WRONG rename that breaks the harness (it instantiates the exact
      name). FIX: suppress MODULE-NAME-CASE when the prompt's RTL block literally
      declares the module name verbatim.
  (2) MISSING-PORT FP — prompt given-code that defines a SUB-module (e.g.
      `dual_port_memory` with din/dout/read_addr/we/write_addr) had those ports
      matched only against the TOP, so they were flagged missing though they are
      correctly declared on the sub-module in the same completion. FIX: a name is
      SATISFIED if it is a declared port of ANY module in the completion (top OR
      sub-module) OR of a harness-supplied context module.
  (3) PORT-DIRECTION FP — a markdown heading like `### 1. Module: Word_Change_Pulse`
      was parsed as a signal then direction-mismatched. FIX: exclude tokens equal
      to a declared MODULE name from the signal/direction comparison.
  (d) context — names provided by `input.context` rtl/*.sv are harness-supplied
      context, not author-missing (the #715 family).

§4.05 NO-LEAK: a GENUINE interface gap on the REAL top must STILL be flagged — a
real missing top-port, a real direction mismatch, and a genuine module-name-case
miss where the prompt did NOT declare the name verbatim all still fire.

chip-AGNOSTIC: pure prompt-prose + RTL structure; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
PROG = PROGRAMS / "iface_conformance_v2.py"
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as M  # noqa: E402


def _run_cli(tmp_path, rtl, prompt, rid=None, strict=False, context=None):
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    rp.write_text(rtl)
    pp.write_text(prompt)
    cmd = [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp)]
    if rid is not None:
        cmd += ["--id", rid]
    for i, ctx in enumerate(context or []):
        cp = tmp_path / f"ctx{i}.sv"
        cp.write_text(ctx)
        cmd += ["--context", str(cp)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


# ── 驗收 (the exact acceptance shape) ───────────────────────────────────────
def test_acceptance_module_name_heading_no_port_direction_finding(tmp_path):
    """驗收 END-STATE: `### 1. Module: Word_Change_Pulse` is a module-name
    heading, not a port — no PORT-DIRECTION (nor MISSING-PORT) finding fires."""
    rtl = "module Word_Change_Pulse(input clk, output reg p); endmodule\n"
    prompt = "### 1. Module: Word_Change_Pulse\nDesign a pulse module.\n"
    for strict in (False, True):
        r = _run_cli(tmp_path, rtl, prompt,
                     rid="cvdp_copilot_word_change_detector_0001",
                     strict=strict)
        assert r.returncode == 0, (strict, r.stdout, r.stderr)
        assert "interface-conformance ok" in r.stdout
        assert "PORT-DIRECTION" not in r.stdout
        assert "Word_Change_Pulse" not in r.stdout


# ── FP CLASS 1: MODULE-NAME-CASE (verbatim skeleton) no longer fires ────────
def test_fp1_module_name_case_suppressed_when_prompt_declares_verbatim(tmp_path):
    """A code-completion prompt whose RTL skeleton declares the module name
    VERBATIM (e.g. `FindFasterClock`): the harness instantiates that exact name,
    so MODULE-NAME-CASE must NOT fire even though the id stem is lowercase."""
    prompt = ("Complete this module:\n```verilog\n"
              "module FindFasterClock(input clk_a, input clk_b, output reg y);\n"
              "endmodule\n```\n")
    rtl = ("module FindFasterClock(input clk_a, input clk_b, output reg y);\n"
           "  assign y = clk_a;\nendmodule\n")
    for strict in (False, True):
        r = _run_cli(tmp_path, rtl, prompt,
                     rid="cvdp_copilot_findfasterclock_0001", strict=strict)
        assert r.returncode == 0, (strict, r.stdout, r.stderr)
        assert "MODULE-NAME-CASE" not in r.stdout
        assert "interface-conformance ok" in r.stdout


def test_fp1_helper_parse_all_rtl_keeps_top_first(tmp_path):
    """parse_all_rtl returns EVERY module, top first — the structural signal
    the scoping relies on."""
    mods = M.parse_all_rtl(
        "module top(input a); sub u(); endmodule\n"
        "module sub(input b, output c); endmodule\n")
    assert [m.module_name for m in mods] == ["top", "sub"]
    assert mods[1].ports == {"b": "input", "c": "output"}


# ── FP CLASS 2: MISSING-PORT (sub-module ports) no longer fires ─────────────
def test_fp2_submodule_ports_satisfied_not_missing(tmp_path):
    """Prompt given-code defines a SUB-module `dual_port_memory`; its ports are
    correctly declared on that sub-module in the completion → SATISFIED, no
    MISSING-PORT, even in strict mode."""
    prompt = ("Use this sub-module:\n```verilog\n"
              "module dual_port_memory(input [7:0] din, output [7:0] dout, "
              "input [3:0] read_addr, input we, input [3:0] write_addr);\n"
              "endmodule\n```\nImplement the top `ping_pong`.\n")
    rtl = ("module ping_pong(input clk, input rst, output reg done);\n"
           "  dual_port_memory u_mem(.din(d), .dout(q), .read_addr(ra), "
           ".we(we), .write_addr(wa));\nendmodule\n"
           "module dual_port_memory(input [7:0] din, output [7:0] dout, "
           "input [3:0] read_addr, input we, input [3:0] write_addr);\n"
           "endmodule\n")
    for strict in (False, True):
        r = _run_cli(tmp_path, rtl, prompt, rid="cvdp_copilot_ping_pong_0001",
                     strict=strict)
        assert r.returncode == 0, (strict, r.stdout, r.stderr)
        assert "MISSING-PORT" not in r.stdout
        for sig in ("din", "dout", "read_addr", "write_addr"):
            assert sig not in r.stdout
        assert "interface-conformance ok" in r.stdout


# ── FP CLASS 3: PORT-DIRECTION / module-name token excluded ─────────────────
def test_fp3_module_name_token_excluded_from_comparison(tmp_path):
    """A token equal to a declared MODULE name (here surfaced via a heading +
    a one-row table) is NOT an interface signal — it is excluded entirely, so
    neither MISSING-PORT nor PORT-DIRECTION fires for it."""
    prompt = ("### 1. Module: Word_Change_Pulse\n\n"
              "| Signal | Direction |\n| `Word_Change_Pulse` | output |\n")
    rtl = "module Word_Change_Pulse(input clk, output reg p);\nendmodule\n"
    for strict in (False, True):
        r = _run_cli(tmp_path, rtl, prompt,
                     rid="cvdp_copilot_word_change_detector_0001",
                     strict=strict)
        assert r.returncode == 0, (strict, r.stdout, r.stderr)
        assert "Word_Change_Pulse" not in r.stdout
        assert "PORT-DIRECTION" not in r.stdout
        assert "MISSING-PORT" not in r.stdout


# ── (d) context-provided names are not author-missing (#715 family) ─────────
def test_context_rtl_ports_satisfied_not_missing(tmp_path):
    """Ports declared on a harness-supplied --context module count as SATISFIED
    — not author-missing — while WITHOUT the context they are flagged missing."""
    prompt = "| `bus_req` | input | | `bus_ack` | output |\n"
    rtl = "module dut(input clk);\nendmodule\n"
    ctx = "module ctx_mod(input bus_req, output bus_ack);\nendmodule\n"
    # without context → both missing
    r0 = _run_cli(tmp_path, rtl, prompt)
    assert "bus_req" in r0.stdout and "bus_ack" in r0.stdout
    # with context → satisfied
    r1 = _run_cli(tmp_path, rtl, prompt, context=[ctx], strict=True)
    assert r1.returncode == 0, (r1.stdout, r1.stderr)
    assert "interface-conformance ok" in r1.stdout
    assert "bus_req" not in r1.stdout and "bus_ack" not in r1.stdout


def test_context_does_not_appear_in_files_read_unless_passed(tmp_path):
    """Blindness: files_read lists ONLY prompt + rtl when no --context; when a
    --context is passed it is listed (a legitimately handed-in file)."""
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    cp = tmp_path / "ctx.sv"
    jp = tmp_path / "rep.json"
    rp.write_text("module dut(input clk);\nendmodule\n")
    pp.write_text("| `clk` | input |\n")
    cp.write_text("module ctx(input clk);\nendmodule\n")
    r = subprocess.run(
        [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp),
         "--context", str(cp), "--json", str(jp)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rep = json.loads(jp.read_text())
    assert set(rep["files_read"]) == {str(pp), str(rp), str(cp)}


# ── §4.05 NO-LEAK: a GENUINE gap on the REAL top still fires ────────────────
def test_noleak_real_missing_top_port_still_flagged(tmp_path):
    """A prompt-named top port genuinely ABSENT from every module (and not a
    module name) STILL fires MISSING-PORT — strict blocks."""
    prompt = "AXI master. | `arvalid` | output | | `arready` | input |\n"
    rtl = "module axim(input clk, input arready);\nendmodule\n"
    r = _run_cli(tmp_path, rtl, prompt, strict=True)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "MISSING-PORT" in r.stdout and "arvalid" in r.stdout


def test_noleak_real_port_direction_mismatch_still_flagged(tmp_path):
    """A real top-port direction mismatch (prompt input vs RTL output, name is
    NOT a module name) STILL fires PORT-DIRECTION — strict blocks."""
    prompt = "SRAM. | `sram_valid` | input | | `sram_data` | output |\n"
    rtl = "module sram_if(output sram_valid, output sram_data);\nendmodule\n"
    r = _run_cli(tmp_path, rtl, prompt, strict=True)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "PORT-DIRECTION" in r.stdout and "sram_valid" in r.stdout


def test_noleak_genuine_module_name_case_still_flagged(tmp_path):
    """A genuine MODULE-NAME-CASE miss — the prompt did NOT declare the name
    verbatim in an RTL skeleton (only mentions the lowercase id in backticks) —
    STILL fires; the suppression is gated on a verbatim prompt declaration."""
    prompt = "Design `findfasterclock`. | `clk` | input |\n"
    rtl = "module FindFasterClock(input clk);\nendmodule\n"
    r = _run_cli(tmp_path, rtl, prompt,
                 rid="cvdp_copilot_findfasterclock_0001")
    assert r.returncode == 0  # advisory
    assert "MODULE-NAME-CASE" in r.stdout
    assert "FindFasterClock" in r.stdout


def test_noleak_missing_sub_module_port_not_anywhere_still_flagged(tmp_path):
    """Sub-module scoping must not become a blanket pass: a prompt-named signal
    declared on NO module (top or sub) still fires MISSING-PORT."""
    prompt = ("```verilog\nmodule sub(input a, output b);\nendmodule\n```\n"
              "| `c_not_declared` | input |\n")
    rtl = ("module top(input clk);\n  sub u(.a(x), .b(y));\nendmodule\n"
           "module sub(input a, output b);\nendmodule\n")
    r = _run_cli(tmp_path, rtl, prompt, strict=True)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "MISSING-PORT" in r.stdout and "c_not_declared" in r.stdout
    # a/b ARE declared on the sub-module → not flagged
    assert "'a'" not in r.stdout and "'b'" not in r.stdout


# ── chip-AGNOSTIC source guard ──────────────────────────────────────────────
def test_chip_agnostic_source():
    guard = PROGRAMS / "source_chip_agnostic_check.py"
    r = subprocess.run(
        [sys.executable, str(guard), str(PLUGIN)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
