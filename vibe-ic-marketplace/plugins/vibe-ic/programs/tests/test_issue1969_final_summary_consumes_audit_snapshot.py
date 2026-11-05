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
















# Additional public #1969 denominator controls. Existing tests above are intact.












# #3149: actual producer publishes an immutable recheck in the renderer's call.
import pytest  # noqa: E402




@pytest.mark.parametrize("publication", ["none", "wrong-hash"])
def test_issue3149_old_recheck_does_not_become_current(monkeypatch, tmp_path, publication):
    project = tmp_path / "project"
    target = project / "reports/audit/phase23_completion_audit.json"
    target.parent.mkdir(parents=True)
    audit = _fixture()
    target.write_text(json.dumps(audit))
    old = target.with_name("phase23_completion_audit." + "a" * 64 + ".json")
    old.write_text(json.dumps(audit))
    original = {p: p.read_bytes() for p in [target, old]}
    text = "Overall: FAIL (strict=True)\n"
    if publication == "wrong-hash":
        text += "flow_compliance_check: AUDIT_SNAPSHOT " + json.dumps({
            "path": str(old), "sha256": "0" * 64}) + "\n"
    monkeypatch.setattr(F, "_run_audit", lambda *a, **kw: (text, "FAIL"))
    markdown = F._render(project)
    assert "NO-VERDICT-IN-AUDIT" in markdown
    assert "no coherent audit counts available" in markdown
    assert all(p.read_bytes() == data for p, data in original.items())
