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


def test_waiver_downgrades_the_contradiction_to_pass(tmp_path):
    """An evidenced waiver — WAIVER_KEY in waivers.json, >=60 chars — downgrades
    the escape direction to PASS_WITH_WAIVER (rc 0), disclosed not hidden."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    (run / "waivers.json").write_text(json.dumps({
        G.WAIVER_KEY: "x" * G.WAIVER_MIN}))
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR_WAIVED"
    assert rep.verdict == "PASS"
    assert rep.rc == 0
    assert "WAIVED" in rep.reason


def test_waiver_too_short_does_not_downgrade(tmp_path):
    """The >=WAIVER_MIN floor is enforced, not decorative — a placeholder
    string one character short of it must not buy a pass."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    (run / "waivers.json").write_text(json.dumps({
        G.WAIVER_KEY: "x" * (G.WAIVER_MIN - 1)}))
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR"
    assert rep.rc == 1


def test_no_waivers_json_at_all_still_fails(tmp_path):
    """The base case (no waiver mechanism touched) must be untouched by this
    addition — negative control for the waiver feature itself."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR"
    assert rep.rc == 1


def test_waiver_does_not_touch_an_unrelated_contradiction_free_run(tmp_path):
    """A waiver present but nothing to waive: a CONSISTENT run stays
    CONSISTENT, not accidentally promoted or altered."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    (run / "waivers.json").write_text(json.dumps({
        G.WAIVER_KEY: "x" * G.WAIVER_MIN}))
    rep = G.check(run)
    assert rep.state == "CONSISTENT"


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
    """No aggregate report — a phase report is the counterpart. The escape must
    not be evadable by deleting the aggregate.

    The `source` label changed from `newest_phase` to `strictest_phase` in
    2026-08-04's fix: the selection no longer consults `st_mtime`, because this
    gate runs under an umbrella that rewrites the very files it would be
    timing. The BEHAVIOUR this test pins — rc 1, counterpart taken from a phase
    report rather than an aggregate — is unchanged."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL",
                 orch_name="phase3_one_shot.json")
    rep = G.check(run)
    assert rep.rc == 1
    assert rep.orchestrator["source"] == "strictest_phase"
    assert rep.orchestrator["report"].endswith("phase3_one_shot.json")


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


# ── #445: a SKIP that hides a success claim ────────────────────────────────
def _cell(tmp_path, result_text, orch_verdict):
    import json
    d = tmp_path / "run"
    (d / "reports" / "orchestrator").mkdir(parents=True)
    (d / "RESULT.md").write_text(result_text)
    (d / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"verdict": orch_verdict}))
    return d


def test_a_prose_success_claim_over_a_FAIL_is_disclosed_not_skipped(tmp_path):
    """MEASURED on a published cell (#445): RESULT.md asserts
    'OVERALL: PRODUCTION-READY' while the same cell's own final_summary.md says
    'FAIL=12 — blocking; do not claim PASS', and this gate returned SKIP.

    Correctly, by its own contract — it adjudicates STATED headlines and that
    is not one. But SILENTLY, and a silent skip on a success claim standing
    beside a failing orchestrator reads exactly like a clean result.
    """
    import deliverable_verdict_consistency_check as M
    d = _cell(tmp_path, "# R\n\n## OVERALL: PRODUCTION-READY (all gates pass)\n",
              "FAIL")
    rep = M.check(d)
    assert rep.state == "UNCHECKED_SUCCESS_CLAIM", rep.state
    assert rep.verdict == "DISCLOSED"
    assert "PRODUCTION-READY" in rep.reason


def test_the_disclosure_is_NON_FATAL_and_rc_unchanged():
    """It replaces a SKIP, so it must exit exactly as that SKIP did. A gate
    that started FAILing here would be adjudicating a claim it has just said
    it cannot adjudicate."""
    import deliverable_verdict_consistency_check as M
    assert M._EXIT["UNCHECKED_SUCCESS_CLAIM"] == M._EXIT["NOT_APPLICABLE"] == 2


def test_no_disclosure_when_the_orchestrator_PASSES(tmp_path):
    """The paired half. A confident sentence is only interesting next to a
    FAILING run; firing on every optimistic report would make this noise."""
    import deliverable_verdict_consistency_check as M
    d = _cell(tmp_path, "# R\n\n## OVERALL: PRODUCTION-READY\n", "PASS")
    rep = M.check(d)
    assert rep.verdict != "DISCLOSED", rep.reason


def test_no_disclosure_when_the_deliverable_makes_no_success_claim(tmp_path):
    """The other paired half: a report with no claim is a plain SKIP."""
    import deliverable_verdict_consistency_check as M
    d = _cell(tmp_path, "# R\n\nWork is ongoing; several steps remain.\n",
              "FAIL")
    rep = M.check(d)
    assert rep.state == "NOT_APPLICABLE", rep.state


def test_the_verdict_vocabulary_is_NOT_widened():
    """The property the whole design rests on: a prose adjective must never
    become a headline TOKEN, or any confident sentence turns into a verdict."""
    import deliverable_verdict_consistency_check as M
    for word in ("PRODUCTION-READY", "CONVERGED", "COMPLETE", "CLEAN"):
        assert M._TOKEN_RE.match(word) is None, word


# ═══════════════════════════════════════════════════════════════════════════
# #797 item 1 — A FRESHNESS JUDGEMENT THE JUDGE ITSELF PERTURBS.
#
# `read_orchestrator_verdict` used to take the per-phase report with the
# greatest `st_mtime`. Two independent reasons that is not a measurement of
# this run, either fatal on its own:
#
#   1. This gate is registered under `flow_compliance_check`, which is a
#      producer as well as a judge — one invocation rewrites 17 tracked files
#      and adds 25 (measured 2026-08-04; the measurement `--read-only` exists
#      for). The orchestrator reports are inside that set, so the umbrella
#      changes WHICH report this gate selects purely by having looked.
#   2. On a fresh checkout git stamps every file with the checkout time, so
#      `m > best[0]` is false for every candidate after the first and "newest"
#      degrades silently to glob-then-alphabetical order.
#
# The tests below drive the REAL entry point and assert the property directly:
# permuting only the mtimes of a fixed tree must not move the verdict.
# ═══════════════════════════════════════════════════════════════════════════
import os as _os


def _phase_only_run(tmp_path: Path, verdicts: dict, mtimes: dict) -> Path:
    """A run with NO aggregate report and several per-phase ones, so the
    tie-break is what decides. `verdicts` and `mtimes` are keyed by filename."""
    run = tmp_path / "run"
    orch = run / "reports" / "orchestrator"
    orch.mkdir(parents=True, exist_ok=True)
    run.joinpath("RESULT.md").write_text(_PASS_MD)
    for name, v in verdicts.items():
        (orch / name).write_text(json.dumps({"verdict": v}))
    for name, t in mtimes.items():
        _os.utime(orch / name, (t, t))
    return run


def test_permuting_only_the_mtimes_cannot_move_the_verdict(tmp_path):
    """THE property. Identical bytes, opposite mtime orderings: one verdict.

    Before the fix this returned rc 1 with one ordering and rc 0 with the
    other — the umbrella that drives this gate rewrites these very files, so
    the run's verdict was decided by the order the auditor happened to touch
    them."""
    verdicts = {"phase2_one_shot.json": "PASS",
                "phase3_one_shot.json": "FAIL"}
    seen = []
    for i, mt in enumerate(({"phase2_one_shot.json": 1000,
                             "phase3_one_shot.json": 2000},
                            {"phase2_one_shot.json": 2000,
                             "phase3_one_shot.json": 1000})):
        rep = G.check(_phase_only_run(tmp_path / f"p{i}", verdicts, mt))
        seen.append((rep.rc, rep.state, Path(rep.orchestrator["report"]).name))
    assert seen[0] == seen[1], (
        f"the same tree gave two answers under two mtime orderings: {seen}")


def test_all_equal_mtimes_still_reaches_the_failing_report(tmp_path):
    """The fresh-checkout case, which the mtime rule could not express at all:
    git gives every file the same stamp, so `newest` collapsed to glob order
    and whichever directory a report happened to sit in decided the run."""
    rep = G.check(_phase_only_run(
        tmp_path, {"phase2_one_shot.json": "PASS",
                   "phase3_one_shot.json": "FAIL"},
        {"phase2_one_shot.json": 1000, "phase3_one_shot.json": 1000}))
    assert rep.rc == 1, "a recorded phase FAIL must not be outvoted by a tie"
    assert Path(rep.orchestrator["report"]).name == "phase3_one_shot.json"


def test_a_disagreeing_set_is_disclosed_not_silently_resolved(tmp_path):
    """A choice was made among reports that disagree; the evidence has to name
    what it did NOT compare against, or a reader cannot tell a choice happened."""
    rep = G.check(_phase_only_run(
        tmp_path, {"phase2_one_shot.json": "PASS",
                   "phase3_one_shot.json": "FAIL"},
        {"phase2_one_shot.json": 1000, "phase3_one_shot.json": 2000}))
    assert rep.orchestrator["source"] == "strictest_phase_of_disagreeing"
    got = {(Path(c["report"]).name, c["verdict"])
           for c in rep.orchestrator["candidates"]}
    assert got == {("phase2_one_shot.json", "PASS"),
                   ("phase3_one_shot.json", "FAIL")}, got


def test_agreeing_reports_are_not_reported_as_a_disagreement(tmp_path):
    """Negative control: when every candidate agrees there was no choice to
    disclose, and the gate must not manufacture one."""
    rep = G.check(_phase_only_run(
        tmp_path, {"phase2_one_shot.json": "PASS",
                   "phase3_one_shot.json": "PASS_WITH_WAIVERS"},
        {"phase2_one_shot.json": 1000, "phase3_one_shot.json": 2000}))
    assert rep.rc == 0
    assert rep.orchestrator["source"] == "strictest_phase"
    assert "candidates" not in rep.orchestrator


def test_the_aggregate_still_wins_when_it_exists(tmp_path):
    """Unchanged contract: an aggregate report is the deliverable's counterpart
    and is taken WHOLE, disagreeing phase reports or not. The fix narrows only
    the no-aggregate fallback."""
    run = _phase_only_run(tmp_path, {"phase3_one_shot.json": "FAIL"},
                          {"phase3_one_shot.json": 2000})
    (run / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"verdict": "PASS"}))
    rep = G.check(run)
    assert rep.orchestrator["source"] == "aggregate"
    assert rep.rc == 0


def test_one_physical_report_reached_by_two_globs_is_not_a_disagreement(
        tmp_path):
    """`reports/orchestrator/*_one_shot.json` and `reports/*_one_shot.json` can
    name ONE file through two paths. Counting it twice would invent a
    disagreement out of a single report."""
    run = tmp_path / "run"
    orch = run / "reports" / "orchestrator"
    orch.mkdir(parents=True)
    run.joinpath("RESULT.md").write_text(_PASS_MD)
    (orch / "phase3_one_shot.json").write_text(json.dumps({"verdict": "PASS"}))
    link = run / "reports" / "phase3_one_shot.json"
    try:
        link.symlink_to(orch / "phase3_one_shot.json")
    except OSError:
        pytest.skip("symlinks unavailable on this filesystem")
    rep = G.check(run)
    assert rep.orchestrator["source"] == "strictest_phase"
    assert "candidates" not in rep.orchestrator


# ===========================================================================
# vibe-ic#883 — THE COMPLETION AUDIT IS A VERDICT SOURCE TOO.
#
# The module's docstring cited `phase23_completion_audit.json` from the day it
# was written and never read it. Because an AGGREGATE report short-circuits the
# candidate search, a FAIL audit sat invisibly behind a PASS aggregate — and the
# check returned exit 0 on the exact deliverable-over-FAIL shape it exists to
# catch. Measured on the shipped tree
# benchmark-data/ic/caravel_user_project/v1.9.43_sky130A; the false certificate
# stood 6 days and was retired by a human, not by this gate.
#
# These tests are the defect-direction mutation for that escape: revert the fix
# and the first two FAIL.
# ===========================================================================
def _add_audit(run: Path, verdict: str,
               name: str = "phase23_completion_audit.json") -> Path:
    d = run / "reports" / "audit"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"phase": "all", "verdict": verdict}, indent=2))
    return p


def test_defect_pass_aggregate_hides_fail_completion_audit(tmp_path):
    """THE #883 escape, reproduced exactly: deliverable PASS, aggregate
    orchestrator PASS, completion audit FAIL. The aggregate must NOT be allowed
    to short-circuit past the audit."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS_WITH_WAIVERS")
    _add_audit(run, "FAIL")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR", rep.state
    assert rep.rc == 1
    # The audit must be NAMED as the source, so a reader can see which record
    # decided it rather than having to infer it.
    assert "completion_audit" in str(rep.orchestrator.get("source"))
    assert rep.orchestrator["verdict"] == "FAIL"
    # And the displaced value is retained: a choice was made, not hidden.
    assert rep.orchestrator["displaced"]["verdict"] == "PASS_WITH_WAIVERS"


