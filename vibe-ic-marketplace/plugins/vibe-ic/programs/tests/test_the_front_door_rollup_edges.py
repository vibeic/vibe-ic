"""The front door's roll-up, at its edges — through main() and through the guard.

R-0915-145. The conjunction rule itself stands (a FAILING completion audit over
passing phases is a FAIL). These are the four edges a pre-landing review confirmed,
each driven through the entry point rather than through a re-implementation.

H1  #505's DEMOTED ROW. The standalone shape (`--skip-phase3`, a phase1 failure
    that is purely doc-extraction coverage) demotes phase1 to COVERAGE-INCOMPLETE
    and KEEPS its rc, because a coverage-only phase1 always exits 1 -- the rc
    belongs to the verdict the row had BEFORE the demotion. The roll-up's "claims
    a pass but exited non-zero" rule is right for an UNDEMOTED row and turned this
    shape into FAIL/exit 1, where the base published PASS_WITH_WAIVERS/exit 0.
    The demotion now records itself, and only the #505 branch may mint the token.

M2  THE AUDIT AXIS MUST NOT FAIL OPEN. `if ca == "FAIL"` meant NOT_MEASURED, an
    unparseable value and an ABSENT audit all read as satisfied -- so a phase3 run
    whose --strict completion refresh raised inside a swallowed try published PASS
    at exit 0. Only PASS satisfies the axis now; waivers cap at the waiver tier;
    anything else, absence included, is NOT_MEASURED with the reason stated.

M3  AND IT MUST BE THIS RUN'S AUDIT. The reader took
    `reports/orchestrator/phase3_one_shot.json` unconditionally, so a leftover FAIL
    from an earlier full run gated a later `--skip-phase3` invocation that never
    touched phase3. A document counts only when phase3 ran in THIS invocation and
    the document was written at or after it started; an older one is named as
    ignored, not used.

L4  ONE IMPLEMENTATION. `vibe_ic_entry_guard` re-derived the verdict with its own
    copy of the old rule and its verdict set had no NOT_MEASURED, so a GENUINE
    report was discarded as forged and `benchmark_dispatch --score` could refuse a
    real run. The guard now replays the runner's own roll-up.
"""
from __future__ import annotations

import json
import time
import os
import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import _path_layout as _pl                                   # noqa: E402
import vibe_ic_entry_guard as GUARD                          # noqa: E402
import vibe_ic_one_shot_runner as V
import _audit_scope                          # noqa: E402
from _route_fixture import stage_owner_route  # noqa: E402
from programs.tests.test_execution_receipt_chain import real_entry, isolated_transport


@pytest.fixture()
def project(tmp_path_factory):
    p = Path(tempfile.mkdtemp(prefix="fdedge_",
                              dir=str(tmp_path_factory.mktemp("fd"))))
    rtl = p / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text("module d(); endmodule\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")
    return p


#: WHERE EACH PRODUCER REALLY WRITES -- and now that is ONE RULE, which is the point.
#:
#: Round 3 measured three locations and taught the fixtures all three:
#:     reports/phase1_one_shot.json                 <- phase1's runner, NOT routed
#:     reports/orchestrator/phase2_one_shot.json
#:     reports/orchestrator/phase3_one_shot.json
#: and I made the READER learn them too. That was the wrong half to change. `_path_layout`
#: categorises all three `*_one_shot.json` files as `orchestrator`, and the repo says the
#: flat location is not sanctioned, twice, without being asked:
#:   * `reports_subfolder_taxonomy_check` FAILS on it -- measured against a staged layout:
#:     `[FAIL] ... 1 stray file(s): phase1_one_shot.json`;
#:   * `vibe_ic_entry_guard` documents `reports/orchestrator/phase1_one_shot.json` as the
#:     standalone runner's location and calls the flat one "legacy".
#: So the PRODUCER moved onto the router, and both sides now resolve through one call.
#: These fixtures therefore write through the router too -- not because it is convenient,
#: but because a real `phase1_one_shot_runner` invocation was measured landing there, which
#: `test_phase1s_producer_resolves_its_report_through_the_router` pins against the source.
#:
#: The coverage-only sidecar is NOT in that set and is not routed at all: it is declared
#: literally, as `_path_layout.COVERAGE_ONLY_SIDECAR_REL`, and staged through
#: `coverage_only_sidecar_path` like everything else that touches it.
#:
#: CORRECTING WHAT THIS NOTE USED TO SAY. It claimed three locations -- "its producer writes
#: `reports/`, `_phase1_failure_is_coverage_only` reads `reports/phase1/`, and the router's
#: catch-all would say `reports/audit/`". Measured: the producer writes `reports/phase1/`, the
#: same place the reader reads, so there were never three LOCATIONS -- there were FIVE
#: hand-written COPIES of one location, across three programs, which is a different defect and
#: the one next/icslot-sidecarpath closed. The router's catch-all really would say
#: `reports/audit/`, and that remains a live mismatch: moving the file there is a producer move
#: needing a read-side tolerance for the old place, and it is not done.


def _report(project: Path, name: str, payload: dict) -> Path:
    path = _pl.report_path(project, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")
    return path


def _drive_main(project: Path, monkeypatch, *, phase1, phase2, phase3=None,
                extra_argv=()) -> tuple:
    """Run the REAL main() with the phase subprocesses stubbed.

    Only `_run_phase` and the phase-1 entry decision are staged; every line of the
    roll-up, the axis reader and the report writer is the shipped one.
    """
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": phase1[0]})
            if phase1[2] is not None:
                # THE SIDECAR'S OWN PATH AND KEY. The path is now ONE declaration
                # (`_path_layout.coverage_only_sidecar_path`) that the producer, both
                # readers and this fixture all ask, so a fixture can no longer drift
                # from the code by staging the old place; the LITERAL is pinned once,
                # in `test_a_pass_one_written_before_the_move_is_still_carried`, which
                # is what still catches a silent relocation. The KEY is read from the
                # consumer: `_phase1_failure_is_coverage_only` asks for
                # `coverage_only_failure`, and any other key stages a fixture the
                # demotion branch cannot see.
                side = _pl.coverage_only_sidecar_path(project)
                side.parent.mkdir(parents=True, exist_ok=True)
                side.write_text(json.dumps(phase1[2]) + "\n")
            return phase1[1]
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": phase2[0]})
            return phase2[1]
        if "phase3" in runner.name and phase3 is not None:
            _report(project, "phase3_one_shot.json", phase3[0])
            return phase3[1]
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", *extra_argv])
    real_entry('IC', 'default', project)
    rc = V.main()
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    return rc, json.loads(out.read_text())


# ── H1: the #505 standalone shape ──────────────────────────────────────────

def test_the_505_standalone_shape_is_pass_with_waivers_at_exit_zero(
        project, monkeypatch):
    """THE REGRESSION, through main(): coverage-only phase1 FAIL at rc 1, demoted,
    plus a passing phase2. On 99ae0fa6b this published FAIL and exited 1."""
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=("FAIL", 1, {"coverage_only_failure": True,
                            "coverage_pct": 71.0, "total_todo": 0}),
        phase2=("PASS", 0),
        extra_argv=("--skip-phase3",))
    assert doc["verdict"] == "PASS_WITH_WAIVERS", (
        doc["verdict"], doc.get("verdict_reasons"))
    assert rc == 0, rc
    phases = {r["name"]: r for r in doc["phases"]}
    assert phases["phase1"]["verdict"] == "COVERAGE-INCOMPLETE"
    assert phases["phase1"]["rc"] == 1, (
        "the row must KEEP the rc its process really returned; the demotion is "
        "recorded beside it, not by rewriting history")
    dem = doc["demoted_phases"]["phase1"]
    assert dem["token"] == V.DEMOTION_COVERAGE_ONLY
    assert dem["original_rc"] == 1 and dem["original_verdict"] == "FAIL"
    assert any("pre-demotion" in r for r in doc["verdict_reasons"]), (
        doc["verdict_reasons"])


