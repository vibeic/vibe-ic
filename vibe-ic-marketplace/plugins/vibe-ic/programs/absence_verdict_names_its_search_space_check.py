#!/usr/bin/env python3
"""absence_verdict_names_its_search_space_check.py — "not found" must say WHERE
it looked.

THE CLASS
=========
A step refused a thing the distribution DOES declare, with its size, in a file
the step never opened. The refusal read as thorough because it carried a count:

    PAD_SITE_NOT_FOUND: PAD_SITE_NAME='io_site' is not a SITE in the IO cell
    library this run resolved (0 site(s) from 1 LEF(s); PAD-class: [])

"0 of 1" is a DENOMINATOR, and the repo already has a gate that asks a PASS to
disclose one (`gate_discloses_denominator_check`). This is the other half, and
the four-times-measured class that gate names is the reason it is needed:

    A DENOMINATOR OVER ONE VIEW IS NOT A SEARCH SPACE.

The count above is true, and every part of it was measured, and the thing was
declared one directory over in a view the sentence does not mention. A reader
handed that sentence cannot tell "I looked in the two places this is declared
and it is in neither" from "I looked in one of them". Both print the same way,
and only one of them is a finding about the input.

WHAT THIS CHECKS
================
Every ABSENCE VERDICT in `programs/` — a refusal constructed with a rule id
matching `*_NOT_FOUND` / `*_ABSENT` / `*_MISSING` / `*_NOT_PRESENT`, the
repo's own naming convention for a machine-readable "it is not there" — must
carry a LOCUS in the same refusal: something that tells the reader where the
program looked.

A LOCUS is any of, and the list is deliberately generous because the defect is
saying NOTHING, not saying it imprecisely:

  * a path-shaped literal — a separator, a glob, a known artefact extension,
    or an environment-variable sigil;
  * an interpolated expression whose name is locus vocabulary (`path`, `dir`,
    `root`, `glob`, `file`, `rel`, `view`, `source`, `where`, `lef`, `report`,
    `tree`, `library`, `section`, `doc`, ... — the full list is `_LOCUS_WORDS`
    and it is printed by `--explain`);
  * an interpolated `Path`/`os.path`/`.relative_to(...)`/`.name` expression.

WHAT IT DELIBERATELY DOES NOT CHECK
===================================
It does NOT check that the locus is COMPLETE. Completeness is a property of the
DISTRIBUTION, not of our source: whether the two views a PDK declares a site in
were both opened cannot be decided by reading our Python, only by reading the
PDK. That is the decision this program cannot make from the input it has, and
saying so here is more useful than a predicate that pretends otherwise. What it
CAN do — and what closes the reachable half of the class — is refuse an absence
verdict that names no search space at all, which is the state the pre-fix
message would have been in had it not carried its one-view count.

It does NOT flag a rule id used as an environment-variable name, a dict key or
a comparison operand. The population is REFUSAL CONSTRUCTION only: the id must
be a positional argument of a call. Measured while writing this: without that
restriction `os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT")` is reported as a
silent refusal, which is a false positive of exactly the kind that teaches
people to ignore a tool.

DENOMINATOR
===========
Every run prints how many files it parsed and how many absence verdicts it
found, PASS or FAIL, so a run that walked nothing cannot read like a clean one.

EXIT
====
  0  every absence verdict names a search space (the count is printed)
  1  at least one does not; each is reported with file, line and rule id
  2  the population could not be built — the programs directory is not a
     directory, or nothing in it parsed. An absent corpus is not a measurement
     of zero.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROGRAM = "absence_verdict_names_its_search_space_check"

#: The repo's own naming convention for a machine-readable "it is not there".
ABSENCE_RULE_ID = re.compile(
    r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(NOT_FOUND|ABSENT|MISSING|NOT_PRESENT)$")

#: A literal that is shaped like somewhere you can look.
#:
#: A FILESYSTEM path is the obvious form and it is not the only one. A refusal
#: that a FIELD is absent from a document already opened answers "where did you
#: look" with a DOCUMENT ADDRESS — `foundry_signoff_plan.closures[3]` sends a
#: reader to precisely one place, which is the whole point of the rule. Both
#: forms are accepted, and neither is a widening to clear a red: an address is
#: a locus under the rule as stated ("say WHICH view you read"), and a refusal
#: carrying no address of any kind is still refused, which
#: `test_a_refusal_with_no_address_of_any_kind_is_refused` pins.
#:
#: The dotted form requires TWO-CHARACTER-MINIMUM segments on both sides of
#: every dot, so English abbreviations ("i.e.", "e.g.") are not addresses.
_LOCUS_LITERAL = re.compile(
    r"(?:/)"                       # a path separator
    r"|(?:\*)"                     # a glob
    r"|(?:\$\{?[A-Z_]+)"           # an environment-variable reference
    r"|(?:\.(?:json|ya?ml|lef|tlef|def|tcl|v|sv|md|txt|log|csv|spef|lib|gds|"
    r"cfg|conf|ini|toml|py|sdc|rpt))\b"
    r"|(?:[A-Za-z_][A-Za-z0-9_]*\[)"          # an indexed address: closures[3]
    r"|(?:\b[a-z_][a-z0-9_]+(?:\.[a-z_][a-z0-9_]+)+\b)"    # a.b.c
    # An address whose TAIL is interpolated: the f-string literal ends at the
    # dot and the field name arrives from a variable
    # (`f"foundry_signoff_plan.{k} is required"`). The literal fragment the
    # parser sees is `foundry_signoff_plan.` and it is an address with its last
    # segment supplied at run time, not a sentence that happens to end in a dot
    # — a sentence's dot is preceded by a word AND followed by whitespace or
    # end-of-string, which is why the anchor is end-of-FRAGMENT.
    r"|(?:[A-Za-z_][A-Za-z0-9_]+\.$)",
    re.I)

#: Names that, when interpolated into a refusal, tell a reader where we looked.
_LOCUS_WORDS: Tuple[str, ...] = (
    "path", "paths", "dir", "dirs", "directory", "root", "roots", "glob",
    "globs", "file", "files", "filename", "rel", "abs", "loc", "location",
    "where", "source", "sources", "src", "view", "views", "tree", "trees",
    "lef", "lefs", "libdir", "library", "libraries", "libs", "report",
    "reports", "artefact", "artifact", "doc", "docs", "document", "section",
    "url", "uri", "searched", "search", "looked", "candidates", "scanned",
    "corpus", "manifest", "config", "cfg", "project", "run_dir", "workdir",
    "stem", "suffix", "parent", "name",
)
_LOCUS_NAME = re.compile("|".join(re.escape(w) for w in _LOCUS_WORDS), re.I)

#: Attribute/call tails that are path expressions whatever the variable is called.
_LOCUS_CALLS = frozenset({
    "relative_to", "as_posix", "resolve", "absolute", "joinpath", "basename",
    "dirname", "abspath", "realpath", "relpath", "fspath", "Path",
})


#: Calls that take a NAME as their first argument and are not refusals at all:
#: an environment read, a dict lookup, a default. Measured while writing this —
#: `os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT")` is a TEST HOOK whose whole
#: job is to force the honest-degrade path, and reporting it as a silent
#: refusal is the false positive that teaches people to ignore a tool.
_NOT_A_REFUSAL = frozenset({
    "get", "getenv", "setdefault", "pop", "setenv", "delenv", "__getitem__",
    "count", "index", "startswith", "endswith", "add", "discard", "remove",
})


def _func_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _has_locus(node: ast.AST) -> bool:
    """True when anything under `node` tells a reader where we looked."""
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if _LOCUS_LITERAL.search(n.value):
                return True
            # A literal that spells a locus word ("no LEF view was opened").
            if _LOCUS_NAME.search(n.value):
                return True
        elif isinstance(n, ast.Name):
            if _LOCUS_NAME.search(n.id):
                return True
        elif isinstance(n, ast.Attribute):
            if n.attr in _LOCUS_CALLS or _LOCUS_NAME.search(n.attr):
                return True
        elif isinstance(n, ast.Call):
            if _func_name(n.func) in _LOCUS_CALLS:
                return True
    return False


def _bindings(fn: ast.AST) -> Dict[str, List[ast.AST]]:
    """Every value assigned to a bare name anywhere inside `fn`.

    A refusal very often reads ``_finding(RULE_ID, reason)`` with ``reason``
    built two lines above out of the path it just failed to open. The locus IS
    disclosed; it simply is not spelled at the call. Resolving one level of
    binding is the difference between reading this repo's real refusals and
    reporting four of them as silent — measured, on the tree this shipped with.
    """
    out: Dict[str, List[ast.AST]] = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(n.value)
                elif isinstance(t, ast.Tuple):
                    for el in t.elts:
                        if isinstance(el, ast.Name):
                            out.setdefault(el.id, []).append(n.value)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and \
                isinstance(n.target, ast.Name) and n.value is not None:
            out.setdefault(n.target.id, []).append(n.value)
    return out


def _has_locus_resolved(nodes: List[ast.AST], binds: Dict[str, List[ast.AST]],
                        depth: int = 2) -> bool:
    """`_has_locus` over `nodes`, following bare names into their bindings."""
    for node in nodes:
        if _has_locus(node):
            return True
    if depth <= 0:
        return False
    followed: List[ast.AST] = []
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                followed += binds.get(n.id, [])
    return bool(followed) and _has_locus_resolved(followed, binds, depth - 1)


def absence_verdicts(tree: ast.AST) -> List[Tuple[int, str, List[ast.AST]]]:
    """Every refusal CONSTRUCTION whose rule id is absence-class.

    Returns (lineno, rule_id, companion-expressions). Three restrictions, each
    of which removed a MEASURED false positive rather than a hypothetical one:

      * the rule id must be a POSITIONAL argument of a call — an id used as an
        env-var name, a dict key or a comparison operand is not a refusal;
      * the call must not be a lookup (`_NOT_A_REFUSAL`);
      * the companions include the arguments of any ENCLOSING call, because a
        refusal is routinely nested inside the report that carries the paths
        (``_report(..., inputs={...}, findings=[_finding(RULE_ID, ...)])``).
        Reading the inner call alone reports the outer report's disclosure as
        missing.
    """
    parents: Dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[id(c)] = n

    out: List[Tuple[int, str, List[ast.AST]]] = []
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        if _func_name(call.func) in _NOT_A_REFUSAL:
            continue
        for i, arg in enumerate(call.args):
            if not (isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and ABSENCE_RULE_ID.match(arg.value)):
                continue
            companions: List[ast.AST] = [
                a for j, a in enumerate(call.args) if j != i]
            companions += [kw.value for kw in call.keywords]
            # keyword NAMES are disclosure too: `note(RULE_ID, path=str(mj))`
            # says where it looked in the keyword, not in a value.
            companions += [ast.Constant(value=kw.arg) for kw in call.keywords
                           if kw.arg]
            # walk out to the enclosing call(s), at most two levels
            node: Any = call
            for _ in range(6):
                node = parents.get(id(node))
                if node is None:
                    break
                if isinstance(node, ast.Call):
                    companions += list(node.args)
                    companions += [kw.value for kw in node.keywords]
                    companions += [ast.Constant(value=kw.arg)
                                   for kw in node.keywords if kw.arg]
                    break
            out.append((call.lineno, arg.value, companions))
            break
    return out


def _enclosing_function(tree: ast.AST, lineno: int) -> ast.AST:
    """The innermost function containing `lineno`, else the module."""
    best: ast.AST = tree
    best_span = -1
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(n, "end_lineno", None) or n.lineno
            if n.lineno <= lineno <= end:
                span = end - n.lineno
                if best_span < 0 or span < best_span:
                    best, best_span = n, span
    return best


def scan(root: Path, include_tests: bool = False) -> Dict[str, Any]:
    """Parse every shipped program under `root` and classify its absence
    verdicts.

    `tests/` is EXCLUDED by default and the exclusion is a scoping decision,
    not an oversight: a test constructs refusals as FIXTURES, deliberately
    minimal, to drive the code under test. Requiring a fixture to disclose a
    search space would flag the very tests that prove this rule.
    """
    files_parsed = 0
    files_unparsable: List[str] = []
    files_skipped_tests = 0
    verdicts: List[Dict[str, Any]] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if not include_tests and "tests" in rel.parts:
            files_skipped_tests += 1
            continue
        try:
            # A SUBJECT's SyntaxWarning is not this gate's verdict. Parsing a
            # file that carries e.g. an invalid escape sequence prints a
            # warning attributed to `<unknown>:<line>`, which lands in this
            # gate's output looking like this gate's finding. Suppressed HERE
            # and only here: a real SyntaxError is still caught below and the
            # file is still counted as NOT scanned, so nothing that could not
            # be read is recorded as clean.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(p.read_text(errors="replace"))
        except SyntaxError:
            files_unparsable.append(str(rel))
            continue
        files_parsed += 1
        for lineno, rule_id, companions in absence_verdicts(tree):
            fn = _enclosing_function(tree, lineno)
            binds = _bindings(fn)
            named = _has_locus_resolved(companions, binds) if companions else False
            verdicts.append({
                "file": str(rel),
                "line": lineno,
                "rule_id": rule_id,
                "names_search_space": named,
            })
    return {
        "files_parsed": files_parsed,
        "files_unparsable": files_unparsable,
        "files_skipped_tests": files_skipped_tests,
        "absence_verdicts": len(verdicts),
        "verdicts": verdicts,
        "silent": [v for v in verdicts if not v["names_search_space"]],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--programs-dir", default=None,
                    help="directory to scan (default: this program's own "
                         "directory, i.e. the plugin's programs/)")
    ap.add_argument("--json", default=None, help="write the full result here")
    ap.add_argument("--explain", action="store_true",
                    help="print the locus vocabulary and exit 0")
    a = ap.parse_args(argv)

    if a.explain:
        print("locus words:", ", ".join(_LOCUS_WORDS))
        print("locus calls:", ", ".join(sorted(_LOCUS_CALLS)))
        print("absence rule-id pattern:", ABSENCE_RULE_ID.pattern)
        return 0

    root = Path(a.programs_dir) if a.programs_dir else Path(__file__).resolve().parent
    if not root.is_dir():
        print(f"=== {PROGRAM} ===")
        print(f"  NOT CHECKED: {root} is not a directory, so this gate parsed "
              f"nothing and scanned nothing. A check that could not look has "
              f"not passed.")
        return 2

    res = scan(root)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2) + "\n")

    print(f"=== {PROGRAM} ===")
    print(f"  files parsed     : {res['files_parsed']}")
    print(f"  absence verdicts : {res['absence_verdicts']}")
    print(f"  naming a locus   : "
          f"{res['absence_verdicts'] - len(res['silent'])}")
    if res["files_unparsable"]:
        print(f"  unparsable files : {len(res['files_unparsable'])} "
              f"(not scanned, and not counted as clean): "
              f"{res['files_unparsable'][:5]}")

    if res["files_parsed"] == 0:
        print("  NOT CHECKED: nothing under this directory parsed, so the "
              "population is empty for a reason that is not 'the repo is "
              "clean'.")
        return 2

    if res["absence_verdicts"] == 0:
        print("  NOT CHECKED: no absence verdict was found at all. This "
              "program's subject is absent, which is not the same as every "
              "absence verdict being well-formed.")
        return 2

    if res["silent"]:
        print(f"  FAIL: {len(res['silent'])} absence verdict(s) name no search "
              f"space. 'Not found' that does not say where it looked cannot be "
              f"told apart from 'not looked for':")
        for v in res["silent"]:
            print(f"    {v['file']}:{v['line']}  {v['rule_id']}")
        return 1

    print("  PASS: every absence verdict names where it looked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
