"""Sign-off DRC gate must read the router DRC report's LAST iteration count.

DEFECT (vibe-ic, signoff_audit.py:1423-1425). The tapeout sign-off audit's
plain-text DRC reader `_drc_violation_count` extracts the violation count with
`re.search`, which returns the FIRST match. A detailed-route DRC report is
ITERATIVE — the router prints one running count per repair iteration
(`[INFO DRT-0199]  Number of violations = N`) and a report may hold more than
one route pass — so `re.search` reads the state BEFORE any repair. That first
count can be:

  * LARGER  than the final count → over-report → false FAIL on a clean design;
  * SMALLER than the final count → under-report → false PASS on a design that
    NEVER CONVERGED — the serious half: a sign-off gate silently passing dirty
    geometry.

Meanwhile the SAME plugin's `phase3_one_shot_runner._drt_final_violations`
documents "Uses the LAST" and returns `counts[-1]`. Two readers, one grammar,
different answers, by construction.

FIX. Both readers now route through one shared helper
`_signoff_drc_format.router_iter_last_count`, which takes the LAST count.

This test drives the REAL nested `_drc_violation_count` bytes (extracted from
`signoff_audit._check_tapeout` via AST, exec'd against the module's own
globals) so it is a genuine bidirectional negative control: it FAILs against
the byte-identical pre-fix program (which returns the first count) and PASSes
after. All four brief fixtures are covered — A (monotone-to-zero), B (two route
passes, non-monotone), C (single count), D (no count → must be None, not 0) —
plus the earlier-format branches (invariant 2) and reader agreement
(invariant 4).

Fixtures reproduce §3 of DEFECT_BRIEF.md verbatim; integers are the brief's
disclosed placeholders. No PDK, no design, no EDA tool.
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import _signoff_drc_format as _sdf  # noqa: E402  the shared home
import phase3_one_shot_runner as P  # noqa: E402  the contrasting reader
import signoff_audit as SA          # noqa: E402  the gate under test


# --------------------------------------------------------------------------- #
# Extract the REAL nested `_drc_violation_count` from `_check_tapeout` so the   #
# test exercises the gate's actual source bytes, not a re-implementation.      #
# --------------------------------------------------------------------------- #
def _extract_gate_reader():
    src = Path(SA.__file__).read_text()
    tree = ast.parse(src)
    outer = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_check_tapeout")
    inner = next(n for n in outer.body
                 if isinstance(n, ast.FunctionDef)
                 and n.name == "_drc_violation_count")
    mod = ast.Module(body=[inner], type_ignores=[])
    ns = dict(vars(SA))          # the module's own globals: re, _sdf, Path, ...
    exec(compile(mod, SA.__file__, "exec"), ns)
    fn = ns["_drc_violation_count"]
    assert isinstance(fn, types.FunctionType)
    return fn


GATE_READER = _extract_gate_reader()


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


# --------------------------------------------------------------------------- #
# The four brief fixtures (§3, §5.2), verbatim structure.                       #
# --------------------------------------------------------------------------- #
FIXTURE_A = (
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "violation count summary: 0 violation(s) found\n"
    "drc source: final [INFO DRT-0199] count\n"
    "[INFO DRT-0199]   Number of violations = 100.\n"
    "[INFO DRT-0199]   Number of violations = 40.\n"
    "[INFO DRT-0199]   Number of violations = 10.\n"
    "[INFO DRT-0199]   Number of violations = 0.\n"
)
FIXTURE_B = (
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "drc source: final [INFO DRT-0199] count\n"
    "[INFO DRT-0199]   Number of violations = 5.\n"
    "[INFO DRT-0199]   Number of violations = 2.\n"
    "[INFO DRT-0199]   Number of violations = 0.\n"
    "[INFO DRT-0199]   Number of violations = 90.\n"
    "[INFO DRT-0199]   Number of violations = 30.\n"
    "[INFO DRT-0199]   Number of violations = 7.\n"
)
FIXTURE_C = (  # single count — "take the last" must degrade to "take the only"
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "[INFO DRT-0199]   Number of violations = 12.\n"
)
FIXTURE_D = (  # no count lines at all — must read None, never 0
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "this file was truncated before any iteration count was written\n"
)


# --------------------------------------------------------------------------- #
# 1. The gate reader itself — the bidirectional negative control.              #
#    Pre-fix these assert-7 / assert-0 lines fail (gate returns 5 / 100).      #
# --------------------------------------------------------------------------- #
def test_gate_reads_last_not_first_fixture_a(tmp_path):
    # monotone to zero: first=100 (false FAIL), last=0 (clean, correct)
    assert GATE_READER(_write(tmp_path, "a.rpt", FIXTURE_A)) == 0


def test_gate_reads_last_not_first_fixture_b(tmp_path):
    # THE separator: first=5, min=0, summary absent, last=7. Only "last" gives 7.
    # This is the false-PASS half — a fix tested only on A never sees it.
    assert GATE_READER(_write(tmp_path, "b.rpt", FIXTURE_B)) == 7


def test_gate_single_count_returns_that_count(tmp_path):
    # invariant 3: last-match degrades to only-match.
    assert GATE_READER(_write(tmp_path, "c.rpt", FIXTURE_C)) == 12


def test_gate_no_count_is_none_never_zero(tmp_path):
    # invariant 1 (most important): unreadable stays None, never 0.
    # 0 would turn "could not determine" into "design is clean" — false PASS.
    got = GATE_READER(_write(tmp_path, "d.rpt", FIXTURE_D))
    assert got is None          # the exact sentinel the caller treats as
    assert got != 0             # "could not determine"; 0 would be false PASS


# --------------------------------------------------------------------------- #
# 2. Invariant 2 — the earlier format branches still win, not shadowed.        #
# --------------------------------------------------------------------------- #
def test_report_database_branch_still_wins(tmp_path):
    # A KLayout report-database is counted by <item>, not the DRT path, even
    # when it also happens to mention a DRT-style line.
    xml = (
        "<report-database>\n"
        "  <item></item>\n"
        "  <item></item>\n"
        "  <item></item>\n"
        "[INFO DRT-0199]   Number of violations = 999.\n"
        "</report-database>\n"
    )
    assert GATE_READER(_write(tmp_path, "rdb.rpt", xml)) == 3


def test_svrf_branch_zero_fail_reads_zero_not_unparsed(tmp_path):
    # invariant 2: a clean foundry-deck sign-off (0 FAIL rules) must read 0,
    # NOT None — and must not be shadowed by the router-iteration branch.
    svrf = (
        "SVRF-native DRC report\n"
        "PASS rule.a op x -> 0\n"
        "PASS rule.b op y -> 0\n"
        "PASS rule.c op z -> 0\n"
    )
    assert GATE_READER(_write(tmp_path, "svrf.rpt", svrf)) == 0


# --------------------------------------------------------------------------- #
# 3. The shared helper — the single implementation both readers now use.       #
# --------------------------------------------------------------------------- #
def test_shared_helper_takes_last():
    assert _sdf.router_iter_last_count(FIXTURE_A) == 0
    assert _sdf.router_iter_last_count(FIXTURE_B) == 7
    assert _sdf.router_iter_last_count(FIXTURE_C) == 12
    assert _sdf.router_iter_last_count(FIXTURE_D) is None


def test_shared_helper_completing_fallback():
    # older builds print no DRT-0199 line — fall back to Completing 100% with N,
    # still LAST.
    log = (
        "Completing 100% with 42 violations.\n"
        "Completing 100% with 3 violations.\n"
    )
    assert _sdf.router_iter_last_count(log) == 3


# --------------------------------------------------------------------------- #
# 4. Invariant 4 — the two readers agree BY CONSTRUCTION, on every fixture.     #
# --------------------------------------------------------------------------- #
def test_two_readers_agree_by_construction(tmp_path):
    for name, body in (("a", FIXTURE_A), ("b", FIXTURE_B),
                       ("c", FIXTURE_C), ("d", FIXTURE_D)):
        gate = GATE_READER(_write(tmp_path, f"{name}.rpt", body))
        drt = P._drt_final_violations(body)
        assert gate == drt, f"readers disagree on fixture {name}: {gate!r} != {drt!r}"


def test_phase3_reader_unchanged_on_two_pass_report():
    # The contrasting reader was already correct; the fix must keep it so.
    assert P._drt_final_violations(FIXTURE_B) == 7
    assert P._drt_final_violations(FIXTURE_D) is None
