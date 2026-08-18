"""ORGANIC #661 — full-stack TB-gen instantiated a PHANTOM DUT module name.

`step_full_stack_tb_gen` did `top_module = l9.get("top_module") or top_name`.
`L9.top_module` is frequently the `l1_ic_name_fallback` (a product / SKU name,
e.g. a SoC project name) — NOT a real RTL module. Binding the TB to it emits
`<phantom> u_dut (...)` → iverilog "Unknown module type: <phantom>" → the
full-stack / reference TB FAILs → the whole Phase-2 chain is blocked even though
the RTL is correct. The #629 reconcile only fixes the top PORTS, not the top
MODULE name, so it never caught this.

Fix: `_v661_resolve_dut_module` resolves the DUT STRUCTURALLY against rtl/:
  (a) --top-name when it names a real module in rtl/;
  (b) L9.top_module ONLY when it names a real module in rtl/;
  (c) the single instantiation-graph root among rtl/ modules;
  (d) None (caller keeps legacy fallback) when unresolvable.
NEVER returns a name absent from rtl/. chip-AGNOSTIC.

Positive: an L9 whose top_module == ic_name (NOT a real module) + a 3-module
rtl/ (wrapper instantiates leaf instantiates counter) → resolves to the wrapper
(the inst-graph root), the emitted TB instantiates the REAL module, and the
phantom ic_name NEVER appears as the DUT.
Negative no-leak: the ic_name (phantom) is NEVER selected as the DUT when it is
absent from rtl/; --top-name is honoured ONLY when it is a real module.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


# the field-agent's exact caravel topology, chip-AGNOSTICally generalised: an
# ic_name (`acme_product`) that is NOT a real module, a wrapper that
# instantiates a leaf that instantiates a counter.
_WRAPPER = """\
module proj_wrapper (
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] dout
);
    proj_leaf u_leaf (.clk(clk), .rst_n(rst_n), .dout(dout));
endmodule
"""
_LEAF = """\
module proj_leaf (
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] dout
);
    counter #(.BITS(8)) u_cnt (.clk(clk), .rst_n(rst_n), .q(dout));
endmodule
"""
_COUNTER = """\
module counter #(parameter BITS = 8) (
    input  wire clk,
    input  wire rst_n,
    output reg  [BITS-1:0] q
);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) q <= 0; else q <= q + 1'b1;
endmodule
"""


def _scaffold(tmp_path, ic_name="acme_product", top_ports=None):
    """Build a minimal project: 3-module rtl/ + an L9 whose top_module is the
    ic_name fallback (a NON-module product name)."""
    import json
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "proj_wrapper.v").write_text(_WRAPPER)
    (rtl / "proj_leaf.v").write_text(_LEAF)
    (rtl / "counter.v").write_text(_COUNTER)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    l9 = {
        "top_module": ic_name,  # the l1_ic_name_fallback — NOT a real module
        "top_ports": top_ports if top_ports is not None else [
            {"name": "clk", "direction": "input"},
            {"name": "rst_n", "direction": "input"},
            {"name": "dout", "direction": "output", "width": 8},
        ],
    }
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    return proj


# ── resolver unit: never picks the phantom ic_name ─────────────────────────

def test_resolver_picks_inst_graph_root_not_phantom_ic_name(tmp_path):
    proj = _scaffold(tmp_path)
    # top_name=chip_top is NOT a module here → falls through to inst-graph root.
    dut = R._v661_resolve_dut_module(proj, "chip_top", "acme_product")
    assert dut == "proj_wrapper"          # the inst-graph root
    assert dut != "acme_product"          # NO-LEAK: phantom never selected


def test_resolver_honours_top_name_when_real_module(tmp_path):
    proj = _scaffold(tmp_path)
    # --top-name names a REAL leaf module → honoured over the inst-graph root.
    assert R._v661_resolve_dut_module(proj, "proj_leaf", "acme_product") \
        == "proj_leaf"


def test_resolver_uses_l9_top_module_only_when_real(tmp_path):
    proj = _scaffold(tmp_path)
    # L9.top_module that IS a real module is honoured (not overridden by root).
    assert R._v661_resolve_dut_module(proj, "chip_top", "counter") == "counter"


def test_resolver_ignores_phantom_l9_top_module(tmp_path):
    proj = _scaffold(tmp_path, ic_name="not_a_module")
    # phantom L9.top_module is skipped; resolver falls to the inst-graph root.
    assert R._v661_resolve_dut_module(proj, "chip_top", "not_a_module") \
        == "proj_wrapper"


def test_resolver_none_when_no_rtl(tmp_path):
    import json
    # NO-REGRESSION: no rtl/ at all → None so the caller keeps legacy fallback.
    proj = tmp_path / "nortl"
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "x", "top_ports": []}))
    assert R._v661_resolve_dut_module(proj, "chip_top", "x") is None


def test_module_names_lists_all_three(tmp_path):
    proj = _scaffold(tmp_path)
    assert set(R._v661_rtl_module_names(proj)) == {
        "proj_wrapper", "proj_leaf", "counter"}


# ── end-to-end: emitted TB instantiates the REAL module, not the phantom ───

def test_emitted_tb_instantiates_real_module_not_phantom(tmp_path):
    proj = _scaffold(tmp_path)
    res = R.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status in ("PASS", "SKIP"), res.detail
    sim = _pl.sim_full_stack_dir(proj)
    tbs = sorted(sim.glob("tb_*_full.v"))
    assert tbs, "a full-stack TB must be emitted"
    # the TB filename + the u_dut instantiation must reference the REAL module.
    tb = next((t for t in tbs if "proj_wrapper" in t.name), None)
    assert tb is not None, [t.name for t in tbs]
    txt = tb.read_text()
    assert "proj_wrapper u_dut" in txt
    # NO-LEAK: the phantom ic_name must NEVER be instantiated as the DUT.
    assert "acme_product u_dut" not in txt
    assert "module acme_product" not in txt
