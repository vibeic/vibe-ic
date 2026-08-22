#!/usr/bin/env python3
"""An environment pointer that overrules a location the caller NAMED.

THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE WIRED AS A BLOCKING CHECK.
=======================================================================
The gate for this rule is
`programs/explicit_argument_outranks_the_environment_pointer.py`.
That one REFUSES: it runs a narrow population with no inventory and goes red
on a live defect. This
file does something different and complementary — it reports the WIDE
population, the classification, and the debt recorded against it.

Both were written independently from the same capture record, by two lanes that
could not see each other's tree, and on this tree they returned opposite
verdicts. That is not a bug in either: a wide population with recorded waivers
PASSES today with the debt written down, and a narrow population with no
inventory FAILS today because the debt refuses. Only one of those is a gate.
The ruling (2026-08-22) gave the NAME to the refusing one, and gave this one the
job it was actually doing.

So: exit status here is INFORMATIONAL. The default is 0 whatever is found,
because a census that exits non-zero gets wired as a gate by the next person who
reads the exit code. `--strict` restores a refusing exit for a caller who
deliberately wants one; nothing in the flow should pass it.



CENSUS — informational. The gate is `programs/explicit_argument_outranks_the_environment_pointer.py`.

WHAT IT ASKS THE REPOSITORY
===========================
A pointer read from the environment may replace a location that is ABSENT. It
may never replace one the caller named on the command line. A program that lets
the pointer win measures a tree the caller did not ask about and publishes the
verdict under the caller's name — and the louder the pointer's tree, the more
convincing the wrong answer looks.

MEASURED: a checker given an explicit two-path subject instead reported a pass
over 8309 tracked paths of a shared tree. Binding the shared corpus and testing
against fixtures become mutually exclusive, so the fixture's own defect is
never seen.

THE PREDICATE — GUARD POLARITY, NOT PRESENCE
============================================
A finding is an assignment that writes an ENVIRONMENT-derived value onto a
PARSED-ARGUMENT ATTRIBUTE (`args.<opt> = <from os.environ>`), where the guard
around it requires that argument to be PRESENT.

The polarity is the whole rule, and one file carries both shapes side by side:

    if _env_tree and args.tree:          <- fires when the caller NAMED a tree
        args.tree = _env_tree                THE DEFECT

    elif _env_tree and not args.tree:    <- fires when nothing was named
        args.tree = _env_tree                CORRECT — the pointer fills a gap

A rule keyed on "assigns from the environment onto an argument" flags both and
is useless. A rule keyed on the guard requiring the argument to be ABSENT
separates them, and this one does.

THE TARGET IS AN ATTRIBUTE, WHICH IS WHY A NAME-ONLY SCAN MISSES IT. The first
version of this predicate tracked `root = args.root` bindings and found ZERO,
because the live instance writes back onto the namespace itself. Tracking
`args.<opt>` as an assignment target is what makes the rule see its own
subject.

WHAT THE REMEDY IS
==================
Route the consumer through the resolver that already states the rule — the
pointer applies only when the named location is not a directory — and announce
BOTH which location was scanned and which pointer was set and not followed.
Announcing the override is not sufficient by itself: the live instance already
prints `note: <ENV> overrides --tree ...` and still answers about the wrong
tree.

EXIT
====
  0  no pointer outranks an explicit argument
  1  a NEW one, or a stale inventory row
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

_INVENTORY_NAME = "env_pointer_override_inventory.json"

#: The names an argparse namespace is conventionally bound to here.
_NAMESPACES = ("args", "a", "opts", "ns", "parsed", "cfg")


def _reads_environment(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "getenv":
                return True
            if n.func.attr == "get" and isinstance(n.func.value, ast.Attribute) \
                    and n.func.value.attr == "environ":
                return True
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) \
                and n.value.attr == "environ":
            return True
        # a local already bound from the environment, by the repo's convention
        if isinstance(n, ast.Name) and (n.id.startswith("_env")
                                        or n.id.startswith("env_")):
            return True
    return False


def _parents(tree: ast.AST) -> Dict[int, ast.AST]:
    out: Dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            out[id(c)] = n
    return out


def _guard_test(pm: Dict[int, ast.AST], node: ast.AST) -> Optional[str]:
    """The `if` test that controls this statement, as source."""
    cur = node
    for _ in range(6):
        p = pm.get(id(cur))
        if p is None:
            return None
        if isinstance(p, ast.If) and any(x is cur for x in p.body):
            try:
                return ast.unparse(p.test)
            except Exception:                    # noqa: BLE001
                return ""
        cur = p
    return None


def _requires_present(test: str, attr: str) -> bool:
    """True when the guard fires because the argument WAS given.

    The absent forms are the remedy and must never be flagged:
        not args.tree        args.tree is None        args.tree in (None, "")
    """
    if not test:
        return False
    a = re.escape(attr)
    absent = (re.search(rf"not\s+\w+\.{a}\b", test)
              or re.search(rf"\w+\.{a}\s+is\s+None", test)
              or re.search(rf"\w+\.{a}\s+in\s*\(", test))
    if absent:
        return False
    return bool(re.search(rf"\b\w+\.{a}\b", test))


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    assignments = 0
    for base in (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                 root / "tools"):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "tests" in p.parts or "node_modules" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            parsed += 1
            pm = _parents(tree)
            rel = p.relative_to(root).as_posix()
            for st in ast.walk(tree):
                if not (isinstance(st, ast.Assign) and len(st.targets) == 1):
                    continue
                t = st.targets[0]
                if not (isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id in _NAMESPACES):
                    continue
                if not _reads_environment(st.value):
                    continue
                assignments += 1
                test = _guard_test(pm, st) or ""
                if _requires_present(test, t.attr):
                    findings.append({"file": rel, "line": st.lineno,
                                     "argument": t.attr, "guard": test[:80]})
    return findings, {"modules_parsed": parsed,
                      "env_assignments_onto_an_argument": assignments,
                      "pointer_outranks_argument": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['argument']}"


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
    ap.add_argument("--strict", action="store_true",
                    help="restore a refusing exit; a census "
                         "is informational by default")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] explicit_argument_outranks_the_environment_"
                  "pointer: no repository root. NOT a pass.", file=sys.stderr)
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
        print(f"[CANNOT DETERMINE] explicit_argument_outranks_the_environment_"
              f"pointer: the walk did not complete ({type(exc).__name__}: "
              f"{exc}). NOT a pass.", file=sys.stderr)
        return 2

    print(f"  modules parsed:                    {denom['modules_parsed']}")
    print(f"  env writes onto a parsed argument: "
          f"{denom['env_assignments_onto_an_argument']}")
    print(f"  pointer outranks the argument:     "
          f"{denom['pointer_outranks_argument']}")
    print(f"  inventory rows applied:            {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[CENSUS] {len(new)} environment pointer(s) overrule a location "
              f"the caller named:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  sets --{f['argument']} from "
                      f"the environment under `if {f['guard']}`")
        print("\n  That guard fires BECAUSE the caller named the location. A "
              "pointer may fill\n  an absent location and never replace a named "
              "one — invert the guard to the\n  absent form, and announce both "
              "what was scanned and what was not followed.")
    if stale:
        rc = 1
        print(f"\n[CENSUS] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print(f"[CENSUS] {len(findings)} site(s) classified, "
              f"{len(known)} recorded as known debt, "
              f"{len(new)} unrecorded. This is a count, not a "
              f"verdict — the gate is programs/explicit_argument_outranks_the_environment_pointer.py.")
    if rc and not a.strict:
        print("\n  CENSUS: reported, not refused. The gate for this rule is\n"
              "  programs/explicit_argument_outranks_the_environment_pointer.py — run that for a verdict.")
        return 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
