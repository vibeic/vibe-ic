#!/usr/bin/env python3
"""prepared_checkout_states_the_revision_it_holds.py — which commit is in there.

WHY THIS EXISTS
===============
`landing_tier_checkout_preflight.py` proves a prepared checkout is SELF-CONTAINED.
It says nothing about WHICH REVISION that self-contained checkout holds, and those
are different facts.

MEASURED: automation prepared a checkout by cloning a branch NAME from a local
path. The local branch position was stale, the commit under test was not in the
resulting tree, and the gate run produced a complete, internally consistent,
entirely confident verdict about the wrong revision. Every gate passed. Nothing
in the record said which commit had been judged.

A verdict about an unnamed revision is not a weak verdict. It is not a verdict.

TWO ARMS, BECAUSE THE DEFECT HAS TWO ENDS
=========================================
SOURCE ARM (default)   every site that selects a REVISION with `git checkout`
                       must inspect the outcome — `check=True`, an explicit
                       returncode test, or a following `rev-parse HEAD`. A site
                       that checks out and walks on has assumed the revision it
                       never confirmed.

                       `git checkout -- <path>` is NOT in the population. That
                       restores a file; it selects no revision. Measured on this
                       repository, 2 of the 4 real checkout sites are that shape,
                       and counting them would have made this rule's denominator
                       a lie in the flattering direction.

RUNTIME ARM (--root)   given a prepared checkout and the revision it is supposed
                       to hold, confirm it.

                       A 40-hex SHA is absolute and is resolved in the tree. A
                       REF NAME is resolved AT THE UPSTREAM and never against the
                       tree's own copy of it, because the tree's copy is the
                       thing that goes stale — and a stale ref resolves perfectly
                       well, which is why this must not be a fallback. Without
                       --upstream a name cannot be confirmed at all, and that is
                       rc 2, not a pass.

DID NOT LOOK IS NOT LOOKED AND FOUND NOTHING
============================================
    rc 0   confirmed: HEAD is the expected revision / every site inspects.
    rc 1   refuted: HEAD is a DIFFERENT revision / a site never looks.
    rc 2   NOT CHECKED — the tree is not a repository, the expected revision
           cannot be resolved, the upstream cannot be reached, the population is
           empty, or a candidate could not be parsed.
    rc 3   bad invocation.

rc 1 and rc 2 are the whole design. "The checkout holds the wrong commit" and "I
could not establish which commit it holds" are the two states the original defect
merged, and merging them is what let a confident verdict be published about a
tree nobody had identified. A checkout that cannot prove its revision is
UNDETERMINED, never correct.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

NAME = "prepared_checkout_states_the_revision_it_holds"
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return True
    parts = rel.split("/")
    return "tests" in parts or parts[-1].startswith("test_")


def _git(root: Path, args: Sequence[str]) -> Tuple[int, str]:
    try:
        cp = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 128, str(exc)
    return cp.returncode, (cp.stdout or cp.stderr).strip()


# ---------------------------------------------------------------- source arm

class Finding:
    def __init__(self, path: str, line: int, why: str):
        self.path, self.line, self.why = path, line, why

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}: a revision is checked out and the "
                f"outcome is never inspected — {self.why}. A checkout that "
                f"silently failed leaves the tree on its previous revision, and "
                f"every measurement after it is about a commit nobody named.")


def _is_git_checkout(elts: Sequence[ast.expr]) -> bool:
    consts = [e.value for e in elts if isinstance(e, ast.Constant)
              and isinstance(e.value, str)]
    if "git" not in consts or "checkout" not in consts:
        return False
    # `git checkout -- <path>` restores a file. It selects no revision, so it is
    # not in this population; counting it would inflate the denominator with
    # sites the rule has no opinion about.
    return "--" not in consts


def _inspected(call: ast.Call, tree: ast.AST) -> bool:
    """True when this subprocess call's outcome is looked at."""
    for kw in call.keywords:
        if kw.arg == "check" and isinstance(kw.value, ast.Constant) \
                and kw.value.value is True:
            return True
    # Assigned to a name that is later tested, or used directly in a test.
    parent_fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            for sub in ast.walk(node):
                if sub is call:
                    parent_fn = node
                    break
    if parent_fn is None:
        return False
    src = ast.dump(parent_fn)
    # returncode inspected, or HEAD re-resolved somewhere in the same function.
    return ("returncode" in src or "'rev-parse'" in src
            or '"rev-parse"' in src or "check_call" in src
            or "check_output" in src)


