#!/usr/bin/env python3
"""watchdog_ceiling_semantics_check.py — supervision is not a SHAPE, it is a
SEMANTICS. THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
====================
Owner rule, standing: "dont use timeout (we have phase-out this time-out
mechanism) to stop". `_watchdog.py` is the mechanism that replaces it, and the
one way to quietly restore what it replaced is to let a CLOCK stop a job again.

THE RULING THIS GATE NOW ENFORCES (2026-09-07, vibe-ic#2051)
============================================================
`hard_ceiling_s` is a RECORDED BUDGET. It is written into the run's sidecar and
announced when it is crossed, and the job CONTINUES. **Only the progress-stall
watchdog may stop a job**, and it stops one on evidence — every readable
forward-progress signal flat for `stall_grace_s` — never on elapsed time. A job
that is going nowhere while still busy has its own primitive, `abort_probe`,
which stops on the CALLER'S DOMAIN READ and returns the distinct RC_ABORTED.

That ruling MOVES THIS GATE'S QUESTION. Until v1.17.98 the offence was "a call
site declared a ceiling BELOW the backstop", because the supervisor killed at
whatever number it was handed and the docker path additionally wrapped the
container command in a GNU `timeout` at the same number. Neither is true any
more, so flagging a bounded ceiling would now be flagging something that cannot
hurt anyone — a gate asserting a defect the code no longer has is not strictness,
it is a false statement that a reader has to work to disbelieve.

What CAN still restore the kill is the mechanism itself, so that is what is
checked now.

THE OFFENCE CLASSES
===================
(0) THE PRIMITIVE KILLS ON THE CLOCK — **blocking**. Inside the supervision
    primitives themselves (`_watchdog.py`, `_docker_watchdog.py`), which every
    other class deliberately skips:

      * a `kill…(…, "ceiling")` call — the exact line the ruling removed
        (`supervise` used to read `kill_fn(proc, "ceiling"); return "ceiling"`).
        MEASURED 2026-09-06 on 8HD-9: two LEC yosys runs under
        `timeout --kill-after=5 86395`, one of them 5360 s into a proof at 1374
        points proved, 0 failed, 99.9 % CPU and still advancing. Restoring that
        line is the mutation this class exists to redden.
      * an OUTER CLOCK on the shared supervised dispatch — a function that
        launches through a supervisor AND wraps its command in
        `wrap_with_container_timeout`. `run_docker_supervised` did exactly that
        until #2051; `supervised_container_command` is the clock-free
        replacement, and the wrap's other purpose (tearing an orphan down whole)
        is served without it because `docker exec` already makes the stamping
        shell a process-group leader — MEASURED 2026-09-07 in the pinned image,
        `pid=pgid=sid` with no `timeout` present, and the identity reap leaving
        zero survivors where an unstamped control leaves all three alive.

(1) TIMEOUT-TO-A-PRIMITIVE-THAT-HAS-NONE — **blocking**, unchanged. `timeout=`
    passed to `_progress_run.run` / `.run_or_undetermined` / `.run_best_effort`.
    That module removed the parameter deliberately ("convert a call site by
    deleting the `timeout=` argument") and does NOT accept and ignore it, so the
    call raises TypeError — which is neither OSError nor SubprocessError and so
    slips past the `except` clauses these call sites are written with. MEASURED:
    1 of 108 `_progress_run` call sites on main, in the analog runner's A6
    advisory, where it took the whole A6_block_pv step down instead of degrading.

WHAT IS REPORTED RATHER THAN REFUSED, AND WHY IT IS STILL PRINTED
=================================================================
  * **BUDGET** — a supervised launch declaring a `hard_ceiling_s` below the
    module backstop. Since #2051 that number can no longer stop anything, so it
    is not an offence; it is the run's declared budget and the reader is
    entitled to see every one of them with its resolved value. This section IS
    the caller census the ruling asks for — "every caller passing an explicit
    `hard_ceiling_s`, and what the value now means" — computed rather than
    hand-listed, so it cannot go stale the way a written list does.
  * **RESIDUAL_CONTAINER_CLOCK** — a NON-primitive file that builds its own
    supervised dispatch and still wraps the container command in a GNU
    `timeout`. `phase3_one_shot_runner._docker_exec` is one: it is a second copy
    of the supervised dispatch, owned by another lane, and the ruling is not
    fully in force until its holder removes the wrap there too. Reported with
    file and line rather than refused, because this gate's author cannot fix a
    file it does not own and a silent clean verdict would say the work was done.
    A reader gets the residual by name; nobody gets to forget it.
  * a ceiling whose value this file cannot resolve — a call, a parameter, a
    local bound from a call. Those are NOT silently cleared: each is COUNTED and
    PRINTED as UNJUDGED with its file, line and source expression, so a reader
    sees what the resolver could not decide instead of inferring it from a clean
    verdict.
  * a `_docker_exec` with no `marker=` — the short raw-probe path, a different
    (bounded, correct) mechanism, judged by `loop_watchdog_compliance`.

A BOUND IS A BOUND WHATEVER ITS SPELLING
========================================
The resolver is kept in full even though a bound is no longer an offence,
because the BUDGET census is only worth reading if it resolves the spellings
real call sites use. This is `ci_harness_timeout_ceiling_check`'s #1277 lesson
applied one layer over: a resolver that reads only literals DROPS the very sites
this gate was written for. The two headline offences on main were spelled
``hard_ceiling_s=float(timeout)`` (a parameter, defaulted at the enclosing
``def``) and ``hard_ceiling_s=_drc_budget`` (a local bound from
``_drc_wall_budget_s()``, whose own fallback literal is the budget). Neither is
a `Constant` at the call site, and dropping them would make the census a list of
the easy cases.

RESIDUAL BOUNDARIES, STATED RATHER THAN LEFT SILENT
----------------------------------------------------
  * class (1) recognises ``import _progress_run as X`` -> ``X.run(...)``. A
    ``from _progress_run import run`` -> bare ``run(...)`` would not be seen.
    MEASURED on this tree: ZERO files use that form, so the rule covers the
    whole population today -- but it covers it by luck of style, not by
    construction, and a reader is entitled to know which.
  * a ``**kwargs`` splat into a supervised launch could carry a ceiling this
    file cannot see. MEASURED on this tree: TWO splat sites exist -- one inside
    `_watchdog` itself (outside this scan by construction) and one in
    `gate_discloses_denominator_check`, whose dict is built two lines above the
    call and carries only ``poll_s``. So no ceiling hides in a splat today.
  * the same-file function resolver keys on the function NAME. Two
    module-level functions sharing a name in one file resolve to the last
    definition. Every row is printed with its file and line, so a wrong
    resolution is visible rather than silent.

So resolution is by `ast` over, in order: a literal; ``float(X)``/``int(X)``
around anything resolvable; ``math.inf``; a module-level constant in the same
file; a LOCAL assignment in the enclosing function; the enclosing function's
PARAMETER DEFAULT; ``os.environ.get(KEY, DEFAULT)`` -> the default (an env
budget IS a ceiling, and its default is the one every run without the variable
gets); ``max(...)``/``min(...)`` over whatever resolves; a call to a
module-level function IN THE SAME FILE -> the MINIMUM of its statically
resolvable `return` values, which is the conservative read of "can this be
bounded"; and any spelling of `DEFAULT_HARD_CEILING_S`, resolved to the value
`_watchdog.py` itself declares. No file is imported and no code runs.

CLI
===
    watchdog_ceiling_semantics_check.py [ROOT] [--programs-dir DIR]
                                        [--table] [--json OUT]

`--table` prints the full CENSUS — every supervised launch in the tree and the
ceiling it declares — which is the same population the verdict is computed over,
so the report and the verdict can never disagree about what was looked at.

Exit codes: 0 = clean, 1 = >=1 offender, 2 = usage/parse error.
chip-AGNOSTIC + tool-AGNOSTIC + PDK-AGNOSTIC: Python AST shapes only.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Kept in sync with `_watchdog.DEFAULT_HARD_CEILING_S` by READING it, not by
#: copying the number: a second hand-written copy of a constant is the drift
#: shape this repo removes one gate at a time.
def _default_hard_ceiling_s(programs_dir: Path) -> float:
    """The backstop value `_watchdog` itself declares. Read from its source with
    `ast` so this gate never imports the tree it judges."""
    src = programs_dir / "_watchdog.py"
    try:
        tree = ast.parse(src.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return 86_400.0
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "DEFAULT_HARD_CEILING_S":
                    try:
                        return float(ast.literal_eval(node.value))
                    except (ValueError, TypeError):
                        return 86_400.0
    return 86_400.0


#: The supervisor entry points. A `_docker_exec` counts only WITH a marker —
#: without one it is the short raw-probe path and a different mechanism.
_SUPERVISOR_ATTRS = ("run_supervised", "run_host_supervised",
                     "run_docker_supervised")
_PROGRESS_RUN_ATTRS = ("run", "run_or_undetermined", "run_best_effort")

#: Files that DEFINE the mechanism, and so legitimately name its parameters.
_PRIMITIVES = {"_watchdog.py", "_docker_watchdog.py", "_progress_run.py",
               "_owned_process_supervisor.py"}
_SELF = "watchdog_ceiling_semantics_check.py"

_EXEMPT_TAG = "# ceiling-exempt:"


def _callee(node: ast.Call) -> str:
    f = node.func
    parts: List[str] = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


def _is_supervisor_call(node: ast.Call) -> bool:
    f = node.func
    attr = (f.attr if isinstance(f, ast.Attribute)
            else f.id if isinstance(f, ast.Name) else "")
    if attr in _SUPERVISOR_ATTRS:
        return True
    if attr == "_docker_exec":
        return any(k.arg == "marker" for k in node.keywords)
    return False


def _progress_run_aliases(tree: ast.AST) -> set:
    """Names `_progress_run` was imported under in this module."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "_progress_run":
                    out.add(a.asname or a.name)
    return out


