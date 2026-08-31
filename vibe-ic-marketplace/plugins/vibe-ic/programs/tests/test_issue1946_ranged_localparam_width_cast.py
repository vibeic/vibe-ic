#!/usr/bin/env python3
"""Issue #1946: make ranged-localparam truncation explicit and value-identical."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"
SIM_IMAGE = "cvdp-sim-oss:v110"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROG), *args],
        capture_output=True,
        text=True,
        check=False,
    )


_TARGETS = """\
module ranged_constants #(
  parameter integer DOOR_OPEN_CYCLES = 100,
  parameter integer N = 10,
  parameter integer CNT_W = $clog2(DOOR_OPEN_CYCLES + 1),
  parameter integer VALUE = 511
) (
  output wire [CNT_W-1:0] door_open_cycles_c,
  output wire [$clog2(N)-1:0] top_floor,
  output wire [7:0] literal_range_c
);
  localparam [CNT_W-1:0] DOOR_OPEN_CYCLES_C = DOOR_OPEN_CYCLES;
  localparam [$clog2(N)-1:0] TOP_FLOOR = N - 1;
  localparam [15:8] LITERAL_RANGE_C = VALUE;
  assign door_open_cycles_c = DOOR_OPEN_CYCLES_C;
  assign top_floor = TOP_FLOOR;
  assign literal_range_c = LITERAL_RANGE_C;
endmodule
"""


def test_issue1946_casts_symbolic_ranges_and_is_idempotent(tmp_path: Path) -> None:
    rtl = tmp_path / "ranged_constants.sv"
    rtl.write_text(_TARGETS)

    first = _run(["--fix", str(rtl)])
    assert first.returncode == 0, first.stderr
    patched = rtl.read_text()
    assert "DOOR_OPEN_CYCLES_C = CNT_W'(DOOR_OPEN_CYCLES);" in patched
    assert "TOP_FLOOR = $clog2(N)'(N - 1);" in patched
    assert "LITERAL_RANGE_C = 8'(VALUE);" in patched

    second = _run(["--fix", str(rtl)])
    assert second.returncode == 0, second.stderr
    assert rtl.read_text() == patched
    assert "inserted 0 value-identical width cast(s)" in second.stdout


def test_issue1946_finding_clears_after_fix(tmp_path: Path) -> None:
    rtl = tmp_path / "ranged_constants.sv"
    rtl.write_text(_TARGETS)
    before = _run(["--severity", "INFO", str(rtl)])
    assert before.stdout.count("width-trunc-localparam") == 3
    fixed = _run(["--fix", str(rtl)])
    assert fixed.returncode == 0, fixed.stderr
    after = _run(["--severity", "INFO", str(rtl)])
    assert "width-trunc-localparam" not in after.stdout


def test_issue1946_parameter_override_still_compiles(tmp_path: Path) -> None:
    rtl = tmp_path / "ranged_constants.sv"
    rtl.write_text(_TARGETS)
    fixed = _run(["--fix", str(rtl)])
    assert fixed.returncode == 0, fixed.stderr

    tb = tmp_path / "tb.sv"
    tb.write_text(
        "module tb;\n"
        "  wire [8:0] door_open_cycles_c; wire [4:0] top_floor;\n"
        "  wire [7:0] literal_range_c;\n"
        "  ranged_constants #(.DOOR_OPEN_CYCLES(257), .N(17), .VALUE(1023)) dut(.*);\n"
        "  initial begin #1;\n"
        "    if (door_open_cycles_c !== 9'd257 || top_floor !== 5'd16 ||\n"
        "        literal_range_c !== 8'hff) $fatal(1, \"override mismatch\");\n"
        "    $display(\"OVERRIDE_PASS\");\n"
        "  end\n"
        "endmodule\n"
    )
    sim_out = tmp_path / "sim.vvp"
    docker = shutil.which("docker")
    image_available = False
    if docker:
        image = subprocess.run(
            [docker, "image", "inspect", SIM_IMAGE],
            capture_output=True,
            text=True,
            check=False,
        )
        image_available = image.returncode == 0

    # This issue's acceptance toolchain is the pinned CVDP scorer image.  Prefer
    # it over an arbitrary host Icarus/vvp pair so the test has the same result
    # on every arm where that image is available.
    if image_available:
        cmd = [
            docker, "run", "--rm", "-v", f"{tmp_path}:/work", "-w", "/work",
            SIM_IMAGE, "iverilog", "-g2012", "-s", "tb", "-o", sim_out.name,
            rtl.name, tb.name,
        ]
        run_cmd = [
            docker, "run", "--rm", "-v", f"{tmp_path}:/work", "-w", "/work",
            SIM_IMAGE, "vvp", sim_out.name,
        ]
    else:
        host_iverilog = shutil.which("iverilog")
        if not host_iverilog:
            pytest.skip(f"neither host iverilog nor {SIM_IMAGE} is available")
        cmd = [host_iverilog, "-g2012", "-s", "tb", "-o", str(sim_out),
               str(rtl), str(tb)]
        host_vvp = shutil.which("vvp")
        run_cmd = [host_vvp, str(sim_out)] if host_vvp else None
    compiled = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    if run_cmd:
        simulated = subprocess.run(run_cmd, capture_output=True, text=True, check=False)
        assert simulated.returncode == 0, simulated.stdout + simulated.stderr
        assert "OVERRIDE_PASS" in simulated.stdout


def test_issue1946_skips_out_of_scope_declarations(tmp_path: Path) -> None:
    rtl = tmp_path / "excluded.sv"
    rtl.write_text(
        "module excluded #(parameter integer W=8, parameter integer VALUE=255) ();\n"
        "  localparam signed [W-1:0] SIGNED_C = VALUE;\n"
        "  localparam SCALAR_C = VALUE;\n"
        "  localparam [W-1:0] FIRST_C = VALUE, SECOND_C = VALUE - 1;\n"
        "  localparam [W-1:0] CAST_C = W'(VALUE);\n"
        "  localparam [W-1:0] SIZED_C = 8'd3;\n"
        "  localparam [W-1:0] CONCAT_C = {W{1'b0}};\n"
        "  localparam [W-1:0] SLICE_C = VALUE[W-1:0];\n"
        "  localparam [W-2:0] NONCANONICAL_C = VALUE;\n"
        "endmodule\n"
    )
    original = rtl.read_text()
    fixed = _run(["--fix", str(rtl)])
    assert fixed.returncode == 0, fixed.stderr
    assert rtl.read_text() == original
