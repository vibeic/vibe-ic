#!/usr/bin/env python3
"""Tests for crc_polyform_outputreversal_pairing_check.py (Wave 25)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "crc_polyform_outputreversal_pairing_check.py"
)


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True,
        text=True,
    )


def _write_rtl(tmp_path: Path, name: str, body: str) -> None:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_reflected_lsb_first_pass(tmp_path):
    # Reflected poly 0x8C + right-shift LFSR (LSB-first input)
    # + DIRECT output → PASS.
    _write_rtl(
        tmp_path,
        "crc8.sv",
        """
module crc8(input clk, input [7:0] byte_in, output reg [7:0] crc);
  localparam logic [7:0] CRC_POLY = 8'h8C;
  always_ff @(posedge clk) begin
    // right-shift = LSB-first feed
    if (lsb) crc <= {1'b0, crc[7:1]} ^ CRC_POLY;
    else     crc <= {1'b0, crc[7:1]};
  end
endmodule
""",
    )
    _write_rtl(
        tmp_path,
        "tx_phy.sv",
        """
module tx_phy(input [7:0] crc, output reg [7:0] tx_byte);
  always_ff @(posedge clk) tx_byte <= crc;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


def test_non_reflected_msb_first_pass(tmp_path):
    # Non-reflected poly 0x31 + left-shift LFSR (MSB-first input)
    # + DIRECT output → PASS.
    _write_rtl(
        tmp_path,
        "crc8.v",
        """
module crc8(input clk, input bit_in, output reg [7:0] crc);
  localparam [7:0] CRC8_POLY = 8'h31;
  always @(posedge clk) begin
    // left-shift = MSB-first feed
    if (bit_in ^ crc[7]) crc <= {crc[6:0], 1'b0} ^ CRC8_POLY;
    else                 crc <= {crc[6:0], 1'b0};
  end
endmodule
""",
    )
    _write_rtl(
        tmp_path,
        "mac.v",
        """
module mac(input [7:0] crc, output reg [7:0] tx_byte);
  always @(posedge clk) tx_byte <= crc;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_reflected_msb_first_fail(tmp_path):
    # Reflected poly 0x8C declared but input is MSB-first (left-shift)
    # → FAIL.
    _write_rtl(
        tmp_path,
        "crc8.sv",
        """
module crc8(input clk, output reg [7:0] crc);
  localparam logic [7:0] CRC_POLY = 8'h8C;
  always_ff @(posedge clk) begin
    // BUG: left-shift LFSR with reflected poly
    if (bit_in ^ crc[7]) crc <= {crc[6:0], 1'b0} ^ CRC_POLY;
    else                 crc <= {crc[6:0], 1'b0};
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "CRC_POLYFORM_PAIRING_MISMATCH" in r.stdout


def test_no_crc_skip(tmp_path):
    # No CRC files → SKIP.
    _write_rtl(
        tmp_path,
        "alu.sv",
        """
module alu(input wire [7:0] a, output wire [7:0] y);
  assign y = a + 1;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    # Same FAIL pattern silenced by valid waiver.
    _write_rtl(
        tmp_path,
        "crc8.sv",
        """
module crc8(input clk, output reg [7:0] crc);
  localparam logic [7:0] CRC_POLY = 8'h8C;
  always_ff @(posedge clk) begin
    if (bit_in ^ crc[7]) crc <= {crc[6:0], 1'b0} ^ CRC_POLY;
    else                 crc <= {crc[6:0], 1'b0};
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "crc_polyform_intentional_pairing":
            "Vendor uses 0x8C reflected coefficient with MSB-first "
            "feed and explicit bit-reverse on the wire load — "
            "verified equivalent to the spec.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
