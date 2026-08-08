#!/usr/bin/env python3
"""
flow_gate_enforcement_audit.py — which flow gates can actually STOP a run, and
which only get to complain afterwards (#306).

The defect
----------
`cts_quality_check` exists, is wired into `flow/phase1_phase2_phase3.yaml`, has
tests, and FAILed correctly on the SAME cell across three consecutive plugin
versions. The flow ran to completion every time: post_cts.def 44 MB,
routed.def 181 MB, post_hold.def 44 MB. It is the one gate that could have
caught #300 (the clock port bound to a 0-sink decoy) at source. It caught it
three times and stopped nothing. Eleven gates FAILed in that same run.

Root cause, measured by this program: the step runners execute the flow's
`program_exit_zero` gates NOWHERE. The gates are evaluated only by
`flow_compliance_check`, which the runner invokes as `final_audit` — the LAST
step, after every artefact has already been written. So a gate cannot block the
step it guards; it can only describe, afterwards, a run that already happened.

A gate that FAILs but cannot block differs from no gate at all only in that the
failure is searchable later.

What this audits
----------------
For every `program_exit_zero` gate in the flow definition:

  ENFORCED    a runner invokes it inline AND the exit status of that
              invocation reaches a control-flow decision, so it can stop the
              step it guards
  AUDIT_ONLY  its verdict cannot stop the step — it describes, it does not
              block. The `wiring` field on each row says WHY (see #884 below):
              the runner may never invoke it at all, or invoke it and throw
              the exit status away.
  DECLARED    the gate program declares its own intent in its docstring via
              `ENFORCEMENT: blocking` or `ENFORCEMENT: advisory`
  UNDECLARED  no declaration — the intent is unknown, which is how 66 of 72
              gates ended up de-facto advisory without anyone deciding that

This program DESCRIBES; it does not change flow behaviour. Turning audit-only
gates into blocking ones is a deliberate product decision with real blast
radius (11 gates FAILing in one run means those runs start failing — correctly,
but that is an owner's call, not a side effect of an audit tool).

Exit codes:
    0  audit completed
    1  a gate DECLARING `ENFORCEMENT: blocking` is only AUDIT_ONLY — a
       contradiction between stated intent and wiring
    2  I/O error
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_HERE = Path(__file__).resolve().parent
_RUNNERS = ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
            "vibe_ic_one_shot_runner.py", "phase23_one_shot_runner.py",
            "phase1_one_shot_runner.py", "analog_one_shot_runner.py")
_GATE_RE = re.compile(
    # #306 — `advisory_` is the non-blocking slot; a gate wired there IS wired.
    r"(?:optional_|advisory_)?program_exit_zero:\s*[\"']?([\w./-]+)")
_DECL_RE = re.compile(r"ENFORCEMENT:\s*(blocking|advisory)", re.IGNORECASE)
# The second channel: intent stated in the JSON the gate emits. Captures the
# WHOLE right-hand side, not just a leading string literal — see
# `declared_intent` for why a value-only match reads a conditional expression
# as an unconditional declaration.
_VERDICT_MODE_RE = re.compile(r'"verdict_mode":\s*([^,\n}]+)')
_LONE_MODE_RE = re.compile(r'^"(BLOCKS|ADVISES)"$')


def _flow_def(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    return _HERE.parent / "flow" / "phase1_phase2_phase3.yaml"


def gates_in_flow(flow: Path) -> List[str]:
    return sorted(set(_GATE_RE.findall(flow.read_text(errors="replace"))))


def runner_source(programs: Path) -> str:
    out = []
    for r in _RUNNERS:
        p = programs / r
        if p.is_file():
            out.append(p.read_text(errors="replace"))
    return "\n".join(out)


def _invoked(src: str, gate: str) -> bool:
    """A runner NAMES the gate — as a subprocess command string or as an
    imported call. A bare mention in a comment does not count.

    #884: this answers "does a runner name this gate", NOT "can this gate stop
    the step". Being named is necessary for enforcement and nowhere near
    sufficient — a runner that spawns a gate and discards its exit status is
    textually identical to one that stops on it. `audit()` therefore uses this
    only as a cheap pre-filter and decides ENFORCED with `gate_wiring()`, which
    reads the exit status instead of the filename.
    """
    stem = gate[:-3] if gate.endswith(".py") else gate
    if re.search(r"[\"'][^\"'\n]*\b" + re.escape(stem) + r"\.py\b", src):
        return True
    return bool(re.search(r"\b" + re.escape(stem) + r"\s*\.\s*(?:main|check|audit)\s*\(", src))


# ---------------------------------------------------------------------------
# #884 — A FILENAME INSIDE A STRING IS NOT ENFORCEMENT.
#
# This audit used to conclude ENFORCED from `_invoked()` alone, which asks one
# question: does the gate's filename appear inside a string literal in a
# runner? That is a question about TEXT. A runner that spawns a gate and throws
# the exit status away is textually indistinguishable from one that stops the
# step on it, so the audit reported gates as able to block that the runner had
# already decided to ignore. An audit of checks that lie, lying in the same
# way, is the worst version of this defect: it is the instrument everything
# else trusts.
#
# MEASURED — 4 of the 19 gates this audit called ENFORCED, at the commit this
# note was written against:
#
#   rtl_hygiene_lint   design_one_shot_runner.py:1368
#       `rc, out, err = _run([... rtl_hygiene_lint.py ...])`. `_run` RETURNS
#       `(rc, out, err)`, so the decision belongs to the caller — and the
#       caller binds `rc` and never reads it again, scraping `out`/`err` for a
#       repair count instead.
#   dfm_screen_check   phase3_one_shot_runner.py:30690
#       `subprocess.run([... dfm_screen_check.py ...], check=False)` — the
#       result is not bound at all.
#   bsdl_emit          design_one_shot_runner.py:11128
#       the same unbound shape, inside `try: ... except Exception: pass`. The
#       `r.returncode` eleven lines later belongs to a DIFFERENT subprocess
#       (`r` is bound at :11068, the ATPG engine run) — textual proximity read
#       as consumption.
#   sdc_syntax_check   phase3_one_shot_runner.py:29980
#       `r = subprocess.run(...)`, `r.returncode` never read. The runner's own
#       comment says it pre-creates the artefact so a later file-presence gate
#       "passes without depending on the gate's invocation order" — i.e. the
#       gate's verdict is explicitly not what makes that step green.
#
# ENFORCED now requires a proof rather than a substring: the exit status of the
# process that runs the gate must reach a control-flow decision. Text search
# cannot answer that, so this parses. Every branch of the analysis is
# conservative in the SAME direction — when it runs out of road it says
# "unknown", and unknown is not ENFORCED, because the failure this whole
# campaign is about is a check that overstates what it verified.
#
# The `wiring` field records WHICH of the four situations a gate is in; only
# the first can stop a step:
#
#   INLINE_BLOCKING        a runner spawns it and the exit status reaches an
#                          if/while/assert/ternary test, or leaves the function
#                          as a return/raise/sys.exit value, or the call raises
#                          on non-zero by itself and nothing swallows it
#   INLINE_STATUS_IGNORED  a runner spawns it and provably discards the status
#                          — the #884 class. Strictly worse than never wiring
#                          it: it costs the runtime of a real gate, buys
#                          nothing, and LOOKS wired to a reader and to this
#                          audit's previous self.
#   INLINE_UNPROVEN        named in runner source, but through an indirection
#                          this analysis will not follow. Not enforcement:
#                          unknown is not yes.
#   NOT_INVOKED            no runner names it. Reached only by the final
#                          compliance audit, after every artefact is written.
#
# chip-AGNOSTIC by construction: nothing here knows a design, PDK, vendor or
# cell name. It reads Python control flow.
# ---------------------------------------------------------------------------

#: `subprocess.<attr>(...)` entry points that start a process.
_SPAWN_ATTRS = frozenset({"run", "call", "check_call", "check_output", "Popen"})
#: These raise `CalledProcessError` on a non-zero exit all by themselves, so a
#: non-zero status influences control flow without anyone reading `.returncode`.
_RAISING_ATTRS = frozenset({"check_call", "check_output"})
#: Attributes of a `CompletedProcess`/`Popen` that ARE the exit status.
_STATUS_ATTRS = frozenset({"returncode", "check_returncode", "wait", "poll"})
#: A helper that returns `(rc, out, err)` tells us which element is the status
#: only by its NAME. These are runner-wide conventions, not design/PDK/cell
#: identifiers, so this stays chip-agnostic. An unpack matching none of them
#: yields UNPROVEN, never ENFORCED.
_STATUS_NAME_RE = re.compile(
    r"^_*(?:rc|ret|retcode|returncode|return_code|rv|code|status|"
    r"exit_code|exitcode|exit_status)_*\d*_*$", re.IGNORECASE)
#: How many renames to follow when the status is carried onward
#: (`ok = rc == 0` ... `if not ok:`). Bounded so the audit always terminates.
_MAX_TAINT_HOPS = 4
#: How many hops to follow a gate NAME from its literal to the process that
#: spawns it (`"g.py"` -> table -> loop variable -> dispatcher argument).
_MAX_NAME_HOPS = 4

INLINE_BLOCKING = "INLINE_BLOCKING"
INLINE_STATUS_IGNORED = "INLINE_STATUS_IGNORED"
INLINE_UNPROVEN = "INLINE_UNPROVEN"
NOT_INVOKED = "NOT_INVOKED"
#: Weakest to strongest; `audit()` keeps the strongest wiring across runners.
_WIRING_ORDER = (NOT_INVOKED, INLINE_UNPROVEN, INLINE_STATUS_IGNORED,
                 INLINE_BLOCKING)
#: Everything that is not this cannot stop the step it guards.
BLOCKING_WIRING = INLINE_BLOCKING

#: module scope, for the (scope, name) pairs the name-flow analysis carries
_MODULE_SCOPE = 0

#: per-launch-site verdicts, weakest to strongest
_IGNORED, _UNPROVEN, _BLOCKS = "IGNORED", "UNPROVEN", "BLOCKS"
_SITE_ORDER = (_IGNORED, _UNPROVEN, _BLOCKS)
#: how a launch site's verdict names the gate's wiring
_SITE_TO_WIRING = {_BLOCKS: INLINE_BLOCKING,
                   _UNPROVEN: INLINE_UNPROVEN,
                   _IGNORED: INLINE_STATUS_IGNORED}


def _mark(root: ast.AST, sink: Set[int]) -> None:
    for n in ast.walk(root):
        sink.add(id(n))


def _stored_names(target: ast.AST) -> List[str]:
    return [n.id for n in ast.walk(target)
            if isinstance(n, ast.Name) and n.id != "_"]


def _is_status_expr(node: ast.AST) -> bool:
    """`cp.returncode`, or a bare name spelled like an exit status."""
    if isinstance(node, ast.Attribute) and node.attr in _STATUS_ATTRS:
        return True
    return bool(isinstance(node, ast.Name)
                and _STATUS_NAME_RE.match(node.id))


class _RunnerModule:
    """One runner module, parsed and indexed for the only question ENFORCED
    can honestly mean: does the exit status of the process that runs this gate
    reach a decision?

    Deliberately conservative everywhere. `gate_wiring` turns anything it
    cannot prove into UNPROVEN rather than into ENFORCED.
    """

    def __init__(self, text: str, name: str = "<runner>") -> None:
        self.name = name
        self.tree = ast.parse(text)
        self.parent: Dict[int, ast.AST] = {}
        self.func_of: Dict[int, Optional[ast.AST]] = {}
        self.module_funcs: Dict[str, ast.AST] = {}
        #: ids of nodes inside an if/while/ternary/assert test or a
        #: comprehension filter — reaching one of these IS influencing control
        #: flow.
        self.test_ids: Set[int] = set()
        #: ids of nodes inside a return/raise/`sys.exit(...)` — the value
        #: leaves the frame, so the decision belongs to a caller or to the
        #: interpreter.
        self.escape_ids: Set[int] = set()
        self.loads: Dict[Tuple[int, str], List[ast.Name]] = {}
        self.stores: Dict[Tuple[int, str], List[int]] = {}
        #: every string constant naming a `.py` file, for gate lookup
        self.py_consts: List[ast.Constant] = []
        #: name-flow carriers, collected once — these modules are tens of
        #: thousands of lines and the flow analysis revisits them per gate.
        self.binders: List[ast.AST] = []
        self.calls: List[ast.Call] = []
        self._build()
        #: name -> status tuple index (None = the return value IS the status)
        self.wrappers: Dict[str, Optional[int]] = self._status_wrappers()
        #: (call, kind, status_index, site_verdict, arg_names, arg_node_ids)
        self.launches: List[tuple] = self._launch_sites()
        self._func_blocks: Dict[int, bool] = {}
        self._wiring_cache: Dict[str, str] = {}

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        stack: List[tuple] = [(self.tree, None)]
        while stack:
            node, fn = stack.pop()
            self.func_of[id(node)] = fn
            for ch in ast.iter_child_nodes(node):
                self.parent[id(ch)] = node
                nf = ch if isinstance(
                    ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                stack.append((ch, nf))
        for f in self.tree.body:
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.module_funcs.setdefault(f.name, f)
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
                _mark(node.test, self.test_ids)
            elif isinstance(node, ast.comprehension):
                self.binders.append(node)
                for t in node.ifs:
                    _mark(t, self.test_ids)
            elif isinstance(node, ast.Return) and node.value is not None:
                _mark(node.value, self.escape_ids)
            elif isinstance(node, ast.Raise):
                _mark(node, self.escape_ids)
            elif isinstance(node, ast.Call):
                self.calls.append(node)
                # `sys.exit(rc)` / `exit(rc)` — the status decides the process
                # exit, which is as load-bearing as an `if` gets.
                f = node.func
                if ((isinstance(f, ast.Attribute) and f.attr == "exit")
                        or (isinstance(f, ast.Name)
                            and f.id in ("exit", "SystemExit"))):
                    for a in node.args:
                        _mark(a, self.escape_ids)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension,
                                   ast.Assign)):
                self.binders.append(node)
            elif isinstance(node, ast.Name):
                key = (self._scope(node), node.id)
                if isinstance(node.ctx, ast.Load):
                    self.loads.setdefault(key, []).append(node)
                else:
                    self.stores.setdefault(key, []).append(node.lineno)
            elif (isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and ".py" in node.value):
                self.py_consts.append(node)

    def _scope(self, node: ast.AST) -> int:
        f = self.func_of.get(id(node))
        return id(f) if f is not None else _MODULE_SCOPE

    def _status_wrappers(self) -> Dict[str, Optional[int]]:
        """Module functions that spawn a process and RETURN its exit status.

        `_run(cmd) -> (rc, out, err)` is the runners' house helper. A wrapper
        has DELEGATED the decision to its caller, so enforcement must be judged
        at the call site — which is exactly where `rtl_hygiene_lint`'s status
        is dropped. Treating the wrapper's own `return cp.returncode` as
        consumption would re-manufacture the false positive #884 is about.
        """
        out: Dict[str, Optional[int]] = {}
        for name, fn in self.module_funcs.items():
            if not any(self._spawn_kind(c) for c in ast.walk(fn)
                       if isinstance(c, ast.Call)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                v = node.value
                if isinstance(v, ast.Tuple):
                    idx = next((i for i, e in enumerate(v.elts)
                                if _is_status_expr(e)), None)
                    if idx is not None:
                        out[name] = idx
                        break
                elif _is_status_expr(v):
                    out[name] = None
                    break
        return out

    @staticmethod
    def _spawn_kind(call: ast.Call) -> Optional[str]:
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in _SPAWN_ATTRS:
            base = f.value
            if isinstance(base, ast.Name) and base.id == "subprocess":
                return f.attr
        if isinstance(f, ast.Name) and f.id in ("check_call", "check_output"):
            return f.id
        return None

    def _launch_sites(self) -> List[tuple]:
        sites = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            kind = self._spawn_kind(node)
            idx: Optional[int] = None
            if kind is None:
                f = node.func
                if isinstance(f, ast.Name) and f.id in self.wrappers:
                    kind, idx = "wrapper", self.wrappers[f.id]
            if kind is None:
                continue
            names: Set[str] = set()
            ids: Set[int] = set()
            for a in list(node.args) + [k.value for k in node.keywords]:
                for n in ast.walk(a):
                    ids.add(id(n))
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                        names.add(n.id)
            sites.append((node, kind, idx,
                          self._consumed(node, kind, idx), names, ids))
        return sites

    # -- "does the exit status reach a decision?" --------------------------
    def _consumed(self, call: ast.Call, kind: str,
                  idx: Optional[int]) -> str:
        """One of _BLOCKS / _IGNORED / _UNPROVEN for this launch site.

        The three are kept apart because they are DIFFERENT repairs, and
        collapsing them would repeat #884's own mistake in the other
        direction. `_IGNORED` is a claim — "the status is provably never
        read" — and is only returned when the status has no reader at all.
        A status that is read but whose influence cannot be traced within the
        hop budget is `_UNPROVEN`: not enforcement, and not an accusation.
        """
        if kind in _RAISING_ATTRS or (kind == "run"
                                      and self._check_true(call)):
            # A non-zero exit raises here. That IS control flow — unless an
            # enclosing handler swallows it, which is the `bsdl_emit` shape.
            return _IGNORED if self._swallowed(call) else _BLOCKS
        if id(call) in self.test_ids or id(call) in self.escape_ids:
            return _BLOCKS
        scope, line = self._scope(call), call.lineno
        skip = self._handler_ranges(call)
        p = self.parent.get(id(call))
        if isinstance(p, ast.Attribute) and p.attr in _STATUS_ATTRS:
            return _BLOCKS if self._reaches([p], scope, skip) else _UNPROVEN
        if isinstance(p, ast.Assign) and len(p.targets) == 1:
            t = p.targets[0]
            if isinstance(t, ast.Name):
                readers = (self._loads(scope, t.id, line, skip)
                           if kind == "wrapper"
                           else self._attr_loads(scope, t.id, line, skip))
                return self._verdict(readers, scope, skip)
            if isinstance(t, ast.Tuple) and kind == "wrapper" and idx is not None:
                if idx < len(t.elts) and isinstance(t.elts[idx], ast.Name):
                    nm = t.elts[idx].id
                    if nm == "_":
                        return _IGNORED       # explicitly thrown away
                    return self._verdict(
                        self._loads(scope, nm, line, skip), scope, skip)
        if isinstance(p, ast.Expr):
            # `subprocess.run(...)` as a bare statement: the status is not even
            # bound. Nothing can read it. This is the dfm/bsdl shape.
            return _IGNORED
        return _UNPROVEN

    def _verdict(self, readers: Sequence[ast.AST], scope: int,
                 skip: Sequence[Tuple[int, int]]) -> str:
        if not readers:
            return _IGNORED
        return _BLOCKS if self._reaches(readers, scope, skip) else _UNPROVEN

    def _handler_ranges(self, call: ast.AST) -> List[Tuple[int, int]]:
        """Line spans of the `except` handlers guarding this call.

        A store inside one is a FALLBACK binding, not a rebinding that ends the
        first one's life: `snc = subprocess.run(...)` / `except: snc = None` /
        `if snc is not None and snc.returncode != 0:` is enforcement, and
        treating the handler's assignment as a rebind would hide it.
        """
        out: List[Tuple[int, int]] = []
        cur: Optional[ast.AST] = call
        while cur is not None:
            par = self.parent.get(id(cur))
            if isinstance(par, ast.Try) and cur in par.body:
                for h in par.handlers:
                    out.append((h.lineno, h.end_lineno or h.lineno))
            cur = par
        return out

    @staticmethod
    def _check_true(call: ast.Call) -> bool:
        for k in call.keywords:
            if k.arg == "check":
                return bool(isinstance(k.value, ast.Constant)
                            and k.value.value is True)
        return False

    def _swallowed(self, node: ast.AST) -> bool:
        """Is `node` inside a `try` whose handler does not re-raise?

        Then the exception a raising call would produce cannot stop anything,
        so the status does not influence control flow after all.
        """
        cur: Optional[ast.AST] = node
        while cur is not None:
            par = self.parent.get(id(cur))
            if isinstance(par, ast.Try) and cur in par.body:
                for h in par.handlers:
                    if not any(isinstance(n, ast.Raise)
                               for n in ast.walk(h)):
                        return True
            cur = par
        return False

    @staticmethod
    def _in_ranges(line: int, ranges: Sequence[Tuple[int, int]]) -> bool:
        return any(lo <= line <= hi for lo, hi in ranges)

    def _next_store(self, scope: int, name: str, after: int,
                    skip: Sequence[Tuple[int, int]]) -> int:
        later = [ln for ln in self.stores.get((scope, name), ())
                 if ln > after and not self._in_ranges(ln, skip)]
        return min(later) if later else sys.maxsize

    def _loads(self, scope: int, name: str, after: int,
               skip: Sequence[Tuple[int, int]] = ()) -> List[ast.Name]:
        """Loads of `name` in `scope` between its binding and any rebinding.

        The window matters: `bsdl_emit`'s runner reads `r.returncode` from a
        DIFFERENT `r` (bound eleven lines earlier for the ATPG run). A
        scope-wide search would call that consumption — which is exactly the
        proximity-as-evidence mistake #884 is about, so the fix must not
        commit it while diagnosing it.
        """
        stop = self._next_store(scope, name, after, skip)
        return [n for n in self.loads.get((scope, name), ())
                if after < n.lineno < stop]

    def _attr_loads(self, scope: int, name: str, after: int,
                    skip: Sequence[Tuple[int, int]] = ()) -> List[ast.AST]:
        out = []
        for n in self._loads(scope, name, after, skip):
            p = self.parent.get(id(n))
            if isinstance(p, ast.Attribute) and p.attr in _STATUS_ATTRS:
                out.append(p)
        return out

    def _enclosing_assign(self, node: ast.AST) -> Optional[ast.Assign]:
        cur: Optional[ast.AST] = node
        while cur is not None:
            par = self.parent.get(id(cur))
            if isinstance(par, ast.Assign) and cur is par.value:
                return par
            if isinstance(par, (ast.stmt,)) and not isinstance(par, ast.Assign):
                return None
            cur = par
        return None

    def _reaches(self, nodes: Sequence[ast.AST], scope: int,
                 skip: Sequence[Tuple[int, int]] = ()) -> bool:
        """Does any of these status expressions influence control flow?

        Follows renames (`ok = rc == 0` ... `if not ok:`) for a bounded number
        of hops, then gives up and answers no.
        """
        frontier, seen = list(nodes), set()
        for _ in range(_MAX_TAINT_HOPS):
            nxt: List[ast.AST] = []
            for n in frontier:
                if id(n) in seen:
                    continue
                seen.add(id(n))
                if id(n) in self.test_ids or id(n) in self.escape_ids:
                    return True
                # `cp.check_returncode()` as a bare statement raises on a
                # non-zero exit. Nothing needs to READ the status for it to
                # stop the step, so requiring an `if` here would under-report.
                if (isinstance(n, ast.Attribute)
                        and n.attr == "check_returncode"
                        and isinstance(self.parent.get(id(n)), ast.Call)
                        and not self._swallowed(n)):
                    return True
                a = self._enclosing_assign(n)
                if a is not None:
                    for t in a.targets:
                        for nm in _stored_names(t):
                            nxt.extend(self._loads(scope, nm, a.lineno, skip))
            if not nxt:
                return False
            frontier = nxt
        return False

    # -- "which process runs this gate?" -----------------------------------
    def _taint(self, const: ast.Constant) -> Set[Tuple[int, str]]:
        """(scope, name) pairs that can carry this gate filename onward.

        Covers the two shapes the runners use: a local
        (`fixer = PROGRAMS_DIR / "g.py"`) and a module-level dispatch table
        iterated into a helper (`for g in _TABLE: _run_gate(*g)`).
        """
        taint: Set[Tuple[int, str]] = set()
        seed = self._enclosing_assign(const)
        if seed is not None:
            sc = self._scope(seed)
            for t in seed.targets:
                for nm in _stored_names(t):
                    taint.add((sc, nm))
        for _ in range(_MAX_NAME_HOPS):
            grew = False
            for node in self.binders:
                if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                    it = node.iter
                    sc = self._scope(it)
                    if not self._mentions(it, taint, sc):
                        continue
                    tsc = self._scope(node.target)
                    for nm in _stored_names(node.target):
                        if (tsc, nm) not in taint:
                            taint.add((tsc, nm))
                            grew = True
                elif isinstance(node, ast.Assign):
                    sc = self._scope(node)
                    if not self._mentions(node.value, taint, sc):
                        continue
                    for t in node.targets:
                        for nm in _stored_names(t):
                            if (sc, nm) not in taint:
                                taint.add((sc, nm))
                                grew = True
            if not grew:
                break
        return taint

    def _mentions(self, expr: ast.AST, taint: Set[Tuple[int, str]],
                  scope: int) -> bool:
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if (scope, n.id) in taint or (_MODULE_SCOPE, n.id) in taint:
                    return True
        return False

    def _func_can_block(self, fn: ast.AST) -> bool:
        """Does this function contain a launch site that consumes its status?

        Used for ONE hop of dispatch: a gate named in a table handed to a
        helper is enforced if the helper blocks on what it spawns. That is how
        the step-23/25 sign-off gates are genuinely wired.
        """
        key = id(fn)
        if key not in self._func_blocks:
            lo, hi = fn.lineno, (fn.end_lineno or fn.lineno)
            self._func_blocks[key] = any(
                site == _BLOCKS and lo <= call.lineno <= hi
                for call, _k, _i, site, _n, _d in self.launches)
        return self._func_blocks[key]

    def gate_wiring(self, stem: str) -> str:
        if stem in self._wiring_cache:
            return self._wiring_cache[stem]
        self._wiring_cache[stem] = w = self._gate_wiring(stem)
        return w

    def _gate_wiring(self, stem: str) -> str:
        pat = re.compile(r"\b" + re.escape(stem) + r"\.py\b")
        mentions = [c for c in self.py_consts if pat.search(c.value)]
        if not mentions:
            return NOT_INVOKED
        best = NOT_INVOKED
        for m in mentions:
            best = max(best, self._wiring_for(m), key=_WIRING_ORDER.index)
            if best == INLINE_BLOCKING:
                break
        return best

    def _wiring_for(self, const: ast.Constant) -> str:
        taint = self._taint(const)
        best_site: Optional[str] = None
        for call, _k, _i, site, names, ids in self.launches:
            if id(const) not in ids and not (
                    names & {n for (s, n) in taint
                             if s in (_MODULE_SCOPE, self._scope(call))}):
                continue
            if site == _BLOCKS:
                return INLINE_BLOCKING
            best_site = (site if best_site is None else
                         max(best_site, site, key=_SITE_ORDER.index))
        if best_site is not None:
            return _SITE_TO_WIRING[best_site]
        # One dispatch hop: the name is handed to a module function that
        # spawns and blocks. Wrappers are excluded — they RETURN the status,
        # so the decision is the caller's and was judged above.
        for node in self.calls:
            f = node.func
            if not isinstance(f, ast.Name) or f.id in self.wrappers:
                continue
            fn = self.module_funcs.get(f.id)
            if fn is None:
                continue
            sc = self._scope(node)
            args = list(node.args) + [k.value for k in node.keywords]
            if not any(self._mentions(a, taint, sc) for a in args):
                continue
            if self._func_can_block(fn):
                return INLINE_BLOCKING
        return INLINE_UNPROVEN


#: Parsing the six runners costs seconds — they are tens of thousands of lines
#: — and callers (this program's own tests among them) audit repeatedly. Keyed
#: on the file's identity AND its mtime/size so a mutated copy is never served
#: from a stale entry: a mutation control that silently re-read the pristine
#: tree would prove nothing, which is this campaign's own failure mode.
_MODULE_CACHE: Dict[tuple, Optional["_RunnerModule"]] = {}


def runner_modules(programs: Path) -> List[_RunnerModule]:
    """Every runner present, parsed. A runner that will not parse is SKIPPED
    rather than assumed enforcing — the audit reports less, never more."""
    mods = []
    for r in _RUNNERS:
        p = programs / r
        if not p.is_file():
            continue
        try:
            st = p.stat()
            key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
        except OSError:
            continue
        if key not in _MODULE_CACHE:
            try:
                _MODULE_CACHE[key] = _RunnerModule(
                    p.read_text(errors="replace"), r)
            except (SyntaxError, ValueError, RecursionError, OSError):
                _MODULE_CACHE[key] = None
        mod = _MODULE_CACHE[key]
        if mod is not None:
            mods.append(mod)
    return mods


def gate_wiring(mods: Sequence[_RunnerModule], gate: str) -> str:
    """The strongest wiring this gate has across all runners."""
    stem = gate[:-3] if gate.endswith(".py") else gate
    best = NOT_INVOKED
    for m in mods:
        best = max(best, m.gate_wiring(stem), key=_WIRING_ORDER.index)
        if best == INLINE_BLOCKING:
            break
    return best


def declared_intent(programs: Path, gate: str) -> Optional[str]:
    stem = gate if gate.endswith(".py") else gate + ".py"
    p = programs / stem
    if not p.is_file():
        return None
    text = p.read_text(errors="replace")
    m = _DECL_RE.search(text[:4000])
    if m:
        return m.group(1).lower()
    # SECOND DECLARATION CHANNEL, measured 2026-07-26. Some gates state their
    # intent in the JSON they EMIT (`"verdict_mode": "BLOCKS" / "ADVISES"`)
    # rather than in an `ENFORCEMENT:` docstring line. This audit read only
    # the docstring, so it reported those gates as UNDECLARED and a wiring
    # decision could be made without ever seeing what they said about
    # themselves.
    #
    # A CONDITIONAL mode is deliberately NOT read as a declaration:
    # `"BLOCKS" if strict else "ADVISES"` says the intent depends on a flag,
    # so claiming either would be inventing a declaration the program did not
    # make. Those stay UNDECLARED, which is the truth.
    modes = set()
    for rhs in _VERDICT_MODE_RE.findall(text):
        m2 = _LONE_MODE_RE.match(rhs.strip())
        if not m2:
            # A conditional / computed value (`"BLOCKS" if strict else
            # "ADVISES"`) is NOT a declaration. The first version of this
            # guard failed on exactly the case it was written for: matching
            # only the string VALUE after the key saw `"BLOCKS"` and nothing
            # else, so a gate whose default mode is ADVISES was reported as
            # declaring blocking. Capture the whole RHS and require it to be
            # a lone literal.
            return None
        modes.add(m2.group(1))
    if len(modes) == 1:
        return {"BLOCKS": "blocking", "ADVISES": "advisory"}[modes.pop()]
    return None


def audit(flow: Path, programs: Path) -> dict:
    gates = gates_in_flow(flow)
    src = runner_source(programs)
    mods = runner_modules(programs)
    rows = []
    for g in gates:
        # `_invoked` is a cheap pre-filter: a gate no runner NAMES cannot be
        # wired under any control flow, and skipping the parse for it costs
        # nothing. It is never allowed to conclude ENFORCED on its own — #884.
        wiring = gate_wiring(mods, g) if _invoked(src, g) else NOT_INVOKED
        rows.append({
            "gate": g,
            "enforcement": ("ENFORCED" if wiring == BLOCKING_WIRING
                            else "AUDIT_ONLY"),
            "wiring": wiring,
            "declared": declared_intent(programs, g),
        })
    # ORPHANED: a gate program that DECLARES an enforcement intent but is not
    # referenced by the flow definition at all. Worse than AUDIT_ONLY — not
    # even the final compliance audit reaches it, so it runs only if someone
    # invokes it by hand. Found this way: two gates added earlier in this
    # campaign were never wired into the flow, so they could not fire at all.
    in_flow = {r["gate"] for r in rows}
    orphaned = []
    for f in sorted(programs.glob("*_check.py")) + sorted(programs.glob("*_disclosure.py")):
        stem = f.stem
        if stem in in_flow or f"{stem}.py" in in_flow:
            continue
        intent = declared_intent(programs, stem)
        if intent:
            orphaned.append({"gate": stem, "declared": intent,
                             "enforcement": "ORPHANED"})
    contradictions = [r for r in rows
                      if r["declared"] == "blocking"
                      and r["enforcement"] == "AUDIT_ONLY"]
    return {
        "total_gates": len(rows),
        "enforced": sum(1 for r in rows if r["enforcement"] == "ENFORCED"),
        "audit_only": sum(1 for r in rows if r["enforcement"] == "AUDIT_ONLY"),
        # #884 — the breakdown BEHIND `audit_only`. `status_ignored` is the
        # class this audit used to score as ENFORCED: a real gate really is
        # spawned, and its verdict is thrown away.
        "wiring": {w: sum(1 for r in rows if r["wiring"] == w)
                   for w in _WIRING_ORDER},
        "status_ignored": sum(1 for r in rows
                              if r["wiring"] == INLINE_STATUS_IGNORED),
        "declared": sum(1 for r in rows if r["declared"]),
        "undeclared": sum(1 for r in rows if not r["declared"]),
        "contradictions": contradictions,
        "orphaned": orphaned,
        "gates": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit which flow gates can actually stop a run.")
    ap.add_argument("--flow", help="flow definition YAML")
    ap.add_argument("--programs", help="programs dir (default: this one)")
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--baseline", help="known-debt file; NEW contradictions "
                    "and NEW orphans fail, the recorded ones do not")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT set; it may only ever shrink")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the audit now LOOKS at more than it did (>=30 chars; "
                         "recorded in the baseline beside the previous size)")
    a = ap.parse_args(argv)
    flow = _flow_def(a.flow)
    programs = Path(a.programs) if a.programs else _HERE
    if not flow.is_file():
        print(f"IO_ERROR: no flow definition at {flow}", file=sys.stderr)
        return 2
    rep = audit(flow, programs)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    pct = 100 * rep["audit_only"] // max(1, rep["total_gates"])
    print("=== flow gate enforcement audit ===")
    print(f"gates in flow definition : {rep['total_gates']}")
    print(f"  ENFORCED (can block)   : {rep['enforced']}")
    print(f"  AUDIT_ONLY (describes) : {rep['audit_only']}  ({pct}%)")
    print(f"declared intent          : {rep['declared']} "
          f"({rep['undeclared']} UNDECLARED)")
    # #884 — name the gates the runner really does spawn and then ignores.
    # Folded into AUDIT_ONLY above because they cannot block either, but they
    # are a different repair: the wiring exists, only the verdict is dropped.
    ignored = [r["gate"] for r in rep["gates"]
               if r.get("wiring") == INLINE_STATUS_IGNORED]
    if ignored:
        print(f"\nSTATUS_IGNORED — a runner SPAWNS these and discards the exit\n"
              f"status, so they cost a real gate's runtime and block nothing:")
        for g in ignored:
            print(f"  {g}")
    if rep.get("orphaned"):
        print("\nORPHANED — declare an intent but are NOT in the flow definition,\n"
              "so not even the final audit reaches them:")
        for o in rep["orphaned"]:
            print(f"  {o['gate']}  (declared {o['declared']})")
    # A gate that DECLARES blocking and is wired audit-only, or that declares
    # an intent and is not in the flow at all, is the very defect this audit
    # names — measured in a gate's own terms. Four such gates exist today, two
    # of them added during this campaign: declaring an intent is not wiring
    # it. Fixing them changes what a real run BLOCKS on, which is the flow
    # owner's decision, not this audit's. So the four are recorded as DEBT and
    # this audit blocks anything NEW — the class stops growing without the
    # audit quietly deciding enforcement policy on its own.
    now = sorted([f"contradiction::{c['gate']}" for c in rep["contradictions"]]
                 + [f"orphan::{o['gate']}" for o in (rep.get("orphaned") or [])])
    bl_path = Path(a.baseline) if a.baseline else (
        _HERE / "flow_gate_enforcement_baseline.json")
    prev = None
    if bl_path.is_file():
        try:
            prev = sorted(str(x) for x in
                          (json.loads(bl_path.read_text()).get("known") or []))
        except (OSError, ValueError):
            prev = None
    if a.write_baseline:
        if a.scope_expanded is not None and len(a.scope_expanded.strip()) < 30:
            print("\n[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the audit now looks at that it did not before.")
            return 1
        if (prev is not None and len(now) > len(prev)
                and a.scope_expanded is None):
            print(f"\n[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}): this register records debt "
                  f"that must be paid down, never permission to add more. If "
                  f"the audit now LOOKS at more than it did, say so with "
                  f"--scope-expanded '<why>' — a wider scope finding "
                  f"pre-existing debt is not a regression, but it must be "
                  f"recorded, not assumed.")
            return 1
        bl_path.write_text(json.dumps(
            {"_comment": ("Gates that declare an intent they are not wired "
                          "for (vibe-ic#306/#316). MAY ONLY SHRINK. Fixing "
                          "one changes what a real run blocks on — a flow-"
                          "owner decision — so they are recorded, not "
                          "silently enforced here."),
             "previous_size": None if prev is None else len(prev),
             "scope_expanded": a.scope_expanded,
             "known": now}, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {bl_path} ({len(now)} entr(ies))")
        return 0
    if prev is None:
        return 1 if now else 0
    new = [k for k in now if k not in set(prev)]
    paid = [k for k in prev if k not in set(now)]
    if paid:
        print(f"\n[FAIL] {len(paid)} recorded entr(ies) no longer contradict "
              f"— the debt was paid; shrink the baseline so it cannot become "
              f"standing permission:")
        for k in paid:
            print(f"   (resolved) {k}")
    if new:
        print(f"\n[FAIL] {len(new)} NEW gate(s) declare an intent they are "
              f"not wired for:")
        for k in new:
            print(f"   {k}")
    if new or paid:
        return 1
    print(f"\n[PASS] no NEW enforcement contradiction "
          f"({len(now)} recorded as debt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
