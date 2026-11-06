"""vibe-ic#2225 — the repair/retry loop re-dispatched its producer, not its readers.

WHAT WAS MEASURED, BEFORE ANY OF THIS WAS WRITTEN
=================================================
A real run's own `reports/orchestrator/phase2_one_shot.json`
(ve1903 final7 `Prob002_m2014_q4i`), step records in order:

    rtl_gen        BLOCKED  REFUSED TO RUN: phase1/extraction_patterns.json
    rtl_validate   BLOCKED  REFUSED TO RUN: phase2/stage1/rtl/*.sv OR *.v
                            (owed by step 1, read by step 2)
    sim            BLOCKED  REFUSED TO RUN: ...      (owed by step 1, read by 4)
    reference_tb   BLOCKED  rtl/ missing
    rtl_repair_retry_iter   RTL_REPAIR_RETRY 1/3
    rtl_gen        PASS     deterministic emit -> phase2/stage1/rtl/ EXISTS

and then `rtl_validate` and `sim` are never dispatched again. Their refusals
were true when they were recorded and false by the end of the run.

Re-measured against the LIVE pre-flight on a tree built for it (the shape of
`test_the_defect_the_two_sites_refuse_then_the_producer_produces` below): after
the RTL lands, `step_preflight.decide` returns READY for both sites, while the
run's own final record for both is still `BLOCKED / REQUIRED_INPUT_ABSENT` —
and `flow_dashboard_data._runner_verdict_overrides`, which already takes a
site's FINAL record, publishes that stale refusal as flow step 4's status.

ONE ROOT CAUSE. Not one per starved site: the loop re-dispatches its PRODUCER
outside `step_preflight.gate` and nothing revisits the sites that refused
BECAUSE that producer had not produced.

WHAT THESE TESTS PIN, AND WHAT THEY REFUSE TO PIN
=================================================
Every refusal below is built by CALLING `step_preflight.gate` on a real project
tree — never by hand-writing a `StepResult` that looks like one. A test that
constructs its own refusal proves the repair can read a shape the test invented;
these prove it can read the shape the flow actually emits.

They do NOT assert that the run's verdict turns green. `_aggregate_verdict`
counts a superseded BLOCKED as FAIL exactly as it counts `rtl_gen`'s today, and
a run that had to repair a starved producer is not a clean run. The claim is
narrower and is the issue's: the run's record for those sites must describe the
tree the run actually left behind.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R      # noqa: E402


# --------------------------------------------------------------------------- #
# Tree builders. Nothing here is a fixture standing in for an execution — these
# make the STATE, and the pre-flight is then really run against it.
# --------------------------------------------------------------------------- #














# --------------------------------------------------------------------------- #
# 1. THE DEFECT, AND THE REPAIR, ON THE SAME TREE
# --------------------------------------------------------------------------- #








# --------------------------------------------------------------------------- #
# 2. WHAT MUST NOT BE TOUCHED — each of the issue's 驗收 bullets, measured
# --------------------------------------------------------------------------- #












# --------------------------------------------------------------------------- #
# 3. THE WIRING — every retry re-dispatch of the producer is followed by it,
#    and the loop's own termination guard still measures the producer alone
# --------------------------------------------------------------------------- #
def _main_ast() -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(R))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("design_one_shot_runner.main not found")


def _call_name(node) -> str:
    """`f(...)` -> 'f'; `a.b(...)` -> 'b'; anything else -> ''."""
    if not isinstance(node, ast.Call):
        return ""
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _retry_reentries():
    """Every `plan.append(step_rtl_gen(...))` in `main()`, with the two
    statements that follow it in the SAME block."""
    out = []
    for node in ast.walk(_main_ast()):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            for i, stmt in enumerate(body):
                if (isinstance(stmt, ast.Expr)
                        and _call_name(stmt.value) == "append"
                        and stmt.value.args
                        and _call_name(stmt.value.args[0]) == "step_rtl_gen"):
                    out.append((stmt, body[i + 1:i + 3]))
    return out


def test_every_retry_reentry_is_followed_by_the_redispatch_after_its_digest():
    """The behavioural tests above prove the helper; this proves the loops call
    it, and that the ORDER at each site is the one the loop depends on.

    `#49 Fix 1` aborts the repair loop when a retry emits byte-identical RTL, so
    the digest has to be the PRODUCER's. A re-dispatched gate may legitimately
    write into `rtl/` (`test_a_redispatch_can_move_the_rtl_digest` measures that
    it can), and a digest taken after one would read as the emitter having made
    progress — an inert loop that never terminates. So at every re-entry the
    order is: producer, digest, re-dispatch.
    """
    sites = _retry_reentries()
    assert len(sites) >= 4, (
        f"only {len(sites)} retry re-entry site(s) of `step_rtl_gen` found in "
        "main(); the runner has two repair/retry loops, each with a plain and "
        "a hint-remediated re-dispatch")
    for stmt, following in sites:
        line = stmt.lineno
        assert len(following) == 2, f"line {line}: nothing follows the re-entry"
        digest, redispatch = following
        assert (isinstance(digest, ast.Assign)
                and _call_name(digest.value) == "_rtl_dir_sha256"), (
            f"line {line}: the statement after the re-entry is not the RTL "
            "digest the byte-identical-retry guard reads")
        assert (isinstance(redispatch, ast.Expr)
                and _call_name(redispatch.value)
                == "_redispatch_starved_sites"), (
            f"line {line}: this repair/retry re-dispatches `step_rtl_gen` and "
            "never revisits the sites that producer had starved — see "
            "vibe-ic#2225; their pre-retry refusals stay as the run's answer")
        assert digest.lineno < redispatch.lineno






def test_every_site_dispatched_before_a_repair_loop_registers_its_redispatch():
    """A site can only be replayed if the dispatch registered how. Both sites
    that the reference_tb repair loop can starve — the ones dispatched BEFORE
    it — go through `_dispatch_site`, which registers as a side effect of
    dispatching so the two can never describe different calls."""
    src = inspect.getsource(R)
    for site in ("rtl_validate", "sim"):
        assert f'_dispatch_site("{site}"' in src, (
            f"site {site!r} is dispatched without registering a re-dispatch; "
            "after an RTL repair/retry its refusal can only be superseded by "
            "SUPERSEDED_UNMEASURED, never re-measured")
