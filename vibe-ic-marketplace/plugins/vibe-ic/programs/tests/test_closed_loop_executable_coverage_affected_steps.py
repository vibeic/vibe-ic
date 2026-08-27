#!/usr/bin/env python3
"""The step-32 repair pass must declare the blast radius the FLOW implies, not a
hand-typed list nobody checks.

WHAT WAS MEASURED, at 867de4289 (v1.11.18)
==========================================
Three documents described the same set and no two agreed:

    phase3_one_shot_runner.py  "affected_steps": [21, 23, 24, 29, 30]
    flow step 32 trigger       "Aggregator: re-run #21-#28 after repair"
    flow step 32 blocks_on     [23, 24, 25, 26, 27, 29, 30, 31]

and nothing read any of them. `postroute_timing_repair_audit` asks `"affected_steps" not in
data` and stops there, so `[]` and `[999]` were both clean. `git log -S` puts the
literal in `0a9e51577`; no test asserted it in the ~300 versions since —
`test_postroute_timing_repair_auto_trigger_mcorner_ocv_gate.py` and `test_postroute_timing_repair_audit.py` build
their own fixture dicts that merely happen to carry the same numbers.

THE RULE THIS FILE ENFORCES
===========================
The repair rewrites the ROUTED implementation — multi-corner `repair_design` +
`repair_timing -setup` + `detailed_route`, followed by its own re-extraction —
which is step 21's output. So the evidence that no longer describes the design is

    {21} u descendants(21)  -  descendants(32)  -  {32}

over the flow's `blocks_on` graph: everything downstream of routing that has
already produced evidence, minus what is downstream of the repair and would
consume its result anyway.

The two entries the old literal omitted and that matter most:
  * 22, parasitic extraction — the repair re-extracts, which is proof it is stale;
  * 31, physical verification — the repair changes geometry AND netlist, so DRC
    and LVS are both invalidated. Shipping a repair without re-running LVS is the
    failure this file exists to make impossible to reintroduce quietly.

Every assertion below is derived from the SHIPPED flow at run time, so the day
the DAG moves this test moves with it — and `test_the_derivation_is_not_a_constant`
proves the derivation actually reads the graph instead of returning a literal.
"""
from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
PLUGIN = _HERE.parent.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
RUNNER = PLUGIN / "programs" / "phase3_one_shot_runner.py"

#: The step whose output the repair rewrites, and the step that does the repair.
ROUTING_STEP = "21"
REPAIR_STEP = "32"

#: The literal that shipped for ~300 versions. Kept so the negative control is
#: an actual historical state and not an invented one.
PRE_FIX_LITERAL = ["21", "23", "24", "29", "30"]


def _norm(v: Any) -> str:
    return str(v).strip()


def _load(doc_path: Path = FLOW) -> Dict[str, Any]:
    return yaml.safe_load(doc_path.read_text(encoding="utf-8"))


def _blocks_on(doc: Dict[str, Any]) -> Dict[str, List[str]]:
    return {_norm(s["id"]): [_norm(p) for p in (s.get("blocks_on") or [])]
            for s in doc["steps"] if isinstance(s, dict) and "id" in s}


def _ancestors(sid: str, bo: Dict[str, List[str]]) -> Set[str]:
    out: Set[str] = set()
    stack = [sid]
    while stack:
        for p in bo.get(stack.pop(), []):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def _descendants(sid: str, bo: Dict[str, List[str]]) -> Set[str]:
    return {k for k in bo if sid in _ancestors(k, bo)}


def derive_blast_radius(doc: Dict[str, Any]) -> Set[str]:
    """{21} u desc(21) - desc(32) - {32}, over this document's own graph."""
    bo = _blocks_on(doc)
    return (({ROUTING_STEP} | _descendants(ROUTING_STEP, bo))
            - _descendants(REPAIR_STEP, bo) - {REPAIR_STEP})