def _module_constants(tree: ast.AST) -> Dict[str, ast.AST]:
    """MODULE-LEVEL `NAME = <expr>` bindings, in source order (last wins)."""
    out: Dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
    return out


class _Ctx:
    """Everything the resolver may read, gathered once per file.

    `consts`  module-level NAME -> expr
    `locals_` enclosing-function NAME -> expr (params' defaults included)
    `funcs`   module-level function name -> its FunctionDef
    `backstop` the value `_watchdog.py` declares, for `DEFAULT_HARD_CEILING_S`
    """

    def __init__(self, consts, funcs, backstop):
        self.consts = consts
        self.funcs = funcs
        self.backstop = backstop
        self.locals_: Dict[str, ast.AST] = {}


def _function_locals(fn: ast.AST) -> Dict[str, ast.AST]:
    """NAME -> expr for the function's own assignments AND parameter defaults.

    A parameter default is not a `Constant` at the call site and not a module
    constant, so without it `hard_ceiling_s=float(timeout)` in a
    `def _docker(..., timeout=120, ...)` resolves to nothing at all.
    """
    out: Dict[str, ast.AST] = {}
    a = getattr(fn, "args", None)
    if a is not None:
        pos = list(getattr(a, "posonlyargs", [])) + list(a.args)
        for arg, default in zip(pos[len(pos) - len(a.defaults):], a.defaults):
            out[arg.arg] = default
        for arg, default in zip(a.kwonlyargs, a.kw_defaults):
            if default is not None:
                out[arg.arg] = default
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, node.value)
    return out


