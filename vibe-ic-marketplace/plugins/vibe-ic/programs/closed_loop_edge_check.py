#!/usr/bin/env python3
"""closed_loop_edge_check.py — a declared `closed_loop` must be an edge
something can actually take, or the declaration is decoration.

CHIP_AGNOSTIC: strict — no process, vendor or PDK name anywhere in this file,
DOCSTRING INCLUDED. This is STRICTER than the repo-wide `source_chip_agnostic_check`,
which permits open-PDK names and clears 508 programs that carry one legitimately.
That gate's PASS is not this file's verdict; `test_closed_loop_edge_check::test_the_program_names_no_process_or_vendor_token` is, and it reads the WHOLE file.

MEASURED, which is why this paragraph exists: a docstring paragraph naming two open
PDKs was added to this file, the repo-wide gate returned PASS over 1544 files, and
this file's own test was red. The rule was real and invisible. Identify a library by
its cell count and the registry population it came from, never by its name.

THE DEFECT, MEASURED ON main @ 46db018669 (v1.11.7)
====================================================
The canonical flow declares NINETEEN `closed_loop:` blocks. **Nothing in this
repository reads any of them.**

    grep -c "closed_loop:" flow/phase1_phase2_phase3.yaml            -> 19
    grep -n  "fallback_to:" flow/phase1_phase2_phase3.yaml           -> 19 lines
    grep -rn "closed_loop|fallback_to" --include=*.py --include=*.json
             (whole plugin, excluding flow/)                         -> 0 consumers

The only hits are unrelated homonyms: `undisclosed_loops` (a hygiene-profile
key), `triage_record_check`'s `close_loop` triage flag, and
`phase1_doc_one_shot_runner._v1_6_581_route_l1_fallback_top_module`.

The 63x8 matrix even SHIPS the accessor and exports it —
`tests/matrix_63x8/flowref.py: def closed_loop(step_id)`, listed in `__all__` —
and no dimension module and no test calls it. The capability was built and left
unwired, which is the same shape as the four PPA programs the flow references
zero times.

CONSEQUENCE: a `fallback_to:` naming a step that does not exist would pass every
gate in this repository. The convergence edges the flow's whole close-loop story
rests on were, as a class, unfalsifiable. A `closed_loop` nobody can redden is
decoration — the same rule the mutation ledger applies to gates, applied to
edges.

WHAT AN EDGE HAS TO BE, AND EVERY CLAUSE WAS MEASURED BEFORE IT WAS ASSERTED
============================================================================
Five predicates. Each was run against all 19 shipped declarations FIRST; the
counts are stated so a future reader can tell an invariant from a preference.

  CL-NO-FALLBACK          `closed_loop` with no `fallback_to`.        0 of 19
  CL-NO-TRIGGER           no `trigger`, or an empty one.              0 of 19
  CL-FALLBACK-UNRESOLVED  `fallback_to` names an undeclared step.     0 of 19
  CL-NOT-A-LOOP           the edge does not close a loop.             0 of 19
  CL-NO-GATE              the declaring step has no gate, so nothing
                          can ever produce the verdict the trigger
                          names and the edge can never be taken.      0 of 19

CL-NOT-A-LOOP IS THE WEAKER OF TWO CANDIDATES, AND DELIBERATELY SO
------------------------------------------------------------------
The obvious rule — "`fallback_to` must be a transitive `blocks_on` ANCESTOR" —
was measured and REJECTED: it reddens two healthy cells on main. Steps 23 and 31
both fall back FORWARD to 32, the ECO aggregator, and step 32 `blocks_on` 23 and
31, so those edges are legitimate hand-offs, not defects:

    fallback is NOT an ancestor and NOT self -> [('23','32'), ('31','32')]

What survives contact with the corpus is the structural property that a LOOP
EDGE MUST CLOSE A LOOP: `fallback_to` is the step itself, OR a transitive
`blocks_on` ancestor of it (go back), OR a step that transitively `blocks_on` it
(hand forward to something that waits on you). All three re-enter the step. That
is 19 of 19 on main with zero exceptions and it is derivation-free.

RAW IDS, NOT NORMALISED ONES
----------------------------
`flow_compliance_check` keys its cascade graph on the RAW yaml id, so an edge
whose id is the string `"9"` where the step declares the int `9` resolves to
NOTHING there while looking fine to a reader. Dimension 5 learned this for
`blocks_on` (`D5-EDGE-UNRESOLVED`) and the same trap applies to `fallback_to`;
this check reports the type mismatch by name rather than normalising it away.

A ZERO DENOMINATOR IS A REFUSAL, NOT A PASS
===========================================
If the flow declares no `closed_loop` at all — or the document cannot be read —
this program exits 2 and says so. "I could not read it" and "I read it and it
was clean" must never produce the same verdict; a check that reports green over
an empty denominator is the failure this repository has hit in three separate
systems. The denominator is printed on every run, pass or fail.

WHAT THIS CHECK DOES NOT DO — stated so a reviewer does not have to find it
==========================================================================
  * It does not verify that a runner ACTUALLY re-executes the fallback step. No
    runner reads `closed_loop` today; making one do so is a separate change and
    a larger one. This check makes the DECLARATION honest, which is the
    precondition for wiring it, and it will redden the day a declaration stops
    being honest.
  * It does not judge whether the trigger TEXT describes something the gate can
    detect. That is a semantic question about prose; CL-NO-GATE bounds it from
    below by requiring that a verdict can exist at all.
  * It does not require the fallback target to be re-runnable in isolation.

chip-AGNOSTIC: it reads the flow document's own structure. No design, foundry,
process, chip token or SKU appears anywhere in this file.

Exit codes: 0 = every declared edge resolves, 1 = a finding, 2 = the question
could not be put (unreadable flow, or zero declarations) or a bad argument.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082/#1470

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a hard dep of the plugin
    yaml = None  # type: ignore

TOOL = "closed_loop_edge_check"
VERSION = "1.0.0"

RC_OK, RC_FINDINGS, RC_ARG = 0, 1, 2
#: The refusal tier: unreadable flow, or a denominator of zero.
RC_NOT_MEASURED = 2

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
FLOW_REL = Path("flow") / "phase1_phase2_phase3.yaml"
#: The same override the eight dimension modules honour, so a falsifiability
#: replay that repoints the substrate at a mutant is read by this check too.
FLOW_YAML_ENV = "VIBE_IC_MATRIX_FLOW_YAML"


def flow_yaml_path() -> Path:
    import os
    override = os.environ.get(FLOW_YAML_ENV)
    return Path(override) if override else PLUGIN_ROOT / FLOW_REL


def load_steps(path: Path) -> List[Dict[str, Any]]:
    if yaml is None:  # pragma: no cover - defensive
        raise RuntimeError("PyYAML is required to read the flow")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path} does not parse to a mapping")
    steps = doc.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"{path} declares no `steps` list")
    return [s for s in steps if isinstance(s, dict) and "id" in s]


def _norm(v: Any) -> str:
    return str(v).strip()


def build_index(steps: List[Dict[str, Any]]
                ) -> Tuple[Set[Any], Dict[str, Dict[str, Any]]]:
    """``(raw ids, normalised id -> step)``.

    The RAW set is kept because `flow_compliance_check` keys on it; see the
    module docstring.
    """
    raw: Set[Any] = set()
    by: Dict[str, Dict[str, Any]] = {}
    for s in steps:
        try:
            raw.add(s["id"])
        except TypeError:  # pragma: no cover - unhashable id
            pass
        by[_norm(s["id"])] = s
    return raw, by


def ancestors(sid: str, by: Dict[str, Dict[str, Any]]) -> Set[str]:
    """Transitive `blocks_on` closure of *sid*. Cycle-safe."""
    out: Set[str] = set()
    stack = [sid]
    while stack:
        cur = stack.pop()
        for p in (by.get(cur, {}).get("blocks_on") or []):
            p = _norm(p)
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def closes_a_loop(sid: str, fb: str, by: Dict[str, Dict[str, Any]]) -> bool:
    """The surviving invariant. See the module docstring for what was rejected."""
    return fb == sid or fb in ancestors(sid, by) or sid in ancestors(fb, by)


#: Keys that STRUCTURE a gate rather than being a clause themselves. Everything
#: else at clause position is a clause. MEASURED over the shipped flow: the five
#: clause keys in use are `program_exit_zero`, `advisory_program_exit_zero`,
#: `optional_program_exit_zero`, `files_exist` and `json_field_true`; enumerating
#: THOSE instead would silently stop counting a sixth the day one is added, so
#: the container list is the closed set and the clause set is the open one.
_GATE_CONTAINERS = ("all_of", "any_of")

#: Clause kinds that can BLOCK. Disclosed in the report, never gated on: a step
#: whose gate is advisory-only is dimension 6's `D6-ADVISORY-ONLY-GATE`, not
#: this check's finding, and duplicating it here would be a second opinion on a
#: question that already has an owner.
_BLOCKING_CLAUSES = ("program_exit_zero", "files_exist", "json_field_true",
                     "optional_program_exit_zero")


def gate_clause_kinds(step: Dict[str, Any]) -> List[str]:
    """Every clause key the step's gate declares, flattened.

    The walker is recursive because `all_of` may nest, and it matches the
    grammar `flowref.gate_clauses` walks — a BARE clause is legal at the top of
    a gate (step 13 ships `gate: {program_exit_zero: "..."}` with no `all_of`),
    and a first draft of this check that only accepted list values reported step
    13 as gate-less. That was the CHECK being wrong, not the flow, and it is
    recorded here because the same shape will tempt the next author.
    """
    out: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _GATE_CONTAINERS:
                    walk(v)
                elif v not in (None, "", [], {}, False):
                    out.append(str(k))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(step.get("gate") if isinstance(step.get("gate"), dict) else None)
    return out


def has_gate(step: Dict[str, Any]) -> bool:
    """True when the step's gate declares at least one clause of any kind."""
    return bool(gate_clause_kinds(step))


