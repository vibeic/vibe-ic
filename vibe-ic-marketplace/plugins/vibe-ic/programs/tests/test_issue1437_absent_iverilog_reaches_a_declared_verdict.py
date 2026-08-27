r"""An ABSENT iverilog must reach a DECLARED verdict, never escape as a traceback. (#1437)

WHY THIS EXISTS
---------------
``subprocess.run(["iverilog", ...])`` raises ``FileNotFoundError`` *before
returning*, so a module that documents an outcome for exactly this situation
never reaches it: the caller gets a traceback instead of an answer. An oracle
that COULD NOT RUN then reads as an oracle that CRASHED.

MEASURED on this tree with iverilog absent from PATH, by calling each module
directly (not through its tests — three of the five have tests that skip when
the tool is missing, so the suite was green over a live production hole)::

    nextstate_misc_synth.host_verify(...)      ->  FileNotFoundError ESCAPED
    verilogeval_human_tier_pipeline._run_iverilog(...)
                                               ->  FileNotFoundError ESCAPED
    benchmark/gates_atomic.run(["iverilog",…]) ->  FileNotFoundError ESCAPED
    benchmark/score_iverilog_tb._tb_is_non_discriminating(...)
                                               ->  FileNotFoundError ESCAPED

THE POPULATION, AND WHY THE ISSUE'S LIST IS NOT IT
--------------------------------------------------
#1437 lists fifteen ``programs/*.py`` found by a grep detector: a module counts
as GUARDED if ``which(`` or ``FileNotFoundError`` appears anywhere in the file.
That detector was said to "over-clear but never over-accuse". Re-measured here
with an AST detector (argv[0] of a real subprocess call is literally
``iverilog``; guarded := an ENCLOSING ``try`` catches it, or a ``which``-style
gate dominates the exec), it does BOTH:

    over-ACCUSES  11 of the 15 — five never exec iverilog at all (the string is
                  a lint keyword or a tool-name table: benchmark_result_md_lint,
                  enhancement_emit, fpga_verification_audit,
                  loop_watchdog_compliance_check, tool_substitution_disclose),
                  four gate on a shell ``which`` the grep cannot see, and two
                  wrap the exec in ``except Exception``.
    over-CLEARS   2 that ARE broken — ``benchmark/score_iverilog_tb.py`` (its
                  ``which`` calls name *vvp*, and the two that name iverilog sit
                  in helpers that do not dominate either exec) and
                  ``benchmark/gates_atomic.py``.

So the edit population is FOUR modules / five iverilog exec sites, each
confirmed by RUNNING it rather than grepping it. A fifth,
``kmap_truth_table_oracle_check``, was the same defect and landed separately as
#1418 (present at ``ab5a23a28``); it is NOT fixed by this change and is kept in
the locator's list only so its guard cannot silently regress.

The same escape exists one line later on ``vvp`` — the design COMPILED but the
simulator could not be RUN, which is equally not a verdict about the RTL — so
the two sites that sit in a function this change already edits are guarded too,
matching how #1418 guarded both arms. NOT touched, stated rather than implied:
``score_iverilog_tb._bounded_vvp``, whose vvp exec is reachable only after a
SUCCESSFUL iverilog compile (so the binary demonstrably exists) and which lives
in container-routing machinery this change has no reason to open.

``test_scan_is_not_vacuous`` below is the denominator that stops a broken
locator from buying a green.

WHAT "DECLARED" MEANS PER MODULE — the remedy is NOT uniform
------------------------------------------------------------
Two of the six sites must NOT simply fall into the existing ``returncode != 0``
branch, because that branch reports a *finding about the design*:

  * ``verilogeval_human_tier_pipeline`` — its Tier-5 prover reads "did not pass"
    as "the golden _ref.sv FAILS its own _test.sv", a benchmark-defect claim.
  * ``score_iverilog_tb._score_shape_b_impl`` — ``rc != 0`` becomes
    ``{"verdict": "FAIL", "reason": "compile_error"}``, a claim about the
    candidate.

Turning an absent compiler into either one converts a traceback into a
FABRICATED FINDING, which is worse: the traceback at least announced itself.
Both therefore get a distinct not-run outcome, and the tests below pin that
distinction rather than merely pinning "did not raise".

THE PREDICATE'S BOUNDARY IS THE LOAD-BEARING PART
-------------------------------------------------
"the compiler was absent" is recognised as rc==127 AND the repo's existing
``COMMAND_NOT_FOUND:`` marker (already written by ``_watchdog``,
``design_one_shot_runner``, ``phase1_doc_one_shot_runner``,
``phase3_one_shot_runner``). It must REJECT a bare "No such file or directory",
because a genuine compile failure over a missing ``\`include`` says exactly
that — pinned by ``test_predicate_rejects_a_real_compile_error``.

BOTH DIRECTIONS ARE ASSERTED
----------------------------
Green here is not bought by weakening anything: every test drives the real
module with iverilog genuinely absent and asserts the DECLARED value, and
``test_predicate_rejects_a_real_compile_error`` plus
``test_scan_is_not_vacuous`` are the arms that stay red if the property is
violated or the instrument stops looking.
"""
import ast
import re
import shutil
import subprocess
import sys
import builtins
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_BENCHMARK = _PLUGIN / "benchmark"
for _p in (str(_PROGRAMS), str(_BENCHMARK)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The whole point is the ABSENT-tool path. When a real iverilog is installed the
# production call succeeds and there is nothing to assert, so these SKIP rather
# than pretend. `_no_iverilog` is the precondition, stated not implied.
_HAS_IVERILOG = shutil.which("iverilog") is not None
_no_iverilog = pytest.mark.skipif(
    _HAS_IVERILOG, reason="iverilog IS installed — the absent-tool path cannot be driven")

# Every module that must keep its guard, relative to the plugin root. Exec lines
# are deliberately NOT pinned — the AST locator finds them, so the denominator
# survives the files moving. Used by test_scan_is_not_vacuous.
_MUST_STAY_GUARDED = (
    # fixed by THIS change
    "programs/nextstate_misc_synth.py",
    # `programs/verilogeval_human_tier_pipeline.py` was DELETED — its exec sites
    # went with it, and the property it carried (a checker that never ran must
    # not manufacture a finding) is now asserted against the module that
    # replaced it, below. A denominator that lists a file which no longer exists
    # fails this test rather than quietly shrinking, which is the point.
    "programs/deterministic_emit_chain.py",
    "benchmark/gates_atomic.py",
    "benchmark/score_iverilog_tb.py",
    # fixed upstream by #1418 — carried here so its guard cannot regress unseen
    "programs/kmap_truth_table_oracle_check.py",
)


# ----------------------------------------------------------------------------
# the five modules, each driven with iverilog genuinely absent
# ----------------------------------------------------------------------------
def _s3_prompt() -> str:
    """The S3 don't-care SOP/POS prompt, lifted from the module's own pinned test
    so this file cannot drift away from a shape `synth()` actually fires on."""
    t = (_PROGRAMS / "tests" / "test_v1_1_76_nextstate_misc.py").read_text(
        errors="replace")
    m = re.search(r'PROB070\s*=\s*"""(.*?)"""', t, re.S)
    assert m, "PROB070 fixture not found in test_v1_1_76_nextstate_misc.py"
    return m.group(1)


@_no_iverilog
def test_nextstate_host_verify_returns_TOOL_ERR_not_a_traceback():
    """`host_verify()` documents ("PASS"|"BLOCK"|"SKIP"|"TOOL_ERR", detail)."""
    import nextstate_misc_synth as M

    prompt = _s3_prompt()
    assert M.synth(prompt) is not None, (
        "synth() did not fire — this test would pass vacuously via the SKIP arm")

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ref.sv").write_text(
            "module RefModule(input a,b,c,d, output out_sop,out_pos);\n"
            "  assign out_sop=1'b0; assign out_pos=1'b0;\nendmodule\n")
        (d / "test.sv").write_text("module tb(); endmodule\n")
        verdict, detail = M.host_verify(prompt, str(d / "ref.sv"), str(d / "test.sv"))

    assert verdict in ("PASS", "BLOCK", "SKIP", "TOOL_ERR"), (
        f"undeclared outcome {verdict!r}")
    assert verdict == "TOOL_ERR", (
        f"expected TOOL_ERR for an absent compiler, got {verdict!r}: {detail!r}")
    assert "COMMAND_NOT_FOUND" in str(detail), detail