def test_an_undemoted_row_claiming_a_pass_at_nonzero_rc_still_fails(
        project, monkeypatch):
    """The rule the demotion exemption must not launder: phase2 reports PASS and
    exits 1, with no demotion record. That is a report disagreeing with its own
    process and it still fails."""
    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("PASS", 0, None), phase2=("PASS", 1),
                          extra_argv=("--skip-phase3",))
    assert doc["verdict"] == "FAIL", (doc["verdict"], doc["verdict_reasons"])
    assert rc == 1
    assert doc["demoted_phases"] == {}
    assert any("rc=1" in r for r in doc["verdict_reasons"])


def test_only_the_505_token_exempts_an_rc():
    """The exemption is keyed on ONE token minted at ONE site. A row carrying any
    other demotion record is not exempt — demotion is not a laundering path."""
    rows = [("phase1", "COVERAGE-INCOMPLETE", 1)]
    assert V._roll_up(rows, ["PASS"],
                      demoted={"phase1": {"token": V.DEMOTION_COVERAGE_ONLY}},
                      audit_axis={"state": "PASS"})[0] == "PASS_WITH_WAIVERS"
    for bogus in ({"token": "something_else"}, {}, {"token": ""}):
        assert V._roll_up(rows, ["PASS"], demoted={"phase1": bogus},
                          audit_axis={"state": "PASS"})[0] == "FAIL", bogus


# ── M2: the audit axis never passes on a token nobody taught it ────────────

def test_the_audit_axis_is_fail_closed_for_every_token():
    assert V._audit_axis_from_verdicts(["PASS"])["state"] == "PASS"
    assert V._audit_axis_from_verdicts(["FAIL"])["state"] == "FAIL"
    assert V._audit_axis_from_verdicts(["FAIL", "PASS"])["state"] == "FAIL"
    assert V._audit_axis_from_verdicts(
        ["PASS_WITH_WAIVERS"])["state"] == "PASS_WITH_WAIVERS"
    for token in ("NOT_MEASURED", "INSUFFICIENT_DATA", "", "greenish", None):
        axis = V._audit_axis_from_verdicts([token] if token is not None else [])
        assert axis["state"] == "NOT_MEASURED", (token, axis)
        assert axis["reason"], token
    assert V._audit_axis_from_verdicts(None)["state"] == "NOT_MEASURED"


def test_a_phase3_run_with_no_readable_audit_is_not_measured(project,
                                                             monkeypatch):
    """THE SWALLOWED-REFRESH CASE, through main(): phase3 ran and reported PASS,
    and no completion audit exists. On 99ae0fa6b that published PASS at exit 0."""
    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("PASS", 0, None), phase2=("PASS", 0),
                          phase3=({"verdict": "PASS"}, 0))
    assert doc["completion_audit_axis"]["state"] == "NOT_MEASURED", (
        doc["completion_audit_axis"])
    assert doc["verdict"] == "NOT_MEASURED", (
        doc["verdict"], doc["verdict_reasons"])
    assert rc == 1
    assert any("completion audit" in r for r in doc["verdict_reasons"])


def test_a_failing_audit_still_fails_a_fully_passing_run(project, monkeypatch):
    """The refutation that stands: the conjunction includes the audit."""
    def _phase3(payload, code):
        return payload, code
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    # the audit document is written by phase3's stub so it belongs to this run
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase3" in runner.name:
            _report(project, "phase3_one_shot.json", {"verdict": "PASS"})
            _report(project, "phase23_completion_audit.json", {"verdict": "FAIL"})
            return 0
        return 0
    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    assert doc["completion_audit_axis"]["state"] == "FAIL"
    assert doc["verdict"] == "FAIL" and rc == 1
    assert any("completion audit" in r for r in doc["verdict_reasons"])


# ── M3: the axis belongs to THIS invocation ────────────────────────────────

def test_a_leftover_audit_from_an_earlier_run_does_not_gate_this_one(
        project, monkeypatch):
    """A `--skip-phase3` invocation over a tree that still carries an earlier full
    run's FAILING audit. On 99ae0fa6b that published FAIL; the base read PASS. This
    run has no audit axis at all, and says so."""
    old = _report(project, "phase23_completion_audit.json", {"verdict": "FAIL"})
    _report(project, "phase3_one_shot.json",
            {"verdict": "FAIL", "completion_audit_verdict": "FAIL"})
    import os
    stale = os.stat(old).st_mtime_ns - 10 ** 10
    for rel in ("phase23_completion_audit.json", "phase3_one_shot.json"):
        os.utime(_pl.report_path(project, rel), ns=(stale, stale))

    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("PASS", 0, None), phase2=("PASS", 0),
                          extra_argv=("--skip-phase3",))
    assert doc["completion_audit_axis"]["state"] == "NOT_APPLICABLE", (
        doc["completion_audit_axis"])
    assert doc["verdict"] == "PASS", (doc["verdict"], doc["verdict_reasons"])
    assert rc == 0
    assert any("no phase2/3 completion audit axis" in r
               for r in doc["verdict_reasons"]), doc["verdict_reasons"]