def problems_for_step(step: Dict[str, Any], raw_ids: Set[Any],
                      by: Dict[str, Dict[str, Any]]) -> List[str]:
    """Every closed-loop defect of one step, measured. Empty == healthy.

    PURE given its inputs, and the single implementation: dimension 5 of the
    63x8 matrix calls THIS function rather than restating the predicate, so the
    two can never drift apart.
    """
    cl = step.get("closed_loop")
    if not isinstance(cl, dict):
        return []
    sid = _norm(step["id"])
    problems: List[str] = []

    if "fallback_to" not in cl or cl.get("fallback_to") in (None, ""):
        problems.append(
            f"CL-NO-FALLBACK: step {sid} declares closed_loop with no "
            f"`fallback_to` (keys: {sorted(cl)}); there is no edge to take")
        fb_raw = None
    else:
        fb_raw = cl["fallback_to"]

    trigger = cl.get("trigger")
    if not isinstance(trigger, str) or not trigger.strip():
        problems.append(
            f"CL-NO-TRIGGER: step {sid} declares closed_loop with trigger="
            f"{trigger!r}; nothing states the condition under which the edge is "
            f"taken, so no reader and no runner can decide to take it")

    if fb_raw is not None:
        fb = _norm(fb_raw)
        if fb_raw not in raw_ids:
            hint = (
                f" — a step {fb!r} exists but is declared as "
                f"{type(by[fb]['id']).__name__}, not {type(fb_raw).__name__}; "
                f"flow_compliance_check keys the cascade graph on the RAW id, "
                f"so this edge resolves to nothing there"
                if fb in by else
                " — no step with that id is declared at all")
            problems.append(
                f"CL-FALLBACK-UNRESOLVED: step {sid} closed_loop.fallback_to "
                f"{fb_raw!r} ({type(fb_raw).__name__}){hint}")
        elif not closes_a_loop(sid, fb, by):
            problems.append(
                f"CL-NOT-A-LOOP: step {sid} closed_loop.fallback_to {fb!r} is "
                f"neither the step itself, nor a transitive blocks_on ancestor "
                f"of it, nor a step that transitively blocks_on it — taking the "
                f"edge never re-enters {sid}, so it is not a loop")

        if not has_gate(step):
            problems.append(
                f"CL-NO-GATE: step {sid} declares a closed_loop to {fb!r} but "
                f"no gate with any clause, so no verdict this flow computes can "
                f"ever satisfy the trigger and the edge can never be taken")

    return problems