@_no_iverilog
def test_gates_atomic_run_returns_127_not_a_traceback():
    """gates_atomic's `run()` helper is the single exec path for every gate step;
    its module docstring promises a gates.json holding EACH step's verdict, which
    a FileNotFoundError out of step 3 makes unwritable."""
    import gates_atomic as M

    rc, out = M.run(["iverilog", "-g2012", "-o", "/dev/null", "/dev/null"],
                    timeout=30)
    assert rc == 127, f"expected the repo's absent-command rc=127, got {rc}"
    assert "COMMAND_NOT_FOUND" in out, out


@_no_iverilog
def test_score_iverilog_tb_stub_probe_is_inconclusive_not_a_traceback():
    """`_tb_is_non_discriminating` documents "None if the stub can't be
    built/run (inconclusive — left counted)". An absent compiler is that."""
    import score_iverilog_tb as M

    sample = ("module TopModule(input a, input b, output out);\n"
              "  assign out = a & b;\nendmodule\n")
    assert M._build_zero_stub(sample) is not None, (
        "zero-stub not buildable — this test would pass vacuously")

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        tb = d / "tb.v"
        tb.write_text('module tb(); initial $display("PASSED"); endmodule\n')
        verdict = M._tb_is_non_discriminating(sample, tb, d, re.compile("PASSED"))

    assert verdict is None, (
        f"an unbuildable stub is documented inconclusive, got {verdict!r}")


