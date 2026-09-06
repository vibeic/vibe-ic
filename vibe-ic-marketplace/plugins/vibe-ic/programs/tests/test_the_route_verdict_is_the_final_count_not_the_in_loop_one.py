"""CZD-17 (ordrv5 ruling) — the route verdict is the FINAL count.

`drt_reconciliation` demanded that two readings agree which are taken at
DIFFERENT POINTS IN TIME:

  metric  `route__drc_errors`   OpenROAD emits it in FlexDR::end, BEFORE the
                                repair passes and before verifyRoute
                                (FlexDR.cpp:1714) — the state mid-loop.
  prose   `[INFO DRT-0702] Post-route verification: N violation(s).`
                                the whole-design verifyRoute — the FINAL
                                state, the geometry that ships.

So a difference is STRUCTURAL, not evidence of a broken tool, and refusing on
it records a converged route as UNKNOWN. RULING: the final count decides; the
in-loop count is diagnostic, recorded beside it; absence of ANY final reading
is still refused, because an unmeasured route must not read as a clean one.

The DRT excerpts below are copied verbatim from this lane's own RUN A
(subservient x gf180mcuD, image 0.3.46) — tool grammar only, chip-AGNOSTIC.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _sdf():
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(
        "_signoff_drc_format", PROGRAMS / "_signoff_drc_format.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["_signoff_drc_format"] = m
    spec.loader.exec_module(m)
    return m


# RUN A: thirteen in-loop lines at 1, then the repair cleared the junction.
RUNA_TAIL = "\n".join(
    ["[INFO DRT-0199]   Number of violations = 1."] * 13
    + ["[INFO DRT-0703] Post-route verification: 5 violation(s) repaired.",
       "[INFO DRT-0702] Post-route verification: 0 violation(s)."])

# The shape the ruling names for rbsub2: the loop reported clean, the FINAL
# whole-design verify found five. A REAL non-convergence.
# NOTE: rbsub2's own log is not present on this host; this is a fixture of the
# stated shape, not a copy of that run.
RBSUB2_SHAPE = "\n".join(
    ["[INFO DRT-0199]   Number of violations = 0.",
     "[INFO DRT-0702] Post-route verification: 5 violation(s)."])


# The in-loop number that produced the historical refusal did NOT come from the
# log: `router_iter_last_count` already appends the post-route VERIFIED count,
# so the log side reads 0. It came from the metrics JSON, measured on RUN A:
#     detailedroute__route__drc_errors = 1        (FlexDR::end, mid-loop)
#     [INFO DRT-0702] ... 0 violation(s)          (verifyRoute, final)
RUNA_IN_LOOP_METRIC = 1


def test_runa_final_is_zero_though_the_metric_said_one():
    m = _sdf()
    assert m.router_post_route_final_count(RUNA_TAIL) == 0
    # the log side already resolves to the verified count ...
    assert m.router_iter_last_count(RUNA_TAIL) == 0
    # ... so the disagreement was metric(1) vs prose(0): two points in time.
    assert RUNA_IN_LOOP_METRIC != m.router_post_route_final_count(RUNA_TAIL)


def test_a_real_non_convergence_is_still_caught():
    """The ruling must not turn into 'trust the loop'. Final 5 is a failure."""
    m = _sdf()
    assert m.router_post_route_final_count(RBSUB2_SHAPE) == 5


def test_silence_is_not_zero():
    """No final line at all -> None, never 0. An unmeasured route must not read
    as a clean one; the step refuses on this."""
    m = _sdf()
    assert m.router_post_route_final_count(
        "[INFO DRT-0199]   Number of violations = 1.") is None
    assert m.router_post_route_final_count("") is None


def _pnr_source() -> str:
    return (PROGRAMS / "phase3_one_shot_runner.py").read_text()


class _Rec:
    """The two fields `_route_verdict` reads, nothing else."""
    def __init__(self, ok, value, detail="metric 1 vs prose 0"):
        self.ok, self.value, self.detail = ok, value, detail


def _pnr():
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(
        "phase3_one_shot_runner", PROGRAMS / "phase3_one_shot_runner.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["phase3_one_shot_runner"] = m
    spec.loader.exec_module(m)
    return m


def test_runa_publishes_pass_and_records_the_diagnostic():
    """RUN A's real shape: metric 1, final 0. PASS on the final count, and the
    disagreement SAID rather than swallowed."""
    published, note, refuse = _pnr()._route_verdict(
        _Rec(ok=False, value=None), final_verified=0)
    assert refuse is False
    assert published == 0
    assert note is not None and "ROUTE_DRC_METRIC_DISAGREEMENT" in note
    assert "0" in note


def test_a_real_non_convergence_publishes_the_count():
    """rbsub2's shape: loop 0, final 5. The verdict is 5 — the caller's
    `> 0` branch then raises ROUTE_NOT_CONVERGED with that number."""
    published, _note, refuse = _pnr()._route_verdict(
        _Rec(ok=False, value=0), final_verified=5)
    assert refuse is False
    assert published == 5


def test_no_final_reading_at_all_still_refuses():
    published, note, refuse = _pnr()._route_verdict(
        _Rec(ok=False, value=None), final_verified=None)
    assert refuse is True
    assert published is None and note is None


def test_an_agreeing_run_is_untouched():
    """Control: when the two agree there is no note and no refusal, and the
    published number is unchanged from what it always was."""
    published, note, refuse = _pnr()._route_verdict(
        _Rec(ok=True, value=0), final_verified=0)
    assert (published, note, refuse) == (0, None, False)


def test_the_disagreement_is_recorded_not_refused():
    """RED before the ruling: the step returned FAIL on `not ok`.

    Asserted on the CODE, with the docstring stripped, so the guard cannot
    match its own explanation."""
    src = _pnr_source()
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "step_pnr"]
    assert len(fn) == 1
    body = list(fn[0].body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)):
        body = body[1:]
    code = "\n".join(ast.unparse(n) for n in body)
    # the refusal that used to fire on a disagreement is gone ...
    assert "'finding': 'ROUTE_DRC_METRIC_DISAGREEMENT'" not in code, code[:400]
    # ... the disagreement is still SAID, on stderr and in the step's extras ...
    assert "drt_metric_disagreement_note" in code
    # ... the final verified count is what the step reads ...
    assert "router_post_route_final_count" in code
    # ... and the decision itself is DELEGATED to the pure function the
    # behavioural tests above drive, so the two cannot diverge.
    assert "_route_verdict(_drt_rec, _drt_final)" in code
    assert "_drt_viol = _drt_published" in code


def test_the_absence_of_a_final_reading_is_still_a_refusal():
    """The one thing that must NOT become a note."""
    src = _pnr_source()
    assert "ROUTE_DRC_NOT_MEASURED" in src
    assert "no final count to" in src


def test_the_in_loop_metric_is_still_carried_for_a_reader():
    src = _pnr_source()
    assert "drt_in_loop_metric" in src
    assert "drt_final_verified" in src
