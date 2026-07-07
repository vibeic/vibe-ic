"""ORGANIC #683 — step_yosys_synth synth-top resolution lacked the
instantiation-graph-root fallback the TB resolver already has.

For a reused-IP / catalog-glue design whose Phase-1 doc-extraction lifts a
doc-prose integration top name into `L9.top_module` that is NOT a real staged
module (a PHANTOM top) and `L9.synth_top=null`, `step_yosys_synth`'s synth-top
precedence (waivers.phase2_synth_top → L9.synth_top → <top>_asic.sv → top_name)
resolves `synth_top='chip_top'` (caller default). No chip_top module exists, and
`_autoemit_chip_top_if_needed` BAILS 'genuinely ambiguous' on a multi-module
design → yosys `synth -top chip_top` → "chip_top is not a valid top-level module"
→ Phase-2 FAIL. The SAME-runner TB path `_v661_resolve_dut_module` HAS clause (c)
'unique instantiation-graph root' and resolves the real top correctly; the synth
step never called it.

Fix: in step_yosys_synth, ONLY when the precedence falls through to the runner
auto-wrapper name 'chip_top' AND no chip_top module is defined in staged rtl/,
call `_v661_resolve_dut_module(project, top_name, L9.top_module)` and, if it
returns a REAL instantiation-graph-root module, adopt it as synth_top. Pure
instantiation-graph structural detection; chip-AGNOSTIC.

POSITIVE: a reused-IP project with phantom L9.top_module + synth_top=null + no
chip_top module + a UNIQUE instantiation-graph root → step_yosys_synth adopts the
graph-root as synth_top (no 'chip_top is not valid' FAIL).
§4.05 NEGATIVE no-leak: a design WITH a real chip_top still uses chip_top (NOT
overridden); a design with a real L9.synth_top still uses it (precedence
preserved); a genuinely ambiguous multi-root design does NOT silently pick a
wrong root — the resolver returns None so it honestly bails/waives; the TB
resolver path is unchanged.

The fixtures embed the real repro SHAPE (phantom integration-top 'the_top' /
graph-root 'core' pattern, generalising the round-5 ibex_top→ibex_core case) with
generic names.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402

_HAVE_YOSYS = shutil.which("yosys") is not None
_yosys = pytest.mark.skipif(not _HAVE_YOSYS,
                            reason="yosys not on host — step is a no-op")

# ── reusable RTL bodies (generic names; phantom integration-top shape) ──────
_LEAF = """\
module {n} (
    input  wire clk,
    input  wire rst_n,
    output reg  [7:0] q
);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) q <= 0; else q <= q + 1'b1;
endmodule
"""
_ROOT_WRAPPING = """\
module {root} (
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] q
);
    {child} u_child (.clk(clk), .rst_n(rst_n), .q(q));
