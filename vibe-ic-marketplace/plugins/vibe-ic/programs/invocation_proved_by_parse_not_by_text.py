#!/usr/bin/env python3
"""A wiring audit that decides invocation by searching the caller's TEXT.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
Whether one module invokes another is a question about CODE, and a text search
cannot answer it. About half of a large orchestrating module is prose, and a
name that appears there is graded as a call, so the audit certifies wiring that
does not exist. The inverse holds too: a text scan cannot see a call assembled
at run time. Both directions of such an audit are unsound, and its CLEAN
verdicts carry no information either.

The consequence lands on the design, not on the audit. A step whose producer
nothing dispatches reports a missing artefact for every input forever, and
every reader charges that to the design rather than to the flow.

MEASURED on the capture commit: `flow_step_executor_coverage_check.py` — whose
own docstring says a step with no dispatching producer "can only ever be
MISSING, and that is the root cause of middle steps silently skipped" —
contains no syntax-tree parse at all. It concatenates the runner sources and
applies a regular expression to 3,055,921 bytes, of which 1,472,929 (48%) are
docstring and comment. On the same commit, three producers declared by two path
steps appear ZERO times in any runner, in code tokens or in prose tokens.

A second lane measured the mirror on the consumption side: of 7 runners, 5 name
the compliance checker in prose only, and a text scan graded 3 of them as
consumers of a verdict they never ask for.

THE PREDICATE
=============
A finding is an ENFORCEMENT module where all of these hold:

  1. it reads PYTHON SOURCE — a `read_text` / `open().read()` whose path
     expression names a `.py` file, or a join over such reads;
  2. it SEARCHES that text to decide something: `in` membership,
     `re.search` / `findall` / `finditer` / `match`, `.count()` or `.find()`.
     The NEEDLE's shape is deliberately not part of the predicate — the known
     instance searches for an artefact-path token, not for a `.py` name, and a
     rule keyed on the needle would miss it;
  3. and the module NEVER calls `ast.parse` — it has no way to tell a call
     node from a docstring.

Clause 3 is what keeps this usable. A module that parses AND greps has a
syntax tree available and the grep is doing something else; flagging it would
bury the population that has no tree at all.

WHAT THE REMEDY IS
==================
Decide invocation from the syntax tree: a call node, an element of an argument
vector, or an import — never a docstring, a comment or a help string. Where the
caller builds an argument vector from a constant, resolve the constant. Report
a name occurring only in prose as its OWN outcome, so the audit can state how
many of its positive verdicts came from prose.

`hdl_declaration_scan_strips_comments_check` already enforces exactly this
discipline for hardware-description declaration scans and is a live blocking
gate. This is the same discipline for the PROGRAM-INVOCATION population, which
had no equivalent.

EXIT
====
  0  no text-decided invocation audit outside the inventory
  1  a NEW one, or a stale inventory row
  2  cannot determine
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_INVENTORY_NAME = "invocation_text_scan_inventory.json"

_ENFORCEMENT_SUFFIXES = ("_check.py", "_audit.py", "_gate.py", "_scan.py",
                         "_gates.py", "_guard.py", "_coverage.py")

_SEARCH_METHODS = ("count", "find", "rfind", "index")
_RE_SEARCHES = ("search", "match", "findall", "finditer", "fullmatch")


def _strings_under(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)
        if isinstance(n, ast.JoinedStr):
            out.add("".join(v.value for v in n.values
                            if isinstance(v, ast.Constant)
                            and isinstance(v.value, str)))
    return out


def _names_a_py_file(node: ast.AST) -> bool:
    return any(".py" in s for s in _strings_under(node))


def _reads_python_source(value: ast.AST, py_names: Set[str]) -> bool:
    """Does this expression read the TEXT of a python source file?

    The `.py` names need not be in the same expression. The known instance
    builds its corpus from a module-level list of runner filenames and reads
    them in a loop, so requiring the name and the read to sit together missed
    the very site the rule was written for.
    """
    for n in ast.walk(value):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        attr = f.attr if isinstance(f, ast.Attribute) else None
        if attr in ("read_text", "read") or (
                isinstance(f, ast.Name) and f.id == "open"):
            if _names_a_py_file(value):
                return True
            if any(isinstance(x, ast.Name) and x.id in py_names
                   for x in ast.walk(value)):
                return True
    return False


def _has_ast_parse(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "parse":
                base = f.value
                if isinstance(base, ast.Name) and base.id == "ast":
                    return True
            if isinstance(f, ast.Name) and f.id == "parse":
                return True
    return False


def _py_source_names(tree: ast.AST) -> Set[str]:
    """Names that hold a `.py` filename, or a collection of them.

    DATAFLOW, not module-wide presence. "The module mentions a .py string
    somewhere" was measured at 108 findings across 67 modules, nearly all of
    them reading a report or a shell script — a corpus that is not python
    source at all. What the rule is about is a corpus built from a closed set
    of PYTHON MODULES, which is a binding, not a coincidence.
    """
    out: Set[str] = set()
    for n in ast.walk(tree):
        targets: List[ast.expr] = []
        value: Optional[ast.AST] = None
        if isinstance(n, ast.Assign):
            targets, value = list(n.targets), n.value
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            targets, value = [n.target], n.value
        if value is None:
            continue
        strs = {c.value for c in ast.walk(value)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if not any(x.endswith(".py") for x in strs):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out.add(t.id)
    return out


def _accumulator_functions(tree: ast.AST, py_names: Set[str]) -> Set[str]:
    """Local functions that RETURN python source text.

    `_load_runner_text()` appends seven `read_text()` results and joins them.
    Its caller binds a name to the result, and that name is the corpus.
    """
    out: Set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # `for f in _RUNNER_FILES: parts.append(p.read_text(...))` — the read
        # names no constant of its own; the LOOP is what makes it a python
        # source read.
        loop_over_py = any(
            isinstance(lp, (ast.For, ast.AsyncFor)) and any(
                isinstance(x, ast.Name) and x.id in py_names
                for x in ast.walk(lp.iter))
            for lp in ast.walk(fn))
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            if _reads_python_source(n, py_names):
                out.add(fn.name)
                break
            f2 = n.func
            if loop_over_py and isinstance(f2, ast.Attribute) \
                    and f2.attr in ("read_text", "read"):
                out.add(fn.name)
                break
    return out


def _source_text_names(tree: ast.AST) -> Dict[str, int]:
    """Names holding python source text -> the line they were bound at."""
    py_names = _py_source_names(tree)
    accum = _accumulator_functions(tree, py_names)
    out: Dict[str, int] = {}
    for n in ast.walk(tree):
        targets: List[ast.expr] = []
        value: Optional[ast.AST] = None
        if isinstance(n, ast.Assign):
            targets, value = list(n.targets), n.value
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            targets, value = [n.target], n.value
        elif isinstance(n, ast.AugAssign):
            targets, value = [n.target], n.value
        if value is None:
            continue
        direct = _reads_python_source(value, py_names)
        if not direct and isinstance(value, ast.Call) and isinstance(
                value.func, ast.Name) and value.func.id in accum:
            direct = True
        # a join / concatenation over names already known to hold source
        joined = False
        for sub in ast.walk(value):
            if isinstance(sub, ast.Name) and sub.id in out:
                joined = True
                break
        if not (direct or joined):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = n.lineno

    # ONE HOP THROUGH A PARAMETER. The known instance never binds its corpus
    # to a name: it calls `classify(doc, _load_runner_text())` and the corpus
    # arrives as a parameter. A tracker that reads only assignments cannot see
    # the site the rule exists for.
    funcs = {fn.name: fn for fn in ast.walk(tree)
             if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Name):
            continue
        callee = funcs.get(n.func.id)
        if callee is None:
            continue
        for i, arg in enumerate(n.args):
            carries = (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                       and arg.func.id in accum) or (
                isinstance(arg, ast.Name) and arg.id in out)
            if not carries:
                continue
            params = callee.args.posonlyargs + callee.args.args
            if i < len(params):
                out.setdefault(params[i].arg, n.lineno)
    return out


def _searches_for_a_callee(tree: ast.AST, sources: Dict[str, int]) -> List[dict]:
    hits: List[dict] = []
    for n in ast.walk(tree):
        # `"x.py" in src`
        if isinstance(n, ast.Compare) and any(
                isinstance(o, (ast.In, ast.NotIn)) for o in n.ops):
            for comp in n.comparators:
                if isinstance(comp, ast.Name) and comp.id in sources:
                    hits.append({"line": n.lineno, "how": "`in` membership",
                                 "text": comp.id})
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        attr = f.attr if isinstance(f, ast.Attribute) else (
            f.id if isinstance(f, ast.Name) else None)
        # `src.count("x.py")`
        if attr in _SEARCH_METHODS and isinstance(f, ast.Attribute) \
                and isinstance(f.value, ast.Name) and f.value.id in sources:
            hits.append({"line": n.lineno, "how": f".{attr}()",
                         "text": f.value.id})
        # `re.findall(pat, src)` and `PAT.findall(src)`
        if attr in _RE_SEARCHES:
            subject = None
            if len(n.args) >= 2 and isinstance(n.args[1], ast.Name):
                subject = n.args[1].id
            elif n.args and isinstance(n.args[0], ast.Name) and isinstance(
                    f, ast.Attribute) and not (
                    isinstance(f.value, ast.Name) and f.value.id == "re"):
                subject = n.args[0].id
            if subject in sources:
                hits.append({"line": n.lineno, "how": f"re.{attr}()",
                             "text": subject})
    return hits


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    readers = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "node_modules" in p.parts or "tests" in p.parts:
                continue
            if not p.name.endswith(_ENFORCEMENT_SUFFIXES):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            parsed += 1
            sources = _source_text_names(tree)
            if not sources:
                continue
            readers += 1
            if _has_ast_parse(tree):
                continue
            hits = _searches_for_a_callee(tree, sources)
            if not hits:
                continue
            rel = p.relative_to(root).as_posix()
            for h in hits:
                findings.append({"file": rel, "line": h["line"],
                                 "how": h["how"], "text_name": h["text"],
                                 "bound_at": sources[h["text"]]})
    return findings, {"enforcement_modules": parsed,
                      "modules_reading_python_source": readers,
                      "text_decided_invocation_sites": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['text_name']}::{f['how']}"


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
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] invocation_proved_by_parse_not_by_text: "
                  "no repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] invocation_proved_by_parse_not_by_text: the "
              f"walk did not complete ({type(exc).__name__}: {exc}). NOT a "
              f"pass.", file=sys.stderr)
        return 2

    print(f"  enforcement modules:            {denom['enforcement_modules']}")
    print(f"  reading python source text:     {denom['modules_reading_python_source']}")
    print(f"  invocation decided by text:     {denom['text_decided_invocation_sites']}")
    print(f"  inventory rows applied:         {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} audit(s) decide invocation by searching "
              f"text:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  {f['how']} over "
                      f"`{f['text_name']}` (python source read at line "
                      f"{f['bound_at']}), and the module never parses it")
        print("\n  A name in a docstring is not a call, and a call assembled at "
              "run time is\n  not a name. Parse the caller and decide from the "
              "syntax tree; report a\n  prose-only occurrence as its own "
              "outcome so the audit can state how many\n  of its positive "
              "verdicts came from prose.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] invocation_proved_by_parse_not_by_text: no wiring audit "
              "decides invocation from raw text.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
