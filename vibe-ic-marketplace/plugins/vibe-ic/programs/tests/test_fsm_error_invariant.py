"""Unit tests for fsm_error_invariant.py."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'fsm_error_invariant.py'
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import fsm_error_invariant as fei  # noqa: E402


def run_cli(tmp_path, sv):
    f = tmp_path / 't.sv'
    f.write_text(sv)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json',
         str(tmp_path / 'f.json'), str(f)],
        capture_output=True, text=True)
    findings = json.loads((tmp_path / 'f.json').read_text())
    return res, findings


def test_detects_error_in_case_branch(tmp_path):
    sv = """
module m(input clk, input rst_n, output reg rx_error, output reg [2:0] state);
    always @(posedge clk) begin
        if (!rst_n) begin
            rx_error <= 1'b0;
        end else begin
            case (state)
                3'd0: ;
                3'd1: begin
                    rx_error <= 1'b1;     // flagged
                end
                default: ;
            endcase
        end
    end
endmodule
"""
    _, findings = run_cli(tmp_path, sv)
    assert any(f['signal'] == 'rx_error' for f in findings)


def test_reset_clause_not_flagged(tmp_path):
    """Assignment of error=0 inside reset should not be flagged."""
    sv = """
module m(input clk, input rst_n, output reg err);
    always @(posedge clk) begin
        if (!rst_n) begin
            err <= 1'b1;    // this is reset init, heuristic skips
        end
    end
endmodule
"""
    _, findings = run_cli(tmp_path, sv)
    # Our heuristic says: if `if (!rst_n)` appears in recent context, skip.
    # Because this is literally in the reset branch, it should be ignored.
    assert all(f['signal'] != 'err' for f in findings)


def test_normal_signal_not_flagged(tmp_path):
    """Signals without error/err/fail/abort/timeout/reject/invalid in the name
    should never trigger."""
    sv = """
module m(input clk, output reg ready);
    always @(posedge clk) begin
        case (1'b0)
            1'b0: ready <= 1'b1;
        endcase
    end
endmodule
"""
    _, findings = run_cli(tmp_path, sv)
    assert findings == []


def test_multiple_error_aliases_all_caught(tmp_path):
    """Check various error-name synonyms."""
    sv = """
module m(input clk);
    reg timeout_flag, abort_sig, crc_fail, invalid_cmd;
    always @(posedge clk) begin
        case (1'b0)
            1'b0: begin
                timeout_flag <= 1'b1;
                abort_sig    <= 1'b1;
                crc_fail     <= 1'b1;
                invalid_cmd  <= 1'b1;
            end
        endcase
    end
endmodule
"""
    _, findings = run_cli(tmp_path, sv)
    sigs = {f['signal'] for f in findings}
    # All four error-synonym signals should be flagged
    assert 'timeout_flag' in sigs
    assert 'abort_sig' in sigs
    assert 'crc_fail' in sigs
    assert 'invalid_cmd' in sigs


def test_exit_code_zero_when_clean(tmp_path):
    sv = "module m; endmodule\n"
    res, findings = run_cli(tmp_path, sv)
    assert res.returncode == 0
    assert findings == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
