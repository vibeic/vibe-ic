#!/usr/bin/env python3
"""Tests for ORGANIC #723 — rtl_hygiene_lint rule
`reset-boundary-residual-enable`.

The rule DETECTS a clocked register that is RESET-CLEARED to 0 then updated
under a purely LEVEL-sensitive enable that traces to a TOP-LEVEL INPUT, with NO
registered armed/settle/valid-after-reset qualifier — the
stale-enable-post-reset-write hole.

ORGANIC #770 round-2 (this rule's gating is SUPERSEDED): the level-enable
heuristic is UNCORROBORATED — a held-high enable on the first post-reset edge is
the CORRECT behaviour for the overwhelming majority of valid/ready / capture
registers (AXI `awvalid_q`/`wvalid_q`/`timeout_flag_q`). So the finding is now
PROSE_HEURISTIC with NO structural corroboration → it is emitted as an ADVISORY
(`block_eligible == False`, demoted to INFO severity) and NEVER hard-blocks
(never trips rc=1). It is still REPORTED at `--severity INFO`.

Validates:
  (a) the `## 驗收` fixture still DETECTS the pattern but emits it as an
      ADVISORY (INFO severity, block_eligible False, rc=0 — #770 round-2);
  (b) §4.05 NO-LEAK:
        - a version WITH a registered armed/settle guard does NOT fire;
        - a counter gated by an INTERNAL (non-input) enable does NOT fire;
  (c) corpus-clean on ordinary reset-cleared counters (unconditional `else`,
      toggle, reset-cleared D-register).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'rtl_hygiene_lint.py'
assert SCRIPT.exists()

RULE = 'reset-boundary-residual-enable'


def _run(tmp_path, sv_content, name='dut.sv', severity='INFO'):
    """Run the lint and return (CompletedProcess, list-of-findings-dicts).

    ORGANIC #770 round-2 — the finding is now ADVISORY (INFO severity), so the
    default capture severity is INFO (else the JSON filter would drop it)."""
    f = tmp_path / name
    f.write_text(sv_content)
    jpath = tmp_path / 'findings.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--severity', severity,
         '--json', str(jpath), str(f)],
        capture_output=True, text=True)
    findings = json.loads(jpath.read_text()) if jpath.exists() else []
    return res, findings


def _fires(findings):
    return [f for f in findings if f['rule'] == RULE]


# ---------------------------------------------------------------------------
# (a) The `## 驗收` fixture WARNs.
# ---------------------------------------------------------------------------
ACCEPTANCE_FIXTURE = (
    "module m(input clk,rst_n,we,output reg [3:0] cnt); wire dw=we; "
    "always @(posedge clk or negedge rst_n) if(!rst_n) cnt<=0; "
    "else if(dw) cnt<=cnt+1; endmodule\n"
)


def test_acceptance_fixture_advisory(tmp_path):
    # ORGANIC #770 round-2 — the pattern is STILL DETECTED, but emitted as an
    # ADVISORY (block_eligible False, INFO severity) and does NOT hard-block.
    res, findings = _run(tmp_path, ACCEPTANCE_FIXTURE)
    hits = _fires(findings)
    assert hits, f"expected {RULE} to be DETECTED on the 驗收 fixture; got {findings}"
    # the offending register is `cnt`
    assert any(h['symbol'] == 'cnt' for h in hits)
    # #770 round-2 — uncorroborated level-enable heuristic → ADVISORY, INFO
    assert all(h['severity'] == 'INFO' for h in hits)
    assert all(h['block_eligible'] is False for h in hits)
    assert all('ORGANIC #770' in h['advisory_note'] for h in hits)
    # an advisory-only finding must NOT make the program exit nonzero
    assert res.returncode == 0


def test_acceptance_fixture_advisory_via_stdout(tmp_path):
    """The pattern is reported (at INFO) with an [ADVISORY …] suffix and the
    program exits 0 — no hard block (ORGANIC #770 round-2)."""
    f = tmp_path / 'r.sv'
    f.write_text(ACCEPTANCE_FIXTURE)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--severity', 'INFO', str(f)],
        capture_output=True, text=True)
    assert RULE in res.stdout
    assert 'ADVISORY' in res.stdout
    assert res.returncode == 0


# ---------------------------------------------------------------------------
# (b) §4.05 NO-LEAK — these must NOT fire.
# ---------------------------------------------------------------------------
WITH_ARMED_GUARD = """
module m(input clk, rst_n, we, output reg [3:0] cnt);
    reg armed;
    wire dw = we;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin cnt <= 0; armed <= 0; end
        else begin
            armed <= 1'b1;
            if (armed && dw) cnt <= cnt + 1;
        end
endmodule
"""

WITH_SETTLE_GUARD = """
module m(input clk, rst_n, we, output reg [3:0] cnt);
    reg reset_done;
    wire dw = we;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin cnt <= 0; reset_done <= 1'b0; end
        else if (reset_done && dw) cnt <= cnt + 1;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) reset_done <= 1'b0; else reset_done <= 1'b1;
endmodule
"""

INTERNAL_ENABLE = """
module m(input clk, rst_n, output reg [3:0] cnt);
    reg internal_en;
    wire dw = internal_en;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin cnt <= 0; internal_en <= 1'b0; end
        else if (dw) cnt <= cnt + 1;
endmodule
"""

