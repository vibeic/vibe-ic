"""Transitive-cone reduction of a staged reused-IP RTL tree.

DEFECT (measured — opentitan_aes x sky130A, plugin v1.9.76):
  `reused_ip_rtl_consume` staged the ENTIRE 284-file vendor package FLAT into
  `phase2/stage1/rtl/` instead of the transitive cone of the declared top. Under
  the plugin's own preferred slang frontend the design then could not elaborate,
  with FOUR distinct errors, all consequences of over-staging:
    1. `aes_sbox.sv` instantiates `aes_sbox_dom` — a masked S-box variant the
       dataset EXCLUDED (shipped as `aes_sbox_dom.sv.unused-...`), selected by a
       chip_top parameter default → unknown module.
    2. `prim_ascon_duplex.sv` (an ORPHAN unrelated to the top) uses a macro no
       staged file defines → unknown macro.
    3. `prim_flash.sv` (another ORPHAN) → unknown macro.
    4. `tlul_adapter_shim.sv` + `tlul_adapter_vh.sv` both define `tlul_adapter_vh`
       → DUPLICATE definition.

FIX (chip-AGNOSTIC): reduce the staged set to the TRANSITIVE CONE of the resolved
  top (`rtl_transitive_cone.transitive_cone`). Orphans (2)(3) and out-of-cone
  duplicates (4) vanish; an in-cone duplicate is resolved canonically; packages
  are topologically ordered; a module the top INSTANTIATES that NO staged file
  DEFINES (1) is surfaced — and when the design SHIPPED it but it was excluded,
  the consume step DEGRADES LOUDLY (FAIL) rather than emitting a chip_top that
  references an absent module. A never-shipped instantiation (a black-box
  hard-macro) stays a non-gating advisory.

These tests assert the OBSERVABLE properties (which files survive, which module
is reported unresolved, whether a genuinely-correct alternative ELABORATES under
iverilog) — never an implementation internal — so they are a true control.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import rtl_transitive_cone as TC  # noqa: E402
import design_one_shot_runner as R  # noqa: E402


def _names(paths):
    return sorted(p.name for p in paths)


# ── (A) cone reduction drops ORPHAN files unrelated to the top ───────────────
def test_cone_drops_orphans(tmp_path):
    """A top that instantiates only `sub` keeps {top, sub} and DROPS an orphan
    file the top never reaches (the prim_ascon_duplex / prim_flash class)."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        "module top(input a, output b);\n sub u(.a(a),.b(b));\nendmodule\n")
    (d / "sub.v").write_text(
        "module sub(input a, output b);\n assign b=a;\nendmodule\n")
    (d / "orphan.v").write_text(
        "module orphan(input x, output y);\n assign y=x;\nendmodule\n")
    res = TC.transitive_cone("top", d)
    assert "top.v" in _names(res.cone_files)
    assert "sub.v" in _names(res.cone_files)
    assert "orphan.v" in _names(res.dropped_files)
    assert res.unresolved_modules == []


