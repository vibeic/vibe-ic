#!/usr/bin/env python3
"""Tests for ORGANIC #727 — rtl_hygiene_lint rule `uninit-registered-output`
must CREDIT a reset assignment that lives inside a single mixed
`always @(... posedge/negedge <rst>)` process (reset branch + datapath share
ONE block), instead of false-flagging the output as "no reset".

Before the fix the rule used a whole-module early-return: if no INPUT port name
matched the reset-name detector, the module was treated as reset-less and EVERY
registered output was flagged. APB resets like `presetn` are not spelled
rst/reset, so a perfectly reset-covered output (`if(!presetn) v<=0;`) was
false-flagged. The fix replaces that with a per-OUTPUT structural reset-credit:
an output assigned under the reset condition of its enclosing reset-bearing
process (single mixed block included) is credited and not flagged.

Validates:
  (a) the `## 驗收` fixture no longer fires — `v` IS reset in `if(!presetn)` of
      the single mixed process (`presetn` is detected STRUCTURALLY, by being the
      sensitivity-list edge signal that the head `if` tests, not by name);
  (b) §4.05 NO-LEAK — an output that is truly NEVER assigned under any reset
      condition is STILL flagged, even when the module HAS a reset port and a
      sibling output IS reset in the same mixed block;
  (c) the multi-output APB mixed-block analog (pready/prdata/pslverr/sram_valid)
      — all reset in one `if(!presetn)` branch — produces NO findings;
  (d) a synchronous `if(rst) z<=0;` (clk-only sensitivity list) is credited;
  (e) a genuinely reset-less module still fires (rule not over-suppressed).
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'rtl_hygiene_lint.py'
assert SCRIPT.exists()

RULE = 'uninit-registered-output'


def _run(tmp_path, sv_content, name='dut.sv', severity='WARN'):
    """Run the lint and return (CompletedProcess, list-of-findings-dicts)."""
    f = tmp_path / name
    f.write_text(sv_content)
    jpath = tmp_path / 'findings.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--severity', severity,
         '--json', str(jpath), str(f)],
        capture_output=True, text=True)
    findings = json.loads(jpath.read_text()) if jpath.exists() else []
    return res, findings


def _fired_symbols(findings):
    return {f['symbol'] for f in findings if f['rule'] == RULE}


# ---------------------------------------------------------------------------
# (a) The `## 驗收` fixture must NOT fire — `v` is reset in the single process.
# ---------------------------------------------------------------------------
ACCEPTANCE_FIXTURE = (
    "module m(input pclk,presetn,output reg v); "
    "always @(posedge pclk or negedge presetn) begin "
    "if(!presetn) v<=0; else v<=1; end endmodule\n"
)


def test_acceptance_fixture_no_finding(tmp_path):
    res, findings = _run(tmp_path, ACCEPTANCE_FIXTURE)
    assert _fired_symbols(findings) == set(), (
        "`v` IS reset in the if(!presetn) branch of the single mixed process; "
        f"must not be flagged. findings={findings}")
    assert res.returncode == 0, res.stdout + res.stderr


# ---------------------------------------------------------------------------
# (b) §4.05 NO-LEAK — an output NEVER assigned under reset is STILL flagged,
#     even though the module has a reset port and a sibling output IS reset.
# ---------------------------------------------------------------------------
NOLEAK_FIXTURE = (
    "module m2(input pclk,presetn,output reg a,output reg b);\n"
    " always @(posedge pclk or negedge presetn) begin\n"
    "  if(!presetn) begin a<=0; end\n"        # only a is reset
    "  else begin a<=1; b<=1; end\n"          # b only ever assigned in datapath
    " end\nendmodule\n"
)


def test_noleak_unreset_output_still_fires(tmp_path):
    res, findings = _run(tmp_path, NOLEAK_FIXTURE)
    fired = _fired_symbols(findings)
    assert 'b' in fired, (
        "`b` is never assigned under the reset condition -> still powers up X; "
        f"must STILL be flagged. findings={findings}")
    assert 'a' not in fired, (
        "`a` IS reset in if(!presetn); must not be flagged. "
        f"findings={findings}")
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# (c) Multi-output APB mixed-block — all reset in one if(!presetn) branch.
# ---------------------------------------------------------------------------
APB_MIXED_FIXTURE = (
    "module apb(input pclk,presetn,output reg pready,output reg [7:0] prdata,"
    "output reg pslverr,output reg sram_valid);\n"
    " always @(posedge pclk or negedge presetn) begin\n"
    "  if(!presetn) begin pready<=0; prdata<=0; pslverr<=0; sram_valid<=0; end\n"
    "  else begin pready<=1; prdata<=8'hAB; pslverr<=0; sram_valid<=1; end\n"
    " end\nendmodule\n"
)


def test_apb_mixed_block_all_reset_no_finding(tmp_path):
    res, findings = _run(tmp_path, APB_MIXED_FIXTURE)
    assert _fired_symbols(findings) == set(), (
        "all four APB outputs are reset in the single if(!presetn) branch; "
        f"none may be flagged. findings={findings}")
    assert res.returncode == 0


# ---------------------------------------------------------------------------
# (d) Synchronous reset (clk-only sensitivity list, if(rst) z<=0) is credited.
# ---------------------------------------------------------------------------
SYNC_RESET_FIXTURE = (
    "module m4(input clk,rst,output reg z);\n"
    " always @(posedge clk) begin\n"
    "  if(rst) z<=0; else z<=1;\n"
    " end\nendmodule\n"
)


def test_sync_reset_credited_no_finding(tmp_path):
    res, findings = _run(tmp_path, SYNC_RESET_FIXTURE)
    assert _fired_symbols(findings) == set(), (
        "`z` is synchronously reset by if(rst); must not be flagged. "
        f"findings={findings}")
    assert res.returncode == 0


# ---------------------------------------------------------------------------
# (e) Genuinely reset-less module STILL fires (rule not over-suppressed).
# ---------------------------------------------------------------------------
RESETLESS_FIXTURE = (
    "module u(input clk,output reg q); always @(posedge clk) q<=1; endmodule\n"
)


def test_resetless_output_still_fires(tmp_path):
    res, findings = _run(tmp_path, RESETLESS_FIXTURE)
    assert 'q' in _fired_symbols(findings), (
        "`q` has no reset and no power-up initializer; must be flagged. "
        f"findings={findings}")
    assert res.returncode == 1