endmodule
"""


def _scaffold(tmp_path, rtl_files, l9, waivers=None):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    for name, txt in rtl_files.items():
        (rtl / name).write_text(txt)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def _synth_top_in(detail):
    for tok in detail.split():
        if tok.startswith("synth_top="):
            return tok.split("=", 1)[1]
    return None


# ── POSITIVE (resolver unit, no yosys needed) ───────────────────────────────

def test_resolver_picks_graph_root_for_phantom_top(tmp_path):
    """The structural resolver step_yosys_synth now consults returns the UNIQUE
    instantiation-graph root for a phantom L9.top_module."""
    proj = _scaffold(
        tmp_path,
        {"core.sv": _ROOT_WRAPPING.format(root="core", child="sub"),
         "sub.sv": _LEAF.format(n="sub")},
        {"top_module": "the_top", "synth_top": None})
    # top_name=chip_top is NOT a module here → falls through to graph root.
    assert R._v661_resolve_dut_module(proj, "chip_top", "the_top") == "core"
    # the phantom integration-top is NEVER returned.
    assert "the_top" not in set(R._v661_rtl_module_names(proj))


# ── POSITIVE (end-to-end through step_yosys_synth) ──────────────────────────

@_yosys
def test_synth_adopts_graph_root_no_chip_top_fail(tmp_path):
    proj = _scaffold(
        tmp_path,
        {"core.sv": _ROOT_WRAPPING.format(root="core", child="sub"),
         "sub.sv": _LEAF.format(n="sub")},
        {"top_module": "the_top", "synth_top": None})
    res = R.step_yosys_synth(proj, "chip_top", container="vibeic-eda")
    assert res.status == "PASS", res.detail
    assert _synth_top_in(res.detail) == "core", res.detail
    # NO 'chip_top is not a valid top-level module' FAIL.
    assert "chip_top is not a valid" not in res.detail
    # no spurious chip_top wrapper had to be auto-emitted.
    rtl = _pl.rtl_dir(proj)
    assert not (rtl / "chip_top.v").is_file()
    assert not (rtl / "chip_top.sv").is_file()


# ── §4.05 NEGATIVE no-leak ──────────────────────────────────────────────────

@_yosys
def test_noleak_real_chip_top_not_overridden(tmp_path):
    """A design WITH a real chip_top module keeps synth_top=chip_top — the
    fallback must NOT fire (chip_top IS defined in staged rtl/)."""
    proj = _scaffold(
        tmp_path,
        {"chip_top.sv": _ROOT_WRAPPING.format(root="chip_top", child="sub"),
         "sub.sv": _LEAF.format(n="sub")},
        {"top_module": "chip_top", "synth_top": None})
    res = R.step_yosys_synth(proj, "chip_top", container="vibeic-eda")
    assert res.status == "PASS", res.detail
    assert _synth_top_in(res.detail) == "chip_top", res.detail


@_yosys
def test_noleak_real_l9_synth_top_preserved(tmp_path):
    """A design with a real L9.synth_top keeps using it (precedence preserved);
    the fallback never fires because synth_top != the auto-wrapper name."""
    proj = _scaffold(
        tmp_path,
        {"mytop.sv": _ROOT_WRAPPING.format(root="mytop", child="sub"),
         "sub.sv": _LEAF.format(n="sub")},
        {"top_module": "the_top", "synth_top": "mytop"})
    res = R.step_yosys_synth(proj, "chip_top", container="vibeic-eda")
    assert res.status == "PASS", res.detail
    assert _synth_top_in(res.detail) == "mytop", res.detail


@_yosys
def test_noleak_real_waiver_synth_top_preserved(tmp_path):
    """waivers.json:phase2_synth_top still wins over the graph-root fallback."""
    proj = _scaffold(
        tmp_path,
        {"waivedtop.sv": _ROOT_WRAPPING.format(root="waivedtop", child="sub"),
         "sub.sv": _LEAF.format(n="sub"),
         # a DIFFERENT real graph-root the fallback would otherwise pick.
         "other.sv": _ROOT_WRAPPING.format(root="other", child="sub2"),
         "sub2.sv": _LEAF.format(n="sub2")},
        {"top_module": "the_top", "synth_top": None},
        waivers={"phase2_synth_top": "waivedtop"})
    res = R.step_yosys_synth(proj, "chip_top", container="vibeic-eda")
    assert res.status == "PASS", res.detail
    assert _synth_top_in(res.detail) == "waivedtop", res.detail


def test_noleak_ambiguous_multi_root_resolver_returns_none(tmp_path):
    """A genuinely ambiguous design (TWO instantiation-graph roots, no chip_top,
    phantom L9.top_module) → the resolver returns None, so the fallback does NOT
    silently pick a wrong root. (resolver-unit; no yosys needed.)"""
    proj = _scaffold(
        tmp_path,
        {"rootA.sv": _LEAF.format(n="rootA"),
         "rootB.sv": _LEAF.format(n="rootB")},
        {"top_module": "the_top", "synth_top": None})
    assert R._v661_resolve_dut_module(proj, "chip_top", "the_top") is None


@_yosys
def test_noleak_ambiguous_multi_root_honestly_fails(tmp_path):
    """End-to-end: the ambiguous case must NOT adopt a wrong root and must NOT
    masquerade as PASS — it honestly FAILs on the chip_top error (or the
    existing auto-emit/waiver path), never silently synthesising rootA over
    rootB."""
    proj = _scaffold(
        tmp_path,
        {"rootA.sv": _LEAF.format(n="rootA"),
         "rootB.sv": _LEAF.format(n="rootB")},
        {"top_module": "the_top", "synth_top": None})
    res = R.step_yosys_synth(proj, "chip_top", container="vibeic-eda")
    # honest FAIL — neither rootA nor rootB was silently chosen.
    assert res.status == "FAIL", res.detail
    assert _synth_top_in(res.detail) != "rootA"
    assert _synth_top_in(res.detail) != "rootB"


def test_noleak_tb_resolver_path_unchanged(tmp_path):
    """The TB path `step_full_stack_tb_gen` → `_v661_resolve_dut_module` must be
    unchanged: it still resolves the graph-root for the same phantom-top shape
    (the fix is in step_yosys_synth only, sharing the SAME resolver)."""
    proj = _scaffold(
        tmp_path,
        {"core.sv": _ROOT_WRAPPING.format(root="core", child="sub"),
         "sub.sv": _LEAF.format(n="sub")},
        {"top_module": "the_top",
         "top_ports": [
             {"name": "clk", "direction": "input"},
             {"name": "rst_n", "direction": "input"},
             {"name": "q", "direction": "output", "width": 8}]})
    res = R.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status in ("PASS", "SKIP"), res.detail
    sim = _pl.sim_full_stack_dir(proj)
    tbs = sorted(sim.glob("tb_*_full.v"))
    assert tbs, "a full-stack TB must be emitted"
    tb = next((t for t in tbs if "core" in t.name), None)
    assert tb is not None, [t.name for t in tbs]
    txt = tb.read_text()
    assert "core u_dut" in txt
    assert "the_top u_dut" not in txt  # phantom never instantiated
