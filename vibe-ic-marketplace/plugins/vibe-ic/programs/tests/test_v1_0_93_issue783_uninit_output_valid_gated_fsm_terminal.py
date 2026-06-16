"""Regression test for ORGANIC #783 (CVDP convergence round 8, cluster R8C4).

rule_uninit_registered_output hard-blocked (rc=1, WARN, block_eligible=True,
and `--fix` injected `initial out_data = 0;`) the legitimate *valid-gated
FSM-terminal output* pattern: a wide result register written ONLY in a
terminal/computed FSM state (`DONE: out_data <= ...`), deliberately OUTSIDE the
reset branch, and qualified by a reset-covered `done`/`valid` companion output.

Post ORGANIC #727 the rule credits an output only when assigned under the reset
branch, so this output was falsely flagged uninitialised. The prose heuristic
"the reference expects 0 at t=0" is CONTRADICTED here: the consumer samples the
result only when the valid flag asserts, so the pre-clock X is never observed,
and forcing `initial 0` would DIVERGE the power-up value (X vs 0) from a
spec-faithful / golden reference on equivalence/area-opt tasks.

The fix:
  * POSITIVE — the pattern is downgraded to ADVISORY (INFO, block_eligible=False)
    via _advisory(PROSE_HEURISTIC, CONTRADICTED), and `--fix` no longer injects
    `initial 0` for it.
  * §4.05 NO-LEAK — three genuine defects of the same class STILL hard-block:
      (N1) a truly reset-less DFF,
      (N2) a free-running output that merely FORGOT its reset (not state-gated),
      (N3) a state-gated terminal output with NO done/valid companion.

All fixtures are self-contained (no host artifacts).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'rtl_hygiene_lint.py'
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import rtl_hygiene_lint as rhl  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures (self-contained)
# ---------------------------------------------------------------------------
# POSITIVE: the valid-gated FSM-terminal output. out_data is written ONLY in
# the DONE terminal state, qualified by the reset-covered `done` companion.
POSITIVE_SV = """
module sorting_engine (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [31:0] in_data,
    output reg  [31:0] out_data,
    output reg         done
);
    localparam IDLE = 2'd0, LOAD = 2'd1, RUN = 2'd2, DONE = 2'd3;
    reg [1:0] state;
    reg [31:0] array0, array1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            done  <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    done <= 1'b0;
                    if (start) state <= LOAD;
                end
                LOAD: begin
                    array0 <= in_data;
                    state  <= RUN;
                end
                RUN: begin
                    array1 <= array0 + 1;
                    state  <= DONE;
                end
                DONE: begin
                    out_data <= array1;
                    done     <= 1'b1;
                    state    <= IDLE;
                end
            endcase
        end
    end
endmodule
"""

# N1: a truly reset-less DFF — clause (1) of the gate (no reset_covered) fails.
NEG1_RESETLESS_DFF = """
module resetless_dff (
    input  wire clk,
    input  wire d,
    output reg  q
);
    always @(posedge clk) begin
        q <= d;
    end
endmodule
"""

# N2: free-running output that merely FORGOT its reset — out_acc is written
# OUTSIDE any case (not state-gated) so clause (3) fails.
NEG2_FORGOT_RESET = """
module forgot_reset (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  in_d,
    output reg  [15:0] out_acc,
    output reg         done
);
    reg [1:0] state;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 2'd0;
            done  <= 1'b0;
        end else begin
            out_acc <= out_acc + in_d;
            case (state)
                2'd0: done <= 1'b0;
                2'd1: done <= 1'b1;
                default: state <= 2'd0;
            endcase
        end
    end
endmodule
"""

# N3: state-gated terminal output with NO done/valid companion — clause (2)
# fails (no 1-bit reset-covered companion output exists).
NEG3_NO_DONE_COMPANION = """
module no_done_companion (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] in_data,
    output reg  [31:0] out_data
);
    localparam IDLE=2'd0, RUN=2'd1, DONE=2'd2;
    reg [1:0] state;
    reg [31:0] acc;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
        end else begin
            case (state)
                IDLE: state <= RUN;
                RUN:  begin acc <= in_data; state <= DONE; end
                DONE: begin out_data <= acc; state <= IDLE; end
            endcase
        end
    end
