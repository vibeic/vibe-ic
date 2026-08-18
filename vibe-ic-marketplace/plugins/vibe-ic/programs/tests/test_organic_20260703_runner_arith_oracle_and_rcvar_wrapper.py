#!/usr/bin/env python3
r"""test_organic_20260703_runner_arith_oracle_and_rcvar_wrapper.py

ORGANIC-20260703-runner-arith-oracle-tb-gen-and-rcvar-wrapper-defects.

(a) arith_oracle_tb_gen fired on NON-arithmetic / sequential-FSM modules and
    built a bogus closed-form combinational oracle (no clock driven, no
    start/valid asserted) → reference_tb false-FAIL on correct sequential RTL.
    Fix: DEFER when the top has a CLOCK input, a start/valid/enable HANDSHAKE,
    or a control/STATUS output — the combinational oracle is unsound there.

(b) the reset_clock_variant_aliases wrapper referenced the inner module's
    LOCALPARAM-derived port width (`output [DWIDTH_ACCUMULATOR-1:0] result`)
    without declaring it, so the wrapper failed to elaborate
    (`Unable to bind parameter DWIDTH_ACCUMULATOR`). Fix: hoist the referenced
    localparam(s) into the wrapper's `#(...)` parameter-port list.

Run: python3 -m pytest programs/tests/test_organic_20260703_runner_arith_oracle_and_rcvar_wrapper.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from shutil import which

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import arith_oracle_tb_gen as aotg          # noqa: E402
import reset_clock_variant_alias as R       # noqa: E402


# ── (a) arith oracle DEFER on sequential / handshake / status signatures ─────
def _mk_project(tmp_path: Path, top: str, ports: list, l2: str) -> Path:
    root = tmp_path / top
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"ic_name": top, "frs_sections": [{"content": l2}]}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": top, "top_ports": ports}))
    return root


def test_clocked_pipelined_multiplier_defers(tmp_path):
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rstn", "direction": "input", "width": 1},
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "result", "direction": "output", "width": 16},
    ]
    project = _mk_project(tmp_path, "mac", ports,
                          "result = a * b pipelined multiply-accumulate")
    spec, reason = aotg.extract_arith_spec(project, "digital_arithmetic_primitive")
    assert spec is None
    assert "clock" in reason.lower()


def test_handshake_driven_adder_defers(tmp_path):
    ports = [
        {"name": "start", "direction": "input", "width": 1},
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "sum", "direction": "output", "width": 9},
    ]
    project = _mk_project(tmp_path, "adder", ports,
                          "sum = a + b with a start handshake")
    spec, reason = aotg.extract_arith_spec(project, "digital_arithmetic_primitive")
    assert spec is None
    assert "handshake" in reason.lower()


def test_status_output_datapath_defers(tmp_path):
    ports = [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "result", "direction": "output", "width": 16},
        {"name": "valid_out", "direction": "output", "width": 1},
    ]
    project = _mk_project(tmp_path, "mul", ports,
                          "result = a * b with a valid_out flag")
    spec, reason = aotg.extract_arith_spec(project, "digital_arithmetic_primitive")
    assert spec is None
    assert "status" in reason.lower() or "valid_out" in reason


def test_pure_combinational_multiplier_still_accepted(tmp_path):
    # a clockless, handshake-less, single-data-output primitive is UNAFFECTED
    ports = [
        {"name": "x", "direction": "input", "width": 8},
        {"name": "y", "direction": "input", "width": 8},
        {"name": "p", "direction": "output", "width": 16},
    ]
    project = _mk_project(tmp_path, "mult8", ports,
                          "p = x * y mod 2^N parallel multiplier")
    spec, reason = aotg.extract_arith_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["operator"] == "*"


# ── (b) rcvar wrapper hoists a localparam-derived port width ─────────────────
_INNER = """\
module pipeline_mac #(
    parameter DWIDTH = 16,
    parameter N      = 4
) (
    clk, rstn, multiplicand, multiplier, valid_i, result, valid_out
);
  localparam DWIDTH_ACCUMULATOR = 2*DWIDTH + $clog2(N);
  input  logic clk;
  input  logic rstn;
  input  logic [DWIDTH-1:0] multiplicand;
  input  logic [DWIDTH-1:0] multiplier;
  input  logic valid_i;
  output logic [DWIDTH_ACCUMULATOR-1:0] result;
  output logic valid_out;
  assign result = 0;
  assign valid_out = 0;