def evaluate(path: Path) -> Tuple[str, Dict[str, Any]]:
    rep: Dict[str, Any] = {"program": TOOL, "version": VERSION,
                           "flow": str(path), "findings": []}
    try:
        steps = load_steps(path)
    except (OSError, ValueError, RuntimeError) as exc:
        rep["verdict"] = "NOT_MEASURED"
        rep["missing_authority"] = f"the flow document could not be read: {exc}"
        rep["declarations"] = 0
        return "NOT_MEASURED", rep

    raw_ids, by = build_index(steps)
    rep["steps_read"] = len(steps)
    declaring = [s for s in steps if isinstance(s.get("closed_loop"), dict)]
    rep["declarations"] = len(declaring)
    rep["declaring_steps"] = [_norm(s["id"]) for s in declaring]

    if not declaring:
        rep["verdict"] = "NOT_MEASURED"
        rep["missing_authority"] = (
            f"the flow declares {len(steps)} step(s) and ZERO `closed_loop` "
            f"blocks, so this check has an empty denominator; a green over "
            f"nothing is not a measurement")
        return "NOT_MEASURED", rep

    edges = []
    for s in declaring:
        cl = s["closed_loop"]
        sid = _norm(s["id"])
        probs = problems_for_step(s, raw_ids, by)
        kinds = gate_clause_kinds(s)
        edges.append({"step": sid, "fallback_to": cl.get("fallback_to"),
                      "trigger": cl.get("trigger"),
                      "gate_clause_kinds": kinds,
                      # DISCLOSED, not gated: see _BLOCKING_CLAUSES.
                      "gate_can_block": any(k in _BLOCKING_CLAUSES
                                            for k in kinds),
                      "problems": probs})
        for p in probs:
            rep["findings"].append({"severity": "ERROR", "step": sid,
                                    "rule": p.split(":", 1)[0],
                                    "message": p})
    rep["edges"] = edges
    rep["verdict"] = "FAIL" if rep["findings"] else "PASS"
    return rep["verdict"], rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--flow", default=None,
                    help="the flow yaml (default: the plugin's canonical flow, "
                         f"or ${FLOW_YAML_ENV} when set)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    path = Path(args.flow) if args.flow else flow_yaml_path()
    verdict, rep = evaluate(path)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out,
                          json.dumps(rep, indent=2, ensure_ascii=False) + "\n")

    n = rep.get("declarations", 0)
    if verdict == "NOT_MEASURED":
        print(f"{TOOL}: {rep['flow']}")
        print(f"NOT_MEASURED: {rep['missing_authority']}")
        return RC_NOT_MEASURED

    scope = (f"checked {n} declared closed_loop edge(s) over "
             f"{rep['steps_read']} step(s)")
    if verdict == "FAIL":
        print(f"[FAIL] {TOOL}: {scope}")
        for f in rep["findings"]:
            print(f"  - {f['message']}")
        return RC_FINDINGS

    print(f"[PASS] {TOOL}: {scope}; every edge resolves to a declared step, "
          f"closes a loop, carries a trigger, and leaves a step whose gate can "
          f"produce a verdict. Edges: "
          + ", ".join(f"{e['step']}->{e['fallback_to']}" for e in rep["edges"]))
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
