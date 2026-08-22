#!/usr/bin/env python3
"""local_clone_does_not_borrow_objects.py — a prepared checkout owns its objects.

WHY THIS EXISTS
===============
`landing_tier_checkout_preflight.py` refuses to start a tier in a checkout whose
`.git/objects/info/alternates` exists, because the objects live in ANOTHER
repository and a `git gc` there can delete them mid-run. That refusal is correct
and it is enforced on the checkout AFTER it has been built.

Nothing enforced the other end. A preparation site that builds its checkout with
`--shared` or `--reference` produces exactly the shape the preflight refuses, and
the contradiction is only discovered an hour later, by which time the honest
verdict about the run is that nothing was measured.

WHAT IS AND IS NOT A FINDING — THE NARROWING, STATED
====================================================
The capture record this implements asked for a scan refusing any local clone
"that does not disable hardlinked and shared object storage". Implemented as
written it is WRONG on this repository, and the counter-example is the repo's own
primary preparation site:

    tools/ci/gatekeeper_status_poller.prepare_gate_checkout()
        "`--no-hardlinks` is deliberately NOT used: it would copy the whole
         object store to buy nothing, because a hardlinked inode already
         outlives the source's own `git gc`."

That reasoning is correct, and the preflight agrees with it in as many words —
it ACCEPTS a hardlink clone and PRINTS `git clone <root> <dest>` as its own
remedy. A rule that reddens the remedy its sibling gate prints is a false alarm
generator, so the rule is narrowed here to the thing the preflight actually
refuses:

    FINDING          a clone that creates OBJECT ALTERNATES — `--shared`,
                     `-s`, `--reference`, `--reference-if-able`. This is the
                     shape the preflight refuses, so a site that builds it has
                     scheduled a guaranteed mid-tier refusal.
    NOT A FINDING    hardlinks (the default for a local path). Immutable inodes,
                     survive the source's `gc`, accepted by the preflight, and
                     named as the remedy by two programs.

WHAT THIS SCAN CAN AND CANNOT SEE — STATED, BECAUSE A PASS MUST BE LEGIBLE
==========================================================================
It reads argv expressions: a list/tuple literal, `+` concatenation of them, and
a simple name bound to a literal list. That covers how preparation sites in this
tree are actually written, INCLUDING the `["git","clone"] + OPTS` form, which an
earlier version of this scan reported as PASS.

It cannot see an option assembled at runtime from a value it cannot constant-fold
— read from a config file, computed in a branch, passed in as a parameter. There
is no scan that can. That residue is why `landing_tier_checkout_preflight` exists
and runs on the built checkout: this gate refuses the shape at the site, the
preflight refuses it at the artefact, and neither alone is complete.

DID NOT LOOK IS NOT LOOKED AND FOUND NOTHING
============================================
These are separate exit codes and they never collapse:

    rc 0   the scan read N>0 clone sites and none of them borrows objects.
    rc 1   a clone site borrows objects.
    rc 2   NOT CHECKED — either no clone site was found at all (a scan over an
           empty population certifies nothing: the same rc a wrong --root
           produces, which is the point), or a candidate file could not be read
           or parsed. An unreadable file is not a clean file.
    rc 3   bad invocation.

A file that cannot be parsed is reported and forces rc 2 even when other files
were clean, because "I read every site" is the claim rc 0 makes.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

NAME = "local_clone_does_not_borrow_objects"

# The options that make git populate objects/info/alternates instead of
# copying or hardlinking. These, and only these, are what the preflight refuses.
BORROWING_OPTIONS = ("--shared", "-s", "--reference", "--reference-if-able")

SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}


def _skip(path: Path, root: Path) -> bool:
    """True for a path that is not a checkout-PREPARATION site.

    TESTS ARE EXCLUDED, AND THAT IS THE RULE, NOT AN EVASION. Measured on this
    repository the only two `--shared` clones in the whole tree are:

        programs/tests/test_landing_tier_checkout_preflight.py:119
        tools/ci/test_gatekeeper_status_poller.py:286

    Both BUILD a borrowing clone on purpose, to prove that the preflight refuses
    it. They are that gate's negative controls — the evidence it works. Reddening
    them would mean this checker's PASS could only be bought by deleting the
    proof that its sibling gate has teeth, which is the wrong trade in every
    direction. The rule is about a site that PREPARES a checkout for real work.
    """
    rel = path.relative_to(root).as_posix()
    if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return True
    parts = rel.split("/")
    if "tests" in parts or parts[-1].startswith("test_"):
        return True
    return False


class Finding:
    def __init__(self, path: str, line: int, option: str, snippet: str):
        self.path, self.line, self.option, self.snippet = path, line, option, snippet

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}: a clone passes {self.option!r}, which "
                f"creates objects/info/alternates — the exact shape "
                f"landing_tier_checkout_preflight refuses, so this checkout is "
                f"scheduled to be refused after it is built. Use a plain local "
                f"clone (hardlinks, which the preflight accepts). [{self.snippet}]")


class Unread:
    def __init__(self, path: str, why: str):
        self.path, self.why = path, why

    def __str__(self) -> str:
        return f"{self.path}: NOT CHECKED — {self.why}"


def _is_clone_argv(elts: Sequence[ast.expr]) -> bool:
    """True when a list/tuple of args is a `git clone ...` argv."""
    consts = [e.value for e in elts if isinstance(e, ast.Constant)
              and isinstance(e.value, str)]
    return "git" in consts and "clone" in consts


def _list_constants(tree: ast.AST) -> dict:
    """`{name: [str constants]}` for simple list/tuple assignments.

    MEASURED: without this the scan reported PASS on

        OPTS = ["--quiet", "--shared"]
        subprocess.run(["git", "clone"] + OPTS + [str(src), str(dest)])

    which is a borrowing clone written the way a real preparation site writes
    one. A scan that answers PASS because the offending token sits one
    assignment away is not conservative, it is wrong in the passing direction —
    the same failure this whole capture is about.
    """
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, (ast.List, ast.Tuple)):
            out[node.targets[0].id] = [
                e.value for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return out


def _flatten_argv(node: ast.AST, lists: dict) -> List[str]:
    """Every string constant an argv expression contributes, following `+` and
    simple names bound to literal lists."""
    out: List[str] = []
    if isinstance(node, (ast.List, ast.Tuple)):
        for e in node.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                out.append(e.value)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        out.extend(_flatten_argv(node.left, lists))
        out.extend(_flatten_argv(node.right, lists))
    elif isinstance(node, ast.Name):
        out.extend(lists.get(node.id, []))
    return out


def _scan_python(text: str, rel: str) -> Tuple[List[Finding], Optional[Unread]]:
    """Findings from argv expressions, via AST so a comment can never be one."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], Unread(rel, f"could not be parsed as Python ({exc.msg})")
    lists = _list_constants(tree)
    out: List[Finding] = []
    seen = set()
    for node in ast.walk(tree):
        argv = None
        if isinstance(node, (ast.List, ast.Tuple)):
            argv = node
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            argv = node
        if argv is None:
            continue
        toks = _flatten_argv(argv, lists)
        if "git" not in toks or "clone" not in toks:
            continue
        for opt in BORROWING_OPTIONS:
            if opt not in toks:
                continue
            key = (rel, argv.lineno, opt)
            if key in seen:
                continue
            seen.add(key)
            out.append(Finding(rel, argv.lineno, opt, " ".join(toks)[:90]))
    return out, None


