"""Transitive-cone reduction of a staged reused-IP RTL tree.

DEFECT (measured — opentitan_aes x sky130A, plugin v1.9.76):
  `reused_ip_rtl_consume` staged the ENTIRE 281-file vendor package FLAT into
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
  duplicates (4) vanish; packages are topologically ordered; a module the top
  INSTANTIATES that NO staged file DEFINES (1) is surfaced by name.

THE GOVERNING PROPERTY — NEVER WORSE THAN STAGING EVERYTHING
  The unreduced flow stages the whole package, which on a duplicate produces a
  LOUD `already been declared` error: unmissable, and never a wrong answer. Two
  earlier revisions of this reducer instead moved the IMPLEMENTATION aside, kept
  a STUB, and returned a GREEN step running a stubbed-out design. That is
  strictly worse than the error it "fixed". So every test below is written
  against ONE contract:

      for every input, this step's outcome must be no worse than the outcome of
      staging everything — it must not drop a file the build needs, and it must
      not FAIL where the unreduced flow passes.

  Tests assert OBSERVABLE properties (which files survive, which module is
  reported, whether the staged tree ELABORATES under real iverilog and computes
  the RIGHT ANSWER under real vvp) — never an implementation internal.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import rtl_scan_scope as SCOPE  # noqa: E402
import rtl_transitive_cone as TC  # noqa: E402
import design_one_shot_runner as R  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None
_HAS_VVP = shutil.which("vvp") is not None
_needs_sim = pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_VVP),
                                reason="iverilog/vvp not installed")


def _names(paths):
    return sorted(p.name for p in paths)


def _write_l9(root: Path, top_module: str) -> None:
    p = root / "phase1" / "generated_docs"
    p.mkdir(parents=True, exist_ok=True)
    (p / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": top_module}))


def _mk_vendor_project(root: Path, files: dict, l9_top: str,
                       extra_input: dict | None = None) -> Path:
    vd = root / "input" / "vendor_rtl"
    vd.mkdir(parents=True, exist_ok=True)
    for n, t in files.items():
        (vd / n).write_text(t)
    for n, t in (extra_input or {}).items():
        p = root / "input" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    _write_l9(root, l9_top)
    return root


def _elaborate(rtl_dir: Path, top: str):
    """(rc, first_error). cwd is the staged dir, so `include resolves the way a
    real filelist-driven build resolves it."""
    srcs = sorted(p.name for p in rtl_dir.glob("*.sv")) + \
        sorted(p.name for p in rtl_dir.glob("*.v"))
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", "-s", top,
                        "-o", "/dev/null", *srcs],
                       capture_output=True, text=True, cwd=str(rtl_dir))
    return r.returncode, (r.stderr or r.stdout).strip()[:300]


def _run_tb(rtl_dir: Path, tb_src: str):
    """(rc, RESULT). Compiles the STAGED tree plus a TB and runs it."""
    (rtl_dir / "__tb.sv").write_text(tb_src)
    srcs = sorted(p.name for p in rtl_dir.glob("*.sv")) + \
        sorted(p.name for p in rtl_dir.glob("*.v"))
    r = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", "sim.out",
                        *srcs], capture_output=True, text=True,
                       cwd=str(rtl_dir))
    if r.returncode != 0:
        return r.returncode, None
    v = subprocess.run(["vvp", "sim.out"], capture_output=True, text=True,
                       cwd=str(rtl_dir))
    for line in v.stdout.splitlines():
        if line.startswith("RESULT="):
            return 0, int(line.split("=", 1)[1])
    return 0, None


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


# ════════════════════════════════════════════════════════════════════════════
# H1 — NO HEURISTIC MAY CHOOSE BETWEEN DUPLICATE DEFINERS.
#
# Two tie-breaks have been tried and both were refuted end-to-end, with real
# iverilog + vvp, on a design whose correct answer is RESULT=1:
#
#   min(len(raw))   "a shim is thin, keep the shortest"  -> kept the SHIM
#   stem == module  "M.sv IS M's file"                   -> kept the STUB,
#                                                           whenever the
#                                                           canonical-stem file
#                                                           IS the black-box stub
#
#   origin/main     3 staged, iverilog rc=2 'adapter' has already been declared
#   stem rule       impl moved aside, rc=0, vvp RESULT=0, step PASS  <- GREEN
#                                                                       and WRONG
#
# The `-y <dir>` `+libext` justification for the stem rule does not hold: every
# staged file is passed EXPLICITLY on the command line, and library search only
# applies to modules still unresolved AFTER all command-line files are read.
# ════════════════════════════════════════════════════════════════════════════

_STUB_HAS_CANONICAL_STEM = {
    "widget.sv":
        "module widget(input a, input c, output y);\n"
        "  adapter u_ad(.a(a), .c(c), .y(y));\n"
        "endmodule\n",
    # THE STUB — and it carries the canonical stem.
    "adapter.sv":
        "// technology black-box stub shipped by the vendor package\n"
        "module adapter(input a, input c, output y);\n"
        "  assign y = 1'b0;\n"
        "endmodule\n",
    # THE IMPLEMENTATION — a multi-module vendor bundle, the exact shape this
    # reducer exists for.
    "vendor_impl_bundle.sv":
        "module adapter(input a, input c, output y);\n"
        "  wire merged;\n"
        "  or_helper u_or(.p(a), .q(c), .r(merged));\n"
        "  assign y = merged;\n"
        "endmodule\n"
        "module or_helper(input p, input q, output r);\n"
        "  assign r = p | q;\n"
        "endmodule\n",
}

_TB_WIDGET = (
    "`timescale 1ns/1ps\n"
    "module tb;\n"
    "  reg a = 1'b1, c = 1'b0; wire y;\n"
    "  widget dut(.a(a), .c(c), .y(y));\n"
    "  initial begin\n"
    "    #10;\n"
    '    $display("RESULT=%0d", y);\n'
    "    $finish;\n"
    "  end\n"
    "endmodule\n")


def test_h1_stub_with_the_canonical_stem_is_never_the_winner(tmp_path):
    """The refutation of the stem rule, at cone level: `adapter.sv` is the STUB.
    Neither candidate may be dropped; both stay in the cone."""
    d = tmp_path / "rtl"
    d.mkdir()
    for n, t in _STUB_HAS_CANONICAL_STEM.items():
        (d / n).write_text(t)
    res = TC.transitive_cone("adapter" and "widget", d)
    cone = _names(res.cone_files)
    assert "adapter.sv" in cone, cone
    assert "vendor_impl_bundle.sv" in cone, cone      # IMPLEMENTATION SURVIVES
    assert res.dropped_files == [], res.dropped_files
    assert res.duplicate_definers == [
        ("adapter", ["adapter.sv", "vendor_impl_bundle.sv"])]
    assert res.conditional_duplicates == []
    assert res.hard_duplicates == [
        ("adapter", ["adapter.sv", "vendor_impl_bundle.sv"])]