def _returns_of(fn: ast.AST) -> List[ast.AST]:
    return [n.value for n in ast.walk(fn)
            if isinstance(n, ast.Return) and n.value is not None]


def _resolve(expr: ast.AST, ctx: "_Ctx", _depth: int = 0) -> Optional[float]:
    """A float, or None when this file cannot decide. None is NEVER treated as
    clean — the caller reports it as UNJUDGED."""
    if _depth > 8 or expr is None:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, (int, float)):
        return float(expr.value)
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            return float(expr.value)
        except ValueError:
            return None
    # any spelling of the primitive's own backstop constant
    name = (expr.attr if isinstance(expr, ast.Attribute)
            else expr.id if isinstance(expr, ast.Name) else "")
    if name == "DEFAULT_HARD_CEILING_S":
        return ctx.backstop
    # math.inf
    if (isinstance(expr, ast.Attribute) and expr.attr == "inf"
            and isinstance(expr.value, ast.Name) and expr.value.id == "math"):
        return math.inf
    if isinstance(expr, ast.Call):
        callee = expr.func
        cname = (callee.attr if isinstance(callee, ast.Attribute)
                 else callee.id if isinstance(callee, ast.Name) else "")
        if cname in ("float", "int") and len(expr.args) == 1:
            return _resolve(expr.args[0], ctx, _depth + 1)
        if cname in ("max", "min") and expr.args:
            vals = [v for v in (_resolve(a, ctx, _depth + 1)
                                for a in expr.args) if v is not None]
            if not vals:
                return None
            return max(vals) if cname == "max" else min(vals)
        # os.environ.get(KEY, DEFAULT) / os.getenv(KEY, DEFAULT): an env budget
        # IS a ceiling, and its DEFAULT is what every run without the variable
        # gets. Judging the default is judging the shipped behaviour.
        if cname in ("get", "getenv") and len(expr.args) == 2:
            return _resolve(expr.args[1], ctx, _depth + 1)
        # a module-level function in THIS file: the minimum of its statically
        # resolvable returns — the conservative read of "can this be bounded".
        if isinstance(callee, ast.Name) and callee.id in ctx.funcs:
            fn = ctx.funcs[callee.id]
            inner = _Ctx(ctx.consts, ctx.funcs, ctx.backstop)
            inner.locals_ = _function_locals(fn)
            vals = [v for v in (_resolve(r, inner, _depth + 1)
                                for r in _returns_of(fn)) if v is not None]
            return min(vals) if vals else None
        return None
    if isinstance(expr, ast.Name):
        if expr.id in ctx.locals_:
            # Guard the self-reference `hard_ceiling_s=hard_ceiling_s` where the
            # parameter has no default: `_function_locals` then has no entry and
            # this branch is not taken, which is correct — it is UNJUDGED.
            nxt = ctx.locals_[expr.id]
            if not (isinstance(nxt, ast.Name) and nxt.id == expr.id):
                return _resolve(nxt, ctx, _depth + 1)
        if expr.id in ctx.consts:
            return _resolve(ctx.consts[expr.id], ctx, _depth + 1)
    return None


