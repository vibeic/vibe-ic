"""The producer runs the blocker-list contract guard on what it publishes.

WHY THIS TEST EXISTS. `blocker_classification_check` guards the classified
blocker list `flow_compliance_check` emits beside the tally, and until this
change nothing but its own unit test ever handed it a report — zero coverage of
real artefacts, which is what `checker_execution_wiring_audit` blocks on. A
guard wired to a fixture and never to the producer is the shape this repo keeps
closing.

Both directions are asserted, on EMITTED JSON rather than on source:

  * a real run publishes the disclosure field and it is EMPTY — measured on an
    empty project (40 blockers, 0 violations) and on a copy of a committed run
    tree (41 blockers, 0 violations), so the wiring ships with no false alarm
    to bless;
  * a blocker list that breaks the contract is NAMED in that same field, while
    the design's own verdict is unchanged by it — which is the property that
    lets this guard run inside the producer at all.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_FCC_PATH = _PROGRAMS / "flow_compliance_check.py"


#: Bound for the blocking call below. Derived, not chosen:
#: `ci_harness_timeout_ceiling_check` resolves the pytest harness bound from
#: tools/gatekeeper-land.sh:197 (`--timeout=180 --timeout-method=thread`) and
#: permits one blocking call at most 180 // 3 = 60 s; above that the inner
#: bound can never fire, because pytest ends the SESSION first and every
#: other file in the subset loses its verdict. The landed value was 600.
#: MEASURED on this tree with `pytest --durations=0`: the whole test — this
#: subprocess included — costs 0.35 s, so 60 s is 170x headroom and is a hang
#: detector for a hung `flow_compliance_check`, the only way it fails to
#: return.
_CEILING_S = 60

def _empty_project(root: Path) -> Path:
    (root / "input" / "docs").mkdir(parents=True)
    (root / "reports").mkdir(parents=True)
    return root


def test_a_real_run_publishes_the_guard_verdict_and_it_is_clean(tmp_path):
    """Subprocess, exactly as the flow invokes it: the field is there, empty.

    `blockers` is asserted non-empty on purpose — a report with nothing to
    classify would satisfy the contract vacuously and would prove nothing about
    whether the guard was handed a real list.
    """
    proj = _empty_project(tmp_path / "proj")
    out = tmp_path / "report.json"
    subprocess.run([sys.executable, str(_FCC_PATH), str(proj),
                    "--json", str(out)],
                   capture_output=True, text=True, timeout=_CEILING_S)
    doc = json.loads(out.read_text())
    assert doc["blockers"], "no blocker list was produced; the guard saw nothing"
    assert "blocker_contract_violations" in doc, (
        "the producer published a blocker list without publishing whether it "
        "satisfies its own contract")
    assert doc["blocker_contract_violations"] == []
    assert doc["blocker_list_error"] == ""


def test_a_blocker_list_that_breaks_the_contract_is_named_in_the_report(
        tmp_path, monkeypatch):
    """The control: make the classifier invent a blocker, in-process.

    A step that is not in `steps` must not appear in `blockers` — attributing a
    blocker to a step that passed fabricates work rather than losing it. The
    guard has to say so through the ARTEFACT, not only in its own unit test.

    The same project is run twice, classifier clean and classifier broken, and
    `overall` is compared: a defect in the classifier must not become a
    statement about the design, which is the whole reason this is advisory
    inside the producer and blocking in the CI sweep.
    """
    fcc = importlib.import_module("flow_compliance_check")
    real = fcc._bc.build_blockers

    clean_proj = _empty_project(tmp_path / "clean")
    clean_out = tmp_path / "clean.json"
    fcc.main([str(clean_proj), "--json", str(clean_out)])
    clean = json.loads(clean_out.read_text())
    assert clean["blocker_contract_violations"] == []

    def _inventing(*args, **kwargs):
        blockers = list(real(*args, **kwargs))
        blockers.append({
            "step_id": 99999, "step_name": "a step that does not exist",
            "stage": "s", "status": "FAIL", "classification": "DESIGN_FACT",
            "basis": "invented-by-the-control", "measures": "m",
            "observed": "o", "derived_from": [], "sub_blockers": None,
        })
        return blockers

    monkeypatch.setattr(fcc._bc, "build_blockers", _inventing)

    broken_proj = _empty_project(tmp_path / "broken")
    broken_out = tmp_path / "broken.json"
    fcc.main([str(broken_proj), "--json", str(broken_out)])
    broken = json.loads(broken_out.read_text())

    violations = broken["blocker_contract_violations"]
    assert violations, "the invented blocker reached the report ungraded"
    assert any("99999" in v for v in violations), violations
    assert broken["overall"] == clean["overall"], (
        "a defect in the CLASSIFIER moved the verdict about the design")
