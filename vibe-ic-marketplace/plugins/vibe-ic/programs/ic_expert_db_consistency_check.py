#!/usr/bin/env python3
"""ic_expert_db_consistency_check.py — gate: the IC Expert DB stays an ADVISORY
knowledge layer that is CONSISTENT with (never contradicts) the deterministic
gate/program layer, and is blindness-clean.

The IC Expert DB feeds the general Vibe-IC authoring path with design-craft
knowledge. It must NOT:
  1. contain a benchmark/design IDENTIFIER (blindness — no `cvdp_*`, `Prob\\d+`,
     `circuit\\d+` design→solution association leaking into the author digest);
  2. assert an oracle-VALUE bound to a named design (e.g. "design X expects 0xF2");
  3. claim to BE / OVERRIDE a deterministic gate (a lesson is ADVICE, not a hard
     rule the flow enforces — it must never say "the gate must accept", "disable
     the check", "skip lint", "ignore the conformance gate", etc.);
  4. instruct sourcing a name/value from a hidden-scorer artifact (§4.05
     ORACLE-SOURCE ban, issue #139 adjudication 2026-07-14): the scorer-side
     `.env` (its TOPLEVEL / VERILOG_SOURCES variables), "harness metadata", or
     the golden `output.*` are the oracle — a lesson keyed on them is only
     actionable via a forbidden oracle read, so it can never be honest general
     experience. Lessons MAY still describe how a hidden checker BINDS/samples
     the design (craft about the observable contract); they may not name the
     oracle files/variables as an INPUT to the authoring decision.

Structural invariants also checked: the DB parses, every entry has ic_class +
non-empty lessons, and lesson_count matches. The OPTIONAL `related[]` cross-link
field (sibling ic_class names sharing a core craft — the lightweight concept
graph) must, when present, be a list of strings that each name an EXISTING
ic_class, with no self-reference and no duplicates (a dangling link would point
the author at knowledge that isn't there).

Run CLEAN on the shipped DB before merge (exit 0). chip-AGNOSTIC.

Usage: ic_expert_db_consistency_check.py [--db <path>] [--json OUT]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

_DEFAULT_DB = (Path(__file__).resolve().parent.parent
               / "agents" / "ic_expert_db" / "ic_expert_db.json")

# blindness: design identifiers that must never appear in an advisory lesson
_ID_RES = [
    re.compile(r"\bcvdp_[A-Za-z0-9_]+\b"),
    re.compile(r"\bProb\d{2,}\w*\b", re.I),
    re.compile(r"\bcircuit\d+\b", re.I),
]
# oracle-value-bound-to-a-named-design leak (a bare general constant is fine)
_ORACLE_RE = re.compile(
    r"\b(?:design|problem|benchmark|testbench|harness)\b[^.\n]{0,40}"
    r"\b(?:expects?|must\s+(?:output|equal|be)|golden)\b[^.\n]{0,20}\b0x[0-9A-Fa-f]+",
    re.I)
# a lesson trying to OVERRIDE the deterministic layer (advisory boundary)
_OVERRIDE_RE = re.compile(
    r"\b(?:disable|skip|bypass|ignore|suppress|waive|turn\s+off|override)\b"
    r"[^.\n]{0,30}\b(?:gate|lint|check|conformance|hygiene|synth|assertion|verific)",
    re.I)
# §4.05 ORACLE-SOURCE ban (issue #139 adjudication, 2026-07-14): a lesson may
# never key an authoring decision on a hidden-scorer artifact. History: a
# captured lesson literally advised "reconcile the top-module name to the
# harness TOPLEVEL/VERILOG_SOURCES from .env" — an instruction to read the
# oracle, waved through because no regex covered it. These tokens are the
# scorer-side file/variable names; none has a legitimate reason to appear in
# spec-alone design advice (the legal input-side counterpart is named
# `input.context` / "the prompt/task", which these patterns do not match).
_ORACLE_SOURCE_RES = [
    re.compile(r"\.env\b"),
    re.compile(r"\bVERILOG_SOURCES\b"),
    re.compile(r"\bharness\s+(?:metadata|TOPLEVEL)\b", re.I),
    re.compile(r"\boutput\.(?:context|response)\b", re.I),
]


def check(db_path: Path):
    findings = []
    try:
        db = json.loads(Path(db_path).read_text())
    except Exception as e:  # noqa: BLE001
        return {"pass": False, "findings": [f"DB does not parse: {e}"]}
    entries = db.get("entries")
    if not isinstance(entries, list) or not entries:
        return {"pass": False, "findings": ["DB has no entries[]"]}
    all_classes = {e.get("ic_class") for e in entries if e.get("ic_class")}
    total = 0
    for e in entries:
        cls = e.get("ic_class")
        lessons = e.get("lessons")
        if not cls or not isinstance(lessons, list) or not lessons:
            findings.append(f"entry missing ic_class/lessons: {str(e)[:60]}")
            continue
        if e.get("lesson_count") != len(lessons):
            findings.append(f"[{cls}] lesson_count {e.get('lesson_count')} != {len(lessons)}")
        rel = e.get("related")
        if rel is not None:
            if not isinstance(rel, list) or not all(isinstance(r, str) for r in rel):
                findings.append(f"[{cls}] related must be a list[str]")
            else:
                if cls in rel:
                    findings.append(f"[{cls}] related self-references its own ic_class")
                if len(set(rel)) != len(rel):
                    findings.append(f"[{cls}] related has duplicate links")
                for r in rel:
                    if r not in all_classes:
                        findings.append(f"[{cls}] related link '{r}' names no existing ic_class (dangling)")
        for les in lessons:
            total += 1
            for rx in _ID_RES:
                m = rx.search(les)
                if m:
                    findings.append(f"[{cls}] BLINDNESS: design-id '{m.group(0)}' in lesson")
            if _ORACLE_RE.search(les):
                findings.append(f"[{cls}] ORACLE-LEAK: named-design→value in lesson")
            if _OVERRIDE_RE.search(les):
                findings.append(f"[{cls}] OVERRIDE: lesson tries to disable/override a gate "
                                f"(advisory boundary)")
            for rx in _ORACLE_SOURCE_RES:
                m = rx.search(les)
                if m:
                    findings.append(f"[{cls}] ORACLE-SOURCE: lesson keys on the hidden-scorer "
                                    f"artifact '{m.group(0)}' (§4.05 ban — advice must be "
                                    f"actionable from the spec/input alone)")
                    break
    return {"pass": not findings, "classes": len(entries),
            "total_lessons": total, "findings": findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = check(a.db)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2))
    verdict = "PASS" if rep["pass"] else "FAIL"
    print(f"ic_expert_db_consistency: {verdict} "
          f"(classes={rep.get('classes','?')} lessons={rep.get('total_lessons','?')})")
    for f in rep.get("findings", []):
        print(f"  ! {f}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