def _scan_shell(text: str, rel: str) -> List[Finding]:
    out: List[Finding] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0]          # a comment is never a finding
        if "git clone" not in line:
            continue
        for opt in BORROWING_OPTIONS:
            # -s is too short to match as a substring; require a word boundary.
            toks = line.replace("=", " ").split()
            if opt in toks:
                out.append(Finding(rel, i, opt, line.strip()[:90]))
    return out


def audit(root: Path) -> Tuple[List[Finding], List[Unread], int]:
    """(findings, unread, sites) over `root`."""
    findings: List[Finding] = []
    unread: List[Unread] = []
    sites = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _skip(path, root):
            continue
        if path.suffix not in (".py", ".sh"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            # Only a file that could contain a clone site counts as unread.
            try:
                blob = path.read_bytes()
            except OSError:
                unread.append(Unread(path.relative_to(root).as_posix(), str(exc)))
                continue
            if b"clone" in blob:
                unread.append(Unread(path.relative_to(root).as_posix(),
                                     f"could not be decoded as UTF-8 ({exc})"))
            continue
        if "clone" not in text:
            continue
        rel = path.relative_to(root).as_posix()
        sites += 1
        if path.suffix == ".py":
            f, u = _scan_python(text, rel)
            findings.extend(f)
            if u is not None:
                unread.append(u)
        else:
            findings.extend(_scan_shell(text, rel))
    return findings, unread, sites


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="repository tree to scan (default: cwd)")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3
    root = Path(args.root)
    if not root.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.root!r} is not a directory.",
              file=sys.stderr)
        return 3
    try:
        findings, unread, sites = audit(root)
    except Exception as exc:                       # noqa: BLE001
        # An escaped traceback that becomes a finding is an unearned claim.
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for u in unread:
        print(str(u), file=sys.stderr)
    # Denominator on its own line, before the verdict. The verdict line carries
    # no count, so a host with a different file population still prints an
    # identical last line.
    print(f"examined {sites} file(s) containing a clone under {str(root)!r}")
    if sites == 0:
        print(f"[{NAME}] NOT CHECKED — no clone site was found, so nothing was "
              f"judged. An empty population is not a clean one.", file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a prepared checkout borrows its objects")
        return 1
    if unread:
        print(f"[{NAME}] NOT CHECKED — a candidate file could not be read")
        return 2
    print(f"[{NAME}] PASS — no clone site creates object alternates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
