#!/usr/bin/env python3
"""A control whose reference point is a name that moves.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A negative control has to be built from a state that stays legitimately
vulnerable. When the reference version is fetched by a BRANCH name, the
reference moves the moment the fix lands there, and the control begins
asserting that a repaired program is still broken.

The failure is silent in the direction that matters. The control stops
discriminating and reads as a test that is merely wrong, rather than as
coverage that has been withdrawn.

The same predicate covers the coverage-deriving form: a guard whose SUBJECT SET
comes from a diff against a moving name collects a different population in
every clone. One tree, two answers, and the difference surfaces as a changed
collection count rather than as a defect.

THE PREDICATE
=============
Parse every test and program. For each process call whose argv names `git`,
find the subcommand and the arguments that subcommand consumes as a REVISION.
Refuse when such an argument is branch-shaped:

    origin/<anything>   upstream/<anything>   main   master   develop
    <name>@{u}          @{upstream}           <name>@{push}

Out of scope by construction: `git rev-parse --abbrev-ref` and
`--symbolic-full-name`, which return the NAME of a ref rather than an object.
Asking which branch the upstream is cannot be a reference version and cannot
derive a subject set.

ACCEPTED, and this is the discriminator that makes the rule usable: the
working-tree pointer (`HEAD`, `HEAD~1`, a bare sha) against a fixture
repository the caller has just created. There the pointer is immutable IN
CONTEXT. The discriminator is the BRANCH SHAPE, not the presence of a revision
— 30 of the 31 revision-reading calls measured on the capture commit read a
working-tree pointer against a fixture and are correctly silent.

WHY A PARSE AND NOT A GREP
==========================
The naive form of this search — a regular expression for `origin/main` over the
same corpus — was measured at 15 sites across 12 files, 13 of them PROSE inside
docstrings. A rule whose positives are 87% comments is not a rule.

EXIT
====
  0  no branch-shaped revision outside the inventory
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

_INVENTORY_NAME = "mutable_ref_reference_inventory.json"

#: git subcommands that consume a revision in a positional slot.
_REV_SUBCOMMANDS = {
    "show": 1, "rev-parse": 1, "log": 1, "diff": 1, "cat-file": 2,
    "merge-base": 1, "checkout": 1, "rev-list": 1, "describe": 1,
    "ls-tree": 1, "archive": 1, "restore": 1, "switch": 1, "reset": 1,
}

_BRANCH_SHAPED = re.compile(
    r"""^(?:
          (?:origin|upstream|remotes/[^/\s]+)/[^\s:]+     # remote-tracking
        | (?:main|master|develop|trunk)                   # bare branch name
        | [^\s:]*@\{(?:u|upstream|push)\}                 # upstream shorthand
        )
        (?:[~^][0-9]*)?$""",
    re.VERBOSE,
)

_SPAWNERS = ("run", "call", "check_call", "check_output", "Popen", "getoutput")

#: `os.system` / `os.popen` are spawns too, and `os.system` is the archetypal
#: DISCARDED status: it returns an exit code and has no `check=` at all. They
#: are matched only on the `os` module, so an unrelated `.system()` method on
#: some other object is not a spawn.
#:
#: ADDED 2026-08-22 by an audit of this file's OWN enumerations, prompted by
#: six instrument errors in one session that were all the same shape: a list of
#: the cases I expected, not of the cases the tree uses. There are ZERO real
#: `os.system` call sites today — both occurrences are strings inside test
#: fixtures — so this closes a latent gap and changes no finding.
_OS_SPAWNS = ("system", "popen")


def _is_os_spawn(node) -> bool:
    f = getattr(node, "func", None)
    return (isinstance(f, ast.Attribute) and f.attr in _OS_SPAWNS
            and isinstance(f.value, ast.Name) and f.value.id == "os")



def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # An f-string: keep the literal parts so `f"origin/main:{p}"` is read.
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _argv_strings(node: ast.AST) -> Optional[List[Optional[str]]]:
    """The argv list of a spawn call, as literal strings where they are literal."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    attr = f.attr if isinstance(f, ast.Attribute) else (
        f.id if isinstance(f, ast.Name) else None)
    if not (attr in _SPAWNERS or _is_os_spawn(node)):
        return None
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        return [_const_str(e) for e in first.elts]
    s = _const_str(first)
    if s is not None:
        return s.split()
    return None


def _branch_shaped_revision(argv: List[Optional[str]]) -> Optional[Tuple[str, str]]:
    """(subcommand, offending revision) or None."""
    try:
        gi = next(i for i, a in enumerate(argv)
                  if a and a.rsplit("/", 1)[-1] == "git")
    except StopIteration:
        return None
    rest = argv[gi + 1:]
    # skip global options like -C <path>
    i = 0
    while i < len(rest) and rest[i] and rest[i].startswith("-"):
        i += 2 if rest[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(rest) or not rest[i]:
        return None
    sub = rest[i]
    if sub not in _REV_SUBCOMMANDS:
        return None
    # `rev-parse --abbrev-ref` / `--symbolic-full-name` returns a NAME, not an
    # object. Asking which branch the upstream is cannot be a reference
    # version and cannot derive a subject set, so it is out of scope by
    # construction rather than by exemption.
    if sub == "rev-parse" and any(
            a in ("--abbrev-ref", "--symbolic-full-name") for a in rest if a):
        return None
    for a in rest[i + 1:]:
        if a is None or a.startswith("-"):
            continue
        head = a.split(":", 1)[0]
        if _BRANCH_SHAPED.match(head):
            return sub, a
    return None


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    revision_calls = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "node_modules" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            parsed += 1
            rel = p.relative_to(root).as_posix()
            for n in ast.walk(tree):
                argv = _argv_strings(n)
                if not argv:
                    continue
                if not any(a and a.rsplit("/", 1)[-1] == "git" for a in argv):
                    continue
                revision_calls += 1
                hit = _branch_shaped_revision(argv)
                if hit:
                    findings.append({"file": rel, "line": n.lineno,
                                     "subcommand": hit[0], "revision": hit[1]})
    return findings, {"modules_parsed": parsed,
                      "git_process_calls": revision_calls,
                      "branch_shaped_revisions": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['subcommand']}::{f['revision']}"


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
            print("[CANNOT DETERMINE] reference_control_resolved_through_a_"
                  "mutable_ref: no repository root. NOT a pass.", file=sys.stderr)
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
        print(f"[CANNOT DETERMINE] reference_control_resolved_through_a_mutable_"
              f"ref: the walk did not complete ({type(exc).__name__}: {exc}). "
              f"NOT a pass.", file=sys.stderr)
        return 2

    print(f"  modules parsed:            {denom['modules_parsed']}")
    print(f"  git process calls:         {denom['git_process_calls']}")
    print(f"  branch-shaped revisions:   {denom['branch_shaped_revisions']}")
    print(f"  inventory rows applied:    {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} reference(s) resolve through a name that "
              f"moves:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  git {f['subcommand']} "
                      f"{f['revision']}")
        print("\n  Name the object, not the branch. A control built on a moving "
              "name stops\n  discriminating the moment the fix lands there, and "
              "reads as merely wrong.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] reference_control_resolved_through_a_mutable_ref: every "
              "revision read is immutable or inventoried.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
