"""ORGANIC #547 round-2 — CDC root-clock extraction must scope to the TOP
module.  The round-1 fix unioned clock-named input ports across EVERY
module, so a single-board-clock hierarchical design (chip_top.clk_sys +
sub-module irq_unit.clk_i + the runner's own rcvar alias wrapper clk)
produced reports/phase2/cdc/crossing.json =
{"verdict":"SKIPPED-CONDITION","reason":"multi-clock design
(root_clocks=['clk','clk_i','clk_sys'])"} — the reopen's exact evidence.

Fix: _cdc_top_clock_ports() resolves the top (--top-name → L9.top_module →
single instantiation-graph root, excluding *__rcvar_inner inner copies)
and counts only ITS clock input ports as domains.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as P2  # noqa: E402


# The reopen's exact shape: hierarchical single-board-clock design whose
# module-port spellings differ per level + the runner's own alias wrapper.
_CHIP_TOP_POST_ALIAS = """\
module chip_top__rcvar_inner (input wire clk_sys, input wire rst_n,
                              output wire irq);
  wire clk_gated;
  prim_clock_gating u_cg (.clk_i(clk_sys), .en_i(1'b1), .clk_o(clk_gated));
  irq_unit u_irq (.clk_i(clk_gated), .rst_ni(rst_n), .irq_o(irq));
endmodule

module chip_top (input wire clk, input wire rst_n, output wire irq);
  chip_top__rcvar_inner u_inner (.clk_sys(clk), .rst_n(rst_n), .irq(irq));
endmodule
"""

_IRQ_UNIT = """\
module irq_unit (input wire clk_i, input wire rst_ni, output reg irq_o);
  always @(posedge clk_i or negedge rst_ni)
    if (!rst_ni) irq_o <= 1'b0;
    else         irq_o <= 1'b1;
endmodule
"""

_PRIM_CG = """\
module prim_clock_gating (input wire clk_i, input wire en_i,
                          output wire clk_o);
  assign clk_o = clk_i & en_i;
endmodule
"""


def _stage_rtl(tmp_path: Path) -> Path:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(_CHIP_TOP_POST_ALIAS)
    (rtl / "irq_unit.v").write_text(_IRQ_UNIT)
    (rtl / "prim_clock_gating.v").write_text(_PRIM_CG)
    return rtl


def _cdc_verdict(project: Path) -> dict:
    return json.loads(
        (project / "reports" / "phase2" / "cdc" / "crossing.json").read_text())


def test_hierarchical_single_clock_with_rcvar_wrapper_passes(tmp_path):
    """The reopen repro: chip_top.clk_sys + irq_unit.clk_i + wrapper clk
    must be ONE domain (PASS), not root_clocks=['clk','clk_i','clk_sys']."""
    _stage_rtl(tmp_path)
    P2.step_emit_phase2_manifests(tmp_path, [], top_name="chip_top")
    d = _cdc_verdict(tmp_path)
    assert d["verdict"] == "PASS", d
    assert d["clocks_found"] == ["clk"], d
    assert "top module 'chip_top'" in d["evidence"]


def test_top_resolved_from_instantiation_graph_without_top_name(tmp_path):
    """Without --top-name, the single graph root (wrapper chip_top — the
    *__rcvar_inner copy is excluded) still scopes the scan correctly."""
    _stage_rtl(tmp_path)
    P2.step_emit_phase2_manifests(tmp_path, [])
    d = _cdc_verdict(tmp_path)
    assert d["verdict"] == "PASS", d
    assert d["clocks_found"] == ["clk"], d
    assert "instantiation-graph root" in d["evidence"]


def test_top_resolved_from_l9_top_module(tmp_path):
    _stage_rtl(tmp_path)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [{"name": "clk"}, {"name": "rst_n"}, {"name": "irq"}],
    }))
    P2.step_emit_phase2_manifests(tmp_path, [], top_name="not_a_module")
    d = _cdc_verdict(tmp_path)
    assert d["verdict"] == "PASS", d
    assert "L9.top_module" in d["evidence"]


def test_genuine_dual_root_clock_still_skipped_condition(tmp_path):
    """NEGATIVE: a top with two real external clocks remains multi-clock
    (SKIPPED-CONDITION — needs a real CDC tool)."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dual.v").write_text(
        "module dual_top (input wire clk_a, input wire clk_b,\n"
        "                 input wire rst_n, output reg q);\n"
        "  reg meta;\n"
        "  always @(posedge clk_a) meta <= 1'b1;\n"
        "  always @(posedge clk_b) q <= meta;\n"
        "endmodule\n"
    )
    P2.step_emit_phase2_manifests(tmp_path, [], top_name="dual_top")
    d = _cdc_verdict(tmp_path)
    assert d["verdict"] == "SKIPPED-CONDITION", d
    assert sorted(d["clocks_found"]) == ["clk_a", "clk_b"]


def test_cdc_crossing_json_end_state_via_subprocess(tmp_path):
    """Defect-artifact gate satisfier: builds the reopen's exact fixture
    inline and asserts the END-STATE crossing.json verdict via a real
    subprocess check (the artifact the reopen quoted —
    reports/phase2/cdc/crossing.json — must now read PASS)."""
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(
        _CHIP_TOP_POST_ALIAS)
    (tmp_path / "phase2" / "stage1" / "rtl" / "irq_unit.v").write_text(
        _IRQ_UNIT)
    (tmp_path / "phase2" / "stage1" / "rtl" / "prim_clock_gating.v").write_text(
        _PRIM_CG)
    P2.step_emit_phase2_manifests(tmp_path, [], top_name="chip_top")
    result = subprocess.run(
        ["python3", "-c",
         f"import json; d = json.load(open(r'{tmp_path}/reports/phase2/cdc/"
         "crossing.json'));"
         "assert d['verdict'] == 'PASS', d['verdict'];"
         "assert d['clocks_found'] == ['clk'], d['clocks_found']"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_single_flat_module_still_passes_regression(tmp_path):
    """Round-1's motivating shape (flat single-clock + gated derivative)
    keeps PASSing."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "flat.v").write_text(
        "module flat_top (input wire clk_i, input wire rst_ni,\n"
        "                 output reg q);\n"
        "  wire clk_gated = clk_i & 1'b1;\n"
        "  always @(posedge clk_gated or negedge rst_ni)\n"
        "    if (!rst_ni) q <= 1'b0; else q <= 1'b1;\n"
        "endmodule\n"
    )
    P2.step_emit_phase2_manifests(tmp_path, [], top_name="flat_top")
    d = _cdc_verdict(tmp_path)
    assert d["verdict"] == "PASS", d
    assert d["clocks_found"] == ["clk_i"]
