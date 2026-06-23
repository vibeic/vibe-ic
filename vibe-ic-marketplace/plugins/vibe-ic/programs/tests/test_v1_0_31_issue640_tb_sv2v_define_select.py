"""ORGANIC #640 — the reference-TB sv2v pre-pass
(`design_one_shot_runner._iverilog_compile_with_sv_fallback`) historically
(a) staged NO .svh / *_pkg.* closure and passed NO -I include path, and
(b) hardcoded `sv2v -DSIMULATION`. On a SYNTHESIS-pruned REUSED-IP closure
the canonical assertion-macro header
(`ifdef VERILATOR / `elsif SYNTHESIS / `else -> `include
"<standard-macros>.svh") ships ONLY the synthesis-arm dummy-macros .svh;
the sim-arm standard-macros .svh is intentionally excluded. Under
-DSIMULATION the `else arm takes and `include's a never-staged header, so
sv2v dies at the lexer ("Could not find file …") before any parsing — even
though the IDENTICAL closure converts clean under -DSYNTHESIS (the define
the #587 synth path already uses, and which PASSes).

The fix mirrors #587 in the TB path: stage the .svh/.vh/.h + *_pkg.*
closure, pass -I <stage>, and pick the sv2v define STRUCTURALLY via
`synth_frontend.decide_sv2v_tb_define` — flip to -DSYNTHESIS IFF the
`include closure has a hole under -DSIMULATION that -DSYNTHESIS resolves
cleanly; otherwise keep -DSIMULATION so a genuine missing-include / RTL
defect still FAILs honestly.

These tests are docker-free: they exercise the REAL decision entry point
with synthetic in-memory closures, plus source-level pins on the TB
fallback. They cover BOTH the defect shape AND the load-bearing NEGATIVE
no-leak cases (an empty / under-staged / non-conditional closure must NOT
trigger the flip).
"""
import importlib
import inspect

sf = importlib.import_module("synth_frontend")
p2 = importlib.import_module("design_one_shot_runner")


# Canonical vendor assertion-macro header: synth-arm uses the dummy
# macros, the `else (simulation) arm includes the standard macros.
_PRIM_ASSERT = """\
`ifdef VERILATOR
  `include "prim_assert_dummy_macros.svh"
`elsif SYNTHESIS
  `include "prim_assert_dummy_macros.svh"
`else
  `include "prim_assert_standard_macros.svh"
`endif
module dut; endmodule
"""

_DUMMY_MACROS = "`define ASSERT(__name, __prop)\n"
_STD_MACROS = "`define ASSERT(__name, __prop)\n"


# --------------------------------------------------------------------------
# 1. DEFECT SHAPE — synth-pruned closure: only the dummy-macros .svh is
#    staged. Under -DSIMULATION the `else arm `include's the never-staged
#    standard-macros header (closure HOLE); -DSYNTHESIS resolves clean.
#    The decision MUST flip to SYNTHESIS so the staged arm is selected.
# --------------------------------------------------------------------------
def test_synth_pruned_closure_flips_to_synthesis():
    files = {
        "prim_assert.sv": _PRIM_ASSERT,
        "prim_assert_dummy_macros.svh": _DUMMY_MACROS,
    }
    define, reason = sf.decide_sv2v_tb_define(files)
    assert define == "SYNTHESIS", (
        f"synth-pruned closure must convert under -DSYNTHESIS so the "
        f"staged dummy-macros arm is selected; got {define!r} ({reason})")
    assert "SYNTHESIS" in reason


# --------------------------------------------------------------------------
# 2. NEGATIVE no-leak — closure complete under SIMULATION (BOTH macro
#    headers staged). The historical -DSIMULATION behaviour MUST be kept;
#    flipping here would be a needless behaviour change.
# --------------------------------------------------------------------------
def test_complete_sim_closure_keeps_simulation():
    files = {
        "prim_assert.sv": _PRIM_ASSERT,
        "prim_assert_dummy_macros.svh": _DUMMY_MACROS,
        "prim_assert_standard_macros.svh": _STD_MACROS,
    }
    define, _reason = sf.decide_sv2v_tb_define(files)
    assert define == "SIMULATION", (
        "a closure that already resolves under -DSIMULATION must not flip")


# --------------------------------------------------------------------------
# 3. NEGATIVE no-leak — genuinely UNDER-STAGED closure: NO macro header at
#    all. The include is unresolved under BOTH arms (the synth dummy-macros
#    header is missing too), so this is a real closure defect — keep
#    -DSIMULATION so the honest sv2v/iverilog failure still surfaces. The
#    fix must NOT relax the floor so far that an under-staged closure
#    silently "passes" by flipping the define.
# --------------------------------------------------------------------------
def test_under_staged_closure_does_not_flip():
    files = {"prim_assert.sv": _PRIM_ASSERT}  # no .svh staged at all
    define, _reason = sf.decide_sv2v_tb_define(files)
    assert define == "SIMULATION", (
        "an under-staged closure (synth arm ALSO missing its header) must "
        "keep -DSIMULATION so the honest failure stands — never flip to "
        "mask a real missing-include defect")


# --------------------------------------------------------------------------
# 4. NEGATIVE no-leak — EMPTY input must never trigger a flip.
# --------------------------------------------------------------------------
def test_empty_input_keeps_simulation():
    define, reason = sf.decide_sv2v_tb_define({})
    assert define == "SIMULATION"
    assert "no staged sources" in reason


# --------------------------------------------------------------------------
# 5. NEGATIVE no-leak — plain RTL with NO conditional `include arms keeps
#    the historical -DSIMULATION.
# --------------------------------------------------------------------------
def test_plain_rtl_keeps_simulation():
    files = {"foo.sv": "module foo (input a, output b); assign b = ~a;\n"
                       "endmodule\n"}
    define, _reason = sf.decide_sv2v_tb_define(files)
    assert define == "SIMULATION"


# --------------------------------------------------------------------------
# 6. SOURCE PINS — the TB fallback must (a) NOT hardcode `-DSIMULATION` in
#    its sv2v command, (b) route the define through the structural decision
#    helper, and (c) pass an -I include path so staged headers resolve.
# --------------------------------------------------------------------------
def test_tb_fallback_uses_structural_define_and_include_path():
    src = inspect.getsource(p2._iverilog_compile_with_sv_fallback)
    # No more hardcoded -DSIMULATION in the sv2v invocation.
    assert "sv2v -DSIMULATION" not in src, (
        "TB sv2v pre-pass must not hardcode -DSIMULATION (#640)")
    # Define is chosen structurally via the shared helper.
    assert "decide_sv2v_tb_define" in src, (
        "TB sv2v pre-pass must select the define via "
        "synth_frontend.decide_sv2v_tb_define")
    assert "-D{sv2v_define}" in src
    # Include path is passed so staged .svh / pkg headers resolve.
    assert "-I {stage}" in src, (
        "TB sv2v pre-pass must pass -I <stage> so the staged header / "
        "package closure resolves (mirrors #587)")


def test_decide_helper_signature_is_chip_agnostic():
    # The decision takes ONLY an in-memory file-text map + abstract define
    # names — no chip/vendor/SKU parameter — so it generalises to every IC.
    sig = inspect.signature(sf.decide_sv2v_tb_define)
    params = list(sig.parameters)
    assert params[0] == "files_text"
    assert "sim_define" in params and "synth_define" in params
