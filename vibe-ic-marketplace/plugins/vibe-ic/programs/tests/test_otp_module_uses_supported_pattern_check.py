#!/usr/bin/env python3
"""Tests for otp_module_uses_supported_pattern_check.py (Wave 21,
v0.119.53)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "otp_module_uses_supported_pattern_check.py"
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


def _write_qsf(tmp_path: Path, family: str = "MAX 10",
               extra: str = "") -> None:
    fpga = tmp_path / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True, exist_ok=True)
    (fpga / "top.qsf").write_text(
        f'set_global_assignment -name FAMILY "{family}"\n'
        'set_global_assignment -name DEVICE 10M50DAF484C7G\n'
        + extra
    )


def _write_mif(tmp_path: Path, name: str = "apple.mif") -> None:
    """Place an .mif file under rtl/ so the reachability check passes."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(
        "WIDTH=8;\nDEPTH=128;\nADDRESS_RADIX=HEX;\n"
        "DATA_RADIX=HEX;\nCONTENT BEGIN\nEND;\n"
    )


def test_altsyncram_with_init_file_pass(tmp_path):
    """Wave 21: altsyncram with .init_file param + reachable .mif → PASS."""
    _write_qsf(
        tmp_path,
        "MAX 10",
        extra=(
            "set_global_assignment -name SEARCH_PATH ../rtl\n"
            "set_global_assignment -name MISC_FILE ../rtl/apple.mif\n"
        ),
    )
    _write_mif(tmp_path, "apple.mif")
    _write_rtl(
        tmp_path,
        "otp_mem.sv",
        """
module otp_mem (
    input  wire        clk,
    input  wire  [6:0] addr,
    output wire  [7:0] dout
);
  altsyncram #(
    .operation_mode("ROM"),
    .init_file("apple.mif"),
    .init_file_layout("PORT_A"),
    .lpm_type("altsyncram"),
    .width_a(8),
    .widthad_a(7),
    .numwords_a(128)
  ) u_otp (
    .clock0    (clk),
    .address_a (addr),
    .q_a       (dout)
  );
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "altsyncram" in r.stdout
    assert "Pattern A" in r.stdout


def test_altsyncram_missing_init_file_fail(tmp_path):
    """altsyncram instantiation but NO .init_file param → FAIL."""
    _write_qsf(tmp_path, "MAX 10")
    _write_rtl(
        tmp_path,
        "otp_mem.sv",
        """
module otp_mem (
    input  wire        clk,
    input  wire  [6:0] addr,
    output wire  [7:0] dout
);
  altsyncram #(
    .operation_mode("ROM"),
    .lpm_type("altsyncram"),
    .width_a(8),
    .widthad_a(7),
    .numwords_a(128)
  ) u_otp (
    .clock0    (clk),
    .address_a (addr),
    .q_a       (dout)
  );
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "ALTSYNCRAM_MISSING_INIT_FILE" in r.stdout


def test_altsyncram_init_file_unreachable_fail(tmp_path):
    """altsyncram with .init_file but the file is not reachable → FAIL."""
    _write_qsf(tmp_path, "MAX 10")  # no SEARCH_PATH/MISC_FILE, no .mif
    _write_rtl(
        tmp_path,
        "otp_mem.sv",
        """
module otp_mem (
    input  wire        clk,
    input  wire  [6:0] addr,
    output wire  [7:0] dout
);
  altsyncram #(
    .operation_mode("ROM"),
    .init_file("missing_apple.mif"),
    .lpm_type("altsyncram"),
    .width_a(8),
    .widthad_a(7),
    .numwords_a(128)
  ) u_otp (
    .clock0    (clk),
    .address_a (addr),
    .q_a       (dout)
  );
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ALTSYNCRAM_INIT_FILE_UNREACHABLE" in r.stdout


def test_vendor_ram_ip_pass(tmp_path):
    """Pattern B: vendor RAM_IP wrapper with INIT_FILE_NAME → PASS."""
    _write_qsf(tmp_path, "MAX 10")
    _write_rtl(
        tmp_path,
        "ram128x8.v",
        """
module ram128x8 (
    input  wire        clk,
    input  wire  [6:0] addr,
    output wire  [7:0] dout
);
  RAM_IP #(
    .INIT_FILE_NAME("apple.ver"),
    .INIT_FILE_FORMAT_HEX(1)
  ) u_otp (
    .clock     (clk),
    .address   (addr),
    .q         (dout)
  );
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "Pattern B" in r.stdout


