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

TWO ARMS, AND WHY THE FIRST ONE IS NOT ENOUGH
=============================================
ARM A is keyed on the flow's `required_outputs`. It is correct and it is also
BLIND TO THE INCIDENT THAT MOTIVATED THIS RULE: the capture's two multi-corner
sign-off reports are emitted and never declared, so arm A files them under
DISCLOSED and no input can redden them. A gate that passes on its own motivating
incident certifies the defect absent, which is worse than not existing.

ARM B is keyed on the module's OWN demonstrated convention, taken from the
capture's `pattern` field: "One report in a family carries the stage statement
because its own emitter writes it, and the sibling reports that actually decide
the slow and fast corners are written by different emitters that do not." If a
module stamps one timing/power report it emits, it knows how to stamp, and a
sibling it emits unstamped is an omission rather than a scope question. A module
that stamps nothing is not in arm B's population at all.

Keying arm B on the sign-off gate's evidence globs was the obvious repair and is
the wrong one: `sta_spef_multicorner.rpt` matches only that gate's catch-all
`*sta*.rpt`, so adopting the globs means adopting a catch-all.

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


# ── ARM B — the FAMILY rule, taken from the capture's own `pattern` field ────
# "One report in a family carries the stage statement because its own emitter
#  writes it, and the sibling reports that actually decide the slow and fast
#  corners are written by different emitters that do not."
#
# Arm A above is keyed on the flow's `required_outputs`. That key CANNOT reach
# the capture's own incident: both multi-corner sign-off reports are emitted but
# never declared, so arm A files them under DISCLOSED and can never redden them.
# Keying arm B on the sign-off gate's evidence globs was the obvious repair and
# is the wrong one — `sta_spef_multicorner.rpt` matches only that gate's
# catch-all `*sta*.rpt`, so adopting the globs means adopting a catch-all.
#
# This arm is keyed on the module's OWN demonstrated convention instead, which
# needs no external list and cannot be argued with: if a module stamps one
# timing/power report it emits, it knows how to stamp, and a sibling report it
# emits WITHOUT the stamp is an omission rather than a scope question. A module
# that never stamps anything is not in this arm's population at all.
_RPT = re.compile(r'([\w.-]*(?:power|timing|sta|slack|fmax)[\w.-]*\.rpt)', re.I)


# The atomic-write doctrine in this tree is temp-file + rename (`_atomic_output`),
# so a scope that emits its report correctly calls `os.replace` and never
# `write_text` on the destination. `_is_write` above knows only the direct forms,
# which is why the capture's own `sta_mcorner_ocv_postrepair.rpt` — written by
# `_measure_postrepair_mcorner_ocv` via `replace` — was invisible to this scan.
_RENAME_ATTRS = ("replace", "rename", "move")

# A scope that COPIES an existing artefact is republishing it, not producing it,
# and the stage stamp belongs on the producer. Without this exclusion the arm
# reddens `_publish_artefact_mirror`, whose own docstring says it copies `src` to
# `dst` and records the result as a MIRROR — a republished byte-identical copy
# cannot state a basis its producer did not.
#
# `read_text`/`read_bytes` are deliberately NOT copy signals: every report
# generator in this tree reads the tool log it summarises, so treating a read as
# evidence of copying emptied this arm's population entirely and turned the whole
# gate green — measured, not supposed.
_COPY_ATTRS = ("copy", "copy2", "copyfile", "copytree")


_READ_ATTRS = ("read_bytes", "read_text")


def _is_copier(scope: ast.AST) -> bool:
    """True when the scope writes bytes it READ from another path verbatim.

    A read alone is not the signal — every report generator reads the tool log it
    summarises. The signal is the DATAFLOW: content read from one path reaching a
    write unchanged, either directly (`dst.write_bytes(src.read_bytes())`) or via
    a name (`body = src.read_bytes()` ... `dst.write_bytes(body)`). That is a
    republished byte-identical copy, and the stage stamp belongs to whatever
    produced the original.
    """
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in _COPY_ATTRS:
            return True
    copied: Set[str] = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name) \
                and isinstance(n.value, ast.Call) \
                and isinstance(n.value.func, ast.Attribute) \
                and n.value.func.attr in _READ_ATTRS:
            copied.add(n.targets[0].id)
    for n in ast.walk(scope):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("write_bytes", "write_text") and n.args):
            continue
        a = n.args[0]
        if isinstance(a, ast.Name) and a.id in copied:
            return True
        if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) \
                and a.func.attr in _READ_ATTRS:
            return True
    return False


