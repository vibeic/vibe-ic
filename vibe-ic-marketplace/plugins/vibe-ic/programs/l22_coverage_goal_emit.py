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
    source      the input document, PROJECT-RELATIVE
    line        the line in that document

`source` must be relative, and was not. `framed_hits` returns
`str(path)` off a glob of the resolved project dir, so the emitted goal
carried an absolute path — `/…/<checkout>/phase1/input_doc/<file>` — into
an L document. That is right for a gate REPORT, which is a run record
whose job is to say where the run happened, and wrong for an L document,
which is a design artefact the flow reads back, diffs across runs and
compares between designs: the same design emitted from two checkouts
produced two different L22s and neither was comparable to the other.
Measured across the tracked corpus, 2550 of 2554 L documents already use
a project-relative provenance path; this emitter added one absolute path
per design the moment it ran. Relativisation (and the policy for an
input that lives OUTSIDE the project, which is recorded as an explicit
`<outside-project>/<basename>` marker rather than dropped or emitted
absolute) lives in `l_doc_consumer_contract.project_relative_source`,
next to the code that produced the absolute path. `line` is untouched: a
line number is a property of the file, not of the machine.

`signoff_gate` is load-bearing and defaults to True. A design may state
a measurable target and explicitly mark it informational ("資訊性",
"非 sign-off gate"). Emitting such a target as a blocking one would
invent a sign-off condition the design never asked for; dropping it
would lose a stated requirement. So it is emitted WITH the qualifier
recorded, and the qualifier phrase is kept in `signoff_qualifier` so a
human can audit the call.

How that contract was violated, and by what
------------------------------------------------------------------
This module borrows the consumer gate's detection, and the gate's own
policy is to DISCARD a hit whose line the document disclaims — right
for a gate ("is my layer missing a requirement?"), wrong for an emitter
("what did the design declare?"). Inheriting it silently dropped the
informational goal instead of emitting it non-blocking. MEASURED:
16 of 21 probed qualifier values emitted NOTHING at all, and the 5 that
survived were the WEAKEST disclaimers — the ones this module's private
list knew and the shared one did not. The strongest, most explicit
disclaimers ("informational", "not a sign-off gate", "資訊性") were the
ones that vanished. A consumer reading `coverage_goals[]` saw a design
with no coverage goal whatsoever.

Two corrections, both keeping the predicate shared:
  * detection opts in via `framed_hits(..., include_non_normative=True)`,
    so the disclaimed hit is RETAINED and carries the line-scoped verdict;
  * the qualifier vocabulary moved OUT of this file into
    `l_doc_consumer_contract.signoff_qualifier()`. The private copy had
    drifted from the shared one in both directions.

The qualifier is scoped to the hit's OWN LINE, never to the ±160-char
context. MEASURED with the context scope: a table row explicitly marked
`sign-off` was emitted `signoff_gate: False` because its NEIGHBOUR said
`advisory` — silently downgrading a real sign-off condition. A document
disclaims the row it is written on; proximity is not membership.

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
    project_relative_source,
    signoff_qualifier,
)
# THE L-document write chokepoint — records the producing release on the L22
# this emitter rewrites.
import l_doc_generator_stamp as _stamp  # noqa: E402

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

# The phrases by which a design marks a stated target as NOT a sign-off
# gate live in `l_doc_consumer_contract.signoff_qualifier()`, NOT here.
# A private copy lived in this file and drifted from the shared one in
# both directions — see the module docstring.

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

    # include_non_normative=True — an EMITTER must not inherit a GATE's
    # discard policy. A target the design declares and marks informational
    # is still declared; dropping it makes this layer read as having no
    # coverage goal at all.
    hits = framed_hits(input_doc_texts(project), gate._COVERAGE_TARGET_RE,
                       include_non_normative=True)

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
        # OWN LINE, never the ±160-char context: a document disclaims the
        # row it is written on. `line_text` is present because this call
        # opted into include_non_normative.
        qualifier = signoff_qualifier(h.get("line_text") or "")
        # PROJECT-RELATIVE, never absolute. `framed_hits` hands back
        # `str(path)` — right for a gate REPORT (a run record says where the
        # run happened), wrong here: this value is written INTO an L
        # document, a design artefact the flow reads back and diffs. An
        # absolute path makes the same design emit a different L22 from
        # every checkout. `line` is untouched — it is a property of the
        # file's contents, not of the machine. See
        # `l_doc_consumer_contract.project_relative_source`.
        src, src_outside = project_relative_source(h.get("source"), project)
        goal = {
            "name": name,
            "target_pct": pct,
            "signoff_gate": qualifier is None,
            "signoff_qualifier": qualifier,
            "source": src,
            "line": h.get("line"),
            "evidence": text[:200],
            "extraction_strategy": TOOL,
        }
        if src_outside:
            # Present ONLY when it fires. An always-present `false` would
            # change the shape of every goal ever emitted to say nothing;
            # this key exists to be conspicuous on the rare run whose input
            # lives outside the project, and `source` already carries the
            # `<outside-project>/` marker for a human reader.
            goal["source_outside_project"] = True
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
        _stamp.dump(l22_path, doc)
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


def _describe(goal: Dict[str, Any]) -> str:
    """One reviewable line per emitted goal.

    A non-blocking goal NAMES the phrase the design used, so a reader can
    see WHY it is non-blocking rather than trusting the flag.
    """
    head = f"{goal['name']}>={goal['target_pct']}%"
    if goal.get("signoff_gate"):
        return head
    qual = goal.get("signoff_qualifier")
    return f"{head} (NOT a sign-off gate — the design says {qual!r})"


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
        detail = ", ".join(_describe(g) for g in rep["emitted"])
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