def test_a_document_older_than_this_invocation_is_named_as_ignored(project):
    """The axis reader, directly: phase3 ran, but the only audit on disk predates
    this invocation. It is IGNORED and the axis is NOT_MEASURED — never PASS, and
    never that document's verdict either."""
    import os
    _report(project, "phase23_completion_audit.json", {"verdict": "PASS"})
    path = _pl.report_path(project, "phase23_completion_audit.json")
    stale = os.stat(path).st_mtime_ns - 10 ** 10
    os.utime(path, ns=(stale, stale))
    axis = V._completion_audit_axis(project, phase3_ran=True,
                                    started_at=os.stat(path).st_mtime + 5)
    assert axis["state"] == "NOT_MEASURED", axis
    assert axis["ignored"] == [
        "reports/audit/phase23_completion_audit.json"], axis
    assert "earlier run" in axis["reason"], axis
    assert axis["sources"] == []


def test_no_phase3_means_no_axis_not_a_satisfied_one(project):
    _report(project, "phase23_completion_audit.json", {"verdict": "PASS"})
    axis = V._completion_audit_axis(project, phase3_ran=False, started_at=0.0)
    assert axis["state"] == "NOT_APPLICABLE", axis
    assert "did not run in this invocation" in axis["reason"]


# ── L4: the guard replays the runner's roll-up ─────────────────────────────

def _orchestrator_report(verdict: str, phases: list, **extra) -> dict:
    doc = {"phase": "vibe-ic", "verdict": verdict, "phases": phases}
    doc.update(extra)
    return doc


def test_the_guard_accepts_a_genuine_new_rule_report():
    """A report that is FAIL because its own completion audit failed, with every
    phase passing. The guard's old copy of the rule derived PASS and discarded it
    as forged."""
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    data = _orchestrator_report(
        "FAIL", phases, completion_audit_axis={"state": "FAIL", "reason": "x"},
        completion_audit_verdicts=["FAIL"], demoted_phases={})
    assert GUARD._expected_front_door_verdict(data, phases) == "FAIL"


def test_the_guard_rejects_a_forged_pass_over_a_failing_audit():
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    data = _orchestrator_report(
        "PASS", phases, completion_audit_axis={"state": "FAIL", "reason": "x"},
        completion_audit_verdicts=["FAIL"], demoted_phases={})
    assert GUARD._expected_front_door_verdict(data, phases) != "PASS"


def test_not_measured_is_a_front_door_verdict_the_guard_knows():
    assert "NOT_MEASURED" in GUARD._ORCHESTRATOR_VERDICTS, (
        "a genuine NOT_MEASURED report is discarded before any derivation runs")


def test_the_guard_holds_a_legacy_report_to_the_rule_it_was_published_under():
    """A report from before these fields existed carries no axis. It is judged by
    the old derivation — exactly as trusted as it was, and no more — because a
    guard cannot fairly hold a document to a rule it could not have followed."""
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    legacy = _orchestrator_report("PASS", phases)
    assert "completion_audit_axis" not in legacy
    assert GUARD._expected_front_door_verdict(legacy, phases) == "PASS"


def test_the_guard_does_not_keep_its_own_copy_of_the_rule():
    """SOURCE PIN, on the thing that drifted: the guard must delegate to the
    runner's roll-up for a report carrying its inputs."""
    src = (PROGRAMS / "vibe_ic_entry_guard.py").read_text()
    assert "_roll_up(" in src, (
        "the guard no longer calls the runner's roll-up; a second copy of the "
        "conjunction rule is what discarded genuine reports as forged")
    assert "import vibe_ic_one_shot_runner" in src


