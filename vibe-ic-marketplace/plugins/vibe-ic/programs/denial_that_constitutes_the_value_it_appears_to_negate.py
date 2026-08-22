#!/usr/bin/env python3
"""A blanket denial check on an extractor whose subject IS the denial.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A polarity guard that treats EVERY denial as a negation inverts the sentences
in which the denial IS the value. A specification saying a quantity "is not
stated" is GRANTING FREEDOM, not withholding a number, and an extractor whose
subject is that freedom must read the sentence as a POSITIVE.

Applying a blanket denial check to such an extractor silently drops the
freedoms the specification granted — the same disease as ignoring polarity
altogether, pointing the other way. Adding the guard without the table converts
a false negative into a false positive and READS AS A FIX.

MEASURED: a lane repaired two of three offending extractors — one now consults
the shared module, one is declared not-prose with a stated reason that a port
declaration is a grammar in which a negated declaration is unspellable — and
measured the third repair FAILING. The same blanket check broke FOUR
previously passing tests, because the fixture sentence granting freedom spells
that freedom with a denial. It was reverted, and the finding left open rather
than closed with a repair that inverts the sentences the function exists to
read.

WHAT THIS IS NOT
================
`prose_polarity_consulted_check` is a live blocking gate demanding that a
prose-reading extractor CONSULT the shared module. This is the narrower thing
that was the reason its own remedy could not be applied to one of its three
offenders: the module had no constitutive-versus-negating table, so there was
nothing for an absence-extractor to consult that would not invert it.

The table now ships in `_prose_polarity` as `CONSTITUTIVE_IDIOMS`, keyed by the
CONCEPT the calling extractor extracts, with `classify_denial` testing
constitutive FIRST — because every constitutive idiom also matches the
negation vocabulary, which is exactly what makes the blanket check wrong here.

THE PREDICATE
=============
A finding is a function where all of these hold:

  1. its EXTRACTED CONCEPT is constitutive — the function's own name, or the
     field it assigns into, spells one of the concepts the table is keyed by
     (freedom, optionality, absence, exclusion);
  2. it applies a BLANKET denial check — `is_denied`, `NEGATION_RE.search`,
     one of the tier patterns, or an inline regex over the bare denial
     vocabulary;
  3. and it never reaches the table: no `classify_denial`,
     `constitutive_idiom` or `concept_is_constitutive` anywhere in it.

The remedy is `classify_denial(<concept>, span)`, which returns which of the
two a denial is and the word that decided it.

EXIT
====
  0  no blanket denial check on a constitutive extractor
  1  a NEW one, or a stale inventory row
  2  cannot determine — no tree, or the shared module has no table
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prose_polarity                                         # noqa: E402

_INVENTORY_NAME = "constitutive_denial_inventory.json"

#: How an extractor SPELLS the concept it extracts, per table key. Matched
#: against the function name and against every field it assigns into.
_CONCEPT_ALIASES: Dict[str, Tuple[str, ...]] = {
    "freedom": ("unconstrained", "unspecified", "not_stated", "notstated",
                "no_constraint", "unbounded", "any_value", "dont_care",
                "free_choice", "freedom"),
    "optionality": ("optional", "not_required", "notrequired", "optionality",
                    "discretion"),
    "absence": ("absent", "absence", "is_missing", "has_no", "no_reset",
                "not_present", "omitted"),
    "exclusion": ("exclusion", "excluded", "excluding", "exclude_list",
                  "except_list"),
}

#: The blanket-denial call names, as they are spelled at a call site.
_BLANKET_CALLS = ("is_denied", "NEGATION_RE", "DENIAL_CORE_RE",
                  "DENIAL_RETIRED_RE")

#: An inline regex over the bare denial vocabulary is the same blanket check
#: written out longhand. TWO conditions, because a docstring saying "no" is not
#: a regex: the constant must carry a word-boundary escape AND a denial word as
#: a whole token.
#:
#: The boundary escape is the ONLY pattern marker used. Accepting `(?:` or a
#: bare alternation was measured at six false positives — a markdown table row
#: reading `| declared but not applied |` and five docstrings — because a pipe
#: is prose punctuation and a docstring saying "not" is not a check. A literal
#: backslash-b essentially never occurs in English.
_LOOKS_LIKE_A_PATTERN = re.compile(r"\\b")
_DENIAL_TOKEN = re.compile(r"(?<![A-Za-z])(?:not|no|none|never)(?![A-Za-z])")

#: What clears it.
_TABLE_CALLS = ("classify_denial", "constitutive_idiom",
                "concept_is_constitutive")


def _concept_of(name: str) -> Optional[str]:
    low = name.lower()
    for concept, aliases in _CONCEPT_ALIASES.items():
        if any(a in low for a in aliases):
            return concept
    return None


def _assigned_fields(fn: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(
                        t.slice, ast.Constant) and isinstance(t.slice.value, str):
                    out.add(t.slice.value)
                if isinstance(t, ast.Attribute):
                    out.add(t.attr)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("setdefault", "update", "get"):
            for arg in n.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.add(arg.value)
        if isinstance(n, ast.keyword) and n.arg:
            out.add(n.arg)
    return out


def _names_used(fn: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            out.add(n.id)
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _blanket_denial(fn: ast.AST, used: Set[str]) -> Optional[str]:
    for call in _BLANKET_CALLS:
        if call in used:
            return call
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            v = n.value
            if _LOOKS_LIKE_A_PATTERN.search(v) and _DENIAL_TOKEN.search(v):
                return f"inline denial regex {v[:40]!r}"
    return None


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    constitutive = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "node_modules" in p.parts or "tests" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            parsed += 1
            rel = p.relative_to(root).as_posix()
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                concept = _concept_of(fn.name)
                via = "function name"
                if concept is None:
                    for field in _assigned_fields(fn):
                        concept = _concept_of(field)
                        if concept:
                            via = f"field {field!r}"
                            break
                if concept is None:
                    continue
                constitutive += 1
                used = _names_used(fn)
                if any(t in used for t in _TABLE_CALLS):
                    continue
                how = _blanket_denial(fn, used)
                if how is None:
                    continue
                findings.append({"file": rel, "line": fn.lineno,
                                 "function": fn.name, "concept": concept,
                                 "concept_via": via, "blanket_check": how})
    return findings, {"modules_parsed": parsed,
                      "constitutive_extractors": constitutive,
                      "blanket_checked": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['function']}::{f['concept']}"


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        if not getattr(_prose_polarity, "CONSTITUTIVE_IDIOMS", None):
            print("[CANNOT DETERMINE] denial_that_constitutes_the_value_it_"
                  "appears_to_negate: the shared polarity module ships no "
                  "constitutive table, so there is nothing an absence-extractor "
                  "could consult. NOT a pass.", file=sys.stderr)
            return 2
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] denial_that_constitutes_the_value_it_"
                  "appears_to_negate: no repository root. NOT a pass.",
                  file=sys.stderr)
            return 2
        findings, denom = scan(root)
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings,
                 "table_keys": sorted(_prose_polarity.CONSTITUTIVE_IDIOMS)},
                indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] denial_that_constitutes_the_value_it_appears_"
              f"to_negate: the walk did not complete ({type(exc).__name__}: "
              f"{exc}). NOT a pass.", file=sys.stderr)
        return 2

    print(f"  table keys:                 "
          f"{', '.join(sorted(_prose_polarity.CONSTITUTIVE_IDIOMS))}")
    print(f"  modules parsed:             {denom['modules_parsed']}")
    print(f"  constitutive extractors:    {denom['constitutive_extractors']}")
    print(f"  blanket-checked among them: {denom['blanket_checked']}")
    print(f"  inventory rows applied:     {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} extractor(s) apply a blanket denial check "
              f"to a concept a denial CONSTITUTES:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  {f['function']}() extracts "
                      f"'{f['concept']}' (by {f['concept_via']}) and applies "
                      f"{f['blanket_check']}")
        print("\n  \"not stated\" is a grant, not a withholding. Use "
              "`classify_denial(<concept>,\n  span)`, which tests constitutive "
              "FIRST — every constitutive idiom also\n  matches the negation "
              "vocabulary, which is what makes the blanket check wrong.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] denial_that_constitutes_the_value_it_appears_to_negate: "
              "no constitutive extractor carries a blanket denial check.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