# enable already self-gates on reset (en & rst_n) — not a residual-enable hole
ENABLE_SELF_GATED_BY_RESET = """
module m(input clk, rst_n, we, output reg [3:0] cnt);
    wire dw = we & rst_n;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) cnt <= 0;
        else if (dw) cnt <= cnt + 1;
endmodule
"""


@pytest.mark.parametrize('name,sv', [
    ('with_armed_guard', WITH_ARMED_GUARD),
    ('with_settle_guard', WITH_SETTLE_GUARD),
    ('internal_enable', INTERNAL_ENABLE),
    ('enable_self_gated_by_reset', ENABLE_SELF_GATED_BY_RESET),
])
def test_no_leak(tmp_path, name, sv):
    _, findings = _run(tmp_path, sv, name=f'{name}.sv')
    assert not _fires(findings), (
        f"{name}: rule {RULE} must NOT fire (no-leak); got "
        f"{[f for f in findings if f['rule'] == RULE]}")


# ---------------------------------------------------------------------------
# (c) Corpus-clean on ordinary reset-cleared counters.
# ---------------------------------------------------------------------------
# unconditional else (the ubiquitous legitimate counter — no level enable)
LEGIT_UNCOND_COUNTER = """
module m(input clk, input rst_n, output wire [7:0] q);
    reg [7:0] data;
    always @(posedge clk) if (!rst_n) data <= 0; else data <= data + 1;
    assign q = data;
endmodule
"""

# reset-cleared toggle (no level enable)
LEGIT_TOGGLE = """
module m(input clk, input rst_n, output reg y);
    always @(posedge clk) if (!rst_n) y <= 0; else y <= ~y;
endmodule
"""

# reset-cleared D register driven by a datapath input but unconditional else
LEGIT_RESET_CLEARED_D = """
module m(input clk, rst_n, d_in, output reg q);
    always @(posedge clk) if (rst) q <= 0; else q <= d_in;
endmodule
"""

# reset-cleared accumulator and counter, both unconditional in the else branch
LEGIT_TWO_REGS = """
module m(input clk, input rst_n, output reg [7:0] acc, output reg [7:0] ctr);
    always @(posedge clk) begin
        if (!rst_n) begin acc <= 8'h00; ctr <= 8'h00; end
        else        begin acc <= acc + ctr; ctr <= ctr + 1; end
    end
endmodule
"""


@pytest.mark.parametrize('name,sv', [
    ('legit_uncond_counter', LEGIT_UNCOND_COUNTER),
    ('legit_toggle', LEGIT_TOGGLE),
    ('legit_reset_cleared_d', LEGIT_RESET_CLEARED_D),
    ('legit_two_regs', LEGIT_TWO_REGS),
])
def test_corpus_clean_ordinary_counters(tmp_path, name, sv):
    _, findings = _run(tmp_path, sv, name=f'{name}.sv')
    assert not _fires(findings), (
        f"{name}: rule {RULE} false-fired on a legitimate reset-cleared "
        f"counter; got {[f for f in findings if f['rule'] == RULE]}")


# ---------------------------------------------------------------------------
# extra: the indirect-input-trace path (enable via a chain of comb wires)
# still fires, proving condition (b) covers `assign`/`wire` chains.
# ---------------------------------------------------------------------------
def test_detects_through_combinational_chain(tmp_path):
    sv = """
module m(input clk, rst_n, write_enable, full, output reg [3:0] ptr);
    wire not_full = ~full;
    wire do_write = write_enable & not_full;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) ptr <= 0;
        else if (do_write) ptr <= ptr + 1;
endmodule
"""
    _, findings = _run(tmp_path, sv)
    hits = _fires(findings)
    assert hits, f"expected {RULE} to be DETECTED through a comb chain; got {findings}"
    assert any(h['symbol'] == 'ptr' for h in hits)
    # ORGANIC #770 round-2 — still ADVISORY-only through the comb chain.
    assert all(h['block_eligible'] is False for h in hits)


# ---------------------------------------------------------------------------
# extra: multi-module file — fire on the offending module's input-gated reg,
# stay clean on a sibling submodule that uses an unconditional else.
# ---------------------------------------------------------------------------
def test_multi_module_fires_only_on_real_hole(tmp_path):
    sv = """
module sub(input clk, rst_n, output reg [3:0] c);
    always @(posedge clk) if (!rst_n) c <= 0; else c <= c + 1;
endmodule
module top(input clk, rst_n, en, output reg [3:0] cnt);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) cnt <= 0; else if (en) cnt <= cnt + 1;
    sub u (.clk(clk), .rst_n(rst_n), .c());
endmodule
"""
    _, findings = _run(tmp_path, sv, name='multi.sv')
    hits = _fires(findings)
    assert hits, f"expected {RULE} to be DETECTED on top.cnt; got {findings}"
    syms = {h['symbol'] for h in hits}
    assert 'cnt' in syms          # the real hole
    assert 'c' not in syms        # sibling unconditional-else counter is clean
    # ORGANIC #770 round-2 — the detection is ADVISORY-only (never hard-blocks).
    assert all(h['block_eligible'] is False for h in hits)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
