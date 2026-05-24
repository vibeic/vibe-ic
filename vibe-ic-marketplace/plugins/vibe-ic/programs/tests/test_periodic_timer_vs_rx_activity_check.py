"""Tests for periodic_timer_vs_rx_activity_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "periodic_timer_vs_rx_activity_check.py"


def _run(tmp_path, src, name="dut.v"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(src))
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(p), "--json"],
        capture_output=True, text=True,
    )
    return r.returncode, json.loads(r.stdout) if r.stdout else {}


def test_v068_shape_flagged(tmp_path):
    """wake_ctrl w/o any RX-guarded reset — flagged."""
    src = """
    module wake_ctrl(input clk, input rstn, input woken_i,
                     output reg ito_expired_o, output reg frozen_o);
        reg [18:0] cnt;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                cnt <= 19'd0;
                ito_expired_o <= 1'b0;
                frozen_o <= 1'b0;
            end else begin
                ito_expired_o <= 1'b0;
                if (woken_i) frozen_o <= 1'b1;
                if (!frozen_o && !woken_i) begin
                    if (cnt == 19'd249999) begin
                        cnt <= 19'd0;
                        ito_expired_o <= 1'b1;
                    end else cnt <= cnt + 19'd1;
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1
    assert out["verdict"] == "FAIL"
    rules = [f["rule"] for f in out["findings"]]
    assert "periodic_timer_no_rx_reset" in rules


def test_with_bus_active_reset_passes(tmp_path):
    """wake_ctrl with explicit `if (bus_active_i) cnt <= 0;` — passes."""
    src = """
    module wake_ctrl(input clk, input rstn, input woken_i,
                     input bus_active_i,
                     output reg ito_expired_o, output reg frozen_o);
        reg [18:0] cnt;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) begin
                cnt <= 19'd0;
            end else begin
                ito_expired_o <= 1'b0;
                if (woken_i) frozen_o <= 1'b1;
                if (!frozen_o && !woken_i) begin
                    if (bus_active_i) cnt <= 19'd0;
                    else if (cnt == 19'd249999) begin
                        cnt <= 19'd0;
                        ito_expired_o <= 1'b1;
                    end else cnt <= cnt + 19'd1;
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_v052_shape_with_cmd_valid_passes(tmp_path):
    """v052 idiom: `if (cmd_valid) cnt <= 0;` at top of block."""
    src = """
    module wake_ctrl(input clk, input porb, input cmd_valid,
                     input [7:0] cmd_op, input awake,
                     output reg wake_req);
        reg [23:0] cnt;
        always @(posedge clk or negedge porb) begin
            if (!porb) begin
                cnt <= 24'd0;
                wake_req <= 1'b0;
            end else begin
                wake_req <= 1'b0;
                if (cmd_valid) begin
                    cnt <= 24'd0;
                end else if (awake) cnt <= 24'd0;
                else begin
                    if (cnt == 24'd24999) begin
                        wake_req <= 1'b1;
                        cnt <= 24'd0;
                    end else cnt <= cnt + 24'd1;
                end
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_silence_comment(tmp_path):
    """Module with non-bus counter can silence the gate."""
    src = """
    module dut(input clk, input rstn, output reg tick);
        reg [15:0] cnt;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) cnt <= 0;
            else cnt <= cnt + 1; // periodic-timer-rx-reset-ok
            tick <= (cnt == 16'hFFFF);
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_non_counter_reg_not_flagged(tmp_path):
    """NBA-increment on a reg WITHOUT timer/counter hint name → not flagged."""
    src = """
    module dut(input clk, input rstn, input bit_valid_i, input [7:0] data_i,
               output reg [7:0] latch);
        reg [7:0] acc;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) acc <= 8'd0;
            else if (bit_valid_i) acc <= acc + data_i;
            latch <= acc;
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    # `acc` is NOT obviously a timer — gate should NOT warn.
    assert rc == 0


def test_generic_keepalive_pattern(tmp_path):
    """I2C-slave-style keepalive counter reset on SCL activity."""
    src = """
    module keepalive(input clk, input rstn, input sda_rx, output reg pulse);
        reg [15:0] hb_cnt;
        always @(posedge clk or negedge rstn) begin
            if (!rstn) hb_cnt <= 16'd0;
            else if (sda_rx) hb_cnt <= 16'd0;
            else if (hb_cnt == 16'd50000) begin
                pulse <= 1'b1;
                hb_cnt <= 16'd0;
            end else hb_cnt <= hb_cnt + 16'd1;
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_missing_file(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path / "nope.v")],
        capture_output=True)
    assert r.returncode == 2


def test_empty_dir(tmp_path):
    (tmp_path / "readme.md").write_text("")
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path)],
        capture_output=True)
    assert r.returncode == 2
