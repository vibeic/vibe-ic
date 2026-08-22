"""Regression for ORGANIC #656 — the clock/reset variant-alias wrapper EMITTER
drops the `import pkg::*;` clauses it consumed during parse, leaving
package-scoped port-width params undeclared in the generated outer wrapper.

現象 (round-3 v1.0.35 6-IC clean-room re-run): a REUSED-IP / IP-integration-
wrapper top is declared with the standard SystemVerilog ordering
`module chip_top import tlul_pkg::*; import top_pkg::*; #(params) (... [TL_AW-1:0]
port ...);` whose port widths are PACKAGE-SCOPED localparams (e.g. `TL_AW`,
`TL_DW`, `TL_SZW` are localparams inside `package top_pkg`). The #637 parse-side
fix consumes the `import pkg::*;` clauses so `parse_module_ports` returns all
ports past the imports — that fix is independently correct and still passes. But
`emit_variant_alias_wrapper` re-emitted ONLY the `#(...)` param block and the
port list, never the consumed imports, so the emitted outer wrapper referenced
bare package-scoped width identifiers with NO import in scope → a deterministic
SV elaboration error (`use of undeclared identifier` on slang/Verilator/VCS;
`Unable to bind parameter` on iverilog — same undeclared-identifier class) and a
hard synth FAIL. This surfaces only once the alias actually FIRES on an
import-pkg top (a non-canonical clock/reset spelling like `clk_i`→`clk`).

Fix: `_module_header` now also CAPTURES the consumed `import pkg::*;` clauses and
returns them as a third tuple element; `parse_module_imports` exposes them; and
`emit_variant_alias_wrapper` takes an `import_block` arg and re-emits the imports
in the wrapper header (right after `module <wrapper>`, before the `#(...)` param
header and the port list) so the package-scoped widths resolve on the outer
wrapper. #637's own positive case (the existing wrapper-emit / parse path) still
passes — this is a NEW emit-path facet, not a #637 regression.

A field agent reconstructing the pre-alias top (the on-disk
`chip_top__rcvar_inner` renamed back to `chip_top`, carrying
`import tlul_pkg::*; import top_pkg::*;` + package-scoped widths) observed the
emitted wrapper with grep-count 0 import clauses and N undeclared-identifier
errors; with the fix the wrapper carries both imports (grep-count 2) and
elaborates with 0 undeclared-identifier errors.

NEGATIVE no-leak: a header with NO imports emits NO spurious import line.

chip-AGNOSTIC: pure SV `import <ident>::*;` grammar + generic package-scoped
port-width handling; no chip / bus / vendor literal baked in.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import reset_clock_variant_alias as RCV  # noqa: E402


# A REUSED-IP top whose port widths are PACKAGE-SCOPED localparams, declared
# with the standard SV `module X import a_pkg::*; import b_pkg::*; #(p) (ports)`
# ordering. `clk_i` is a non-canonical clock spelling → the alias FIRES
# (clk_i → clk), so the wrapper is actually emitted.
def _import_pkg_top(module: str) -> str:
    return (
        f"module {module}\n"
        "  import tlul_pkg::*;\n"
        "  import top_pkg::*;\n"
        "#(\n"
        "  parameter int FOO = 1\n"
        ") (\n"
        "  input  logic clk_i,\n"
        "  input  logic rst_ni,\n"
        "  input  logic [TL_AW-1:0]  addr_i,\n"
        "  input  logic [TL_SZW-1:0] size_i,\n"
        "  input  logic [TL_DBW-1:0] be_i,\n"
        "  output logic [TL_DW-1:0]  data_o\n"
        ");\n"
        "  assign data_o = '0;\nendmodule\n"
    )


# The packages whose localparams the widths above reference.
_PKGS = (
    "package top_pkg;\n"
    "  localparam int TL_AW  = 32;\n"
    "  localparam int TL_DW  = 32;\n"
    "  localparam int TL_SZW = 3;\n"
    "endpackage\n"
    "package tlul_pkg;\n"
    "  localparam int TL_DBW = 4;\n"
    "endpackage\n"
)


def _emit_wrapper(inner_text: str, inner: str, wrapper: str) -> str:
    ports = RCV.parse_module_ports(inner_text, inner)
    plan = RCV.plan_aliases([p[2] for p in ports])
    pblock, pnames = RCV.parse_module_params(inner_text, inner)
    iblock = RCV.parse_module_imports(inner_text, inner)
    return RCV.emit_variant_alias_wrapper(
        inner, ports, plan, wrapper_name=wrapper,
        param_block=pblock, param_names=pnames, import_block=iblock)


# ── parse-side capture ───────────────────────────────────────────────────────

def test_module_header_returns_import_clauses():
    """`_module_header` returns a 3-tuple whose third element is the consumed
    `import pkg::*;` clauses (verbatim, in source order)."""
    txt = _import_pkg_top("chip_top")
    hdr = RCV._module_header(txt, "chip_top")
    assert hdr is not None
    param_block, port_block, imports = hdr
    assert imports == ["import tlul_pkg::*;", "import top_pkg::*;"]
    # The other two elements are unchanged (#637 parse path intact).
    assert "FOO" in (param_block or "")
    assert "clk_i" in port_block


def test_parse_module_imports_helper():
    txt = _import_pkg_top("chip_top")
    assert RCV.parse_module_imports(txt, "chip_top") == [
        "import tlul_pkg::*;", "import top_pkg::*;"]


# ── ACCEPTANCE: imports preserved in the emitted wrapper ─────────────────────

def test_wrapper_contains_both_import_clauses():
    """The emitted wrapper header CONTAINS both import clauses (grep-count 2),
    so the package-scoped port widths resolve. This is the core #656
    acceptance: previously the wrapper had grep-count 0."""
    wrapper = _emit_wrapper(_import_pkg_top("chip_top_inner"),
                            "chip_top_inner", "chip_top")
    assert "import tlul_pkg::*;" in wrapper
    assert "import top_pkg::*;" in wrapper
    # grep-count 2: exactly the two consumed clauses, no more, no less.
    assert wrapper.count("import ") == 2, wrapper
    # The alias actually fired (this is an emit-path facet, not a no-op): the
    # non-canonical clk_i is exposed as canonical clk and wired clk_i->clk.
    assert "input clk" in wrapper
    assert ".clk_i(clk)" in wrapper
    # The import header precedes the param header and the port list (so the
    # widths are in scope where they are used).
    i_import = wrapper.index("import tlul_pkg::*;")
    i_param = wrapper.index("parameter int FOO")
    i_width = wrapper.index("[TL_AW-1:0]")
    assert i_import < i_param < i_width, wrapper


# ── ACCEPTANCE: 0 undeclared-identifier elaboration errors ───────────────────

def _have_iverilog() -> bool:
    return shutil.which("iverilog") is not None


@pytest.mark.skipif(not _have_iverilog(), reason="iverilog not available")
def test_wrapper_elaborates_with_zero_undeclared_identifiers(tmp_path):
    """The emitted wrapper + its inner + the packages elaborate with 0
    undeclared-identifier errors. WITHOUT the fix the bare package-scoped
    widths (TL_AW/TL_DW/TL_SZW/TL_DBW) are undeclared in the wrapper and the
    frontend errors out; WITH the fix the re-emitted imports bring them into
    scope and elaboration is clean (exit 0)."""
    inner_text = _import_pkg_top("chip_top_inner")
    wrapper = _emit_wrapper(inner_text, "chip_top_inner", "chip_top")

    src = tmp_path / "design.sv"
    # package decls + the renamed inner + the generated wrapper, single file.
    src.write_text(_PKGS + inner_text + wrapper)

    proc = subprocess.run(
        ["iverilog", "-g2012", "-s", "chip_top", "-o", str(tmp_path / "a.out"),
         str(src)],
        capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    # No undeclared-identifier-class error. slang/Verilator phrase it as
    # "use of undeclared identifier"; iverilog as "Unable to bind parameter".
    low = out.lower()
    assert "use of undeclared identifier" not in low, out
    assert "unable to bind parameter" not in low, out
    assert proc.returncode == 0, out


@pytest.mark.skipif(not _have_iverilog(), reason="iverilog not available")
def test_wrapper_WITHOUT_imports_FAILS_elaboration_baseline(tmp_path):
    """Baseline that proves the test has teeth: the SAME wrapper with the
    import clauses STRIPPED OUT does NOT elaborate — the package-scoped widths
    are undeclared. (Confirms the fix is what makes the positive case pass, not
    a frontend that ignores the imports.)"""
    inner_text = _import_pkg_top("chip_top_inner")
    wrapper = _emit_wrapper(inner_text, "chip_top_inner", "chip_top")
    # Strip the imports from the WRAPPER header only (simulate the pre-fix
    # emitter). The inner keeps its imports; only the outer wrapper loses them.
    w_lines = wrapper.splitlines()
    w_stripped = "\n".join(
        ln for ln in w_lines if "import " not in ln) + "\n"
    assert w_stripped.count("import ") == 0

    src = tmp_path / "design_bad.sv"
    src.write_text(_PKGS + inner_text + w_stripped)
    proc = subprocess.run(
        ["iverilog", "-g2012", "-s", "chip_top", "-o", str(tmp_path / "a.out"),
         str(src)],
        capture_output=True, text=True)
    assert proc.returncode != 0, (
        "pre-fix wrapper (no imports) should FAIL elaboration but passed")


# ── NEGATIVE no-leak: no imports → no spurious import line ───────────────────

def _no_import_top(module: str) -> str:
    return (
        f"module {module}\n"
        "#(\n"
        "  parameter int W = 8\n"
        ") (\n"
        "  input  logic clk_i,\n"
        "  input  logic rst_ni,\n"
        "  output logic [W-1:0] q\n"
        ");\n"
        "  assign q = '0;\nendmodule\n"
    )


def test_no_imports_emits_no_spurious_import_line_NOLEAK():
    """A top with NO `import` clause emits a wrapper with NO import line — the
    fix must not fabricate imports."""
    txt = _no_import_top("plain_inner")
    assert RCV.parse_module_imports(txt, "plain_inner") == []
    wrapper = _emit_wrapper(txt, "plain_inner", "plain_top")
    assert "import " not in wrapper, wrapper
    # The alias still fires on the plain top (clk_i -> clk).
    assert ".clk_i(clk)" in wrapper


def test_explicit_empty_import_block_emits_nothing():
    """Passing import_block=None or [] explicitly emits no import line."""
    txt = _no_import_top("plain_inner")
    ports = RCV.parse_module_ports(txt, "plain_inner")
    plan = RCV.plan_aliases([p[2] for p in ports])
    pblock, pnames = RCV.parse_module_params(txt, "plain_inner")
    for ib in (None, []):
        w = RCV.emit_variant_alias_wrapper(
            "plain_inner", ports, plan, wrapper_name="plain_top",
            param_block=pblock, param_names=pnames, import_block=ib)
        assert "import " not in w, (ib, w)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
