"""ORGANIC round-9 Step-2.7 §4.05 remediations — the v1.1.1 #785/#786/#787
checker relaxations were each reproduced HIGH-leaking by the pre-push adversarial
review (subagent relaxations uniformly too wide). These lock the no-leak fixes.

#785 — _nl_port_is_prose dropped GENUINE described ports (`- input load enable.`,
       `- input reset active high.`) → a missing such port leaked past
       spec_conformance. Fix: a CANONICAL signal name or IDENTIFIER-shaped name is
       never dropped; only a bare generic datapath noun stays phantom-prone.
#786 — _is_fault_state SUBSTRING-matched, exempting operational states
       (ERROR_RECOVERY / WAIT_TIMEOUT / FAILSAFE / NO_FAULT / …) → genuine
       mid-FSM spurious-error anti-patterns silently suppressed. Fix: whole-TOKEN
       fault vocab + a negater/operational token forces NOT-a-fault.
#787 — datapath latency measured the FIRST bus change, so a staged-partial /
       glitch under-measured → a genuine 2-cycle datapath passed as 1-cycle. Fix:
       SETTLE measurement (last change) + a multi-change bus is ADVISORY (rc=3),
       never a hard rc=0 PASS.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_P))
import _specrtl_common as SC          # noqa: E402
import fsm_error_invariant as FE      # noqa: E402

_LAT = _P / "latency_conformance_check.py"


# ── #785: real described ports kept; generic-noun phantoms still dropped ──────
@pytest.mark.parametrize("bullet,name", [
    ("- input load enable.", "load"),
    ("- input reset active high.", "reset"),
    ("- input rst_n active-low reset.", "rst_n"),
    ("- input enable.", "enable"),
    ("- input data_valid.", "data_valid"),
    ("- output ready (handshake).", "ready"),
])
def test_785_noleak_genuine_described_port_kept(bullet, name):
    got = [p.name for p in SC._parse_nl_ports(bullet)]
    assert name in got, (bullet, got)


@pytest.mark.parametrize("bullet", [
    "- Input data stream.",
    "- Output average over the window.",
    "- Input data elements are divided into pairs before summation.",
])
def test_785_phantom_prose_still_dropped(bullet):
    assert SC._parse_nl_ports(bullet) == [], bullet


# ── #786: operational fault-substring states FIRE; genuine fault states SKIP ──
@pytest.mark.parametrize("label", [
    "ERROR_RECOVERY", "WAIT_TIMEOUT", "FAILSAFE", "NO_FAULT", "CLEAR_ERROR",
    "S_FAULTLESS", "FAULT_CLEAR", "DEFAULT",
])
def test_786_noleak_operational_state_not_exempt(label):
    assert FE._is_fault_state(label) is False, label


@pytest.mark.parametrize("label", [
    "FAULT", "S_ERROR", "ERROR_STATE", "TIMEOUT", "ERR", "FAIL", "ABORT",
    "FATAL", "ST_FAULT",
])
def test_786_genuine_fault_state_still_exempt(label):
    assert FE._is_fault_state(label) is True, label


# ── #787: staged/glitch datapath → ADVISORY (rc=3), never a rc=0 PASS ─────────
def _lat(tmp_path, rtl, expect=1):
    import json
    p = tmp_path / "dut.v"
    p.write_text(rtl)
    jp = tmp_path / "lat.json"
    r = subprocess.run(
        [sys.executable, str(_LAT), "--rtl", str(p), "--event", "start",
         "--output", "result", "--expect", str(expect), "--json", str(jp)],
        capture_output=True, text=True)
    r.verdict = (json.loads(jp.read_text()).get("verdict")
                 if jp.exists() else None)
    return r


_STAGED = (
    "module dut(input clk, input rst_n, input start, input [7:0] a, "
    "input [7:0] b, output [7:0] result);\n"
    " reg [7:0] acc, fin; reg s1, s2;\n"
    " always @(posedge clk or negedge rst_n)\n"
    "  if(!rst_n) begin acc<=0; fin<=0; s1<=0; s2<=0; end\n"
    "  else begin s1<=start; s2<=s1; acc<=a; fin<=a+b; end\n"
    " assign result = s2 ? fin : (s1 ? acc : 8'h00);\nendmodule\n")
_CLEAN1 = (
    "module dut(input clk, input rst_n, input start, input [7:0] a, "
    "input [7:0] b, output reg [7:0] result);\n"
    " always @(posedge clk or negedge rst_n)\n"
    "  if(!rst_n) result<=0; else if(start) result<=a+b;\nendmodule\n")
_GENUINE2 = (
    "module dut(input clk, input rst_n, input start, input [7:0] a, "
    "output reg [7:0] result);\n"
    " reg [7:0] r1; reg s1;\n"
    " always @(posedge clk or negedge rst_n)\n"
    "  if(!rst_n) begin r1<=0; result<=0; s1<=0; end\n"
    "  else begin s1<=start; r1<=a; if(s1) result<=r1; end\nendmodule\n")


def _has_iverilog():
    from shutil import which
    return which("iverilog") and which("vvp")


@pytest.mark.skipif(not _has_iverilog(), reason="iverilog/vvp not present")
def test_787_noleak_staged_partial_is_advisory_not_pass(tmp_path):
    r = _lat(tmp_path, _STAGED, expect=1)
    assert r.returncode == 3, r.stdout       # ADVISORY, NOT rc=0 PASS
    assert r.verdict == "DATAPATH_AMBIGUOUS", r.verdict


@pytest.mark.skipif(not _has_iverilog(), reason="iverilog/vvp not present")
def test_787_clean_1cycle_datapath_still_passes(tmp_path):
    r = _lat(tmp_path, _CLEAN1, expect=1)
    assert r.returncode == 0, r.stdout       # positive preserved


@pytest.mark.skipif(not _has_iverilog(), reason="iverilog/vvp not present")
def test_787_noleak_genuine_2cycle_vs_expect1_still_blocks(tmp_path):
    r = _lat(tmp_path, _GENUINE2, expect=1)
    assert r.returncode == 1, r.stdout       # real latency miss still hard-blocks


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