def test_defect_fail_audit_beats_pass_when_no_aggregate_exists(tmp_path):
    """Same escape through the per-phase lane rather than the aggregate lane."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS",
                 orch_name="phase3_one_shot.json")
    _add_audit(run, "FAIL")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR", rep.state
    assert rep.rc == 1


def test_lenient_audit_never_overrides_a_strict_orchestrator(tmp_path):
    """The asymmetry is preserved. A PASS audit must NOT rescue a deliverable
    from a FAIL orchestrator — that would open the escape from the other side."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="FAIL")
    _add_audit(run, "PASS")
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR", rep.state
    assert rep.rc == 1


def test_underclaiming_over_a_fail_audit_is_still_not_a_failure(tmp_path):
    """Honest direction: deliverable FAIL over an audit FAIL is consistent, and
    a deliverable stricter than the record is never punished."""
    run = _mkrun(tmp_path, deliverable=_FAIL_MD, orch_verdict="PASS")
    _add_audit(run, "FAIL")
    rep = G.check(run)
    assert rep.rc == 0, rep.state


def test_audit_absent_changes_nothing(tmp_path):
    """No audit in the tree -> byte-identical behaviour to before #883."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    rep = G.check(run)
    assert rep.rc == 0, rep.state
    assert rep.orchestrator["source"] == "aggregate"


def test_agreeing_audit_is_recorded_even_when_it_changes_nothing(tmp_path):
    """A consulted-and-agreed audit must still be visible in the evidence, or
    'the audit was read' and 'there was no audit' look identical."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    _add_audit(run, "PASS")
    rep = G.check(run)
    assert rep.rc == 0, rep.state
    assert rep.orchestrator["audit_verdict"] == "PASS"