def _exempted(src_lines: List[str], node: ast.AST) -> Optional[str]:
    """The `# ceiling-exempt: <reason>` reason, or None. The tag may sit
    anywhere inside the statement's source span or on the line above it; the
    reason after the colon must be non-empty."""
    start = max(1, getattr(node, "lineno", 1) - 1)
    end = getattr(node, "end_lineno", getattr(node, "lineno", 1))
    for i in range(start, min(end, len(src_lines)) + 1):
        line = src_lines[i - 1]
        if _EXEMPT_TAG in line:
            reason = line.split(_EXEMPT_TAG, 1)[1].strip()
            if reason:
                return reason
    return None


class Row:
    __slots__ = ("file", "line", "callee", "kind", "expr", "value", "verdict",
                 "detail")

    def __init__(self, file, line, callee, kind, expr, value, verdict, detail):
        self.file, self.line, self.callee = file, line, callee
        self.kind, self.expr, self.value = kind, expr, value
        self.verdict, self.detail = verdict, detail

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


def scan_file(path: Path, backstop: float, *, src: Optional[str] = None,
              tree: Optional[ast.AST] = None) -> List[Row]:
    if src is None:
        src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    if tree is None:
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            return [Row(path.name, getattr(exc, "lineno", 0) or 0, "-", "parse",
                        "", None, "UNJUDGED", f"SyntaxError: {exc}")]
    consts = _module_constants(tree)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    pr_aliases = _progress_run_aliases(tree)
    ctx = _Ctx(consts, funcs, backstop)

    # Which function encloses each line, so a call's LOCAL bindings and the
    # enclosing `def`'s parameter defaults are in scope for the resolver. The
    # INNERMOST enclosing function wins.
    enclosing: Dict[int, ast.AST] = {}
    for fn in funcs.values():
        for ln in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1):
            prev = enclosing.get(ln)
            if prev is None or fn.lineno >= prev.lineno:
                enclosing[ln] = fn

    _locals_cache: Dict[int, Dict[str, ast.AST]] = {}
    rows: List[Row] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = enclosing.get(node.lineno)
        # CACHED per function: `_function_locals` walks the whole body, and
        # calling it once per CALL node is quadratic in the runner files
        # (phase3 is 50k lines). Measured before the cache: one file did not
        # finish in two minutes.
        if fn is None:
            ctx.locals_ = {}
        else:
            key = id(fn)
            if key not in _locals_cache:
                _locals_cache[key] = _function_locals(fn)
            ctx.locals_ = _locals_cache[key]

        # ---- class (2): timeout= to a primitive that has no such parameter
        f = node.func
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id in pr_aliases
                and f.attr in _PROGRESS_RUN_ATTRS):
            if any(k.arg == "timeout" for k in node.keywords):
                why = _exempted(lines, node)
                rows.append(Row(
                    path.name, node.lineno, _callee(node),
                    "progress_run_timeout", "timeout=", None,
                    "EXEMPT" if why else "OFFENDER",
                    why or ("`_progress_run` has no `timeout` parameter — this "
                            "call raises TypeError, which is neither OSError nor "
                            "SubprocessError and so is not caught beside it. "
                            "Delete the argument.")))
                continue
            # ---- class (3): a CLEAN call to the replacement primitive.
            #
            # CZT2 — this class was missing, and its absence made the gate's own
            # headline number unable to move in the direction the gate exists to
            # push. `_pr.run` calls were counted ONLY when they were offenders,
            # so converting a `subprocess.run(timeout=N)` wall clock to the
            # supervised primitive changed the examined-site count by ZERO: the
            # old call was never in the population and the new one was not
            # either. MEASURED: twenty such conversions in one lane, examined
            # count 115 before and 115 after.
            #
            # That matters because the number is used as a MONOTONICITY check --
            # "never fewer examined sites, a shrink means something left
            # supervision". A count that cannot rise when supervision spreads
            # cannot fall when it retreats either, so the check was answering a
            # question about a population it did not contain.
            rows.append(Row(
                path.name, node.lineno, _callee(node), "progress_run", "-",
                None, "CLEAN",
                "supervised on the child's own forward progress (output / CPU "
                "/ IO), with no wall clock of any kind"))
            continue

        # ---- class (1): a bounded ceiling on a supervised launch
        if not _is_supervisor_call(node):
            continue
        kw = next((k for k in node.keywords if k.arg == "hard_ceiling_s"), None)
        if kw is None:
            rows.append(Row(path.name, node.lineno, _callee(node), "ceiling",
                            "<default>", backstop, "CLEAN",
                            "no ceiling declared — the primitive's own backstop"))
            continue
        expr = ast.unparse(kw.value)
        val = _resolve(kw.value, ctx)
        if val is None:
            rows.append(Row(path.name, node.lineno, _callee(node), "ceiling",
                            expr, None, "UNJUDGED",
                            "value not statically resolvable in this file"))
        elif val >= backstop:
            rows.append(Row(path.name, node.lineno, _callee(node), "ceiling",
                            expr, val, "CLEAN",
                            "at or above the module backstop — the default "
                            "budget, declared explicitly"))
        else:
            # NOT AN OFFENCE SINCE vibe-ic#2051. This row used to read
            # OFFENDER, on the true-at-the-time ground that "the supervisor
            # kills at it regardless of forward progress". It does not any
            # more: crossing the ceiling writes a `hard_ceiling` event, the
            # notice fires once, and the job runs on. The number is a declared
            # BUDGET, so it is resolved and PRINTED — a reader gets every
            # caller and its value — and it refuses nothing.
            rows.append(Row(
                path.name, node.lineno, _callee(node), "ceiling", expr, val,
                "BUDGET",
                f"a declared budget of {val:g}s (below the {backstop:g}s "
                f"module default). Since vibe-ic#2051 this value cannot stop "
                f"the job: at the crossing the supervisor records a "
                f"`hard_ceiling` event, notifies, and CONTINUES. Only a "
                f"progress STALL stops a job; a job that is busy but going "
                f"nowhere is stopped by an `abort_probe` over its OWN output "
                f"(rc RC_ABORTED), which is a measurement rather than a clock."))
    return rows


