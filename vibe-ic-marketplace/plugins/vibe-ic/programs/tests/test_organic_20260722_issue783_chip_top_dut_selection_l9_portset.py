#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #783 — `_autoemit_chip_top_wrapper` wrapped
the WRONG module when the design's real top is a `*_wrapper` integration top.

Root cause pinned: the candidate scan blanket-`continue`d any file whose stem
ends in `_asic`/`_wrapper`/`_tb`/`_test`/`_synth` as an "obvious helper /
sub-module file". For a harness-integration design that heuristic is exactly
inverted — the `_wrapper` module IS the deliverable chip face (its whole job is
to add the harness pins an inner block does not have). With the only correct
module excluded, the sole surviving candidate was the inner block, so the
auto-emitted `<top>.v` pass-through exposed the INNER port face and silently
dropped every pin the wrapper adds.

Observable downstream failure (caravel_user_project x sky130A, v1.5.23):
    l9_rtl_pin_consistency_check — FAIL — 2 finding(s)
      · L9 declares pins missing from RTL top: ['analog_io','user_irq',
                                                'vccd1','vssd1']
      · RTL top has ports not in L9: ['irq']
→ phase2 strict-structural FAIL → final_audit FAIL → whole run halted.

NEGATIVE CONTROL (why the obvious one-line fix is NOT the fix): simply dropping
`_wrapper` from the suffix list makes BOTH modules primary candidates, the
`module name == file stem` filter then matches both, and the function returns
None → no chip_top at all → yosys "Module '<top>' not found" → synth FAIL.
Pinned by `test_negctl_unskip_alone_yields_no_wrapper`.

Fix: suffix-named files are DEFERRED into a secondary pool instead of dropped,
and a chip-AGNOSTIC L9 port-set tiebreak picks the module whose functional pin
face best agrees with L9's declared contract (each module's own
`ifdef USE_POWER_PINS face excluded from both sides — supply pins are owned by
the power-intent/PDN layer). The tiebreak runs ONLY when L9 declares top pins
AND the pool holds >1 module, so every historical single-candidate / no-L9 case
is byte-identical (test_noleak_*).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import design_one_shot_runner as P  # noqa: E402

# ---------------------------------------------------------------------------
# Faithful minimal harness-integration shape: the `_wrapper` module is the real
# top (adds analog_io / user_clock2 / user_irq + the full supply face); the
# inner block is a sub-module with a narrower face and a differently-named irq.
# ---------------------------------------------------------------------------
_INNER = """\
`default_nettype none
module user_proj_example #(
    parameter BITS = 16
)(
`ifdef USE_POWER_PINS
    inout vccd1,
    inout vssd1,
`endif
    input  wb_clk_i,
    input  wb_rst_i,
    input  [31:0] wbs_dat_i,
    output [31:0] wbs_dat_o,
    output wbs_ack_o,
    output [2:0] irq
);
    assign wbs_dat_o = wbs_dat_i;
    assign wbs_ack_o = 1'b1;
    assign irq = 3'b000;
endmodule
`default_nettype wire
"""

_WRAPPER = """\
`default_nettype none
module user_project_wrapper #(
    parameter BITS = 32
)(
`ifdef USE_POWER_PINS
    inout vdda1,
    inout vssa1,
    inout vccd1,
    inout vssd1,
`endif
    input  wb_clk_i,
    input  wb_rst_i,
    input  [31:0] wbs_dat_i,
    output [31:0] wbs_dat_o,
    output wbs_ack_o,
    inout  [28:0] analog_io,
    input  user_clock2,
    output [2:0] user_irq
);
    user_proj_example mprj (
        .wb_clk_i(wb_clk_i), .wb_rst_i(wb_rst_i),
        .wbs_dat_i(wbs_dat_i), .wbs_dat_o(wbs_dat_o),
        .wbs_ack_o(wbs_ack_o), .irq(user_irq));
