"""synth_frontend: control decisions key on OBSERVABLE OUTCOMES, not tool wording.

THE DEFECT (systemic, same shape as the lec_run slang-retry bug fixed in
ea13744db): `synth_frontend.py` drove five control decisions off hard-coded
allow-lists of tool ERROR PHRASING. Three of them had NO observable backstop:

  * `synth_frontend_should_retry_under_synthesis` — whether phase-3 synth retries
    the closure under -DSYNTHESIS. Keyed on "$urandom" / "Feature unimplemented" /
    "not allowed in a constant context".
  * `verilator_should_retry_synthesis_define`     — the phase-2 sim -DSYNTHESIS
    retry. Keyed on "stdrand" / "Unsupported: $urandom"; verilator renames its
    `Unsupported:` diagnostics between releases.
  * `sim_frontend_should_try_verilator`           — whether the sim path escapes
    to verilator after sv2v fails. Keyed on `Sym_brack_l_aster`, an
    Alex-generated LEXER TOKEN NAME — the most volatile string sv2v emits.

A reworded abort (SAME real failure, different phrasing) therefore made the
retry/escape silently not fire, converting a recoverable closure into an
honest-looking FALSE FAIL with nothing in the log to show a capability was
skipped.

THE FIX: each decision now reads (1) the OBSERVABLE — did the tool produce an
elaborated design / any usable output? — and (2) a DESIGN PROPERTY of the RTL:
does the source actually branch on the sim/synth define, or actually carry SVA
constructs? The wording survives only as an explanatory string in the reason.

§4.05 — widening a RETRY trigger must not widen what PASSES. Pinned below:
a real result is never re-read (no verdict shopping); a closure with no
define-conditional arm is never retried (the retry would re-read byte-identical
source); a testbench that itself branches on the define REFUSES the flip (the
one way this retry could make a failing run finish vacuously); and every retry
still has to satisfy the caller's own rc/artifact/marker check to pass.
"""
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import synth_frontend as SF  # noqa: E402


# ── fixtures: the DESIGN, not the diagnostics ───────────────────────────────

# A vendor primitive whose sim-only arm is unsynthesizable and whose `else arm
# is the real hardware. This is the DESIGN PROPERTY that makes a define flip
# meaningful.
DUT_DEFINE_CONDITIONAL = (
    "module prim_cdc_rand_delay(input clk, input d, output q);\n"
    "`ifdef SIMULATION\n"
    "  int dly;\n"
    "  always_ff @(posedge clk) dly <= $urandom_range(0, 3);\n"
    "  assign q = d ^ (dly == 0);\n"
    "`else\n"
    "  logic qq;\n"
    "  always_ff @(posedge clk) qq <= d;\n"
    "  assign q = qq;\n"
    "`endif\n"
    "endmodule\n")

# The same class of module with NO define-conditional arm: flipping the define
# feeds the frontend byte-identical text, so a retry provably cannot help.
DUT_NO_DEFINE_ARM = (
    "module adder(input [7:0] a, input [7:0] b, output [8:0] s);\n"
    "  assign s = a + b;\n"
    "endmodule\n")

# RTL that genuinely contains SVA/sequence/property constructs sv2v cannot lower.
DUT_WITH_SVA = (
    "module fifo_ctrl(input clk, input rst_n, input push);\n"
    "  sequence s_push_stable;\n"
    "    push [*3];\n"
    "  endsequence\n"
    "  assert property (@(posedge clk) disable iff (!rst_n) s_push_stable);\n"
    "endmodule\n")

# A real RTL defect in an assertion-free design — nothing an SV-2017 frontend
# would lower differently.
DUT_REAL_DEFECT = (
    "module m(input a, output b);\n"
    "  wire b = ;\n"
    "endmodule\n")

TB_PLAIN = ('module tb;\n'
            '  initial begin #10; $display("TB_DONE"); $finish; end\n'
            'endmodule\n')

