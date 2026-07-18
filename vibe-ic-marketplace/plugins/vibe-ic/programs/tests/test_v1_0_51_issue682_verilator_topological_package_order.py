"""ORGANIC #682 — verilator `--binary` SIM escape staged multi-package SV in
ALPHABETICAL (pkg-first) order, not TOPOLOGICAL (dependency) order.

The iverilog → sv2v ladder falls through to the verilator `--binary` SIM escape
(#657) on a REUSED-IP SystemVerilog closure with inter-dependent packages (pkg A
`import`s pkg B). The runner staged the `*_pkg.sv` files pkg-first but
ALPHABETICALLY (`_select_asic_rtl_sources`). verilator `--binary` does
SINGLE-PASS elaboration and errors "Package/class for '::' reference not found" /
"Reference to <type> before declaration (IEEE 1800-2023 6.18)" whenever a package
importing a later-sorted package is parsed first. iverilog / sv2v / yosys-slang
are multi-pass + order-tolerant, so ONLY the last (verilator) tier of the sim
ladder is order-sensitive.

Fix: `_v682_topological_package_order` parses each `*_pkg.sv`'s
`import <name>_pkg::` references, builds a dependency DAG over the staged package
set, and emits packages in dependency order (deps before dependents) AHEAD of the
non-package RTL. `_select_asic_rtl_sources` and the `_verilator_sim_escape`
staging both apply it. Cycles fall back to a stable order (never crash). Pure
import grammar; chip-AGNOSTIC.

POSITIVE: a chain `a_pkg` imports `b_pkg` imports `c_pkg` (alpha a<b<c) → the
emitted order is `c_pkg, b_pkg, a_pkg` (topological), packages before non-pkg.
§4.05 NEGATIVE no-leak: independent packages keep a stable (alphabetical) order;
a dependency cycle falls back gracefully without crash; non-package RTL still
comes after every package; the #668 -DSYNTHESIS stdrand retry signature still
returns retry=True (the order fix does not disturb the define-retry decision).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import synth_frontend as _sf  # noqa: E402


# ── A dependency chain: a_pkg → b_pkg → c_pkg (alphabetical a<b<c) ──────────
_A_PKG = "package a_pkg; import b_pkg::*; typedef logic t_a; endpackage\n"
_B_PKG = "package b_pkg; import c_pkg::*; typedef logic t_b; endpackage\n"
_C_PKG = "package c_pkg; typedef logic t_c; endpackage\n"
_DESIGN = "module design (input wire clk); import a_pkg::*; endmodule\n"


def _scaffold_chain(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "a_pkg.sv").write_text(_A_PKG)
    (rtl / "b_pkg.sv").write_text(_B_PKG)
    (rtl / "c_pkg.sv").write_text(_C_PKG)
    (rtl / "design.sv").write_text(_DESIGN)
    return rtl


# ── POSITIVE: dependency-first (topological) order ──────────────────────────

def test_selector_emits_packages_topologically(tmp_path):
    rtl = _scaffold_chain(tmp_path)
    names = [p.name for p in R._select_asic_rtl_sources(rtl)]
    # c (no deps) before b (imports c) before a (imports b).
    assert names.index("c_pkg.sv") < names.index("b_pkg.sv"), names
    assert names.index("b_pkg.sv") < names.index("a_pkg.sv"), names
    # the alphabetical order (a,b,c) is explicitly NOT what we emit.
    assert names.index("a_pkg.sv") > names.index("c_pkg.sv"), names


def test_topological_helper_direct(tmp_path):
    rtl = _scaffold_chain(tmp_path)
    pkgs = sorted(rtl.glob("*_pkg.sv"))  # alphabetical input: a, b, c
    assert [p.name for p in pkgs] == ["a_pkg.sv", "b_pkg.sv", "c_pkg.sv"]
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    assert out == ["c_pkg.sv", "b_pkg.sv", "a_pkg.sv"], out


# ── §4.05 NEGATIVE no-leak ──────────────────────────────────────────────────

def test_noleak_independent_packages_keep_stable_order(tmp_path):
    """Independent packages (no import edges) keep a STABLE (alphabetical)
    order — the topo sort must not reorder unrelated packages."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "x_pkg.sv").write_text("package x_pkg; typedef logic t; endpackage\n")
    (rtl / "y_pkg.sv").write_text("package y_pkg; typedef logic t; endpackage\n")
    (rtl / "z_pkg.sv").write_text("package z_pkg; typedef logic t; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    assert out == ["x_pkg.sv", "y_pkg.sv", "z_pkg.sv"], out


def test_noleak_dependency_cycle_falls_back_no_crash(tmp_path):
    """A package import cycle (m imports n, n imports m) must NOT crash; both
    members are emitted in a stable order (the SCC degrades gracefully)."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "m_pkg.sv").write_text("package m_pkg; import n_pkg::*; endpackage\n")
    (rtl / "n_pkg.sv").write_text("package n_pkg; import m_pkg::*; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = R._v682_topological_package_order(pkgs)  # must not raise
    names = [p.name for p in out]
    assert set(names) == {"m_pkg.sv", "n_pkg.sv"}, names
    assert len(names) == 2  # no member dropped or duplicated


def test_noleak_self_referential_import_no_crash(tmp_path):
    """A package importing ITS OWN symbol (a degenerate self-edge) is ignored
    (no self-dependency edge); a single package is returned unchanged."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "s_pkg.sv").write_text(
        "package s_pkg; import s_pkg::*; typedef logic t; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = R._v682_topological_package_order(pkgs)
    assert [p.name for p in out] == ["s_pkg.sv"]


def test_noleak_non_package_rtl_after_all_packages(tmp_path):
    rtl = _scaffold_chain(tmp_path)
    names = [p.name for p in R._select_asic_rtl_sources(rtl)]
    pkg_idx = [i for i, n in enumerate(names) if "pkg" in n]
    nonpkg_idx = [i for i, n in enumerate(names) if "pkg" not in n]
    assert pkg_idx and nonpkg_idx, names
    # every package index precedes every non-package index.
    assert max(pkg_idx) < min(nonpkg_idx), names
    assert "design.sv" in names


def test_noleak_import_of_non_staged_package_is_no_edge(tmp_path):
    """An import of a package NOT in the staged set adds no ordering edge — the
    staged packages still emit in a stable order (no phantom dependency)."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    # both import an external `foreign_pkg` that is never staged.
    (rtl / "p_pkg.sv").write_text(
        "package p_pkg; import foreign_pkg::*; typedef logic t; endpackage\n")
    (rtl / "q_pkg.sv").write_text(
        "package q_pkg; import foreign_pkg::*; typedef logic t; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    assert out == ["p_pkg.sv", "q_pkg.sv"], out


def test_noleak_668_synthesis_define_retry_still_fires():
    """The #682 ordering fix must NOT disturb the #668 -DSYNTHESIS retry: the
    verilator stdrand sim-only-construct signature still returns retry=True."""
    stderr = ("%Error: prim_cdc_rand_delay.sv:42: Duplicate declaration of "
              "signal: stdrand\n")
    retry, reason = _sf.verilator_should_retry_synthesis_define(
        stderr,
        rtl_text_blob=("module prim_cdc_rand_delay;\n`ifdef SIMULATION\n"
                       "  int dly; initial dly = $urandom;\n`else\n"
                       "  wire dly = 1'b0;\n`endif\nendmodule\n"),
        tb_text="module tb; initial $finish; endmodule\n")
    assert retry is True, reason
    # and a non-sim-only failure still does NOT retry (honesty preserved).
    retry2, _ = _sf.verilator_should_retry_synthesis_define(
        "%Error: real_design_bug.sv:10: syntax error\n")
    assert retry2 is False


# ── §4.05 NEGATIVE no-leak — round-2 adversarial: PHANTOM import edges ───────
# `import` text the SV compiler never treats as a real dependency must NOT
# create an ordering edge: (1) an `import` inside an inactive `ifdef-guarded arm
# (the compiler may never see it), and (2) an `import`-looking substring inside a
# STRING LITERAL (mere data). A phantom edge would either reorder independent
# packages (BREAK 1) or forge a FALSE CYCLE whose back-edge-skip fallback then
# emits a real dependency AFTER its dependent — reintroducing the exact
# single-pass verilator "before declaration" failure #682 exists to prevent
# (BREAK 2). Edges are now scanned on a string-blanked, `ifdef-region-removed
# view of the body.

def test_noleak_break1_ifdef_disabled_import_is_not_an_edge(tmp_path):
    """BREAK 1 — `a_pkg` has `import b_pkg` ONLY inside a `\\`ifdef NEVER` guard,
    `b_pkg` is independent → the guarded import must NOT create an edge, so the
    two stay in stable (alphabetical) order, NOT [b, a]."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "a_pkg.sv").write_text(
        "package a_pkg;\n`ifdef NEVER\n  import b_pkg::*;\n`endif\n"
        "  typedef logic t_a;\nendpackage\n")
    (rtl / "b_pkg.sv").write_text(
        "package b_pkg; typedef logic t_b; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    assert out == ["a_pkg.sv", "b_pkg.sv"], out
    # production selector mirrors the helper.
    sel = [p.name for p in R._select_asic_rtl_sources(rtl)]
    assert sel == ["a_pkg.sv", "b_pkg.sv"], sel


def test_noleak_break2_ifdef_phantom_false_cycle_real_dep_order(tmp_path):
    """BREAK 2 (the target bug) — real DAG low→mid→high (correct order
    [high, mid, low]); `high_pkg` carries a PHANTOM `import low_pkg` inside a
    `\\`ifdef DBG` guard. The phantom edge would forge a high↔low cycle whose
    back-edge-skip fallback emits high AFTER mid (which imports high) — a real
    dependency-after-dependent. With the guarded import ignored, the real chain
    emits [high, mid, low]."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "high_pkg.sv").write_text(
        "package high_pkg;\n`ifdef DBG\n  import low_pkg::*;\n`endif\n"
        "  typedef logic t_h;\nendpackage\n")
    (rtl / "mid_pkg.sv").write_text(
        "package mid_pkg; import high_pkg::*; typedef logic t_m; endpackage\n")
    (rtl / "low_pkg.sv").write_text(
        "package low_pkg; import mid_pkg::*; typedef logic t_l; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    assert out == ["high_pkg.sv", "mid_pkg.sv", "low_pkg.sv"], out
    # the critical invariant: high (imported by mid) emits BEFORE mid.
    assert out.index("high_pkg.sv") < out.index("mid_pkg.sv"), out
    # production selector mirrors the helper end-to-end.
    sel = [p.name for p in R._select_asic_rtl_sources(rtl)]
    assert sel == ["high_pkg.sv", "mid_pkg.sv", "low_pkg.sv"], sel


def test_noleak_break2_string_literal_phantom_false_cycle(tmp_path):
    """BREAK 2 string variant — the phantom edge comes from an `import`-looking
    substring inside a STRING LITERAL instead of an `\\`ifdef guard. Same real
    chain low→mid→high; the string is data, not a dependency → [high, mid, low]."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "high_pkg.sv").write_text(
        'package high_pkg; localparam string S = "import low_pkg::z"; '
        'typedef logic t_h; endpackage\n')
    (rtl / "mid_pkg.sv").write_text(
        "package mid_pkg; import high_pkg::*; typedef logic t_m; endpackage\n")
    (rtl / "low_pkg.sv").write_text(
        "package low_pkg; import mid_pkg::*; typedef logic t_l; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    assert out == ["high_pkg.sv", "mid_pkg.sv", "low_pkg.sv"], out
    assert out.index("high_pkg.sv") < out.index("mid_pkg.sv"), out


def test_noleak_unguarded_real_import_still_creates_edge(tmp_path):
    """The `ifdef/string gating must be SURGICAL: a genuine UNGUARDED `import`
    outside any guard still creates a real ordering edge, even when the same file
    ALSO has a separate guarded import that must be ignored."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    # a_pkg: real unguarded import of b_pkg + a guarded (ignored) import of c_pkg.
    (rtl / "a_pkg.sv").write_text(
        "package a_pkg;\n  import b_pkg::*;\n`ifdef X\n  import c_pkg::*;\n"
        "`endif\n  typedef logic t_a;\nendpackage\n")
    (rtl / "b_pkg.sv").write_text(
        "package b_pkg; typedef logic t_b; endpackage\n")
    (rtl / "c_pkg.sv").write_text(
        "package c_pkg; typedef logic t_c; endpackage\n")
    pkgs = sorted(rtl.glob("*_pkg.sv"))
    out = [p.name for p in R._v682_topological_package_order(pkgs)]
    # b (real dep) BEFORE a; c (guarded — no edge) keeps stable order.
    assert out.index("b_pkg.sv") < out.index("a_pkg.sv"), out
    assert "c_pkg.sv" in out