@_needs_sim
def test_h1_stub_with_canonical_stem_never_green_with_the_wrong_answer(tmp_path):
    """END-TO-END GROUND TRUTH, the property that actually matters: the staged
    tree must NEVER be one that elaborates cleanly and computes the WRONG
    answer. Either the duplicate is still there for the frontend to reject, or
    the answer is right. The regressed behaviour was rc=0 + RESULT=0 + PASS."""
    _mk_vendor_project(tmp_path, _STUB_HAS_CANONICAL_STEM, "widget")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    staged = {p.name for p in rtl.glob("*.sv")}
    assert "vendor_impl_bundle.sv" in staged, staged
    rc, result = _run_tb(rtl, _TB_WIDGET)
    if rc == 0:
        assert result == 1, "green flow computing the WRONG answer (stub kept)"
    else:
        # the loud duplicate-definition error — exactly what origin/main gives
        assert "already been declared" in _elaborate(rtl, "widget")[1]
    # and it is named, not silent
    assert "DUPLICATE" in sr.detail
    assert "adapter.sv" in sr.detail and "vendor_impl_bundle.sv" in sr.detail


def test_h1_case_differing_stems_are_not_a_tie_break_either(tmp_path):
    """`M.sv` (stub) vs `m.sv` (impl): a case-sensitive stem match would drop
    the implementation on a case-sensitive filesystem. Both are kept."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(
        "module top(input a, output y);\n m u(.a(a), .y(y));\nendmodule\n")
    (d / "M.sv").write_text(
        "module m(input a, output y);\n assign y = 1'b0;\nendmodule\n")
    (d / "m.sv").write_text(
        "module m(input a, output y);\n assign y = a;\nendmodule\n")
    res = TC.transitive_cone("top", d)
    assert res.dropped_files == []
    assert res.duplicate_definers == [("m", ["M.sv", "m.sv"])]


def test_h1_the_step_does_not_fabricate_a_fail_on_a_duplicate(tmp_path):
    """A duplicate is reported, not FAILed. `origin/main` PASSes this step and
    lets the frontend reject the tree; FAILing here would be a verdict the
    unreduced flow does not reach, on evidence (`ifdef-blind text) that cannot
    tell a defect from a normal vendor pattern."""
    _mk_vendor_project(tmp_path, _STUB_HAS_CANONICAL_STEM, "widget")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS", sr.detail[-300:]
    assert ("adapter", ["adapter.sv", "vendor_impl_bundle.sv"]) in \
        [tuple(x) if isinstance(x, tuple) else (x[0], x[1])
         for x in sr.extras["cone_unconditional_duplicates"]]


@_needs_sim
def test_h1_correct_alternative_still_reduces_elaborates_and_is_right(tmp_path):
    """The other half of the bidirectional control: the same package with NO
    duplicate. The cone REDUCES, the tree elaborates, and vvp prints the CORRECT
    answer. A guard firing here would be a false positive."""
    files = {
        "widget.sv": _STUB_HAS_CANONICAL_STEM["widget.sv"],
        "adapter.sv":
            "module adapter(input a, input c, output y);\n"
            "  wire merged;\n"
            "  or_helper u_or(.p(a), .q(c), .r(merged));\n"
            "  assign y = merged;\n"
            "endmodule\n",
        "vendor_helper_bundle.sv":
            "module or_helper(input p, input q, output r);\n"
            "  assign r = p | q;\nendmodule\n",
        "orphan_x.sv": "module orphan_x(input p, output q);\n"
                       " assign q=~p;\nendmodule\n",
    }
    _mk_vendor_project(tmp_path, files, "widget")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    staged = {p.name for p in rtl.glob("*.sv")}
    assert sr.status == "PASS", sr.detail[-300:]
    assert staged == {"widget.sv", "adapter.sv", "vendor_helper_bundle.sv"}, \
        staged
    assert _run_tb(rtl, _TB_WIDGET) == (0, 1)


# ════════════════════════════════════════════════════════════════════════════
# H2 — the `include grammar. Any form that is not read must fail CLOSED.
# ════════════════════════════════════════════════════════════════════════════

def test_h2_include_scan_reads_the_unmasked_directive():
    """`_strip_comments_and_strings` blanks string literals — including the
    include PATH. Applying the directive scan to that text matched nothing, so
    the whole header closure was dead code."""
    src = '`include "defs.svh"\nmodule m; endmodule\n'
    blanked = TC._strip_comments_and_strings(src)
    kept = TC._strip_comments_and_strings(src, blank_strings=False)
    assert TC._RE_INCLUDE_DIRECTIVE.search(blanked)
    assert TC._classify_include(
        TC._RE_INCLUDE_DIRECTIVE.search(blanked).group(1)) is None
    assert TC._classify_include(
        TC._RE_INCLUDE_DIRECTIVE.search(kept).group(1)) == "defs.svh"


@pytest.mark.parametrize("directive,expect", [
    ('`include "defs.svh"', "defs.svh"),          # canonical
    ('`include"defs.svh"', "defs.svh"),           # NO whitespace — legal
    ('`include\t"defs.svh"', "defs.svh"),         # tab
    ('`include   "sub/defs.svh"', "defs.svh"),    # path -> basename
    ('`include <defs.svh>', None),                # angle form: not resolvable
    ('`include `HDRPATH', None),                  # macro-valued
    ('`include', None),                           # truncated
])
def test_h2_every_include_form_is_either_read_or_declared_unreadable(
        directive, expect):
    """The round-2 grammar was two narrow regexes, and a form matching NEITHER
    was silently dropped with no diagnostic at all. Now every ```include`` is
    matched and then CLASSIFIED, so the third outcome does not exist."""
    m = TC._RE_INCLUDE_DIRECTIVE.search(directive)
    assert m is not None, directive
    assert TC._classify_include(m.group(1)) == expect


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog missing")
def test_h2_no_whitespace_include_is_legal_and_its_header_survives(tmp_path):
    """MEASURED: ``\\`include"defs.svh"`` is accepted by iverilog -g2012 (and by
    yosys read_verilog -sv). Round 2 matched neither regex, moved the header
    aside, and produced a tree that failed ``Include file ... not found`` where
    the UNREDUCED tree built clean — a regression against staging everything."""
    _mk_vendor_project(tmp_path, {
        "widget.sv": '`include"widget_defs.svh"\n'
                     "module widget(input a, output y);\n"
                     "  byte_t unused;\n  assign y = a;\nendmodule\n",
        "widget_defs.svh": "typedef logic [7:0] byte_t;\n",
        "orphan.sv": "module orphan(input p, output q); assign q=~p; endmodule\n",
    }, "widget")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    assert (rtl / "widget_defs.svh").is_file(), \
        sorted(p.name for p in rtl.glob("*"))
    assert not (rtl / "orphan.sv").exists()          # still reduces
    assert sr.status == "PASS"
    assert _elaborate(rtl, "widget")[0] == 0


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog missing")
def test_h2_define_less_header_survives_and_elaborates(tmp_path):
    """The COMMON case: a header of typedefs/parameters with NO `define. The
    macro closure cannot rescue it (there is no macro), so a broken include
    scan drops it and the tree fails `Include file ... not found`."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "widget_body.svh").write_text(
        "typedef logic [7:0] byte_t;\nlocalparam int WW = 8;\n")
    (d / "top.sv").write_text(
        '`include "widget_body.svh"\n'
        "module top(output byte_t y);\n assign y = WW;\nendmodule\n")
    (d / "orphan.sv").write_text("module orphan; endmodule\n")
    res = TC.transitive_cone("top", d)
    assert "widget_body.svh" in _names(res.cone_files)
    TC.prune_to_cone(d, res)
    assert (d / "widget_body.svh").is_file()
    assert not (d / "orphan.sv").exists()
    assert _elaborate(d, "top")[0] == 0


def test_h2_included_dot_v_body_fragment_survives(tmp_path):
    """`include "body.v"` — an included BODY FRAGMENT is not a header
    extension, so a header-only closure drops it too."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "body.v").write_text("  assign y = a;\n")
    (d / "top.v").write_text(
        'module top(input a, output y);\n`include "body.v"\nendmodule\n')
    (d / "orphan.v").write_text("module orphan; endmodule\n")
    res = TC.transitive_cone("top", d)
    TC.prune_to_cone(d, res)
    assert (d / "body.v").is_file()
    assert not (d / "orphan.v").exists()


def test_h2_unreadable_include_drops_NOTHING_not_just_keeps_headers(tmp_path):
    """```include `PATH`` has no statically knowable target, and the target can
    be ANY staged file — a `.v` body fragment as easily as a header. "Keep every
    header" was not a fail-safe, it was a guess that happened to cover one
    extension pair: a macro-valued include of a `.v` fragment still dropped it.
    The only answer that cannot break a build is the unreduced one."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        '`define P "frag.v"\nmodule top;\n`include `P\nendmodule\n')
    (d / "frag.v").write_text("wire body_fragment;\n")
    (d / "hdr.vh").write_text("// header\n")
    (d / "orphan.v").write_text("module orphan; endmodule\n")
    res = TC.transitive_cone("top", d)
    assert res.unreducible, res.reason
    assert res.dropped_files == []
    assert _names(res.cone_files) == ["frag.v", "hdr.vh", "orphan.v", "top.v"]
    assert any("`include" in u for u in res.unparseable_refs)
    assert TC.prune_to_cone(d, res) == []
    assert (d / "frag.v").is_file()


def test_h2_include_word_inside_a_string_literal_is_not_a_directive(tmp_path):
    """``$display("try `include ...")`` contains the TOKEN but no directive.
    Treating it as one made the whole reduction fail closed on a file that has
    no include at all — correct-but-useless. The two renderings differ ONLY
    inside string bodies, which is how it is told apart without re-lexing."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(
        "module top;\n"
        '  initial $display("try `include \\"ghost.svh\\" now");\n'
        "endmodule\n")
    (d / "ghost.svh").write_text("// nothing\n")
    res = TC.transitive_cone("top", d)
    assert res.unreducible == "", res.reason
    assert "ghost.svh" in _names(res.dropped_files)