endmodule
"""


def test_parse_module_localparams():
    lp = R.parse_module_localparams(_INNER, "pipeline_mac")
    assert lp == [("DWIDTH_ACCUMULATOR", "2*DWIDTH + $clog2(N)")]


def test_wrapper_hoists_localparam_into_param_port_list():
    ports = R.parse_module_ports(_INNER, "pipeline_mac")
    pblock, pnames = R.parse_module_params(_INNER, "pipeline_mac")
    lpdefs = R.parse_module_localparams(_INNER, "pipeline_mac")
    plan = R.plan_aliases([p[2] for p in ports])
    w = R.emit_variant_alias_wrapper(
        "pipeline_mac__rcvar_inner", ports, plan, wrapper_name="pipeline_mac",
        param_block=pblock, param_names=pnames, localparam_defs=lpdefs)
    # the localparam is re-declared in the wrapper header
    assert "localparam DWIDTH_ACCUMULATOR = 2*DWIDTH + $clog2(N)" in w
    # it is NOT forwarded to the inner instance (the inner keeps its own)
    assert ".DWIDTH_ACCUMULATOR(" not in w
    assert ".DWIDTH(DWIDTH)" in w and ".N(N)" in w


def test_wrapper_without_localparam_dependency_is_byte_identical():
    # a wrapper whose port widths do NOT reference a localparam must be exactly
    # the pre-fix output (no hoist, no param-header reformat) — no regression.
    src = ("module m #(parameter W = 8) (clk, rstn, d);\n"
           "  input clk; input rstn; input [W-1:0] d;\n"
           "  localparam UNUSED = 2*W;\n"
           "endmodule\n")
    ports = R.parse_module_ports(src, "m")
    pblock, pnames = R.parse_module_params(src, "m")
    lpdefs = R.parse_module_localparams(src, "m")
    plan = R.plan_aliases([p[2] for p in ports])
    with_lp = R.emit_variant_alias_wrapper(
        "m__rcvar_inner", ports, plan, wrapper_name="m",
        param_block=pblock, param_names=pnames, localparam_defs=lpdefs)
    without_lp = R.emit_variant_alias_wrapper(
        "m__rcvar_inner", ports, plan, wrapper_name="m",
        param_block=pblock, param_names=pnames)
    # UNUSED localparam is not referenced by any port width → not hoisted
    assert "UNUSED" not in with_lp
    assert with_lp == without_lp


def test_full_transform_elaborates_and_synths(tmp_path):
    if not which("iverilog"):
        import pytest
        pytest.skip("iverilog not on PATH")
    import re
    inner = re.sub(r"\bmodule(\s+)pipeline_mac\b",
                   r"module\1pipeline_mac__rcvar_inner", _INNER, count=1)
    ports = R.parse_module_ports(_INNER, "pipeline_mac")
    pblock, pnames = R.parse_module_params(_INNER, "pipeline_mac")
    lpdefs = R.parse_module_localparams(_INNER, "pipeline_mac")
    plan = R.plan_aliases([p[2] for p in ports])
    w = R.emit_variant_alias_wrapper(
        "pipeline_mac__rcvar_inner", ports, plan, wrapper_name="pipeline_mac",
        param_block=pblock, param_names=pnames, localparam_defs=lpdefs)
    f = tmp_path / "pmac.sv"
    f.write_text(inner + "\n\n" + w)
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", str(f)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert r.returncode == 0, r.stdout.decode("utf-8", "replace")
