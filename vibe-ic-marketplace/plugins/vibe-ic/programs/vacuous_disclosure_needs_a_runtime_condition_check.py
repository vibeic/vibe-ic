#!/usr/bin/env python3
"""A disclosure token is not a working gate — the skip must be CONDITIONED.

THIS GATE BLOCKS (rc=1) on a disclosure nothing can decline to print.

WHY THIS GATE EXISTS
====================
Matrix dimension D6 (`skip_discipline`) promises two halves:

    (a) is the skip CONDITIONED on a runtime fact, and
    (b) is it REPORTED at a non-PASS tier?

MEASURED on the 68x9 matrix (mutation probe, plugin v1.12.33): it delivers
(b) only. Two mutations of the SAME gate, differing only in what the broken
gate says about itself:

    M1b  the gate stops working and says nothing         -> RED, hard.
    M1   the gate stops working and says `VACUOUS_PASS`  -> GREEN,
         80 passed / 1 xfailed, byte-identical to the clean tree.

Worse, the module's own capability census counted the MUTATED gate as having
MORE live legs than before -- L2, L3c and L6 became "capable" -- while the
number of legs that actually FIRED stayed at zero. Capability is not firing.

On a realistic project (a `clock_plan.json` that exists but declares zero
clocks) the clean tree reports step 16 `status='FAIL'`; the mutated tree
reports `status='VACUOUS_PASS'` and the headline moves the step out of
"executed" altogether. The gate that exists to catch an empty clock plan
stops catching it, and the matrix reads GREENER than before.

So: adding a disclosure token to a broken gate converts a red cell to green.
That is the defect this program closes.

THE RULE
========
A disclosure sentinel (`VACUOUS_PASS`, `SKIPPED-CONDITION`,
`SKIPPED-SETUP-REQUIRED`, `DISCLOSED_SKIP`, `NOT_RUN`, `NO_BUILD`,
`PASS_WITH_WAIVERS`, and `sys.exit(2)`) may only be reached under a condition
that READS RUNTIME STATE. Concretely, at least one enclosing `if` / `while` /
`except` / comprehension-guard on the path to the emit site must test an
expression that calls something or reads a name it did not spell as a literal
-- an input file's existence, a parsed field, a subprocess exit code, the
length of what was collected.

A sentinel that is:

  * emitted UNCONDITIONALLY (no enclosing test at all), or
  * emitted only under tests that are pure literals (`if True:`, `if 1:`)

is reported. Such a sentinel cannot decline to print, so it says nothing
about the run: it is decoration that buys a tier.

WHAT THIS DOES NOT CLAIM
========================
It does not decide whether the runtime fact is the RIGHT one -- that is a
judgment about the gate's subject, not a structural property. It decides only
the half D6 never asked: whether there is a runtime fact in the loop at all.
Half (b), the tier the skip is reported at, remains
`gate_skip_routing_check`'s job; the two are complementary and neither
subsumes the other.

FAIL-SAFE
=========
A module that cannot be parsed is reported UNANALYSABLE and counted, never
silently cleared -- the direction that makes an unreadable gate visible
instead of green.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# The sentinels a consumer reads as "this gate declined to judge". Kept in one
# place so the vocabulary is stated once and can be extended without hunting.
SENTINELS: Tuple[str, ...] = (
    "VACUOUS_PASS",
    "VACUOUS-PASS",
    "SKIPPED-CONDITION",
    "SKIPPED-SETUP-REQUIRED",
    "SKIPPED_CONDITION",
    "DISCLOSED_SKIP",
    "DISCLOSED-SKIP",
    "PASS_WITH_WAIVERS",
    "NO_BUILD",
    "NOT_RUN",
    "__VACUOUS_HINT__",
)

GATE_SUFFIXES = ("_check.py", "_lint.py", "_audit.py", "_guard.py")


def _is_sentinel_text(value: str) -> bool:
    """Is this literal a DISCLOSURE, or merely prose that names one?

    The consumer contract is line-START: `flow_compliance_check` reads a
    sentinel only when `line.lstrip().startswith(<token>)`. So
    `f"...  DISCLOSED-SKIP={n}  ..."` is a COUNT in a summary line, not a
    claim about this run, and crediting it as one would flag every gate that
    merely REPORTS on skips. A sentinel anywhere but the start of a rendered
    line cannot be read as a verdict, so it is not judged as one.
    """
    for line in value.splitlines():
        stripped = line.lstrip().lstrip("[").lstrip()
        if any(stripped.startswith(s) for s in SENTINELS):
            return True
    return False


def _emit_call(node: ast.AST) -> Optional[ast.Call]:
    """The call, if any, by which this statement SHOWS text to a consumer.

    Only three shapes put a sentinel in front of the machine that reads the
    verdict: `print(...)`, `sys.exit(...)`, and a `.write(...)` on a stream.
    A docstring that DISCUSSES `VACUOUS_PASS`, a constant tuple listing the
    vocabulary, and a comment naming it are prose about the program, not the
    program speaking -- crediting them would repeat the exact mistake this
    repo already paid for (prose read as wiring).
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id == "print":
            return sub
        if isinstance(func, ast.Attribute):
            if func.attr == "exit":
                return sub
            if func.attr == "write":
                return sub
    return None