def test_h2_commented_out_include_is_never_followed(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(
        '// `include "ghost.svh"\n`include "live.svh"\nmodule top; endmodule\n')
    (d / "ghost.svh").write_text("// nothing\n")
    (d / "live.svh").write_text("// nothing\n")
    res = TC.transitive_cone("top", d)
    assert "live.svh" in _names(res.cone_files)
    assert "ghost.svh" in _names(res.dropped_files)


def test_h2_include_of_an_unstaged_file_is_reported(tmp_path):
    """An ```include`` naming a file NOTHING staged provides used to produce no
    diagnostic whatsoever. The build breaks identically with or without the
    reduction, so this is advisory — but it is not silent."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text('`include "nowhere.svh"\nmodule top; endmodule\n')
    (d / "orphan.sv").write_text("module orphan; endmodule\n")
    res = TC.transitive_cone("top", d)
    assert res.unresolved_includes == ["nowhere.svh (included by top.sv)"]
    assert "orphan.sv" in _names(res.dropped_files)      # still reduces


# ════════════════════════════════════════════════════════════════════════════
# H3 — `ifdef-guarded technology variants are the NORMAL vendor pattern.
# ════════════════════════════════════════════════════════════════════════════

_IFDEF_VARIANTS = {
    "top.sv": "module top(input a, output y);\n  ram u(.a(a), .y(y));\n"
              "endmodule\n",
    "prim_generic_ram.sv":
        "`ifndef USE_XILINX\nmodule ram(input a, output y);\n"
        "  assign y = a;\nendmodule\n`endif\n",
    "prim_xilinx_ram.sv":
        "`ifdef USE_XILINX\nmodule ram(input a, output y);\n"
        "  assign y = ~a;\nendmodule\n`endif\n",
}

_TB_TOP_A = ("module tb;\n reg a = 1'b1; wire y;\n top dut(.a(a), .y(y));\n"
             ' initial begin #10; $display("RESULT=%0d", y); $finish; end\n'
             "endmodule\n")


@_needs_sim
def test_h3_ifdef_guarded_variants_are_not_failed(tmp_path):
    """MEASURED: the staged tree ELABORATES (rc=0) and computes the CORRECT
    answer (RESULT=1), because the preprocessor compiles exactly one arm. Round
    2 reported `AMBIGUOUS duplicate module definition(s)` and FAILed the step —
    a fabricated failure on a design `origin/main` passes."""
    _mk_vendor_project(tmp_path, _IFDEF_VARIANTS, "top")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    assert _run_tb(rtl, _TB_TOP_A) == (0, 1)
    assert sr.status == "PASS", sr.detail[-300:]
    assert sr.extras["cone_conditional_duplicates"] == ["ram"]
    assert sr.extras["cone_unconditional_duplicates"] == []


def test_h3_conditional_classification_is_structural(tmp_path):
    """A declaration inside ANY `ifdef nesting, or inside a `define macro body,
    is not unconditionally present in the compilation unit. No condition is
    evaluated — this program does no preprocessing."""
    d = tmp_path / "rtl"
    d.mkdir()
    for n, t in _IFDEF_VARIANTS.items():
        (d / n).write_text(t)
    res = TC.transitive_cone("top", d)
    assert res.duplicate_definers == [
        ("ram", ["prim_generic_ram.sv", "prim_xilinx_ram.sv"])]
    assert res.conditional_duplicates == ["ram"]
    assert res.hard_duplicates == []
    assert res.dropped_files == []          # still never drops a candidate


def test_h3_macro_body_module_keyword_mints_nothing(tmp_path):
    """``\\`define MK(N) module N; endmodule`` declares no module until expanded,
    so it can never be read as half of a duplicate-definition defect."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(
        "`define MK(N) module N; endmodule\nmodule top; endmodule\n")
    u = TC.parse_unit(d / "top.sv")
    assert "N" in u.conditional_modules
    assert "top" not in u.conditional_modules
    res = TC.transitive_cone("top", d)
    assert res.hard_duplicates == []


# ════════════════════════════════════════════════════════════════════════════
# FAIL-CLOSED inventory: RTL below the flat staged directory
# ════════════════════════════════════════════════════════════════════════════

def test_nested_rtl_makes_the_reduction_fail_closed(tmp_path):
    """`a/M.sv` + `b/M.sv` are invisible to a non-recursive glob, so the
    inventory is incomplete: the duplicate is unseen and `M` reads as
    unresolved. An answer computed from a partial inventory is not an answer —
    nothing is dropped and the limit is stated."""
    d = tmp_path / "rtl"
    (d / "a").mkdir(parents=True)
    (d / "b").mkdir(parents=True)
    (d / "top.sv").write_text(
        "module top(input a, output y);\n M u(.a(a), .y(y));\nendmodule\n")
    (d / "orphan.sv").write_text("module orphan; endmodule\n")
    (d / "a" / "M.sv").write_text(
        "module M(input a, output y); assign y=1'b0; endmodule\n")
    (d / "b" / "M.sv").write_text(
        "module M(input a, output y); assign y=a; endmodule\n")
    res = TC.transitive_cone("top", d)
    assert res.unreducible, res.reason
    assert res.dropped_files == []
    assert TC.prune_to_cone(d, res) == []
    assert (d / "orphan.sv").is_file()
    # and no advisory is drawn from the partial scan
    assert res.unresolved_modules == []


# ── BIDIRECTIONAL control tied to real iverilog elaboration ─────────────────
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
    """DEFECT PRESENT: the cone instantiates `variant` but NO file defines it →
    reported unresolved. Ground truth: iverilog ALSO refuses the same tree."""
    d = tmp_path / "rtl"
    _mk_design(d, with_variant=False)
    res = TC.transitive_cone("chip_top", d)
    assert "variant" in res.unresolved_modules
    if _HAS_IVERILOG:
        assert _elaborate(d, "chip_top")[0] != 0


def test_control_correct_alternative_passes_and_elaborates(tmp_path):
    """CORRECT ALTERNATIVE: the SAME design WITH `variant.v` → no unresolved
    module AND iverilog elaborates it."""
    d = tmp_path / "rtl"
    _mk_design(d, with_variant=True)
    res = TC.transitive_cone("chip_top", d)
    assert res.unresolved_modules == []
    assert "variant.v" in _names(res.cone_files)
    if _HAS_IVERILOG:
        assert _elaborate(d, "chip_top")[0] == 0


# ── topological package order: dependency before importer ───────────────────
def test_topological_package_order(tmp_path):
    """A package imported by another is emitted BEFORE its importer, and all
    packages precede non-package RTL."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "b_pkg.sv").write_text(
        "package b_pkg;\n import a_pkg::*;\n localparam int W = a_pkg::N;\n"
        "endpackage\n")
    (d / "a_pkg.sv").write_text(
        "package a_pkg;\n localparam int N = 8;\nendpackage\n")
    (d / "m.sv").write_text("module m; import b_pkg::*; endmodule\n")
    names = [p.name for p in TC.topological_package_first(sorted(d.glob("*.sv")))]
    assert names.index("a_pkg.sv") < names.index("b_pkg.sv")
    assert names.index("b_pkg.sv") < names.index("m.sv")


def test_package_detection_is_structural_not_a_filename_substring(tmp_path):
    """`"pkg" in f.name` ordered a package declared in a file the vendor did not
    name `*pkg*` AFTER its importer — the exact bug this function prevents. The
    filenames are chosen so ALPHABETICAL order is the WRONG order: only a rule
    that actually reads the `package` declaration gets it right."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "zz_defs.sv").write_text(
        "package p;\n localparam int W=8;\nendpackage\n")
    (d / "aa_user.sv").write_text("module aa_user; import p::*; endmodule\n")
    files = sorted(d.glob("*.sv"))
    assert [p.name for p in files] == ["aa_user.sv", "zz_defs.sv"]  # the trap
    names = [p.name for p in TC.topological_package_first(files)]
    assert names.index("zz_defs.sv") < names.index("aa_user.sv"), names