# ── (B) in-cone DUPLICATE resolved canonically (shim dropped, real kept) ─────
def test_in_cone_duplicate_resolved_by_stem(tmp_path):
    """When two IN-CONE files define the same module, the file whose STEM equals
    the module name is kept and the shim/stub is recorded as dropped — no
    DUPLICATE definition survives (the tlul_adapter_vh class)."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        "module top(input a, output b);\n adapter u(.a(a),.b(b));\nendmodule\n")
    # the REAL module — file stem matches module name
    (d / "adapter.v").write_text(
        "module adapter(input a, output b);\n"
        " assign b = a;  // the genuine implementation, longer body\n"
        " wire keep_alive = a & b;\nendmodule\n")
    # a SHIM re-declaring the same module from a differently-named file
    (d / "adapter_shim.v").write_text(
        "module adapter(input a, output b);\nassign b=a;\nendmodule\n")
    res = TC.transitive_cone("top", d)
    cone = _names(res.cone_files)
    assert "adapter.v" in cone            # stem-match kept
    assert "adapter_shim.v" not in cone   # shim dropped
    assert ("adapter", "adapter.v", "adapter_shim.v") in res.dropped_duplicates
    # observable: the cone has exactly ONE definer of `adapter`
    definers = [p for p in res.cone_files
                if "module adapter" in (p.read_text())]
    assert len(definers) == 1


# ── (C) BIDIRECTIONAL negative control, tied to real iverilog elaboration ────
_HAS_IVERILOG = shutil.which("iverilog") is not None


def _iverilog_elaborates(rtl_dir: Path, top: str) -> bool:
    srcs = sorted(str(p) for p in rtl_dir.glob("*.v"))
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", "-s", top,
                        "-o", "/dev/null", *srcs],
                       capture_output=True, text=True)
    return r.returncode == 0


def _mk_design(d: Path, with_variant: bool):
    d.mkdir(parents=True, exist_ok=True)
    (d / "chip_top.v").write_text(
        "module chip_top(input a, input b, output y);\n"
        " core u(.a(a),.b(b),.y(y));\nendmodule\n")
    (d / "core.v").write_text(
        "module core(input a, input b, output y);\n"
        " variant v(.a(a),.b(b),.y(y));\nendmodule\n")
    if with_variant:
        (d / "variant.v").write_text(
            "module variant(input a, input b, output y);\n"
            " assign y = a & b;\nendmodule\n")


def test_control_defect_present_is_flagged(tmp_path):
    """DEFECT PRESENT: the top's cone instantiates `variant` but NO file defines
    it → the cone reports it unresolved. Ground truth: iverilog ALSO refuses to
    elaborate the same tree — the observable and the tool agree."""
    d = tmp_path / "rtl"
    _mk_design(d, with_variant=False)
    res = TC.transitive_cone("chip_top", d)
    assert "variant" in res.unresolved_modules
    if _HAS_IVERILOG:
        assert not _iverilog_elaborates(d, "chip_top")


def test_control_correct_alternative_passes_and_elaborates(tmp_path):
    """CORRECT ALTERNATIVE: the SAME design WITH `variant.v` present → the cone
    reports NO unresolved module AND iverilog elaborates it. A guard that fired
    here would be a false positive."""
    d = tmp_path / "rtl"
    _mk_design(d, with_variant=True)
    res = TC.transitive_cone("chip_top", d)
    assert res.unresolved_modules == []
    assert "variant.v" in _names(res.cone_files)
    if _HAS_IVERILOG:
        assert _iverilog_elaborates(d, "chip_top")


# ── (D) topological package order: dependency before importer ────────────────
def test_topological_package_order(tmp_path):
    """A package imported by another is emitted BEFORE its importer, and all
    packages precede non-package RTL (single-unit elaboration needs a package
    declared before use)."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "b_pkg.sv").write_text(
        "package b_pkg;\n import a_pkg::*;\n localparam int W = a_pkg::N;\n"
        "endpackage\n")
    (d / "a_pkg.sv").write_text(
        "package a_pkg;\n localparam int N = 8;\nendpackage\n")
    (d / "m.sv").write_text(
        "module m; import b_pkg::*; endmodule\n")
    order = TC.topological_package_first(
        sorted(d.glob("*.sv")))
    names = [p.name for p in order]
    assert names.index("a_pkg.sv") < names.index("b_pkg.sv")   # dep first
    assert names.index("b_pkg.sv") < names.index("m.sv")       # pkgs before RTL


# ── (E) robustness: function calls / keywords / gate primitives NOT modules ──
def test_calls_and_gate_primitives_not_flagged_unresolved(tmp_path):
    """The instantiation scan must not mistake a function call `foo(...)`, a
    control keyword `for (...)`, or a Verilog gate primitive `nand u(...)` for an
    unresolved user module — else a correct design false-FAILs."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        "module top(input a, input b, output y, output z);\n"
        "  wire w;\n"
        "  nand g1 (w, a, b);\n"                # gate primitive
        "  xor  g2 (z, a, b);\n"                # gate primitive
        "  function automatic integer f(input integer x);\n"
        "    f = x + 1;\n  endfunction\n"
        "  integer r;\n"
        "  always @(*) begin\n"
        "    r = f(3);\n"                        # function call
        "    for (r = 0; r < 2; r = r + 1) ;\n"  # keyword + paren
        "  end\n"
        "  assign y = w;\nendmodule\n")
    res = TC.transitive_cone("top", d)
    assert res.unresolved_modules == []


# ── (F) top not defined → NO pruning (never regress a design we can't anchor) ─
def test_top_not_defined_no_pruning(tmp_path):
    """If the requested top is not among the staged sources the cone anchor is
    absent — return ALL files as the cone and drop NOTHING (no regression)."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "a.v").write_text("module a(input x, output y); assign y=x; endmodule\n")
    (d / "b.v").write_text("module b(input x, output y); assign y=x; endmodule\n")
    res = TC.transitive_cone("nonexistent_top", d)
    assert res.dropped_files == []
    assert len(res.cone_files) == 2
    assert not res.reduced


