#!/usr/bin/env python3
"""ORGANIC #695 [P2, chip-AGNOSTIC] — prompt→interface conformance gate.

Oracle-RCA on the CVDP cvdp-open residual surfaced a recurring PROMPT-DERIVABLE,
PROGRAM-CHECKABLE interface class the blind author gets wrong and no gate caught
before emit. The hidden cocotb harness binds the DUT by EXACT names/directions
and derives TOPLEVEL from the canonical id, so any of:
  (1) module name != the canonical id stem CASE-EXACTLY (FindFasterClock vs
      harness top findfasterclock) → elaboration fail;
  (2) a prompt-named interface port ABSENT from the RTL port list (AXI ar*/aw*;
      s_ready; register_addr_i named only in a wavedrom) → bind/elab fail;
  (3) a port whose DIRECTION disagrees with the prompt's signal table (harness
      DRIVES sram_valid as input but RTL declares output) → functional fail.
All three derive from the PROMPT ALONE + the RTL, so a deterministic gate that
reads ONLY those two flags them at emit time; run-time stays BLIND.

POSITIVE: replicate the 驗收 END-STATE — the FindFasterClock case flags
MODULE-NAME-CASE + missing `faster`, rc 0 advisory / 1 strict; the fixed RTL
prints `interface-conformance ok`. Plus AXI missing-port + sram_valid
direction.

§4.05 NEGATIVE no-leak: an INTERNAL signal named in prompt PROSE but legitimately
NOT a port must NOT hard-block (advisory only — and not even flagged when the
mention carries no direction/table evidence); a conformant RTL prints ok; the
gate NEVER reads the oracle / hidden TB — it opens ONLY --prompt + --rtl.

chip-AGNOSTIC: pure prompt-prose + RTL structure; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
PROG = PROGRAMS / "iface_conformance_v2.py"
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as M  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── 驗收 fixtures (the exact acceptance shape) ──────────────────────────────
ACCEPT_RTL = (
    "module FindFasterClock(input clk_A, input clk_B, input rst_n, "
    "output y); assign y=clk_A; endmodule\n")
ACCEPT_PROMPT = (
    "Design `findfasterclock`. | `clk_A` | input | ... | `clk_B` | input | "
    "... | `rst_n` | input | ... | `faster` | output |\n")
ACCEPT_ID = "cvdp_copilot_findfasterclock_0001"
FIXED_RTL = (
    "module findfasterclock(input clk_A, input clk_B, input rst_n, "
    "output faster); assign faster=clk_A; endmodule\n")


def _run_cli(tmp_path, rtl, prompt, rid=None, strict=False):
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    rp.write_text(rtl)
    pp.write_text(prompt)
    cmd = [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp)]
    if rid is not None:
        cmd += ["--id", rid]
    if strict:
        cmd.append("--strict")
    return _pr.run(cmd, capture_output=True, text=True)


# ── POSITIVE: 驗收 END-STATE ────────────────────────────────────────────────
def test_acceptance_advisory_flags_case_and_missing_port_rc0(tmp_path):
    r = _run_cli(tmp_path, ACCEPT_RTL, ACCEPT_PROMPT, rid=ACCEPT_ID)
    assert r.returncode == 0, r.stderr  # advisory default → rc 0
    out = r.stdout
    assert "MODULE-NAME-CASE: harness top is 'findfasterclock'" in out
    assert "FindFasterClock" in out
    assert "MISSING-PORT" in out and "faster" in out


def test_acceptance_strict_exits_1(tmp_path):
    r = _run_cli(tmp_path, ACCEPT_RTL, ACCEPT_PROMPT, rid=ACCEPT_ID,
                 strict=True)
    assert r.returncode == 1
    assert "MODULE-NAME-CASE" in r.stdout
    assert "MISSING-PORT" in r.stdout


def test_acceptance_fixed_rtl_prints_ok_rc0(tmp_path):
    for strict in (False, True):
        r = _run_cli(tmp_path, FIXED_RTL, ACCEPT_PROMPT, rid=ACCEPT_ID,
                     strict=strict)
        assert r.returncode == 0, r.stderr
        assert "interface-conformance ok" in r.stdout


# ── POSITIVE: AXI missing-port ──────────────────────────────────────────────
def test_axi_missing_burst_ports_flagged(tmp_path):
    prompt = ("AXI master. | `arvalid` | output | | `arready` | input | "
              "| `awvalid` | output | | `rdata` | input |\n")
    rtl = ("module axim(input clk, output awvalid, input arready, "
           "input rdata); endmodule\n")
    r = _run_cli(tmp_path, rtl, prompt)
    assert r.returncode == 0  # advisory
    assert "MISSING-PORT" in r.stdout and "arvalid" in r.stdout
    # awvalid/arready/rdata ARE declared → not reported missing
    assert "'awvalid'" not in r.stdout


def test_axi_missing_port_strict_blocks(tmp_path):
    prompt = "AXI. | `arvalid` | output | | `awvalid` | output |\n"
    rtl = "module axim(input clk, output awvalid); endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt, strict=True)
    assert r.returncode == 1
    assert "arvalid" in r.stdout


# ── POSITIVE: port-direction (sram_valid) ───────────────────────────────────
def test_port_direction_input_vs_output_flagged(tmp_path):
    prompt = "SRAM iface. | `sram_valid` | input | desc | `sram_data` | output |\n"
    rtl = "module sram_if(output sram_valid, output sram_data); endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt)
    assert r.returncode == 0
    assert "PORT-DIRECTION" in r.stdout
    assert "sram_valid" in r.stdout
    assert "input" in r.stdout and "output" in r.stdout


def test_port_direction_matching_is_ok(tmp_path):
    prompt = "SRAM. | `sram_valid` | input | | `sram_data` | output |\n"
    rtl = "module sram_if(input sram_valid, output sram_data); endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt, strict=True)
    assert r.returncode == 0
    assert "interface-conformance ok" in r.stdout


# ── wavedrom name source ────────────────────────────────────────────────────
def test_wavedrom_named_port_missing_flagged(tmp_path):
    prompt = ('Timing: {"signal":[{"name":"register_addr_i"},'
              '{"name":"clk"}]}. | `clk` | input |\n')
    rtl = "module r(input clk); endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt)
    assert r.returncode == 0
    assert "register_addr_i" in r.stdout
    assert "wavedrom" in r.stdout  # source attribution


# ── §4.05 NEGATIVE no-leak ──────────────────────────────────────────────────
def test_internal_prose_signal_not_a_port_no_block(tmp_path):
    """An internal signal mentioned in prose (bare backtick, no direction word
    nearby, not in a table) must NOT be treated as a port — advisory only,
    never a hard block, even with --strict."""
    prompt = ("A counter. Internally it uses a `tmp_accumulator` register. "
              "Ports: | `clk` | input | | `q` | output |\n")
    rtl = ("module ctr(input clk, output q); reg [7:0] tmp_accumulator; "
           "assign q = tmp_accumulator[0]; endmodule\n")
    for strict in (False, True):
        r = _run_cli(tmp_path, rtl, prompt, strict=strict)
        assert r.returncode == 0, (strict, r.stdout, r.stderr)
        assert "interface-conformance ok" in r.stdout
        assert "tmp_accumulator" not in r.stdout


def test_conformant_rtl_prints_ok(tmp_path):
    prompt = "Mod `foo`. | `a` | input | | `b` | output |\n"
    rtl = "module foo(input a, output b); assign b=a; endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt, rid="cvdp_copilot_foo_0001",
                 strict=True)
    assert r.returncode == 0
    assert "interface-conformance ok" in r.stdout


def test_module_name_genuinely_different_not_flagged(tmp_path):
    """A genuinely DIFFERENT module name (not just a case variant of the id
    stem) is the author's/prompt's design freedom (the prompt `Module Name:`
    may rename) — flagging it would false-fire constantly. Only a CASE-only
    difference is the deterministic harness elaboration miss."""
    prompt = "Mod. | `a` | input | | `b` | output |\n"
    rtl = "module qam16_mapper(input a, output b); assign b=a; endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt,
                 rid="cvdp_copilot_findfasterclock_0001", strict=True)
    # b/a declared, name differs by MORE than case → no MODULE-NAME-CASE flag
    assert "MODULE-NAME-CASE" not in r.stdout
    assert r.returncode == 0


def test_gate_is_blind_opens_only_prompt_and_rtl(tmp_path):
    """The gate must NEVER read the oracle / hidden TB — the JSON report's
    files_read must list ONLY the --prompt and --rtl paths."""
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    jp = tmp_path / "rep.json"
    rp.write_text(ACCEPT_RTL)
    pp.write_text(ACCEPT_PROMPT)
    # plant an oracle/hidden-TB decoy in the same dir; it must NOT be read
    (tmp_path / "testbench.sv").write_text("module tb; endmodule\n")
    (tmp_path / "verified_findfasterclock.v").write_text("ORACLE\n")
    r = _pr.run(
        [sys.executable, str(PROG), "--id", ACCEPT_ID, "--prompt", str(pp),
         "--rtl", str(rp), "--json", str(jp)],
        capture_output=True, text=True)
    assert r.returncode == 0
    import json
    rep = json.loads(jp.read_text())
    assert set(rep["files_read"]) == {str(pp), str(rp)}
    assert rep["conformant"] is False  # case + missing port findings


def test_empty_rtl_refused_rc2(tmp_path):
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    rp.write_text("   \n")
    pp.write_text(ACCEPT_PROMPT)
    r = _pr.run(
        [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp)],
        capture_output=True, text=True)
    assert r.returncode == 2


def test_no_id_runs_port_checks_only(tmp_path):
    """Without --id no module-name-case check runs, but port/direction checks
    still fire."""
    prompt = "Mod. | `a` | input | | `missing_sig` | output |\n"
    rtl = "module m(input a); endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt)  # no rid
    assert r.returncode == 0
    assert "MODULE-NAME-CASE" not in r.stdout
    assert "MISSING-PORT" in r.stdout and "missing_sig" in r.stdout


# ── unit-level helpers ──────────────────────────────────────────────────────
def test_harness_top_from_id():
    assert M.harness_top_from_id("cvdp_copilot_findfasterclock_0001") \
        == "findfasterclock"
    assert M.harness_top_from_id("cvdp_copilot_qam16_mapper_0042") \
        == "qam16_mapper"
    assert M.harness_top_from_id("cvdp_copilot_foo") == "foo"
    assert M.harness_top_from_id("") is None
    assert M.harness_top_from_id(None) is None


def test_parse_rtl_nonansi_directions():
    iface = M.parse_rtl(
        "module m(a, b, c); input a; input b; output c; endmodule")
    assert iface.module_name == "m"
    assert iface.ports == {"a": "input", "b": "input", "c": "output"}


def test_parse_rtl_ansi_directions():
    iface = M.parse_rtl(
        "module m(input wire [3:0] a, output reg b, inout c); endmodule")
    assert iface.module_name == "m"
    assert iface.ports["a"] == "input"
    assert iface.ports["b"] == "output"
    assert iface.ports["c"] == "inout"


def test_extract_prompt_iface_table_directions():
    pif = M.extract_prompt_iface("| `clk` | input | | `q` | output |")
    assert pif.ports["clk"] == "input"
    assert pif.ports["q"] == "output"


def test_chip_agnostic_source():
    """The new program must pass the chip-AGNOSTIC source guard."""
    guard = PROGRAMS / "source_chip_agnostic_check.py"
    r = _pr.run(
        [sys.executable, str(guard), str(PLUGIN)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