# ── robustness: function calls / keywords / gate primitives NOT modules ──────
def test_calls_and_gate_primitives_not_flagged_unresolved(tmp_path):
    """A function call `foo(...)`, a keyword `for (...)`, or a gate primitive
    `nand u(...)` must never read as an unresolved user module."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        "module top(input a, input b, output y, output z);\n"
        "  wire w;\n"
        "  nand g1 (w, a, b);\n"
        "  xor  g2 (z, a, b);\n"
        "  function automatic integer f(input integer x);\n"
        "    f = x + 1;\n  endfunction\n"
        "  integer r;\n"
        "  always @(*) begin\n"
        "    r = f(3);\n"
        "    for (r = 0; r < 2; r = r + 1) ;\n"
        "  end\n"
        "  assign y = w;\nendmodule\n")
    assert TC.transitive_cone("top", d).unresolved_modules == []


def test_udp_primitive_head_is_not_an_unresolved_module(tmp_path):
    """`primitive mux_udp(o,a,b,s);` parses as type=`primitive`,
    instance=`mux_udp` — a phantom unresolved module named "primitive"."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "mux_udp.v").write_text(
        "primitive mux_udp(o, a, b, s);\n output o; input a, b, s;\n"
        " table\n  0 ? 0 : 0;\n  1 ? 0 : 1;\n  ? 0 1 : 0;\n  ? 1 1 : 1;\n"
        " endtable\nendprimitive\n")
    (d / "top.v").write_text(
        "module top(input a, input b, input s, output y);\n"
        " mux_udp u (y, a, b, s);\nendmodule\n")
    res = TC.transitive_cone("top", d)
    assert res.unresolved_modules == [], res.unresolved_modules
    assert "mux_udp.v" in _names(res.cone_files)