def _scan_python(text: str, rel: str) -> Tuple[List[Finding], int, Optional[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], 0, f"could not be parsed as Python ({exc.msg})"
    findings: List[Finding] = []
    sites = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        argv = None
        for a in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(a, (ast.List, ast.Tuple)) and _is_git_checkout(a.elts):
                argv = a
                break
        if argv is None:
            continue
        sites += 1
        if not _inspected(node, tree):
            findings.append(Finding(rel, node.lineno,
                                    "no check=True, no returncode test and no "
                                    "rev-parse of the resulting HEAD"))
    return findings, sites, None


def audit_source(root: Path) -> Tuple[List[Finding], List[str], int]:
    findings: List[Finding] = []
    unread: List[str] = []
    sites = 0
    for path in sorted(root.rglob("*.py")):
        if not path.is_file() or _skip(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unread.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        if "checkout" not in text:
            continue
        rel = path.relative_to(root).as_posix()
        f, n, err = _scan_python(text, rel)
        if err:
            unread.append(f"{rel}: {err}")
            continue
        findings.extend(f)
        sites += n
    return findings, unread, sites


# --------------------------------------------------------------- runtime arm

_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def _is_sha(rev: str) -> bool:
    """True for an absolute object name. A sha means the same thing everywhere."""
    return bool(_SHA.match(rev.strip()))


def confirm_revision(root: Path, expect: str,
                     upstream: Optional[str] = None) -> Tuple[int, str]:
    """(rc, sentence) — does `root` hold `expect`?"""
    rc, _ = _git(root, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        return 2, (f"NOT CHECKED — {root} is not a git checkout this tool can "
                   f"interrogate, so which revision it holds was not "
                   f"established. This is not a pass.")
    rc, head = _git(root, ["rev-parse", "HEAD"])
    if rc != 0 or not head:
        return 2, (f"NOT CHECKED — {root} has no resolvable HEAD "
                   f"(an empty or broken repository). Not a pass.")
    # A SYMBOLIC EXPECTATION IS RESOLVED AT THE UPSTREAM, NEVER AGAINST THE
    # TREE'S OWN COPY OF IT. This is the whole measured defect and the first
    # version of this function got it backwards.
    #
    # MEASURED against a real pair of repositories: clone `up` while its `main`
    # is A, advance upstream `main` to B (the commit under test), leave the
    # clone's HEAD at A. The clone does NOT contain B. Asking this function for
    # `main` resolved `main` INSIDE THE CLONE -- which is a stale ref that
    # resolves perfectly well to A -- so want == head and it answered
    #
    #     CONFIRMED -- <clone> holds c6c0f8390bb8, which is 'main'.   rc 0
    #
    # A false pass on precisely the case this program exists for: "automation
    # prepares a checkout by cloning a branch NAME from a local path, the local
    # branch position is stale, and the commit under test is absent from the
    # resulting tree." A stale ref never fails to resolve, so the upstream
    # fallback below could never fire.
    #
    # A 40-hex sha is absolute and means the same thing everywhere, so it is
    # still resolved locally. A NAME means "whatever the upstream calls that
    # today", and only the upstream can say.
    if not _is_sha(expect):
        if not upstream:
            return 2, (f"NOT CHECKED — {expect!r} is a REF NAME, and the only "
                       f"copy of it here is {root}'s own, which is exactly the "
                       f"thing that goes stale. A name cannot be confirmed "
                       f"against the tree being checked. Pass --upstream to say "
                       f"where {expect!r} is defined. Not a pass.")
        urc, uout = _git(root, ["ls-remote", upstream, expect])
        if urc != 0 or not uout:
            return 2, (f"NOT CHECKED — {expect!r} could not be resolved at "
                       f"{upstream}, so what {root} should hold was never "
                       f"established. A checkout that cannot prove its revision "
                       f"is undetermined, not correct.")
        want = uout.split()[0]
        if head == want:
            return 0, (f"CONFIRMED — {root} holds {head[:12]}, which is what "
                       f"{upstream} calls {expect!r}.")
        present = _git(root, ["cat-file", "-e", want])[0] == 0
        return 1, (f"REFUTED — {root} holds {head[:12]}, but {upstream} says "
                   f"{expect!r} is {want[:12]}"
                   f"{'' if present else ', which this tree does not even contain'}"
                   f". The tree was prepared for a revision it does not hold, so "
                   f"every gate run in it measured a different commit.")

    rc, want = _git(root, ["rev-parse", "--verify", "--quiet", f"{expect}^{{commit}}"])
    if rc != 0 or not want:
        # The tree does not contain the revision at all. That is exactly the
        # measured defect — but it is only a REFUTATION if we can name what the
        # revision should have been, which needs the upstream.
        if upstream:
            urc, uout = _git(root, ["ls-remote", upstream, expect])
            if urc != 0 or not uout:
                return 2, (f"NOT CHECKED — {expect!r} is absent from {root} AND "
                           f"the upstream {upstream} could not be reached to say "
                           f"what it should be. The revision could not be "
                           f"confirmed; it was not shown to be wrong either.")
            want = uout.split()[0]
            return 1, (f"REFUTED — {root} does not contain {expect!r} "
                       f"({want[:12]} on {upstream}). HEAD is {head[:12]}. The "
                       f"tree was prepared for a revision it does not hold, so "
                       f"every gate run in it measured a different commit.")
        return 2, (f"NOT CHECKED — {expect!r} does not resolve in {root} and no "
                   f"--upstream was given to resolve it against. Absent from "
                   f"this tree is not the same fact as wrong.")
    if head == want:
        return 0, (f"CONFIRMED — {root} holds {head[:12]}, which is {expect!r}.")
    return 1, (f"REFUTED — {root} holds {head[:12]}, but it was prepared for "
               f"{expect!r} = {want[:12]}. A verdict produced here is about "
               f"{head[:12]} whatever the record says.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tree", nargs="?", default=".",
                    help="source tree to scan (default: cwd)")
    ap.add_argument("--root", type=Path,
                    help="runtime arm: a prepared checkout to interrogate")
    ap.add_argument("--expect", help="runtime arm: the revision it should hold")
    ap.add_argument("--upstream",
                    help="runtime arm: remote to resolve --expect against")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3

    if args.root is not None or args.expect is not None:
        if args.root is None or args.expect is None:
            print(f"[{NAME}] BAD INVOCATION — the runtime arm needs both --root "
                  f"and --expect.", file=sys.stderr)
            return 3
        if not args.root.is_dir():
            print(f"[{NAME}] BAD INVOCATION — {args.root} is not a directory.",
                  file=sys.stderr)
            return 3
        try:
            rc, sentence = confirm_revision(args.root, args.expect, args.upstream)
        except Exception as exc:                    # noqa: BLE001
            print(f"[{NAME}] NOT CHECKED — the check itself failed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"[{NAME}] {sentence}",
              file=sys.stderr if rc != 0 else sys.stdout)
        return rc

    tree = Path(args.tree)
    if not tree.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.tree!r} is not a directory.",
              file=sys.stderr)
        return 3
    try:
        findings, unread, sites = audit_source(tree)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for u in unread:
        print(f"NOT CHECKED — {u}", file=sys.stderr)
    print(f"examined {sites} revision-selecting checkout site(s) under "
          f"{str(tree)!r}")
    if sites == 0:
        print(f"[{NAME}] NOT CHECKED — no revision-selecting checkout site was "
              f"found, so nothing was judged.", file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a prepared checkout never confirms its revision")
        return 1
    if unread:
        print(f"[{NAME}] NOT CHECKED — a candidate file could not be read")
        return 2
    print(f"[{NAME}] PASS — every revision-selecting checkout inspects its outcome")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