# A testbench whose own checking lives inside the sim-define arm. Flipping the
# define would compile the checks away and let the run finish vacuously.
TB_DEFINE_CONDITIONAL = (
    'module tb;\n'
    '  initial begin\n'
    '    #10;\n'
    '`ifdef SIMULATION\n'
    '    if (dut.q !== expected) $fatal(1, "MISMATCH");\n'
    '`endif\n'
    '    $display("TB_DONE"); $finish;\n'
    '  end\n'
    'endmodule\n')

# The SAME real failure, phrased eight different ways. Every one of these is a
# plausible release-to-release rewording; NONE of them may change the decision.
REWORDED_SIMONLY_ABORTS = (
    "prim_cdc.sv:5:38: error: $urandom is not allowed in a constant context",
    "prim_cdc.sv:5:38: error: system function 'urandom_range' cannot be used "
    "in a constant expression",
    "%Error-UNSUPPORTED: prim_cdc.sv:5:38: Unsupported: $urandom",
    "%Error-UNSUPPORTED: prim_cdc.sv:5:38: System function not supported: "
    "$urandom_range",
    "%Error: prim_cdc.sv:17:8: Duplicate declaration of signal: stdrand",
    "error: Feature unimplemented: randomisation helper",
    "ERROR: frontend aborted (see above)",
    "",
)

REWORDED_SV2V_PARSE_ABORTS = (
    "m.sv:7:10: Parse error: unexpected token [* (Sym_brack_l_aster)",
    "sv2v: m.sv:7:10: syntax error near Sym_bracket_l_asterisk",
    "sv2v: m.sv:2:19: unexpected '[*' in sequence_expr",
    "sv2v: conversion failed",
    "",
)


# ═══════════════════════════════════════════════════════════════════════════
# POSITIVE — the reworded abort now fires the retry/escape
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("err", REWORDED_SIMONLY_ABORTS)
def test_synth_retry_fires_on_any_phrasing(err):
    """Site `:360`. The OBSERVABLE (no netlist) + the DESIGN PROPERTY (the
    closure branches on the define set) decide the retry. Under the old
    allow-list, phrasings 2/4/6/7/8 returned False → FALSE FAIL."""
    ok, reason = SF.synth_frontend_should_retry_under_synthesis(
        err, rtl_text_blob=DUT_DEFINE_CONDITIONAL, produced_output=False)
    assert ok is True, f"{err!r} → {reason}"
    assert "SYNTHESIS" in reason


@pytest.mark.parametrize("err", REWORDED_SIMONLY_ABORTS)
def test_verilator_retry_fires_on_any_phrasing(err):
    """Site `:301`. Same invariant on the phase-2 sim path."""
    ok, reason = SF.verilator_should_retry_synthesis_define(
        err, rtl_text_blob=DUT_DEFINE_CONDITIONAL, tb_text=TB_PLAIN,
        produced_output=False)
    assert ok is True, f"{err!r} → {reason}"


@pytest.mark.parametrize("err", REWORDED_SV2V_PARSE_ABORTS)
def test_verilator_escape_fires_on_any_phrasing(err):
    """Site `:160`. The escape is decided by "sv2v produced no conversion" +
    "the RTL really carries SVA", never by sv2v's lexer token names."""
    ok, reason = SF.sim_frontend_should_try_verilator(
        ["fifo_ctrl.sv"], 1, err, DUT_WITH_SVA, converted_exists=False)
    assert ok is True, f"{err!r} → {reason}"


def test_decision_is_invariant_across_wording():
    """The load-bearing property: hold the observable and the design property
    fixed, vary ONLY the wording — the boolean must not move. This is what a
    wording allow-list can never satisfy, and it is unfakeable by adding more
    phrases to a list."""
    for fn, kwargs in (
        (SF.synth_frontend_should_retry_under_synthesis,
         dict(rtl_text_blob=DUT_DEFINE_CONDITIONAL, produced_output=False)),
        (SF.verilator_should_retry_synthesis_define,
         dict(rtl_text_blob=DUT_DEFINE_CONDITIONAL, tb_text=TB_PLAIN,
              produced_output=False)),
    ):
        verdicts = {fn(e, **kwargs)[0] for e in REWORDED_SIMONLY_ABORTS}
        assert verdicts == {True}, f"{fn.__name__} varied with wording"

    escapes = {SF.sim_frontend_should_try_verilator(
        ["m.sv"], 1, e, DUT_WITH_SVA, converted_exists=False)[0]
        for e in REWORDED_SV2V_PARSE_ABORTS}
    assert escapes == {True}


