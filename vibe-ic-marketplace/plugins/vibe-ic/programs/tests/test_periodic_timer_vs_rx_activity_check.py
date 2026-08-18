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


def test_clock_divider_mdc_cnt_not_flagged(tmp_path):
    """mdio mdc_cnt shape: the counter's expiry path only toggles a clock-like
    reg (`mdc <= ~mdc`) and pulses a 1-cycle tick (`mdc_tick <= 1'b1`). It does
    NOT gate a TX / output-enable / packet-send event — it is a CLOCK DIVIDER,
    not a periodic-TX wake timer. Must NOT warn."""
    src = """
    module mdio_mdc(input clk, input rst_n, output reg mdc);
        localparam [15:0] MDC_DIV = 16'd24;
        localparam S_IDLE = 2'd0;
        reg [1:0]  state;
        reg [15:0] mdc_cnt;
        reg        mdc_tick;
        always @(posedge clk) begin
            if (!rst_n) begin
                mdc_cnt  <= 16'd0;
                mdc      <= 1'b0;
                mdc_tick <= 1'b0;
            end else if (state == S_IDLE) begin
                mdc_cnt  <= 16'd0;
                mdc      <= 1'b0;
                mdc_tick <= 1'b0;
            end else if (mdc_cnt == MDC_DIV[15:0]) begin
                mdc_cnt  <= 16'd0;
                mdc      <= ~mdc;
                mdc_tick <= 1'b1;
            end else begin
                mdc_cnt  <= mdc_cnt + 16'd1;
                mdc_tick <= 1'b0;
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0, out
    assert out["verdict"] == "PASS", out


def test_pure_div_toggle_not_flagged(tmp_path):
    """Simplest register-divided clock with a prescaler `div_cnt` and a toggle
    on expiry (`clk_div <= ~clk_div`). No TX event ⇒ clock divider ⇒ no warn.
    Mirrors sdc_gen._find_register_divided_clocks form B."""
    src = """
    module clkdiv(input clk, input rst_n, output reg clk_div);
        reg [7:0] div_cnt;
        always @(posedge clk) begin
            if (!rst_n) begin
                div_cnt <= 8'd0;
                clk_div <= 1'b0;
            end else if (div_cnt == 8'd99) begin
                div_cnt <= 8'd0;
                clk_div <= ~clk_div;
            end else begin
                div_cnt <= div_cnt + 8'd1;
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0, out
    assert out["verdict"] == "PASS", out


def test_real_wake_timer_still_flagged_alongside_divider(tmp_path):
    """A genuine autonomous wake-pulse timer (expiry path drives a TX wake
    event, no RX reset) must STILL warn — even when a clock divider lives in
    the SAME file. The divider must be silent; the wake timer must not."""
    src = """
    module mixed(input clk, input rst_n, output reg mdc,
                 output reg wake_pulse_o);
        // --- clock divider: must NOT warn ---
        reg [15:0] mdc_cnt;
        reg        mdc_tick;
        always @(posedge clk) begin
            if (!rst_n) begin
                mdc_cnt  <= 16'd0;
                mdc      <= 1'b0;
                mdc_tick <= 1'b0;
            end else if (mdc_cnt == 16'd24) begin
                mdc_cnt  <= 16'd0;
                mdc      <= ~mdc;
                mdc_tick <= 1'b1;
            end else begin
                mdc_cnt  <= mdc_cnt + 16'd1;
                mdc_tick <= 1'b0;
            end
        end
        // --- real wake/keepalive timer: must STILL warn (gates a TX event,
        //     no RX-activity reset) ---
        reg [18:0] wake_cnt;
        always @(posedge clk) begin
            if (!rst_n) begin
                wake_cnt    <= 19'd0;
                wake_pulse_o <= 1'b0;
            end else begin
                wake_pulse_o <= 1'b0;
                if (wake_cnt == 19'd249999) begin
                    wake_cnt     <= 19'd0;
                    wake_pulse_o <= 1'b1;
                end else wake_cnt <= wake_cnt + 19'd1;
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1, out
    assert out["verdict"] == "FAIL", out
    flagged = {f["register"] for f in out["findings"]}
    assert "wake_cnt" in flagged, out
    assert "mdc_cnt" not in flagged, out


def test_divider_with_tx_event_still_flagged(tmp_path):
    """A counter that toggles a clock reg BUT also drives a TX event on expiry
    is NOT a pure clock divider — it must STILL warn (do-not-silence guard)."""
    src = """
    module tricky(input clk, input rst_n, output reg clk_div,
                  output reg tx_send_o);
        reg [15:0] period_cnt;
        always @(posedge clk) begin
            if (!rst_n) begin
                period_cnt <= 16'd0;
                clk_div    <= 1'b0;
                tx_send_o  <= 1'b0;
            end else begin
                tx_send_o <= 1'b0;
                if (period_cnt == 16'd5000) begin
                    period_cnt <= 16'd0;
                    clk_div    <= ~clk_div;
                    tx_send_o  <= 1'b1;
                end else period_cnt <= period_cnt + 16'd1;
            end
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 1, out
    flagged = {f["register"] for f in out["findings"]}
    assert "period_cnt" in flagged, out


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
