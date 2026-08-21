#!/usr/bin/env python3
"""Tests for nba_shift_register_same_cycle_read_check.py (Wave 12)."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "nba_shift_register_same_cycle_read_check.py")


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
    for name, body in rtl_files.items():
        (rtl / name).write_text(body)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


PATTERN_A = """
module tx_phy(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] tx_byte,
    output reg out
);
    reg [7:0] tx_sr;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            tx_sr <= 8'd0;
            out   <= 1'b0;
        end else begin
            out   <= tx_sr[1];
            tx_sr <= tx_sr >> 1;
        end
    end
endmodule
"""


PATTERN_B = """
module tx_phy(
    input  wire clk,
    output wire next_bit,
    output reg  out
);
    reg [7:0] tx_sr;
    assign next_bit = tx_sr[1];
    always_ff @(posedge clk) begin
        tx_sr <= tx_sr >> 1;
    end
endmodule
"""


PATTERN_C = """
module tx_phy(
    input  wire clk,
    output reg  out
);
    reg [7:0] tx_sr;
    always_ff @(posedge clk) begin
        out   <= tx_sr[0];
        tx_sr <= tx_sr >> 1;
    end
endmodule
"""


PATTERN_D = """
module tx_phy(
    input  wire clk,
    output reg  out
);
    reg [7:0] tx_sr;
    always_ff @(posedge clk) begin
        // intentional 1-bit look-ahead pipeline below
        tx_sr <= {1'b0, tx_sr[7:1]};
        out   <= tx_sr[1];
    end
endmodule
"""


NO_SHIFT = """
module simple(input wire clk, input wire d, output reg q);
    always_ff @(posedge clk) q <= d;
endmodule
"""


def test_pattern_a_fail(tmp_path):
    proj = _proj(tmp_path, {"tx_phy.v": PATTERN_A})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NBA_SHIFT_REG_SAME_CYCLE_READ" in r.stdout
    assert "tx_phy.v" in r.stdout
    assert "tx_sr" in r.stdout


def test_pattern_b_fail(tmp_path):
    proj = _proj(tmp_path, {"tx_phy.v": PATTERN_B})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NBA_SHIFT_REG_COMB_READ" in r.stdout


def test_pattern_c_pass(tmp_path):
    proj = _proj(tmp_path, {"tx_phy.v": PATTERN_C})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_pattern_d_warn(tmp_path):
    proj = _proj(tmp_path, {"tx_phy.v": PATTERN_D})
    r = _run(proj)
    # Concat shift -> WARN (exit 0)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stdout or "PASS" in r.stdout


def test_with_waiver(tmp_path):
    proj = _proj(
        tmp_path,
        {"tx_phy.v": PATTERN_A},
        waivers={
            "nba_shift_register_intentional": (
                "Intentional pipeline — downstream consumer "
                "expects post-shift value with explicit 1-cycle "
                "delay; covered by formal property in formal/."
            )
        },
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIVER" in r.stdout


def test_no_shift_register(tmp_path):
    proj = _proj(tmp_path, {"simple.v": NO_SHIFT})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_SKIP" in r.stdout or "PASS" in r.stdout


def test_help_works():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0


# NOTE: the former `test_v0119_43_real_rtl_caught` demo test was removed — it
# was pinned to an external benchmark dir (1st_benchmark_benchmark_a/
# phase2_v0119.43-vendor) absent from the repo (so it permanently skipped), and
# the same-cycle-read detection it demonstrated is already covered by the inline
# pattern tests above (test_pattern_a_fail/_b_fail catch the bug; _c_pass/_d_warn
# / _with_waiver / _no_shift_register cover the clean and waiver paths).