def test_reason_records_the_observable_not_the_wording():
    """When the phrasing is unrecognised the reason must SAY the decision came
    from the observable — so the log never implies a phrase drove it."""
    _, reason = SF.synth_frontend_should_retry_under_synthesis(
        "ERROR: frontend aborted (see above)",
        rtl_text_blob=DUT_DEFINE_CONDITIONAL)
    assert "decided on the observable" in reason
    assert "`ifdef SIMULATION" in reason  # design-property evidence, logged


# ═══════════════════════════════════════════════════════════════════════════
# PROVEN-NEGATIVE (a) — a REAL error must not trigger a covering retry
# ═══════════════════════════════════════════════════════════════════════════

def test_synth_no_retry_without_define_conditional_arm():
    """A genuine synthesis error in a design with NO define-conditional arm:
    the -DSYNTHESIS retry would re-read BYTE-IDENTICAL source, so it must not
    run. This is the bound that keeps the widened trigger from covering real
    failures."""
    ok, reason = SF.synth_frontend_should_retry_under_synthesis(
        "ERROR: syntax error, unexpected TOK_ID at adder.sv:2",
        rtl_text_blob=DUT_NO_DEFINE_ARM, produced_output=False)
    assert ok is False
    assert "byte-identical" in reason


def test_verilator_no_retry_without_define_conditional_arm():
    ok, reason = SF.verilator_should_retry_synthesis_define(
        "%Error: Cannot find file containing module: some_missing_mod",
        rtl_text_blob=DUT_NO_DEFINE_ARM, tb_text=TB_PLAIN,
        produced_output=False)
    assert ok is False
    assert "byte-identical" in reason


def test_no_retry_when_design_property_unobservable():
    """Fail-safe: with no RTL text the design property cannot be observed, so
    the answer is NO RETRY. A retry decision must never be made on nothing."""
    assert SF.synth_frontend_should_retry_under_synthesis("$urandom")[0] is False
    assert SF.verilator_should_retry_synthesis_define("stdrand")[0] is False


def test_escape_refused_for_a_real_defect_in_an_assertion_free_design():
    """A genuine RTL defect with no SVA anywhere: an SV-2017 frontend would not
    lower it differently, so the escape must not fire and the FAIL stands."""
    ok, reason = SF.sim_frontend_should_try_verilator(
        ["m.sv"], 1, "m.sv:1: Parse error: unexpected token", DUT_REAL_DEFECT,
        converted_exists=False)
    assert ok is False
    assert "genuine defect" in reason


def test_retry_is_single_shot_not_a_loop():
    """No endless retry: each decision function is a pure predicate returning a
    single verdict, and once the retry has produced output the predicate goes
    False — so a caller that feeds its result back cannot spin."""
    ok_first, _ = SF.synth_frontend_should_retry_under_synthesis(
        "anything", rtl_text_blob=DUT_DEFINE_CONDITIONAL, produced_output=False)
    ok_after, _ = SF.synth_frontend_should_retry_under_synthesis(
        "anything", rtl_text_blob=DUT_DEFINE_CONDITIONAL, produced_output=True)
    assert (ok_first, ok_after) == (True, False)


# ═══════════════════════════════════════════════════════════════════════════
# PROVEN-NEGATIVE (b) — the retry cannot convert a FAIL into a PASS
# ═══════════════════════════════════════════════════════════════════════════

def test_verilator_retry_refused_when_the_testbench_branches_on_the_define():
    """THE §4.05 HOLE, closed. Flipping the define is only sound while it
    changes the DUT's arms. If the TESTBENCH also branches on it, the retry
    could compile the TB's own checking away and let the run finish vacuously —
    turning a genuine functional FAIL into a pass. Refuse the flip.

    The old wording gate had NO equivalent guard, so this is strictly stronger
    than the behaviour being replaced."""
    ok, reason = SF.verilator_should_retry_synthesis_define(
        "%Error: Unsupported: $urandom",
        rtl_text_blob=DUT_DEFINE_CONDITIONAL,
        tb_text=TB_DEFINE_CONDITIONAL, produced_output=False)
    assert ok is False
    assert "vacuously" in reason


