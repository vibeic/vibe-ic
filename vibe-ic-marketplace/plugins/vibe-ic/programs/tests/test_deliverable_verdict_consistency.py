"""A deliverable may not ship a PASS over the orchestrator's FAIL.

MEASURED ESCAPE this suite pins (spm × ihp-sg13g2, 8HD-8, 2026-07-26)
=====================================================================
    RESULT.md                                   01:39   PASS_WITH_WAIVERS
    reports/orchestrator/vibe_ic_one_shot.json  09:44   FAIL  (halted_at=phase3)

The run shipped for 8 hours with a deliverable claiming PASS over its own FAIL,
and every gate stayed green. ``run_output_completeness_check`` — the one gate
that keys off the deliverable — returned ``COMPLETE / PASS`` while its OWN
evidence dict carried ``orchestrator_verdict='FAIL'``. It had both numbers in
hand and never compared them.

WHAT THIS SUITE IS FOR
======================
Test COUNT is not evidence. Each test below exists to FAIL when a specific
decision in the program is wrong. The mutation block at the bottom is the proof:
every mutation is applied to the real source, the suite is re-run, and the
mutation must be killed by a NAMED set of tests. A mutation no test kills means
the tests are padding.

THE ANTI-RUBBER-STAMP MUTATION (``test_mutation_M1_...``)
---------------------------------------------------------
The load-bearing one. It rewrites the orchestrator side to re-read the
DELIVERABLE instead of the runner's JSON — i.e. turns the program into a
checker that merely re-states the headline. Both sides then agree by
construction and the contradiction becomes unreachable. If that mutation
survives, this program proves nothing, and the suite must say so.

Chip-AGNOSTIC: no IC / vendor / PDK literal appears in any assertion.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

PROG_PATH = PROGRAMS / "deliverable_verdict_consistency_check.py"

import deliverable_verdict_consistency_check as G  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — a minimal run dir. The two sides are written INDEPENDENTLY: the
# deliverable is markdown authored "by the agent", the orchestrator is JSON
# "emitted by the runner". Nothing derives one from the other.
# ---------------------------------------------------------------------------
def _mkrun(tmp_path: Path, *, deliverable: str | None,
           orch_verdict: str | None,
           orch_name: str = "vibe_ic_one_shot.json",
           extra: dict | None = None) -> Path:
    run = tmp_path / "run"
    (run / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
    if deliverable is not None:
        (run / "RESULT.md").write_text(deliverable)
    if orch_verdict is not None:
        payload = {"phase": "vibe-ic", "verdict": orch_verdict}
        payload.update(extra or {})
        (run / "reports" / "orchestrator" / orch_name).write_text(
            json.dumps(payload, indent=2))
    return run


_PASS_MD = "# RESULT — a run\n\n**Verdict:** PASS\n\nBody text.\n"
_FAIL_MD = "# RESULT — a run\n\n**Verdict:** FAIL\n\nBody text.\n"


# ===========================================================================
# DEFECT DIRECTION — each of these MUST fail the check. If any returns PASS,
# the escape is open.
# ===========================================================================
def test_defect_pass_headline_over_orchestrator_fail(tmp_path):
    """THE escape: deliverable says PASS, orchestrator says FAIL."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR"
    assert rep.verdict == "FAIL"
    assert rep.rc == 1


