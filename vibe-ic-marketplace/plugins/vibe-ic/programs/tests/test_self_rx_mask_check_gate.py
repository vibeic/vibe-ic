#!/usr/bin/env python3
"""Tests for self_rx_mask_check.py"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "self_rx_mask_check.py"


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_clean_rtl(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0


def test_rx_with_oe_or_mask_passes(tmp_path):
    """Standard form: `rx_masked = id_bus_rx | id_bus_oe;` — the OR-gate
    forces RX HIGH while the chip drives, masking the self-loop."""
    (tmp_path / "core.sv").write_text("""\
module core(input id_bus_rx, output id_bus_oe);
  wire rx_masked;
  assign rx_masked = id_bus_rx | id_bus_oe;
endmodule
""")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 0, r.stdout


def test_unmasked_rx_fails(tmp_path):
    """Negative: RX directly consumed without any oe-related guard → FAIL."""
    (tmp_path / "core.sv").write_text("""\
module core(input id_bus_rx, output reg byte_done, output id_bus_oe);
  reg [7:0] shift;
  always @(posedge clk) begin
    shift <= {shift[6:0], id_bus_rx};
  end
endmodule
""")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 1, r.stdout
    assert "self_rx_not_masked" in r.stdout


def test_registered_rx_signal_detected(tmp_path):
    """v0.119.19: vendor-benchmark RTL named the registered bus signal
    `id_bus_rx_q1` (registered form, not `_rx` literal). The earlier
    name-guessing list missed it; loosened to accept `_d`/`_q`/`_q<n>`
    suffixes. Without the fix, the gate emitted `rx_signal_not_found`
    WARN and silently passed when the design actually was unmasked."""
    (tmp_path / "core.sv").write_text("""\
module core(input clk, input id_bus, output reg id_bus_oe);
  reg id_bus_q1;
  always @(posedge clk) id_bus_q1 <= id_bus;
  // Self-RX path uses id_bus_q1 directly, no mask — should FAIL.
  reg [7:0] shift;
  always @(posedge clk) shift <= {shift[6:0], id_bus_q1};
endmodule
""")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 1, r.stdout
    # v0.119.20: tighten OR-assertion — the loosened guesser is now
    # committed, so the gate MUST detect id_bus_q1 and emit the actual
    # `self_rx_not_masked` finding (not the fallback `rx_signal_not_found`).
    # Allowing either branch let the pre-fix dead-name path silently
    # satisfy the test.
    assert "self_rx_not_masked" in r.stdout, \
        f"loosened guesser must detect registered name id_bus_q1: {r.stdout}"
    assert "rx_signal_not_found" not in r.stdout, \
        f"fallback must NOT fire — guesser should resolve id_bus_q1: {r.stdout}"


def test_registered_rx_with_mask_passes(tmp_path):
    """Positive: `id_bus_q1` form with explicit mask via `~id_bus_oe`
    inside the RX consumer should PASS."""
    (tmp_path / "core.sv").write_text("""\
module core(input clk, input id_bus, output reg id_bus_oe);
  reg id_bus_q1;
  always @(posedge clk) id_bus_q1 <= id_bus;
  reg [7:0] shift;
  always @(posedge clk) begin
    if (~id_bus_oe)
        shift <= {shift[6:0], id_bus_q1};
  end
endmodule
""")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 0, r.stdout


# v0.119.28 testbench-exclusion regression matrix.
# Each subtest builds an offending RTL (`*_drive_low` without mask) at
# the given path and asserts whether the gate fires (RTL kept) or
# silently passes (path excluded).
def _bad_rtl():
    """RTL that the gate actually FAILs on: oe-style driver + unmasked
    RX consumption of the same wire. Same anti-pattern as
    `test_unmasked_rx_fails`."""
    return """\
module rx_phy(input clk, input id_bus_rx, output id_bus_oe);
  reg [7:0] shift;
  always @(posedge clk) begin
    shift <= {shift[6:0], id_bus_rx};
  end
endmodule
"""


def _make(tmp_path, rel_path):
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_bad_rtl())
    return p


def test_v028_excluded_path_verification_dir(tmp_path):
    """v0.119.28: a `verification/` directory component must be excluded."""
    _make(tmp_path, "verification/rx_phy.sv")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 0, \
        f"verification/ dir should exclude file: {r.stdout}"


def test_v028_excluded_path_sim_unit_dir(tmp_path):
    _make(tmp_path, "sim_unit/rx_phy.sv")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 0, r.stdout


def test_v028_excluded_path_sva_dir(tmp_path):
    _make(tmp_path, "sva/rx_phy.sv")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 0, r.stdout


def test_v028_excluded_path_existing_tb_dir(tmp_path):
    """Regression: pre-v0.119.28 exclusions still work."""
    _make(tmp_path, "tb/integration.sv")
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 0, r.stdout


def test_v028_real_rtl_with_tb_substring_kept(tmp_path):
    """`rxtb_decoder.v` is a real RTL file whose name happens to contain
    `tb` as a substring; it must NOT be excluded by accident."""
    p = tmp_path / "phase2" / "stage1" / "rtl" / "rxtb_decoder.v"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_bad_rtl())
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 1, \
        f"rxtb_decoder.v is RTL, must NOT be excluded: {r.stdout}"


def test_v028_verifier_module_in_rtl_dir_kept(tmp_path):
    """Sanity for the docstring caveat: a real RTL file at
    `rtl/verifier_axi.v` (substring `verif*` in NAME, not directory)
    must still be analyzed."""
    p = tmp_path / "phase2" / "stage1" / "rtl" / "verifier_axi.v"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_bad_rtl())
    r = _run([str(tmp_path), "--pair", "id_bus"])
    assert r.returncode == 1, \
        f"verifier_axi.v is RTL (filename, not dir), must NOT be excluded: {r.stdout}"