endmodule
`default_nettype wire
"""

# L9's declared contract == the WRAPPER's face (this is what the vendor docs
# describe: the harness-facing pin table).
_L9_PORTS = [
    ("wb_clk_i", "input"), ("wb_rst_i", "input"),
    ("wbs_dat_i", "input"), ("wbs_dat_o", "output"),
    ("wbs_ack_o", "output"), ("analog_io", "inout"),
    ("user_clock2", "input"), ("user_irq", "output"),
    ("vccd1", "inout"), ("vssd1", "inout"),
]

TOP = "caravel_user_project"


def _mk(tmp_path: Path, *, with_l9: bool = True,
        with_wrapper: bool = True) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "user_proj_example.v").write_text(_INNER)
    if with_wrapper:
        (rtl / "user_project_wrapper.v").write_text(_WRAPPER)
    if with_l9:
        gd = proj / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
            "top_module": TOP,
            "top_ports": [{"name": n, "direction": d, "mode": d}
                          for n, d in _L9_PORTS],
        }))
    return proj


def _negctl_pool(tmp_path: Path, *, with_l9: bool = True) -> Path:
    """Same two modules, but the wrapper carries a name NO suffix rule touches
    (file and module both `harness_top`) — i.e. exactly the candidate pool the
    naive `_wrapper`-un-skip one-liner would build: two PRIMARY candidates,
    both satisfying `module name == file stem`."""
    proj = _mk(tmp_path, with_l9=with_l9, with_wrapper=False)
    rtl = proj / "phase2" / "stage1" / "rtl"
    (rtl / "harness_top.v").write_text(
        _WRAPPER.replace("user_project_wrapper", "harness_top"))
    return proj


def _emit(proj: Path):
    return P._autoemit_chip_top_wrapper(
        proj, proj / "phase2" / "stage1" / "rtl", TOP)


def _wrapped_dut(out: Path) -> str:
    """The emitted header records which module it wrapped."""
    import re
    m = re.search(r"rtl/ only defined '(\w+)'", out.read_text())
    return m.group(1) if m else ""


# ── the defect ──────────────────────────────────────────────────────────
def test_wraps_the_l9_matching_wrapper_not_the_inner_block(tmp_path):
    proj = _mk(tmp_path)
    out = _emit(proj)
    assert out is not None, "no chip_top emitted — yosys would fail"
    assert _wrapped_dut(out) == "user_project_wrapper"


def test_emitted_top_carries_every_l9_functional_pin(tmp_path):
    """The pins the pre-fix wrapper DROPPED must now be on the chip face."""
    proj = _mk(tmp_path)
    text = _emit(proj).read_text()
    for pin in ("analog_io", "user_clock2", "user_irq"):
        assert pin in text, f"L9 pin {pin!r} missing from emitted chip_top"
    # the inner block's differently-named irq must NOT leak onto the face
    assert "\n    output [2:0] irq" not in text


def test_power_face_still_ifdef_guarded(tmp_path):
    """#783 must not regress the v1.5.22 power-pin connection guard."""
    text = _emit(_mk(tmp_path)).read_text()
    assert "`ifdef USE_POWER_PINS" in text
    body = text.split("u_dut", 1)[1]
    for rail in ("vccd1", "vssd1"):
        assert f".{rail}({rail})" in body
        # the connection must live inside the guard, never before it
        assert body.index("`ifdef USE_POWER_PINS") < body.index(
            f".{rail}({rail})")


# ── negative control ────────────────────────────────────────────────────
def test_negctl_unskip_alone_yields_no_wrapper(tmp_path):
    """Pins WHY simply dropping `_wrapper` from the suffix list is NOT the fix.

    That one-liner puts both modules in the PRIMARY pool. Reproduced exactly by
    renaming the wrapper file so no suffix rule applies to it: both candidates
    then match `module name == file stem`, the basename filter cannot narrow to
    one, and the function bails ambiguous → None → no chip_top emitted → yosys
    "Module 'caravel_user_project' not found" → synth FAIL. The port-set
    tiebreak is what actually resolves it (test_negctl_portset_resolves_it).

    Reproduced by giving the wrapper a name no suffix rule touches (file AND
    module `harness_top`), which is byte-for-byte the pool state the one-line
    un-skip would produce: two primary candidates, both `module == stem`."""
    proj = _negctl_pool(tmp_path, with_l9=False)
    assert _emit(proj) is None


def test_negctl_portset_resolves_it(tmp_path):
    """Same ambiguous two-primary-candidate pool as above, but WITH the L9 port
    evidence: the tiebreak now resolves it to the module that implements L9's
    contract instead of bailing."""
    proj = _negctl_pool(tmp_path)
    out = _emit(proj)
    assert out is not None and _wrapped_dut(out) == "harness_top"


