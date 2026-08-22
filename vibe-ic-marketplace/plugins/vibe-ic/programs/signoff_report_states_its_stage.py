#!/usr/bin/env python3
"""signoff_report_states_its_stage.py — timing and power evidence says which
side of place-and-route it came from.

WHY THIS EXISTS
===============
MEASURED: of three reports in one sign-off family, ONE carried the stage
statement — because its own emitter wrote it — and the siblings that actually
decide the slow and fast corners were written by different emitters that did not.
48 of 56 timing rows were then dropped from the evidence set as out of scope, and
both setup and hold reported an incomplete view set rather than a failure.

The READ side is already correct and already landed: `_sta_basis.declared_basis`
is the single reader and returns *undeclared* rather than guessing a side. So an
unstamped report is dropped QUIETLY instead of being refused, and the axis blames
its own evidence instead of the producer. The gap is entirely producer-side —
nothing required the statement to be WRITTEN.

WHAT IS IN THE POPULATION, AND WHY IT IS DRAWN FROM THE FLOW
===========================================================
"A report a step offers as sign-off evidence" is not a judgement call here: the
flow declares it. `flow/phase1_phase2_phase3.yaml` names each step's
`required_outputs`, and this program reads that file rather than carrying a
hand-list that would drift.

Within those declared outputs the rule applies to TIMING and POWER reports, whose
numbers move across place-and-route and for which `STA_BASIS` is defined. It does
NOT apply to a DRC, LVS or density report: `STA_BASIS` is a statement about a
timing basis, and requiring it on a geometry check would be a stamp that means
nothing. Restricting the rule is not a weakening — a rule that demands a
meaningless field is how meaningless fields get filled in.

THE EMITTER IS IDENTIFIED PER FUNCTION, NOT PER MODULE
======================================================
One module emits many reports, so module granularity cannot answer "does the
emitter of THIS report stamp it". The writing FUNCTION is resolved the same way
`only_the_declaring_step_writes_its_output` resolves it — a variable assigned
from an expression carrying the declared basename, then a real write on that
variable — and the stamp is looked for in that function's own source.

WHAT IS DISCLOSED RATHER THAN REFUSED
=====================================
A timing or power report that is EMITTED but that the flow does not DECLARE is
outside the population, and it is printed with its count on every run. That
disclosure is not an aside: the power report whose missing stamp is recorded
above is exactly such a report, and "nothing requires it to be stamped because
nothing declares it as evidence" is the honest statement of that gap. Silently
scoping it out would hide the finding this rule came from.

    rc 0   N>0 declared timing/power reports, each stamped by its emitter (or
           disclosed as inexpressible).
    rc 1   a declared timing/power report is emitted without the stage statement.
    rc 2   NOT CHECKED — no flow, no declarations, or no such report has an
           identifiable emitter.
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

NAME = "signoff_report_states_its_stage"
FLOW_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml")
PROGRAMS_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/programs")
STAMP = "STA_BASIS"
_ALT = re.compile(r"\s+OR\s+")
# Reports whose numbers move across place-and-route, and for which the stamp
# is defined. Geometry checks are deliberately excluded — see the docstring.
_TIMING_OR_POWER = re.compile(r"(timing|sta|power|slack|fmax)", re.I)
_NOT_TIMING = re.compile(r"(drc|lvs|density|antenna|erc|fill|perc)", re.I)
# Declared timing reports whose stage the stamp CANNOT express. `_sta_basis`
# normalises to exactly two values, PRE_LAYOUT and POST_ROUTE. A clock-tree
# report is written after CTS and before routing, so it can answer neither
# honestly, and demanding the stamp there would force a value that is wrong
# whichever one is chosen. These are DISCLOSED with this reason on every run,
# never silently dropped — the exclusion is part of the finding, not a way
# around it, and closing it needs a third value in the stamp's vocabulary.
_STAGE_NOT_EXPRESSIBLE = re.compile(r"(clock_tree|cts)", re.I)


def is_timing_or_power(path: str) -> bool:
    """A TIMING OR POWER REPORT — not a document, not a stats blob.

    MEASURED: without the `.rpt` requirement this matched a power-INTENT
    document (`L21_POWER_INTENT.json`), synthesis `stats.json` and a crosstalk
    JSON, taking the population from 2 to 78 and producing six findings that
    were all wrong. None of those artefacts has a side of place-and-route, and
    `STA_BASIS` is undefined for them.

    The stamp is a statement about a TIMING basis, so the population is the
    report files whose numbers move across place-and-route.
    """
    base = path.rsplit("/", 1)[-1]
    if not base.endswith(".rpt"):
        return False
    if _NOT_TIMING.search(base):
        return False
    return bool(_TIMING_OR_POWER.search(path))


def stage_not_expressible(path: str) -> bool:
    """True for a declared timing report the two-value stamp cannot describe."""
    return bool(_STAGE_NOT_EXPRESSIBLE.search(path))


def declared_outputs(flow_path: Path) -> Dict[str, Set[str]]:
    import yaml
    data = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    out: Dict[str, Set[str]] = collections.defaultdict(set)
    for step in (data or {}).get("steps") or []:
        for decl in step.get("required_outputs") or []:
            if isinstance(decl, str):
                for alt in _ALT.split(decl):
                    if alt.strip():
                        out[alt.strip()].add(str(step.get("id")))
    return dict(out)


def _str_consts(node: ast.AST) -> List[str]:
    return [c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)]


def _is_write(node: ast.Call) -> bool:
    attr = node.func.attr                           # type: ignore[union-attr]
    if attr in ("write_text", "write_bytes"):
        return True
    if attr != "open":
        return False
    mode = "".join(a.value for a in node.args
                   if isinstance(a, ast.Constant) and isinstance(a.value, str))
    mode += "".join(k.value.value for k in node.keywords
                    if k.arg == "mode" and isinstance(k.value, ast.Constant)
                    and isinstance(k.value.value, str))
    return any(m in mode for m in ("w", "a", "x"))


class Emitter:
    def __init__(self, path: str, module: str, func: str, stamped: bool):
        self.path, self.module, self.func = path, module, func
        self.stamped = stamped

    def __str__(self) -> str:
        return (f"{self.path}: emitted by {self.module}:{self.func}() which "
                f"never writes {STAMP}. The one reader of that stamp treats its "
                f"absence as UNDECLARED, so this report is dropped from the "
                f"evidence set quietly and the axis reports an incomplete view "
                f"instead of a failure.")


def _emits_stamp(scope: ast.AST) -> bool:
    """True only when the stamp is WRITTEN, not merely mentioned.

    MEASURED FALSE PASS: this was `STAMP in <function source text>`, so

        def emit(project, body):
            # TODO: we should write STA_BASIS here one day
            p.write_text(body)

    reported PASS. A comment ADMITTING the stamp is missing certified it as
    present — the strongest possible form of the defect this rule exists for.
    Docstrings are excluded for the same reason: describing a stamp is not
    emitting one.
    """
    doc = ast.get_docstring(scope, clean=False) if isinstance(
        scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
    for node in ast.walk(scope):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and STAMP in node.value and node.value != doc:
            return True
    return False


def scan(root: Path) -> Tuple[List[Emitter], List[Emitter], int, int]:
    """(unstamped declared, undeclared emitted, declared population, found)."""
    flow = root / FLOW_REL
    if not flow.is_file():
        raise FileNotFoundError(f"{FLOW_REL} is not present under {root}")
    declared = declared_outputs(flow)
    wanted = {p for p in declared if is_timing_or_power(p)}
    by_base: Dict[str, Set[str]] = collections.defaultdict(set)
    for p in wanted:
        by_base[p.rsplit("/", 1)[-1]].add(p)

    unstamped: List[Emitter] = []
    undeclared: List[Emitter] = []
    inexpressible: List[Emitter] = []
    unparsed = [0]
    seen: Set[Tuple[str, str, str]] = set()
    found = 0
    for dirpath, dirnames, filenames in os.walk(root / PROGRAMS_REL,
                                                followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests")
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            fp = Path(dirpath) / fn
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text)
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
            lines = text.splitlines()
            for scope in ast.walk(tree):
                if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                stamped = _emits_stamp(scope)
                var: Dict[str, Set[str]] = collections.defaultdict(set)
                for stmt in ast.walk(scope):
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                            and isinstance(stmt.targets[0], ast.Name):
                        for c in _str_consts(stmt.value):
                            if c in by_base:
                                var[stmt.targets[0].id].add(c)
                for node in ast.walk(scope):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)):
                        continue
                    if not _is_write(node):
                        continue
                    tgt = node.func.value
                    names: Set[str] = set()
                    if isinstance(tgt, ast.Name):
                        names |= var.get(tgt.id, set())
                    for c in _str_consts(tgt):
                        if c in by_base:
                            names.add(c)
                    for bn in names:
                        for full in by_base[bn]:
                            key = (full, fn, scope.name)
                            if key in seen:
                                continue
                            seen.add(key)
                            found += 1
                            if stamped:
                                continue
                            e = Emitter(full, fn, scope.name, False)
                            if stage_not_expressible(full):
                                inexpressible.append(e)
                            else:
                                unstamped.append(e)
    # Emitted-but-undeclared timing/power reports, disclosed.
    undeclared = _undeclared_timing_reports(root, set(declared))
    return unstamped, undeclared, inexpressible, len(wanted), found, unparsed[0]


def _undeclared_timing_reports(root: Path, declared: Set[str]) -> List[Emitter]:
    """Timing/power .rpt basenames a module writes that the flow never declares."""
    out: List[Emitter] = []
    declared_bases = {p.rsplit("/", 1)[-1] for p in declared}
    seen: Set[Tuple[str, str]] = set()
    pat = re.compile(r'"([\w.-]*(?:power|timing|sta|slack)[\w.-]*\.rpt)"', re.I)
    for dirpath, dirnames, filenames in os.walk(root / PROGRAMS_REL,
                                                followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests")]
        for fn in sorted(filenames):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            try:
                text = (Path(dirpath) / fn).read_text(encoding="utf-8",
                                                      errors="replace")
            except OSError:
                continue
            for m in pat.finditer(text):
                base = m.group(1)
                if base in declared_bases or (fn, base) in seen:
                    continue
                seen.add((fn, base))
                out.append(Emitter(base, fn, "(module)", False))
    return out


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
        unstamped, undeclared, inexpressible, population, found, unparsed = scan(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the flow's declarations could not be "
              f"read: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for e in unstamped:
        print(str(e))
    for e in undeclared:
        print(f"DISCLOSED — {e.module} emits {e.path}, which the flow does not "
              f"declare as any step's required output. Nothing requires it to "
              f"carry {STAMP}, because nothing declares it as evidence.",
              file=sys.stderr)
    for e in inexpressible:
        print(f"DISCLOSED — {e.path} is emitted by {e.module}:{e.func}() with "
              f"no {STAMP}, and the stamp's two values (PRE_LAYOUT, POST_ROUTE) "
              f"cannot describe a report written after CTS and before routing. "
              f"Closing this needs a third value in the stamp's vocabulary, not "
              f"a stamp chosen at random.", file=sys.stderr)
    print(f"examined {found} emitter(s) of {population} flow-declared "
          f"timing/power report(s); {len(inexpressible)} inexpressible and "
          f"{len(undeclared)} emitted-but-undeclared report(s) disclosed; "
          f"{unparsed} source file(s) skipped as unparseable")
    if population == 0:
        print(f"[{NAME}] NOT CHECKED — the flow declares no timing or power "
              f"report, so this gate walked an empty set. Not a pass.",
              file=sys.stderr)
        return 2
    if found == 0:
        print(f"[{NAME}] NOT CHECKED — no declared timing/power report has an "
              f"identifiable emitter, so nothing was judged. Not a pass.",
              file=sys.stderr)
        return 2
    if unstamped:
        print(f"[{NAME}] FAIL — a declared sign-off report states no stage")
        return 1
    print(f"[{NAME}] PASS — no declared timing/power report with an identified "
          f"emitter is unstamped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