def test_a_top_only_the_runners_scan_can_see_drops_nothing(tmp_path):
    """The runner gates the reduction on `_cone_root in _v661_rtl_module_names`,
    and THAT scan reads string-PRESERVED text while this one reads
    string-BLANKED text. So a `module <name> (...);` inside a ``$display``
    literal is a module to the runner and not to the cone — reachable, and
    measured here. It lands on the fail-safe: the cone cannot be anchored, so
    NOTHING is dropped and the reason says so."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(
        "module top(input a, output y);\n"
        '  initial $display("module ghost_top (input b);");\n'
        "  assign y = a;\nendmodule\n")
    (d / "orphan.sv").write_text(
        "module orphan(input p, output q); assign q=~p; endmodule\n")
    seen_by_runner = R._MODULE_HEADER_RE.findall(
        R._strip_v_comments((d / "top.sv").read_text()))
    assert "ghost_top" in [m for m, _ in seen_by_runner]     # the divergence
    res = TC.transitive_cone("ghost_top", d)
    assert res.unreducible, res.reason
    assert res.dropped_files == []
    assert TC.prune_to_cone(d, res) == []
    assert (d / "orphan.sv").is_file()


# ── top not defined → NO pruning ────────────────────────────────────────────
def test_top_not_defined_no_pruning(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "a.v").write_text("module a(input x, output y); assign y=x; endmodule\n")
    (d / "b.v").write_text("module b(input x, output y); assign y=x; endmodule\n")
    res = TC.transitive_cone("nonexistent_top", d)
    assert res.dropped_files == []
    assert len(res.cone_files) == 2
    assert not res.reduced
    assert res.unreducible


# ── an ESCAPED identifier is invisible to this grammar → keep + report ───────
def test_escaped_identifier_is_kept_and_reported(tmp_path):
    """`\\esc.mod ` matches no `[A-Za-z_]\\w*` regex here, so its definer would
    be dropped with NO `unresolved` entry — a build break with zero
    diagnostic."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text(
        "module top(input a, output y);\n"
        "  \\esc.mod  u1 (.a(a), .y(y));\nendmodule\n")
    (d / "escmod.v").write_text(
        "module \\esc.mod  (input a, output y);\n assign y=a;\nendmodule\n")
    (d / "orphan.v").write_text("module orphan; endmodule\n")
    res = TC.transitive_cone("top", d)
    assert "escmod.v" in _names(res.cone_files), _names(res.cone_files)
    assert "orphan.v" in _names(res.dropped_files)
    assert "esc.mod" in " ".join(res.unparseable_refs), res.unparseable_refs
    TC.prune_to_cone(d, res)
    assert (d / "escmod.v").is_file()


def test_step_emits_the_unparseable_advisory(tmp_path):
    _mk_vendor_project(tmp_path, {
        "widget.sv": "module widget(input a, output y);\n"
                     "  \\esc.mod  u1 (.a(a), .y(y));\nendmodule\n",
        "escmod.sv": "module \\esc.mod  (input a, output y);\n"
                     " assign y=a;\nendmodule\n",
        "orphan.sv": "module orphan; endmodule\n",
    }, "widget")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert "unparseable" in sr.detail.lower(), sr.detail[:300]
    assert any("esc.mod" in u
               for u in sr.extras.get("cone_unparseable_refs", [])), sr.extras
    staged = {p.name for p in (tmp_path / "phase2/stage1/rtl").glob("*.sv")}
    assert "escmod.sv" in staged and "orphan.sv" not in staged, staged


# ════════════════════════════════════════════════════════════════════════════
# M2 — an unresolved module is an ADVISORY, never a fabricated FAIL.
# ════════════════════════════════════════════════════════════════════════════

_BLACKBOX_TOP = ("module widget(input a, output y);\n"
                 "  hardmacro_sram u(.a(a), .y(y));\nendmodule\n")


@pytest.mark.parametrize("label,extra", [
    ("control: no sibling at all", None),
    ("editor backup", {"docs/hardmacro_sram.sv.bak": "module hardmacro_sram; endmodule\n"}),
    ("patch original", {"hardmacro_sram.v.orig": "module hardmacro_sram; endmodule\n"}),
    ("patch reject", {"rtl/hardmacro_sram.sv.rej": "module hardmacro_sram; endmodule\n"}),
    ("dataset exclusion", {"hardmacro_sram.sv.unused-excluded": "module hardmacro_sram; endmodule\n"}),
    ("doc siblings", {"hardmacro_sram.md": "# doc\n", "hardmacro_sram.svg": "<svg/>\n"}),
])
def test_m2_no_sibling_filename_can_fabricate_a_step_failure(
        tmp_path, label, extra):
    """A `<M>.sv.<tag>` sibling under input/ is EVIDENCE, not a verdict.
    Nothing in a filename distinguishes a dataset exclusion from an editor
    backup or a patch reject, and `origin/main` PASSes every one of these. The
    absent module surfaces where it always did — loudly, at elaboration."""
    _mk_vendor_project(tmp_path, {"widget.sv": _BLACKBOX_TOP}, "widget",
                       extra_input=extra)
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS", f"{label}: fabricated FAIL: {sr.detail[-300:]}"
    assert "hardmacro_sram" in (
        sr.extras.get("cone_unresolved_excluded", [])
        + sr.extras.get("cone_unresolved_blackbox", [])), sr.extras
    assert "ADVISORY" in sr.detail


def test_m2_a_real_exclusion_is_still_named_with_its_evidence(tmp_path):
    """Downgrading the verdict must not downgrade the INFORMATION: the sibling
    that proves an RTL source exists in a non-stageable form is named by path."""
    _mk_vendor_project(tmp_path, {"widget.sv": _BLACKBOX_TOP}, "widget",
                       extra_input={
                           "vendor_rtl/hardmacro_sram.sv.unused-excluded":
                               "module hardmacro_sram; endmodule\n"})
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.extras["cone_unresolved_excluded"] == ["hardmacro_sram"]
    ev = sr.extras["cone_unresolved_excluded_evidence"]["hardmacro_sram"]
    assert ev.endswith("hardmacro_sram.sv.unused-excluded"), ev
    assert ev in sr.detail


def test_m2_an_oracle_segment_never_influences_the_step(tmp_path):
    """§4.05: a file reached through a harness/oracle segment must not drive a
    step's reported state at all. The policy is `reused_ip_rtl_consume`'s own
    `_is_oracle_parts`, reused — not a second copy."""
    _mk_vendor_project(tmp_path, {"widget.sv": _BLACKBOX_TOP}, "widget",
                       extra_input={
                           "tb/hardmacro_sram.sv.golden":
                               "module hardmacro_sram; endmodule\n",
                           "golden/hardmacro_sram.v.ref":
                               "module hardmacro_sram; endmodule\n"})
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS"
    assert sr.extras["cone_unresolved_excluded"] == [], sr.extras
    assert sr.extras["cone_unresolved_blackbox"] == ["hardmacro_sram"]
    assert R._v_shipped_but_excluded(tmp_path, "hardmacro_sram") is None


def test_m2_predicate_returns_the_evidence_path(tmp_path):
    """Only a FURTHER extension component after `.sv`/`.v` is an exclusion tag —
    `startswith("<M>.sv")` also matches `<M>.svg` / `<M>.sva` / `<M>.svh`."""
    inp = tmp_path / "input" / "docs"
    inp.mkdir(parents=True)
    for n in ("m.svg", "m.sva", "m.svh", "m.sv", "m.v", "m.vh", "m.md"):
        (inp / n).write_text("x")
    assert R._v_shipped_but_excluded(tmp_path, "m") is None
    (inp / "m.sv.unused-excluded").write_text("x")
    assert R._v_shipped_but_excluded(tmp_path, "m") == \
        "input/docs/m.sv.unused-excluded"


# ════════════════════════════════════════════════════════════════════════════
# M3 — a malformed manifest must not fabricate a HALF-MOVED verdict, and the
#      recovery command it prints must not crash.
# ════════════════════════════════════════════════════════════════════════════

