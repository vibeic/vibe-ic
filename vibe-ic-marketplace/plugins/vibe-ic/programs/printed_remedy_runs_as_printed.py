#!/usr/bin/env python3
"""printed_remedy_runs_as_printed.py — a remedy you can paste is a remedy.

WHY THIS EXISTS
===============
A refusal that prints "run this to fix it" makes a promise. When the printed
line omits an argument the entry point requires, following it EXACTLY fails
without ever running the command — and the reader's honest conclusion is that
the refusal itself is broken, not that the message is stale. The refusal loses
its authority at the moment it is most needed.

MEASURED, AND RECORDED IN THIS REPOSITORY'S OWN SOURCE
======================================================
`container_image_provenance.py:145` carries the failure verbatim:

        docker logs: [ERROR] Unexpected option "sleep"

The composed EDA image has an ENTRY POINT that parses the arguments after the
image reference. `--skip` must reach it BEFORE the command, or the entry point
takes the command for one of its own options and refuses it. The command never
runs. The exit is non-zero — so this is not even a silent failure, it is a
confident wrong answer about a tool that was never invoked.

The correct shape is pinned by that program's own test:

        docker run -d --init <ceiling> --name <name> <image> --skip sleep infinity
                                                             ^^^^^^ before the command

WHAT IS A FINDING
=================
    a `docker run` against the EDA image whose first token after the image
    reference is NOT `--skip` — the entry point will consume the command.

WHAT WAS DROPPED, AND WHY — A FALSE FINDING IS A DEFECT
=======================================================
This rule was first written to refuse `docker exec` in a remedy as well, on the
reasoning that it presumes a container the reader has not started. Swept over
this repository it produced NINE findings and every one was wrong. They were
diagnostics REPORTING a failed exec ("docker exec failed: ..."), not
instructions to run one — and one of them was this program's own finding text,
which describes the defect in order to name it.

Telling "run this" from "this failed" inside a string literal is not something
this scan can do, and a rule that reddens a correct error message to protect a
correct remedy is a net loss. The `docker run` ordering rule below stays because
it is decidable from the token order alone.

WHAT THIS SCAN CAN AND CANNOT SEE
=================================
It folds a printed expression: string literals, `+` concatenation, f-string
literal parts, and a simple name bound to a string constant. That covers the
`"... " + IMAGE + " bash"` form, which an earlier version reported as PASS.
An unresolvable part becomes `<x>` rather than being deleted, so tokens that were
never adjacent are never glued into a command nobody printed.

It cannot see a remedy assembled from values it cannot constant-fold. The
residue is real and is why the paired test EXECUTES the remedy shape rather than
only asserting on its text.

STRINGS ONLY, AND ONLY PRINTED ONES
===================================
The scan reads string literals that reach a `print`/`raise`/message builder. A
comment describing the defect, and a docstring quoting a bad command in order to
warn about it, are not remedies and are not findings — this file is full of both
and must not redden itself.

    rc 0   N>0 printed remedies were read and each runs as printed.
    rc 1   a printed remedy cannot run as printed.
    rc 2   NOT CHECKED — empty population, or a file that could not be parsed.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

NAME = "printed_remedy_runs_as_printed"
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

# An image reference for the composed EDA image, in the shapes it is written.
_IMAGE = re.compile(r"(?:\S+/)?(?:vibeic-eda|iic-osic-tools)(?::\S+)?")
_DOCKER_RUN = re.compile(r"docker\s+run\b")
# Placeholders a remedy legitimately leaves for the reader to fill in.
_PLACEHOLDER = re.compile(r"^[<{%$]|^\.\.\.$")


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return True
    parts = rel.split("/")
    return "tests" in parts or parts[-1].startswith("test_")


class Finding:
    def __init__(self, path: str, line: int, why: str, text: str):
        self.path, self.line, self.why, self.text = path, line, why, text

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.why} [{self.text[:110]}]"


def _tokens_after_image(cmd: str) -> Optional[List[str]]:
    """The tokens following the image reference in a `docker run`, or None."""
    toks = cmd.split()
    for i, t in enumerate(toks):
        if _IMAGE.fullmatch(t):
            return toks[i + 1:]
    return None


def inspect_remedy(text: str) -> Optional[str]:
    """The sentence naming why `text` will not run as printed, or None."""
    if not _DOCKER_RUN.search(text):
        return None
    after = _tokens_after_image(text)
    if after is None:
        return None                      # no image reference: not this population
    # Drop placeholder tokens the reader substitutes.
    real = [t for t in after if not _PLACEHOLDER.match(t)]
    if not real:
        return None                      # `docker run ... <image>` with nothing after
    if real[0] != "--skip":
        return (f"a printed `docker run` against the EDA image puts {real[0]!r} "
                f"where the entry point expects `--skip` — the entry point "
                f"consumes the command and answers [ERROR] Unexpected option "
                f"{real[0]!r}, so the command never runs")
    return None


def _str_constants(tree: ast.AST) -> dict:
    """`{name: value}` for simple module-level string assignments.

    MEASURED: without this the scan reported PASS on

        IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.16"
        print("Remedy: docker run ... " + IMAGE + " bash -lc yosys")

    which is a swallowed remedy written the way a real refusal writes one — the
    image reference kept in a constant. Answering PASS because the token sits
    one assignment away is wrong in the passing direction.
    """
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return out


def _fold(node: ast.AST, names: dict) -> str:
    """A concatenation expression rendered AS PRINTED, following `+` and simple
    names bound to string constants. An unresolvable part becomes a placeholder,
    never a deletion — deleting it would glue tokens that were never adjacent."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id, "<x>")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _fold(node.left, names) + _fold(node.right, names)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str)
            else "<x>" for v in node.values)
    return "<x>"


