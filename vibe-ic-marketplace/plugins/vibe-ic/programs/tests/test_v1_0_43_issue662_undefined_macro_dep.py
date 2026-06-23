"""ORGANIC #662 — undefined-macro / unresolved-`include dependency pre-check.

When staged RTL references a `` `MACRO `` / `` `include "f" `` whose definition
is unstaged, iverilog + yosys/slang both fail with a BARE undefined-macro error
and NO remediation hint. The defining file frequently exists under
`input/design_src/**/rtl/` but was not pulled into the compile set.

Fix: `_v662_resolve_dependency_files` scans the staged rtl/ for macros
USED-but-not-DEFINED and `` `include ``s that are not present, searches
`input/design_src/**/rtl/` for the defining file, and either AUTO-STAGES it into
rtl/ or returns an actionable remediation hint naming it. Fail-open robustness
aid — never blocks. chip-AGNOSTIC: pure `` `define `` / `` `include `` grammar.

Positive: a user RTL referencing a macro defined in a sibling `defines.v` under
input/design_src/**/rtl/ → the pre-check stages it AND the hint names it.
Negative no-leak: Verilog compiler directives (`` `ifdef ``, `` `timescale ``,
…) are NOT treated as undefined user macros; a fully-self-contained staged set
yields NO hints and stages nothing.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


# the field-agent's exact caravel case, chip-AGNOSTICally generalised: a wrapper
# that uses a macro defined only in an unstaged sibling under design_src/rtl/.
_WRAPPER = """\
`default_nettype none
module proj_wrapper (
    inout  wire [`PROJ_IO_PADS-1:0] io,
    input  wire clk
);
`ifdef USE_POWER_PINS
    inout wire vccd1;
`endif
endmodule
"""
_DEFINES = "`define PROJ_IO_PADS 38\n"


def _scaffold(tmp_path, stage_defines=False):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "proj_wrapper.v").write_text(_WRAPPER)
    if stage_defines:
        (rtl / "defines.v").write_text(_DEFINES)
    # the dependency pool: defines.v lives under input/design_src/**/rtl/
    dep = proj / "input" / "design_src" / "verilog" / "rtl"
    dep.mkdir(parents=True, exist_ok=True)
    (dep / "defines.v").write_text(_DEFINES)
    return proj


# ── undefined-macro detection (excludes compiler directives) ───────────────

def test_undefined_macros_excludes_compiler_directives(tmp_path):
    proj = _scaffold(tmp_path)
    staged = R._select_asic_rtl_sources(_pl.rtl_dir(proj))
    undef = R._v662_undefined_macros(staged)
    assert "PROJ_IO_PADS" in undef            # a real user macro, undefined
    # NO-LEAK: `ifdef / `default_nettype / USE_POWER_PINS-style directives are
    # not user macros and must not be reported as undefined.
    assert "ifdef" not in undef
    assert "endif" not in undef
    assert "default_nettype" not in undef


def test_defines_collected_from_pool(tmp_path):
    proj = _scaffold(tmp_path)
    pool = R._v662_design_src_rtl_files(proj)
    assert any(p.name == "defines.v" for p in pool)
    assert "PROJ_IO_PADS" in R._v662_collect_defines(pool)


# ── positive: auto-stage the defining file + name it in the hint ───────────

def test_auto_stages_defining_file_and_hints(tmp_path):
    proj = _scaffold(tmp_path)
    res = R._v662_resolve_dependency_files(proj, auto_stage=True)
    assert "PROJ_IO_PADS" in res["undefined_macros"]
    assert "defines.v" in res["staged"]
    # the hint names the resolving file structurally
    assert any("PROJ_IO_PADS" in h and "defines.v" in h for h in res["hints"])
    # the file is now physically present in rtl/ → the macro resolves
    assert (_pl.rtl_dir(proj) / "defines.v").is_file()


def test_hint_only_mode_does_not_stage(tmp_path):
    proj = _scaffold(tmp_path)
    res = R._v662_resolve_dependency_files(proj, auto_stage=False)
    assert res["staged"] == []
    assert not (_pl.rtl_dir(proj) / "defines.v").is_file()
    assert any("PROJ_IO_PADS" in h for h in res["hints"])


# ── negative no-leak: a self-contained staged set yields nothing ───────────

def test_self_contained_set_no_hints(tmp_path):
    proj = _scaffold(tmp_path, stage_defines=True)  # defines.v already staged
    res = R._v662_resolve_dependency_files(proj, auto_stage=True)
    assert res["undefined_macros"] == []
    assert res["unresolved_includes"] == []
    assert res["staged"] == []
    assert res["hints"] == []


def test_no_rtl_dir_returns_empty(tmp_path):
    # NO-REGRESSION: absent rtl/ → empty result, never crashes.
    res = R._v662_resolve_dependency_files(tmp_path / "nope", auto_stage=True)
    assert res["undefined_macros"] == [] and res["staged"] == []


# ── unresolved `include resolution ─────────────────────────────────────────

def test_unresolved_include_resolved_from_pool(tmp_path):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        '`include "shared_defs.vh"\nmodule top(); endmodule\n')
    dep = proj / "input" / "design_src" / "ip" / "rtl"
    dep.mkdir(parents=True, exist_ok=True)
    (dep / "shared_defs.vh").write_text("`define WIDTH 8\n")
    res = R._v662_resolve_dependency_files(proj, auto_stage=True)
    assert "shared_defs.vh" in res["unresolved_includes"]
    assert "shared_defs.vh" in res["staged"]
    assert (rtl / "shared_defs.vh").is_file()


# ── macro with no defining file → actionable hint, no crash ────────────────

def test_unresolvable_macro_emits_hint_not_crash(tmp_path):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top(); wire x = `MISSING_MACRO; endmodule\n")
    (proj / "input" / "design_src").mkdir(parents=True, exist_ok=True)
    res = R._v662_resolve_dependency_files(proj, auto_stage=True)
    assert "MISSING_MACRO" in res["undefined_macros"]
    assert res["staged"] == []
    assert any("MISSING_MACRO" in h and "no defining file" in h
               for h in res["hints"])