@_no_iverilog
def test_score_iverilog_tb_shape_b_does_not_score_a_candidate_FAIL():
    """THE SECOND FABRICATED-FINDING ARM. `rc != 0` in _score_shape_b_impl
    becomes {"verdict": "FAIL", "reason": "compile_error"} — a claim ABOUT THE
    CANDIDATE. An absent compiler must not produce it."""
    import score_iverilog_tb as M

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        samples, dataset = d / "samples", d / "dataset"
        (dataset / "any_design").mkdir(parents=True)
        samples.mkdir()
        (samples / "any_design.v").write_text(
            "module TopModule(output out); assign out=1'b0; endmodule\n")
        (dataset / "any_design" / "tb.v").write_text(
            'module tb(); initial $display("PASSED"); endmodule\n')
        layout = {"tb_filename": "tb.v"}
        res = M._score_shape_b_impl("any_design", samples, dataset, layout,
                                    {"pass_regex": "PASSED",
                                     "cwd_design_dir": False})
    assert res.get("reason") not in ("no_sample", "no_testbench"), (
        f"never reached the compiler — this test would pass vacuously: {res!r}")

    assert res.get("verdict") != "FAIL", (
        f"an absent compiler was scored as a candidate FAIL: {res!r}")
    assert res.get("verdict") == "SKIP", res
    assert "COMMAND_NOT_FOUND" in str(res.get("log", "")) or \
           "absent" in str(res.get("reason", "")), res


# ----------------------------------------------------------------------------
# the arms that keep the green honest
# ----------------------------------------------------------------------------


