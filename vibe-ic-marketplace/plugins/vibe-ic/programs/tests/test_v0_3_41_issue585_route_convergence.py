"""ORGANIC #585 — step_pnr reported PASS when detailed route COMPLETED
with nonzero DRT violations (`Completing 100% with N violations`,
`[INFO DRT-0199] Number of violations = N`, rc=0): the unconverged GDS
flowed downstream and one congestion root-cause surfaced as hundreds of
fake DRC/LVS/STA findings (live: 297 route violations → 640 DRC).

Fix: _drt_final_violations() parses the LAST DRT-0199 count (fallback:
last `Completing 100% with N violations`); step_pnr FAILs with finding
ROUTE_NOT_CONVERGED naming N + the congestion knobs when N > 0; outputs
stay on disk but are marked non-signoff in extras.
"""
import ast
import inspect
import sys
import textwrap
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── reading the wiring as CODE, not as text ──────────────────────────────────
# A SOURCE OFFSET IS NOT A PROPERTY. The wiring order below used to be asserted
# with `src.index(a) < src.index(b)` over the raw text of `step_pnr`, and
# `str.index` returns the FIRST occurrence anywhere -- prose included. A comment
# 1455 lines above the gate ("antenna 22 -> 0, then ROUTE_NOT_CONVERGED: 1
# Metal-1 spacing, ...") therefore became the anchor, and the test reported
# `109936 < 23302` FALSE while the code order it exists to protect was intact:
# the rc/def-file gate is at line 1848 of the function and the finding is
# raised at 2109. The red was a sentence, not a defect.
#
# These helpers read the function's own AST. Comments are not in an AST, so a
# comment can neither satisfy nor break an assertion here; a real reorder still
# does, because it moves the line numbers of the CODE.


def _fn_ast(fn) -> ast.FunctionDef:
    return ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]


def _str_lines(node, needle):
    """Lines of the STRING CONSTANTS carrying `needle`. Not comments."""
    return sorted(n.lineno for n in ast.walk(node)
                  if isinstance(n, ast.Constant)
                  and isinstance(n.value, str) and needle in n.value)


def _call_lines(node, name):
    """Lines where `name(...)` is actually CALLED."""
    return sorted(n.lineno for n in ast.walk(node)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == name)


def _if_lines(node, test_src):
    """Lines of the `if` statements whose condition is exactly `test_src`."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.If):
            continue
        try:
            if ast.unparse(n.test) == test_src:
                out.append(n.lineno)
        except Exception:                        # noqa: BLE001
            continue
    return sorted(out)


# ── parser semantics ─────────────────────────────────────────────────────────

def test_parses_last_drt_0199_count():
    log = (
        "[INFO DRT-0195] Start 55th optimization iteration.\n"
        "Completing 100% with 312 violations.\n"
        "[INFO DRT-0199] Number of violations = 312.\n"
        "[INFO DRT-0195] Start 56th optimization iteration.\n"
        "Completing 100% with 297 violations.\n"
        "[INFO DRT-0199] Number of violations = 297.\n"
    )
    assert R._drt_final_violations(log) == 297


def test_parses_completing_line_fallback():
    log = "Completing 100% with 5 violations.\n"
    assert R._drt_final_violations(log) == 5


def test_converged_route_reads_zero():
    log = (
        "Completing 100% with 0 violations.\n"
        "[INFO DRT-0199] Number of violations = 0.\n"
        "[INFO DRT-0267] cpu time = ...\n"
    )
    assert R._drt_final_violations(log) == 0


def test_no_route_in_log_reads_none():
    assert R._drt_final_violations("") is None
    assert R._drt_final_violations("GPL-0301 utilization 120%") is None


def test_spef_repair_incremental_reroute_final_count_wins():
    """The post-route SPEF-repair incremental reroute prints its own
    DRT-0199 — the LAST one is the shipped geometry's state."""
    log = (
        "[INFO DRT-0199] Number of violations = 0.\n"   # main route clean
        "SPEF_REPAIR_CAPTABLE: ...\n"
        "[INFO DRT-0199] Number of violations = 3.\n"   # reroute left 3
    )
    assert R._drt_final_violations(log) == 3


# ── verdict wiring (the issue's 現象 end-state) ─────────────────────────────

def test_step_pnr_wires_route_convergence_gate():
    """step_pnr must consult _drt_final_violations after the rc gate and
    FAIL with ROUTE_NOT_CONVERGED naming the knobs when N > 0."""
    fn = _fn_ast(R.step_pnr)
    # vibe-ic#1080 — the consultation moved INTO `_drt_reading`, which runs the
    # prose parser AND cross-checks it against the tool's own metric. The
    # original intent is unchanged and is asserted on both halves rather than
    # relaxed: step_pnr must still consult the reading, and the reading must
    # still run `_drt_final_violations`. Dropping the second assertion would
    # let the prose parser be deleted without a test noticing, which is the
    # opposite of what this test was written to protect.
    #
    # EVERY ONE OF THESE IS NOW A CLAIM ABOUT CODE. Written as substrings of the
    # raw source they were also satisfiable by a comment naming the thing, which
    # is how the ordering assertion below came to be anchored on prose.
    consult = _call_lines(fn, "_drt_reading")
    assert consult, "step_pnr no longer CALLS _drt_reading"
    assert _call_lines(_fn_ast(R._drt_reading), "_drt_final_violations"), (
        "_drt_reading no longer CALLS _drt_final_violations: the prose parser "
        "can now be deleted with no test noticing")
    route = _str_lines(fn, "ROUTE_NOT_CONVERGED")
    assert route, "step_pnr no longer RAISES the ROUTE_NOT_CONVERGED finding"
    assert _str_lines(fn, "--die-um"), "the die knob is not named in the finding"
    assert _str_lines(fn, "--util"), "the util knob is not named in the finding"
    assert _str_lines(fn, "non_signoff_outputs"), (
        "the unconverged outputs are no longer marked non-signoff")

    # THE ORDERING PROPERTY, asserted where it lives: the routing-outcome gate
    # runs AFTER the rc/def-file FAIL gate, so an aborted route is reported as
    # an abort and not as an unconverged route. Line numbers of CODE, so a
    # reformat or a new comment cannot move them and a real reorder must.
    rc_gate = _if_lines(fn, "rc != 0 or not def_file.is_file()")
    assert len(rc_gate) == 1, (
        f"expected exactly one rc/def-file FAIL gate, found {rc_gate}. If it "
        f"was legitimately split, name the one that must come first.")
    assert rc_gate[0] < route[0], (
        f"the ROUTE_NOT_CONVERGED finding is raised at line {route[0]} of "
        f"step_pnr, BEFORE the rc/def-file FAIL gate at line {rc_gate[0]}: an "
        f"aborted route would be reported as an unconverged one")
    assert rc_gate[0] < consult[0], (
        f"_drt_reading is consulted at line {consult[0]}, before the rc/"
        f"def-file FAIL gate at line {rc_gate[0]}")


def test_drt_gate_verdict_directions(tmp_path):
    """Both directions per the issue: N>0 → FAIL shape; N==0 → no gate
    trip. Exercised through the parser + the wiring contract (full
    step_pnr needs docker; the parser is the deterministic core)."""
    bad = "Completing 100% with 297 violations.\n" \
          "[INFO DRT-0199] Number of violations = 297.\n"
    good = "[INFO DRT-0199] Number of violations = 0.\n"
    assert R._drt_final_violations(bad) == 297      # would FAIL
    assert R._drt_final_violations(good) == 0       # stays PASS