def test_a_design_that_legitimately_fails_under_synthesis_still_fails():
    """A design whose SYNTHESIS arm is itself broken: the predicate still says
    "retry" (it cannot know in advance), but the retry then fails on its own
    merits and the caller keeps the FAIL. Pinned here as the contract: the
    predicate authorises an ATTEMPT, never a verdict — it returns no notion of
    pass, and the caller's rc/artifact check is the only thing that can."""
    ok, _ = SF.synth_frontend_should_retry_under_synthesis(
        "error: $urandom", rtl_text_blob=DUT_DEFINE_CONDITIONAL)
    assert ok is True
    # the predicate's whole contract is (bool, str) — no verdict, no artifact.
    result = SF.synth_frontend_should_retry_under_synthesis(
        "error: $urandom", rtl_text_blob=DUT_DEFINE_CONDITIONAL)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], bool) and isinstance(result[1], str)


# ═══════════════════════════════════════════════════════════════════════════
# PROVEN-NEGATIVE (c) — no verdict shopping
# ═══════════════════════════════════════════════════════════════════════════

def test_no_reread_once_a_real_result_exists():
    """Once the tool HAS produced output, no alternate-frontend / alternate-
    define re-read may be attempted. A real result is the verdict; re-reading
    it under another frontend hoping for a better answer is verdict shopping."""
    ok, reason = SF.synth_frontend_should_retry_under_synthesis(
        "%Error: Unsupported: $urandom",
        rtl_text_blob=DUT_DEFINE_CONDITIONAL, produced_output=True)
    assert ok is False
    assert "already produced" in reason

    ok, reason = SF.verilator_should_retry_synthesis_define(
        "%Error: Unsupported: $urandom",
        rtl_text_blob=DUT_DEFINE_CONDITIONAL, tb_text=TB_PLAIN,
        produced_output=True)
    assert ok is False
    assert "already produced" in reason

    ok, reason = SF.sim_frontend_should_try_verilator(
        ["m.sv"], 0, "", DUT_WITH_SVA, converted_exists=True)
    assert ok is False
    assert "cleanly" in reason


def test_default_frontend_success_never_falls_back():
    """Same invariant on the SV-frontend selection: a default frontend that
    SUCCEEDED is never re-read, whatever its log says."""
    need, reason = SF.decide_synth_frontend(
        ["m.sv"], 0, True, "syntax error TOK_PACKAGE everywhere",
        rtl_text_blob="package p; endpackage\n")
    assert need is False
    assert "succeeded" in reason


# ═══════════════════════════════════════════════════════════════════════════
# The DESIGN-PROPERTY primitives
# ═══════════════════════════════════════════════════════════════════════════

def test_define_conditional_arms_detects_every_directive_form():
    for src, expect in (
        ("`ifdef SIMULATION\n`endif\n", True),
        ("`ifndef SYNTHESIS\n`endif\n", True),
        ("`ifdef FOO\n`elsif SYNTHESIS\n`endif\n", True),
        ("`ifdef VERILATOR\n`endif\n", False),   # different define — flip is a no-op
        ("module m; endmodule\n", False),
        ("", False),
    ):
        got, _ = SF.define_conditional_arms_present(src)
        assert got is expect, src


def test_define_conditional_arms_honours_custom_define_names():
    got, _ = SF.define_conditional_arms_present(
        "`ifdef SIM\n`endif\n", sim_define="SIM", synth_define="SYN")
    assert got is True
    got, _ = SF.define_conditional_arms_present("`ifdef SIM\n`endif\n")
    assert got is False