#: The supervision primitives, scanned by class (0) ONLY — the mechanism that
#: every other class deliberately skips. A primitive that is absent from the
#: tree under test yields NO row: "the file is not here" is not "the file kills
#: on a clock", and a gate that refused on absence would be answering a
#: question about the corpus while claiming to answer one about the code.
_PRIMITIVE_KILL_FILES = ("_watchdog.py", "_docker_watchdog.py")

#: The wrap that puts a GNU `timeout` in front of an in-container command.
#: Legitimate in front of a RAW `docker exec` driven by a host-side
#: `subprocess.run(timeout=)` (killing the client there orphans the tool);
#: never legitimate in front of a SUPERVISED launch, which has a supervisor.
_OUTER_CLOCK_WRAP = "wrap_with_container_timeout"


def _enclosing_functions(fns: List[ast.AST]) -> Dict[int, ast.AST]:
    """line -> the INNERMOST function enclosing it, from an ALREADY-COLLECTED
    function list.

    It takes the list rather than the tree because its caller has just walked
    that tree and holds every `FunctionDef` in it. Re-walking to find them again
    was MEASURED at 9.1 s of this scan's 19.2 s under cProfile — `ast.walk` is
    the whole cost of this gate and every avoidable pass over a 50k-line runner
    shows up in a landing.
    """
    out: Dict[int, ast.AST] = {}
    for fn in fns:
        for ln in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1):
            prev = out.get(ln)
            if prev is None or fn.lineno >= prev.lineno:
                out[ln] = fn
    return out


