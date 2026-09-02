"""#497 step 2 — the four consumers read the RECORDS, not the prose.

WHAT THIS PINS
--------------
`StepResult.reasons` carried six line shapes and four independent consumers
re-derived its grammar from prefixes. Two of the four are `all(...)` predicates,
so a parse error became a VERDICT change rather than a reporting one. Step 2
moves all four onto the umbrella's structured `gate_records`:

  1. `_parse_p0_failing_subgates`      -> `_p0_failing_gate_names`
     (feeds `_step_failure_is_informational_only` AND the
      PASS_WITH_OPEN_SOURCE_CONSTRAINTS `p0_is_deferrable` test)
  2. `_normalise_p0_reason_line` / `_per_gate_from_p0_reasons`
                                       -> `_p0_audit_gate_records`
  3. the `structural_fail_lines` scrape -> `_p0_structural_fail_lines`
     (the highest-stakes one: it sets `forced_fail` under
      `--phase 2 --strict-structural`, the flags
      `design_one_shot_runner.step_final_audit` ships)
  4. `_p0_passed_gate_count`            -> `_p0_passed_count`

HOW IT IS PINNED, AND WHY THAT SHAPE
------------------------------------
Asserting that the outputs are *correct* would pass just as well on the old
scrapers — they were correct too, on the shapes they had been taught. What
separates the two implementations is what happens when the prose and the
records DISAGREE. So most tests here drive the real `main()` with the umbrella
replaced by one that publishes honest records beside FABRICATED prose, and read
the artefacts `main()` actually writes. A consumer still parsing prose fails
them; a consumer reading records cannot.

Step 2 deliberately leaves `reasons` authored by the prose buckets, so the
operator listing still renders the fabrication. That is the seam step 3 closes;
these tests are about the four MACHINE consumers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
sys.path.insert(0, str(PROGRAMS))
import _gate_invocation as GI  # noqa: E402
import flow_compliance_check as F  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _p0_umbrella_probe_flow as _probe  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _project_with_rtl(tmp_path: Path) -> Path:
    """A project shaped like a run that actually happened.

    THE DELIVERY-ROUTE DECLARATION IS NOT DECORATION. `main()` runs several
    post-passes AFTER `check_step`, and `_attribute_condition_owner_blocks`
    (#1983) is one of them: every step that names `condition_owner: {step:
    0.5ic, declaration: delivery_route}` is hard `MISSING`, attributed
    `blocked-by-upstream(step 0.5ic)`, unless exactly one of the declaration's
    three alternatives exists in the tree. A `monkeypatch` that makes
    `check_step` return PASS does not reach that pass — it is not a step gate.

    MEASURED on tree 5e850b3acee8 without this file: steps 15.5ic, 26.5ic,
    37.5ip and 37.5ic all go MISSING with

        blocked-by-upstream(step 0.5ic): … delivery_route declaration is
        MISSING: none of ['input/submission_template/slots/*.yaml',
        'input/submission_template/NO_TEMPLATE.txt',
        'input/submission_template/SELF_TAPEOUT.txt'] exists

    None of the four is P0 and none is in `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`,
    so `non_blocked_failing` is non-empty, the OSS-constraints promotion never
    fires and `overall` stops at FAIL — before this file's subject, what the
    consumers do with a RECORD, has decided anything.

    The repair is the fixture, not the rule. Stubbing
    `_attribute_condition_owner_blocks` would blind these fixtures to a real
    blocking rule and hide exactly the #1983 x OSS-promotion interaction a real
    run meets every time; adding the four steps to
    `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` would loosen a shipped gate so a
    fixture can pass. This project declares a route instead — the IP/hardmacro
    terminal, the one alternative a bare RTL module with no operator template
    and no die of its own honestly is.
    """
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    tmpl = proj / "input" / "submission_template"
    tmpl.mkdir(parents=True)
    (tmpl / "NO_TEMPLATE.txt").write_text(
        "delivered as an IP/hardmacro: no operator submission template\n")
    return proj


def _stub_umbrella(monkeypatch, records, fails, skips, waivers=()):
    """Replace the umbrella with one whose PROSE and RECORDS disagree.

    Both channels are published exactly as the real umbrella publishes them:
    the 4-tuple carries the prose buckets, `records_out` carries the records.
    """
    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend(records)
        return (not any(r["verdict"] == "FAIL" for r in records),
                list(fails), list(skips), list(waivers))
    monkeypatch.setattr(F, "_run_structural_rtl_gates", _stub)


def _rec(name, verdict, message="", **evidence):
    return F._p0_gate_record(name, verdict, message, evidence)


def _run(tmp_path, extra=("--phase", "2", "--strict-structural"),
         probe_flow=False):
    """Drive the real `main()` over a probe flow whose P0 chain is SATISFIED.

    SAME ROOT CAUSE AS THE SIX THIS PR ALREADY FIXES, found by a full sweep of
    `a38902d16` rather than by the matrix. `P0` declares `blocks_on: [1]` and
    step 1 declares `blocks_on: [D1]`; a `tmp_path` project has run neither, so
    on the shipped 63-step flow the ordering rule fires against P0 and reds the
    run before this file's subject — what the CONSUMERS do with a record — can
    decide anything:

        [P0] … = INCOMPLETE marked done while dependency [1] Spec-to-RTL = MISSING
        [P0] … = INCOMPLETE marked done while dependency [D1] …          = MISSING

    Two tests here assert `rc == 0` after asserting the audit is clean
    (`failed_gates == []`, `gates == []`, `structural_fail_lines == []`), so
    they were failing on the flow's health rather than on the consumers':

        test_a_not_invocable_record_is_never_a_failing_gate
        test_waived_and_skipped_records_are_not_failures

    WHY THIS SEARCH MISSED IT AT FIRST, since it will mislead the next reader
    too: the ordering rule renders as `PASS_VOIDED_BY_DEPENDENCY` when it voids
    a PASS, but P0 here is `INCOMPLETE`, so the violation is reported with that
    word instead and a grep for the voided-PASS wording finds nothing.
    """
    proj = _project_with_rtl(tmp_path)
    report = tmp_path / "report.json"
    argv = [str(proj), "--json", str(report)]
    if probe_flow:
        flow_def = tmp_path / "p0_probe_flow.yaml"
        _probe.write_flow(flow_def)
        _probe.write_seed(proj)
        argv += ["--flow-def", str(flow_def)]
    rc = F.main([*argv, *extra])
    audit = json.loads(
        (proj / "reports" / "audit" /
         "phase23_completion_audit.json").read_text())
    return rc, json.loads(report.read_text()), audit


#: a reason line naming a gate that has NO record. Under the prose contract
#: every one of the four consumers would report it as a failing gate.
PHANTOM = "zzz_fabricated_gate_check"


# ═══════════ 1. prose that lies cannot reach any machine consumer ═══════════
def test_a_failing_gate_named_only_in_the_prose_reaches_no_consumer(
        tmp_path, monkeypatch, capsys):
    """The whole class, in one fixture.

    The prose says two gates failed; the records say one did. Every machine
    consumer must report the one with a record, and none may report the name
    that exists only as a sentence.
    """
    real = "real_structural_check"
    _stub_umbrella(
        monkeypatch,
        records=[_rec(real, "FAIL", "the real first line", exit_code=1),
                 _rec("quiet_check", "PASS", exit_code=0)],
        fails=[f"FAIL: {real} — the real first line",
               f"FAIL: {PHANTOM} — fabricated, has no record"],
        skips=[])
    rc, report, audit = _run(tmp_path)
    capsys.readouterr()

    # consumer 2 — the audit `gates` array
    assert [g["name"] for g in audit["gates"]] == [real]
    # consumer 1 — the canonical failed-gate name list
    assert audit["failed_gates"] == [real]
    assert audit["failed_gate_count"] == 1
    # consumer 3 — the strict-structural listing that sets forced_fail
    assert audit["structural_fail_lines"] == [f"{real} — the real first line"]
    # consumer 4 — the PASS population, which contributes no prose at all
    assert audit["passed_gate_count"] == 1
    assert PHANTOM not in json.dumps(audit["gates"])
    assert PHANTOM not in json.dumps(audit["failed_gates"])
    assert PHANTOM not in json.dumps(audit["structural_fail_lines"])
    assert rc == 1, "a real structural FAIL must still force the verdict"


def test_a_failing_gate_named_only_in_the_records_is_reported(
        tmp_path, monkeypatch, capsys):
    """The other direction: silence in the prose must not hide a FAIL.

    A migration that made the consumers merely IGNORE unknown prose would pass
    the test above and fail this one.
    """
    real = "silent_but_failing_check"
    _stub_umbrella(
        monkeypatch,
        records=[_rec(real, "FAIL", "boom", exit_code=1)],
        fails=[],            # the prose says nothing failed
        skips=[])
    rc, _report, audit = _run(tmp_path)
    capsys.readouterr()
    assert audit["failed_gates"] == [real]
    assert [g["name"] for g in audit["gates"]] == [real]
    assert audit["structural_fail_lines"] == [f"{real} — boom"]
    assert rc == 1


# ═════════════ 2. the two all(...) predicates that decide verdicts ══════════
def test_informational_only_is_decided_by_records_not_prose(
        tmp_path, monkeypatch, capsys):
    """`_step_failure_is_informational_only` excludes a step from `failing`.

    Under the prose contract, ONE unrecognised line made the `all(...)` False
    and converted a tolerated outcome into a FAIL. Here the prose fabricates a
    non-informational failing gate and the predicate must not see it.
    """
    info = sorted(F.INFORMATIONAL_GATES & set(F._STRUCTURAL_RTL_GATES))[0]
    _stub_umbrella(
        monkeypatch,
        records=[_rec(info, "FAIL", "coverage signal", exit_code=1)],
        fails=[f"FAIL: {info} — coverage signal",
               f"FAIL: {PHANTOM} — fabricated blocker"],
        skips=[])
    p0 = F.StepResult(
        id="P0", name="P0", stage="stage1", status="FAIL",
        reasons=[f"FAIL: {info} — coverage signal",
                 f"FAIL: {PHANTOM} — fabricated blocker"],
        gate_records=[_rec(info, "FAIL", "coverage signal", exit_code=1)])
    assert F._step_failure_is_informational_only(p0) is True

    # and end-to-end: the umbrella's failure is informational-only, so
    # --strict-structural must not force the verdict on it.
    rc, _report, audit = _run(tmp_path)
    capsys.readouterr()
    assert audit["structural_fail_lines"] == [], (
        "an INFORMATIONAL gate must not appear in the strict-structural block")
    assert rc == 0, "an informational-only P0 must not force Overall: FAIL"


def _all_steps_pass(monkeypatch):
    """Every non-P0 step PASSes, so P0 is the only thing standing between the
    run and the PASS_WITH_OPEN_SOURCE_CONSTRAINTS promotion.

    The promotion additionally requires `_OS_CONSTRAINTS_PREREQ_STEPS` (the
    chip is engineering-complete on FPGA + on-board test) to be PASS, which no
    fixture project reaches — that is why this path had no end-to-end test and
    why reverting its cut-over went unnoticed by the whole suite. Step 36 is
    outside `--phase 2`, so these runs must drive the FULL flow.
    """
    def _stub(_project, step, _waivers, **_kw):
        return F.StepResult(id=step.get("id"), name=step.get("name", ""),
                            stage=step.get("stage", ""), status="PASS",
                            reasons=[], evidence=[])
    monkeypatch.setattr(F, "check_step", _stub)


def test_deferrability_is_decided_by_records_not_prose(
        tmp_path, monkeypatch, capsys):
    """The PASS_WITH_OPEN_SOURCE_CONSTRAINTS `all(...)`, end to end.

    Same predicate shape as the informational one, opposite policy set: ONE
    name outside `_P0_THIN_INPUT_DEFERRABLE_SUBGATES` turns a deferrable run
    into a hard FAIL. The prose here supplies exactly that name and has no
    record behind it — which is the #492 shape, where 37 disclosure bullets
    supplied 37 such names on a run with 2 real failures.
    """
    deferrable = sorted(F._P0_THIN_INPUT_DEFERRABLE_SUBGATES)[:2]
    _all_steps_pass(monkeypatch)
    _stub_umbrella(
        monkeypatch,
        records=[_rec(g, "FAIL", "needs a commercial tool", exit_code=1)
                 for g in deferrable],
        fails=[f"FAIL: {g} — needs a commercial tool" for g in deferrable]
              + [f"FAIL: {PHANTOM} — fabricated, has no record"],
        skips=[])
    _rc, report, audit = _run(tmp_path, extra=("--strict-structural",))
    printed = capsys.readouterr().out

    assert report["overall"] == "PASS_WITH_OPEN_SOURCE_CONSTRAINTS", printed
    assert audit["verdict"] == "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"
    p0_deferral = next(d for d in audit["open_source_constraints_deferrals"]
                       if d["step_id"] == "P0")
    assert [s["sub_gate"] for s in p0_deferral["p0_thin_input_subgates"]] == \
        deferrable, "the deferral breakdown must name the recorded gates only"
    assert PHANTOM not in json.dumps(audit["open_source_constraints_deferrals"])


def test_a_non_deferrable_recorded_failure_still_blocks_the_promotion(
        tmp_path, monkeypatch, capsys):
    """Guard: the promotion must not become unconditional.

    Identical fixture except the extra failing gate has a RECORD. The verdict
    must stay FAIL — otherwise the test above would pass on an implementation
    that simply ignored the second gate.
    """
    deferrable = sorted(F._P0_THIN_INPUT_DEFERRABLE_SUBGATES)[:2]
    real = next(g for g in F._STRUCTURAL_RTL_GATES
                if g not in F._P0_THIN_INPUT_DEFERRABLE_SUBGATES
                and g not in F.INFORMATIONAL_GATES)
    _all_steps_pass(monkeypatch)
    _stub_umbrella(
        monkeypatch,
        records=[_rec(g, "FAIL", "needs a commercial tool", exit_code=1)
                 for g in deferrable]
                + [_rec(real, "FAIL", "a genuine structural defect",
                        exit_code=1)],
        fails=[f"FAIL: {g} — needs a commercial tool" for g in deferrable],
        skips=[])
    rc, report, _audit = _run(tmp_path, extra=("--strict-structural",))
    capsys.readouterr()
    assert report["overall"] == "FAIL"
    assert rc == 1


def test_a_real_non_deferrable_failure_still_defeats_both_predicates():
    """Guard: the cut-over must not make everything tolerable."""
    info = sorted(F.INFORMATIONAL_GATES)[0]
    real = next(g for g in F._STRUCTURAL_RTL_GATES
                if g not in F.INFORMATIONAL_GATES
                and g not in F._P0_THIN_INPUT_DEFERRABLE_SUBGATES)
    p0 = F.StepResult(
        id="P0", name="P0", stage="stage1", status="FAIL", reasons=["x"],
        gate_records=[_rec(info, "FAIL", "soft", exit_code=1),
                      _rec(real, "FAIL", "hard", exit_code=1)])
    assert F._step_failure_is_informational_only(p0) is False
    assert not all(g in F._P0_THIN_INPUT_DEFERRABLE_SUBGATES
                   for g in F._p0_failing_gate_names(F._p0_gate_records(p0)))


# ══════════════ 3. the outcome kinds that carry no verdict at all ═══════════
def test_a_not_invocable_record_is_never_a_failing_gate(
        tmp_path, monkeypatch, capsys):
    """#492's disclosure, as a verdict rather than a sentence.

    The prose still carries the disclosure block — that is the point of #492 —
    and the consumers must be structurally incapable of reading it as a
    failure. Not because they recognise its wording, but because the record
    says NOT_INVOCABLE.
    """
    ni = [_rec(f"unreachable_{i}_check", "NOT_INVOCABLE",
               "argparse rejected the umbrella's argv: unrecognized arguments",
               exit_code=2) for i in range(3)]
    skips = [GI.format_not_invocable_entry(r["name"], r["message"])
             for r in ni]
    _stub_umbrella(monkeypatch, records=ni, fails=[], skips=skips)
    rc, report, audit = _run(tmp_path, probe_flow=True)
    printed = capsys.readouterr().out

    assert audit["failed_gates"] == []
    assert audit["gates"] == []
    assert audit["structural_fail_lines"] == []
    assert rc == 0, "gates that never ran must not force the verdict"
    # the disclosure is still disclosed — the fix suppresses the MIS-READING
    p0 = next(s for s in report["steps"] if s["id"] == "P0")
    assert any(GI.NOT_INVOCABLE_SENTINEL in r for r in p0["reasons"])
    assert GI.NOT_INVOCABLE_HEADING_SENTINEL in printed


def test_waived_and_skipped_records_are_not_failures(
        tmp_path, monkeypatch, capsys):
    w = {"gate": "waived_check", "review_required": True, "ticket": "T-1",
         "reason": "thin-input", "evidence": "coverage-shape",
         "first_line": "the gate's own first line"}
    _stub_umbrella(
        monkeypatch,
        records=[F._p0_waiver_record(w),
                 _rec("skipped_check", "SKIP", "", exit_code=2,
                      skip_kind="input-missing"),
                 _rec("passing_check", "PASS", exit_code=0)],
        fails=[], skips=["skipped_check"], waivers=[w])
    rc, _report, audit = _run(tmp_path, probe_flow=True)
    capsys.readouterr()
    assert audit["failed_gates"] == []
    assert audit["failed_gate_count"] == 0
    assert audit["passed_gate_count"] == 1
    assert audit["structural_fail_lines"] == []
    assert rc == 0


# ═══════ 4. the PASS population — the number that read 0 for years ══════════
def test_passed_gate_count_counts_gates_no_prose_line_ever_named(
        tmp_path, monkeypatch, capsys):
    """Defect 3, asserted positively.

    A passing gate contributes NO reason line, by construction. The count was
    derived by scanning `reasons` for `PASS: <gate>` lines that have never
    existed, so it was pinned at 0 on every run in the artifact's history.
    """
    n = 7
    _stub_umbrella(
        monkeypatch,
        records=[_rec(f"clean_{i}_check", "PASS", exit_code=0)
                 for i in range(n)],
        fails=[], skips=[])
    _rc, report, audit = _run(tmp_path)
    capsys.readouterr()
    assert audit["passed_gate_count"] == n
    p0 = next(s for s in report["steps"] if s["id"] == "P0")
    blob = "\n".join(p0["reasons"])
    for i in range(n):
        assert f"clean_{i}_check" not in blob, (
            "premise: a passing gate is named nowhere in the prose")


def test_passed_gate_count_is_zero_when_the_umbrella_never_ran(tmp_path):
    """stage 3/4: no P0 step, no records, and 0 is the truth — not a scrape."""
    proj = _project_with_rtl(tmp_path)
    report = tmp_path / "report.json"
    F.main([str(proj), "--json", str(report), "--stage", "3", "--lenient"])
    audit = json.loads(
        (proj / "reports" / "audit" /
         "phase23_completion_audit.json").read_text())
    assert audit["passed_gate_count"] == 0
    assert audit["gates"] == []
    assert not [s for s in json.loads(report.read_text())["steps"]
                if s["id"] == "P0"]


# ═════════════ 5. the anchor: a real run, no stub anywhere ══════════════════
@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    proj = _project_with_rtl(tmp_path_factory.mktemp("i497s2"))
    report = proj.parent / "report.json"
    rc = F.main([str(proj), "--json", str(report),
                 "--phase", "2", "--strict-structural"])
    return (rc, json.loads(report.read_text()),
            json.loads((proj / "reports" / "audit" /
                        "phase23_completion_audit.json").read_text()))


def test_every_published_field_is_the_projection_of_the_published_records(
        real_run):
    """One real dispatch of the whole registry; the artefacts must agree with
    the records they were derived from, with nothing left over."""
    _rc, report, audit = real_run
    p0 = next(s for s in report["steps"] if s["id"] == "P0")
    recs = p0["gate_records"]
    assert recs and len(recs) == len(F._STRUCTURAL_RTL_GATES)
    assert audit["gates"] == F._p0_audit_gate_records(recs)
    assert audit["failed_gates"] == F._p0_failing_gate_names(recs)
    assert audit["failed_gate_count"] == len(audit["failed_gates"])
    assert audit["passed_gate_count"] == F._p0_passed_count(recs)
    assert audit["structural_fail_lines"] == F._p0_structural_fail_lines(recs)
    # non-trivial on all four axes, or the assertions above are vacuous
    assert audit["failed_gates"], "fixture must reach the FAIL population"
    assert audit["passed_gate_count"] > 0
    assert not any(r["verdict"] == "NOT_INVOCABLE" for r in recs)
    assert any(r["verdict"] == "SKIP"
               and r.get("evidence", {}).get("skip_kind") ==
               "declaration-not-present" for r in recs), (
        "the incomplete fixture must exercise the explicit derived-N/A arm")
    assert any(r["verdict"] == "SKIP" for r in recs)


def test_the_failing_gate_names_are_gate_names_not_sentences(real_run):
    """A gate name has no spaces. Kills the disclosure heading, the prose
    messages and the clean-sweep sentence in one invariant, without naming
    any of them."""
    import re
    _rc, _report, audit = real_run
    for name in audit["failed_gates"]:
        assert re.fullmatch(r"[A-Za-z_][\w.]*", name), name
        assert name in F._STRUCTURAL_RTL_GATES, (
            f"{name} is reported as a failing gate but is not registered")