def test_readmemh_only_max10_fail(tmp_path):
    """Wave 21: register-array + $readmemh only (no altsyncram, no
    vendor IP) → FAIL with Pattern A hint, even on MAX 10."""
    _write_qsf(tmp_path, "MAX 10")
    _write_rtl(
        tmp_path,
        "rom_lookup.v",
        """
module rom_lookup (
    input  wire        clk,
    input  wire  [6:0] addr,
    output reg   [7:0] dout
);
  reg [7:0] mem [0:127];
  initial $readmemh("apple.hex", mem);
  always @(posedge clk) dout <= mem[addr];
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "OTP_PATTERN_UNSUPPORTED_ON_MAX10" in r.stdout
    # Pattern A hint must be in the failure body
    assert "Pattern A" in r.stdout
    assert "altsyncram" in r.stdout


def test_three_off_pragmas_max10_fail(tmp_path):
    """Wave 21 NEGATIVE check: QSF has the 3 OFF pragmas on MAX 10 →
    FAIL with the verbatim warning."""
    _write_qsf(
        tmp_path,
        "MAX 10",
        extra=(
            "set_global_assignment -name AUTO_RAM_RECOGNITION OFF\n"
            "set_global_assignment -name AUTO_ROM_RECOGNITION OFF\n"
            "set_global_assignment -name "
            "BLOCK_RAM_TO_MLAB_CELL_CONVERSION OFF\n"
        ),
    )
    _write_rtl(
        tmp_path,
        "rom_lookup.v",
        """
module rom_lookup (
    input  wire        clk,
    input  wire  [6:0] addr,
    output reg   [7:0] dout
);
  reg [7:0] mem [0:127];
  initial $readmemh("apple.hex", mem);
  always @(posedge clk) dout <= mem[addr];
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WAVE20_WRONG_RECIPE_3_OFF_PRAGMAS_ON_MAX10" in r.stdout
    # All three forbidden pragmas should be cited.
    assert "AUTO_RAM_RECOGNITION" in r.stdout
    assert "AUTO_ROM_RECOGNITION" in r.stdout
    assert "BLOCK_RAM_TO_MLAB_CELL_CONVERSION" in r.stdout


def test_no_otp_module_skip(tmp_path):
    """No module with OTP/ROM/MEM/LUT name → SKIP."""
    _write_qsf(tmp_path, "MAX 10")
    _write_rtl(
        tmp_path,
        "alu.sv",
        """
module alu (
    input  wire [7:0] a,
    output wire [7:0] y
);
  assign y = a + 8'd1;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_non_max10_family_skip(tmp_path):
    """Cyclone V family → SKIP (gate is MAX-10 specific)."""
    _write_qsf(tmp_path, "Cyclone V")
    _write_rtl(
        tmp_path,
        "otp_mem.sv",
        """
module otp_mem (
    input  wire        clk,
    input  wire  [6:0] addr,
    output reg   [7:0] dout
);
  reg [7:0] mem [0:127];
  always @(posedge clk) dout <= mem[addr];
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Waiver absorbs the failure → PASS_WITH_WAIVER."""
    _write_qsf(tmp_path, "MAX 10")
    _write_rtl(
        tmp_path,
        "otp_mem.sv",
        """
module otp_mem (
    input  wire        clk,
    input  wire  [6:0] addr,
    output reg   [7:0] dout
);
  reg [7:0] mem [0:127];
  always @(posedge clk) begin
    case (addr)
      7'd0: dout <= 8'h10;
      7'd1: dout <= 8'h00;
      7'd2: dout <= 8'h11;
      7'd3: dout <= 8'h22;
      default: dout <= 8'h00;
    endcase
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "otp_pattern_intentional_logic_lut":
            "Tiny 4-entry decode-only LUT for board ID — fits in 6 LE,"
            " not a real OTP. lab-cal verified.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_qsf_skip(tmp_path):
    """No QSF in the project → SKIP (likely ASIC / pre-FPGA)."""
    _write_rtl(
        tmp_path,
        "otp_mem.sv",
        """
module otp_mem (input wire clk, output reg [7:0] dout);
  reg [7:0] mem [0:127];
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout
