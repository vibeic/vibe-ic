"""ORGANIC #618 [MEDIUM] — reset_clock_variant_alias unconditionally renamed a
spec-matching top clock port to a hardcoded canon (`clk`). When a design's OWN
staged constraint SDC already pins the ORIGINAL spelling (`set clk_port_name
clk_i` / `create_clock [get_ports {clk_i}]`), the rename rewrote the CORRECT
port (clk_i -> clk), so l9_rtl_pin_consistency_check (the SOLE strict-structural
gate) FAILed (L9<->RTL top pin mismatch) and the SDC's get_ports clk_i resolved
to no object. The existing L9 guard only fired on the resolved_via_chip_top
path AND required L9.top == tgt — the ibex case took the directly-authored
chip_top branch with L9.top (ibex_top) != tgt (chip_top), so it never fired.

Fix: a spec-aware suppression that applies UNCONDITIONALLY — before renaming a
clock/reset port, consult the design's staged constraint SDC (the
upstream-verified ground truth, same ranking as #554/#623). Drop from the
rename plan any source port whose spelling is pinned there.

POSITIVE (#618): staged SDC pins `clk_i` -> step SKIPs, chip_top keeps `clk_i`
verbatim, no `__rcvar_inner` wrapper is emitted.

NEGATIVE no-leak (the load-bearing half, §4.05):
  - NO staged SDC -> the legitimate #518 hidden-TB alias STILL fires
    (clk_i -> clk, inner created).
  - staged SDC pins ONLY clk_i while the design also has an unpinned reset_n ->
    clk_i is preserved but the reset_n -> rst_n alias STILL fires (partial
    suppression, not a blanket skip).

chip-AGNOSTIC: standard-SDC syntax + set-membership on port spellings; no chip
names. The real #618 discriminating SDC line (`set clk_port_name clk_i`) is
embedded verbatim.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import sdc_constraints as S  # noqa: E402
import design_one_shot_runner as R  # noqa: E402

# The real on-disk #618 evidence, verbatim (OpenROAD-flow-scripts Tcl-var form).
REAL_618_SDC = (
    "set clk_name      core_clock\n"
    "set clk_port_name clk_i\n"
    "set clk_period    10.0\n"
    "set clk_port      [get_ports $clk_port_name]\n"
    "create_clock -name $clk_name -period $clk_period $clk_port\n"
)

CHIP_TOP_CLK_I = (
    "module chip_top (\n  input  clk_i,\n  input  rst_ni,\n"
    "  output [7:0] o_data\n);\n  assign o_data = 8'd0;\nendmodule\n"
)


def _stage_sdc(proj, text):
    c = proj / "input/constraints"
    c.mkdir(parents=True, exist_ok=True)
    (c / "constraint.sdc").write_text(text)


def _request_interface(proj, *ports, top="chip_top"):
    """Declare the public target interface this case intentionally asks for.

    RULED by v1.17.48 (76e5960ee, "require a requested interface before aliasing
    reset/clock names"): automatic adaptation now needs an authoritative
    interface that NAMES THE DESTINATION spelling and does NOT require the
    source spelling. Without one the step refuses before it ever looks at the
    SDC — MEASURED on e1814e28d, all three step-level cases below returned the
    same "no authoritative interface requests an equivalent reset/clock
    spelling" SKIP, so the #618 SDC guard decided nothing and this file's three
    outcomes had collapsed into one.

    That ruling is about WHO may ask for a rename. #618 is about a design whose
    own staged SDC pins the spelling being renamed, which is a different
    question and the one these cases exist to ask. Staging the request puts the
    SDC guard back in the position of deciding, exactly as v1.17.48 did for the
    eleven wrapping fixtures it updated itself.
    """
    docs = proj / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": top, "top_ports": list(ports)}))


def _stage_rtl(proj, text, name="chip_top.sv"):
    rtl = R._pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / name
    f.write_text(text)
    return f


# ── sdc_constraints.staged_constrained_ports ───────────────────────────────

def test_staged_ports_resolves_tcl_var(tmp_path):
    _stage_sdc(tmp_path, REAL_618_SDC)
    assert S.staged_constrained_ports(tmp_path) == {"clk_i"}


def test_staged_ports_literal_get_ports(tmp_path):
    _stage_sdc(tmp_path, "create_clock -name core -period 10 [get_ports {clk_i}]\n")
    assert "clk_i" in S.staged_constrained_ports(tmp_path)


def test_staged_ports_empty_without_sdc(tmp_path):
    assert S.staged_constrained_ports(tmp_path) == set()


def test_staged_ports_includes_data_ports_harmlessly(tmp_path):
    # set_input_delay on a data port is collected too, but the runner only
    # intersects with the (clock/reset) rename plan, so it never mis-suppresses.
    _stage_sdc(tmp_path,
               "create_clock -name c -period 10 [get_ports {clk_i}]\n"
               "set_input_delay 2 -clock c [get_ports {data_i}]\n")
    pinned = S.staged_constrained_ports(tmp_path)
    assert {"clk_i", "data_i"} <= pinned


# ── step_reset_clock_variant_aliases spec-aware suppression ────────────────

def test_step_skips_rename_when_sdc_pins_original(tmp_path):
    # POSITIVE #618: staged SDC pins clk_i -> no rename.
    _stage_sdc(tmp_path, REAL_618_SDC)
    # `clk` is requested (the destination); `rst_ni` is requested as itself, so
    # only the CLOCK alias is on the table and #618 is what decides it.
    _request_interface(tmp_path, "clk", "rst_ni", "o_data")
    chip = _stage_rtl(tmp_path, CHIP_TOP_CLK_I)
    res = R.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert res.status == "SKIP"
    assert "#618" in res.detail and "clk_i" in res.detail
    after = chip.read_text()
    assert "clk_i" in after, "the SDC-pinned port spelling must survive"
    assert "__rcvar_inner" not in after, "no wrapper may be emitted"


def test_step_renames_when_no_staged_sdc(tmp_path):
    # NO-LEAK (#518): no staged SDC -> the alias rename still fires.
    _request_interface(tmp_path, "clk", "rst_ni", "o_data")
    chip = _stage_rtl(tmp_path, CHIP_TOP_CLK_I)
    res = R.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert res.status == "PASS"
    after = chip.read_text()
    assert "__rcvar_inner" in after, "the #518 hidden-TB alias must still fire"


def test_step_partial_pin_keeps_aliasing_unpinned(tmp_path):
    # NO-LEAK: SDC pins clk_i only; the unpinned reset_n -> rst_n alias fires,
    # clk_i is preserved (partial suppression, not a blanket skip).
    _stage_sdc(tmp_path, "create_clock -name c -period 10 [get_ports {clk_i}]\n")
    # BOTH destinations requested, NEITHER source: the two aliases are on the
    # table together, so the SDC pinning clk_i alone is what splits them.
    _request_interface(tmp_path, "clk", "rst_n", "o_data")
    chip = _stage_rtl(
        tmp_path,
        "module chip_top (\n  input  clk_i,\n  input  reset_n,\n"
        "  output [7:0] o_data\n);\n  assign o_data = 8'd0;\nendmodule\n")
    res = R.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert res.status == "PASS"
    assert "reset_n" in res.detail and "rst_n" in res.detail
    # clk_i must NOT be among the aliased ports.
    assert "'clk_i'" not in res.detail
