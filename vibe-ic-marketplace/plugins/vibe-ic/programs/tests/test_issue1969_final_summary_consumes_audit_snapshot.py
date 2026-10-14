"""vibe-ic#1969 — final_summary consumes one machine-readable audit snapshot.

The flow checker already owns the count and the per-step verdict.  Re-parsing
its human stdout gave the renderer a second definition: bracketed ``Step`` text
inside a gate's evidence could overwrite the real outer step line.  The fixture
below (one row per step of the live flow) is internally coherent, but its stdout is deliberately shaped so
that the retired recount sees the measured drift from the issue:

    SKIPPED-CONDITION 21 vs 23, INCOMPLETE 0 vs 1,
    PARTIALLY-VACUOUS 0 vs 5, VACUOUS-PASS 0 vs 3,
    WAIVED-DEFERRED 0 vs 2.

The renderer must read ``step_counts`` for the roll-up and ``steps[].status``
for the per-step view from the SAME canonical audit JSON.  Reconciliation is
therefore an internal-integrity tripwire, not a contest between two parsers.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
sys.path.insert(0, str(HERE))

import final_report_generate as F  # noqa: E402
import final_summary_rollup_consistency_check as C  # noqa: E402
from _hostpaths import require_repo  # noqa: E402

FIXTURE = HERE / "fixtures" / "issue1969_recount_drift_audit.json"

#: The roll-up the renderer must publish: the FIXTURE's own `step_counts`,
#: which R-0915-85 reduced from twelve buckets to five. The eight-key literal
#: this replaces had four DUPLICATE keys after the collapse -- three `PASS`
#: and three `NOT_MEASURED` entries where the old words had been distinct --
#: so Python kept the last of each and the table silently asserted two
#: numbers instead of eight.
EXPECTED = {
    "PASS": 9,
    "PASS_WITH_WAIVERS": 2,
    "FAIL": 7,
    "NOT_MEASURED": 29,
    "NOT_APPLICABLE": 23,
}
#: `WAIVED-DEFERRED` is the CONTRACT label `final_report_generate` accepts as
#: an alias for PASS_WITH_WAIVERS in the stdout tally; it is not a roll-up row
#: of its own, so the published table carries the five and only the five.


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write_flow(path: Path, audit: dict) -> None:
    path.write_text(yaml.safe_dump({
        "version": 2,
        "flow_name": "issue1969_synthetic_68",
        "total_steps": len(audit["steps"]),
        "analog_steps": 0,
        "stages": [{"id": "stage1", "name": "synthetic stage"}],
        "steps": [
            {"id": row["id"], "name": row["name"], "stage": "stage1"}
            for row in audit["steps"]
        ],
    }, sort_keys=False), encoding="utf-8")


def _stdout_that_recounts_wrong(audit: dict) -> str:
    """Human output whose primary lines are right and nested evidence is not.

    The old dict-comprehension parser let the later evidence line overwrite the
    outer step with the same id.  Two skips and every member of the four other
    issue buckets are overwritten, reproducing 21/0/0/0/0 without changing the
    producer's JSON at all.
    """
    counts = audit["step_counts"]
    # R-0915-85 — the synthetic stdout tally is the FIVE, printed the way the
    # checker prints them, plus the WAIVED-DEFERRED alias the contract keeps.
    # It used to name eight buckets and double-count three of them into this
    # same line, which is not a shape any producer emits any more.
    tally = (
        f"  PASS={counts['PASS']}  "
        f"PASS_WITH_WAIVERS={counts['PASS_WITH_WAIVERS']}  "
        f"WAIVED-DEFERRED={counts['PASS_WITH_WAIVERS']}  "
        f"FAIL={counts['FAIL']}  "
        f"NOT_MEASURED={counts['NOT_MEASURED']}  "
        f"NOT_APPLICABLE={counts['NOT_APPLICABLE']}"
    )
    lines = [
        "=== Vibe-IC synthetic compliance ===",
        "Project: /synthetic/project",
        "Flow def: /synthetic/flow.yaml",
        f"Steps: {len(audit['steps'])} total (4/43 executed PASS, 2 DEFERRED via waiver)",
        tally,
    ]
    skip_overwrites = 0
    aliases = iter(("DESIGN_FACT", "MISSING_CAPABILITY", "UNCLASSIFIED"))
    alias = next(aliases)
    for row in audit["steps"]:
        status = row["status"].replace("_", "-")
        sid = row["id"]
        lines.append(f"  x [{status:<24}] Step {sid}: {row['name']}  (stage1)")
        overwrite = status in {
            "NOT_MEASURED", "PASS", "NOT_MEASURED", "PASS_WITH_WAIVERS",
        }
        if status == "NOT_APPLICABLE" and skip_overwrites < 2:
            overwrite = True
            skip_overwrites += 1
        if overwrite:
            lines.append(
                f"       evidence [{alias}] Step {sid}: nested gate detail")
            try:
                alias = next(aliases)
            except StopIteration:
                aliases = iter(("DESIGN_FACT", "MISSING_CAPABILITY", "UNCLASSIFIED"))
                alias = next(aliases)
    lines.append("Overall: FAIL  (strict=True)")
    return "\n".join(lines) + "\n"


def _render(monkeypatch, tmp_path: Path, audit: dict) -> str:
    project = tmp_path / "project"
    audit_path = project / "reports" / "audit" / "phase23_completion_audit.json"
    flow = tmp_path / "flow.yaml"
    _write_flow(flow, audit)
    monkeypatch.setattr(F, "FLOW_YAML", flow)
    stdout = _stdout_that_recounts_wrong(audit)

    def _fake_run_audit(*_args, **_kwargs):
        # The real checker writes the canonical snapshot during this call.
        # Doing the same here proves the renderer consumes the artifact from
        # THIS invocation rather than an older file left in the run directory.
        audit_path.parent.mkdir(parents=True)
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        return stdout, "FAIL"

    monkeypatch.setattr(F, "_run_audit", _fake_run_audit)
    return F._render(project, run_audit=True)


def test_fixture_is_the_same_step_universe_as_the_live_flow():
    """Real-artifact backing: fixture ids are the shipped flow's ids.

    The name no longer carries a count. It said "69" and went red the day the
    flow grew step 37.3 (#2514, 9ef6a544e..a51ba6220) — correctly, because
    the fixture had not grown with it; but a number in a test's NAME is one
    more copy of the flow's size that has to be edited by hand, and this
    assertion already derives the universe from the yaml."""
    flow_path = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    live = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    assert [str(s["id"]) for s in live["steps"]] == [
        str(s["id"]) for s in _fixture()["steps"]]


def test_renderer_consumes_json_counts_not_the_drifting_stdout_recount(
        monkeypatch, tmp_path):
    audit = _fixture()
    # Non-degeneracy: this really is the issue's retired-parser drift.
    parsed = F._parse_verdicts(_stdout_that_recounts_wrong(audit))
    recounted, total = F._verdict_rollup(
        {"steps": audit["steps"]}, parsed)
    # 68 -> 69 (2026-09-03): canonical step 37.4. The fixture gains ONE row
    # and it is `PASS_VOIDED_BY_DEPENDENCY`, deliberately: that status is not
    # in the overwrite set above, so the drifting recount this test is about
    # is left exactly as it was -- SKIPPED-CONDITION still recounts to 21 and
    # the other four buckets still to 0. A row in an overwriting status would
    # have moved the alias cycle and quietly changed what the test measures.
    #
    # 69 -> 70 (#2514): canonical step 37.3. Its row is DERIVED, not chosen:
    # 37.3 `blocks_on: [21]` and step 21 is `NOT_MEASURED/upstream_failed` in
    # this fixture, so 37.3 is the same -- which is what 37.4 already is here
    # since R-0915-85 migrated `PASS_VOIDED_BY_DEPENDENCY` into NOT_MEASURED.
    # That status IS in the overwrite set now, so it moves the alias cycle by
    # one; every assertion below is over membership (PASS recounts to 0, the
    # three synthetic classes appear), none over which alias lands where.
    # step_counts NOT_MEASURED 28 -> 29 is the fixture's own per-step tally.
    assert total == len(_fixture()["steps"]) == 70
    # THE PREMISE, restated over what the drift now looks like: the nested
    # evidence lines overwrite their outer step, so the stdout recount is not
    # the audit's own tally and must never be what the renderer publishes.
    # `PASS` recounts to ZERO while the artefact says 9, and three synthetic
    # classes appear that are not step statuses at all.
    assert recounted.get("PASS", 0) == 0
    assert audit["step_counts"]["PASS"] == 9
    assert {"DESIGN_FACT", "MISSING_CAPABILITY",
            "UNCLASSIFIED"} <= set(recounted), recounted

    md = _render(monkeypatch, tmp_path, audit)
    table = C.parse_rollup_table(md)
    assert table == EXPECTED, (
        "the final summary re-derived the roll-up instead of consuming "
        f"audit JSON step_counts: {table}")
    assert C.RECONCILIATION_FAILED_MARKER not in md


def test_reconciliation_banner_is_reserved_for_a_torn_audit_json(
        monkeypatch, tmp_path):
    audit = _fixture()
    # Keep the denominator unchanged while making step_counts disagree with
    # the per-step records inside that SAME artifact.
    audit["step_counts"]["NOT_MEASURED"] = 0
    audit["step_counts"]["PASS"] += 1
    md = _render(monkeypatch, tmp_path, audit)
    assert C.RECONCILIATION_FAILED_MARKER in md
    assert "torn audit" in md.lower()


def test_checker_serializes_per_step_verdicts_beside_step_counts(tmp_path):
    """Drive the real producer: the canonical audit must be self-contained."""
    checker = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "flow_compliance_check.py")
    flow = tmp_path / "one_step.yaml"
    flow.write_text(
        "version: 2\n"
        "flow_name: issue1969_one_step\n"
        "total_steps: 1\n"
        "analog_steps: 0\n"
        "stages:\n"
        "  - id: stage1\n"
        "    name: synthetic stage\n"
        "steps:\n"
        "  - id: 1\n"
        "    name: synthetic missing-output step\n"
        "    stage: stage1\n"
        "    required_outputs: [never_written.txt]\n",
        encoding="utf-8")
    project = tmp_path / "producer_project"
    project.mkdir()
    run = subprocess.run(
        [sys.executable, str(checker), str(project), "--flow-def", str(flow),
         "--strict"], capture_output=True, text=True, check=False)
    assert run.returncode == 1, run.stdout + run.stderr
    audit = json.loads((project / "reports" / "audit" /
                        "phase23_completion_audit.json").read_text())
    assert audit["step_counts"]["FAIL"] == 1
    observed = audit.get("steps")
    assert isinstance(observed, list), (
        "the canonical audit published the tally but omitted the verdicts it "
        f"counted; keys={sorted(audit)}")
    observed_pairs = [(str(s["id"]), s["status"]) for s in observed]
    # R-0915-85 — a declared output that does not exist is FAIL(missing_
    # artefact). The pair carries the reason, so the test still distinguishes
    # it from a gate defect rather than asserting a bare FAIL.
    assert ("1", "FAIL") in observed_pairs
    assert next(s for s in observed if str(s["id"]) == "1"
                )["reason_class"] == "missing_artefact"
    # The checker injects its P0 preflight into even a one-step probe flow.
    # Whatever final universe it counted, every unit has a step record.
    assert len(observed) == sum(audit["step_counts"].values())


PUBLIC_INPUTS = HERE / "fixtures" / "audit-public-inputs"


def _render_public_input(monkeypatch, tmp_path: Path, filename: str):
    """Supply only the external audit boundary; consume the real fresh JSON."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    audit = json.loads((PUBLIC_INPUTS / filename).read_text(encoding="utf-8"))
    project = tmp_path / "public_project"
    audit_path = project / "reports" / "audit" / "phase23_completion_audit.json"
    flow = tmp_path / "public_flow.yaml"
    _write_flow(flow, audit)
    monkeypatch.setattr(F, "FLOW_YAML", flow)
    # Match the checker's existing typed-disclosure rule, independently of
    # the renderer. The global PASS bucket still includes these rows.
    excluded = sum(
        row["status"] == "PASS"
        and bool({"vacuity", "partial_vacuity"} & set(row["disclosures"]))
        for row in audit["steps"])
    counts = audit["step_counts"]
    executed = counts["PASS"] - excluded
    total = sum(counts.values()) - counts["PASS_WITH_WAIVERS"] - counts["NOT_APPLICABLE"]
    stdout = "\n".join([
        "=== Vibe-IC public synthetic compliance ===",
        "Project: /synthetic/public_project",
        "Flow def: /synthetic/public_flow.yaml",
        f"Steps: {sum(counts.values())} total ({executed}/{total} executed PASS, "
        f"{counts['PASS_WITH_WAIVERS']} DEFERRED via waiver)",
        "  " + "  ".join(f"{key}={value}" for key, value in counts.items()),
        f"Overall: {audit['verdict']}  (strict=True)",
    ]) + "\n"

    def _fake_run_audit(*_args, **_kwargs):
        audit_path.parent.mkdir(parents=True)
        audit_path.write_bytes((PUBLIC_INPUTS / filename).read_bytes())
        (project / "audit.stdout").write_text(stdout, encoding="utf-8")
        return stdout, audit["verdict"]

    monkeypatch.setattr(F, "_run_audit", _fake_run_audit)
    md = F._render(project, run_audit=True)
    (project / "reports" / "final_summary.md").write_text(md, encoding="utf-8")
    assert json.loads(audit_path.read_text(encoding="utf-8")) == audit
    return md, audit


def _assert_public_summary(md: str, audit: dict) -> None:
    assert f"**`Overall: {audit['verdict']}`**" in md
    assert C.parse_rollup_table(md) == {
        key: value for key, value in audit["step_counts"].items() if value}
    assert C.RECONCILIATION_FAILED_MARKER not in md


def _assert_executed_views(md: str, numerator: int, denominator: int) -> None:
    # Check every published view, including the producer headline, prose,
    # acceptance sentence and resource log. A correct headline alone is not
    # enough when the renderer repeats a different number further down.
    views = [
        re.findall(r"\((\d+)/(\d+) executed PASS,", md),
        re.findall(r"PASS=\d+ → executed PASS=(\d+)", md),
        re.findall(r"executed PASS = (\d+)/(\d+)", md),
        re.findall(r"Canonical step executed PASS: \*\*(\d+)/(\d+)\*\*", md),
    ]
    expected = [
        [(str(numerator), str(denominator))], [str(numerator)],
        [(str(numerator), str(denominator))],
        [(str(numerator), str(denominator))],
    ]
    assert views == expected, {"observed": views, "expected": expected}


def test_failure_must_not_claim_all_measured_pass(monkeypatch, tmp_path):
    md, audit = _render_public_input(
        monkeypatch, tmp_path, "failure_pass1_fail1_no_waivers.audit.json")
    _assert_public_summary(md, audit)
    _assert_executed_views(md, 1, 2)
    # Scan the complete report for universal success claims about measured
    # or executed steps, allowing synonymous wording and Markdown wrapping.
    prose = " ".join(md.lower().replace("*", "").replace("_", " ").split())
    false_claims = re.findall(
        r"(?:every|all|each)\b[^.!?\n]{0,160}"
        r"(?:measur\w*|execut\w*)[^.!?\n]{0,160}"
        r"(?:passed|verified|successful\w*)", prose)
    assert false_claims == [], {"false_universal_success_claims": false_claims}


def test_partial_pass_must_not_be_counted_as_executed(monkeypatch, tmp_path):
    md, audit = _render_public_input(
        monkeypatch, tmp_path, "partial_vacuity_pass1_fail1.audit.json")
    _assert_public_summary(md, audit)
    assert audit["steps"][0]["status"] == "PASS"
    assert audit["steps"][0]["disclosures"] == ["partial_vacuity"]
    assert audit["steps"][0]["partial_vacuity_disclosed"] is True
    assert audit["steps"][1]["status"] == "FAIL"
    _assert_executed_views(md, 0, 2)


def test_overall_fail_is_preserved_in_rendered_summary(monkeypatch, tmp_path):
    for filename in ("failure_pass1_fail1_no_waivers.audit.json",
                     "partial_vacuity_pass1_fail1.audit.json"):
        md, audit = _render_public_input(
            monkeypatch, tmp_path / filename, filename)
        _assert_public_summary(md, audit)
        assert "**FAIL=1**" in md
        assert "INCOMPLETE — fix FAILs before claiming." in md
        assert "Engineering Phase 2+3 complete." not in md


def test_all_pass_companion_keeps_truthful_executed_counts(monkeypatch, tmp_path):
    md, audit = _render_public_input(
        monkeypatch, tmp_path, "all_pass2_no_waivers.audit.json")
    _assert_public_summary(md, audit)
    _assert_executed_views(md, 2, 2)
    assert "Engineering Phase 2+3 complete." in md


# Additional public #1969 denominator controls. Existing tests above are intact.
def _render_exclusion_input(monkeypatch, tmp_path: Path, filename: str):
    audit_bytes = (PUBLIC_INPUTS / filename).read_bytes()
    audit = json.loads(audit_bytes)
    project = tmp_path / "excluded_public_project"
    audit_path = project / "reports" / "audit" / "phase23_completion_audit.json"
    flow = tmp_path / "excluded_public_flow.yaml"
    _write_flow(flow, audit)
    monkeypatch.setattr(F, "FLOW_YAML", flow)
    counts = audit["step_counts"]
    # The existing producer serializes these named NOT_MEASURED exclusions.
    # Independently build its known headline, then exercise production loading,
    # count interpretation, reconciliation and every rendered ratio normally.
    excluded = [row for row in audit["steps"]
                if row["status"] == "NOT_MEASURED"
                and row.get("excluded_from_verdict")]
    assert {str(row["id"]) for row in excluded} == {
        str(row["step_id"]) for row in audit["not_measured_excluded"]}
    numerator = counts["PASS"] - sum(
        row["status"] == "PASS" and bool(
            {"vacuity", "partial_vacuity"} & set(row["disclosures"]))
        for row in audit["steps"])
    denominator = (sum(counts.values()) - counts["PASS_WITH_WAIVERS"]
                   - counts["NOT_APPLICABLE"] - len(excluded))
    stdout = "\n".join([
        "=== Vibe-IC public synthetic compliance ===",
        "Project: /synthetic/excluded_public_project",
        "Flow def: /synthetic/excluded_public_flow.yaml",
        f"Steps: {sum(counts.values())} total ({numerator}/{denominator} executed PASS, "
        f"{counts['PASS_WITH_WAIVERS']} DEFERRED via waiver)",
        "  " + "  ".join(f"{key}={value}" for key, value in counts.items()),
        f"Overall: {audit['verdict']}  (strict=True)",
    ]) + "\n"

    def _fake_run_audit(*_args, **_kwargs):
        audit_path.parent.mkdir(parents=True)
        audit_path.write_bytes(audit_bytes)
        (project / "audit.stdout").write_text(stdout, encoding="utf-8")
        return stdout, audit["verdict"]

    monkeypatch.setattr(F, "_run_audit", _fake_run_audit)
    md = F._render(project, run_audit=True)
    (project / "reports" / "final_summary.md").write_text(md, encoding="utf-8")
    assert audit_path.read_bytes() == audit_bytes
    _assert_public_summary(md, audit)
    return md, audit


def test_two_excluded_nm_rows_share_the_producers_denominator(monkeypatch, tmp_path):
    md, audit = _render_exclusion_input(
        monkeypatch, tmp_path, "two_excluded_nm_70_rows.audit.json")
    assert len(audit["steps"]) == 70
    assert audit["step_counts"] == {"PASS": 12, "PASS_WITH_WAIVERS": 0,
        "FAIL": 3, "NOT_MEASURED": 31, "NOT_APPLICABLE": 24}
    assert {str(row["step_id"]) for row in audit["not_measured_excluded"]} == {"6", "39"}
    _assert_executed_views(md, 10, 44)
    assert "**FAIL=3**" in md
    assert "INCOMPLETE — fix FAILs before claiming." in md
    assert "every canonical step that MEASURED something passed" not in md


def test_partial_pass_with_excluded_nm_keeps_both_qualifications(monkeypatch, tmp_path):
    md, audit = _render_exclusion_input(
        monkeypatch, tmp_path, "partial_with_two_excluded_nm.audit.json")
    assert audit["steps"][0]["disclosures"] == ["partial_vacuity"]
    _assert_executed_views(md, 0, 2)
    assert "**FAIL=1**" in md
    assert "Engineering Phase 2+3 complete." not in md


def test_unexcluded_nm_rows_remain_required_and_unmeasured(monkeypatch, tmp_path):
    md, audit = _render_exclusion_input(
        monkeypatch, tmp_path, "only_nm_with_two_excluded.audit.json")
    assert audit["step_counts"]["NOT_MEASURED"] == 4
    _assert_executed_views(md, 0, 2)
    assert "Engineering Phase 2+3 complete." not in md


def test_failed_row_marker_cannot_remove_a_measured_failure(monkeypatch, tmp_path):
    md, audit = _render_exclusion_input(
        monkeypatch, tmp_path, "failed_row_exclusion_marker_remains_blocking.audit.json")
    assert audit["steps"][1]["status"] == "FAIL"
    assert audit["steps"][1]["excluded_from_verdict"]
    _assert_executed_views(md, 1, 2)
    assert "**FAIL=1**" in md
    assert "Engineering Phase 2+3 complete." not in md


def test_inapplicable_row_marker_is_not_subtracted_twice(monkeypatch, tmp_path):
    md, audit = _render_exclusion_input(
        monkeypatch, tmp_path, "na_row_exclusion_marker_not_double_subtracted.audit.json")
    assert audit["steps"][1]["status"] == "NOT_APPLICABLE"
    assert audit["steps"][1]["excluded_from_verdict"]
    _assert_executed_views(md, 1, 1)
