#!/usr/bin/env python3
"""
l22_verification_plan_measurable_check.py — SEMANTIC gate for
L22_VERIFICATION_PLAN (batch layergate-7).

THE DEFECT
==========
L22 is squarely in the checks-that-lie family. OBSERVED in 24/24
sampled runs: ``extraction_status = NOT_YET_EXTRACTED``,
``coverage_goals = []``, ``formal_properties = []`` — while the SAME
file carries a five-item prose ``verification_categories_derived_from_spec``
list and ``verification_plan_present: "implicit"``. Those two fields
are shaped to read as POPULATED to any non-empty heuristic while
carrying zero enforceable targets. An asserted "implicit" verification
plan with no measurable target cannot be falsified by anything
downstream.

L22 HAS NO CONSUMER IN THE SHIPPING FLOW AT ALL (#509). The only program
that reads it is ``programs/phase2_scaffold_gen.py``, which greps L22 for
text and would append a truncated ``L22: <120 chars>`` line into
``compliance_vectors.txt`` — and that program is a CONTRACT ORACLE, not a
flow step: no runner and no step of ``flow/phase1_phase2_phase3.yaml``
calls it, at any version. Earlier wording here called it "the only
consumer today", which read as a live reader and it is not one.

That makes the case for this gate STRONGER, not weaker. Truncated prose
would not be a target even if something did consume it, no coverage gate
reads L22's goals, and a layer whose every reader is hypothetical is a
layer nothing downstream can falsify — which is precisely why the
measurable-target requirement has to be enforced HERE, at the layer,
rather than deferred to a consumer that would catch it later.

CONSUMER CONTRACT
=================
A coverage gate compares a MEASURED number against a target. So the
contract is: every coverage goal must carry a name and a numeric target
a downstream gate can compare against; every formal property must carry
a checkable statement. Prose is not a target.

BLOCKS or ADVISES?
==================
MIXED, and each half is justified separately:

  F1 UNCOMPARABLE_COVERAGE_GOAL ........................... BLOCKS
      A ``coverage_goals[]`` entry exists but carries no numeric target
      (or no name). A goal a coverage gate cannot compare against is a
      goal that always passes. Self-contained inside L22, so blocking
      costs nothing but a fabricated PASS.

  F2 TARGET_OUTSIDE_CONSUMING_LAYER ....................... BLOCKS
      The design's OWN inputs state a measurable verification target —
      a percentage next to coverage vocabulary, with requirement
      framing ("goal", "must", "at least", ">=") in the surrounding
      window — but L22, the layer a coverage gate would consume, carries
      no numeric goal. This is the L21 defect verbatim, one layer over.
      It BLOCKS because the L21 post-mortem's third compounding fault
      was that the gate's verdict was FAIL and the flow continued
      anyway. A layer gate that fails must be able to stop the flow.

  F3 UNFALSIFIABLE_PLAN_ASSERTION ......................... ADVISES
      ``verification_plan_present`` is truthy (notably the literal
      string ``"implicit"``) and/or a prose category list is present,
      while ``coverage_goals[]`` and ``formal_properties[]`` are both
      empty AND the design's own inputs state no numeric target. The
      layer is asserting a plan it cannot back — but the design never
      asked for a measurable one, and the layer honestly self-reports
      ``NOT_YET_EXTRACTED``. Blocking here would stop 24/24 sampled
      runs for a shape the design's inputs never contradicted, so this
      half ADVISES and names the exact field pair that reads as
      populated while carrying nothing enforceable.

REQUIREMENT FRAMING IS LOAD-BEARING
===================================
A bare "90% coverage" in an input doc is often a STATUS report about
somebody else's achieved coverage, not a requirement for this design.
F2 therefore requires a requirement word within a +/-160-char window,
exactly as ``l8_clock_domains_typed_check._is_real_clock_freq`` requires
a clock keyword near a frequency literal. Without this the gate would
read "the upstream project already hit over 90% coverage" as a target.

DERIVED, NOT RECOGNISED
=======================
Triggers read only the design's own input docs and its own sibling
L-docs. No design name, no PDK name, no vendor part number, no
design-specific signal literal.

SINGLE DETERMINISTIC TRACK
==========================
No AI second track — see l_doc_consumer_contract.py for why claiming
one that produces nothing is worse than claiming none.

Usage:
    python3 l22_verification_plan_measurable_check.py <project_dir> [--json PATH]

Exit codes:
    0 = PASS (or ADVISE-only findings)
    1 = FAIL (F1 and/or F2) — BLOCKS
    2 = SKIP (no L22, or L22 not applicable to this IC class)

Honors waiver ``l22_verification_targets_intentionally_qualitative``
(>=40 chars).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l_doc_consumer_contract import (  # noqa: E402
    applicability_of,
    framed_hits,
    input_doc_texts,
    is_extraction_claimed,
    l_doc_fields,
    load_l_doc,
    nonempty_str,
    numeric_target,
    sibling_l_doc_texts,
    waiver_rationale,
    write_report,
)

GATE = "l22_verification_plan_measurable_check"
WAIVER_ID = "l22_verification_targets_intentionally_qualitative"

# A percentage adjacent to coverage vocabulary, in either order.
# framed_hits() runs this against WHITESPACE-NORMALISED text, so the gap
# class is `[^.]` rather than `[^.\n]`: real specs hard-wrap their
# requirements ("...verify the core with 100%\ncoverage.") and a
# newline-excluding gap silently skips exactly the sentence that matters.
# Requirement framing is applied on top by framed_hits().
_COVERAGE_TARGET_RE = re.compile(
    r"(?:\d{1,3}(?:\.\d+)?\s*%[^.]{0,60}?\b(?:coverage|covered|"
    r"code\s+coverage|functional\s+coverage|branch\s+coverage|"
    r"toggle\s+coverage|statement\s+coverage|assertion\s+coverage|"
    r"fault\s+coverage)\b"
    r"|\b(?:coverage|code\s+coverage|functional\s+coverage|"
    r"branch\s+coverage|toggle\s+coverage|statement\s+coverage|"
    r"assertion\s+coverage|fault\s+coverage)\b[^.]{0,60}?"
    r"\d{1,3}(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)

# Sibling layers that legitimately carry a verification target upstream
# of L22. If the target lives here and not in L22, that IS the defect.
_SIBLING_CODES = ("L16", "L24", "L10")

_GOAL_KEYS = ("coverage_goals", "coverage_targets", "goals",
              "coverage_plan")
_FORMAL_KEYS = ("formal_properties", "properties", "assertions",
                "formal_props")
_REGRESSION_KEYS = ("regression_matrix", "regression", "regressions")
_PRESENT_KEYS = ("verification_plan_present", "vplan_present",
                 "verification_plan")
_PROSE_KEYS = ("verification_categories_derived_from_spec",
               "verification_categories", "verification_items",
               "verification_plan_summary", "notes")

_GOAL_NAME_KEYS = ("name", "group", "metric", "goal", "id", "feature")
_GOAL_TARGET_KEYS = ("target_pct", "target", "goal_pct", "threshold",
                     "min_pct", "percent", "pct", "value", "target_percent")

_PROP_TEXT_KEYS = ("property", "statement", "assertion", "expression",
                   "sva", "text", "description", "formula")
_PROP_NAME_KEYS = ("name", "id", "label")


def _get(fields: dict, keys) -> Any:
    for k in keys:
        if k in fields:
            return fields[k]
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _truthy_assertion(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, str):
        t = value.strip().lower()
        if not t:
            return False
        for neg in ("n/a", "na", "none", "not ", "no ", "absent", "false",
                    "unknown", "tbd", "deferred"):
            if t.startswith(neg):
                return False
        return True
    return value is not None and value is not False


def _goal_missing_fields(entry: Any) -> List[str]:
    """What this goal lacks for a coverage gate to compare against it."""
    if not isinstance(entry, dict):
        # A bare string goal ("100% line coverage") is prose; a coverage
        # gate cannot compare a measured number against a sentence.
        return ["name", "numeric_target"]
    missing: List[str] = []
    if not any(nonempty_str(entry.get(k)) for k in _GOAL_NAME_KEYS):
        missing.append("name")
    tgt = None
    for k in _GOAL_TARGET_KEYS:
        if k in entry:
            tgt = numeric_target(entry[k])
            if tgt is not None:
                break
    if tgt is None:
        missing.append("numeric_target")
    return missing


def _prop_missing_fields(entry: Any) -> List[str]:
    """What this formal property lacks to be a checkable statement."""
    if isinstance(entry, str):
        return [] if len(entry.strip()) >= 12 else ["statement"]
    if not isinstance(entry, dict):
        return ["name", "statement"]
    missing: List[str] = []
    if not any(nonempty_str(entry.get(k)) for k in _PROP_NAME_KEYS):
        missing.append("name")
    if not any(nonempty_str(entry.get(k), 12) for k in _PROP_TEXT_KEYS):
        missing.append("statement")
    return missing


def inspect(project: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "gate": GATE,
        "project": str(project),
        "verdict": "SKIP",
        "blocking_findings": [],
        "advisory_findings": [],
        "evidence": {},
    }

    l22_path, l22 = load_l_doc(project, "L22")
    if l22_path is None:
        result["reason"] = "no L22 doc in phase1/generated_docs"
        return result
    result["evidence"]["l22_path"] = str(l22_path)

    if l22 is None:
        result["verdict"] = "FAIL"
        result["blocking_findings"].append({
            "id": "UNPARSEABLE_LAYER",
            "detail": f"{l22_path} is not parseable JSON; no coverage "
                      f"gate can read a target out of it.",
        })
        return result

    applicability = applicability_of(l22)
    result["evidence"]["applicability"] = applicability
    if applicability in ("NOT_APPLICABLE", "N/A", "NA"):
        result["reason"] = (f"L22 applicability={applicability} for "
                            f"ic_class={l22.get('ic_class')}")
        return result

    fields = l_doc_fields(l22)
    goals = _as_list(_get(fields, _GOAL_KEYS))
    props = _as_list(_get(fields, _FORMAL_KEYS))
    regression = _get(fields, _REGRESSION_KEYS)
    present = _get(fields, _PRESENT_KEYS)

    prose_items = 0
    for k in _PROSE_KEYS:
        v = fields.get(k)
        if isinstance(v, list):
            prose_items += len(v)
        elif nonempty_str(v, 12):
            prose_items += 1

    measurable_goals = [g for g in goals if not _goal_missing_fields(g)]
    result["evidence"]["coverage_goal_count"] = len(goals)
    result["evidence"]["measurable_goal_count"] = len(measurable_goals)
    result["evidence"]["formal_property_count"] = len(props)
    result["evidence"]["prose_item_count"] = prose_items
    result["evidence"]["verification_plan_present"] = present
    result["evidence"]["regression_matrix_populated"] = bool(regression)

    # ── F1 UNCOMPARABLE_COVERAGE_GOAL (BLOCKS) ───────────────────────
    bad_goals: List[str] = []
    for i, g in enumerate(goals):
        miss = _goal_missing_fields(g)
        if miss:
            label = None
            if isinstance(g, dict):
                for k in _GOAL_NAME_KEYS:
                    if nonempty_str(g.get(k)):
                        label = str(g[k])
                        break
            bad_goals.append(f"{label or f'coverage_goals[{i}]'}: "
                             f"missing {','.join(miss)}")
    if bad_goals:
        result["blocking_findings"].append({
            "id": "UNCOMPARABLE_COVERAGE_GOAL",
            "detail": (
                f"{len(bad_goals)}/{len(goals)} coverage_goals[] entries "
                f"carry no numeric target a coverage gate can compare a "
                f"measured number against (or no name to key it by). A "
                f"goal that cannot be compared always passes. "
                f"Examples: {'; '.join(bad_goals[:5])}"),
        })

    bad_props: List[str] = []
    for i, p in enumerate(props):
        miss = _prop_missing_fields(p)
        if miss:
            bad_props.append(f"formal_properties[{i}]: "
                             f"missing {','.join(miss)}")
    if bad_props:
        result["blocking_findings"].append({
            "id": "UNCHECKABLE_FORMAL_PROPERTY",
            "detail": (
                f"{len(bad_props)}/{len(props)} formal_properties[] "
                f"entries carry no checkable statement a formal tool "
                f"could prove or refute. "
                f"Examples: {'; '.join(bad_props[:5])}"),
        })

    # ── F2 TARGET_OUTSIDE_CONSUMING_LAYER (BLOCKS) ───────────────────
    doc_hits = framed_hits(input_doc_texts(project), _COVERAGE_TARGET_RE)
    sib_hits = framed_hits(sibling_l_doc_texts(project, _SIBLING_CODES),
                           _COVERAGE_TARGET_RE)
    result["evidence"]["coverage_target_hits_input_docs"] = len(doc_hits)
    result["evidence"]["coverage_target_hits_sibling_l_docs"] = len(sib_hits)

    if (doc_hits or sib_hits) and not measurable_goals:
        result["blocking_findings"].append({
            "id": "TARGET_OUTSIDE_CONSUMING_LAYER",
            "detail": (
                f"The design's own inputs state a MEASURABLE "
                f"verification target in {len(doc_hits)} input-doc "
                f"location(s) and {len(sib_hits)} sibling-L-doc "
                f"location(s), but L22 — the layer a coverage gate would "
                f"consume — carries {len(measurable_goals)} measurable "
                f"coverage_goals[] (of {len(goals)} total). The target "
                f"is present somewhere and absent from the layer that "
                f"would consume it: nothing downstream could compare a "
                f"measured number against it."),
            "evidence": (doc_hits + sib_hits)[:4],
        })

    # ── F3 UNFALSIFIABLE_PLAN_ASSERTION (ADVISES) ────────────────────
    asserts_plan = (_truthy_assertion(present) or prose_items > 0
                    or is_extraction_claimed(l22))
    if asserts_plan and not measurable_goals and not props \
            and not doc_hits and not sib_hits:
        result["advisory_findings"].append({
            "id": "UNFALSIFIABLE_PLAN_ASSERTION",
            "severity": "ADVISE",
            "detail": (
                f"L22 asserts a verification plan "
                f"(verification_plan_present={present!r}, "
                f"{prose_items} prose category/item(s), "
                f"extraction_claimed={is_extraction_claimed(l22)}) while "
                f"coverage_goals[] and formal_properties[] are both "
                f"EMPTY and regression_matrix is "
                f"{'populated' if regression else 'empty'}. Those fields "
                f"read as POPULATED to any non-empty heuristic while "
                f"carrying zero enforceable targets — nothing downstream "
                f"can falsify this plan. ADVISE not BLOCK: the design's "
                f"own inputs state no numeric verification target, so "
                f"the layer contradicts no requirement."),
        })

    if result["blocking_findings"]:
        result["verdict"] = "FAIL"
    elif result["advisory_findings"]:
        result["verdict"] = "PASS_WITH_ADVISORY"
    elif measurable_goals or props:
        result["verdict"] = "PASS"
    else:
        result["verdict"] = "SKIP"
        result["reason"] = ("L22 asserts no plan and the design's own "
                            "inputs state no measurable target")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[1]
                                 if __doc__ else "")
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None, metavar="PATH")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE}: {project} is not a directory")
        return 2

    result = inspect(project)

    waiver = waiver_rationale(project, WAIVER_ID)
    if waiver and result["verdict"] == "FAIL":
        result["verdict"] = "WAIVED"
        result["waiver"] = waiver

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2,
                                              ensure_ascii=False))
    write_report(project, GATE, result)

    for f in result["advisory_findings"]:
        print(f"[ADVISE] {GATE}: {f['id']} — {f['detail']}")

    verdict = result["verdict"]
    if verdict == "SKIP":
        print(f"[SKIP] {GATE}: {result.get('reason', 'not applicable')}")
        return 2
    if verdict == "WAIVED":
        print(f"[SKIP] {GATE}: waived via {WAIVER_ID} — {result['waiver'][:90]}")
        return 2
    if verdict == "FAIL":
        for f in result["blocking_findings"]:
            print(f"[FAIL] {GATE}: {f['id']} — {f['detail']}")
        return 1
    print(f"[PASS] {GATE}: "
          f"{result['evidence'].get('measurable_goal_count', 0)} coverage "
          f"goal(s) with a comparable numeric target, "
          f"{result['evidence'].get('formal_property_count', 0)} formal "
          f"property/properties")
    return 0


if __name__ == "__main__":
    sys.exit(main())
