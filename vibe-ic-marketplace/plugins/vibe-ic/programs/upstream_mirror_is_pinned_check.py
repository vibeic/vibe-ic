#!/usr/bin/env python3
"""upstream_mirror_is_pinned_check.py — a re-implementation must be pinned to
the thing it re-implements.

THE CLASS
=========
A module's header said it borrows upstream's shape: upstream's variable names
verbatim, upstream's numbered steps in upstream's order. Inside it, the
along-the-row extent was taken from the ORIENTED footprint while upstream
measures the MASTER. On a real ring that was a 4.4x error — 19 x 350 = 6650 um
summed against a 1500 um side — and it did not surface as "our arithmetic
disagrees with theirs". It surfaced as an unrelated refusal, weeks later.

OUR half of that invariant was pinned by a test. THEIRS was not. So the
sentence "upstream does it this way" was true when it was typed and unchecked
from then on, and a change on either side of the mirror would land as a silent
divergence.

    A BORROWING STATED ONLY IN PROSE IS NOT A BORROWING THAT IS MAINTAINED.

WHAT THIS CHECKS
================
Every module under `programs/` that declares a module-level `UPSTREAM_MIRROR`
must carry, in that declaration:

    upstream    the upstream artefact, by path, as it is laid out in the
                shipped toolchain (e.g. `<project>/scripts/.../<file>.tcl`)
    mirrors     what is mirrored, in one sentence a reader can check
    pinned_by   `tests/<file>.py::<test>` — a test that READS that artefact

and the named test must EXIST, in the named file, and that file must actually
reference the declared upstream artefact. A `pinned_by` pointing at a test that
does not read upstream is a pin in name only, which is the failure this exists
to prevent rather than to document.

WHAT THIS DOES NOT DO, STATED
=============================
It does not decide WHICH modules ought to declare a mirror. That is a judgement
about whether a citation is a borrowing or a reference, and this program has no
input from which to make it. What it does instead is COUNT the candidates — the
modules whose own prose claims a borrowing while declaring none — and print
them on every run, PASS or FAIL. They are follow-on work, they are named, and
they are not quietly absent from the output. They do NOT fail the gate: turning
a prose scan into a blocking predicate is how a checker earns a reputation for
firing on correct code, and the honest form of "I could not decide this" is to
show the reader the list.

EXIT
====
  0  every declared mirror is pinned (the count is printed)
  1  a declared mirror is unpinned, or its pin does not read upstream
  2  the population could not be built, or is EMPTY. Zero declared mirrors is
     not "every mirror is pinned" — it is a question with no subject, and a
     gate that answers PASS to that is the zero-denominator defect.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

PROGRAM = "upstream_mirror_is_pinned_check"

DECLARATION = "UPSTREAM_MIRROR"
REQUIRED_KEYS = ("upstream", "mirrors", "pinned_by")

#: Prose that CLAIMS a borrowing. Used only to COUNT candidates, never to fail.
_MIRROR_CLAIM = re.compile(
    r"\b(mirror(?:s|ing|ed)?|verbatim|re-?implement(?:s|ed|ation)?|"
    r"reproduc(?:e|es|ed|ing)|borrow(?:s|ed|ing)?|follow(?:s|ing) "
    r"upstream|upstream'?s own)\b", re.I)

#: An upstream artefact path, as the shipped toolchain lays one out.
_UPSTREAM_PATH = re.compile(
    r"\b[a-z][a-z0-9_.-]*/(?:scripts|config|steps|src|passes|techlibs|tcltk)/"
    r"[A-Za-z0-9_./-]+\.(?:tcl|py|v|lib|json|yaml)\b")


def _module_docstring(tree: ast.AST) -> str:
    try:
        return ast.get_docstring(tree) or ""
    except Exception:
        return ""


def _declaration(tree: ast.AST) -> Optional[Dict[str, str]]:
    """The module-level `UPSTREAM_MIRROR` dict, literally evaluated.

    Only a LITERAL is accepted. A declaration computed at import time cannot be
    read without running the module, and a gate that imports its subjects
    inherits their side effects — which is how a checker starts needing a PDK
    to answer a question about source text.
    """
    for node in getattr(tree, "body", []):
        targets: List[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name) and t.id == DECLARATION:
                try:
                    val = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    return {"__unreadable__":
                            "not a literal dict; this gate reads source, it "
                            "does not import"}
                return val if isinstance(val, dict) else {
                    "__unreadable__": f"is a {type(val).__name__}, not a dict"}
    return None


def check_declaration(programs: Path, mod_rel: str,
                      decl: Dict[str, str]) -> List[str]:
    """Human-readable problems with ONE declaration; empty list == pinned."""
    problems: List[str] = []
    if "__unreadable__" in decl:
        return [f"{mod_rel}: {DECLARATION} {decl['__unreadable__']}"]
    for k in REQUIRED_KEYS:
        if not str(decl.get(k, "")).strip():
            problems.append(f"{mod_rel}: {DECLARATION} has no {k!r}")
    if problems:
        return problems

    upstream = str(decl["upstream"]).strip()
    pinned_by = str(decl["pinned_by"]).strip()
    if "::" not in pinned_by:
        return [f"{mod_rel}: pinned_by {pinned_by!r} is not "
                f"'tests/<file>.py::<test>'"]
    rel, test_name = pinned_by.split("::", 1)
    pin = programs / rel
    if not pin.is_file():
        return [f"{mod_rel}: pinned_by names {rel}, which does not exist. A "
                f"mirror whose pin is not there is a mirror nothing maintains."]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            pin_tree = ast.parse(pin.read_text(errors="replace"))
    except SyntaxError as exc:
        return [f"{mod_rel}: pin {rel} does not parse: {exc}"]

    names = {n.name for n in ast.walk(pin_tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if test_name not in names:
        problems.append(
            f"{mod_rel}: pinned_by names {test_name}, which {rel} does not "
            f"define")

    # THE PIN MUST READ UPSTREAM. A test that only asserts our own invariant
    # is the state this gate exists to improve on — ours was already pinned
    # when the drift happened, and it did not help, because the two halves
    # were never compared.
    #
    # THREE FORMS COUNT AS READING UPSTREAM, and the third is the best of them:
    #   * the declared path in full;
    #   * its tail, for a pin that resolves the project root itself;
    #   * a reference to `UPSTREAM_MIRROR`, i.e. the pin takes the path FROM
    #     the declaration instead of repeating it. That is not a weaker pin,
    #     it is a stronger one — a repeated literal is a second copy of the
    #     same fact and the two drift independently, which is the whole
    #     disease this gate treats. Measured: the first pin written for this
    #     gate did exactly that and this check flagged it, which is how the
    #     third form got here.
    # A pin mentioning NONE of the three still fails
    # (`test_a_pin_that_mentions_neither_the_path_nor_the_declaration_fails`).
    pin_text = pin.read_text(errors="replace")
    tail = upstream.split("/", 1)[-1] if "/" in upstream else upstream
    reads_upstream = (upstream in pin_text
                      or tail in pin_text
                      or DECLARATION in pin_text)
    if not reads_upstream:
        problems.append(
            f"{mod_rel}: pin {rel} mentions neither the declared upstream "
            f"artefact {upstream!r} nor {DECLARATION}. A pin that does not "
            f"read upstream cannot see upstream change.")
    return problems


def candidates(programs: Path, declared: set) -> List[Dict[str, str]]:
    """Modules whose own prose claims a borrowing while declaring none.

    Counted and printed, never failed — see the docstring.
    """
    out: List[Dict[str, str]] = []
    for p in sorted(programs.rglob("*.py")):
        rel = str(p.relative_to(programs))
        if "tests" in Path(rel).parts or rel in declared:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(p.read_text(errors="replace"))
        except SyntaxError:
            continue
        doc = _module_docstring(tree)
        if not doc:
            continue
        path_hit = _UPSTREAM_PATH.search(doc)
        if path_hit and _MIRROR_CLAIM.search(doc):
            out.append({"module": rel, "cites": path_hit.group(0)})
    return out


def scan(programs: Path) -> Dict[str, Any]:
    declared: Dict[str, Dict[str, str]] = {}
    parsed = 0
    for p in sorted(programs.rglob("*.py")):
        rel = str(p.relative_to(programs))
        if "tests" in Path(rel).parts:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(p.read_text(errors="replace"))
        except SyntaxError:
            continue
        parsed += 1
        decl = _declaration(tree)
        if decl is not None:
            declared[rel] = decl

    problems: List[str] = []
    for rel, decl in declared.items():
        problems += check_declaration(programs, rel, decl)

    return {
        "files_parsed": parsed,
        "declared": {k: v for k, v in declared.items()},
        "problems": problems,
        "undeclared_candidates": candidates(programs, set(declared)),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--programs-dir", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    programs = (Path(a.programs_dir) if a.programs_dir
                else Path(__file__).resolve().parent)
    if not programs.is_dir():
        print(f"=== {PROGRAM} ===")
        print(f"  NOT CHECKED: {programs} is not a directory. A check that "
              f"could not look has not passed.")
        return 2

    res = scan(programs)
    if a.json:
        # ATOMIC (vibe-ic#1082): this is the DECLARED report a later
        # reader resolves, so the final name must appear only once the
        # write is complete.
        atomic_write_text(Path(a.json),
                          json.dumps(res, indent=2) + "\n")

    print(f"=== {PROGRAM} ===")
    print(f"  files parsed        : {res['files_parsed']}")
    print(f"  declared mirrors    : {len(res['declared'])}")
    for rel, d in sorted(res["declared"].items()):
        print(f"      {rel} -> {d.get('upstream', '(none)')}")
    print(f"  undeclared candidates (prose claims a borrowing, declares "
          f"nothing — follow-on, NOT a failure): "
          f"{len(res['undeclared_candidates'])}")
    for c in res["undeclared_candidates"]:
        print(f"      {c['module']} cites {c['cites']}")

    if res["files_parsed"] == 0:
        print("  NOT CHECKED: nothing under this directory parsed.")
        return 2
    if not res["declared"]:
        print(f"  NOT CHECKED: no module declares {DECLARATION}. Zero declared "
              f"mirrors is a question with no subject, not a clean answer to "
              f"it.")
        return 2
    if res["problems"]:
        print(f"  FAIL: {len(res['problems'])} declared mirror(s) are not "
              f"pinned to what they mirror:")
        for p in res["problems"]:
            print(f"    {p}")
        return 1
    print("  PASS: every declared mirror names a pin that reads upstream.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
