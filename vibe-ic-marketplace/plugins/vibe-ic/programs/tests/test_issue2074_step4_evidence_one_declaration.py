"""Issue #2074 — "where Step-4 evidence lives" has ONE declaration.

`flow/phase1_phase2_phase3.yaml` declares step 4's evidence as one requirement
in the shapes the supported TB paths emit::

    phase2/stage1/sim/*.log OR phase2/stage1/sim/results.xml
    OR phase2/stage1/sim/pass.flag
    OR phase2/stage1/sim_professional/**/results.xml

`design_one_shot_runner.step_step4_functional_evidence` looked only at
`phase2/stage1/sim/results.xml`. A JUnit written to the professional path (the
analog-acceptance producer's, #2064) therefore satisfied the gate and not the
inline step, so the inline verdict could not move and the reason a reader was
given named a file the flow does not require.

Both consumers now resolve the SAME entry, read from the YAML, through the same
`_glob_first`. Structural and chip-AGNOSTIC; no simulator.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as FLOW           # noqa: E402



_JUNIT = ("<testsuites><testsuite name='functional' tests='1' failures='0' "
          "errors='0' skipped='0'><testcase name='declared_behavior'/>"
          "</testsuite></testsuites>")

#: The gate's own resolution of one `required_outputs` entry, with no step
#: ledger — exactly what `check_step`'s probe does on a fresh run root.
_NO_BINDING = {"available": False, "reason": "no step ledger"}






def _gate_entry() -> str:
    """The flow YAML's step-4 evidence entry, read here INDEPENDENTLY of the
    program so the two cannot drift into agreement by construction."""
    doc = yaml.safe_load(Path(FLOW.DEFAULT_FLOW_DEF).read_text())
    for step in doc["steps"]:
        if str(step.get("id")) != "4":
            continue
        for entry in step.get("required_outputs") or []:
            if "phase2/stage1/sim/results.xml" in str(entry):
                return str(entry)
    raise AssertionError("the flow declares no step-4 sim-evidence entry")




# --------------------------------------------------------------------------
# 1. ONE declaration, read from the flow YAML.
# --------------------------------------------------------------------------
def test_the_alternatives_are_the_flow_yamls_own_entry():
    assert FLOW.step4_sim_evidence_alternatives() == [
        a.strip() for a in _gate_entry().split(" OR ") if a.strip()]


def test_the_declaration_still_names_both_homes():
    alts = FLOW.step4_sim_evidence_alternatives()
    assert "phase2/stage1/sim/results.xml" in alts
    assert "phase2/stage1/sim_professional/**/results.xml" in alts


def test_an_unreadable_declaration_raises_instead_of_defaulting(tmp_path):
    """Degrade LOUDLY. An empty alternative list would read as "the run
    produced nothing" and charge the design for a broken flow definition."""
    broken = tmp_path / "flow.yaml"
    broken.write_text("steps:\n  - id: 4\n    required_outputs: []\n")
    with pytest.raises(FLOW.Step4EvidenceUndeclared):
        FLOW.step4_sim_evidence_alternatives(broken)
    absent = tmp_path / "nowhere.yaml"
    with pytest.raises(FLOW.Step4EvidenceUndeclared):
        FLOW.step4_sim_evidence_alternatives(absent)


# --------------------------------------------------------------------------
# 2. A results.xml at EITHER declared path satisfies BOTH consumers.
# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# 3. A results.xml ELSEWHERE satisfies NEITHER.
# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# 4. MUTATION ARM — narrow the inline path again and the professional-only
#    tree goes red, which is exactly the state #2074 reported.
# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# 5. #2073 holds at the inline step too: the professional verdict is the union.
# --------------------------------------------------------------------------




if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
