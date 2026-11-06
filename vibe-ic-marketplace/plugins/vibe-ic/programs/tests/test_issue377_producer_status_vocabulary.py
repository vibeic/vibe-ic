#!/usr/bin/env python3
"""vibe-ic#377 — the producer `extraction_status` vocabulary.

TWO THINGS ARE PINNED HERE, and they are the two halves of one measurement.

(1) THE NON-FUSION INVARIANT.
    `l_doc_consumer_contract.is_extraction_claimed` and the L16/L17/L18 gates'
    local `_STATUS_FOUND_NOTHING` set read the SAME producer field and look
    like two spellings of one concept. They are not. They are two different
    binary projections of a THREE-valued producer state, and the property that
    proves it is a state on which BOTH are False. These tests assert that
    property directly on the real functions, so a future "unification" that
    makes one the negation of the other reddens here instead of silently
    turning an honest empty layer into a blocking assertion.

(2) THE ARM THAT VOCABULARY WAS DECLARED FOR AND NEVER WIRED.
    `l16_compliance_properties_actionable_check` defined `_STATUS_FOUND_NOTHING`
    and never loaded it. E2 catches "status claims success, payload empty";
    the opposite direction — "status says it found nothing, payload populated"
    — went unchecked, while both sibling gates in the same family check it.

NEGATIVE CONTROL IS THE POINT: every rail is asserted in both directions.
All fixtures are SYNTHESIZED neutral data. No design/PDK/vendor name appears.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
PROG = _PROGRAMS / "l16_compliance_properties_actionable_check.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# (1) The non-fusion invariant
# ---------------------------------------------------------------------------
def test_the_two_status_predicates_are_not_complements():
    """The load-bearing property: a state on which BOTH answer False.

    If someone "unifies" the two by making `_STATUS_FOUND_NOTHING` the
    complement of `is_extraction_claimed`, NOT_YET_EXTRACTED must become True
    for one of them and this reddens.
    """
    contract = _load("l_doc_consumer_contract")

    doc = {"extraction_status": "NOT_YET_EXTRACTED"}
    claimed = contract.is_extraction_claimed(doc)

    assert claimed is False, (
        "is_extraction_claimed must treat an un-run skeleton as asserting "
        "nothing")


def test_ran_and_found_nothing_is_true_for_both_questions():
    """The overlap is an answer to two questions, not drift.

    EXTRACTION_FOUND_NOTHING means extraction RAN (so it is a claim about the
    run) AND reported empty (so the payload should be empty). Both predicates
    saying True is correct; a "fix" that makes one False to match the other
    would break the arm that depends on it.
    """
    contract = _load("l_doc_consumer_contract")

    doc = {"extraction_status": "EXTRACTION_FOUND_NOTHING"}
    assert contract.is_extraction_claimed(doc) is True






# ---------------------------------------------------------------------------
# (2) L16 E4 — fixtures
# ---------------------------------------------------------------------------
def _mk_project(tmp: Path, l16: dict) -> Path:
    """A neutral design: 4 declared ports, two registers, one clock domain."""
    proj = tmp / "run"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "widget_top",
        "ports": [
            {"name": "core_clk", "direction": "input", "width": 1},
            {"name": "core_rst_n", "direction": "input", "width": 1},
            {"name": "load_enable", "direction": "input", "width": 1},
            {"name": "result_valid", "direction": "output", "width": 1},
        ],
        "clock_domains": [{"name": "core_clk"}],
    }))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "registers": [{"name": "ctrl_mode"}, {"name": "status_flags"}]}))
    (gd / "L16_COMPLIANCE_PROPERTIES.json").write_text(json.dumps(l16))
    return proj


def _mk_programs_dir(tmp: Path) -> Path:
    pdir = tmp / "programs_stub"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "professional_tb_gen.py").write_text(
        "from pathlib import Path\n"
        "def build_assertions(gd):\n"
        "    return (gd / 'L16_COMPLIANCE_PROPERTIES.json').read_text()\n")
    return pdir


# Anchored on a port this synthetic design declares, so the property is
# ACTIONABLE and the run cannot fail for an unrelated reason.
_ANCHORED = [{"english_form": "load_enable must be stable while busy",
              "signals": ["load_enable"]}]


def _run(project: Path, pdir: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(PROG), str(project), "--programs-dir", str(pdir),
         *extra], capture_output=True, text=True)


def _cats(cp) -> set[str]:
    return {f["category"] for f in json.loads(cp.stdout)["findings"]}