# ===========================================================================
# vibe-ic#897 — AN UNREADABLE SECOND OPINION MUST NOT READ AS AGREEMENT.
#
# `_load_verdict_json` collapses missing / wrong-key / empty / zero-byte /
# malformed into ONE `None`, so "there is no audit" and "the audit is corrupt"
# arrived identically — and the gate printed "agrees in polarity" having read
# one record while the run shipped two. Four of the five measured silencing
# edits now DISCLOSE. The fifth (delete the file) still passes, and that is
# stated rather than papered over: an absent file is genuinely
# indistinguishable from a run that never produced one.
# ===========================================================================
def _audit(run: Path, body: str | None, name="phase23_completion_audit.json"):
    d = run / "reports" / "audit"
    d.mkdir(parents=True, exist_ok=True)
    if body is not None:
        (d / name).write_text(body)


@pytest.mark.parametrize("body,label", [
    (json.dumps({"result": "FAIL"}), "wrong key"),
    ("{}", "empty object"),
    ("", "zero bytes"),
    ("{not json", "malformed"),
])
def test_an_unreadable_audit_is_disclosed_not_called_agreement(
        tmp_path, body, label):
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    _audit(run, body)
    rep = G.check(run)
    assert rep.verdict == "DISCLOSED", f"{label}: {rep.verdict} / {rep.state}"
    assert rep.orchestrator.get("audit_unreadable"), label
    assert "did not parse" in rep.reason.lower(), label
    # Still not a FAIL: an unreadable record is not evidence of contradiction,
    # and failing here would adjudicate a question the gate just said it
    # cannot put.
    assert rep.rc == 0, label


def test_a_readable_agreeing_audit_is_still_a_clean_pass(tmp_path):
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    _audit(run, json.dumps({"verdict": "PASS"}))
    rep = G.check(run)
    assert rep.verdict == "PASS" and rep.state == "CONSISTENT", rep.state
    assert not rep.orchestrator.get("audit_unreadable")


def test_a_readable_fail_audit_still_beats_a_pass_aggregate(tmp_path):
    """The #883 behaviour must survive the #897 change."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    _audit(run, json.dumps({"verdict": "FAIL"}))
    rep = G.check(run)
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR", rep.state
    assert rep.rc == 1


def test_no_audit_file_at_all_is_not_reported_as_unreadable(tmp_path):
    """The honest limit of this fix, pinned so it cannot drift silently: an
    ABSENT audit is indistinguishable from a run that never produced one, so
    it stays a clean PASS and is NOT claimed as a lost second opinion."""
    run = _mkrun(tmp_path, deliverable=_PASS_MD, orch_verdict="PASS")
    rep = G.check(run)
    assert rep.verdict == "PASS", rep.verdict
    assert not rep.orchestrator.get("audit_unreadable")