def _string_exprs(node: ast.AST):
    """Every string EXPRESSION here, without descending into an f-string.

    A JoinedStr's chunks are constants of their own; yielding them separately
    would judge `f"steps={n}  DISCLOSED-SKIP={d}"` by a chunk that does start
    with a sentinel. The rendered whole is the only thing a consumer sees.
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, (ast.JoinedStr, ast.Constant)):
            yield cur
            continue
        stack.extend(ast.iter_child_nodes(cur))


def _rendered(node: ast.AST) -> Optional[str]:
    """The text a string expression would print, with `{}` for its holes.

    An f-string is a JoinedStr of several constants; judging each chunk on its
    own would read `f"steps={n}  DISCLOSED-SKIP={d}"` as a line that STARTS
    with a sentinel, because the chunk does. The line-start rule is about the
    rendered line, so render it.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            else:
                out.append("{}")
        return "".join(out)
    return None


def _emits_sentinel(node: ast.AST) -> Optional[str]:
    """The sentinel this statement puts in front of a consumer, if any."""
    call = _emit_call(node)
    if call is None:
        return None
    for sub in _string_exprs(call):
        text = _rendered(sub)
        if text is not None and _is_sentinel_text(text):
            return text.strip()[:80]
    if (isinstance(call.func, ast.Attribute)
            and call.func.attr == "exit"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == 2):
        return "sys.exit(2)"
    return None


def _is_main_guard(test: ast.AST) -> bool:
    """`if __name__ == "__main__":` — true or false before the run begins.

    It decides whether the module was IMPORTED or EXECUTED, which is fixed by
    how the process started, never by the design under test. Counting it as a
    runtime fact would clear every disclosure inside `main()` — i.e. exactly
    the population this gate exists to judge — while still passing its own
    unit tests, which are written as bare functions with no `__main__` block.
    """
    names = {n.id for n in ast.walk(test) if isinstance(n, ast.Name)}
    consts = {n.value for n in ast.walk(test)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return "__name__" in names and "__main__" in consts


def _reads_runtime_state(test: ast.AST) -> bool:
    """Could this test have come out the other way on a different input?

    A test that calls anything, subscripts anything, reads an attribute, or
    compares/uses a plain name is deciding on state the source does not fix.
    A test made only of literals is not: it renders the same on every run.
    """
    if _is_main_guard(test):
        return False
    for sub in ast.walk(test):
        if isinstance(sub, (ast.Call, ast.Subscript, ast.Attribute,
                            ast.Name, ast.Compare, ast.Await)):
            # `if True:` parses as a Constant, never a Name -- so any Name
            # here is a variable whose value the run decides.
            if isinstance(sub, ast.Name) and sub.id in ("True", "False", "None"):
                continue
            return True
    return False


def _guard_chain(tree: ast.Module) -> Dict[ast.AST, List[ast.AST]]:
    """For every node, the enclosing conditional TESTS, outermost first.

    `if`/`while` contribute their test. An `except` handler contributes a
    synthetic marker: reaching it at all required a raise, which is a runtime
    fact. A `for` contributes its iterable for the same reason -- a loop body
    runs only if something was collected.
    """
    chains: Dict[ast.AST, List[ast.AST]] = {}

    def walk(node: ast.AST, chain: List[ast.AST]) -> None:
        chains[node] = chain
        for field, value in ast.iter_fields(node):
            children = value if isinstance(value, list) else [value]
            for child in children:
                if not isinstance(child, ast.AST):
                    continue
                sub = chain
                if isinstance(node, (ast.If, ast.While)) and field in ("body", "orelse"):
                    sub = chain + [node.test]
                elif isinstance(node, ast.ExceptHandler) and field == "body":
                    sub = chain + [node]
                elif isinstance(node, (ast.For, ast.AsyncFor)) and field == "body":
                    sub = chain + [node.iter]
                walk(child, sub)

    walk(tree, [])
    return chains


def _conditioned(chain: Iterable[ast.AST]) -> bool:
    for test in chain:
        if isinstance(test, ast.ExceptHandler):
            return True          # an exception IS a runtime fact
        if _reads_runtime_state(test):
            return True
    return False


def _function_of(tree: ast.Module) -> Dict[ast.AST, Optional[str]]:
    """Innermost enclosing function name for every node (None at module level)."""
    owner: Dict[ast.AST, Optional[str]] = {}

    def walk(node: ast.AST, name: Optional[str]) -> None:
        owner[node] = name
        for child in ast.iter_child_nodes(node):
            nxt = name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nxt = child.name
            walk(child, nxt)

    walk(tree, None)
    return owner


def _conditioned_callees(tree: ast.Module,
                         chains: Dict[ast.AST, List[ast.AST]]) -> set:
    """Functions that at least one CONDITIONED call site invokes.

    A disclosure at the tail of a dedicated `_inconclusive()` helper is
    conditioned by its CALLER, not by anything lexically around it. Judging
    only the lexical chain would report every such helper -- which is the
    single-file version of the adjacency error: the site is unconditional,
    the PATH to it is not.
    """
    called_under_condition: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name and _conditioned(chains.get(node, [])):
            called_under_condition.add(name)
    return called_under_condition


def _terminates(node: ast.If) -> bool:
    """Does this `if` end the function on its own branch?"""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Return, ast.Raise)):
            return True
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "exit"):
            return True
    return False