def test_main_always_supplies_the_axis():
    """THE PIN THAT KEEPS THE STRICT PATH FROM BEING BYPASSED.

    `_roll_up` applies the fail-closed audit rule only when an axis is SUPPLIED,
    because a caller passing none is not talking about the completion audit (#505's
    properties are stated that way). That scoping is only safe while the real
    front door always supplies one — so this asserts main's call site does, by AST,
    on the keyword rather than on surrounding text.
    """
    import ast
    tree = ast.parse((PROGRAMS / "vibe_ic_one_shot_runner.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_roll_up"]
    assert calls, "main no longer rolls up through `_roll_up`"
    kwargs = [{k.arg for k in c.keywords} for c in calls]
    assert any("audit_axis" in kw and "demoted" in kw for kw in kwargs), (
        f"main's roll-up call does not supply `audit_axis`/`demoted`, so the "
        f"fail-closed audit rule and the #505 demotion exemption are both "
        f"unreachable on a real run; keywords seen: {kwargs}")
    # and the axis it supplies is the one tied to this invocation
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "_completion_audit_axis(" in src and "phase3_ran=_phase3_ran" in src
    # PHASE 3's start, not the run's: a document written before phase3 began
    # cannot be phase3's refresh of it.
    assert 'started_at=_phase_started.get("phase3", t0)' in src


# ── R-0915-151: freshness on the CARRIED verdict, and on the rows ───────────

def _audit(project: Path, verdict: str, *, scope: dict = None,
           phase: str = "all") -> Path:
    doc = {"verdict": verdict, "phase": phase}
    if scope is not None:
        doc["scope"] = scope
    return _report(project, "phase23_completion_audit.json", doc)


WHOLE = {"whole_flow": True, "step_count": 70, "flow_step_total": 70}


def test_a_stale_audit_pass_repeated_by_a_fresh_carrier_is_not_measured(
        project, monkeypatch):
    """THE HIGH, through main(). phase3's finalize refresh swallows a TimeoutExpired,
    and `_derive_headline_verdict` then copies the OLD audit's verdict into a FRESH
    phase3_one_shot.json. My round-2 reader put the audit FILE in `ignored` and then
    accepted the SAME verdict from that carrier — axis PASS, exit 0.

    Here the audit says PASS and predates phase3; the carrier repeats it and is
    today's. The axis must be NOT_MEASURED, and the carrier must appear as a POINTER
    that was not used as evidence.
    """
    import os
    stale = _audit(project, "PASS", scope=dict(WHOLE))
    old = os.stat(stale).st_mtime_ns - 10 ** 10
    os.utime(stale, ns=(old, old))

    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase3" in runner.name:
            # the swallowed refresh: a FRESH report carrying the OLD audit's verdict
            _report(project, "phase3_one_shot.json",
                    {"verdict": "PASS", "completion_audit_verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    axis = doc["completion_audit_axis"]
    assert axis["state"] == "NOT_MEASURED", axis
    assert axis["sources"] == [], axis
    assert "reports/audit/phase23_completion_audit.json" in axis["ignored"], axis
    assert any(p["carries"] == "PASS" and p["used_as_evidence"] is False
               for p in axis["pointers"]), axis
    assert doc["verdict"] == "NOT_MEASURED" and rc == 1


def test_a_stale_audit_fail_does_not_gate_a_good_run(project, monkeypatch):
    """THE MIRROR, which matters just as much: a stale FAIL must not gate a run it
    never measured. It is still NOT_MEASURED — never FAIL, and never PASS."""
    import os
    stale = _audit(project, "FAIL", scope=dict(WHOLE))
    old = os.stat(stale).st_mtime_ns - 10 ** 10
    os.utime(stale, ns=(old, old))

    def fake_run_phase(label, runner, args, env=None):
        for name in ("phase1", "phase2", "phase3"):
            if name in runner.name:
                _report(project, f"{name}_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    assert doc["completion_audit_axis"]["state"] == "NOT_MEASURED"
    assert doc["verdict"] == "NOT_MEASURED", doc["verdict"]


def test_a_scoped_audit_is_not_this_runs_axis(project):
    """THE MEDIUM: who wrote the audit, over what population. R-0915-147 gives the
    document a scope, so a phase-2-scoped audit or a pre-Step-29 snapshot is no
    longer accepted as the phase2/3 axis."""
    _audit(project, "PASS", scope={"whole_flow": False, "step_count": 13,
                                   "flow_step_total": 70, "stage_id": "stage2"})
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] == "NOT_MEASURED", axis
    assert "13 of 70" in axis["reason"], axis["reason"]


def test_a_whole_flow_fresh_audit_is_the_axis(project):
    """THE OTHER DIRECTION: the document that IS this run's whole-flow audit is
    accepted, and says which signal established that."""
    _audit(project, "PASS", scope=dict(WHOLE))
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] == "PASS", axis
    assert axis["scope_signal"] == "scope.whole_flow"
    assert axis["sources"][0]["verdict"] == "PASS"


def test_an_audit_without_a_scope_block_is_taken_on_the_weaker_signal(project):
    """A document predating R-0915-147 cannot state its population. It is accepted
    only on `phase == "all"` AND the weaker signal is DISCLOSED, because a weak
    signal read silently is the same mistake in a quieter voice."""
    _audit(project, "PASS", phase="all")
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] == "PASS", axis
    assert "weaker signal" in axis["scope_signal"], axis["scope_signal"]
    _audit(project, "PASS", phase="2")
    axis2 = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis2["state"] == "NOT_MEASURED", axis2


def test_a_phase_that_left_no_report_is_not_measured(project, monkeypatch):
    """THE ROW SIDE of the same rule. phase3's `[SKIP] no usable PDK` returns 0
    WITHOUT writing a report, and the front door then read a stale
    phase3_one_shot.json or invented PASS from rc 0 — for a phase that measured
    nothing."""
    def fake_run_phase(label, runner, args, env=None):
        if "phase3" in runner.name:
            return 0                      # rc 0 and NO report, the shipped shape
        for name in ("phase1", "phase2"):
            if name in runner.name:
                _report(project, f"{name}_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows["phase3"] == "NOT_MEASURED", (rows, doc["verdict"])
    assert doc["verdict"] == "NOT_MEASURED" and rc == 1
    assert any("left no phase3_one_shot.json" in a for a in doc["advisories"]), (
        doc["advisories"])


def test_a_stale_phase_report_is_not_this_runs_row(project, monkeypatch):
    """And a report from an EARLIER run does not become this phase's verdict."""
    import os
    stale = _report(project, "phase3_one_shot.json", {"verdict": "PASS"})
    old = os.stat(stale).st_mtime_ns - 10 ** 10
    os.utime(stale, ns=(old, old))

    def fake_run_phase(label, runner, args, env=None):
        if "phase3" in runner.name:
            return 0                      # leaves the stale report in place
        for name in ("phase1", "phase2"):
            if name in runner.name:
                _report(project, f"{name}_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows["phase3"] == "NOT_MEASURED", rows
    assert any("predates phase3's start" in a for a in doc["advisories"]), (
        doc["advisories"])


def test_a_stale_coverage_sidecar_does_not_demote(project, monkeypatch):
    """M/L: my H1 exemption rests on `_phase1_failure_is_coverage_only`, whose
    sidecar is not tied to this invocation and is written BEFORE three later
    non-coverage blocking returns. A stale sidecar must not demote a phase1 FAIL."""
    import os
    side = _pl.coverage_only_sidecar_path(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True,
                                "coverage_pct": 71.0, "total_todo": 0}) + "\n")
    old = os.stat(side).st_mtime_ns - 10 ** 10
    os.utime(side, ns=(old, old))

    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("FAIL", 1, None), phase2=("PASS", 0),
                          extra_argv=("--skip-phase3",))
    assert doc["demoted_phases"] == {}, doc["demoted_phases"]
    assert doc["verdict"] == "FAIL" and rc == 1
    assert any("predates phase1's start" in a for a in doc["advisories"]), (
        doc["advisories"])


def test_only_rc_1_is_exempt_from_the_demotion(project, monkeypatch):
    """The coverage-only path returns rc 1. Any other rc is a different failure, and
    a fresh sidecar does not make it one."""
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=("FAIL", 2, {"coverage_only_failure": True, "coverage_pct": 71.0,
                            "total_todo": 0}),
        phase2=("PASS", 0), extra_argv=("--skip-phase3",))
    assert doc["demoted_phases"] == {}, doc["demoted_phases"]
    assert doc["verdict"] == "FAIL" and rc == 1
    assert any("not the rc the" in a for a in doc["advisories"]), doc["advisories"]


def test_a_blocking_return_the_classifier_did_not_classify_drops_the_sidecar():
    """THE OTHER HALF OF THE DEMOTION, in phase1's own runner.

    The sidecar is written BEFORE three later blocking returns — the L8 clock-period
    conflict, the extraction gap, the semantic layer gates — and its classifier knows
    nothing about any of them. All three `return 1`, the same rc the coverage-only path
    returns, so no reader can separate them by exit code: the #505 demotion would take
    a NON-coverage phase1 failure and publish PASS_WITH_WAIVERS at exit 0. My rc==1
    guard alone does NOT close that, which is why this half is here.

    Each of those returns now removes the sidecar it would otherwise leave. Pinned by
    AST on the call, and by position: the drop must precede the return it guards.
    """
    import ast
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert src.count("_drop_v0_3_7_exit_reason(project)") >= 3, (
        "fewer than three unclassified blocking returns drop the sidecar")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_drop_v0_3_7_exit_reason")
    assert "unlink" in ast.unparse(fn), "the drop does not remove anything"
    # every drop sits immediately before a `return 1`, never after it
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "_drop_v0_3_7_exit_reason(project)" in line and "def " not in line:
            nxt = next((l.strip() for l in lines[i + 1:i + 3] if l.strip()), "")
            assert nxt.startswith("return"), (i + 1, nxt)