def runner_affected_steps() -> Set[str]:
    """The literal the runner actually ships, read from the source.

    Read via AST rather than by importing: the runner is a 41k-line module with
    heavyweight import-time work, and this test must measure the SOURCE anyway —
    an import would measure whatever a mock happened to leave behind.
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    found: List[List[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "affected_steps":
                assert isinstance(v, ast.List), (
                    "`affected_steps` is no longer a list literal; this test "
                    "can no longer read it and must be rewritten, not deleted")
                found.append([_norm(e.value) for e in v.elts
                              if isinstance(e, ast.Constant)])
    assert len(found) == 1, (
        f"expected exactly one `affected_steps` literal in {RUNNER.name}, "
        f"found {len(found)}: {found}")
    return set(found[0])


# ══════════════════════════════════════════════════════════════════════════
# POSITIVE
# ══════════════════════════════════════════════════════════════════════════
def test_the_runner_literal_is_the_derived_blast_radius():
    derived = derive_blast_radius(_load())
    assert runner_affected_steps() == derived, (
        "the shipped `affected_steps` and the flow DAG disagree; fix whichever "
        "is wrong and say which in the commit — do not just make them match")


def test_the_literal_carries_no_duplicates_and_no_phantom_steps():
    doc = _load()
    ids = {_norm(s["id"]) for s in doc["steps"]}
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    literal: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "affected_steps":
                    literal = [_norm(e.value) for e in v.elts
                               if isinstance(e, ast.Constant)]
    assert literal, "no literal found"
    assert len(literal) == len(set(literal)), f"duplicates: {literal}"
    assert set(literal) <= ids, f"phantom step ids: {set(literal) - ids}"


def test_extraction_and_physical_verification_are_in_the_radius():
    """The two the pre-fix literal omitted, asserted by NAME so a future author
    reads why rather than seeing a bare number."""
    derived = derive_blast_radius(_load())
    by = {_norm(s["id"]): str(s.get("name") or "") for s in _load()["steps"]}
    assert "22" in derived and "Extraction" in by["22"]
    assert "31" in derived and "Physical Verification" in by["31"]
    assert {"22", "31"} <= runner_affected_steps()


def test_the_radius_excludes_what_runs_after_the_repair():
    """Metal fill and GDS consume the repair's result; they are not invalidated
    by it. A radius that swallowed them would be a different kind of wrong."""
    derived = derive_blast_radius(_load())
    bo = _blocks_on(_load())
    after = _descendants(REPAIR_STEP, bo)
    assert after, "step 32 has no descendants — the flow changed shape"
    assert not (derived & after)
    assert REPAIR_STEP not in derived


# ══════════════════════════════════════════════════════════════════════════
# NEGATIVE — the control that makes the green mean something
# ══════════════════════════════════════════════════════════════════════════
def test_the_pre_fix_literal_would_fail_this_test():
    """Bidirectional control. A test that cannot fail against the pre-fix code
    proves nothing, and this one has to be checked against the state it was
    written for rather than only against the state it produced."""
    derived = derive_blast_radius(_load())
    assert set(PRE_FIX_LITERAL) != derived
    missed = derived - set(PRE_FIX_LITERAL)
    assert "31" in missed, (
        "the pre-fix literal is supposed to have omitted physical verification; "
        f"it did not, so the premise of this file is wrong — missed={sorted(missed)}")


def test_the_flow_prose_for_step_32_also_disagrees_with_the_derivation():
    """Recorded as a live measurement, not prose: step 32's trigger still says
    `re-run #21-#28`, which is neither the derivation nor the old literal. The
    flow is the lander's file, so this asserts the DISAGREEMENT rather than the
    fix — and goes green the moment the prose is corrected in either direction.
    """
    doc = _load()
    step32 = next(s for s in doc["steps"] if _norm(s["id"]) == REPAIR_STEP)
    trigger = str(step32["closed_loop"]["trigger"])
    prose_says = {str(n) for n in range(21, 29)}      # "#21-#28"
    derived = derive_blast_radius(doc)
    if "21-#28" in trigger or "21-28" in trigger:
        assert prose_says != derived
        assert {"29", "30", "31"} <= (derived - prose_says)
    else:
        pytest.skip("step 32's trigger prose no longer names #21-#28")


def test_the_derivation_is_not_a_constant():
    """Mutate the DAG and the answer must move.

    Without this, `derive_blast_radius` could return a frozen set and every
    assertion above would still pass — the shape this repository calls a ruler
    fitted to the answer.
    """
    doc = _load()
    base = derive_blast_radius(doc)
    mutant = copy.deepcopy(doc)
    for s in mutant["steps"]:
        if _norm(s["id"]) == "22":          # detach extraction from routing
            s["blocks_on"] = []
    moved = derive_blast_radius(mutant)
    assert moved != base
    assert "22" in base and "22" not in moved


def test_the_radius_is_anchored_by_who_NAMES_the_repair_step():
    """MEASURED, and it contradicted the first draft of this test.

    Deleting step 32's own record does NOT move the radius: `descendants(32)` is
    computed from the steps that NAME 32 in their `blocks_on` (34 and 36), not
    from 32's own entry. That is the right property — the subtraction survives
    the record being renamed or moved — but it means the thing to guard is the
    naming, not the record. So both arms are asserted: deleting the record is a
    no-op, and cutting every reference to 32 makes the radius swallow the whole
    downstream tail, which is the failure a reader should be able to recognise.
    """
    base = derive_blast_radius(_load())

    no_record = _load()
    no_record["steps"] = [s for s in no_record["steps"]
                          if _norm(s["id"]) != REPAIR_STEP]
    assert derive_blast_radius(no_record) == base

    orphaned = _load()
    for s in orphaned["steps"]:
        if s.get("blocks_on"):
            s["blocks_on"] = [p for p in s["blocks_on"]
                              if _norm(p) != REPAIR_STEP]
    grown = derive_blast_radius(orphaned)
    assert grown > base, "cutting every reference to 32 must widen the radius"
    # GDSII output is unambiguously DOWNSTREAM of the repair; its appearance is
    # the recognisable signature of the anchor having been cut. (34, metal fill,
    # does NOT appear: its only parent was 32, so it leaves the graph entirely.)
    assert "37" in (grown - base), sorted(grown - base)
