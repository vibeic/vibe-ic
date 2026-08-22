#!/usr/bin/env python3
"""only_the_declaring_step_writes_its_output.py — one flow-declared path, one
writer.

WHY THIS EXISTS
===============
MEASURED: a precheck delegated to the same checker with a REDUCED argument set
and wrote its result at the flow's canonical evidence path. That path then had
two writers, and the one that ran last won:

    the declaring step's write   811 bytes, 2 findings, sign-off scope populated
    the delegate's write         308 bytes, 1 finding, no scope keys at all

A release tier graded the second. Nothing was corrupt, nothing errored, and the
verdict was about an artefact the declaring step did not produce. Which writer
wins is decided by execution order, so the same tree can grade either way.

THE RULE
========
A path the flow declares as a step's required output may be written by ONE
module. When the flow itself declares the same path for more than one step, the
path is EXEMPT — the flow has said two steps legitimately produce it, and this
program does not overrule the declaration it reads.

A non-declaring writer needs BOTH a private directory and a different basename.
A private directory alone is not enough, because discovery here is by recursive
glob and a private directory is still found by one.

THE GUARD THE RECORD ASKED FOR
==============================
A check that silently walks an empty set passes for the wrong reason. Two things
are therefore refused rather than passed:

  * the flow file missing, unreadable, or declaring no outputs  -> rc 2
  * no declared output having any identifiable writer           -> rc 2

and `test_the_known_flow_paths_are_still_recognised_as_flow_owned` pins named
historical paths as flow-owned, so a flow-file rename or a schema change cannot
turn this gate green by emptying its population.

HOW A WRITER IS IDENTIFIED, AND WHAT IS DELIBERATELY NOT CLAIMED
================================================================
Paths here are composed at runtime (`reports_phase3_dir(project) / "antenna.json"`),
so a scan for whole-path literals finds NOTHING — measured: zero. The writer is
identified by resolving, WITHIN ONE SCOPE, a variable assigned from an expression
containing a declared output's basename, and then finding a real write on that
variable: `write_text`, `write_bytes`, or `open` with a mode containing w/a/x.
`.open()` without a write mode is a READ and is not counted.

Shell scripts are scanned too, for a redirection / tee / cp / mv landing on a
declared basename, because this tree drives real work from `tools/*.sh` and a
Python-only scan reported PASS on a shell writer sitting beside a Python one.

This is intra-scope resolution, not whole-program data-flow. It therefore UNDER-
reports: a writer that passes the path through a helper is not seen. Under-
reporting is the safe direction for this rule — every path it names really is
written from the modules it names — and the denominator is printed so the
coverage is legible rather than implied.

    rc 0   N>0 declared outputs have an identified writer; none has two.
    rc 1   a declared output is written by more than one module.
    rc 2   NOT CHECKED — no flow, no declarations, or no identifiable writer.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import collections
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

NAME = "only_the_declaring_step_writes_its_output"
FLOW_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml")
PROGRAMS_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/programs")
WRITE_ATTRS = ("write_text", "write_bytes")
_ALT = re.compile(r"\s+OR\s+")


def declared_outputs(flow_path: Path) -> Dict[str, Set[str]]:
    """`{declared path: {step ids that declare it}}`, alternates split out."""
    import yaml                                    # local: keep import cost off
    data = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    out: Dict[str, Set[str]] = collections.defaultdict(set)
    for step in (data or {}).get("steps") or []:
        sid = str(step.get("id"))
        for decl in step.get("required_outputs") or []:
            if not isinstance(decl, str):
                continue
            # "a/b.flag OR a/c.report" declares BOTH, either satisfying the step.
            for alt in _ALT.split(decl):
                alt = alt.strip()
                if alt:
                    out[alt].add(sid)
    return dict(out)


def _str_consts(node: ast.AST) -> List[str]:
    return [c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)]


#: Calls that LAND BYTES AT A DESTINATION without being `.write_text`.
#:
#: MEASURED GAP, and the worst kind. `os.replace` is this repository's OWN
#: sanctioned way to write an artefact — `_atomic_output.py` exists to make every
#: declared output arrive by temp-file-then-rename, so the artefact only appears
#: under its final name if the step completed. This scan enumerated `write_text`,
#: `write_bytes` and `open(...,'w')` and therefore could not see the CORRECT
#: idiom: the more properly a step wrote its output, the more invisible it was
#: here. A second writer using `shutil.copy` or `os.replace` returned rc=0.
#:
#: Found by reading the census lane's commit "the write enumeration missed shutil
#: and the attribute form of open" and asking the same question of this gate.
DEST_CALLS = {
    ("shutil", "copy"), ("shutil", "copy2"), ("shutil", "copyfile"),
    ("shutil", "move"),
    ("os", "replace"), ("os", "rename"), ("os", "link"), ("os", "symlink"),
}
#: Path methods that land bytes at the RECEIVER's own path.
PATH_DEST_ATTRS = ("replace", "rename", "hardlink_to", "symlink_to")


def _dest_arg(node: ast.Call) -> Optional[ast.expr]:
    """The argument naming where bytes land, for a module-level dest call."""
    f = node.func
    if not isinstance(f, ast.Attribute) or not isinstance(f.value, ast.Name):
        return None
    if (f.value.id, f.attr) not in DEST_CALLS:
        return None
    return node.args[1] if len(node.args) >= 2 else None


def _is_write(node: ast.Call) -> bool:
    attr = node.func.attr                           # type: ignore[union-attr]
    if attr in WRITE_ATTRS or attr in PATH_DEST_ATTRS:
        return True
    if attr != "open":
        return False
    mode = ""
    for a in node.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            mode += a.value
    for k in node.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant) \
                and isinstance(k.value.value, str):
            mode += k.value.value
    return any(m in mode for m in ("w", "a", "x"))


# A shell write: redirection, tee, or a copy/move landing on the path.
_SH_WRITE = re.compile(r"(>>?|\btee\b|\bcp\b|\bmv\b|\binstall\b)")


def _shell_writers(text: str, by_basename: Dict[str, Set[str]]) -> Set[str]:
    """Declared-output basenames this shell script WRITES.

    MEASURED FALSE PASS: the scan was Python-only, so

        echo "{}" > "$PROJECT/reports/coverage.json"

    beside a Python writer of the same declared path reported PASS — two writers,
    one seen. This tree drives real work from shell (`tools/*.sh`), so the blind
    spot was not hypothetical, and unlike the data-flow limit it was not
    disclosed either.
    """
    hit: Set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]          # a comment is never a write
        if not _SH_WRITE.search(line):
            continue
        for base in by_basename:
            if base in line:
                hit.add(base)
    return hit


def writers_of(programs: Path, by_basename: Dict[str, Set[str]]
               ) -> Tuple[Dict[str, Set[str]], int]:
    """`({declared path: {writing file basenames}}, unparseable file count)`."""
    found: Dict[str, Set[str]] = collections.defaultdict(set)
    unparsed = [0]
    for dirpath, dirnames, filenames in os.walk(programs, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests")
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if fn.startswith("test_"):
                continue
            path = Path(dirpath) / fn
            if fn.endswith(".sh"):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for base in _shell_writers(text, by_basename):
                    for full in by_basename[base]:
                        found[full].add(fn)
                continue
            if not fn.endswith(".py"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8",
                                                errors="replace"))
            except (OSError, SyntaxError, ValueError):
        # A file this scan cannot parse is COUNTED, not dropped in
        # silence. Measured today: 0 such files in this population — so
        # the exposure is latent, not live. But a gate that skips input
        # without saying how much has an undisclosed boundary, and this
        # lane's whole finding is that the undisclosed boundary is the
        # one that bites. The count goes on the DENOMINATOR line, never
        # the verdict line.
                unparsed[0] += 1
                continue
            for scope in ast.walk(tree):
                if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.Module)):
                    continue
                var: Dict[str, Set[str]] = collections.defaultdict(set)
                for stmt in ast.walk(scope):
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                            and isinstance(stmt.targets[0], ast.Name):
                        for c in _str_consts(stmt.value):
                            if c in by_basename:
                                var[stmt.targets[0].id].add(c)
                for node in ast.walk(scope):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)):
                        continue
                    dest = _dest_arg(node)
                    if dest is not None:
                        names2: Set[str] = set()
                        if isinstance(dest, ast.Name):
                            names2 |= var.get(dest.id, set())
                        for c in _str_consts(dest):
                            if c in by_basename:
                                names2.add(c)
                        for bn in names2:
                            for full in by_basename[bn]:
                                found[full].add(fn)
                        continue
                    if not _is_write(node):
                        continue
                    target = node.func.value
                    names: Set[str] = set()
                    if isinstance(target, ast.Name):
                        names |= var.get(target.id, set())
                    for c in _str_consts(target):
                        if c in by_basename:
                            names.add(c)
                    for bn in names:
                        for full in by_basename[bn]:
                            found[full].add(fn)
    return dict(found), unparsed[0]


class Finding:
    def __init__(self, path: str, steps: Set[str], modules: Set[str]):
        self.path, self.steps, self.modules = path, steps, modules

    def __str__(self) -> str:
        return (f"{self.path}: declared by step {sorted(self.steps)} and written "
                f"by {len(self.modules)} modules {sorted(self.modules)}. Which "
                f"write survives is decided by execution order, so the graded "
                f"artefact may not be the declaring step's. A non-declaring "
                f"writer needs BOTH a private directory and a different "
                f"basename — discovery is by recursive glob, so a private "
                f"directory alone is still found.")


def audit(root: Path) -> Tuple[List[Finding], List[str], int, int]:
    """(findings, exempt paths, declared count, paths with a writer)."""
    flow = root / FLOW_REL
    if not flow.is_file():
        raise FileNotFoundError(f"{FLOW_REL} is not present under {root}")
    declared = declared_outputs(flow)
    by_basename: Dict[str, Set[str]] = collections.defaultdict(set)
    for p in declared:
        by_basename[p.rsplit("/", 1)[-1]].add(p)
    writers, unparsed = writers_of(root / PROGRAMS_REL, by_basename)
    findings: List[Finding] = []
    exempt: List[str] = []
    for path, mods in sorted(writers.items()):
        if len(mods) < 2:
            continue
        if len(declared[path]) > 1:
            exempt.append(path)          # the flow itself declares two steps
            continue
        findings.append(Finding(path, declared[path], mods))
    return findings, exempt, len(declared), len(writers), unparsed


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="repository root holding the flow and the programs")
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
        findings, exempt, declared, with_writer, unparsed = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the flow's declarations could not be "
              f"read, so no path was judged: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for p in exempt:
        print(f"EXEMPT — {p} is declared by more than one step; the flow says "
              f"two steps produce it and this rule does not overrule it.",
              file=sys.stderr)
    print(f"examined {declared} flow-declared output(s), {with_writer} with an "
          f"identified writer, {len(exempt)} exempt, {unparsed} source file(s) "
          f"skipped as unparseable")
    if declared == 0:
        print(f"[{NAME}] NOT CHECKED — the flow declares no outputs, so this "
              f"gate walked an empty set. That is not a pass.", file=sys.stderr)
        return 2
    if with_writer == 0:
        print(f"[{NAME}] NOT CHECKED — no declared output has an identifiable "
              f"writer, so nothing was judged. That is not a pass.",
              file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a flow-declared output has more than one writer")
        return 1
    print(f"[{NAME}] PASS — no flow-declared output with an identified writer has two")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