def test_m3_non_dict_manifest_does_not_crash_prune(tmp_path):
    """`CONE_RESTORE.json` that is valid JSON but not an object reached `.get`
    on a list and raised an uncaught AttributeError through BOTH entry points."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text("module top; endmodule\n")
    (d / "orphan.sv").write_text("module orphan; endmodule\n")
    side = tmp_path / "rtl_out_of_cone"
    side.mkdir()
    (side / TC.RESTORE_MANIFEST_NAME).write_text('["stale"]')
    res = TC.transitive_cone("top", d)
    assert TC.prune_to_cone(d, res) == ["orphan.sv"]
    man = json.loads((side / TC.RESTORE_MANIFEST_NAME).read_text())
    assert man["moved"] == ["orphan.sv"]
    assert "prior_manifest_problem" in man     # the unreadable one is not hidden


def test_m3_malformed_manifest_does_not_fabricate_a_half_moved_fail(tmp_path):
    """END-TO-END: the step reported phase=MUTATION "the staged tree may be
    HALF-MOVED" while rtl/ held the complete cone and the sidecar held exactly
    the out-of-cone files — and named a recovery command that itself crashed."""
    root = _mk_vendor_project(tmp_path, {
        "top.sv": "module top(input a, output y); assign y=a; endmodule\n",
        "orphan.sv": "module orphan(input p, output q); assign q=~p; endmodule\n",
    }, "top")
    side = root / "phase2" / "stage1" / "rtl_out_of_cone"
    side.mkdir(parents=True)
    (side / TC.RESTORE_MANIFEST_NAME).write_text('["stale"]')
    sr = R.step_reused_ip_consume(root, "chip_top")
    rtl = root / "phase2" / "stage1" / "rtl"
    assert sr.status == "PASS", sr.detail[-300:]
    assert "HALF-MOVED" not in sr.detail
    assert (rtl / "top.sv").is_file()
    assert (side / "orphan.sv").is_file()


def test_m3_a_mutation_crash_is_judged_against_the_tree_not_the_call_site(
        tmp_path, monkeypatch):
    """`prune_to_cone` only ever moves files OUT, and only ones the analysis put
    in `dropped_files`, so a partial move leaves a SUPERSET of the cone staged —
    never worse than not reducing. The verdict is therefore decided by whether a
    CONE file actually went missing, not by which function raised."""
    root = _mk_vendor_project(tmp_path, {
        "widget.sv": "module widget(input a, output b); assign b=a; endmodule\n",
        "orphan.sv": "module orphan; endmodule\n",
    }, "widget")

    def _boom(rtl_dir, result, sidecar=None):
        raise RuntimeError("synthetic prune failure")
    monkeypatch.setattr(TC, "prune_to_cone", _boom)
    sr = R.step_reused_ip_consume(root, "chip_top")
    assert sr.extras["cone_error_phase"] == "MUTATION"
    assert sr.extras["cone_error_missing_from_rtl"] == []
    assert sr.status == "PASS", sr.detail[-300:]      # nothing went missing
    assert "CONE ERROR" in sr.detail and "did not complete" in sr.detail
    assert (root / "phase2/stage1/rtl/widget.sv").is_file()


def test_m3_a_cone_file_that_actually_went_missing_does_fail(tmp_path,
                                                             monkeypatch):
    """The one outcome that IS worse than not reducing: a file the build needs
    is no longer staged. That is the only FAIL this block raises, and it is
    checked against the tree."""
    root = _mk_vendor_project(tmp_path, {
        "widget.sv": "module widget(input a, output b);\n"
                     " leaf u(.a(a),.b(b));\nendmodule\n",
        "leaf.sv": "module leaf(input a, output b); assign b=a; endmodule\n",
        "orphan.sv": "module orphan; endmodule\n",
    }, "widget")

    def _boom(rtl_dir, result, sidecar=None):
        (rtl_dir / "leaf.sv").unlink()        # a cone file vanishes
        raise RuntimeError("synthetic prune failure mid-move")
    monkeypatch.setattr(TC, "prune_to_cone", _boom)
    sr = R.step_reused_ip_consume(root, "chip_top")
    assert sr.status == "FAIL", sr.detail[-300:]
    assert sr.extras["cone_error_missing_from_rtl"] == ["leaf.sv"]
    assert "INCOMPLETE" in sr.detail and "--restore" in sr.detail


def test_analysis_crash_is_named_but_never_fabricates_a_failure(
        tmp_path, monkeypatch):
    """The analysis phase is PURE — a crash leaves the tree exactly as the
    unreduced staging produces, so FAILing would fabricate a failure. But it
    must be STATED: it used to land in `extras` only, where nothing reads it."""
    _mk_vendor_project(tmp_path, {
        "widget.sv": "module widget(input a, output b); assign b=a; endmodule\n",
    }, "widget")

    def _boom(top, rtl_dir):
        raise RuntimeError("synthetic cone analysis failure")
    monkeypatch.setattr(TC, "transitive_cone", _boom)
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert "CONE ERROR" in sr.detail and "ANALYSIS" in sr.detail, sr.detail
    assert "synthetic cone analysis failure" in sr.detail
    assert sr.extras["cone_error_phase"] == "ANALYSIS"
    assert sr.extras["cone_error_traceback"]
    assert sr.status == "PASS"
    assert (tmp_path / "phase2/stage1/rtl/widget.sv").is_file()


# ── L6: state the limit honestly instead of implying universal coverage ──────
def test_l6_unresolvable_top_is_recorded_not_silently_skipped(tmp_path):
    """The reduction runs ONLY when a top resolved. Orphan files are themselves
    graph roots, so the very over-staging this reduces is what can defeat root
    resolution. That case must SAY it was not reduced."""
    _mk_vendor_project(tmp_path, {
        "widget.sv": "module widget(input a, output b);\n"
                     " leaf u(.a(a),.b(b));\nendmodule\n",
        "leaf.sv": "module leaf(input a, output b); assign b=a; endmodule\n",
        "orphan_a.sv": "module orphan_a(input x, output z);\n"
                       " assign z=~x;\nendmodule\n",
        "orphan_b.sv": "module orphan_b(input x, output z);\n"
                       " assign z=x;\nendmodule\n",
    }, "a_name_that_is_not_a_module")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.extras.get("cone_skipped"), sr.extras
    assert "NOT APPLIED" in sr.detail, sr.detail[:300]
    staged = {p.name for p in (tmp_path / "phase2/stage1/rtl").glob("*.sv")}
    assert "orphan_a.sv" in staged
    assert not (tmp_path / "phase2/stage1/rtl_out_of_cone").exists()


# ════════════════════════════════════════════════════════════════════════════
# L7 — the reduction is undoable by PROGRAM, and the undo never lies.
# ════════════════════════════════════════════════════════════════════════════

def _mk_prunable(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    (d / "top.v").write_text(
        "module top(input a, output b); sub u(.a(a),.b(b)); endmodule\n")
    (d / "sub.v").write_text(
        "module sub(input a, output b); assign b=a; endmodule\n")
    (d / "orphan.v").write_text("module orphan; endmodule\n")


def test_l7_prune_restore_round_trip(tmp_path):
    d = tmp_path / "rtl"
    _mk_prunable(d)
    before = _names(list(d.iterdir()))
    res = TC.transitive_cone("top", d)
    assert TC.prune_to_cone(d, res) == ["orphan.v"]
    assert (d.parent / "rtl_out_of_cone" / TC.RESTORE_MANIFEST_NAME).is_file()
    rr = TC.restore_from_sidecar(d)
    assert rr.restored == ["orphan.v"] and rr.problems == []
    assert _names(list(d.iterdir())) == before
    assert TC.restore_from_sidecar(d).restored == []


def test_l7_restore_never_clobbers_a_present_file(tmp_path):
    d = tmp_path / "rtl"
    _mk_prunable(d)
    res = TC.transitive_cone("top", d)
    TC.prune_to_cone(d, res)
    (d / "orphan.v").write_text("module orphan; /* re-authored */ endmodule\n")
    rr = TC.restore_from_sidecar(d)
    assert rr.restored == [] and rr.skipped == ["orphan.v"]
    assert "re-authored" in (d / "orphan.v").read_text()


def test_l7_prune_never_clobbers_a_file_already_in_the_sidecar(tmp_path):
    """"never deletes" has to hold for the SIDECAR too. `shutil.move` onto an
    existing path REPLACES it, so a second reduction over a re-authored tree
    destroyed the first version."""
    d = tmp_path / "rtl"
    _mk_prunable(d)
    (d / "orphan.v").write_text("module orphan; /* v1 */ endmodule\n")
    TC.prune_to_cone(d, TC.transitive_cone("top", d))
    (d / "orphan.v").write_text("module orphan; /* v2 */ endmodule\n")
    TC.prune_to_cone(d, TC.transitive_cone("top", d))
    side = d.parent / "rtl_out_of_cone"
    assert "v1" in (side / "orphan.v").read_text()
    stored = sorted(p.name for p in side.glob("*.v"))
    assert stored == ["orphan.conflict1.v", "orphan.v"], stored
    assert "v2" in (side / "orphan.conflict1.v").read_text()


@pytest.mark.parametrize("payload,expect_problem", [
    ('["orphan.v"]', "not an object"),
    ('{"top": "top"}', "names no files"),
    ("{not json", "not readable JSON"),
])
def test_l7_a_manifest_we_cannot_use_is_a_PROBLEM_not_a_silent_zero(
        tmp_path, payload, expect_problem):
    """`restored 0 file(s)` + exit 0 reads exactly like "there was nothing to
    undo". A manifest that is truncated, malformed or not an object is neither."""
    d = tmp_path / "rtl"
    _mk_prunable(d)
    TC.prune_to_cone(d, TC.transitive_cone("top", d))
    side = d.parent / "rtl_out_of_cone"
    (side / TC.RESTORE_MANIFEST_NAME).write_text(payload)
    rr = TC.restore_from_sidecar(d)
    assert rr.restored == []
    assert any(expect_problem in p for p in rr.problems), rr.problems
    assert TC.main([str(d), "--restore"]) == 1


