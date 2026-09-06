#!/usr/bin/env python3
"""test_organic_20260704_rcvar_whitebox_flat.py — the whitebox-safe FLAT reset/clock
alias transform (ORGANIC-20260704-runner-rcvar-wrapper-breaks-whitebox-harnesses).

emit_variant_alias_flat renames a reset/clock port to its canonical spelling IN the
module's own header + adds a 1-bit internal `wire <orig> = <canon>;`, producing ONE
FLAT module (no `<top>__rcvar_inner` submodule) so a hidden whitebox TB that binds the
design's OWN internal signals hierarchically (dut.<internal>) still sees them.

The step-level transform is OPT-IN (VIBE_IC_RCVAR_WHITEBOX_FLAT=1) so the shipped
default stays the wrapper (its #518/#689/#792 guard tests are untouched).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent
sys.path.insert(0, str(PROG))
import reset_clock_variant_alias as R  # noqa: E402
import design_one_shot_runner as D     # noqa: E402

# active-HIGH reset `reset`; canonical same-polarity spelling `rst` (NOT rst_n).
DUT = (
    "module widget (\n"
    "    input        clk,\n"
    "    input        reset,\n"
    "    input        d,\n"
    "    output reg   q\n"
    ");\n"
    "    reg parity_out;\n"
    "    always @(posedge clk) begin\n"
    "        if (reset) begin q <= 1'b0; parity_out <= 1'b0; end\n"
    "        else begin q <= d; parity_out <= parity_out ^ d; end\n"
    "    end\n"
    "endmodule\n"
)


def test_flat_renames_in_place_no_inner_submodule():
    out = R.emit_variant_alias_flat(DUT, "widget", {"reset": "rst"})
    assert out is not None
    assert "__rcvar_inner" not in out                 # NO nested submodule
    assert out.count("module widget") == 1            # one flat module, same name
    assert "rst" in out and "input        rst" in out.replace(",", " ")
    assert "wire reset = rst;" in out                 # internal alias keeps body valid
    assert "if (reset)" in out                        # body unchanged → resolves to alias


def test_flat_result_compiles_and_whitebox_signal_visible(tmp_path):
    if not shutil.which("iverilog"):
        return
    out = R.emit_variant_alias_flat(DUT, "widget", {"reset": "rst"})
    (tmp_path / "widget.v").write_text(out)
    tb = (            # WHITEBOX TB: binds the design's internal parity_out hierarchically
        "module tb; reg clk=0, rst=1, d=0; wire q;\n"
        "  widget dut(.clk(clk), .rst(rst), .d(d), .q(q));\n"
        "  initial begin #1 $display(\"pv=%b\", dut.parity_out); $finish; end\n"
        "  always #5 clk = ~clk;\n"
        "endmodule\n"
    )
    (tmp_path / "tb.v").write_text(tb)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
                        str(tmp_path / "widget.v"), str(tmp_path / "tb.v")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr   # canonical port + hierarchical dut.parity_out both elaborate


def test_flat_declines_cross_polarity():
    import pytest
    with pytest.raises(ValueError):      # active-high `reset` -> active-low `rst_n`
        R.emit_variant_alias_flat(DUT, "widget", {"reset": "rst_n"})


def test_flat_declines_when_port_not_found():
    # Same-polarity pair (rst<-reset, both active-high) whose orig `rst` is NOT in
    # this header → return None (caller falls back to wrapper). Not a polarity decline.
    assert R.emit_variant_alias_flat(DUT, "widget", {"rst": "reset"}) is None


# ---- step-level opt-in integration -----------------------------------------

_SEQ = (
    "module sequence_detector(\n"
    "    input wire clk,\n"
    "    input wire reset_n,\n"
    "    input wire data_in,\n"
    "    output reg detected\n"
    ");\n"
    "    reg [1:0] state;\n"
    "    always @(posedge clk or negedge reset_n)\n"
    "        if (!reset_n) begin detected <= 1'b0; state <= 2'b0; end\n"
    "        else begin state <= state + 1'b1; detected <= &state; end\n"
    "endmodule\n"
)


def _stage(tmp_path, txt, name):
    rtl = D._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / name
    f.write_text(txt)
    return f


def _request_interface(proj, top, *ports):
    """The public target interface these cases intentionally ask for.

    RULED by v1.17.48 (76e5960ee): automatic reset/clock adaptation now requires
    an authoritative interface naming the DESTINATION spelling and not requiring
    the SOURCE one. Without it the step refuses before either branch below is
    reached — MEASURED on e1814e28d, both cases returned the same "no
    authoritative interface requests an equivalent reset/clock spelling" SKIP,
    so the FLAT-vs-wrapper choice this file exists to pin decided nothing.

    The opt-in is about WHICH SHAPE the transform emits; the ruling is about
    WHETHER it may run at all. Staging the request restores the first question,
    which is the one these two cases ask.
    """
    import json
    docs = proj / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": top, "top_ports": list(ports)}))


def test_step_flat_optin_produces_flat_module(tmp_path, monkeypatch):
    # design ships active-low `reset_n`; hidden whitebox TB needs canonical `rst_n`.
    f = _stage(tmp_path, _SEQ, "sequence_detector.v")
    _request_interface(tmp_path, "sequence_detector",
                       "clk", "rst_n", "data_in", "detected")
    monkeypatch.setenv("VIBE_IC_RCVAR_WHITEBOX_FLAT", "1")
    res = D.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert res.status == "PASS", (res.status, res.detail)
    body = f.read_text()
    assert "__rcvar_inner" not in body               # FLAT — no nested submodule
    assert body.count("module sequence_detector") == 1
    assert "rst_n" in body                            # canonical exposed for the TB
    assert "wire reset_n = rst_n;" in body            # internal alias; body `!reset_n` resolves
    assert "state" in body                            # design internals stay in the flat top


def test_step_default_off_keeps_wrapper(tmp_path, monkeypatch):
    # WITHOUT the opt-in the shipped wrapper path is used (inner submodule present).
    f = _stage(tmp_path, _SEQ, "sequence_detector.v")
    _request_interface(tmp_path, "sequence_detector",
                       "clk", "rst_n", "data_in", "detected")
    monkeypatch.delenv("VIBE_IC_RCVAR_WHITEBOX_FLAT", raising=False)
    res = D.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert res.status == "PASS", (res.status, res.detail)
    assert "__rcvar_inner" in f.read_text()          # default behavior unchanged