def test_defect_pass_with_waivers_headline_over_fail(tmp_path):
    """A QUALIFIED pass is still a pass to a human reader — this is the exact
    token the measured escape used."""
    run = _mkrun(tmp_path,
                 deliverable="# R\n\n**Overall verdict:** `PASS_WITH_WAIVERS` "
                             "— `halted_at: None`, duration 142.1 s\n\nBody.\n",
                 orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR"
    assert rep.headline["token"] == "PASS_WITH_WAIVERS"


def test_defect_heading_form_pass_over_fail(tmp_path):
    """`# \\`PASS\\`` — the heading form, the shape this run's corrected
    deliverable uses for FAIL."""
    run = _mkrun(tmp_path, deliverable="# RESULT\n\n## Verdict\n\n# `PASS`\n\nx\n",
                 orch_verdict="FAIL")
    assert G.check(run).rc == 1


def test_defect_table_row_form_pass_over_fail(tmp_path):
    run = _mkrun(tmp_path,
                 deliverable="# R\n\n| Verdict | PASS |\n|---|---|\n\nx\n",
                 orch_verdict="FAIL")
    assert G.check(run).rc == 1


def test_defect_verdict_section_lead_emphasis_over_fail(tmp_path):
    """`## VERDICT` then `**PASS_WITH_WAIVERS.** prose…` — the form three
    corpus deliverables actually use."""
    run = _mkrun(tmp_path,
                 deliverable="# R\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** "
                             "Independently re-derived from raw artifacts:\n",
                 orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.rc == 1
    assert rep.headline["recogniser"] == "verdict_section"


def test_defect_fires_when_only_a_phase_report_carries_the_fail(tmp_path):
    """No aggregate report — the newest phase report is the counterpart. The
    escape must not be evadable by deleting the aggregate."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL",
                 orch_name="phase3_one_shot.json")
    rep = G.check(run)
    assert rep.rc == 1
    assert rep.orchestrator["source"] == "newest_phase"


def test_defect_failure_names_both_sides_with_locations(tmp_path):
    """The report must QUOTE both independently-produced values, with the
    deliverable's line number and the orchestrator's path — otherwise a reader
    cannot check the claim."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL",
                 extra={"halted_at": "phase3",
                        "verdict_note": "downgraded by the completion audit"})
    rep = G.check(run)
    blob = "\n".join(rep.blocking)
    assert "RESULT.md:3" in blob                    # deliverable + line
    assert "vibe_ic_one_shot.json" in blob          # orchestrator path
    assert "PASS" in blob and "FAIL" in blob        # both values
    assert "downgraded by the completion audit" in blob   # the runner's reason


# ===========================================================================
# FIXED DIRECTION — each of these MUST pass. A gate that fails these is not
# usable; it would block every honest run.
# ===========================================================================
def test_fixed_fail_headline_over_orchestrator_fail(tmp_path):
    """The corrected state of the measured escape."""
    run = _mkrun(tmp_path, deliverable=_FAIL_MD, orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.state == "CONSISTENT"
    assert rep.rc == 0


def test_fixed_pass_headline_over_orchestrator_pass(tmp_path):
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    assert G.check(run).state == "CONSISTENT"


def test_fixed_qualifier_mismatch_is_not_a_contradiction(tmp_path):
    """PASS_WITH_WAIVERS vs PASS is a QUALIFIER difference, not a polarity
    split. String equality here would fire on every honest run."""
    run = _mkrun(tmp_path,
                 deliverable="# R\n\n**Verdict:** PASS_WITH_WAIVERS\n",
                 orch_verdict="PASS")
    assert G.check(run).state == "CONSISTENT"


def test_fixed_deliverable_stricter_is_recorded_not_failed(tmp_path):
    """FAIL over PASS is UNDER-claiming — honest, and outside the escape
    direction. Failing it would punish an agent for downgrading on evidence the
    orchestrator cannot see."""
    run = _mkrun(tmp_path, deliverable=_FAIL_MD, orch_verdict="PASS")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_STRICTER"
    assert rep.rc == 0


# ===========================================================================
# NOT_APPLICABLE — must be rc 2 (a SKIP), never a PASS in the numerator.
# ===========================================================================
def test_na_no_headline_stated(tmp_path):
    run = _mkrun(tmp_path, deliverable="# R\n\nProse with no verdict line.\n",
                 orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.state == "NOT_APPLICABLE"
    assert rep.rc == 2


def test_na_no_orchestrator_report(tmp_path):
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict=None)
    assert G.check(run).rc == 2


def test_na_no_deliverable(tmp_path):
    run = _mkrun(tmp_path, deliverable=None, orch_verdict="FAIL")
    assert G.check(run).rc == 2


def test_na_never_returns_rc2_on_the_escape(tmp_path):
    """rc 2 is the SKIP lane. The escape must never land there — a gate whose
    PASS rides an rc==2 path is not a PASS."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    assert G.check(run).rc == 1


# ===========================================================================
# NARROWNESS — the recognisers must not invent a headline out of prose. Each of
# these is a real shape from the benchmark-data corpus.
# ===========================================================================
def test_narrow_quoted_sub_gate_verdict_is_not_a_headline(tmp_path):
    """A report DISCUSSING another gate's verdict inside a code span is not
    declaring its own. Corpus: benchmark-data/ic/caravel_user_project."""
    md = ('# R\n\nRound-10 note:\n'
          '  `verdict: "PASS_WITH_OPEN_ITEMS"`, `reason: "no conclusive '
          'defect; 3 named\n')
    run = _mkrun(tmp_path, deliverable=md, orch_verdict="FAIL")
    assert G.check(run).state == "NOT_APPLICABLE"


def test_narrow_scoped_subclaim_in_verdict_section_is_not_a_headline(tmp_path):
    """`## VERDICT` opening with `**DOC -> RTL: PASS (…).**` is a SCOPED
    sub-claim. Corpus: benchmark-data/ic/spm."""
    md = ("# R\n\n## VERDICT\n\n**DOC -> RTL: PASS (GENERATED, 100%).** RTL "
          "authored from the L1-L9 design documents only.\n")
    run = _mkrun(tmp_path, deliverable=md, orch_verdict="FAIL")
    assert G.check(run).state == "NOT_APPLICABLE"


def test_narrow_prose_after_a_verdict_label_is_not_a_token(tmp_path):
    run = _mkrun(tmp_path,
                 deliverable="# R\n\n**Verdict:** the run did not converge\n",
                 orch_verdict="FAIL")
    assert G.check(run).state == "NOT_APPLICABLE"


def test_narrow_non_verdict_words_are_not_tokens():
    for w in ("COMPLETE", "CONVERGED", "PRODUCTION-READY", "OK", "GREEN",
              "SIGNED OFF", "DONE"):
        assert G.normalise_token(w) is None, w


def test_narrow_token_vocabulary_is_pass_fail_only():
    assert G.normalise_token("PASS") == "PASS"
    assert G.normalise_token("`FAIL`") == "FAIL"
    assert G.normalise_token("**pass-with-waivers**") == "PASS_WITH_WAIVERS"
    assert G.polarity("PASS_WITH_OPEN_ITEMS") == "PASS"
    assert G.polarity("FAIL") == "FAIL"


# ===========================================================================
# INDEPENDENCE — the structural property that makes this not a rubber stamp.
# ===========================================================================
def test_independence_orchestrator_reader_never_touches_the_deliverable(tmp_path):
    """``read_orchestrator_verdict`` must produce its value with the
    deliverable ABSENT. If it needs the deliverable, the two values are not
    independent and the comparison is circular."""
    run = _mkrun(tmp_path, deliverable=None, orch_verdict="FAIL")
    assert G.read_orchestrator_verdict(run)["verdict"] == "FAIL"


def test_independence_headline_reader_never_touches_the_orchestrator(tmp_path):
    """``extract_headline_verdict`` takes TEXT only — it cannot reach a run dir
    at all, so it cannot be contaminated by the runner's value."""
    assert G.extract_headline_verdict(_PASS_MD)["token"] == "PASS"


def test_independence_the_two_values_can_disagree(tmp_path):
    """The whole point: the sides are free to differ. A checker that re-states
    one value cannot produce this."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.headline["token"] != rep.orchestrator["verdict"]


# ===========================================================================
# CLI — exit codes are the contract flow_compliance_check dispatches on.
# ===========================================================================
def _cli(run: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG_PATH), str(run)],
                          capture_output=True, text=True)


def test_cli_exit_1_on_contradiction(tmp_path):
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    r = _cli(run)
    assert r.returncode == 1
    assert r.stdout.startswith("FAIL: deliverable_verdict_consistency_check")


def test_cli_exit_0_when_consistent(tmp_path):
    run = _mkrun(tmp_path, deliverable=_FAIL_MD, orch_verdict="FAIL")
    assert _cli(run).returncode == 0


def test_cli_exit_2_when_not_applicable(tmp_path):
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict=None)
    assert _cli(run).returncode == 2


# ===========================================================================
# WIRING — a sound gate nobody invokes is not a gate.
# ===========================================================================
def test_wiring_registered_in_the_structural_gate_registry():
    src = (PROGRAMS / "flow_compliance_check.py").read_text()
    assert '"deliverable_verdict_consistency_check"' in src


def test_wiring_reached_by_the_deliverable_self_check():
    """``run_output_completeness_check`` is what the orchestrator ALREADY calls
    at finalize and what the agent's documented self-verify command runs. The
    contradiction state must be reachable from there, or the gate ships as an
    orphan the way its predecessor did."""
    src = (PROGRAMS / "run_output_completeness_check.py").read_text()
    assert "deliverable_verdict_consistency_check" in src
    assert "DELIVERABLE_CONTRADICTS_ORCHESTRATOR" in src


def test_wiring_self_check_reports_the_contradiction(tmp_path):
    """End-to-end through the ALREADY-INVOKED gate, not through this program.

    The deliverable must clear that gate's real-content floor first — a stub is
    a stub whatever its headline says, and the STUB classification correctly
    wins. This is the case the escape actually looked like: a LARGE, complete,
    convincing report whose headline is wrong.
    """
    import run_output_completeness_check as roc
    md = _PASS_MD + ("\nEvidence paragraph carrying real substance.\n" * 20)
    run = _mkrun(tmp_path, deliverable=md, orch_verdict="FAIL")
    (run / "reports").mkdir(exist_ok=True)
    (run / "reports" / "final_summary.md").write_text("compute done\n")
    (run / "out.gds").write_text("x" * 10)
    rep = roc.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR"
    assert rep.verdict == "FAIL"
    assert rep.rc == 1


def test_wiring_self_check_still_passes_a_consistent_run(tmp_path):
    """The new state must not swallow the COMPLETE case."""
    import run_output_completeness_check as roc
    run = _mkrun(tmp_path, deliverable=_FAIL_MD * 40, orch_verdict="FAIL")
    (run / "reports" / "final_summary.md").write_text("compute done\n")
    (run / "out.gds").write_text("x" * 10)
    rep = roc.check(run)
    assert rep.state == "COMPLETE"
    assert rep.rc == 0
