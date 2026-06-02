#!/usr/bin/env python3
"""Tests for bram_init_file_actually_loaded_check.py — Wave 16 Gate 1."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "bram_init_file_actually_loaded_check.py"
)


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def _make_project(tmp_path: Path,
                  rtl_files: dict | None = None,
                  fit_summary: str | None = None,
                  map_rpt: str | None = None,
                  qsf: str | None = None,
                  waivers: dict | None = None) -> Path:
    proj = tmp_path
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "fpga").mkdir(parents=True, exist_ok=True)
    if rtl_files:
        for name, body in rtl_files.items():
            (proj / "phase2" / "stage1" / "rtl" / name).write_text(body)
    if fit_summary is not None:
        (proj / "phase2" / "stage1" / "fpga" / "out.fit.summary").write_text(fit_summary)
    if map_rpt is not None:
        (proj / "phase2" / "stage1" / "fpga" / "out.map.rpt").write_text(map_rpt)
    if qsf is not None:
        (proj / "phase2" / "stage1" / "fpga" / "out.qsf").write_text(qsf)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def test_proper_readmemh_pass(tmp_path):
    """RTL has $readmemh, fit.summary shows >0 memory bits → PASS."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("rom.hex", mem);
  always @(posedge clk) q <= mem[addr];
endmodule
"""
        },
        fit_summary="Total memory bits : 1024 / 1,677,312 ( 0 % )\n",
        map_rpt="; clean compilation ;\n",
        qsf="set_global_assignment -name SEARCH_PATH ../rtl\n",
    )
    # Stage hex file under rtl/ so SEARCH_PATH covers it
    (proj / "phase2" / "stage1" / "rtl" / "rom.hex").write_text("00\n")
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_ram_init_file_max10_fail(tmp_path):
    """RTL has (* ram_init_file *), fit.summary 0 memory bits, map.rpt has
    'MIF is not supported' → FAIL with verbatim warning."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "otp.sv": """\
module otp(input clk, input [6:0] addr, output reg [7:0] q);
  (* ram_init_file = "apple.mif" *)
  reg [7:0] mem [0:127];
  always @(posedge clk) q <= mem[addr];
endmodule
"""
        },
        fit_summary="Total memory bits : 0 / 1,677,312 ( 0 % )\n",
        map_rpt=(
            'Info (276014): Found 1 instances of uninferred RAM logic\n'
            '    Info (276013): RAM logic "otp:u_otp|mem" is uninferred '
            'because MIF is not supported for the selected family File: '
            'rtl/otp.sv Line: 3\n'
        ),
        qsf="set_global_assignment -name FAMILY \"MAX 10\"\n",
    )
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    # Wave 20 (v0.119.52) renamed the failure label to make the
    # silicon-failure mode explicit. Old: BRAM_INIT_NOT_LOADED.
    assert "OTP_NOT_LOADED_ON_FPGA" in r.stdout
    assert "MIF is not supported" in r.stdout
    assert "Total memory bits: 0" in r.stdout


def test_search_path_missing_fail(tmp_path):
    """RTL $readmemh references X.hex but QSF has no SEARCH_PATH covering
    its directory → FAIL."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("missing.hex", mem);
  always @(posedge clk) q <= mem[addr];
endmodule
"""
        },
        # fit.summary OK but file is unreachable
        fit_summary="Total memory bits : 1024 / 1,677,312\n",
        map_rpt="; clean ;\n",
        qsf="set_global_assignment -name SEARCH_PATH ../somewhere_else\n",
    )
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    assert "SEARCH_PATH" in r.stdout or "missing.hex" in r.stdout


def test_no_quartus_output_warn(tmp_path):
    """RTL has BRAM init but no fit.summary / map.rpt → WARN, exit 0."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("rom.hex", mem);
endmodule
"""
        },
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "WARN" in r.stdout


def test_no_bram_skip(tmp_path):
    """Project has no BRAM init declaration → SKIP."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "comb.v": "module comb(input a, output b); assign b = ~a; endmodule\n",
        },
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Explicit waiver silences the FAIL → PASS_WITH_WAIVER."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "otp.sv": """\
module otp(input clk, input [6:0] addr, output reg [7:0] q);
  (* ram_init_file = "apple.mif" *)
  reg [7:0] mem [0:127];
  always @(posedge clk) q <= mem[addr];
endmodule
"""
        },
        fit_summary="Total memory bits : 0 / 1,677,312\n",
        map_rpt=("Info (276013): RAM logic \"otp:u|mem\" is uninferred "
                 "because MIF is not supported for the selected family\n"),
        qsf="",
        waivers={
            "bram_init_runtime_loaded_intentional": (
                "External SPI loader populates ROM at boot — verified by "
                "lab-cal procedure step 4.2"
            )
        },
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


# -- Wave 20 (v0.119.52) — case-statement LUT-style ROM detection ---------
#
# 25th attempt removed (* ram_init_file *) AND $readmemh, replacing with
# a `case (addr)` LUT. Quartus STILL emitted the `MIF not supported`
# warning + Total memory bits: 0. Wave 20 widens the gate so it FAILs
# whenever the verbatim warning is present AND the project has an OTP-
# named module (even without explicit init declarations).

def test_case_statement_rom_max10_warning_fails(tmp_path):
    """v0.119.52 25th-attempt RTL pattern: case-statement LUT ROM in
    `otp_mem.sv`, no $readmemh, no ram_init_file. Quartus map.rpt has
    the MIF-not-supported warning. Must FAIL (was previously SKIP)."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "otp_mem.sv": """\
module otp_mem(input clk, input [6:0] addr, output reg [7:0] dout);
  reg [7:0] mem [0:127];
  always @(posedge clk) begin
    case (addr)
      7'd0: dout <= 8'h10;
      default: dout <= 8'h00;
    endcase
  end
endmodule
"""
        },
        fit_summary="Total memory bits : 0 / 1,677,312\n",
        map_rpt=(
            "Info (276013): RAM logic \"otp_mem:u_otp|Ram0\" is uninferred "
            "because MIF is not supported for the selected family "
            "File: /tmp/otp_mem.sv Line: 21\n"
        ),
        qsf="set_global_assignment -name FAMILY \"MAX 10\"\n",
    )
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    assert "OTP_NOT_LOADED_ON_FPGA" in r.stdout
    assert "altsyncram" in r.stdout


def test_total_memory_bits_zero_on_rom_module_fails(tmp_path):
    """Wave 20: even without an explicit init declaration, when a
    project has a ROM-named module and Total memory bits=0, FAIL."""
    proj = _make_project(
        tmp_path,
        rtl_files={
            "rom_lookup.v": """\
module rom_lookup(input clk, input [6:0] addr, output reg [7:0] dout);
  reg [7:0] mem [0:127];
  always @(posedge clk) dout <= mem[addr];
endmodule
"""
        },
        fit_summary="Total memory bits : 0 / 1,677,312\n",
    )
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    assert "OTP_NOT_LOADED_ON_FPGA" in r.stdout