# ── no-leak ─────────────────────────────────────────────────────────────
def test_noleak_single_candidate_unchanged(tmp_path):
    """One module in the pool → tiebreak is a no-op, historical pick stands."""
    proj = _mk(tmp_path, with_wrapper=False)
    out = _emit(proj)
    assert out is not None and _wrapped_dut(out) == "user_proj_example"


def test_noleak_no_l9_portset_falls_back_to_historical(tmp_path):
    """No L9 top_ports → tiebreak self-disables; the deferred pool is ignored
    exactly as before, so a lone non-suffix candidate is still chosen."""
    proj = _mk(tmp_path, with_l9=False, with_wrapper=False)
    out = _emit(proj)
    assert out is not None and _wrapped_dut(out) == "user_proj_example"


def test_noleak_authored_top_still_short_circuits(tmp_path):
    """An authored <top>.v must still suppress auto-emit entirely."""
    proj = _mk(tmp_path)
    (proj / "phase2" / "stage1" / "rtl" / f"{TOP}.v").write_text(
        f"module {TOP}(input a); endmodule\n")
    assert _emit(proj) is None


# ── the helpers the tiebreak is built from ──────────────────────────────
def test_l9_port_names_helper_reads_cascade(tmp_path):
    proj = _mk(tmp_path)
    names = P._chip_top_l9_top_port_names(proj)
    assert {"analog_io", "user_irq", "vccd1"} <= names


def test_l9_port_names_helper_empty_when_absent(tmp_path):
    proj = _mk(tmp_path, with_l9=False)
    assert P._chip_top_l9_top_port_names(proj) == set()


def test_port_names_helper_excludes_keywords():
    block = "(\n input wire clk,\n output reg [3:0] q,\n inout io\n)"
    assert P._chip_top_port_names(block) == {"clk", "q", "io"}


# ── salvage-port guard: explicit declaration outranks the heuristic ─────
def test_explicit_l9_top_module_outranks_the_portset_tiebreak(tmp_path):
    """SALVAGE-PORT GUARD (#315 p12). When L9 states `top_module` outright and
    exactly one pooled module carries that name, that declaration wins — the
    port-set score is a heuristic read and must not override it. Here L9's
    `top_ports` deliberately describes the WRAPPER's face while `top_module`
    names the INNER block, so the two signals disagree and only the priority
    order decides the outcome."""
    proj = _mk(tmp_path)
    gd = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    d = json.loads(gd.read_text())
    d["top_module"] = "user_proj_example"
    gd.write_text(json.dumps(d))
    out = _emit(proj)
    assert out is not None, "declared top must still yield a chip_top"
    assert _wrapped_dut(out) == "user_proj_example", (
        "the port-set tiebreak overrode an explicit L9.top_module declaration")


def test_declared_top_in_a_deferred_file_is_reachable(tmp_path):
    """The declared top may live in a suffix-named file. Before #783 that file
    was dropped before the v0.1.62 declaration preference could see it."""
    proj = _mk(tmp_path)
    gd = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    d = json.loads(gd.read_text())
    d["top_module"] = "user_project_wrapper"
    gd.write_text(json.dumps(d))
    out = _emit(proj)
    assert out is not None and _wrapped_dut(out) == "user_project_wrapper"


def test_noleak_declaration_guard_inert_without_top_module(tmp_path):
    """No `top_module` key at all → the guard is a no-op and the port-set
    tiebreak decides exactly as #783 shipped it."""
    proj = _mk(tmp_path)
    gd = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    d = json.loads(gd.read_text())
    d.pop("top_module", None)
    gd.write_text(json.dumps(d))
    out = _emit(proj)
    assert out is not None and _wrapped_dut(out) == "user_project_wrapper"


@pytest.mark.parametrize("top_name", ["caravel_user_project", "chip_top"])
def test_top_name_independent(tmp_path, top_name):
    """chip-AGNOSTIC: the selection is driven by L9 port-set agreement, not by
    any particular top string."""
    proj = _mk(tmp_path)
    out = P._autoemit_chip_top_wrapper(
        proj, proj / "phase2" / "stage1" / "rtl", top_name)
    assert out is not None and _wrapped_dut(out) == "user_project_wrapper"
