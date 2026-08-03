"""ORGANIC — chip_top auto-emit + catalog-glue de-dup, two coupled defects a
reused-IP SoC (OpenTitan-style) surfaces:

  A. The DUT selector's module regex required `#`/`(` to IMMEDIATELY follow the
     module name, so a module whose SV-2012 header carries `import <pkg>::*;`
     clauses BEFORE the parameter/port list — `module aes import aes_pkg::*;
     import aes_reg_pkg::*; #( … ) ( … );` — was invisible. The emitter then
     wrapped an unrelated leaf that DID match (e.g. `prim_clock_buf`), so the
     "design" synthesised was a clock buffer, not the accelerator.

  B. Even once the real top is discovered, its parameter types/defaults and
     port types are package-scoped (`sbox_impl_e SecSBoxImpl = SBoxImplDom`,
     `tlul_pkg::tl_h2d_t tl_i`). The pass-through wrapper copied the param/port
     block but NOT the DUT's `import` clauses, so every package symbol was an
     undeclared identifier in the wrapper scope and slang rejected it — though
     the DUT itself elaborates cleanly.

  C. A vendor bundle can stage the SAME module under two filenames as a
     BYTE-IDENTICAL copy (`tlul_adapter_vh.sv` + `tlul_adapter_shim.sv`). Both
     reach the flat synth glob and yosys-slang aborts raw on "duplicate
     definition". Dropping a byte-identical copy cannot change synthesis (the
     module stays defined by the canonical), so the crash-gate de-dups and
     proceeds — while a variant that DIFFERS still hard-FAILs for the author.

Each assertion below is RED on the pre-fix code and GREEN after. chip-AGNOSTIC:
no chip/vendor/package literal is required by the logic under test — the
fixtures name packages only to exercise the grammar.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import design_one_shot_runner as d  # noqa: E402


IMPORT_TOP = """\
// header comment
`include "x.svh"
module widget
  import foo_pkg::*;
  import bar_pkg::*;
#(
  parameter foo_t P = FooDefault,
  parameter int unsigned W = 8
) (
  input  logic         clk_i,
  input  logic [W-1:0] d_i,
  output bar_t         y_o
);
endmodule
"""


def test_import_header_module_is_discovered_not_invisible():
    """A. `module widget import ...; #(...) (...)` parses to a real port block."""
    scan = d._chip_top_mask_comments(IMPORT_TOP)
    mod_re = re.compile(r"^\s*module\s+([A-Za-z_]\w*)\b", re.M)
    m = mod_re.search(scan)
    assert m and m.group(1) == "widget"
    param_block, port_block = d._chip_top_extract_param_and_ports(scan, m.end())
    # Pre-fix: the name-only regex did not exist and the `[(#]` form saw
    # `import`, so (None, None). Post-fix: real param + port blocks.
    assert port_block is not None, "import-header module must not be invisible"
    assert "clk_i" in port_block and "y_o" in port_block
    assert param_block and "parameter" in param_block


def test_wrapper_reemits_dut_package_imports():
    """B. The emitted wrapper carries the DUT's `import` clauses verbatim."""
    scan = d._chip_top_mask_comments(IMPORT_TOP)
    m = re.search(r"\bmodule\s+widget\b", scan)
    imp = d._chip_top_extract_header_imports(scan, IMPORT_TOP, m.end())
    assert "import foo_pkg::*;" in imp
    assert "import bar_pkg::*;" in imp


def test_no_import_module_header_unchanged():
    """B. A module that imports nothing yields an empty import header (the
    historical wrapper shape is byte-identical for the common case)."""
    txt = "module plain #(parameter N = 4) (input a, output b);\nendmodule\n"
    scan = d._chip_top_mask_comments(txt)
    m = re.search(r"\bmodule\s+plain\b", scan)
    imp = d._chip_top_extract_header_imports(scan, txt, m.end())
    assert imp == ""


def test_full_autoemit_prefers_import_top_over_matching_leaf(tmp_path):
    """A+B end-to-end: given an import-header top whose ports agree with L9 and
    a small leaf that also parses, the emitter wraps the TOP and the wrapper
    both instantiates it and imports its packages."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "widget.sv").write_text(IMPORT_TOP)
    # a leaf that DID match the old regex — the historical mis-pick
    (rtl / "leaf_buf.sv").write_text(
        "module leaf_buf (input clk_i, output clk_o);\n"
        "  assign clk_o = clk_i;\nendmodule\n")
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        '{"top_module": "chip_top", "top_ports": '
        '[{"name": "clk_i"}, {"name": "d_i"}, {"name": "y_o"}]}')
    res = d._autoemit_chip_top_wrapper(proj, rtl, "chip_top")
    assert res is not None, "emitter must produce a wrapper"
    body = Path(res).read_text()
    assert "widget" in body and "u_dut" in body, "must wrap the import-header top"
    assert "leaf_buf" not in body, "must NOT wrap the matching leaf"
    assert "import foo_pkg::*;" in body and "import bar_pkg::*;" in body


def test_byte_identical_duplicate_module_is_dedup_safe():
    """C. Two byte-identical files declaring the same module — the resolver's
    canonical/variant split lets the runner drop the redundant copy safely."""
    import catalog_glue_closure_resolver as cg
    # canonical vs a verbatim copy under a different stem
    canon = Path("tlul_adapter_vh.sv")
    variant = Path("tlul_adapter_shim.sv")
    c, variants = cg._canonical_pick("tlul_adapter_vh", [variant, canon])
    assert c == canon, "filename==module name is canonical"
    assert variants == [variant], "the shim is the drop candidate"