def test_phase1s_report_is_read_where_its_producer_writes(project, monkeypatch):
    """THE ARM THAT WOULD HAVE CAUGHT MY ROUND-3 REGRESSION, now against ONE definition.

    Round 3: `_pl.report_path` routed to `reports/orchestrator/` while phase1's runner
    wrote `reports/phase1_one_shot.json`, so EVERY phase1-inclusive run came out
    NOT_MEASURED at exit 1 -- and a real phase1 FAIL became NOT_MEASURED, so the halt never
    fired and phase2/3 ran on bad L documents. My first fix taught the READER both
    locations, which added a fifth answer to a question that already had four. The producer
    now resolves through the router, so this stages the report the way the producer does --
    through that same call -- and requires the row to be the verdict in it.
    """
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            # the producer's own resolution, which is now the router's
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows["phase1"] == "PASS", (rows, doc["verdict"], doc["advisories"])
    assert doc["verdict"] == "PASS" and rc == 0, (doc["verdict"], doc["verdict_reasons"])


def test_the_reader_has_exactly_one_definition_of_where_a_report_lives(project):
    """One call to the router, for every phase, and NO second location.

    The arm is about what the reader does NOT do: a report staged at the unsanctioned flat
    path must not be found, because finding it is what let the two layouts coexist. All
    three `*_one_shot.json` names are categorised `orchestrator` by `_path_layout`, so the
    reader needs no per-phase knowledge at all.
    """
    for name in ("phase1_one_shot.json", "phase2_one_shot.json", "phase3_one_shot.json"):
        assert V._phase_report_path(project, name) == _pl.report_path(project, name), name

    # a file at the flat path is NOT what the reader resolves to, even when it is the only
    # one present and the routed one does not exist
    flat = project / "reports" / "phase1_one_shot.json"
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    resolved = V._phase_report_path(project, "phase1_one_shot.json")
    assert resolved != flat, (
        "the reader still knows a second location; that is what made four answers")
    assert not resolved.is_file()

    # and the resolver reads nothing off the disk, so a newer stale file cannot win it
    import inspect
    src = inspect.getsource(V._phase_report_path)
    for forbidden in ("st_mtime", "is_file", "exists("):
        assert forbidden not in src, (
            f"`_phase_report_path` consults the filesystem ({forbidden}); a path resolver "
            f"that picks by mtime can prefer a stale file from another location")


def test_phase1s_producer_resolves_its_report_through_the_router():
    """The premise, pinned against the producer itself, in BOTH directions.

    No flat write may remain, and every write of this report must go through the router --
    so if anyone reintroduces `reports / "phase1_one_shot.json"`, this arm says so instead
    of the front door silently reading a path nothing writes again.
    """
    import ast
    src = (PROGRAMS / "phase1_one_shot_runner.py").read_text()
    assert 'reports / "phase1_one_shot.json"' not in src, (
        "phase1's runner writes the flat path again; `reports_subfolder_taxonomy_check` "
        "FAILS on that location and the front door resolves only the router's")

    tree = ast.parse(src)
    routed = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "report_path"
                and any(isinstance(a, ast.Constant) and a.value == "phase1_one_shot.json"
                        for a in node.args)):
            routed += 1
    assert routed >= 3, (
        f"only {routed} of phase1's writes of this report resolve through the router; "
        f"measured, the runner has three write sites")


def test_the_sanctioned_location_is_the_one_the_taxonomy_gate_accepts(tmp_path):
    """WHY the router's answer is the sanctioned one, driven through the shipped gate.

    Not an appeal to the router's own table: `reports_subfolder_taxonomy_check` is run over
    both layouts and only one of them passes. If the doctrine ever changes, this arm changes
    with it instead of the claim quietly going stale.
    """
    import subprocess

    def strays(rel: str) -> str:
        proj = tmp_path / rel.replace("/", "_")
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"verdict": "PASS"}) + "\n")
        r = subprocess.run(
            [sys.executable, str(PROGRAMS / "reports_subfolder_taxonomy_check.py"),
             str(proj)], capture_output=True, text=True, timeout=300)
        return r.stdout + r.stderr

    assert "phase1_one_shot.json" in strays("reports/phase1_one_shot.json"), (
        "the flat location is no longer reported as a stray file; re-measure which layout "
        "the doctrine sanctions before trusting the router")
    assert "phase1_one_shot.json" not in strays(
        "reports/orchestrator/phase1_one_shot.json")


# ── the round-2 M, now that 70 sits on 77 ────────────────────────────────────

def test_a_scoped_audit_written_by_the_real_auditor_is_refused(tmp_path):
    """THE ROUND-2 M, closed against a document the REAL auditor wrote.

    My round-2 reader accepted an audit on the weak `phase == "all"` signal, because that
    was the only signal there was: `flow_compliance_check` stamped every receipt
    `phase: "all"` whatever `--stage` said, so a stage-scoped audit was indistinguishable
    from the whole run's. R-0915-147 gave the document a `scope` block, and this asserts
    the front door refuses a scoped one — driven by RUNNING a scoped pass, not by a
    hand-built fixture, because the premise under test is what that program actually
    writes.

    MEASURED here: `flow_compliance_check . --stage-id stage_phase1` publishes the
    canonical audit with `scope.whole_flow=false, step_count=2, flow_step_total=70`.
    """
    import subprocess
    import time

    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("# a counter\n")

    started_at = time.time()
    time.sleep(0.05)                       # the audit must land at or after the start
    subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_compliance_check.py"), str(project),
         "--stage-id", "stage_phase1"],
        capture_output=True, text=True, cwd=str(project), timeout=900)

    audit = _pl.report_path(project, "phase23_completion_audit.json")
    assert audit.is_file(), "the scoped pass wrote no canonical audit to refuse"
    doc = json.loads(audit.read_text())
    assert doc["scope"]["whole_flow"] is False, doc["scope"]
    assert doc["scope"]["step_count"] < doc["scope"]["flow_step_total"], doc["scope"]

    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=started_at)

    assert axis["state"] == "NOT_MEASURED", axis
    assert axis["sources"] == [], axis
    assert axis["scope_signal"] == _audit_scope.SIGNAL_SCOPE, axis
    assert str(doc["scope"]["step_count"]) in axis["reason"], axis["reason"]
    assert str(doc["scope"]["flow_step_total"]) in axis["reason"], axis["reason"]


