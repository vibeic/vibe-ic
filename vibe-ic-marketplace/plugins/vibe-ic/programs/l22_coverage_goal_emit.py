#!/usr/bin/env python3
"""l22_coverage_goal_emit.py — lift measurable coverage targets out of the
design's own input docs and into L22, the layer that CONSUMES them.

VERDICT SEMANTICS: **REPAIRS** (exit 0 unless L22 is unreadable).
This is not a gate. It is the emitter whose absence
`l22_verification_plan_measurable_check` reports as
TARGET_OUTSIDE_CONSUMING_LAYER.

The measured defect
------------------------------------------------------------------
Measured on a real run (spm, plugin v1.6.1, phase1 doc mode):

    L22_VERIFICATION_PLAN.json : coverage_goals = []   (0 of 0 measurable)
                                 prose_item_count = 6
                                 verification_plan_present = "implicit"

    input doc L7, line 45      : "Toggle / branch coverage(資訊性) | ≥ 95%"

The target IS stated by the design, and the gate's own F2 check FINDS
it — it reports `coverage_target_hits_input_docs: 1`. What is missing is
purely the write-back: nothing lifts the found target into L22, so
`coverage_goals[]` stays empty and no downstream coverage gate has a
number to compare a measurement against.

That the gate already locates the line is exactly what makes this
Bucket A: the detection is a solved, deterministic problem, and this
module reuses THE GATE'S OWN regex and framing helper rather than
reimplementing them. A separate predicate here could drift out of
agreement with the gate and produce goals the gate still rejects.

What is emitted, and what is NOT
------------------------------------------------------------------
For every framed hit (a percentage adjacent to coverage vocabulary,
with requirement framing within the same +/-160-char window the gate
uses) one goal is emitted carrying:

    name        the coverage vocabulary term that matched
    target_pct  the percentage, as a float a gate can compare against
    signoff_gate  whether the design says this target BLOCKS sign-off

`signoff_gate` is load-bearing and defaults to True. A design may state
a measurable target and explicitly mark it informational — the spm
input does exactly that ("資訊性", "非 sign-off gate"). Emitting such a
target as a blocking one would invent a sign-off condition the design
never asked for; dropping it would lose a stated requirement. So it is
emitted WITH the qualifier recorded, and the qualifier phrase is kept
in the evidence so a human can audit the call.

Refusals (never invent a target)
------------------------------------------------------------------
  * No framed hit  => nothing is emitted. The gate keeps FAILing if the
    design really did state a target somewhere this predicate cannot
    see; a fabricated goal would convert that into a false PASS.
  * A hit with no parseable percentage => skipped and reported.
  * An EXISTING coverage_goals[] entry is never modified or removed.
    Re-running is idempotent: a goal already present for the same
    (name, target_pct) is not duplicated.

chip-AGNOSTIC: no design name, PDK name or vendor literal. Keyed on
document vocabulary and structure only.

Usage:
    python3 l22_coverage_goal_emit.py <project_dir> [--json OUT] [--dry-run]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from l_doc_consumer_contract import (  # noqa: E402
    framed_hits,
    input_doc_texts,
)

TOOL = "l22_coverage_goal_emit"


def _gate_module():
    """Import the consumer gate so we can borrow ITS regex verbatim.

    Reusing the gate's own pattern is the point: an emitter with a
    private predicate can emit goals the gate does not accept, or miss
    targets the gate does find, and the disagreement surfaces as a
    FAIL nobody can act on."""
    path = _HERE / "l22_verification_plan_measurable_check.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        "l22_verification_plan_measurable_check", path)
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except Exception:
        return None
    return m


# The coverage vocabulary terms, longest-first, so `branch coverage`
# wins over the bare `coverage` when naming the emitted goal.
_VOCAB = (
    "code coverage", "functional coverage", "branch coverage",
    "toggle coverage", "statement coverage", "assertion coverage",
    "fault coverage", "coverage", "covered",
)
_RE_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")

# Phrases by which a design marks a stated target as NOT a sign-off gate.
# Document vocabulary, not a chip literal; both scripts appear in real
# vendor docs shipped to this flow.
_NON_SIGNOFF = (
    "non-signoff", "non sign-off", "not a sign-off", "not a signoff",
    "informational", "informative", "advisory", "for information",
    "非 sign-off", "非sign-off", "資訊性", "非签核", "仅供参考",
)

_L22_NAME = "L22_VERIFICATION_PLAN.json"
_GOAL_KEY = "coverage_goals"


def _metric_name(match_text: str) -> Optional[str]:
    low = match_text.lower()
    for term in _VOCAB:
        if term in low:
            return term
    return None


def _pct(match_text: str) -> Optional[float]:
    m = _RE_PCT.search(match_text)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 0.0 <= v <= 100.0 else None


def _is_signoff(context: str) -> bool:
    low = context.lower()
    return not any(q in low for q in _NON_SIGNOFF)


def _generated_docs(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def run(project: Path, dry_run: bool = False) -> Dict[str, Any]:
    gate = _gate_module()
    if gate is None or not hasattr(gate, "_COVERAGE_TARGET_RE"):
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": "consumer gate absent — refusing to emit against "
                          "a predicate it cannot check",
                "emitted_count": 0, "emitted": [], "skipped": []}

    l22_path = _generated_docs(project) / _L22_NAME
    if not l22_path.is_file():
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": f"{_L22_NAME} absent (phase1 has not run?)",
                "emitted_count": 0, "emitted": [], "skipped": []}
    try:
        doc = json.loads(l22_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"cannot parse {_L22_NAME}: {exc}",
                "emitted_count": 0, "emitted": [], "skipped": []}
    if not isinstance(doc, dict):
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"{_L22_NAME} is not an object",
                "emitted_count": 0, "emitted": [], "skipped": []}

    hits = framed_hits(input_doc_texts(project), gate._COVERAGE_TARGET_RE)

    # WHERE the goals must land. `l_doc_consumer_contract.l_doc_fields()`
    # merges the nested `fields` payload OVER the top level
    # (`merged.update(inner)`), so when a `fields` object exists it WINS.
    # Writing `coverage_goals` at the top level while `fields` carries its
    # own empty list is a silent no-op: the emitter reports success and the
    # gate still reads []. Measured exactly that way before this branch
    # existed. Write into the payload the consumer actually reads.
    payload = doc["fields"] if isinstance(doc.get("fields"), dict) else doc

    existing = payload.get(_GOAL_KEY)
    goals: List[Any] = list(existing) if isinstance(existing, list) else []
    have = {
        (str(g.get("name", "")).lower(), g.get("target_pct"))
        for g in goals if isinstance(g, dict)
    }

    emitted: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for h in hits:
        text = h.get("match") or ""
        ctx = h.get("context") or ""
        name = _metric_name(text) or _metric_name(ctx)
        pct = _pct(text)
        if pct is None:
            pct = _pct(ctx)
        if name is None or pct is None:
            skipped.append({"reason": "no parseable metric/percentage",
                            "match": text[:160]})
            continue
        key = (name.lower(), pct)
        if key in have:
            continue
        have.add(key)
        goal = {
            "name": name,
            "target_pct": pct,
            "signoff_gate": _is_signoff(ctx),
            "source": str(h.get("source") or ""),
            "line": h.get("line"),
            "evidence": text[:200],
            "extraction_strategy": TOOL,
        }
        goals.append(goal)
        emitted.append(goal)

    wrote = False
    if emitted and not dry_run:
        payload[_GOAL_KEY] = goals
        # The layer no longer merely ASSERTS a plan — it now carries
        # comparable targets, so the honest status is no longer
        # "NOT_YET_EXTRACTED".
        if doc.get("extraction_status") == "NOT_YET_EXTRACTED":
            doc["extraction_status"] = "EXTRACTED"
        l22_path.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        wrote = True

    return {
        "tool": TOOL,
        "status": "OK",
        "dry_run": dry_run,
        "framed_hits": len(hits),
        "pre_existing_goals": len(existing) if isinstance(existing, list) else 0,
        "emitted_count": len(emitted),
        "emitted": emitted,
        "skipped": skipped,
        "doc_written": str(l22_path) if wrote else None,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    rep = run(project, dry_run=args.dry_run)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    n = rep.get("emitted_count", 0)
    if rep.get("status") != "OK":
        print(f"{TOOL}: {rep.get('status')} — {rep.get('reason')}")
    elif n:
        detail = ", ".join(
            f"{g['name']}>={g['target_pct']}%"
            f"{'' if g['signoff_gate'] else ' (informational)'}"
            for g in rep["emitted"])
        print(f"{TOOL}: lifted {n} measurable coverage target(s) from the "
              f"design's own inputs into L22 — {detail}")
    else:
        print(f"{TOOL}: no measurable coverage target to lift "
              f"({rep.get('framed_hits', 0)} framed hit(s), "
              f"{rep.get('pre_existing_goals', 0)} goal(s) already present)")
    for s in rep.get("skipped", [])[:5]:
        print(f"  SKIPPED: {s['reason']}: {s['match']!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
