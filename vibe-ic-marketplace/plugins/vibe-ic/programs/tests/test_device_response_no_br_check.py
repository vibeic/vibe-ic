"""Unit tests for device_response_no_br_check.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "device_response_no_br_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import device_response_no_br_check as chk  # noqa: E402


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_bare_br_transition_fails(tmp_path):
    content = """\
module tx_phy (input clk);
    reg [3:0] st;
    localparam ST_IDLE = 4'd0, ST_START = 4'd1, ST_BR_LOW = 4'd2;
    always @(posedge clk) begin
        case (st)
            ST_IDLE: st <= ST_START;
            ST_START: st <= ST_BR_LOW;
        endcase
    end
endmodule
"""
    p = _write(tmp_path, "tx_phy.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert errors, f"Expected FAIL; got {findings}"


def test_br_guarded_by_tx_send_br_passes(tmp_path):
    content = """\
module tx_phy (input clk, input tx_send_br);
    reg [3:0] st;
    localparam ST_IDLE = 4'd0, ST_START = 4'd1, ST_BR_LOW = 4'd2;
    always @(posedge clk) begin
        case (st)
            ST_IDLE: if (tx_send_br) st <= ST_BR_LOW;
                     else            st <= ST_START;
        endcase
    end
endmodule
"""
    p = _write(tmp_path, "tx_phy.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors


def test_non_tx_phy_file_ignored(tmp_path):
    content = """\
module receiver (input clk);
    reg [3:0] st;
    localparam ST_BR_LOW = 4'd2;
    always @(posedge clk) st <= ST_BR_LOW;
endmodule
"""
    p = _write(tmp_path, "rx_phy.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors


def test_no_br_states_passes(tmp_path):
    content = """\
module tx_phy (input clk);
    reg [3:0] st;
    localparam ST_IDLE = 4'd0, ST_BIT_LOW = 4'd1, ST_BIT_HIGH = 4'd2;
    always @(posedge clk) begin
        case (st)
            ST_IDLE: st <= ST_BIT_LOW;
            ST_BIT_LOW: st <= ST_BIT_HIGH;
        endcase
    end
endmodule
"""
    p = _write(tmp_path, "tx_phy.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors
