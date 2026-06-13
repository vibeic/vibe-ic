"""Unit tests for timer_freeze_after_state_check.py.

Ground-truth specimen: v052 wake_ctrl.v, where a tITO idle-timeout
counter kept incrementing after `awake=1` because the increment was
inside a nested `else` branch with no awake-gate. Bug caught only on
real hardware (5 ms wake pulses on ID_BUS after 0x74 wake), not in
sim. v0.64 ships this checker so future runs catch the pattern
statically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "timer_freeze_after_state_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import timer_freeze_after_state_check as chk  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: the v052 wake_ctrl.v BUGGY shape (the original specimen)
# ---------------------------------------------------------------------------
_BUGGY_WAKE_CTRL = """\
module wake_ctrl (
    input  wire        clk,
    input  wire        porb,
    input  wire        cmd_valid,
    input  wire [7:0]  cmd_op,
    input  wire        awake,
    output reg         wake_req
);
    reg [23:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) begin
            cnt       <= 24'd0;
            wake_req  <= 1'b0;
        end else begin
            wake_req <= 1'b0;
            if (cmd_valid) begin
                cnt <= 24'd0;
                if (!awake && cmd_op != 8'h74) begin
                    wake_req <= 1'b1;
                end
            end else begin
                if (cnt == 24'd25000) begin
                    wake_req <= 1'b1;
                    cnt      <= 24'd0;
                end else cnt <= cnt + 24'd1;
            end
        end
    end
endmodule
"""

# Fixed version — the user's v052 fix (added the `else if (awake)` freeze branch).
_FIXED_WAKE_CTRL = """\
module wake_ctrl (
    input  wire        clk,
    input  wire        porb,
    input  wire        cmd_valid,
    input  wire [7:0]  cmd_op,
    input  wire        awake,
    output reg         wake_req
);
    reg [23:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) begin
            cnt       <= 24'd0;
            wake_req  <= 1'b0;
        end else begin
            wake_req <= 1'b0;
            if (cmd_valid) begin
                cnt <= 24'd0;
                if (!awake && cmd_op != 8'h74) begin
                    wake_req <= 1'b1;
                end
            end else if (awake) begin
                cnt <= 24'd0;   // freeze once awake
            end else begin
                if (cnt == 24'd25000) begin
                    wake_req <= 1'b1;
                    cnt      <= 24'd0;
                end else cnt <= cnt + 24'd1;
            end
        end
    end
endmodule
"""


# ---------------------------------------------------------------------------
# Bug-detection: the headline test
# ---------------------------------------------------------------------------
def test_buggy_wake_ctrl_is_flagged(tmp_path):
    """v052 wake_ctrl.v shape — must FLAG."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_ctrl.v").write_text(_BUGGY_WAKE_CTRL)
    findings = chk.audit(rtl)
    assert len(findings) == 1
    f = findings[0]
    assert f.module == "wake_ctrl"
    assert f.counter == "cnt"
    assert f.state_bit == "awake"
    assert "freeze" in f.reason.lower()


def test_fixed_wake_ctrl_passes(tmp_path):
    """User's v0.52.x fix — must NOT flag."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_ctrl.v").write_text(_FIXED_WAKE_CTRL)
    findings = chk.audit(rtl)
    assert findings == []


# ---------------------------------------------------------------------------
# False-positive guards (lessons from real-RTL development)
# ---------------------------------------------------------------------------
def test_state_bit_as_output_does_not_flag(tmp_path):
    """If the matched token is declared `output reg <token>`, the module
    OWNS the state bit (it's the producer). The freeze-after-state rule
    only applies when the state is an INPUT we react to. Specimen: v052
    mac.v has `output reg awake` and a `tsrs_cnt+1` increment — must NOT
    flag (mac.v is the awake producer, not consumer)."""
    src = """\
module producer (
    input  wire clk,
    input  wire porb,
    output reg  awake,
    output reg [15:0] tsrs_cnt
);
    always @(posedge clk or negedge porb) begin
        if (!porb) begin
            awake <= 1'b0;
            tsrs_cnt <= 16'd0;
        end else begin
            tsrs_cnt <= tsrs_cnt + 16'd1;
        end
    end
endmodule
"""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "producer.v").write_text(src)
    assert chk.audit(rtl) == []


def test_internal_reg_state_does_not_flag(tmp_path):
    """If the matched token is an internal `reg`, this module is its own
    state machine and naturally freezes the counter when it deasserts the
    state. Specimen: v052 gen_wake.v has `reg active` and `cnt+1` inside
    the `else` of `if (!active)` — must NOT flag."""
    src = """\
module gen_wake (
    input  wire clk,
    input  wire porb,
    input  wire req
);
    reg active;
    reg [7:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) begin
            active <= 1'b0; cnt <= 8'd0;
        end else begin
            if (!active) begin
                if (req) begin active <= 1'b1; cnt <= 8'd0; end
            end else begin
                if (cnt == 8'd100) active <= 1'b0;
                else cnt <= cnt + 8'd1;
            end
        end
    end
endmodule
"""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "gen_wake.v").write_text(src)
    assert chk.audit(rtl) == []


def test_module_without_state_input_skipped(tmp_path):
    """Module that doesn't import any state-bit input is out of scope."""
    src = """\
module simple_counter (input wire clk, input wire porb, output reg [7:0] cnt);
    always @(posedge clk or negedge porb) begin
        if (!porb) cnt <= 8'd0;
        else cnt <= cnt + 8'd1;
    end
endmodule
"""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "simple.v").write_text(src)
    assert chk.audit(rtl) == []


def test_whitelist_comment_suppresses_flag(tmp_path):
    """A line ending with the whitelist comment is intentionally skipped."""
    src = """\
module wdog (
    input wire clk, input wire porb, input wire awake
);
    reg [7:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) cnt <= 8'd0;
        else cnt <= cnt + 8'd1;  // timer_freeze_check: ok-unconditional
    end
endmodule
"""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wdog.v").write_text(src)
    assert chk.audit(rtl) == []


def test_multiple_state_token_synonyms_recognised(tmp_path):
    """`enable`/`active`/`started` (any in _STATE_TOKENS) all work."""
    for tok in ("enable", "active", "started", "running"):
        src = f"""\
module m (
    input wire clk, input wire porb, input wire {tok}
);
    reg [7:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) cnt <= 8'd0;
        else cnt <= cnt + 8'd1;
    end
endmodule
"""
        rtl = tmp_path / f"rtl_{tok}"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "m.v").write_text(src)
        findings = chk.audit(rtl)
        assert len(findings) == 1, (
            f"state token '{tok}' should trigger the rule; got {findings}"
        )
        assert findings[0].state_bit.lower() == tok


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------
def test_cli_help_works():
    """argparse `--help` raises SystemExit(0); confirm that path."""
    with pytest.raises(SystemExit) as e:
        chk.main(["--help"])
    assert e.value.code == 0


def test_cli_exit_code_pass(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "x.v").write_text(_FIXED_WAKE_CTRL)
    rc = chk.main(["--rtl-dir", str(rtl)])
    assert rc == 0


def test_cli_exit_code_fail(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "x.v").write_text(_BUGGY_WAKE_CTRL)
    rc = chk.main(["--rtl-dir", str(rtl)])
    assert rc == 1


def test_cli_writes_json_report(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "x.v").write_text(_BUGGY_WAKE_CTRL)
    out = tmp_path / "report.json"
    rc = chk.main(["--rtl-dir", str(rtl), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["summary"]["pass"] is False
    assert data["summary"]["findings_count"] == 1


def test_cli_invalid_rtl_dir_returns_2(tmp_path):
    rc = chk.main(["--rtl-dir", str(tmp_path / "does_not_exist")])
    assert rc == 2