endmodule
"""


def run_cli(tmp_path, sv_content):
    f = tmp_path / 'dut.sv'
    f.write_text(sv_content)
    out_json = tmp_path / 'findings.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(out_json), str(f)],
        capture_output=True, text=True)
    findings = json.loads(out_json.read_text())
    return res, findings


def _uninit_findings(findings):
    return [f for f in findings if f['rule'] == 'uninit-registered-output']


# ---------------------------------------------------------------------------
# POSITIVE — the FP now passes (advisory, not a hard block)
# ---------------------------------------------------------------------------
class TestPositiveValidGatedFsmTerminal:
    def test_helper_recognises_pattern(self):
        reset_covered = rhl._reset_covered_signals(POSITIVE_SV)
        assert rhl._is_valid_gated_fsm_terminal_output(
            POSITIVE_SV, 'out_data', reset_covered) is True

    def test_finding_downgraded_to_advisory(self, tmp_path):
        res, findings = run_cli(tmp_path, POSITIVE_SV)
        uninit = _uninit_findings(findings)
        assert len(uninit) == 1
        f = uninit[0]
        assert f['symbol'] == 'out_data'
        assert f['severity'] == 'INFO'
        assert f['block_eligible'] is False
        assert 'valid-gated FSM-terminal' in f.get('advisory_note', '')

    def test_no_hard_block_rc_zero(self, tmp_path):
        res, _ = run_cli(tmp_path, POSITIVE_SV)
        assert res.returncode == 0, res.stdout + res.stderr

    def test_autofix_does_not_inject_initial(self, tmp_path):
        f = tmp_path / 'dut.sv'
        f.write_text(POSITIVE_SV)
        res = subprocess.run(
            [sys.executable, str(SCRIPT), '--fix', str(f)],
            capture_output=True, text=True)
        assert res.returncode == 0, res.stdout + res.stderr
        patched = f.read_text()
        # The advisory FSM-terminal output must NOT be force-initialised.
        assert 'out_data = 0' not in patched
        assert 'repaired 0 reset-less registered output' in res.stdout


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — genuine defects of the same class STILL hard-block
# ---------------------------------------------------------------------------
class TestNoLeakNegativesStillBlock:
    @pytest.mark.parametrize('sv,symbol', [
        (NEG1_RESETLESS_DFF, 'q'),
        (NEG2_FORGOT_RESET, 'out_acc'),
        (NEG3_NO_DONE_COMPANION, 'out_data'),
    ])
    def test_negative_still_hard_blocks(self, tmp_path, sv, symbol):
        res, findings = run_cli(tmp_path, sv)
        uninit = _uninit_findings(findings)
        hit = [f for f in uninit if f['symbol'] == symbol]
        assert hit, f"{symbol} should still be flagged uninit-registered-output"
        f = hit[0]
        assert f['severity'] == 'WARN', f
        assert f['block_eligible'] is True, f
        assert res.returncode == 1, res.stdout + res.stderr

    def test_neg1_helper_false_no_reset(self):
        rc = rhl._reset_covered_signals(NEG1_RESETLESS_DFF)
        # clause (1): no reset-covered register at all.
        assert rhl._is_valid_gated_fsm_terminal_output(
            NEG1_RESETLESS_DFF, 'q', rc) is False

    def test_neg2_helper_false_not_state_gated(self):
        rc = rhl._reset_covered_signals(NEG2_FORGOT_RESET)
        # clause (3): out_acc write is outside any case (free-running).
        assert rhl._is_valid_gated_fsm_terminal_output(
            NEG2_FORGOT_RESET, 'out_acc', rc) is False

    def test_neg3_helper_false_no_companion(self):
        rc = rhl._reset_covered_signals(NEG3_NO_DONE_COMPANION)
        # clause (2): no 1-bit reset-covered companion output.
        assert rhl._is_valid_gated_fsm_terminal_output(
            NEG3_NO_DONE_COMPANION, 'out_data', rc) is False

    def test_negatives_autofix_still_injects(self, tmp_path):
        # A genuine reset-less DFF must STILL be repaired by --fix.
        f = tmp_path / 'dut.sv'
        f.write_text(NEG1_RESETLESS_DFF)
        res = subprocess.run(
            [sys.executable, str(SCRIPT), '--fix', str(f)],
            capture_output=True, text=True)
        patched = f.read_text()
        assert 'q = 0' in patched
        assert 'repaired 1 reset-less registered output' in res.stdout


# ── r2 Step-2.7 §4.05 remediation: the guard required only co-EXISTENCE of a
# case + a reset-covered 1-bit output, not a PROVEN control relationship, so a
# genuine forgot-reset output written inside ANY case with a coincidental
# companion leaked to advisory. The 3 reproduced HIGH leaks must hard-block. ──
import subprocess as _sp
import sys as _sys
import json as _json
from pathlib import Path as _Path

_RH = _Path(__file__).resolve().parents[1] / "rtl_hygiene_lint.py"


def _uninit_block_eligible(tmp_path, src, sym):
    p = tmp_path / "d.sv"; p.write_text(src)
    jp = tmp_path / "o.json"
    _sp.run([_sys.executable, str(_RH), "--severity", "INFO",
             "--json", str(jp), str(p)], capture_output=True, text=True)
    fs = [f for f in _json.loads(jp.read_text())
          if f["rule"] == "uninit-registered-output" and f["symbol"] == sym]
    assert fs, f"rule did not fire on {sym}"
    return fs[0]["block_eligible"]


_R783_UNRELATED_DONE = (
    "module m1(input clk, input rst_n, input [7:0] din,\n"
    " output reg [7:0] data_out, output reg busy);\n"
    " reg [1:0] state;\n"
    " always @(posedge clk or negedge rst_n) begin\n"
    "  if (!rst_n) begin state <= 2'd0; busy <= 1'b0; end\n"
    "  else begin busy <= ~busy;\n"
    "   case (state)\n"
    "    2'd0: begin data_out <= din; state <= 2'd1; end\n"
    "    2'd1: begin data_out <= din; state <= 2'd2; end\n"
    "    2'd2: begin data_out <= din; state <= 2'd0; end\n"
    "   endcase end\n end\nendmodule\n")

_R783_ACCUM = (
    "module m2(input clk, input rst_n, input [7:0] din,\n"
    " output reg [7:0] acc, output reg valid);\n"
    " reg [1:0] state;\n"
    " always @(posedge clk or negedge rst_n) begin\n"
    "  if (!rst_n) begin state <= 2'd0; valid <= 1'b0; end\n"
    "  else begin valid <= 1'b1;\n"
    "   case (state)\n"
    "    2'd0: begin acc <= acc + din; state <= 2'd1; end\n"
    "    2'd1: begin acc <= acc + din; state <= 2'd0; end\n"
    "   endcase end\n end\nendmodule\n")

_R783_CASE_ON_INPUT = (
    "module m3(input clk, input rst_n, input [1:0] mode, input [7:0] din,\n"
    " output reg [7:0] data_out, output reg ready);\n"
    " reg [1:0] state;\n"
    " always @(posedge clk or negedge rst_n) begin\n"
    "  if (!rst_n) begin state <= 2'd0; ready <= 1'b0; end\n"
    "  else case (state)\n"
    "   2'd0: begin state <= 2'd1; ready <= 1'b1; end\n"
    "   2'd1: state <= 2'd0;\n"
    "  endcase\n end\n"
    " always @(posedge clk) begin\n"
    "  case (mode)\n"
    "   2'd0: data_out <= din;\n   2'd1: data_out <= ~din;\n"
    "   default: data_out <= 8'd0;\n"
    "  endcase\n end\nendmodule\n")


def test_783r2_noleak_unrelated_companion_hard_blocks(tmp_path):
    # data_out free-running in every arm; `busy` is an unrelated reset-covered
    # 1-bit output, NOT set in the data_out arm → must stay block-eligible.
    assert _uninit_block_eligible(tmp_path, _R783_UNRELATED_DONE, "data_out") is True


def test_783r2_noleak_accumulator_self_feed_hard_blocks(tmp_path):
    # acc <= acc + din (self-accumulation): the X poisons every cycle → block.
    assert _uninit_block_eligible(tmp_path, _R783_ACCUM, "acc") is True


def test_783r2_noleak_case_on_input_other_block_hard_blocks(tmp_path):
    # data_out written in a case keyed on INPUT `mode`, in a DIFFERENT block from
    # the reset-covered state FSM → no proven control relationship → block.
    assert _uninit_block_eligible(tmp_path, _R783_CASE_ON_INPUT, "data_out") is True


def test_783r2_legit_valid_gated_still_advisory(tmp_path):
    # the canonical valid-gated terminal output (companion `done` set in the SAME
    # DONE arm) must STILL downgrade to advisory.
    src = (
        "module srt(input clk, input rst_n, input [7:0] din,\n"
        " output reg [7:0] out_data, output reg done);\n"
        " reg [1:0] state;\n"
        " always @(posedge clk or negedge rst_n) begin\n"
        "  if (!rst_n) begin state <= 2'd0; done <= 1'b0; end\n"
        "  else case (state)\n"
        "   2'd0: begin state <= 2'd1; done <= 1'b0; end\n"
        "   2'd1: state <= 2'd2;\n"
        "   2'd2: begin out_data <= din; done <= 1'b1; state <= 2'd0; end\n"
        "  endcase\n end\nendmodule\n")
    assert _uninit_block_eligible(tmp_path, src, "out_data") is False