def test_l7_cli_restore_returns_zero_only_on_a_clean_undo(tmp_path):
    d = tmp_path / "rtl"
    _mk_prunable(d)
    TC.prune_to_cone(d, TC.transitive_cone("top", d))
    assert TC.main([str(d), "--restore"]) == 0
    assert (d / "orphan.v").is_file()


def test_l7_a_manifest_entry_may_not_name_a_path(tmp_path):
    """CONTAINMENT: a manifest entry `"../VICTIM.sv"` MOVED a file from outside
    the project INTO it. The shipped CLI never reached it only because the
    default sidecar shares rtl_dir's parent, so src and dst resolved to the same
    path — an accident of layout, not a check."""
    d = tmp_path / "proj" / "rtl"
    _mk_prunable(d)
    alt = tmp_path / "elsewhere" / "sidecar"
    alt.mkdir(parents=True)
    TC.prune_to_cone(d, TC.transitive_cone("top", d), sidecar=alt)
    victim = tmp_path / "VICTIM.sv"
    victim.write_text("module victim; endmodule\n")
    (alt / TC.RESTORE_MANIFEST_NAME).write_text(
        json.dumps({"moved": ["../../../VICTIM.sv"]}))
    rr = TC.restore_from_sidecar(d, sidecar=alt)
    assert rr.restored == []
    assert any("plain filename" in p for p in rr.problems), rr.problems
    assert victim.is_file()
    assert not (d / "VICTIM.sv").exists()
    assert not (d.parent / "VICTIM.sv").exists()


# ════════════════════════════════════════════════════════════════════════════
# L8 — a moved-aside file is not authoritative RTL any more, for EVERY gate.
# ════════════════════════════════════════════════════════════════════════════

def test_l8_out_of_cone_sidecar_is_out_of_rtl_scan_scope(tmp_path):
    assert SCOPE.is_excluded_component("rtl_out_of_cone") is True
    assert SCOPE.is_excluded_component("rtl") is False
    # a PLAIN SUFFIX rule, with no "…unless the component IS the suffix"
    # carve-out — that made `analysis_out_of_cone` excluded while `_out_of_cone`
    # was not, which is not a rule anyone can state.
    assert SCOPE.is_excluded_component("_out_of_cone") is True
    assert SCOPE.is_excluded_component("out_of_cone") is False
    proj = tmp_path / "p"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl_out_of_cone").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "keep.v").write_text(
        "module keep; endmodule\n")
    (proj / "phase2" / "stage1" / "rtl_out_of_cone" / "gone.v").write_text(
        "module gone; endmodule\n")
    got = {p.name for p in SCOPE.authoritative_rtl_files(proj)}
    assert got == {"keep.v"}, got


def test_l8_every_rtl_collector_agrees_the_sidecar_is_out_of_scope(tmp_path):
    """FOUR collectors, not three. `break_handler_safety_check` imported only
    the NAME SET and kept its own `& EXCLUDED_DIRS` comprehension, so it missed
    the suffix rule entirely: measured, the other three saw `design.v` while it
    also read the moved-aside `orphan.v` and reported an ERROR against a file
    the flow does not compile."""
    import gate_utils
    import dispatch_register_default_reset_check as drc
    import break_handler_safety_check as bhs
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl_out_of_cone").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "keep.v").write_text(
        "module keep; endmodule\n")
    (tmp_path / "phase2" / "stage1" / "rtl_out_of_cone" / "gone.v").write_text(
        "module gone; endmodule\n")
    for label, files in (
            ("rtl_scan_scope", SCOPE.authoritative_rtl_files(tmp_path)),
            ("gate_utils", gate_utils.find_rtl_files(tmp_path)),
            ("dispatch_register", drc.collect_files(tmp_path)),
            ("break_handler", bhs.collect_files(tmp_path))):
        got = {Path(f).name for f in files}
        assert got == {"keep.v"}, f"{label} sees {sorted(got)}"


