"""vibe-ic#1969 — final_summary consumes one machine-readable audit snapshot.

The flow checker already owns the count and the per-step verdict.  Re-parsing
its human stdout gave the renderer a second definition: bracketed ``Step`` text
inside a gate's evidence could overwrite the real outer step line.  The 68-step
fixture below is internally coherent, but its stdout is deliberately shaped so
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

EXPECTED = {
    "PASS": 4,
    "FAIL": 7,
    "WAIVED-DEFERRED": 2,
    "SKIPPED-CONDITION": 23,
    "VACUOUS-PASS": 3,
    "PARTIALLY-VACUOUS": 5,
    "INCOMPLETE": 1,
    "PASS-VOIDED-BY-DEPENDENCY": 23,
}


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
    tally = (
        f"  PASS={counts['PASS']}  FAIL={counts['FAIL']}  "
        f"MISSING={counts['MISSING']}  WAIVED-DEFERRED={counts['WAIVED']}  "
        f"SKIPPED={counts['SKIPPED-CONDITION']}  "
        f"VACUOUS-PASS={counts['VACUOUS_PASS']}  "
        f"PARTIALLY-VACUOUS={counts['PARTIALLY-VACUOUS']}  "
        f"INCOMPLETE={counts['INCOMPLETE']}"
    )
    lines = [
        "=== Vibe-IC synthetic compliance ===",
        "Project: /synthetic/project",
        "Flow def: /synthetic/flow.yaml",
        "Steps: 68 total (4/43 executed PASS, 2 DEFERRED via waiver)",
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
            "INCOMPLETE", "PARTIALLY-VACUOUS", "VACUOUS-PASS", "WAIVED",
        }
        if status == "SKIPPED-CONDITION" and skip_overwrites < 2:
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


def test_fixture_is_the_same_68_step_universe_as_the_live_flow():
    """Real-artifact backing: fixture ids are the shipped flow's ids."""
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
    assert total == 68
    assert recounted.get("SKIPPED-CONDITION") == 21
    assert recounted.get("INCOMPLETE", 0) == 0
    assert recounted.get("PARTIALLY-VACUOUS", 0) == 0
    assert recounted.get("VACUOUS-PASS", 0) == 0
    assert recounted.get("WAIVED-DEFERRED", 0) == 0

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
    audit["step_counts"]["INCOMPLETE"] = 0
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
    assert audit["step_counts"]["MISSING"] == 1
    observed = audit.get("steps")
    assert isinstance(observed, list), (
        "the canonical audit published the tally but omitted the verdicts it "
        f"counted; keys={sorted(audit)}")
    observed_pairs = [(str(s["id"]), s["status"]) for s in observed]
    assert ("1", "MISSING") in observed_pairs
    # The checker injects its P0 preflight into even a one-step probe flow.
    # Whatever final universe it counted, every unit has a step record.
    assert len(observed) == sum(audit["step_counts"].values())