def _guard_clauses(tree: ast.Module) -> Dict[str, List[int]]:
    """Per function, the end-lines of its terminating runtime guard clauses.

    A disclosure at the TAIL of `main` is reached only because every earlier
    `if ...: return` declined to fire -- `lec_equivalence_check`'s shape.
    That IS a runtime condition; it is simply spelled as an early return
    rather than as an enclosing block, and a model that only knows enclosing
    blocks would report the most ordinary way a gate is written.
    """
    out: Dict[str, List[int]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        lines: List[int] = []
        for stmt in ast.walk(fn):
            if (isinstance(stmt, ast.If) and _terminates(stmt)
                    and _reads_runtime_state(stmt.test)):
                lines.append(stmt.end_lineno or stmt.lineno)
        out[fn.name] = lines
    return out


def audit_source(text: str, label: str) -> Tuple[List[dict], Optional[str]]:
    """Findings for one module, plus a reason it could not be analysed."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"unparseable: {exc.msg} (line {exc.lineno})"

    chains = _guard_chain(tree)
    owner = _function_of(tree)
    conditioned_funcs = _conditioned_callees(tree, chains)
    guards = _guard_clauses(tree)
    findings: List[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expr, ast.Return, ast.Raise, ast.Assign)):
            continue
        sentinel = _emits_sentinel(node)
        if sentinel is None:
            continue
        if _conditioned(chains.get(node, [])):
            continue
        if owner.get(node) in conditioned_funcs:
            continue
        here = getattr(node, "lineno", 0)
        if any(end < here for end in guards.get(owner.get(node), ())):
            continue
        findings.append({
            "file": label,
            "line": getattr(node, "lineno", 0),
            "sentinel": sentinel,
            "why": ("emitted with no enclosing test that reads runtime state "
                    "— it cannot decline to print"),
        })
    return findings, None


def gate_files(root: Path) -> List[Path]:
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not programs.is_dir():
        programs = root if root.name == "programs" else root / "programs"
    if not programs.is_dir():
        return []
    out = [p for p in sorted(programs.glob("*.py"))
           if p.name.endswith(GATE_SUFFIXES)]
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".",
                    help="the SUBJECT tree to judge (not where this program lives)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any finding (default: report and exit 0)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    files = gate_files(root)
    if not files:
        print(f"CANNOT CHECK: no programs/ directory under {root}", file=sys.stderr)
        return 2

    findings: List[dict] = []
    unanalysable: List[dict] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            unanalysable.append({"file": path.name, "reason": str(exc)})
            continue
        found, reason = audit_source(text, path.name)
        if reason:
            unanalysable.append({"file": path.name, "reason": reason})
        findings.extend(found)

    if args.json:
        print(json.dumps({
            "scanned": len(files),
            "findings": findings,
            "unanalysable": unanalysable,
        }, indent=2))
    else:
        print(f"scanned {len(files)} gate module(s) under {root}")
        for f in findings:
            print(f"  [UNCONDITIONED] {f['file']}:{f['line']}  {f['sentinel']!r}")
        for u in unanalysable:
            print(f"  [UNANALYSABLE]  {u['file']}: {u['reason']}")
        verdict = "PASS" if not findings else f"FAIL: {len(findings)} unconditioned disclosure(s)"
        print(verdict)

    if findings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