def _scope_reports(scope: ast.AST) -> Set[str]:
    """Timing/power .rpt basenames named inside a scope that writes a file."""
    if _is_copier(scope):
        return set()
    writes = False
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in _RENAME_ATTRS:
                writes = True
                break
            try:
                if _is_write(n):
                    writes = True
                    break
            except Exception:                       # noqa: BLE001
                continue
    if not writes:
        return set()
    out: Set[str] = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            for m in _RPT.finditer(n.value):
                base = m.group(1)
                if is_timing_or_power(base) and not stage_not_expressible(base):
                    out.add(base)
    return out


def _stamping_callees(tree: ast.AST) -> Set[str]:
    """Names of functions in THIS module whose own body emits the stamp."""
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _emits_stamp(n):
            out.add(n.name)
    return out


def _delegates_to_a_stamper(scope: ast.AST, stampers: Set[str]) -> bool:
    """The scope hands its work to a same-module function that stamps.

    MEASURED, AND IT COST A PUBLISHED FINDING. `_measure_postrepair_mcorner_ocv`
    writes `sta_mcorner_ocv_postrepair.rpt` and stamps nothing itself, so a
    scope-local reading calls it unstamped. It is not: it passes the report path
    to `_emit_mcorner_ocv_sta`, whose generated session writes STA_BASIS,
    STA_BASIS_LIBERTY, STA_BASIS_NETLIST and STA_BASIS_SPEF into that very file.
    The report carries the stamp; the stamp is simply one call away.

    A gate that reads only the scope in front of it reports the wrapper and misses
    the truth one hop down — the same shape as keying arm A on `required_outputs`,
    which is what this arm was added to repair.
    """
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in stampers:
            return True
    return False


def sibling_stamp_gaps(root: Path) -> Tuple[List[Emitter], int, int]:
    """(findings, modules with a stamping convention, reports judged)."""
    findings: List[Emitter] = []
    modules = 0
    judged = 0
    for dirpath, dirnames, filenames in os.walk(root / PROGRAMS_REL,
                                                followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests")
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            try:
                tree = ast.parse((Path(dirpath) / fn).read_text(
                    encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            stampers = _stamping_callees(tree)
            emitted: List[Tuple[str, str, bool]] = []
            for scope in ast.walk(tree):
                if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                reports = _scope_reports(scope)
                if not reports:
                    continue
                stamped = (_emits_stamp(scope)
                           or _delegates_to_a_stamper(scope, stampers))
                for base in sorted(reports):
                    emitted.append((base, scope.name, stamped))
            if not any(s for _, _, s in emitted):
                continue                    # no convention here — not judged
            modules += 1
            for base, func, stamped in emitted:
                judged += 1
                if not stamped:
                    findings.append(Emitter(base, fn, func, False))
    return findings, modules, judged


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
    try:
        gaps, gap_modules, gap_judged = sibling_stamp_gaps(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the sibling-stamp arm could not read "
              f"this tree: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for e in unstamped:
        print(str(e))
    for e in gaps:
        print(f"{e.path}: emitted by {e.module}:{e.func}() without {STAMP}, "
              f"while the same module stamps another timing/power report it "
              f"emits. The module demonstrates the convention and this report "
              f"is outside it, so the omission is the finding.")
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
          f"{unparsed} source file(s) skipped as unparseable; "
          f"sibling-stamp arm judged {gap_judged} report(s) in {gap_modules} "
          f"module(s) that demonstrate a stamping convention")
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
    if unstamped or gaps:
        print(f"[{NAME}] FAIL — a sign-off report states no stage "
              f"({len(unstamped)} declared-and-unstamped, {len(gaps)} unstamped "
              f"beside a stamped sibling)")
        return 1
    print(f"[{NAME}] PASS — no declared timing/power report with an identified "
          f"emitter is unstamped, and no module that stamps one report it emits "
          f"leaves a sibling timing/power report unstamped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
