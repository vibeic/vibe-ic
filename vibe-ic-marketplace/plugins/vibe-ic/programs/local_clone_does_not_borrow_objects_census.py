#!/usr/bin/env python3
"""A clone that BORROWS its objects from the repository it was cloned from.

THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE WIRED AS A BLOCKING CHECK.
=======================================================================
The gate for this rule is
`programs/local_clone_does_not_borrow_objects.py`.
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



CENSUS — informational. The gate is `programs/local_clone_does_not_borrow_objects.py`.

WHAT IT ASKS THE REPOSITORY
===========================
`landing_tier_checkout_preflight` refuses a checkout whose
`.git/objects/info/alternates` exists, because those objects live in another
repository and a `git gc` there can delete them mid-tier. A clone prepared with
`--shared` or `--reference` is exactly that shape, so any automation preparing
a checkout that way builds one the preflight will refuse, every time, and the
refusal names the checkout rather than the preparation that made it.

This rule is the producer-side half of that refusal: the option the preflight
demands the absence of is the option no preparation site may pass.

A CORRECTION TO THE RECORD THIS CAME FROM, MEASURED
====================================================
The capture record (`2026-08-21-jcap-chip`) states the mechanism as HARDLINKED
storage and its `fix_action` asks for `--no-hardlinks` at every preparation
site. On this tree that is wrong twice, and both were measured rather than
argued:

  1. A PLAIN LOCAL CLONE DOES NOT BORROW. Driven directly:

        git clone <local>                  -> no objects/info/alternates
        git clone --shared <local>         -> alternates PRESENT
        git clone --no-hardlinks <local>   -> no objects/info/alternates

     Only `--shared` (and `--reference`) produce the file the preflight
     refuses. Hardlinking is not borrowing: a hardlinked inode is immutable and
     outlives the source's own `git gc`, which is why the preflight's own
     docstring says a local hardlink clone "is accepted. That is the cheap
     remedy this refusal names."

  2. THE RECORD'S "zero occurrences" IS STALE. `--no-hardlinks` now appears
     once, in `tools/ci/gatekeeper_status_poller.py`, in a comment saying it is
     "deliberately NOT used: it would copy the whole object store to buy
     nothing." A rule requiring that option would enforce against a decision
     this repository made explicitly and wrote down.

So the slug is right and the mechanism in the prose is not. BORROWING IS
ALTERNATES. This program is built to the slug and to the preflight it pairs
with, and the two cannot drift because they name the same file.

THE PREDICATE
=============
Parse every module and read every shell script. A finding is a `git clone`
invocation — an argv list, a shell command line, or a string command — that
carries `--shared`, `--reference`, `--reference-if-able` or
`--dissociate`-less `--reference`. `--dissociate` is accepted BESIDE
`--reference`, because it borrows during the clone and then absorbs the
objects, leaving no alternates: measured by the same three-way drive above,
extended.

Out of scope by construction, and both were measured as false positives on the
first sweep:

  * A TEST that BUILDS the borrowing shape. Both hits the first sweep returned
    were tests constructing `git clone --shared` precisely to prove the
    preflight refuses it — one of them says so in its own docstring: "Deleting
    the preflight call makes this test red rather than making the refusal
    silently disappear." A test that manufactures the defect to prove the guard
    catches it is the guard working, and flagging it would forbid testing the
    thing this rule is about.
  * A `--reference` that is not an argument to `git Several programs take a `--reference` golden of their own, and the
first version of this predicate flagged one — the discriminator is that the
argv names `git` and `clone`, not that the token appears.

EXIT
====
  0  no clone borrows objects
  1  a NEW one, or a stale inventory row
  2  cannot determine
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_INVENTORY_NAME = "clone_borrows_objects_inventory.json"

#: The options that create `.git/objects/info/alternates`.
_BORROWING = ("--shared", "-s", "--reference", "--reference-if-able")

#: Absorbs the borrowed objects, leaving no alternates behind.
_ABSORBS = "--dissociate"

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
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _argv_of(node: ast.AST) -> Optional[List[Optional[str]]]:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    attr = f.attr if isinstance(f, ast.Attribute) else (
        f.id if isinstance(f, ast.Name) else None)
    if not (attr in _SPAWNERS or _is_os_spawn(node)) or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        return [_const_str(e) for e in first.elts]
    s = _const_str(first)
    if s is not None:
        try:
            return shlex.split(s)
        except ValueError:
            return s.split()
    return None


def _borrows(argv: List[Optional[str]]) -> Optional[str]:
    """The borrowing option in a `git clone` argv, or None."""
    toks = [a for a in argv if a]
    if not any(t.rsplit("/", 1)[-1] == "git" for t in toks):
        return None
    if "clone" not in toks:
        return None
    if _ABSORBS in toks:
        return None
    for t in toks:
        head = t.split("=", 1)[0]
        if head in _BORROWING:
            return head
    return None


_SH_CLONE = re.compile(r"\bgit\s+(?:-[^\s]+\s+)*clone\b[^\n;&|]*")


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    py = sh = clones = 0
    files_walked = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or "node_modules" in p.parts:
                continue
            files_walked += 1
            # A test that BUILDS the shape to prove the guard refuses it is not
            # a preparation site. See "Out of scope by construction".
            if "tests" in p.parts or p.name.startswith("test_"):
                continue
            rel = p.relative_to(root).as_posix()
            if p.suffix == ".py":
                py += 1
                try:
                    tree = ast.parse(p.read_text(encoding="utf-8",
                                                 errors="replace"))
                except (OSError, SyntaxError, ValueError):
                    continue
                for n in ast.walk(tree):
                    argv = _argv_of(n)
                    if not argv:
                        continue
                    toks = [a for a in argv if a]
                    if "clone" in toks and any(
                            t.rsplit("/", 1)[-1] == "git" for t in toks):
                        clones += 1
                    opt = _borrows(argv)
                    if opt:
                        findings.append({"file": rel, "line": n.lineno,
                                         "option": opt, "how": "argv"})
            elif p.suffix == ".sh":
                sh += 1
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in _SH_CLONE.finditer(text):
                    clones += 1
                    try:
                        toks = shlex.split(m.group(0))
                    except ValueError:
                        toks = m.group(0).split()
                    opt = _borrows(toks)
                    if opt:
                        findings.append({
                            "file": rel,
                            "line": text[:m.start()].count("\n") + 1,
                            "option": opt, "how": "shell"})
    return findings, {
        "files_walked": files_walked,
        "python_modules": py, "shell_scripts": sh,
                      "git_clone_invocations": clones,
                      "borrowing_clones": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['option']}::{f['how']}"


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
            print("[CANNOT DETERMINE] local_clone_does_not_borrow_objects: no "
                  "repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            Path(a.json_out).write_text(json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] local_clone_does_not_borrow_objects: the walk "
              f"did not complete ({type(exc).__name__}: {exc}). NOT a pass.",
              file=sys.stderr)
        return 2

    print(f"  python modules parsed:     {denom['python_modules']}")
    print(f"  shell scripts read:        {denom['shell_scripts']}")
    print(f"  git clone invocations:     {denom['git_clone_invocations']}")
    print(f"  borrowing the source:      {denom['borrowing_clones']}")
    print(f"  inventory rows applied:    {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[CENSUS] {len(new)} clone(s) borrow objects from their source:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  git clone {f['option']}")
        print("\n  This writes .git/objects/info/alternates, which "
              "landing_tier_checkout_preflight\n  refuses: a `git gc` in the "
              "source can delete those objects mid-run. Drop the\n  option — a "
              "plain local clone hardlinks immutable objects and is accepted — "
              "or\n  add --dissociate so the clone absorbs them.")
    if stale:
        rc = 1
        print(f"\n[CENSUS] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        # A COUNT OVER AN EMPTY POPULATION IS NOT A COUNT. `[CENSUS] 0 site(s)`
        # is honest only if something was read; over a tree this program parsed
        # NOTHING it is indistinguishable from a clean result. Measured: on an
        # empty tree this returned 0 -- and still 0 under `--strict`, so the
        # "--strict is where a caller asks for the refusal" argument did not cover
        # it either. Exiting 0 is a census's contract for a REAL population, not a
        # licence to report over none.
        if denom.get("files_walked", 0) == 0:
            print("[CANNOT DETERMINE] local_clone_does_not_borrow_objects_census: 0 python modules and 0 shell scripts were read -- "
                  "nothing was read, so the count is not a measurement. NOT a pass.")
            return 2

        print(f"[CENSUS] {len(findings)} site(s) classified, "
              f"{len(known)} recorded as known debt, "
              f"{len(new)} unrecorded. This is a count, not a "
              f"verdict — the gate is programs/local_clone_does_not_borrow_objects.py.")
    if rc and not a.strict:
        print("\n  CENSUS: reported, not refused. The gate for this rule is\n"
              "  programs/local_clone_does_not_borrow_objects.py — run that for a verdict.")
        return 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
