#!/usr/bin/env python3
"""Tests for crc_compute_done_before_tx_start_check.py (Wave 12)."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "crc_compute_done_before_tx_start_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _proj(tmp_path: Path, rtl_files: dict[str, str],
          waivers: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    for n, b in rtl_files.items():
        (rtl / n).write_text(b)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


CRC_WITH_DONE = """
module crc_engine(
    input  wire clk,
    input  wire rst_n,
    input  wire feed_vld,
    input  wire [7:0] feed_byte,
    output reg  crc_done,
    output reg  [7:0] crc_out
);
    always_ff @(posedge clk) begin
        crc_out  <= 8'h00;
        crc_done <= feed_vld;
    end
endmodule
"""


CRC_NO_DONE = """
module crc_engine(
    input  wire clk,
    input  wire feed_vld,
    input  wire [7:0] feed_byte,
    output reg  [7:0] crc_out
);
    always_ff @(posedge clk) crc_out <= 8'h00;
endmodule
"""


FSM_WITH_DONE_CHECK = """
module main_fsm(
    input  wire clk,
    input  wire rst_n,
    input  wire crc_done,
    output reg  [7:0] state
);
    parameter ST_IDLE = 8'h00;
    parameter ST_TX   = 8'h10;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= ST_IDLE;
        else begin
            case (state)
                ST_IDLE:
                    if (crc_done)
                        state <= ST_TX;
                default: state <= ST_IDLE;
            endcase
        end
    end
endmodule
"""


FSM_WITHOUT_DONE_CHECK = """
module main_fsm(
    input  wire clk,
    input  wire rst_n,
    input  wire start_req,
    output reg  [7:0] state
);
    parameter ST_IDLE = 8'h00;
    parameter ST_TX   = 8'h10;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= ST_IDLE;
        else begin
            case (state)
                ST_IDLE:
                    if (start_req)
                        state <= ST_TX;
                default: state <= ST_IDLE;
            endcase
        end
    end
endmodule
"""


FSM_NO_TX_STATES = """
module ctrl_fsm(
    input  wire clk,
    input  wire rst_n,
    output reg  [7:0] state
);
    parameter ST_IDLE = 8'h00;
    parameter ST_RUN  = 8'h10;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= ST_IDLE;
        else        state <= ST_RUN;
    end
endmodule
"""


def test_done_signal_in_transition_pass(tmp_path):
    proj = _proj(tmp_path, {
        "crc.v": CRC_WITH_DONE,
        "main_fsm.v": FSM_WITH_DONE_CHECK,
    })
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_no_done_check_fail(tmp_path):
    proj = _proj(tmp_path, {
        "crc.v": CRC_WITH_DONE,
        "main_fsm.v": FSM_WITHOUT_DONE_CHECK,
    })
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CRC_DONE_NOT_IN_TX_TRANSITION" in r.stdout


def test_crc_no_done_port_skip(tmp_path):
    proj = _proj(tmp_path, {
        "crc.v": CRC_NO_DONE,
        "main_fsm.v": FSM_WITHOUT_DONE_CHECK,
    })
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout or "PASS_SKIP" in r.stdout


def test_no_crc_module_skip(tmp_path):
    proj = _proj(tmp_path, {
        "main_fsm.v": FSM_WITHOUT_DONE_CHECK,
    })
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout or "PASS_SKIP" in r.stdout


def test_no_tx_states_warn(tmp_path):
    proj = _proj(tmp_path, {
        "crc.v": CRC_WITH_DONE,
        "ctrl_fsm.v": FSM_NO_TX_STATES,
    })
    r = _run(proj)
    # PASS with WARN about no TX states found
    assert r.returncode == 0, r.stdout + r.stderr


def test_with_waiver_pass(tmp_path):
    proj = _proj(
        tmp_path,
        {
            "crc.v": CRC_WITH_DONE,
            "main_fsm.v": FSM_WITHOUT_DONE_CHECK,
        },
        waivers={
            "crc_done_unnecessary_for_tx_timing": (
                "FSM allocates a fixed 16-cycle CRC compute window "
                "in ST_PRELATENCY before transitioning to ST_TX; "
                "covered by formal property crc_complete_before_tx."
            )
        },
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIVER" in r.stdout


def test_help_works():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