def test_l8_break_handler_verdict_never_comes_from_the_sidecar(tmp_path):
    """The collector-level assertion is not enough — drive the REAL audit and
    show the moved-aside file's defect does not reach the verdict."""
    import break_handler_safety_check as bhs
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    side = tmp_path / "phase2" / "stage1" / "rtl_out_of_cone"
    rtl.mkdir(parents=True)
    side.mkdir(parents=True)
    (rtl / "design.v").write_text(
        "module design(input clk, input rx_break, output reg [1:0] state);\n"
        "  localparam IDLE=0, TX=1;\n"
        "  always @(posedge clk) begin\n"
        "    case (state)\n"
        "      IDLE: if (rx_break) state <= IDLE;\n"
        "      TX: state <= TX;\n"
        "    endcase\n  end\nendmodule\n")
    (side / "orphan.v").write_text(
        "module orphan(input clk, input rx_break, output reg [1:0] state);\n"
        "  localparam IDLE=0;\n"
        "  always @(posedge clk) begin\n"
        "    if (rx_break) state <= IDLE;\n"
        "  end\nendmodule\n")
    res = bhs.audit(tmp_path)
    assert res.summary["files_scanned"] == ["design.v"], res.summary
    assert res.passed is True
    assert [f.file for f in res.findings if f.severity == "ERROR"] == []


def test_l8_sidecar_name_matches_what_the_reducer_creates(tmp_path):
    """The exclusion and the mover must agree."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text("module top; endmodule\n")
    (d / "orphan.v").write_text("module orphan; endmodule\n")
    TC.prune_to_cone(d, TC.transitive_cone("top", d))
    created = [p for p in d.parent.iterdir() if p.is_dir() and p != d]
    assert len(created) == 1, created
    assert SCOPE.is_excluded_component(created[0].name) is True


# ── flat staging discards a same-basename source: PRE-EXISTING, now NAMED ────
def test_flat_staging_name_collision_is_reported(tmp_path):
    """`dst = rtl_dir / src.name` is first-wins, so `a/m.sv` and `b/m.sv`
    compete for one staged name and the second is discarded. The flattening is
    unchanged (the staged FILENAMES are a contract downstream steps read); what
    changes is that the lost source is named instead of vanishing."""
    vd = tmp_path / "input" / "vendor_rtl"
    (vd / "a").mkdir(parents=True)
    (vd / "b").mkdir(parents=True)
    (vd / "top.sv").write_text(
        "module top(input a, output y);\n m u(.a(a), .y(y));\nendmodule\n")
    (vd / "a" / "m.sv").write_text(
        "module m(input a, output y); assign y=a; endmodule\n")
    (vd / "b" / "m.sv").write_text(
        "module m_other(input a, output y); assign y=a; endmodule\n")
    _write_l9(tmp_path, "top")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    coll = sr.extras.get("staged_name_collisions")
    assert coll and "m.sv" in coll, sr.extras
    assert len(coll["m.sv"]) == 2, coll
    assert "basename collision" in sr.detail


# ════════════════════════════════════════════════════════════════════════════
# CORPUS — READ-ONLY, on the real vendor bundles that ship in the checkout.
# ════════════════════════════════════════════════════════════════════════════

def _find_project(name: str) -> Path | None:
    for anc in Path(__file__).resolve().parents:
        cand = anc / "benchmark-data" / "ic" / name
        if (cand / "input" / "vendor_rtl").is_dir() and (cand / "phase1").is_dir():
            return cand
    return None


def test_reproduce_on_real_aes_vendor_input(tmp_path):
    """REPRODUCE on the real opentitan_aes vendor bundle: the cone drops the
    orphans + shim and surfaces exactly the shipped-but-excluded masked S-box.
    benchmark-data is COPIED, never written."""
    proj = _find_project("opentitan_aes")
    if proj is None:
        pytest.skip("opentitan_aes benchmark project not present in this checkout")
    shutil.copytree(proj / "input" / "vendor_rtl", tmp_path / "input" / "vendor_rtl")
    shutil.copytree(proj / "phase1", tmp_path / "phase1")
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    remaining = {p.name for p in rtl.glob("*.sv")} | {p.name for p in rtl.glob("*.v")}
    assert not any("ascon" in n for n in remaining)
    assert "prim_flash.sv" not in remaining
    assert "tlul_adapter_shim.sv" not in remaining
    assert "aes.sv" in remaining and "aes_sbox.sv" in remaining
    assert "aes_sbox_dom" in sr.extras.get("cone_unresolved_modules", [])
    # ADVISORY, not a verdict: origin/main passes this step too.
    assert sr.status == "PASS", sr.detail[-300:]


def test_corpus_cone_is_never_smaller_than_the_build_needs(tmp_path):
    """The never-worse property, on every staged tree the checkout ships: for
    every module each tree declares, the cone must be CLOSED — every
    instantiation / package / include / macro that some staged file provides is
    itself in the cone — and no file declaring a duplicated module is ever
    dropped. READ-ONLY: each tree is copied first."""
    root = None
    for anc in Path(__file__).resolve().parents:
        if (anc / "benchmark-data").is_dir():
            root = anc
            break
    if root is None:
        pytest.skip("no benchmark-data in this checkout")
    trees = sorted(p for p in root.glob("benchmark-data/**/phase2/stage1/rtl")
                   if p.is_dir())
    if not trees:
        pytest.skip("no staged rtl/ trees in this checkout")
    violations = []
    for i, t in enumerate(trees):
        dst = tmp_path / f"t{i:03d}"
        shutil.copytree(t, dst)
        units, _ = TC._collect_units(dst)
        for top in sorted({m for u in units for m in u.modules}):
            r = TC.transitive_cone(top, dst)
            keep = {p.name for p in r.cone_files}
            cone_units = [u for u in units if u.path.name in keep]
            present = {u.path.name for u in units}
            assert keep <= present
            for u in cone_units:
                for m in u.inst_types:
                    if any(m in c.modules for c in units) and \
                            not any(m in c.modules for c in cone_units):
                        violations.append((t.name, top, f"inst {m}"))
                for p in u.ref_pkgs:
                    if any(p in c.packages for c in units) and \
                            not any(p in c.packages for c in cone_units):
                        violations.append((t.name, top, f"pkg {p}"))
                for inc in u.includes:
                    if inc in present and inc not in keep:
                        violations.append((t.name, top, f"include {inc}"))
                for mac in u.used_macros:
                    if any(mac in c.macros for c in units) and \
                            not any(mac in c.macros for c in cone_units):
                        violations.append((t.name, top, f"macro {mac}"))
            dropped = {p.name for p in r.dropped_files}
            for m, cands in r.duplicate_definers:
                for c in cands:
                    if c in dropped:
                        violations.append((t.name, top, f"definer {c} of {m}"))
    assert violations == [], violations[:10]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