def test_the_front_door_refuses_a_scoped_audit_the_same_way_the_other_readers_do():
    """ONE definition, not four. The front door must not be able to disagree with
    `benchmark_evidence_publish`, `phase3_one_shot_runner` and the pre-burn guard about
    what an audit judged — so it calls the same predicate, and this pins that it does.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(V._completion_audit_axis))
    fn = ast.parse(src).body[0]
    assert "_audit_scope.audit_scope_is_whole_flow" in src, (
        "the front door decides the audit's population by its own copy of the rule")

    # CODE ONLY. The docstring explains the rule at length and must go on doing so -- it is
    # the prose a reviewer reads. What must not exist is a SECOND READING of the block: the
    # comment-and-docstring text is stripped and the remaining statements are checked.
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))]
    code = ast.unparse(ast.Module(body=body, type_ignores=[]))
    # the CALL to the shared predicate is the one mention that must remain
    code = code.replace("_audit_scope.audit_scope_is_whole_flow", "<the one predicate>")
    assert "whole_flow" not in code, (
        "a second reading of `scope.whole_flow` is still in this reader's code")
    assert "'scope'" not in code and '"scope"' not in code, (
        "the reader still reaches into the audit's scope block itself")

    # and the predicate really is the one the other readers use
    for consumer in ("benchmark_evidence_publish.py", "phase3_one_shot_runner.py"):
        text = (PROGRAMS / consumer).read_text(errors="replace")
        assert "audit_scope_is_whole_flow" in text, consumer


def test_a_whole_flow_audit_from_the_real_auditor_is_still_accepted(tmp_path):
    """The other direction, so the arm above is not satisfied by refusing everything."""
    project = tmp_path / "proj"
    audit = _pl.report_path(project, "phase23_completion_audit.json")
    audit.parent.mkdir(parents=True, exist_ok=True)
    # the shape a whole-flow pass publishes, with the scope block R-0915-147 added
    audit.write_text(json.dumps({
        "verdict": "PASS",
        "scope": {"phase": "all", "stage": None, "stage_id": None,
                  "step_count": 70, "flow_step_total": 70, "whole_flow": True},
    }) + "\n")
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] != "NOT_MEASURED", axis
    assert axis["sources"] and axis["sources"][0]["verdict"] == "PASS", axis
    assert axis["scope_signal"] == _audit_scope.SIGNAL_SCOPE, axis


def test_a_legacy_audit_with_no_scope_block_is_accepted_but_disclosed(tmp_path):
    """The weaker signal is still usable — and says so, in the predicate's own words."""
    project = tmp_path / "proj"
    audit = _pl.report_path(project, "phase23_completion_audit.json")
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({"verdict": "PASS", "phase": "all"}) + "\n")
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] != "NOT_MEASURED", axis
    assert axis["scope_signal"] == _audit_scope.SIGNAL_LEGACY_PHASE, axis
    assert "weaker signal" in axis["scope_signal"]


# ── a phase whose PROCESS failed and left no report ──────────────────────────

def test_a_phase_whose_process_failed_with_no_report_is_a_fail_and_halts(project,
                                                                        monkeypatch):
    """R-0915-160. My round-3 rule silenced the only witness there was.

    "rc is an exit status, not a measurement" is right for rc == 0 -- phase3's
    `[SKIP] no usable PDK` exits 0 without writing anything, and a PASS conjured from that is
    a claim nobody made. For rc != 0 it is the mirror of the defect it was closing: the
    process DID tell us something, and NOT_MEASURED does not halt, so phase 2 and 3 ran on
    oracle-contaminated L documents. phase1's oracle-leak guard exits `SystemExit(2)` and
    writes no report; so does any traceback.
    """
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            return 2                       # the leak guard's exit; NO report written
        _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()

    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows.get("phase1") == "FAIL", (rows, doc.get("advisories"))
    assert doc["verdict"] != "PASS" and rc != 0, (doc["verdict"], rc)
    assert doc.get("halted_at") == "phase1", (
        f"the run did not halt at phase1, so phase 2/3 would build on whatever phase 1 "
        f"left behind: halted_at={doc.get('halted_at')!r}")
    # phase 2 must not even appear as having been measured
    assert rows.get("phase2") in (None, "NOT_RUN", "SKIPPED"), rows


def test_a_phase_that_exited_zero_with_no_report_is_still_not_measured(project,
                                                                      monkeypatch):
    """The half that must NOT move: rc 0 and no report is an absence, not a pass."""
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0                            # phase2 exits 0 and writes NOTHING

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()

    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows.get("phase2") == "NOT_MEASURED", rows
    assert doc["verdict"] != "PASS" and rc != 0, (doc["verdict"], rc)


