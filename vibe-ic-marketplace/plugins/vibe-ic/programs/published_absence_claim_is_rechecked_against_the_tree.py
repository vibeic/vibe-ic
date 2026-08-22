#!/usr/bin/env python3
"""A published reason string that names a path as ABSENT, and it exists.

THIS GATE BLOCKS (rc=1) on a NEW one. It is GREEN on the tree it ships with,
and the reason that zero is trustworthy is stated below and tested.

WHAT IT ASKS THE REPOSITORY
===========================
A published explanation asserting a named artefact is ABSENT must be
re-evaluated against the tree at the moment it is published, never written as a
literal. A placeholder carries a string saying WHY it cannot answer and names a
module as not yet present; the named thing lands later, in a different change,
and the string is never revisited — it is a literal in a file nobody had reason
to reopen. The stale claim is then copied verbatim into every document the
placeholder publishes, where it reads as a current fact about the tree.

Where the claim reduces to a path, the check is a FILE TEST and the refusal is
unambiguous. That is the whole rule.

THE PREDICATE
=============
A finding is a string constant that is NOT a docstring, in which an absence
verb and a repository-relative path occur in the SAME SENTENCE within 60
characters of each other, and the path RESOLVES TO AN EXISTING FILE.

ATTACHMENT IS THE WHOLE PREDICATE. Matching an absence verb anywhere in a
string and a path anywhere in the same string returns 78 claims of which 73 are
"false" — and every one of those 73 is a module docstring whose absence verb
and whose path are in unrelated sentences, sometimes hundreds of characters
apart. Requiring the same sentence and a 60-character window takes it to zero.

DOCSTRINGS ARE EXCLUDED. A module's documentation is not a published reason
string; the rule is about what a placeholder EMITS into a report.

WHY THE ZERO IS REAL, AND HOW THIS FILE PROVES IT
=================================================
A gate that returns zero because its predicate cannot fire is indistinguishable
from a clean tree, and this repository has measured that failure more than
once. So the zero here is backed two ways:

  * A POSITIVE CONTROL ships in the test file. Three synthetic strings of the
    exact shape — "programs/x.py is not yet present", "... does not exist",
    "docs/y.md has not landed" — must all FIRE. If the predicate ever stops
    matching them the suite goes red, whatever the tree looks like.
  * THE DENOMINATOR IS PRINTED. There are 272 absence-shaped strings outside
    docstrings in this tree. None carries a hard-coded path: they interpolate
    the path at run time (`f"no such file: {p}"`), which is the CORRECT
    pattern and is why the finding count is zero rather than the population
    being empty.

So this is a pure re-entry guard. It has nothing to report today and refuses
the first literal absence claim anybody writes.

EXIT
====
  0  no published absence claim names a path that exists
  1  a claim that is false against this tree
  2  cannot determine
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

_ABSENCE = re.compile(
    r"(does not exist|not yet (?:present|landed|written|implemented|exist)"
    r"|is absent|no such file|not present|has not landed|does not ship"
    r"|is not present|not implemented yet)", re.I)

_PATH = re.compile(
    r"\b((?:programs|tools|docs|flow|schemas|skills|benchmark)/[\w./-]+\.\w{1,6})\b")

#: The verb must be attached to the path. Beyond this they are two unrelated
#: sentences that happen to share a string.
_WINDOW = 60


def _docstring_ids(tree: ast.AST) -> Set[int]:
    out: Set[int] = set()
    for n in ast.walk(tree):
        body = getattr(n, "body", None)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def claims_in(text: str) -> List[Tuple[str, str]]:
    """(path, sentence) for every absence claim ATTACHED to a path."""
    out: List[Tuple[str, str]] = []
    for sentence in re.split(r"(?<=[.;])\s+", text):
        verb = _ABSENCE.search(sentence)
        if not verb:
            continue
        for m in _PATH.finditer(sentence):
            if abs(verb.start() - m.start()) <= _WINDOW:
                out.append((m.group(1), sentence.strip()))
    return out


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not progs.is_dir():
        return [], {"modules_parsed": 0, "absence_shaped_strings": 0,
                    "claims_naming_a_path": 0, "false_claims": 0}
    findings: List[dict] = []
    parsed = 0
    absence_shaped = 0
    attached = 0
    bases = (root, root / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
    for f in sorted(progs.rglob("*.py")):
        if "tests" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        parsed += 1
        docs = _docstring_ids(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
                continue
            if id(n) in docs:
                continue
            if not _ABSENCE.search(n.value):
                continue
            absence_shaped += 1
            for rel, sentence in claims_in(n.value):
                attached += 1
                for base in bases:
                    if (base / rel).is_file():
                        findings.append({
                            "file": f.relative_to(root).as_posix(),
                            "line": n.lineno, "path": rel,
                            "claim": sentence[:110]})
                        break
    return findings, {"modules_parsed": parsed,
                      "absence_shaped_strings": absence_shaped,
                      "claims_naming_a_path": attached,
                      "false_claims": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] published_absence_claim: no repository "
                  "root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if denom["modules_parsed"] == 0:
            print("[CANNOT DETERMINE] published_absence_claim: no programs/ "
                  "under that root. NOT a pass.", file=sys.stderr)
            return 2
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] published_absence_claim: the walk did not "
              f"complete ({type(exc).__name__}: {exc}). NOT a pass.",
              file=sys.stderr)
        return 2

    print(f"  modules parsed:                  {denom['modules_parsed']}")
    print(f"  absence-shaped strings:          {denom['absence_shaped_strings']}"
          f"   <- the population; a zero here would mean the predicate is blind")
    print(f"  claims ATTACHED to a path:       {denom['claims_naming_a_path']}")
    print(f"  of those, false against the tree:{denom['false_claims']:4d}")

    if findings:
        print(f"\n[FAIL] {len(findings)} published claim(s) say a path is absent "
              f"and it exists:")
        for f in findings:
            print(f"   {f['file']}:{f['line']}  names {f['path']}\n"
                  f"      {f['claim']!r}")
        print("\n  The named thing landed in a later change and the string was "
              "never revisited.\n  Re-evaluate the claim at the publish "
              "boundary — where it reduces to a path,\n  that is a file test — "
              "or say only that there is no evidence, without saying\n  why.")
        return 1

    print("[PASS] published_absence_claim_is_rechecked_against_the_tree: no "
          "published claim asserts an absence the tree contradicts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