# ── (G) prune_to_cone moves out-of-cone aside (reversible, outside rtl/) ──────
def test_prune_moves_out_of_cone_files_aside(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        "module top(input a, output b); sub u(.a(a),.b(b)); endmodule\n")
    (d / "sub.v").write_text(
        "module sub(input a, output b); assign b=a; endmodule\n")
    (d / "orphan.v").write_text(
        "module orphan(input x, output y); assign y=x; endmodule\n")
    res = TC.transitive_cone("top", d)
    moved = TC.prune_to_cone(d, res)
    assert moved == ["orphan.v"]
    assert not (d / "orphan.v").exists()            # gone from rtl/
    assert (d.parent / "rtl_out_of_cone" / "orphan.v").is_file()  # preserved
    assert (d / "top.v").is_file() and (d / "sub.v").is_file()


# ── (H) integration: shipped-but-excluded FAILs; black-box stays advisory ────
def _write_l9(root: Path, top_module: str) -> None:
    import json
    p = root / "phase1" / "generated_docs"
    p.mkdir(parents=True, exist_ok=True)
    (p / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": top_module}))


def test_shipped_but_excluded_module_fails_loudly(tmp_path):
    """A top whose cone instantiates a module the design SHIPPED but that was
    dataset-EXCLUDED (present only as `<M>.sv.<suffix>`) makes the consume step
    DEGRADE LOUDLY (FAIL) naming the module — never a silent green."""
    vd = tmp_path / "input" / "vendor_rtl"
    vd.mkdir(parents=True)
    (vd / "widget.sv").write_text(
        "module widget(input a, output b);\n gadget_dom u(.a(a),.b(b));\n"
        "endmodule\n")
    # the selected variant was SHIPPED but EXCLUDED (a non-.sv extension)
    (vd / "gadget_dom.sv.unused-excluded").write_text(
        "module gadget_dom(input a, output b); assign b=a; endmodule\n")
    _write_l9(tmp_path, "chip_top")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "FAIL"
    assert "gadget_dom" in sr.extras.get("cone_unresolved_excluded", [])
    assert "shipped-but-excluded" in sr.detail


def test_blackbox_macro_stays_advisory_pass(tmp_path):
    """A top instantiating a module NEVER shipped as RTL (an intentional
    black-box hard-macro / std-cell resolved downstream by a LIB/LEF) is NOT a
    defect: the step stays PASS with a non-gating advisory. (Prevents a false
    FAIL on every SRAM/pad/std-cell instantiation.)"""
    vd = tmp_path / "input" / "vendor_rtl"
    vd.mkdir(parents=True)
    (vd / "widget.sv").write_text(
        "module widget(input a, output b);\n"
        " sky130_sram_2k u(.clk(a),.q(b));\nendmodule\n")
    # NOTE: no sky130_sram_2k source shipped anywhere → black-box
    _write_l9(tmp_path, "chip_top")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS"
    assert "sky130_sram_2k" in sr.extras.get("cone_unresolved_blackbox", [])
    assert "ADVISORY" in sr.detail


# ── (I) REPRODUCE on the real opentitan_aes vendor input, if present ─────────
def _find_aes_project() -> Path | None:
    """The opentitan_aes benchmark project root (needs both input/vendor_rtl and
    the real phase1/ L9 pin contract — chip_top's wrap-target resolution keys on
    L9's top-level pins to pick `aes`; a stub L9 would not reproduce)."""
    for anc in Path(__file__).resolve().parents:
        cand = anc / "benchmark-data" / "ic" / "opentitan_aes"
        if (cand / "input" / "vendor_rtl").is_dir() \
                and (cand / "phase1").is_dir():
            return cand
    return None


def test_reproduce_on_real_aes_vendor_input(tmp_path):
    """REPRODUCE on the real opentitan_aes vendor bundle when it ships in the
    checkout: the cone drops the orphans + shim and surfaces exactly the
    shipped-but-excluded masked S-box variant."""
    proj = _find_aes_project()
    if proj is None:
        pytest.skip("opentitan_aes benchmark project not present in this checkout")
    shutil.copytree(proj / "input" / "vendor_rtl",
                    tmp_path / "input" / "vendor_rtl")
    shutil.copytree(proj / "phase1", tmp_path / "phase1")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    remaining = {p.name for p in rtl.glob("*.sv")} | {p.name for p in rtl.glob("*.v")}
    # orphans + shim removed from the staged set
    assert not any("ascon" in n for n in remaining)
    assert "prim_flash.sv" not in remaining
    assert "tlul_adapter_shim.sv" not in remaining
    # the genuine top and its cone survive
    assert "aes.sv" in remaining and "aes_sbox.sv" in remaining
    # the excluded masked variant is the reported defect
    assert "aes_sbox_dom" in sr.extras.get("cone_unresolved_modules", [])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