def test_the_split_turns_on_the_exit_status_and_nothing_else(project):
    """Driven directly, both sides, with the report absent in both."""
    import time
    now = time.time()
    assert V._row_verdict(project, "phase1_one_shot.json", 0, now, "phase1")[0] \
        == "NOT_MEASURED"
    for rc in (1, 2, 137):
        verdict, why = V._row_verdict(project, "phase1_one_shot.json", rc, now, "phase1")
        assert verdict == "FAIL", (rc, verdict)
        assert str(rc) in why, (rc, why)

    # and a report that IS there outranks the exit status -- the phase's own account
    f = _pl.report_path(project, "phase1_one_shot.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    assert V._row_verdict(project, "phase1_one_shot.json", 2, 0.0, "phase1")[0] == "PASS"


# ── the RE-RUN cases (R-0915-160 second cut) ─────────────────────────────────

def _stale(path: Path, payload: dict, age_s: float = 9999.0) -> Path:
    """A report on disk from an EARLIER run: written, then back-dated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")
    old = time.time() - age_s
    os.utime(path, (old, old))
    return path


def test_a_phase_that_crashed_over_a_stale_report_is_a_fail_and_halts(project,
                                                                     monkeypatch):
    """(1) THE RE-RUN CASE, and the one that matters most.

    R-0915-151 moved phase 1's producer onto the routed path this reader reads, so on EVERY
    re-run a report is already sitting there. A phase-1 crash after the L documents are written --
    the oracle-leak `SystemExit(2)`, or a killed expert second pass at rc 137 -- then found the
    file present and stale, and my first cut answered NOT_MEASURED while ignoring rc. NOT_MEASURED
    does not halt, so phases 2 and 3 ran on oracle-contaminated documents.
    """
    _stale(_pl.report_path(project, "phase1_one_shot.json"),
           {"verdict": "PASS", "from": "an earlier run"})

    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            return 2                       # the leak guard's exit; writes nothing NEW
        _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}

    assert rows.get("phase1") == "FAIL", (rows, doc.get("advisories"))
    assert doc.get("halted_at") == "phase1", (
        f"the run did not halt, so phases 2/3 would build on whatever phase 1 left: "
        f"halted_at={doc.get('halted_at')!r}")
    assert rc != 0
    # and the stale report's verdict was never read
    assert doc["verdict"] != "PASS", doc["verdict"]
    assert rows.get("phase2") in (None, "NOT_RUN", "SKIPPED"), rows


@pytest.mark.parametrize("rc", [1, 2, 3, 137])
def test_the_class_is_the_same_fresh_or_re_run(project, rc):
    """(1b) ONE CLASS FOR EVERY NON-ZERO rc, INCLUDING THE STALL.

    It used to be FAIL on a fresh project and NOT_MEASURED on a re-run -- two answers to one
    question. MEASURED, every non-zero rc a phase runner in this tree returns is a refusal or an
    error and none is benign: rc 2 is "not a directory", an uncaught exception, or "REFUSED:
    canonical Phase-3 admission"; rc 3 refuses a second concurrent run. So FAIL on both paths.
    """
    now = time.time()
    fresh_answer = V._row_verdict(project, "phase1_one_shot.json", rc, now, "phase1")
    _stale(_pl.report_path(project, "phase1_one_shot.json"), {"verdict": "PASS"})
    rerun_answer = V._row_verdict(project, "phase1_one_shot.json", rc, now, "phase1")

    assert fresh_answer[0] == "FAIL", (rc, fresh_answer)
    assert rerun_answer[0] == "FAIL", (rc, rerun_answer)
    assert str(rc) in (rerun_answer[1] or ""), rerun_answer[1]
    assert "earlier run" in (rerun_answer[1] or ""), rerun_answer[1]


def test_rc_zero_over_a_stale_report_is_still_not_measured(project):
    """The half that must NOT move: exit 0 and no report OF ITS OWN is an absence, not a pass,
    and the stale file's verdict is never read."""
    _stale(_pl.report_path(project, "phase1_one_shot.json"), {"verdict": "PASS"})
    verdict, why = V._row_verdict(project, "phase1_one_shot.json", 0, time.time(), "phase1")
    assert verdict == "NOT_MEASURED", (verdict, why)
    assert "describes an earlier run" in (why or ""), why
    assert "verdict is not read" in (why or ""), why


# ── H5: the AI-backup re-invocation, driven END TO END ──────────────────────
#
# THE DEFECT (review wjn67aev3, MEDIUM #2). The front door may demote a coverage-only phase-1
# FAIL, and for a FIRST pass it decides the sidecar is this invocation's by mtime against the
# phase-1 start. On the expert SECOND pass that is wrong -- the pass carries pass 1's record and
# never rewrites the sidecar -- so the record NAMES the sidecar by content instead.
#
# r7 got the producer half backwards: the second pass named it only when
# `sidecar.mtime >= record.mtime`, while pass 1 writes the sidecar FIRST (in-process, from inside
# D1) and its record LAST. So on every real re-invocation nothing was named, the front door read
# "NOT demoting", and a `--skip-phase3` coverage-only project that was PASS_WITH_WAIVERS flipped
# to FAIL and halted at phase 1.
#
# AND NEITHER HALF'S ARMS COULD SEE IT: the producer fixture staged the sidecar at `record + 10s`,
# the reverse of the real order, and the reader arm asserted source substrings without ever
# calling `main()`. These three arms drive the REAL `main()`, in the REAL write order, with the
# REAL `run_second_pass_only` doing the carrying.

def _sidecar(project: Path) -> Path:
    return _pl.coverage_only_sidecar_path(project)


def _as_pass_one_leaves_it(project: Path, *, age_s: float = 5000.0) -> str:
    """Stage what a completed pass 1 leaves behind, IN THE REAL ORDER, and return the sha it named.

    Sidecar first, record last, both old enough to predate any later invocation's phase-1 start --
    which is exactly the situation the second pass is in and the one the mtime rule got wrong.
    """
    import hashlib
    import os

    import phase1_one_shot_runner as P1

    side = _sidecar(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True,
                                "coverage_pct": 71.0, "total_todo": 0}) + "\n")
    sha = hashlib.sha256(side.read_bytes()).hexdigest()

    summary = {"phase": 1, "mode": "docs", "verdict": "FAIL",
               "steps": [{"name": "doc_extract", "status": "FAIL"}]}
    # THE PRODUCER'S OWN CALL, not a hand-written field: if pass 1 stops naming the sidecar, or
    # names it differently, these arms follow it instead of describing a shape nobody writes.
    P1._name_the_sidecar_this_pass_wrote(project, summary, d1_ran=True)
    assert summary.get("pass1_coverage_sidecar", {}).get("sha256") == sha, summary
    _report(project, "phase1_one_shot.json", summary)

    then = time.time() - age_s
    os.utime(side, (then, then))                                  # sidecar first ...
    record = _pl.report_path(project, "phase1_one_shot.json")
    os.utime(record, (then + 10, then + 10))                      # ... record last
    assert side.stat().st_mtime < record.stat().st_mtime, (
        "the fixture must stage the REAL order, or it reproduces nothing")
    return sha


def _drive_second_pass(project: Path, monkeypatch, *, extra_argv=()) -> tuple:
    """`main()` where phase 1 is the REAL `run_second_pass_only`.

    Only the expert consumption and the steps view are stubbed -- the two things that would need a
    delivered subagent answer and a full step tree. The carrying, the naming and every line of the
    front door's demotion branch are the shipped ones.
    """
    import phase1_one_shot_runner as P1

    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(P1, "_consume_expert_answer",
                        lambda *a, **k: (0, {"consumed": True}), raising=False)

    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            return P1.run_second_pass_only(project, "zzdie", route="ic")
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", "--skip-phase3", *extra_argv])
    real_entry('IC', 'default', project)
    rc = V.main()
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    return rc, json.loads(out.read_text())


def test_invocation_a_demotes_on_a_sidecar_this_pass_wrote(project, monkeypatch):
    """INVOCATION A. A first pass writes the sidecar in this invocation, so the front door's own
    freshness rule carries the demotion. The baseline the re-invocation must not lose."""
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=("FAIL", 1, {"coverage_only_failure": True,
                            "coverage_pct": 71.0, "total_todo": 0}),
        phase2=("PASS", 0),
        extra_argv=("--skip-phase3",))
    assert doc["verdict"] == "PASS_WITH_WAIVERS", (doc["verdict"], doc.get("verdict_reasons"))
    assert rc == 0, rc
    assert doc["demoted_phases"]["phase1"]["token"] == V.DEMOTION_COVERAGE_ONLY