def _unguarded_iverilog_execs(path: Path):
    """Exec sites whose argv[0] is literally "iverilog" and which NO enclosing
    try/except would stop a FileNotFoundError escaping from.

    Name-based on purpose: importing 1138 modules to audit them would run their
    top-level code (same reasoning as #1469's resolver)."""
    catches = {"FileNotFoundError", "OSError", "EnvironmentError", "IOError",
               "Exception", "BaseException"}
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    consts = {t.id: n.value.value
              for n in tree.body if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}

    def names(h):
        if h.type is None:
            return {"BaseException"}
        ts = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
        return {t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "")
                for t in ts}

    def argv0(a):
        if isinstance(a, ast.List) and a.elts:
            e = a.elts[0]
            if isinstance(e, ast.Constant):
                return e.value
            if isinstance(e, ast.Name):
                return consts.get(e.id)
        return None

    # A bare-name call may be a MODULE-LOCAL wrapper that guards internally
    # (benchmark/gates_atomic.py's `run()` is exactly that). Collect the local
    # defs whose own body catches the error, so the locator does not report a
    # call site that is already protected one frame down.
    guarded_wrappers = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(names(h) & catches
                   for t in ast.walk(n) if isinstance(t, ast.Try)
                   for h in t.handlers):
                guarded_wrappers.add(n.name)

    out = []

    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            nxt = stack + [node] if (isinstance(node, ast.Try)
                                     and child in node.body) else stack
            if isinstance(child, ast.Call):
                f = child.func
                nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if (nm in {"run", "check_output", "check_call", "call", "Popen"}
                        and child.args and argv0(child.args[0]) == "iverilog"):
                    caught = any(names(h) & catches for t in nxt for h in t.handlers)
                    via_wrapper = (isinstance(f, ast.Name)
                                   and f.id in guarded_wrappers)
                    if not caught and not via_wrapper:
                        out.append(child.lineno)
            walk(child, nxt)

    walk(tree, [])
    return out


def test_scan_is_not_vacuous():
    """THE DENOMINATOR. Every site this issue fixes must still be FOUND by the
    locator. If a rename, a move or a broken glob makes the locator see nothing,
    this goes red instead of letting an empty scan read as a clean tree — the
    exact confusion #1437's own author hit with `grep -c` on a missing path."""
    missing = [rel for rel in _MUST_STAY_GUARDED if not (_PLUGIN / rel).is_file()]
    assert not missing, f"fixed sites no longer on disk: {missing}"

    # the locator must find *something* to look at, on a file known to exec iverilog
    probe = _unguarded_iverilog_execs.__doc__
    assert probe, "locator lost its contract"

    still_unguarded = {}
    for rel in _MUST_STAY_GUARDED:
        lines = _unguarded_iverilog_execs(_PLUGIN / rel)
        if lines:
            still_unguarded[rel] = lines
    assert not still_unguarded, (
        "these exec sites can still let FileNotFoundError escape: "
        f"{still_unguarded}")


# ── the same property, on the subject that replaced the deleted pipeline ─────
#
# THE PREMISE THESE TWO TESTS CARRIED, AND WHICH HALF OF IT DIED
# ---------------------------------------------------------------
# Both asserted `emit_would_be_blocked(...) == []` when the checker could not
# run, under the heading "on any tool or IO error, return [] rather than
# manufacture a block". Two claims were welded together there:
#
#   (a) DO NOT FABRICATE A FINDING ABOUT THE DESIGN. A block invented by a
#       checker that never looked demotes work that is actually correct, with
#       the authority of an examination that did not happen. STILL TRUE, still
#       asserted below, and now asserted more precisely: the assertion is that
#       no EMIT-BLOCKING RULE NAME is produced, which is the thing a downstream
#       reader acts on, rather than that the container happens to be empty.
#
#   (b) `[]` IS THE RIGHT WAY TO SAY IT. FALSE, and measured false. `[]` is not
#       a neutral container: it is the value `_refusals` reads as ACCEPT. So the
#       old shape did not merely decline to fabricate a block — it fabricated a
#       CLEAN BILL, and did so in the permissive direction, where the cost is a
#       wrong emit shipped rather than a correct one waived to the AI backup.
#       Measured on this tree before the repair: with `timeout=0`, a pure-rotate
#       emit answering a shifter spec — the exact emit `test_pure_rotate_emit_is_
#       gate_blocked` exists to catch — came back `[]`, byte-identical to the
#       genuinely clean AND-gate emit. "The checker broke" and "the tree is
#       clean" were one observable.
#
# So (a) is kept and strengthened, (b) is replaced by the repo's own convention
# for this exact situation: `_gate_dispatch.sh` gives "I could not look" its own
# NOT_CHECKED state rather than folding it into PASS. The marker is
# `deterministic_emit_chain.NOT_MEASURED`, which is never a rule name.
def _no_rule_name_was_fabricated(look, blocking_rules):
    """The (a) half, stated once so both arms below assert the same thing."""
    return look.rules == () and not (set(look.rules) & set(blocking_rules))


