#!/usr/bin/env python3
"""watchdog_ceiling_semantics_check.py — supervision is not a SHAPE, it is a
SEMANTICS. THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
====================
Owner rule, standing: "dont use timeout (we have phase-out this time-out
mechanism) to stop". `_watchdog.py` is the mechanism that replaces it, and its
own docstring rules out the one use that quietly restores what it replaced::

    `hard_ceiling_s` (default 24h) is a pathological-infinite-loop backstop
    ONLY (a CPU-burning loop that never goes idle), NOT the primary control.

`loop_watchdog_compliance_check` already FORCES every long tool through that
supervisor. It reads the SHAPE of the call — is there a `marker=`, is the
callee a `run_supervised` — and there was nothing that read the SEMANTICS. So a
call site could satisfy that gate in full and then pin `hard_ceiling_s` to its
own step budget, which is a wall-clock deadline wearing the watchdog's clothes:
`run_supervised` kills at the ceiling regardless of progress, and both docker
paths additionally wrap the container-side command in a GNU ``timeout`` at that
same number, so the tool is SIGKILLed inside the container too.

MEASURED ON MAIN AT ad38a76d, four sites did exactly that:

    lec_run._docker              hard_ceiling_s=float(timeout)   7200 s default
    phase3 _try_svrf_native_drc  hard_ceiling_s=_drc_budget      7200 s default
    phase3 pad-ring seed         hard_ceiling_s=1800
    phase3 io_view_discover      hard_ceiling_s=300

and the first one was live: on 2026-09-06 a post-layout LEC on an open
benchmark IC had run as ONE Yosys process for 5360 s of a 7195 s budget, 1374
points proved, 0 failed, 99.9 % CPU, still advancing. Had the ceiling fired,
the flow would have recorded a design it never compared. A killed run and a
real failure are the same exit code; this repo's own lesson is that rc=143 is
not a test result, and the same is true of a proof.

A BIGGER NUMBER IS THE SAME DEFECT WITH A LATER DATE, which is why this gate
does not check that a ceiling is "big enough". It checks that the ceiling is
not being used as a control at all.

THE TWO OFFENCE CLASSES
=======================
(1) CEILING-AS-DEADLINE — a call into a progress-stall supervisor that passes a
    `hard_ceiling_s` BELOW `_watchdog.DEFAULT_HARD_CEILING_S`. The supervisor
    entry points are the four this plugin has: `_watchdog.run_supervised`,
    `_watchdog.run_host_supervised`, `_docker_watchdog.run_docker_supervised`,
    and a runner's `_docker_exec(..., marker=...)` (the marker is what routes
    it through the supervisor at all — without one it is a short raw probe and
    outside this gate's population).

    A step that genuinely must be stopped short has a correct primitive already:
    `abort_probe`, which stops a job whose OWN domain signal says it is going
    nowhere and returns the distinct rc RC_ABORTED with a stated reason. That is
    a measurement; a clock is not.

(2) TIMEOUT-TO-A-PRIMITIVE-THAT-HAS-NONE — `timeout=` passed to
    `_progress_run.run` / `.run_or_undetermined` / `.run_best_effort`. That
    module removed the parameter deliberately ("convert a call site by deleting
    the `timeout=` argument") and does NOT accept and ignore it, so the call
    raises TypeError — which is neither OSError nor SubprocessError and so
    slips past the `except` clauses these call sites are written with. MEASURED:
    1 of 108 `_progress_run` call sites on main, in the analog runner's A6
    advisory, where it took the whole A6_block_pv step down instead of degrading.

WHAT IS *NOT* FLAGGED, AND WHY THE UNJUDGEABLE ARE PRINTED
===========================================================
  * `hard_ceiling_s=float("inf")` and any value at or above the module default
    — those ARE the backstop, used as a backstop.
  * a `_docker_exec` with no `marker=` — that is the short raw-probe path, a
    different (bounded, correct) mechanism, judged by `loop_watchdog_compliance`.
  * `# ceiling-exempt: <reason>` on the offending statement (anywhere in its
    source span, or the line immediately above). The reason must be non-empty:
    a bare tag exempts nothing.
  * a ceiling whose value this file cannot resolve — a call, a parameter, a
    local bound from a call. Those are NOT silently cleared: each is COUNTED and
    PRINTED as UNJUDGED with its file, line and source expression, so a reader
    sees what the resolver could not decide instead of inferring it from a clean
    verdict. (`phase3._pnr_ceiling` is one of these, and it is covered from the
    other side by `test_v1_3_47_stall_watchdog`, which asserts
    `_pnr_hard_ceiling_s(cells) >= _WATCHDOG_HARD_CEILING_S`.)

A BOUND IS A BOUND WHATEVER ITS SPELLING
========================================
This is `ci_harness_timeout_ceiling_check`'s #1277 lesson applied one layer
over. A resolver that reads only literals DROPS the very sites this gate was
written for: the two worst offences on main were spelled
``hard_ceiling_s=float(timeout)`` (a parameter, defaulted at the enclosing
``def``) and ``hard_ceiling_s=_drc_budget`` (a local bound from
``_drc_wall_budget_s()``, whose own fallback literal is the budget). Neither is
a `Constant` at the call site, and dropping them is worse than flagging them
wrongly, because a report that lists neither tells a reader nothing was skipped.

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


def scan_file(path: Path, backstop: float) -> List[Row]:
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
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
                and f.attr in _PROGRESS_RUN_ATTRS
                and any(k.arg == "timeout" for k in node.keywords)):
            why = _exempted(lines, node)
            rows.append(Row(
                path.name, node.lineno, _callee(node), "progress_run_timeout",
                "timeout=", None,
                "EXEMPT" if why else "OFFENDER",
                why or ("`_progress_run` has no `timeout` parameter — this "
                        "call raises TypeError, which is neither OSError nor "
                        "SubprocessError and so is not caught beside it. "
                        "Delete the argument.")))
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
        why = _exempted(lines, node)
        if val is None:
            rows.append(Row(path.name, node.lineno, _callee(node), "ceiling",
                            expr, None, "UNJUDGED",
                            "value not statically resolvable in this file"))
        elif val >= backstop:
            rows.append(Row(path.name, node.lineno, _callee(node), "ceiling",
                            expr, val, "CLEAN",
                            "at or above the pathological backstop"))
        elif why:
            rows.append(Row(path.name, node.lineno, _callee(node), "ceiling",
                            expr, val, "EXEMPT", why))
        else:
            rows.append(Row(
                path.name, node.lineno, _callee(node), "ceiling", expr, val,
                "OFFENDER",
                f"a bounded ceiling ({val:g}s < {backstop:g}s) on a SUPERVISED "
                f"launch is a wall-clock deadline: the supervisor kills at it "
                f"regardless of forward progress, and the docker paths wrap the "
                f"container command in a GNU `timeout` at the same number. A "
                f"still-progressing tool dies with no verdict. If this step "
                f"must be stoppable, express the reason as an `abort_probe` "
                f"predicate over its OWN output (rc RC_ABORTED), not as a clock."))
    return rows


def scan(programs_dir: Path) -> Tuple[List[Row], float]:
    backstop = _default_hard_ceiling_s(programs_dir)
    rows: List[Row] = []
    for path in sorted(programs_dir.glob("*.py")):
        if path.name in _PRIMITIVES or path.name == _SELF:
            continue
        rows.extend(scan_file(path, backstop))
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
    clean = [r for r in rows if r.verdict == "CLEAN"]

    print(f"watchdog_ceiling_semantics_check — {pdir}")
    print(f"  backstop read from _watchdog.DEFAULT_HARD_CEILING_S: "
          f"{backstop:g}s")
    print(f"  supervised launches + primitive calls examined: {len(rows)}")
    print(f"    CLEAN {len(clean)}   EXEMPT {len(exempt)}   "
          f"UNJUDGED {len(unjudged)}   OFFENDER {len(offenders)}")

    if args.table:
        print("\n--- CENSUS ---")
        for r in rows:
            print(f"  {r.verdict:<9} {r.file}:{r.line} {r.callee} "
                  f"{r.kind}={r.expr}"
                  + (f" -> {r.value:g}" if isinstance(r.value, float)
                     and math.isfinite(r.value) else ""))

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
        Path(args.json).write_text(json.dumps(
            {"programs_dir": str(pdir), "backstop_s": backstop,
             "rows": [r.as_dict() for r in rows],
             "offenders": len(offenders), "unjudged": len(unjudged)},
            indent=1), encoding="utf-8")

    if offenders:
        print(f"\n[FAIL] {len(offenders)} bounded ceiling(s) / bad timeout "
              f"argument(s) on supervised launches.")
        return 1
    print("\n[PASS] no supervised launch is bounded by a wall clock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
