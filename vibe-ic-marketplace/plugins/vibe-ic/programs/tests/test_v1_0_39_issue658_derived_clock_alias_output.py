#!/usr/bin/env python3
"""ORGANIC #658 — derived-clock gate false-FAILs on a register toggle that is
exported as a 1-bit DATA status output port via an `assign`-alias.

THE BUG
-------
The #569 `_is_consumed()` no-leak hardening walked the `assign`-alias frontier
and treated ANY alias that is an output port as a clock consumer — conservatively
assuming an exported toggle could be an external clock. But a 1-bit DATA/status
flag exported via::

    output logic phase;
    logic phase_q;
    always_ff @(posedge clk_i) phase_q <= ~phase_q;   // status flag toggle
    assign phase = phase_q;                            // exported as DATA

is NEVER used as a clock (no `posedge phase` / `.clk(phase)` anywhere), so it must
keep the #569 `derived_clock_no_consumer` INFO classification. The field agent's
round-3 v1.0.35 clean-room 6-IC re-run surfaced this as a live FALSE
`[ERROR] derived_clock_sdc_missing (phase_q from clk_i)` on an unmodifiable vendor
shadow flop (`prim_subreg_shadow.sv`).

THE FIX
-------
In `_is_consumed()`, an aliased downstream net counts as a clock consumer ONLY
when it is GENUINELY consumed — used as a clock edge (`posedge/negedge`) / a
clock-named pin, or fed to ANY instance pin — NOT when it is *merely re-exported*
as an output port. The DIRECT-export path (`output reg core_clk; core_clk <= ~`)
is unchanged and stays conservatively gated.

ACCEPTANCE: alias-to-output toggle with no `posedge <port>` consumer → INFO/PASS.
NO-LEAK: same toggle exported AND consumed via `posedge phase` in another module
→ ERROR (`derived_clock_sdc_missing`) — a real exported derived clock still needs
the create_generated_clock SDC entry.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "derived_clock_sdc_required_check.py")


def _run(*args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _findings_json(tmp_path: Path, target: str):
    out = tmp_path / "rep.json"
    rc, _, _ = _run(target, "--json", str(out))
    data = json.loads(out.read_text())
    return rc, data


# Vendor shadow-flop minimal repro: a status-flag toggle exported via an
# assign-alias to a 1-bit DATA output port, with NO posedge/clk-pin consumer.
_ALIAS_TO_OUTPUT_TOGGLE = """\
module prim_subreg_shadow #(
  parameter int Width = 1
) (
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic             we,
  input  logic [Width-1:0] wd,
  output logic             phase,
  output logic [Width-1:0] q
);
  logic phase_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) phase_q <= 1'b0;
    else         phase_q <= ~phase_q;
  end
  assign q     = '0;
  assign phase = phase_q;
endmodule
"""

# Guardless toggle (no data-enable guard) — proves the candidate's
# data-enable-guard theory WRONG: the alias-to-output path alone reproduces.
_ALIAS_TO_OUTPUT_TOGGLE_GUARDLESS = """\
module flag(input logic clk_i, output logic phase);
  logic phase_q;
  always_ff @(posedge clk_i) phase_q <= ~phase_q;
  assign phase = phase_q;
