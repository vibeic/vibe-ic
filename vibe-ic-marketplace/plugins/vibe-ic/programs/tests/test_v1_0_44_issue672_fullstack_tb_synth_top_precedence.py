"""ORGANIC #672 — full-stack TB DUT module-name resolution ignored the
phase2_synth_top / L9.synth_top precedence chain.

`step_full_stack_tb_gen` derived the DUT from `l9.get("top_module") or top_name`
(via `_v661_resolve_dut_module`) and never consulted the SAME override precedence
`step_yosys_synth` uses (waivers.json:phase2_synth_top → L9.synth_top →
<top>_asic autodetect → top_name). For a reused-IP / catalog-glue design whose
Phase-1 doc-extraction truthfully lifts a doc-prose integration top name (e.g.
"the main module is named X_top") that is NOT shipped in the staged vendor rtl/,
the TB bound `<phantom> u_dut` → iverilog "Unknown module type". The synth step
recovered (it honors phase2_synth_top); the TB step did not — a same-runner
asymmetry.

Fix: `_v672_synth_top_override` reads waivers.json:phase2_synth_top → L9.synth_top
(the SAME source of truth as step_yosys_synth), and `_v661_resolve_dut_module`
consults it at HIGHEST precedence (a0) — but ONLY when the resolved name names a
real module DEFINED in rtl/, so a phantom override never reintroduces the bug.

Positive: a phantom L9.top_module + a real phase2_synth_top present in rtl/ →
the TB binds the synth-top module (matches what synth binds).
NO-LEAK: a phantom synth-override absent from rtl/ is NEVER bound (falls through
to the real L9.top_module / inst-graph root); #661's positive case (phantom
L9.top_module → inst-graph root) is preserved when no synth-override is set.

chip-AGNOSTIC: structural key lookup + module-present-in-rtl check; no chip /
vendor / SKU literal.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


# A reused-IP topology: vendor rtl/ ships a core + a sibling (so the inst-graph
# root is AMBIGUOUS → #661's (c) returns None), but NOT the doc-prose phantom
# integration top. chip-AGNOSTICally renamed from the field caravel/ibex shape.
_CORE = """\
module vendor_core (input clk, input rst_n, output [7:0] dout);
  vendor_alu u_alu (.clk(clk), .rst_n(rst_n), .dout(dout));
endmodule
"""
_ALU = "module vendor_alu (input clk, input rst_n, output [7:0] dout); endmodule\n"
# a second standalone root so the instantiation-graph has >1 root (ambiguous).
_AUX = "module vendor_aux (input clk); endmodule\n"


def _scaffold(tmp_path, *, l9_top, synth_top=None, waiver_synth_top=None,
              top_ports=None):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "vendor_core.sv").write_text(_CORE)
    (rtl / "vendor_alu.sv").write_text(_ALU)
    (rtl / "vendor_aux.sv").write_text(_AUX)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    l9 = {
        "top_module": l9_top,
        "top_ports": top_ports if top_ports is not None else [
            {"name": "clk", "direction": "input"},
            {"name": "rst_n", "direction": "input"},
            {"name": "dout", "direction": "output", "width": 8},
        ],
    }
    if synth_top is not None:
        l9["synth_top"] = synth_top
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    if waiver_synth_top is not None:
        (proj / "waivers.json").write_text(
            json.dumps({"phase2_synth_top": waiver_synth_top}))
    return proj


# ── override helper precedence ──────────────────────────────────────────────

def test_override_prefers_waiver_over_l9_synth_top(tmp_path):
    proj = _scaffold(tmp_path, l9_top="phantom_top",
                     synth_top="from_l9", waiver_synth_top="from_waiver")
    assert R._v672_synth_top_override(proj) == "from_waiver"


def test_override_falls_to_l9_synth_top(tmp_path):
    proj = _scaffold(tmp_path, l9_top="phantom_top", synth_top="from_l9")
    assert R._v672_synth_top_override(proj) == "from_l9"


def test_override_none_when_neither_present(tmp_path):
    proj = _scaffold(tmp_path, l9_top="vendor_core")
    assert R._v672_synth_top_override(proj) is None


# ── resolver consults the override at highest precedence ────────────────────

def test_resolver_binds_synth_top_over_phantom_l9_top(tmp_path):
    # field scenario: L9.top_module is a phantom doc-prose top NOT in rtl/;
    # phase2_synth_top names the real core. The TB must bind the real core.
    proj = _scaffold(tmp_path, l9_top="phantom_top",
                     waiver_synth_top="vendor_core")
    dut = R._v661_resolve_dut_module(proj, "chip_top", "phantom_top")
    assert dut == "vendor_core"
    assert dut != "phantom_top"


def test_resolver_binds_l9_synth_top_over_phantom_l9_top(tmp_path):
    proj = _scaffold(tmp_path, l9_top="phantom_top", synth_top="vendor_core")
    assert R._v661_resolve_dut_module(proj, "chip_top", "phantom_top") \
        == "vendor_core"


def test_resolver_ignores_phantom_synth_override(tmp_path):
    # NO-LEAK: a synth-override that is ITSELF a phantom (absent from rtl/) must
    # NOT be bound — fall through to the real L9.top_module.
    proj = _scaffold(tmp_path, l9_top="vendor_core",
                     waiver_synth_top="also_phantom")
    dut = R._v661_resolve_dut_module(proj, "chip_top", "vendor_core")
    assert dut == "vendor_core"
    assert dut != "also_phantom"


def test_resolver_preserves_661_when_no_override(tmp_path):
    # NO-REGRESSION on #661: no synth-override + phantom L9.top_module → the
    # resolver still falls to the inst-graph root (here vendor_core, the one
    # module nobody else instantiates among the connected pair).
    proj = tmp_path / "p661"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "vendor_core.sv").write_text(_CORE)
    (rtl / "vendor_alu.sv").write_text(_ALU)  # only the connected pair → 1 root
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "phantom_top", "top_ports": []}))
    assert R._v661_resolve_dut_module(proj, "chip_top", "phantom_top") \
        == "vendor_core"


# ── end-to-end: the emitted TB instantiates the synth-top, not the phantom ──

def test_emitted_tb_binds_synth_top_not_phantom(tmp_path):
    proj = _scaffold(tmp_path, l9_top="phantom_top",
                     waiver_synth_top="vendor_core")
    res = R.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status in ("PASS", "SKIP"), res.detail
    sim = _pl.sim_full_stack_dir(proj)
    tb = sim / "tb_vendor_core_full.v"
    assert tb.is_file(), sorted(p.name for p in sim.glob("*"))
    txt = tb.read_text()
    assert "vendor_core u_dut" in txt
    # NO-LEAK: the phantom doc-prose top must NEVER be instantiated.
    assert "phantom_top u_dut" not in txt
    assert "module phantom_top" not in txt
    # and no phantom-named TB was emitted.
    assert not (sim / "tb_phantom_top_full.v").exists()
