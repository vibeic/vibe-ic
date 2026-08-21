"""phase1 L7 generator — capture a verification plan's DV scenarios when they
are enumerated as a numbered / bulleted list of BOLD-named items, not a table.

Field observation (caravel_user_project × sky130A): the L7 input enumerates
three DV testbenches as `1. **io_ports** — ...`, `2. **la_test1** — ...`,
`3. **la_test2** — ...`. The two existing harvesters read only pipe TABLES, so
L7_TEST_DEBUG.json scored 0 typed test_scenarios (plus one garbled inline-
keyword verification_strategy entry) and FAILed the L7 ≥3 floor on genuine,
harvestable content. The fix adds a named-scenario-list harvester.

chip-AGNOSTIC: keyed on the list-item shape + an L7-keyworded input filename,
no chip literal.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = (Path(__file__).resolve().parent.parent
         / "phase1_doc_one_shot_runner.py")
_spec = importlib.util.spec_from_file_location("_p1_l7", _PROG)
P = importlib.util.module_from_spec(_spec)
sys.modules["_p1_l7"] = P
_spec.loader.exec_module(P)

_PLAN = (
    "# Verification Plan\n\n"
    "The design ships three reference testbenches:\n\n"
    "1. **io_ports** — firmware starts the block and checks the GPIO path.\n"
    "2. **la_test1** — drives the block through the logic-analyzer probe bus.\n"
    "3. **la_test2** — second LA scenario exercising arbitration.\n\n"
    "## Coverage targets\n"
    "- Functional coverage: 100 % of the three scenarios passing.\n"
    "- Reset clears state to 0.\n"
)


def _gen(tmp_path, extracted):
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l7_test_debug(proj, extracted)
    return json.loads(Path(res.path).read_text())


def _named(doc):
    return [s for s in doc.get("test_scenarios", [])
            if s.get("extraction_strategy") == "named_scenario_list"]


def test_named_scenario_list_captured(tmp_path):
    doc = _gen(tmp_path, {"L7_verification_plan.txt": _PLAN})
    names = {s["name"] for s in _named(doc)}
    assert {"io_ports", "la_test1", "la_test2"} <= names, doc.get(
        "test_scenarios")
    assert len(doc["test_scenarios"]) >= 3


def test_coverage_prose_bullets_not_swept(tmp_path):
    """NEGATIVE CONTROL: plain (non-bold) bullets under 'Coverage targets'
    ('- Functional coverage: ...') are NOT captured as scenarios."""
    doc = _gen(tmp_path, {"L7_verification_plan.txt": _PLAN})
    stimuli = {s.get("name") for s in _named(doc)}
    assert not any("coverage" in (n or "").lower() for n in stimuli)
    assert not any("Reset clears" in (n or "") for n in stimuli)


def test_non_verification_doc_not_swept(tmp_path):
    """NEGATIVE CONTROL: the same bold-named numbered list in a NON-L7-keyworded
    input file (architecture doc) is NOT harvested as test scenarios."""
    doc = _gen(tmp_path, {"L2_architecture.txt": _PLAN})
    assert _named(doc) == [], doc.get("test_scenarios")


def test_bold_list_without_description_not_swept(tmp_path):
    """NEGATIVE CONTROL: a bold-name bullet with no dash/colon + description is
    not a scenario shape and must not be captured."""
    txt = ("# Verification\n\n1. **just_a_name**\n2. **another**\n")
    doc = _gen(tmp_path, {"L7_verification_plan.txt": txt})
    assert _named(doc) == []