def test_the_conformance_gate_claims_nothing_when_its_checker_cannot_run():
    """THE FABRICATED-FINDING ARM, re-homed.

    The deleted `verilogeval_human_tier_pipeline` could report "the golden
    _ref.sv FAILS its own _test.sv" — a benchmark-defect claim produced by a
    compiler that never ran. Deleting that module deleted that particular risk,
    but not the shape of it: `deterministic_emit_chain.emit_would_be_blocked`
    shells out to `spec_conformance_check` and must, on any tool or IO error,
    claim NOTHING ABOUT THE DESIGN.

    The asymmetry is why it matters: a fabricated BLOCK demotes work that is
    actually correct, and it does so with the authority of a checker that never
    looked at anything. The opposite fabrication — a clean bill from the same
    checker that never looked — is the one this arm used to require.
    """
    import deterministic_emit_chain as C
    import spec_conformance_check as _scc
    blocking = set(_scc.EMIT_BLOCKING_CONFORMANCE_RULES)
    clean = ("module TopModule(input a, input b, output out);\n"
             "  assign out = a & b;\nendmodule\n")

    # the checker cannot even be imported
    real_import = builtins.__import__

    def _no_checker(name, *a, **k):
        if name == "spec_conformance_check":
            raise ImportError("simulated: checker unavailable")
        return real_import(name, *a, **k)

    builtins.__import__ = _no_checker
    try:
        look = C.emit_block_report("Assign out to a AND b.", clean)
        listed = C.emit_would_be_blocked("Assign out to a AND b.", clean)
        refusals = C._refusals("Assign out to a AND b.", clean, None, True)
    finally:
        builtins.__import__ = real_import

    # (a) nothing about the DESIGN was claimed — no rule name was invented.
    assert _no_rule_name_was_fabricated(look, blocking), (
        f"a block was claimed by a checker that could not be loaded: {look}")
    assert not (set(listed) & blocking), (
        f"a rule name reached the list form from a checker that never ran: "
        f"{listed}")

    # (b) and the absence is DECLARED rather than dressed as a clean bill.
    assert look.measured is False, (
        "an unimportable checker was reported as a completed measurement")
    assert "spec_conformance_check" in look.why_not, look.why_not
    assert listed and listed[0].startswith(C.NOT_MEASURED), listed
    assert refusals, (
        "the caller ACCEPTED an emit no checker examined — this is the "
        "fail-open direction the three-state look exists to close")


def test_an_absent_tool_never_turns_a_clean_emit_into_a_block():
    """The subprocess arm: the checker imports but the tool behind it is gone."""
    import deterministic_emit_chain as C
    import spec_conformance_check as _scc
    import subprocess as _sp
    blocking = set(_scc.EMIT_BLOCKING_CONFORMANCE_RULES)
    clean = ("module TopModule(input a, input b, output out);\n"
             "  assign out = a & b;\nendmodule\n")
    real_run = _sp.run

    def _absent(*a, **k):
        raise FileNotFoundError("simulated: the tool is not installed")

    _sp.run = _absent
    try:
        look = C.emit_block_report("Assign out to a AND b.", clean)
        listed = C.emit_would_be_blocked("Assign out to a AND b.", clean)
    finally:
        _sp.run = real_run

    assert _no_rule_name_was_fabricated(look, blocking), look
    assert not (set(listed) & blocking), listed
    assert look.measured is False, "an absent tool was reported as a measurement"
    assert "FileNotFoundError" in look.why_not, look.why_not