def test_modern_sv_construct_probe_covers_a_dot_v_file():
    """The residual hole in the MEDIUM site `:49`/`:63`: the extension test only
    fires for `.sv`, so a `.v` file carrying SV constructs fell through to the
    wording allow-list. The design-property probe reads the SOURCE, so it fires
    for `.v` too — whatever the tool called its abort."""
    need, reason = SF.decide_synth_frontend(
        ["legacy.v"], 1, False, "ERROR: frontend aborted (see above)",
        rtl_text_blob="import my_pkg::*;\nmodule m; endmodule\n")
    assert need is True
    assert "modern-SV constructs" in reason
    # …and with no SV constructs in a .v file the fallback still stays off.
    need, _ = SF.decide_synth_frontend(
        ["legacy.v"], 1, False, "ERROR: frontend aborted (see above)",
        rtl_text_blob="module m(input a, output b); assign b = a; endmodule\n")
    assert need is False


def test_read_text_blob_is_bounded_and_survives_unreadable_files(tmp_path):
    good = tmp_path / "a.sv"
    good.write_text("module a; endmodule\n")
    blob = SF.read_text_blob([good, tmp_path / "missing.sv", tmp_path])
    assert "module a" in blob
    big = tmp_path / "big.sv"
    big.write_text("x" * 5000)
    assert len(SF.read_text_blob([big], cap_bytes=1000)) <= 1000


# ═══════════════════════════════════════════════════════════════════════════
# Call-site wiring: the design property must actually reach the predicates
# ═══════════════════════════════════════════════════════════════════════════

def test_callers_supply_the_design_property():
    """A predicate that CAN read the design property is useless if the runner
    never passes it — with no blob the fail-safe is "no retry", so an unwired
    call-site would silently disable the retry everywhere."""
    import inspect
    import design_one_shot_runner as D
    import phase3_one_shot_runner as P3

    p3 = inspect.getsource(P3.step_synth)
    assert "synth_frontend_should_retry_under_synthesis" in p3
    assert "rtl_text_blob=_sf.read_text_blob(rtl_files)" in p3
    assert "produced_output=netlist.is_file()" in p3

    esc = inspect.getsource(D._verilator_sim_escape)
    assert "rtl_text_blob=_sf.read_text_blob(rtl_files)" in esc
    assert "tb_text=_tb_text" in esc

    sim = inspect.getsource(D._iverilog_compile_with_sv_fallback)
    assert "converted_exists=converted_host.is_file()" in sim


# ═══════════════════════════════════════════════════════════════════════════
# MEDIUM site `:422` — capability probed by OBSERVATION, not by phrasing
# ═══════════════════════════════════════════════════════════════════════════

# Real `yosys -p 'read_slang'` transcripts captured from the vibeic-eda image.
_PROBE_BUILTIN = (
    "-- Running command `read_slang' --\n"
    "\n"
    "1. Executing SLANG frontend.\n"
    "error: no input files\n"
    "ERROR: Bad command\n")
_PROBE_ABSENT = (
    "-- Running command `read_bogus_cmd' --\n"
    "ERROR: No such command: read_bogus_cmd (type 'help' for a command "
    "overview)\n")


def test_slang_capability_decided_by_pass_execution_not_by_phrasing():
    """yosys numbers and announces every pass it actually DISPATCHES; an unknown
    command never reaches one. That is positive capability evidence, so the
    decision survives a rename of the not-found diagnostic."""
    assert SF.read_slang_is_builtin(_PROBE_BUILTIN) is True
    assert SF.slang_load_prefix(_PROBE_BUILTIN) == ""

    # Reworded not-found diagnostic, still no pass executed → still not built-in.
    reworded_absent = _PROBE_ABSENT.replace(
        "No such command: read_bogus_cmd", "unrecognised command 'read_slang'")
    assert SF.read_slang_is_builtin(reworded_absent) is True, (
        "documented residual: with the phrase gone and no pass line, the probe "
        "is INCONCLUSIVE and falls back to the fork-safe built-in default")

    # The definitive negative still yields the plugin load.
    absent = _PROBE_ABSENT.replace("read_bogus_cmd", "read_slang")
    assert SF.read_slang_is_builtin(absent) is False
    assert SF.slang_load_prefix(absent) == "plugin -i slang; "


def test_slang_probe_fork_safe_default_on_inconclusive_output():
    for out in ("", "some unrelated banner noise"):
        assert SF.read_slang_is_builtin(out) is True
        assert SF.slang_load_prefix(out) == ""