def _is_ceiling_kill(node: ast.Call) -> bool:
    """A `kill...(..., "ceiling")` — a job terminated because a clock said so."""
    f = node.func
    name = (f.attr if isinstance(f, ast.Attribute)
            else f.id if isinstance(f, ast.Name) else "")
    if "kill" not in name.lower():
        return False
    for arg in list(node.args) + [k.value for k in node.keywords]:
        if isinstance(arg, ast.Constant) and arg.value == "ceiling":
            return True
    return False


def _call_name(node: ast.Call) -> str:
    f = node.func
    return (f.attr if isinstance(f, ast.Attribute)
            else f.id if isinstance(f, ast.Name) else "")


def scan_supervised_dispatch(path: Path, *, primitive: bool,
                             tree: Optional[ast.AST] = None) -> List[Row]:
    """Class (0): does this file let a CLOCK stop a supervised job?

    Two shapes, both measured on the code this ruling removed:

      * a `kill...(..., "ceiling")` anywhere in the file — only meaningful in a
        primitive, since only a primitive owns the supervision loop;
      * a function that launches through a supervisor AND wraps its command in
        an outer GNU `timeout` AT THE SAME VALUE it declares as its ceiling. In
        a PRIMITIVE that is an OFFENDER: the shared dispatch is the one place
        the whole plugin inherits from. In a runner that keeps its own copy of
        the dispatch it is a RESIDUAL — reported by file and line, refused by
        nobody here, because the fix belongs to that file's owner and a silent
        pass would claim work that was not done.

    ONE WALK OVER THE MODULE, then group the calls by enclosing function. The
    obvious shape — `ast.walk` each function's own body — re-walks every nested
    node once per ancestor. `scan_file` already learned this the hard way: its
    `_function_locals` cache carries the note that one uncached file "did not
    finish in two minutes".
    """
    if tree is None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return []
    rows: List[Row] = []
    # ONE walk: collect the functions and the calls together, then map the
    # calls onto the functions. Two walks (one to find the functions, one to
    # find the calls) is the shape this started as and it cost 9.1 s.
    fn_list: List[ast.AST] = []
    call_list: List[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_list.append(node)
        elif isinstance(node, ast.Call):
            call_list.append(node)
    enclosing = _enclosing_functions(fn_list)
    fns = {id(f): f for f in fn_list}
    by_fn: Dict[int, List[ast.Call]] = {}
    for node in call_list:
        if primitive and _is_ceiling_kill(node):
            rows.append(Row(
                path.name, node.lineno, _callee(node), "ceiling_kill",
                ast.unparse(node.func), None, "OFFENDER",
                "the supervision primitive TERMINATES a job because a "
                "clock elapsed. Since vibe-ic#2051 `hard_ceiling_s` is a "
                "RECORDED BUDGET and only a progress STALL may stop a job "
                "— this line reintroduces the wall clock that tore down a "
                "converging proof at 86395s. Record and continue; if the "
                "job must be stoppable, use `abort_probe` over its OWN "
                "output (rc RC_ABORTED), which is a measurement."))
        fn = enclosing.get(node.lineno)
        if fn is not None:
            by_fn.setdefault(id(fn), []).append(node)

    for key, calls in by_fn.items():
        fn = fns.get(key)
        if fn is None:
            continue
        ceilings = set()
        for c in calls:
            if not _is_supervisor_call(c):
                continue
            for k in c.keywords:
                if k.arg == "hard_ceiling_s":
                    ceilings.add(ast.unparse(k.value))
        if not ceilings:
            continue
        # THE MATCH IS ON THE VALUE, and that precision is load-bearing rather
        # than tidy. Merely "this function contains a wrap and also a supervised
        # launch" reports `lec_run._docker`, which has BOTH — a supervised
        # branch with no ceiling at all, and a short-probe fallback
        # (`_container_available`, `_docker_exec3`, at `timeout=30`/`60`) whose
        # `_pr.run` genuinely needs the wrap, because there a host-side bound
        # would kill the docker CLIENT and orphan the tool. That wrap is the
        # 2026-07-22 orphan guard doing its job, and naming it would be a
        # finding about the wrong branch.
        #
        # The offence is narrower and exact: the command handed to a SUPERVISED
        # launch is wrapped in a GNU `timeout` AT THE SAME VALUE the launch
        # declares as its ceiling — the budget spent twice, once as a record
        # and once as a SIGKILL.
        wrap = next((c for c in calls
                     if _call_name(c) == _OUTER_CLOCK_WRAP and len(c.args) >= 2
                     and ast.unparse(c.args[1]) in ceilings), None)
        if wrap is None:
            continue
        detail = (
            "a SUPERVISED launch whose in-container command is also wrapped "
            "in a GNU `timeout`. The wrap is an outer wall clock: it SIGKILLs "
            "the tool inside the container at the budget however well the job "
            "is going, which is exactly what vibe-ic#2051 removed. The wrap's "
            "other purpose — tearing a spawned tree down whole rather than "
            "orphaning it onto the good netlist — does not need it: `docker "
            "exec` already starts each exec in its own session, so the "
            "stamping shell is already the process-group leader and the "
            "identity reap signals the whole group. Use "
            "`_docker_watchdog.supervised_container_command`.")
        rows.append(Row(
            path.name, wrap.lineno, fn.name, "outer_clock",
            _OUTER_CLOCK_WRAP + "(...)", None,
            "OFFENDER" if primitive else "RESIDUAL_CONTAINER_CLOCK",
            detail if primitive else
            (detail + " REPORTED, NOT REFUSED: this file keeps its own copy of "
             "the supervised dispatch and is owned by another lane, so the "
             "ruling is not in force here until its holder removes the wrap. "
             "Naming it is the alternative to a clean verdict implying it was "
             "already done.")))
    rows.sort(key=lambda r: (r.line, r.kind))
    return rows


def scan(programs_dir: Path) -> Tuple[List[Row], float]:
    backstop = _default_hard_ceiling_s(programs_dir)
    rows: List[Row] = []
    for path in sorted(programs_dir.glob("*.py")):
        if path.name == _SELF:
            continue
        primitive = path.name in _PRIMITIVES
        # Class (0) runs over EVERY file, primitives included: they are the one
        # population the other classes skip, and they are where the kill lives.
        if primitive and path.name not in _PRIMITIVE_KILL_FILES:
            # `_progress_run` / `_owned_process_supervisor` define the mechanism
            # but own no supervision loop and no container wrap; scanning them
            # for class (0) would look thorough and could never find anything.
            continue
        # PARSE ONCE PER FILE. Class (0) and the class (1)/(2) scan both need
        # this file's AST, and reading + `ast.parse`-ing it a second time is
        # the dominant cost on a tree whose largest runner is 50k lines.
        # MEASURED, interleaved over three rounds on a quiet host: 12.1s for
        # this gate before this landing, 19.5s with a second parse per file.
        # It runs on every landing AND TWICE inside `gates are
        # host-independent`, whose workers carry a 600s budget — so a gate that
        # got slower is not a cosmetic concern, it is how a worker starves and
        # a verdict becomes "could not conclude".
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except OSError:
            continue
        except SyntaxError as exc:
            # Unparseable is UNJUDGED and PRINTED, never silently skipped.
            rows.append(Row(path.name, getattr(exc, "lineno", 0) or 0, "-",
                            "parse", "", None, "UNJUDGED",
                            f"SyntaxError: {exc}"))
            continue
        rows.extend(scan_supervised_dispatch(path, primitive=primitive,
                                             tree=tree))
        if primitive:
            continue
        rows.extend(scan_file(path, backstop, src=src, tree=tree))
    return rows, backstop


def _resolve_programs_dir(root: Optional[str],
                          explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.is_dir() else None
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    if (base / "programs").is_dir():
        return base / "programs"
    return base if base.is_dir() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=None)
    ap.add_argument("--programs-dir", default=None)
    ap.add_argument("--table", action="store_true",
                    help="print the full census, not only the offenders")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    pdir = _resolve_programs_dir(args.root, args.programs_dir)
    if pdir is None:
        print("[ERROR] no programs directory to scan", file=sys.stderr)
        return 2

    rows, backstop = scan(pdir)
    offenders = [r for r in rows if r.verdict == "OFFENDER"]
    unjudged = [r for r in rows if r.verdict == "UNJUDGED"]
    exempt = [r for r in rows if r.verdict == "EXEMPT"]
    budgets = [r for r in rows if r.verdict == "BUDGET"]
    residual = [r for r in rows if r.verdict == "RESIDUAL_CONTAINER_CLOCK"]
    clean = [r for r in rows if r.verdict == "CLEAN"]

    print(f"watchdog_ceiling_semantics_check — {pdir}")
    print(f"  backstop read from _watchdog.DEFAULT_HARD_CEILING_S: "
          f"{backstop:g}s")
    print(f"  the ceiling is a RECORDED BUDGET (vibe-ic#2051); only a "
          f"progress STALL may stop a job")
    print(f"  supervised launches + primitive calls examined: {len(rows)}")
    print(f"    CLEAN {len(clean)}   BUDGET {len(budgets)}   "
          f"EXEMPT {len(exempt)}   UNJUDGED {len(unjudged)}   "
          f"RESIDUAL {len(residual)}   OFFENDER {len(offenders)}")

    if args.table:
        print("\n--- CENSUS ---")
        for r in rows:
            print(f"  {r.verdict:<9} {r.file}:{r.line} {r.callee} "
                  f"{r.kind}={r.expr}"
                  + (f" -> {r.value:g}" if isinstance(r.value, float)
                     and math.isfinite(r.value) else ""))

    if budgets:
        # THE CALLER CENSUS the ruling asks for, computed rather than written
        # down: every site that declares an explicit budget, with the value the
        # resolver actually read. A hand-kept list of these goes stale on the
        # first edit; this one cannot.
        print("\n--- DECLARED BUDGETS (recorded, never a kill) ---")
        for r in budgets:
            print(f"  {r.file}:{r.line} {r.callee} "
                  f"hard_ceiling_s={r.expr} -> {r.value:g}s")

    if residual:
        print("\n--- RESIDUAL CONTAINER CLOCKS (BLOCKING) ---")
        for r in residual:
            print(f"  {r.file}:{r.line} {r.callee}() still wraps its "
                  f"supervised command in a GNU `timeout`")
            print(f"      {r.detail}")

    if unjudged:
        print("\n--- UNJUDGED (printed, never silently cleared) ---")
        for r in unjudged:
            print(f"  {r.file}:{r.line} {r.callee} {r.kind}={r.expr} "
                  f"— {r.detail}")

    if offenders:
        print("\n--- OFFENDERS ---")
        for r in offenders:
            print(f"\n  {r.file}:{r.line}  {r.callee}({r.kind}={r.expr})")
            print(f"      {r.detail}")

    if args.json:
        # vibe-ic#1082: this program's DECLARED report destination is written
        # through `_atomic_artefact`, so a reader never observes a half-written
        # verdict. `write_json` serialises FIRST and only then opens anything,
        # so a non-serialisable row fails with nothing on disk instead of
        # leaving a truncated artefact a later gate would parse as a fact.
        from _atomic_artefact import write_json as _write_json
        _write_json(args.json,
                    {"programs_dir": str(pdir), "backstop_s": backstop,
                     "ceiling_semantics": "recorded_budget_never_a_kill",
                     "rows": [r.as_dict() for r in rows],
                     "offenders": len(offenders), "unjudged": len(unjudged),
                     "budgets": len(budgets),
                     "residual_container_clocks": len(residual)},
                    indent=1)

    # CLASS (0) IS NOW BLOCKING. It was "reported, owned elsewhere" because the
    # one residual lived in a file that kept its own copy of the supervised
    # dispatch, so the ruling was not in force there and a clean verdict would
    # have implied a removal nobody had made. That holder has now routed
    # through `_docker_watchdog.run_docker_supervised` and dropped its wrap, so
    # the population is empty and the class can do what a class is for: refuse.
    # Reported-forever is how a known defect becomes permanent — the count was
    # printed and the exit code said PASS, so nothing downstream could act on
    # it. A gate that cannot go red is not a gate.
    if offenders or residual:
        print(f"\n[FAIL] {len(offenders)} clock kill(s) / bad timeout "
              f"argument(s) and {len(residual)} residual container clock(s) "
              f"on supervised launches.")
        return 1
    print("\n[PASS] no clock may stop a supervised job: the primitives kill "
          "only on a progress stall, and no `timeout=` reaches a primitive "
          "that has none.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