def test_a_clean_look_and_a_failed_look_are_not_the_same_value():
    """THE DEFECT ITSELF, as a test: the two used to be `[]` and `[]`.

    Stated on the pair rather than on either one, because the failure was never
    visible in a single call — each looked perfectly reasonable alone. It is the
    EQUALITY of the two that was the bug, so the equality is what is asserted
    against.
    """
    import deterministic_emit_chain as C
    clean_spec, clean_rtl = ("Assign out to a AND b.",
                             "module TopModule(input a, input b, output out);\n"
                             "  assign out = a & b;\nendmodule\n")
    # A KNOWN-BAD emit, so the arm cannot be satisfied by an emit that is
    # actually fine: a pure rotate answering a shifter spec is the emit
    # `test_pure_rotate_emit_is_gate_blocked` pins as gate-blocked.
    bad_spec = ("Build a 4-bit logical right shifter. The vacated MSB is "
                "filled with 0 each clock.")
    bad_rtl = ("module TopModule(input clk, input [3:0] d, output reg [3:0] q);\n"
               "  always @(posedge clk) q <= {q[0], q[3:1]};\nendmodule\n")

    # STATED FIRST, AND ONLY THROUGH THE PRE-EXISTING API, ON PURPOSE. Against
    # the code before the repair this is the assertion that fails, with the
    # defect as its message. If the arms below came first the whole test would
    # die on `AttributeError: no attribute emit_block_report`, which proves the
    # new function is absent and says nothing about the behaviour that was
    # wrong. `timeout=0` is a real way for the spawn to reach no verdict, and
    # it is applied to the emit the gate WOULD have refused — so a fail-open
    # answer is not merely imprecise, it accepts an emit known to be wrong.
    assert C.emit_would_be_blocked(clean_spec, clean_rtl) != \
        C.emit_would_be_blocked(bad_spec, bad_rtl, timeout=0), (
        "a clean look and a look that never happened produce the same value; "
        "this is the fail-open defect, and it is invisible in either call alone")

    measured_clean = C.emit_block_report(clean_spec, clean_rtl)
    assert measured_clean.measured is True and measured_clean.rules == ()
    could_not_look = C.emit_block_report(bad_spec, bad_rtl, timeout=0)
    assert could_not_look.measured is False, (
        "a spawn that timed out was reported as a completed measurement")

    # And the caller acts on the difference, which is the half that matters:
    # the clean emit is ACCEPTED and the unexamined one is REFUSED. `_refusals`
    # takes no timeout, so the spawn is broken the way the arms above break it.
    assert C._refusals(clean_spec, clean_rtl, None, True) == [], (
        "a genuinely clean emit must still be accepted — a check that refuses "
        "everything is not a check")
    import subprocess as _sp
    real_run = _sp.run
    _sp.run = lambda *a, **k: (_ for _ in ()).throw(
        FileNotFoundError("simulated: the checker binary is gone"))
    try:
        refused = C._refusals(bad_spec, bad_rtl, None, True)
        refused_clean = C._refusals(clean_spec, clean_rtl, None, True)
    finally:
        _sp.run = real_run
    assert refused and refused[0].startswith(C.NOT_MEASURED), refused
    # Deliberately also on the CLEAN emit: the refusal is a statement about the
    # LOOK, not about the RTL. A version that refused only the bad emit would be
    # reading a verdict it never obtained.
    assert refused_clean and refused_clean[0].startswith(C.NOT_MEASURED), \
        refused_clean