endmodule
"""


def test_658_alias_to_output_toggle_is_info_not_error(tmp_path):
    """ACCEPTANCE: `output phase` + `assign phase = phase_q` toggle with no
    posedge consumer → INFO/PASS (not a false derived_clock_sdc_missing)."""
    (tmp_path / "prim_subreg_shadow.sv").write_text(_ALIAS_TO_OUTPUT_TOGGLE)
    rc, data = _findings_json(tmp_path, str(tmp_path))
    assert rc == 0, data
    assert data["verdict"] == "PASS"
    errs = [f for f in data["findings"] if f["severity"] == "ERROR"]
    assert not errs, f"unexpected ERROR(s): {errs}"
    rules = {f["rule"] for f in data["findings"]}
    assert "derived_clock_no_consumer" in rules
    assert "derived_clock_sdc_missing" not in rules


def test_658_guardless_alias_to_output_toggle_still_info(tmp_path):
    """The candidate's data-enable-guard theory is WRONG — a guardless
    `else phase_q <= ~phase_q` exported via assign-alias still classifies as
    INFO. The real trigger is the alias-to-output path, now fixed."""
    (tmp_path / "flag.sv").write_text(_ALIAS_TO_OUTPUT_TOGGLE_GUARDLESS)
    rc, data = _findings_json(tmp_path, str(tmp_path))
    assert rc == 0, data
    assert data["verdict"] == "PASS"
    assert not [f for f in data["findings"] if f["severity"] == "ERROR"]


def test_658_single_file_target_reproduces_info(tmp_path):
    """The field agent reported the FALSE ERROR on a SINGLE file too — confirm
    the fix holds for a single-file target, not only a directory."""
    f = tmp_path / "prim_subreg_shadow.sv"
    f.write_text(_ALIAS_TO_OUTPUT_TOGGLE)
    rc, out, _ = _run(str(f))
    assert rc == 0, out
    assert "derived_clock_sdc_missing" not in out
    assert "derived_clock_no_consumer" in out


def test_658_noleak_exported_AND_clocked_still_errors(tmp_path):
    """NO-LEAK: the same toggle exported AND genuinely consumed via
    `posedge phase` in another module IS a real exported derived clock and
    STILL FAILs (derived_clock_sdc_missing) when no SDC declares it."""
    (tmp_path / "toggle.sv").write_text(_ALIAS_TO_OUTPUT_TOGGLE_GUARDLESS)
    (tmp_path / "consumer.sv").write_text(
        "module consumer(input logic phase, output reg o);\n"
        "  always @(posedge phase) o <= ~o;\n"   # phase used as a clock edge
        "endmodule\n")
    rc, data = _findings_json(tmp_path, str(tmp_path))
    assert rc == 1, data
    assert data["verdict"] == "FAIL"
    errs = [f for f in data["findings"] if f["severity"] == "ERROR"]
    assert "derived_clock_sdc_missing" in {f["rule"] for f in errs}
    # load-bearing: the EXPORTED-AND-CLOCKED toggle `phase_q` itself must be
    # the flagged derived clock (proves the no-leak, not an incidental match).
    assert any("'phase_q'" in f["message"] for f in errs), errs


def test_658_noleak_exported_AND_clocked_passes_with_sdc(tmp_path):
    """NO-LEAK companion: a genuinely-exported derived clock with a
    create_generated_clock SDC entry PASSes — gating, not blanket-FAIL."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "toggle.sv").write_text(_ALIAS_TO_OUTPUT_TOGGLE_GUARDLESS)
    # consumer clocks a DATA register off `phase` (no `o <= ~o`, so `o` is not
    # itself a second divided clock) — isolates the phase_q gate for this case.
    (rtl / "consumer.sv").write_text(
        "module consumer(input logic phase, input logic d, output reg o);\n"
        "  always @(posedge phase) o <= d;\n"
        "endmodule\n")
    sdc = tmp_path / "design.sdc"
    sdc.write_text(
        "create_generated_clock -name phase_q -divide_by 2 "
        "-source [get_ports clk_i] [get_pins phase_q_reg/Q]\n")
    rc, _, _ = _run(str(rtl), "--sdc", str(sdc))
    assert rc == 0


def test_658_noleak_alias_to_clk_pin_still_errors(tmp_path):
    """NO-LEAK: an aliased net fed to a CLOCK PIN (`.clk(phase)`) is a genuine
    consumer and still requires SDC — the alias-frontier instance-pin branch
    is preserved (only the bare output-port re-export was relaxed)."""
    (tmp_path / "m.sv").write_text(
        "module m(input logic clk_i, output logic phase);\n"
        "  logic phase_q;\n"
        "  always_ff @(posedge clk_i) phase_q <= ~phase_q;\n"
        "  assign phase = phase_q;\n"
        "  sub u_sub(.clk(phase), .d(1'b0));\n"   # phase drives a clock pin
        "endmodule\n")
    rc, data = _findings_json(tmp_path, str(tmp_path))
    assert rc == 1, data
    assert "derived_clock_sdc_missing" in {f["rule"] for f in data["findings"]}


def test_658_keeps_569_positive_internal_toggle_info(tmp_path):
    """KEEP #569's positive case: an internal NON-exported toggle that clocks
    nothing remains INFO/PASS (the fix did not over-relax in the other
    direction)."""
    (tmp_path / "a.sv").write_text(
        "module m(input clk_i, output reg dout);\n"
        "  reg phase_q;\n"
        "  always @(posedge clk_i) phase_q <= ~phase_q;\n"
        "  always @(posedge clk_i) dout <= phase_q;\n"   # data use, not clock
        "endmodule\n")
    rc, data = _findings_json(tmp_path, str(tmp_path))
    assert rc == 0, data
    assert data["verdict"] == "PASS"
    assert "derived_clock_no_consumer" in {f["rule"] for f in data["findings"]}


def test_658_keeps_direct_exported_divided_clock_error(tmp_path):
    """KEEP the conservative DIRECT-export gate: a divided net that is ITSELF
    the output port (`output reg core_clk; core_clk <= ~core_clk`) with no SDC
    STILL FAILs — the fix only relaxed the transitive assign-alias re-export,
    not the direct export."""
    (tmp_path / "c.v").write_text(
        "module clkdiv(input ext_clk, output reg core_clk);\n"
        "  always @(posedge ext_clk) core_clk <= ~core_clk;\n"
        "endmodule\n")
    rc, data = _findings_json(tmp_path, str(tmp_path))
    assert rc == 1, data
    assert "derived_clock_sdc_missing" in {f["rule"] for f in data["findings"]}