def _printed_strings(tree: ast.AST) -> List[Tuple[int, str]]:
    """(lineno, text) for every string literal that is printed or raised."""
    out: List[Tuple[int, str]] = []
    names = _str_constants(tree)

    def collect(node: ast.AST, lineno: int) -> None:
        # A concatenation is one printed line; fold it before walking, so the
        # image reference and the command that follows it stay adjacent.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            folded = _fold(node, names)
            if folded.strip():
                out.append((getattr(node, "lineno", lineno), folded))
                return
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.append((getattr(sub, "lineno", lineno), sub.value))
            elif isinstance(sub, ast.JoinedStr):
                # Reconstruct the string AS PRINTED: a substituted expression
                # becomes a placeholder token, never a deletion. Joining only the
                # constant parts glues tokens that were never adjacent and
                # invents commands nobody printed.
                parts = []
                for v in sub.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        parts.append(v.value)
                    else:
                        parts.append("<x>")
                out.append((getattr(sub, "lineno", lineno), "".join(parts)))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "print":
            for a in node.args:
                collect(a, node.lineno)
        elif isinstance(node, ast.Raise) and node.exc is not None:
            collect(node.exc, node.lineno)
        elif isinstance(node, ast.Return) and node.value is not None:
            # `return f"Remedy: ..."` — the shape landing_tier_checkout_preflight
            # uses, so it must be in the population.
            collect(node.value, node.lineno)
    return out


def audit(root: Path) -> Tuple[List[Finding], List[str], int]:
    findings: List[Finding] = []
    unread: List[str] = []
    seen = set()
    remedies = 0
    for path in sorted(root.rglob("*.py")):
        if not path.is_file() or _skip(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unread.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        if "docker" not in text:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            unread.append(f"{rel}: could not be parsed ({exc.msg})")
            continue
        for lineno, s in _printed_strings(tree):
            if "docker" not in s:
                continue
            remedies += 1
            why = inspect_remedy(s)
            if why:
                key = (rel, lineno, why)
                if key not in seen:
                    seen.add(key)
                    findings.append(Finding(rel, lineno, why,
                                            s.replace("\n", " ")))
    return findings, unread, remedies


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
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
        findings, unread, remedies = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for u in unread:
        print(f"NOT CHECKED — {u}", file=sys.stderr)
    print(f"examined {remedies} printed string(s) naming docker under "
          f"{str(root)!r}")
    if remedies == 0:
        print(f"[{NAME}] NOT CHECKED — no printed remedy was found.",
              file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a printed remedy does not run as printed")
        return 1
    if unread:
        print(f"[{NAME}] NOT CHECKED — a candidate file could not be read")
        return 2
    print(f"[{NAME}] PASS — no printed docker-run remedy puts the command before --skip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