def test_invocation_b_second_pass_still_demotes(project, monkeypatch):
    """INVOCATION B, THE REGRESSION. The same project, re-entered as the expert second pass: the
    sidecar now predates this invocation's phase-1 start by an hour and a half, and what makes it
    trustworthy is that the carried record names it by content.

    At r7 this exits 1 with verdict FAIL and the advisory 'NOT demoting', because the carried
    record named nothing."""
    _as_pass_one_leaves_it(project)
    rc, doc = _drive_second_pass(project, monkeypatch)

    assert doc["verdict"] == "PASS_WITH_WAIVERS", (
        doc["verdict"], doc.get("verdict_reasons"),
        [a for a in doc.get("advisories", []) if "sidecar" in a])
    assert rc == 0, rc
    assert doc["demoted_phases"]["phase1"]["token"] == V.DEMOTION_COVERAGE_ONLY
    assert any("names it by content" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))
    assert not any("NOT demoting" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))


def test_a_sidecar_swapped_after_pass_one_named_it_is_refused(project, monkeypatch):
    """THE NEGATIVE CONTROL, and the reason the name is a DIGEST and not a path. Pass 1 named one
    set of bytes; something replaced them afterwards. The carried name no longer matches, so the
    demotion is refused and the run halts at phase 1 as it should."""
    sha = _as_pass_one_leaves_it(project)
    side = _sidecar(project)
    then = side.stat().st_mtime
    side.write_text(json.dumps({"coverage_only_failure": True, "swapped": True}) + "\n")
    # THE ARM HAS TO CLOSE THE OTHER ROUTE, and my first cut did not. The front door has TWO ways
    # to accept a sidecar: this invocation's phase-1 start (by mtime) OR the carried record's name
    # (by digest). Writing the bytes moved the mtime to now, and `main()` starts milliseconds
    # later, so `_FRESHNESS_TOLERANCE_S` legitimately made the swapped file "this invocation's" --
    # the run demoted, and the arm was measuring the mtime route while claiming to measure the
    # digest. Back-dated so the DIGEST is the only thing that could authorise it.
    os.utime(side, (then, then))
    import hashlib
    assert hashlib.sha256(side.read_bytes()).hexdigest() != sha
    assert side.stat().st_mtime < time.time() - 100, (
        "the swapped sidecar must still look old, or the mtime route decides this arm")

    rc, doc = _drive_second_pass(project, monkeypatch)
    assert doc["verdict"] == "FAIL", (doc["verdict"], doc.get("verdict_reasons"))
    assert rc == 1, rc
    assert doc.get("demoted_phases") == {}, doc.get("demoted_phases")
    assert any("NOT demoting" in a for a in doc.get("advisories", [])), doc.get("advisories")


def test_a_crashed_phase_one_cannot_borrow_an_earlier_runs_naming(project, monkeypatch):
    """THE HOLE r8 OPENED, and the one this round closes (review wkevxl71c).

    Invocation A left a fresh pass-1 record naming the sidecar it wrote, and the front door demoted
    on it -- correctly. Invocation B, on the same tree: phase 1 dies on an uncaught exception, exits
    1 and publishes NO record. `_row_verdict` says FAIL, which halts. But the #505 branch read the
    record still on disk -- A's -- found its name matching the untouched sidecar, saw rc == 1, and
    DEMOTED: phase 2 ran and the roll-up could publish PASS_WITH_WAIVERS for a run whose phase 1
    had crashed. A stale record must never authorise a demotion, whatever it names.
    """
    _as_pass_one_leaves_it(project)                     # invocation A's leftovers

    def crashed_phase1(label, runner, args, env=None):
        if "phase1" in runner.name:
            return 1                                    # exits 1, writes nothing
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", crashed_phase1)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())

    assert doc["verdict"] == "FAIL", (
        f"a run whose phase 1 crashed and published nothing was demoted on an EARLIER run's "
        f"naming: {doc['verdict']} / {doc.get('verdict_reasons')} / "
        f"{[a for a in doc.get('advisories', []) if 'sidecar' in a or 'earlier run' in a]}")
    assert rc == 1, rc
    assert doc.get("demoted_phases") == {}, doc.get("demoted_phases")
    assert any("belongs to an earlier run" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))
    # and the demotion route said so too, rather than falling silent
    assert any("NOT demoting" in a for a in doc.get("advisories", [])), doc.get("advisories")


def test_a_first_pass_that_crashes_after_writing_the_sidecar_is_not_demoted(
        project, monkeypatch):
    """THE SIBLING ON THE MTIME ROUTE (review w3nppqdpn), which r9 left open.

    A FIRST pass, nothing stale anywhere: D1 writes a fresh coverage-only sidecar, and the pass then
    dies before publishing its record -- `_run_expert_track` raising, or the record write itself.
    rc 1, NO record, and `_side_fresh` is True from the sidecar's own mtime, so r9's check (which
    sat on the carried-name route, reached only when the sidecar is NOT fresh) was never asked. The
    run demoted and phase 2 ran on a phase 1 that had crashed.

    `_drive_main` cannot express this: its fake always writes a record. That is the whole point of
    the case, so the fake here writes the sidecar and nothing else.
    """
    def crashes_after_the_sidecar(label, runner, args, env=None):
        if "phase1" in runner.name:
            side = _sidecar(project)
            side.parent.mkdir(parents=True, exist_ok=True)
            side.write_text(json.dumps({"coverage_only_failure": True,
                                        "coverage_pct": 71.0, "total_todo": 0}) + "\n")
            return 1                                    # ... and then it dies. No record.
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", crashes_after_the_sidecar)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())

    # the premise: the sidecar really is fresh, so the mtime route really was open
    assert _sidecar(project).is_file()
    assert not _pl.report_path(project, "phase1_one_shot.json").is_file(), (
        "the arm must leave phase 1 with NO record; a record makes this a different case")

    assert doc["verdict"] == "FAIL", (
        f"a phase 1 that crashed before publishing its record was demoted on its own fresh "
        f"sidecar: {doc['verdict']} / {doc.get('verdict_reasons')}")
    assert rc == 1, rc
    assert doc.get("demoted_phases") == {}, doc.get("demoted_phases")
    assert any("published NO record in this invocation" in a
               for a in doc.get("advisories", [])), doc.get("advisories")
    # and it is NOT excused as "the record belongs to an earlier run" -- there is no record at all
    assert not any("belongs to an earlier run" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))
