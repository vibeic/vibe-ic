"""DIMENSION 1 (wiring) of the 63x8 matrix — is the gate actually WIRED IN?

One parametrized cell per flow step (63). The question is NOT "does the yaml
say something that looks like a gate"; it is **would anything real parse and
execute that gate at run time**.

====================================================================
THE THREE CHANNELS, AND HOW EACH IS MEASURED *LIVE*
====================================================================
A step's gate is reachable if at least one of these holds. Nothing here reads
`.audit_63x8.json`; `cells_for(1)` is used only to enumerate which cells exist.

(a) **flow yaml gate clause** — measured by RUNNING THE REAL EXECUTOR.
    `flow_compliance_check._evaluate_gate` is the function that actually walks
    a step's `gate:` at run time. This module builds a throwaway project that
    satisfies exactly the file preconditions the gate itself declares
    (`files_exist` paths, `condition_files_exist` paths, the `json_field_true`
    document), instruments the three leaf checkers the executor calls
    (`_check_program_exit_zero`, `_check_files_exist`, `_check_json_field_true`)
    and invokes `_evaluate_gate` for real. What comes back is the set of
    programs the executor GENUINELY dispatched — not a re-implementation of the
    walk, and not a text scan.

    That distinction is the whole point of this dimension. A re-implemented
    walker agrees with itself; it cannot notice that the real executor never
    recursed into a clause. Running the real one can.

    Channel (a) holds when the executor dispatched >= 1 resolvable program, or
    (steps 1 and 12, whose gates are legitimately program-free) evaluated >= 1
    native predicate clause.

(b) **P0 umbrella registration** — measured by IMPORTING
    `flow_compliance_check` and reading its dispatch registries. The registries
    are DISCOVERED, not assumed: every module-level container of strings whose
    members all resolve to `programs/<name>.py` counts, plus every program
    subprocessed directly by the module through a `PROGRAMS_DIR / "<name>.py"`
    expression. Today that finds `_STRUCTURAL_RTL_GATES` (241),
    `_THIN_INPUT_WAIVER_GATES`, `_P0_THIN_INPUT_DEFERRABLE_SUBGATES` (both
    subsets) and the two in-process yosys gates. A sibling registry added
    tomorrow is picked up with no edit here.

(c) **runner invocation** — measured by an AST dispatch analysis of every
    `programs/*_one_shot_runner.py`. AST, not grep, because this codebase
    dispatches dynamically and PR #460 shipped a broken change precisely
    because a grep could not see that. Parsing to an AST removes comments
    outright, and module/class/function docstrings are excluded explicitly, so
    a `# e.g. "foo_check"` comment can never be counted as a call site. The
    resolved forms are:
      * `import X` / `from X import ...` where `programs/X.py` exists
      * `__import__("X")` / `importlib.import_module("X")`
      * `__import__(f"{v}_protocol_synth")` — the f-string is turned into an
        anchored regex (`^.*_protocol_synth$`) and EVERY program matching it is
        treated as dispatched, because the name is only knowable at run time.
        An f-string with under 3 characters of literal text is refused rather
        than allowed to match the world.
      * a `"<name>.py"` string constant (this is how `_DECLARED_SIGNOFF_GATES`,
        `_DERIVED_ARTEFACT_GENERATORS` and the DT1/DT2/DT3 producer table name
        their programs; the runner then builds `PROGRAMS_DIR / prog`)
      * `<dir>.glob("*_protocol_synth.py")` — expanded against `programs/`

For the ONE step that declares no `gate:` at all (P0, the structural-RTL
pre-flight umbrella) the three-channel question is malformed: P0 IS the
umbrella. Its cell asserts the umbrella wiring instead, and the identity of the
umbrella step is DERIVED from `flow_compliance_check`'s own source rather than
hard-coded — see `umbrella_step_id()`. A second gate-less step appearing later
does not silently inherit that treatment: it fails and forces a human look.

====================================================================
WHAT THIS FILE DELIBERATELY DOES NOT CLAIM
====================================================================
* It does not claim the gate would PASS or FAIL on a real design. That is
  dimension 2's question. Every leaf program here is stubbed to "exit 0"; only
  the DISPATCH is measured.
* Channel (c) proves a runner *reaches* the program, not that the reaching code
  path executes on any particular project (every runner branches on IC class,
  PDK and artefact presence). A step whose only channel were (c) would
  therefore be weakly covered. As measured today no step is in that position:
  all 62 gated steps hold channel (a), which is the channel that runs the real
  executor, so channel (c) is corroboration here rather than the load-bearing
  leg. The instrument tests at the bottom are what keep the (c) scanner honest.
* It says nothing about whether a gate CAN fail (dimension 2), whether it
  measures what it claims (dimension 4), or whether its outputs appear
  (dimensions 3/7/8).

====================================================================
MUTATION PROOFS (2026-07-27) — every assertion below was reddened
====================================================================
Each mutation was applied to the GUARDED THING, confirmed red, then reverted.

  1. flow yaml, step 21: `drc_report_check` -> `drc_report_check_TYPO`
     -> `test_d1_gate_is_wired_in[step21]` on the unresolved-program assertion.
  2. flow yaml, step 33: second clause folded into the SAME dict as the first
     (`{files_exist: [...], program_exit_zero: power_report_check ...}`), which
     `_evaluate_gate` matches on `files_exist` and returns from
     -> `[step33]` on the unreached assertion, with `gate passed=True`. That is
     the whole dimension in one line: the gate reported PASS while its declared
     checker never ran.
  3. flow yaml, step 12: `gate:` deleted entirely
     -> `[step12]`, because a gate-less step that is not the umbrella step is
     reachable through nothing.
  4. `flow_compliance_check.py`: umbrella `StepResult(id="P0")` -> `"P0_MUT"`
     -> `[stepP0]` and `test_probe_umbrella_step_id_is_a_declared_flow_step`.
  5. `flow_compliance_check.py`: a registry entry with no backing program added
     to `_STRUCTURAL_RTL_GATES`
     -> `[stepP0]` on the orphan assertion.
  6. `phase1_doc_one_shot_runner.py`: the dynamic dispatch refactored into a
     concatenation the resolver cannot fold
     (`f"{n}_protocol_synth"` -> `f"{n}" + "_protocol_synth"`, same for the
     `glob("*_protocol_synth.py")`)
     -> `test_probe_channel_c_resolves_dynamic_fstring_dispatch`, i.e. the
     scanner is not allowed to go quiet and be read as clean.
"""
from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers
from matrix_63x8.cells import DIMENSION_NAMES, cells_for

DIM = 1
assert DIMENSION_NAMES[DIM] == "wiring"

PROGRAMS_DIR: Path = F.PROGRAMS_DIR

#: Runners that count as channel (c). Discovered by glob so a new one-shot
#: runner is covered without editing this list.
RUNNER_GLOB = "*_one_shot_runner.py"

#: Minimum literal characters an f-string must carry before it is allowed to
#: resolve to a set of programs. `f"{x}"` carries none and would otherwise
#: "dispatch" all 1000+ programs — a scanner that matches everything is as
#: useless as one that matches nothing, and far more dangerous.
MIN_FSTRING_LITERAL = 3

#: Shape of a dispatch registry inside the compliance module. See
#: `umbrella_registries` for why the ratio is not 1.0.
MIN_REGISTRY_MEMBERS = 3
REGISTRY_RESOLVE_RATIO = 0.8

#: Floor on how many structural gates the P0 umbrella must REALLY subprocess on
#: a minimal RTL tree. Measured 2026-07-27: 241 of 241 dispatch, 0 class-skip.
#: The floor is a floor, not the measured value, so a legitimate future
#: class-aware skip set does not redden the cell — but a runner that dispatches
#: nothing (the two mutations that used to keep this cell green) does.
MIN_UMBRELLA_DISPATCHES = 100

#: Pseudo-registry name for gate programs the compliance module subprocesses
#: through a bare `PROGRAMS_DIR / "<name>.py"` expression rather than from a
#: container. They ARE dispatched, just not by `_run_structural_rtl_gates`.
DIRECT_DISPATCH_KEY = "<direct dispatch>"

_IMPORT_CALLS = frozenset({"__import__", "import_module"})
_GLOB_CALLS = frozenset({"glob", "rglob", "iglob"})
_GLOB_CHARS = "*?["


# ──────────────────────────────────────────────────────────────────────
# Program inventory (live)
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def all_program_stems() -> frozenset:
    """Every `programs/<stem>.py` on disk, right now."""
    return frozenset(p.stem for p in PROGRAMS_DIR.glob("*.py"))


# ──────────────────────────────────────────────────────────────────────
# Channel (a) — run the REAL gate executor
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GateRun:
    """What the real `_evaluate_gate` did with one step's gate."""

    passed: bool
    reasons: Tuple[str, ...]
    dispatched: Tuple[str, ...]          # program basenames actually invoked
    predicate_calls: Tuple[str, ...]     # native predicate clauses evaluated
    harness_error: Optional[str] = None


def _concretize(pattern: str) -> str:
    """Turn a glob pattern into ONE concrete relative path that matches it.

    Used to build the synthetic project: the gate's own `files_exist` /
    `condition_files_exist` patterns are materialised so that every clause is
    reached instead of the walk short-circuiting on the first absent file.
    `**` collapses to a single directory level (enough to satisfy a recursive
    pattern), `*` -> `x`, `?` -> `y`, `[abc]` -> `a`.
    """
    s = pattern.replace("**/", "g/").replace("**", "g")
    while "[" in s and "]" in s and s.index("[") < s.index("]", s.index("[")):
        a = s.index("[")
        b = s.index("]", a)
        inner = s[a + 1: b]
        s = s[:a] + (inner[0] if inner else "a") + s[b + 1:]
    return s.replace("*", "x").replace("?", "y")


def _materialize(project: Path, gate: Any) -> None:
    """Create every file the gate's own clauses look for.

    Deliberately driven by the gate spec, never by a fixed list: whatever the
    yaml declares as a precondition is what gets created, so a step that grows
    a new `condition_files_exist` entry is still fully dispatched.
    """

    def touch(pattern: str) -> None:
        rel = _concretize(str(pattern)).strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            return
        target = project / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text("{}\n", encoding="utf-8")
        except OSError:
            pass

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        files = node.get(F.K_FILES)
        if isinstance(files, list):
            for pat in files:
                for alt in F.split_any_of(str(pat)):
                    touch(alt)
        for kind in F.EXEC_CLAUSE_KINDS:
            spec = node.get(kind)
            if isinstance(spec, dict):
                cond = spec.get("condition_files_exist")
                if isinstance(cond, list):
                    for pat in cond:
                        touch(str(pat))
        jf = node.get(F.K_JSON_FIELD)
        if isinstance(jf, dict) and jf.get("file") and jf.get("field"):
            doc = project / _concretize(str(jf["file"]))
            expect = jf.get("expect", True)
            if isinstance(expect, str):
                expect = {"true": True, "false": False}.get(expect.lower(), expect)
            if expect is None:
                expect = True
            try:
                doc.parent.mkdir(parents=True, exist_ok=True)
                doc.write_text(
                    json.dumps({str(jf["field"]): expect}), encoding="utf-8"
                )
            except OSError:
                pass
        for key in ("all_of", "any_of"):
            sub = node.get(key)
            if isinstance(sub, (list, dict)):
                walk(sub)

    walk(gate)


@lru_cache(maxsize=1)
def compliance_module():
    """The module the flow's own `final_gate` names, imported live.

    Resolved through the yaml rather than hard-coded, so re-pointing
    `final_gate.program` at something else is a change this file notices.
    """
    fg = F.load_flow().get("final_gate") or {}
    name = str(fg.get("program") or "").strip()
    if not name or F.program_path(name) is None:
        raise RuntimeError(
            f"flow final_gate.program={name!r} does not resolve to "
            f"{PROGRAMS_DIR}/{name}.py"
        )
    if str(PROGRAMS_DIR) not in sys.path:
        sys.path.insert(0, str(PROGRAMS_DIR))
    return importlib.import_module(name)


@lru_cache(maxsize=None)
def live_gate_run(step_id) -> Optional[GateRun]:
    """Run the REAL gate executor over *step_id*'s gate and report dispatch.

    Returns ``None`` when the step declares no gate at all.

    The three leaf checkers are swapped for recorders. Only
    `_check_program_exit_zero` is fully replaced (running 137 real gate
    programs would measure dimension 2, not dimension 1); the two predicate
    checkers DELEGATE to the originals so their verdicts stay real and a gate
    whose preconditions the harness failed to build still reports honestly.
    """
    gate = F.gate(step_id)
    if gate is None:
        return None

    mod = compliance_module()
    dispatched: List[str] = []
    predicate_calls: List[str] = []
    project = Path(tempfile.mkdtemp(prefix=f"d1_{F.normalize_id(step_id)}_"))

    orig_prog = mod._check_program_exit_zero
    orig_files = mod._check_files_exist
    orig_json = mod._check_json_field_true
    try:
        _materialize(project, gate)

        def rec_program(proj, cmd):
            tokens = str(cmd).split()
            if tokens:
                dispatched.append(tokens[0])
            return True, ""

        def rec_files(proj, patterns, any_of):
            predicate_calls.append(f"{F.K_FILES}:{list(patterns)}")
            return orig_files(proj, patterns, any_of)

        def rec_json(proj, spec):
            predicate_calls.append(f"{F.K_JSON_FIELD}:{spec}")
            return orig_json(proj, spec)

        mod._check_program_exit_zero = rec_program
        mod._check_files_exist = rec_files
        mod._check_json_field_true = rec_json
        try:
            passed, reasons = mod._evaluate_gate(project, gate, skip_analog=False)
            harness_error = None
        except Exception as exc:  # noqa: BLE001 — a crash IS a wiring finding
            passed, reasons = False, []
            harness_error = f"{type(exc).__name__}: {exc}"
    finally:
        mod._check_program_exit_zero = orig_prog
        mod._check_files_exist = orig_files
        mod._check_json_field_true = orig_json
        shutil.rmtree(project, ignore_errors=True)

    deduped: List[str] = []
    for name in dispatched:
        if name not in deduped:
            deduped.append(name)
    return GateRun(
        passed=bool(passed),
        reasons=tuple(str(r) for r in reasons),
        dispatched=tuple(deduped),
        predicate_calls=tuple(predicate_calls),
        harness_error=harness_error,
    )


# ──────────────────────────────────────────────────────────────────────
# Channel (b) — the umbrella's own dispatch registries, discovered live
# ──────────────────────────────────────────────────────────────────────
def _string_members(node: ast.AST) -> List[str]:
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    if isinstance(node, ast.Dict):
        return [
            k.value
            for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
    return []


@lru_cache(maxsize=1)
def umbrella_registries() -> Dict[str, Tuple[str, ...]]:
    """`{registry name: gate program names}` found in the compliance module.

    DISCOVERY RULE, not a hard-coded name: a module-level container literal of
    at least `MIN_REGISTRY_MEMBERS` strings, at least `REGISTRY_RESOLVE_RATIO`
    of which resolve to `programs/<member>.py`. That is what a dispatch
    registry looks like structurally, and it is why a sibling registry added
    later is picked up without editing this file.

    The ratio is deliberately NOT 100%. Requiring every member to resolve
    would mean one orphaned entry makes the whole registry INVISIBLE to this
    file — the umbrella would quietly stop being a channel at the exact moment
    it developed a hole. Admitting the registry and then failing on the orphan
    (see the umbrella branch of the cell test) reports the hole instead of
    hiding it.

    The two programs the module subprocesses directly through a
    `PROGRAMS_DIR / "<name>.py"` expression are reported under the pseudo-name
    `<direct dispatch>`: they are dispatched by the umbrella just as surely as
    a registry entry, they simply have no container to live in.
    """
    mod = compliance_module()
    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=mod.__file__)
    stems = all_program_stems()
    out: Dict[str, Tuple[str, ...]] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        members = _string_members(value)
        resolved = [m for m in members if m in stems]
        if (
            len(members) < MIN_REGISTRY_MEMBERS
            or not resolved
            or len(resolved) < REGISTRY_RESOLVE_RATIO * len(members)
        ):
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                # Read the LIVE object, not the literal: a registry the module
                # post-processes at import time must be measured after that.
                live = getattr(mod, tgt.id, None)
                if isinstance(live, (tuple, list, set, frozenset, dict)):
                    members = [m for m in live if isinstance(m, str)]
                out[tgt.id] = tuple(members)

    direct: List[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
            and node.right.value.endswith(".py")
        ):
            stem = node.right.value[:-3]
            if stem in stems and stem not in direct:
                direct.append(stem)
    if direct:
        out[DIRECT_DISPATCH_KEY] = tuple(direct)
    return out


@lru_cache(maxsize=1)
def umbrella_gate_names() -> frozenset:
    acc: Set[str] = set()
    for members in umbrella_registries().values():
        acc.update(members)
    return frozenset(acc)


@lru_cache(maxsize=1)
def umbrella_registry_gate_names() -> frozenset:
    """Registered gates `_run_structural_rtl_gates` itself is responsible for.

    Excludes the :data:`DIRECT_DISPATCH_KEY` pseudo-registry: those two
    programs are subprocessed by a DIFFERENT function in the same module
    (`_run_yosys_gates`), so holding the structural runner responsible for
    dispatching them would be an adjacent measurement. They get their own
    driven probe — see `test_probe_direct_dispatch_programs_really_dispatch`.
    """
    acc: Set[str] = set()
    for name, members in umbrella_registries().items():
        if name == DIRECT_DISPATCH_KEY:
            continue
        acc.update(members)
    return frozenset(acc)


@lru_cache(maxsize=1)
def umbrella_step_id() -> str:
    """The step id the compliance module emits its umbrella verdict under.

    Derived structurally: find the assignment whose value is a call to
    `_run_structural_rtl_gates`, note the names it binds, then find the
    `StepResult(...)` built in the same function that references one of those
    names and read its `id=` keyword. Hard-coding `"P0"` here would make this
    file agree with itself instead of with the module.
    """
    mod = compliance_module()
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    found: Set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound: Set[str] = set()
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_run_structural_rtl_gates"
            ):
                for tgt in node.targets:
                    bound.update(
                        n.id for n in ast.walk(tgt) if isinstance(n, ast.Name)
                    )
        if not bound:
            continue
        for node in ast.walk(fn):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "StepResult"
            ):
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if not (names & bound):
                continue
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                    found.add(str(kw.value.value))
    if len(found) != 1:
        raise RuntimeError(
            f"expected exactly one umbrella StepResult id in "
            f"{mod.__file__}, measured {sorted(found)}"
        )
    return found.pop()


# ──────────────────────────────────────────────────────────────────────
# The umbrella's ACTUAL dispatch, driven for real
#
# 2026-07-27, adversarial finding (FATAL): the P0 branch of the cell test used
# to assert `callable(mod._run_structural_rtl_gates)` and stop there. Two
# independent mutations of `flow_compliance_check.py` — (a) `return True, [],
# [], []` as the runner's first statement, and (b) `return ("pass", gate_name)`
# inserted immediately before the per-gate `argv = [...]` line, so that ZERO of
# the registered gates are ever subprocessed and all of them are reported PASS
# — both left the cell GREEN. `callable()` is satisfied by a function whose
# body does nothing, so the ONE cell that claims the 241-name structural
# umbrella is wired was asserting the umbrella's existence, not its dispatch.
# That is the campaign's own disease inside the campaign's own suite.
#
# The fix is the same instrument channel (a) already uses on the 62 gated
# steps: DRIVE THE REAL FUNCTION and record what it actually invoked. The
# umbrella subprocesses each registered gate as
# `subprocess.run([sys.executable, programs/<name>.py, <project>], cwd=project)`,
# so rebinding the module's `subprocess` attribute to a recorder observes every
# real dispatch and nothing else. Both mutations above make the recorded set
# EMPTY and redden the cell; a mutation that flips a gate's outcome is caught
# by the fail/skip legs below.
# ──────────────────────────────────────────────────────────────────────
#: RTL the umbrella's own directory probe accepts (`phase2/stage1/rtl/*.v`).
_UMBRELLA_RTL_REL = "phase2/stage1/rtl/top.v"
_UMBRELLA_RTL_BODY = "module top(input wire clk);\nendmodule\n"


@dataclass(frozen=True)
class UmbrellaRun:
    """What the REAL `_run_structural_rtl_gates` did on a minimal RTL tree."""

    passed: Optional[bool]
    fails: Tuple[str, ...]
    skips: Tuple[str, ...]
    waivers: Tuple[str, ...]
    #: `programs/<stem>.py` basenames the umbrella genuinely subprocessed.
    dispatched: Tuple[str, ...]
    harness_error: Optional[str] = None


class _SubprocessRecorder:
    """Stands in for the ``subprocess`` module inside the compliance module.

    Records every ``run(argv, ...)`` and answers with a caller-supplied
    returncode. Everything else (``TimeoutExpired`` and friends) is delegated
    to the real module, so the umbrella's own except-clauses still bind to the
    genuine exception types.
    """

    def __init__(self, real, rc_for):
        self._real = real
        self._rc_for = rc_for
        self.calls: List[List[str]] = []
        import threading

        self._lock = threading.Lock()

    def run(self, argv, **_kw):  # noqa: D401 - mimics subprocess.run
        argv = [str(a) for a in argv]
        with self._lock:
            self.calls.append(argv)
        stem = Path(argv[1]).stem if len(argv) > 1 else ""
        rc, out = self._rc_for(stem)

        class _Completed:
            returncode = rc
            stdout = out
            stderr = ""

        return _Completed()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _drive_umbrella(rc_for) -> UmbrellaRun:
    """Run the shipped `_run_structural_rtl_gates` for real, recording dispatch.

    `rc_for(stem) -> (returncode, stdout)` decides each gate's answer, so the
    caller can probe the PASS, FAIL and SKIP legs of the umbrella's own
    classifier without needing 241 real tool runs.
    """
    mod = compliance_module()
    tmp = Path(tempfile.mkdtemp(prefix="matrix_d1_umbrella_"))
    real_sub = getattr(mod, "subprocess")
    recorder = _SubprocessRecorder(real_sub, rc_for)
    try:
        project = tmp / "proj"
        rtl = project / _UMBRELLA_RTL_REL
        rtl.parent.mkdir(parents=True)
        rtl.write_text(_UMBRELLA_RTL_BODY, encoding="utf-8")
        mod.subprocess = recorder
        try:
            passed, fails, skips, waiver_entries = mod._run_structural_rtl_gates(
                project)
        except Exception as exc:  # pragma: no cover - harness failure path
            return UmbrellaRun(None, (), (), (), (), harness_error=repr(exc))
        finally:
            mod.subprocess = real_sub
        assert getattr(mod, "subprocess") is real_sub
        return UmbrellaRun(
            passed=passed,
            fails=tuple(str(f) for f in fails),
            skips=tuple(str(s) for s in skips),
            waivers=tuple(str(w) for w in waiver_entries),
            dispatched=tuple(
                sorted({Path(c[1]).stem for c in recorder.calls if len(c) > 1})),
        )
    finally:
        mod.subprocess = real_sub
        shutil.rmtree(tmp, ignore_errors=True)


@lru_cache(maxsize=1)
def umbrella_dispatch() -> UmbrellaRun:
    """The all-gates-pass leg, memoised (241 recorded dispatches, no real runs)."""
    return _drive_umbrella(lambda stem: (0, ""))


# ──────────────────────────────────────────────────────────────────────
# Channel (c) — AST dispatch analysis of the one-shot runners
# ──────────────────────────────────────────────────────────────────────
@dataclass
class RunnerScan:
    invoked: Set[str] = field(default_factory=set)
    fstring_patterns: List[str] = field(default_factory=list)
    glob_patterns: List[str] = field(default_factory=list)
    unresolvable: List[str] = field(default_factory=list)


def _docstring_constants(tree: ast.AST) -> Set[int]:
    """`id()` of every docstring Constant, so prose can never be a call site."""
    out: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            out.add(id(body[0].value))
    return out


def _fstring_regex(node: ast.JoinedStr) -> Optional[re.Pattern]:
    """Anchored regex for an f-string, or None when it says too little.

    Each `{...}` becomes `[^/\\s]*`. Refusing an f-string with fewer than
    `MIN_FSTRING_LITERAL` literal characters is the guard against
    "resolves to every program in the tree".
    """
    parts: List[str] = []
    literal = 0
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(re.escape(value.value))
            literal += len(value.value.strip(" ./_-"))
        else:
            parts.append(r"[^/\s]*")
    if literal < MIN_FSTRING_LITERAL:
        return None
    return re.compile("^" + "".join(parts) + "$")


def _scan_runner(path: Path) -> RunnerScan:
    """Program basenames *path* can dispatch. AST only — never a text scan."""
    scan = RunnerScan()
    stems = all_program_stems()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_constants(tree)

    def add(name: str) -> None:
        if name in stems:
            scan.invoked.add(name)

    def resolve_fstring(node: ast.JoinedStr, tag: str) -> None:
        rx = _fstring_regex(node)
        if rx is None:
            scan.unresolvable.append(f"{tag} @{path.name}:{node.lineno}")
            return
        scan.fstring_patterns.append(rx.pattern)
        for stem in stems:
            if rx.match(stem) or rx.match(stem + ".py"):
                scan.invoked.add(stem)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name.split(".")[0])
            continue
        if isinstance(node, ast.ImportFrom):
            if not node.level and node.module:
                add(node.module.split(".")[0])
            continue
        if isinstance(node, ast.Call):
            func = node.func
            fname = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if fname in _IMPORT_CALLS and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    add(arg.value.split(".")[0])
                elif isinstance(arg, ast.JoinedStr):
                    resolve_fstring(arg, "dynamic import")
            elif fname in _GLOB_CALLS and node.args:
                arg = node.args[0]
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.endswith(".py")
                    and any(ch in arg.value for ch in _GLOB_CHARS)
                ):
                    scan.glob_patterns.append(arg.value)
                    for hit in PROGRAMS_DIR.glob(arg.value):
                        add(hit.stem)
        if isinstance(node, ast.JoinedStr):
            resolve_fstring(node, "fstring")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            text = node.value.strip()
            if (
                text.endswith(".py")
                and "/" not in text
                and " " not in text
                and not any(ch in text for ch in _GLOB_CHARS)
            ):
                add(text[:-3])
    return scan


@lru_cache(maxsize=1)
def runner_scans() -> Dict[str, RunnerScan]:
    return {
        path.name: _scan_runner(path)
        for path in sorted(PROGRAMS_DIR.glob(RUNNER_GLOB))
    }


@lru_cache(maxsize=1)
def runner_invoked() -> frozenset:
    acc: Set[str] = set()
    for scan in runner_scans().values():
        acc |= scan.invoked
    return frozenset(acc)


def runners_invoking(name: str) -> Tuple[str, ...]:
    return tuple(
        rname for rname, scan in sorted(runner_scans().items()) if name in scan.invoked
    )


# ──────────────────────────────────────────────────────────────────────
# The per-step channel verdict
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Channels:
    a_dispatched: Tuple[str, ...]
    a_predicates: Tuple[str, ...]
    b_registered: Tuple[str, ...]
    c_invoked: Tuple[str, ...]
    declared: Tuple[str, ...]
    unresolved: Tuple[str, ...]
    run: Optional[GateRun]

    @property
    def a(self) -> bool:
        return bool(self.a_dispatched) or bool(self.a_predicates)

    @property
    def b(self) -> bool:
        return bool(self.b_registered)

    @property
    def c(self) -> bool:
        return bool(self.c_invoked)

    @property
    def any(self) -> bool:
        return self.a or self.b or self.c

    def summary(self) -> str:
        c_detail = ", ".join(
            f"{p}<-{'+'.join(runners_invoking(p)) or '?'}" for p in self.c_invoked
        )
        return (
            f"a={'HIT' if self.a else 'miss'}"
            f"(executor dispatched {list(self.a_dispatched)}, evaluated "
            f"{len(self.a_predicates)} native predicate clause(s)) "
            f"b={'HIT' if self.b else 'miss'}"
            f"(umbrella-registered: {list(self.b_registered)}) "
            f"c={'HIT' if self.c else 'miss'}({c_detail or 'none'})"
        )


def channels_for(step_id) -> Channels:
    run = live_gate_run(step_id)
    declared = F.gate_program_tokens(step_id)
    unresolved = F.unresolved_gate_programs(step_id)
    resolvable = F.gate_programs(step_id)
    dispatched = tuple(
        p for p in (run.dispatched if run else ()) if F.program_path(p) is not None
    )
    registry = umbrella_gate_names()
    invoked = runner_invoked()
    return Channels(
        a_dispatched=dispatched,
        a_predicates=(run.predicate_calls if run else ()),
        b_registered=tuple(p for p in resolvable if p in registry),
        c_invoked=tuple(p for p in resolvable if p in invoked),
        declared=declared,
        unresolved=unresolved,
        run=run,
    )


# ──────────────────────────────────────────────────────────────────────
# Parametrization
# ──────────────────────────────────────────────────────────────────────
def _params():
    out = []
    for cell in cells_for(DIM):
        mark = waivers.xfail_mark(cell.step_id, DIM)
        out.append(pytest.param(cell, marks=[mark] if mark else []))
    return out


@pytest.mark.parametrize("cell", _params(), ids=lambda c: f"step{c.step_id}")
def test_d1_gate_is_wired_in(cell):
    """The step's gate must be reachable through >= 1 live channel."""
    sid = cell.step_id
    ch = channels_for(sid)

    # ── The gate-less step: P0, the umbrella itself ───────────────────
    if not F.has_gate(sid):
        # Self-invalidating precondition. A NEW gate-less step must not
        # silently inherit the umbrella's exemption.
        assert F.normalize_id(sid) == umbrella_step_id(), (
            f"step {sid!r} declares no `gate:` but is not the umbrella step "
            f"{umbrella_step_id()!r} that {compliance_module().__name__} emits "
            f"its structural verdict under; it is reachable through no channel "
            f"at all and needs a wiring decision"
        )
        registries = umbrella_registries()
        total = umbrella_gate_names()
        assert total, (
            f"umbrella step {sid}: {compliance_module().__name__} exposes "
            f"registries {sorted(registries)} but they name 0 gate programs — "
            f"the umbrella would certify a verdict over an empty checker set"
        )
        orphans = sorted(g for g in total if F.program_path(g) is None)
        assert not orphans, (
            f"umbrella step {sid}: {len(orphans)} registered gate(s) have no "
            f"backing programs/<name>.py and therefore never dispatch: "
            f"{orphans[:10]}"
        )
        runner = getattr(compliance_module(), "_run_structural_rtl_gates", None)
        assert callable(runner), (
            f"umbrella step {sid}: {compliance_module().__name__}."
            f"_run_structural_rtl_gates is {runner!r}, not callable — nothing "
            f"dispatches the {len(total)} registered gates"
        )

        # `callable()` is satisfied by a function whose body does nothing, so
        # the four assertions above are all declaration-shaped. DRIVE THE REAL
        # UMBRELLA and read back what it genuinely subprocessed.
        run = umbrella_dispatch()
        assert run.harness_error is None, (
            f"umbrella step {sid}: driving the real "
            f"_run_structural_rtl_gates raised: {run.harness_error}"
        )
        assert run.passed is not None, (
            f"umbrella step {sid}: the umbrella reported 'not executed' on a "
            f"tree carrying {_UMBRELLA_RTL_REL} — its own RTL-directory probe "
            f"no longer recognises the flow's canonical RTL location, so the "
            f"{len(total)} registered gates never dispatch. skips={run.skips[:3]}"
        )
        # Every registered gate must either have been REALLY subprocessed or be
        # named in the umbrella's own skip list with a reason. A gate that is
        # neither is one the umbrella counts and never runs.
        skipped_names = {s.split()[0] for s in run.skips if s.split()}
        owned = umbrella_registry_gate_names()
        silent = sorted(
            g for g in owned
            if g not in run.dispatched and g not in skipped_names
        )
        assert not silent, (
            f"umbrella step {sid}: {len(silent)} of the {len(owned)} registered "
            f"structural gates were neither subprocessed by the real "
            f"_run_structural_rtl_gates nor named in its skip list — the "
            f"umbrella certifies a verdict over checkers it never ran: "
            f"{silent[:10]}. Recorded dispatches: {len(run.dispatched)}; "
            f"skips recorded: {len(run.skips)}"
        )
        assert len(run.dispatched) >= MIN_UMBRELLA_DISPATCHES, (
            f"umbrella step {sid}: only {len(run.dispatched)} gate program(s) "
            f"were actually subprocessed on a minimal RTL tree "
            f"(registry names {len(owned)}). Below "
            f"{MIN_UMBRELLA_DISPATCHES} the umbrella is not a dispatcher, and "
            f"an 'all gates passed' verdict from it means nothing"
        )
        return

    # ── Gated steps ───────────────────────────────────────────────────
    assert not ch.unresolved, (
        f"step {sid}: gate names {len(ch.unresolved)} program(s) with no "
        f"matching file under {PROGRAMS_DIR}: {list(ch.unresolved)} "
        f"(declared tokens: {list(ch.declared)}); the clause can never run"
    )

    run = ch.run
    assert run is not None and run.harness_error is None, (
        f"step {sid}: the real gate executor "
        f"{compliance_module().__name__}._evaluate_gate raised on this gate: "
        f"{run.harness_error if run else 'no gate run'}"
    )

    # Every program the yaml declares must be one the REAL executor reached.
    # A declared-but-never-dispatched clause is the exact defect this
    # dimension exists to find: the yaml believes in a checker the walker
    # never gets to.
    unreached = [p for p in ch.declared if p not in run.dispatched]
    assert not unreached, (
        f"step {sid}: the real executor dispatched {list(run.dispatched)} but "
        f"the gate declares {list(ch.declared)}; {unreached} were never "
        f"reached (gate passed={run.passed}, reasons={list(run.reasons)[:3]})"
    )

    assert ch.any, (
        f"step {sid}: reachable through ZERO channels. {ch.summary()}; "
        f"gate declares {list(ch.declared)}, executor dispatched "
        f"{list(run.dispatched)} and evaluated {len(run.predicate_calls)} "
        f"native predicate clause(s); none of those programs is in the "
        f"{len(umbrella_gate_names())}-name umbrella registry or invoked by "
        f"any of the {len(runner_scans())} one-shot runners"
    )


# ──────────────────────────────────────────────────────────────────────
# Instrument self-checks
#
# Not matrix cells. They guard the three measuring devices above against the
# failure mode that produced this campaign: an instrument that quietly returns
# nothing and is read as a clean bill of health.
# ──────────────────────────────────────────────────────────────────────
def test_probe_channel_a_actually_executes_the_real_walker():
    """The channel-(a) probe must run the shipped executor, not a copy."""
    mod = compliance_module()
    assert Path(mod.__file__).resolve().parent == PROGRAMS_DIR.resolve(), (
        f"channel (a) imported {mod.__file__}, which is not in {PROGRAMS_DIR}"
    )
    for attr in (
        "_evaluate_gate",
        "_check_program_exit_zero",
        "_check_files_exist",
        "_check_json_field_true",
    ):
        assert callable(getattr(mod, attr, None)), (
            f"{mod.__name__}.{attr} is missing; the channel-(a) probe would "
            f"silently measure a different execution path"
        )
    # The originals must be restored after every probe.
    live_gate_run(F.step_ids()[0])
    assert mod._check_program_exit_zero.__module__ == mod.__name__, (
        "the channel-(a) probe leaked its recorder into the module"
    )


def test_probe_channel_a_dispatch_is_non_trivial():
    """Across the flow the real executor must dispatch a substantial set.

    A probe that dispatched nothing would make every `unreached` assertion
    above vacuous while still reporting green.
    """
    total = set()
    for sid in F.step_ids():
        run = live_gate_run(sid)
        if run:
            total.update(run.dispatched)
    declared = set()
    for sid in F.step_ids():
        declared.update(F.gate_program_tokens(sid))
    assert total == declared, (
        f"executor dispatched {len(total)} distinct programs but the yaml "
        f"declares {len(declared)}; difference: "
        f"declared-not-dispatched={sorted(declared - total)}, "
        f"dispatched-not-declared={sorted(total - declared)}"
    )
    assert len(total) >= 50, f"only {len(total)} programs dispatched flow-wide"


def test_probe_channel_b_registry_discovery_finds_the_structural_registry():
    """Discovery must find a real registry, and it must be the big one."""
    registries = umbrella_registries()
    assert registries, (
        f"no dispatch registry discovered in {compliance_module().__file__}"
    )
    biggest = max(registries.items(), key=lambda kv: len(kv[1]))
    assert len(biggest[1]) >= 100, (
        f"largest discovered registry is {biggest[0]} with {len(biggest[1])} "
        f"entries; the P0 umbrella is supposed to carry the structural gate set"
    )
    assert all(F.program_path(g) is not None for g in umbrella_gate_names())


def test_probe_channel_c_resolves_dynamic_fstring_dispatch():
    """`__import__(f"{x}_protocol_synth")` must resolve to a real set.

    This is the exact form PR #460's grep could not see. If the resolver
    returned nothing, channel (c) would under-report silently — so assert the
    f-string channel produces programs that NO other form in the same runner
    would have produced.
    """
    scans = runner_scans()
    assert scans, f"no {RUNNER_GLOB} found under {PROGRAMS_DIR}"
    on_disk = {p.stem for p in PROGRAMS_DIR.glob("*_protocol_synth.py")}
    assert on_disk, "no *_protocol_synth.py programs on disk to resolve against"
    resolved = {s for s in runner_invoked() if s.endswith("_protocol_synth")}
    assert resolved >= on_disk, (
        f"channel (c) resolved {len(resolved)} of {len(on_disk)} "
        f"*_protocol_synth programs; missed {sorted(on_disk - resolved)} — the "
        f"dynamic-dispatch resolver is under-reporting"
    )
    patterns = [
        p for scan in scans.values() for p in scan.fstring_patterns
        if "protocol_synth" in p
    ]
    assert patterns, (
        "no f-string pattern mentioning protocol_synth was resolved; the "
        "dynamic-import branch of the scanner never fired"
    )


def test_probe_channel_c_does_not_match_the_world():
    """The scanner must be selective, or 'invoked' means nothing."""
    invoked = runner_invoked()
    total = len(all_program_stems())
    assert invoked, "channel (c) resolved zero programs across every runner"
    assert len(invoked) < total * 0.6, (
        f"channel (c) claims {len(invoked)}/{total} programs are runner-"
        f"invoked; that ratio means the resolver is matching prose, not "
        f"dispatch sites"
    )


def test_probe_no_cell_rests_on_channel_c_alone():
    """Channel (c) must not be the ONLY thing holding a cell up.

    2026-07-27, adversarial finding (LOW), confirmed by re-measurement:
    `resolve_fstring()` is applied to EVERY `ast.JoinedStr` in a runner, not
    only to the argument of `__import__` / `import_module` / `glob`, so the
    1925 harvested "f-string patterns" include a great deal of prose
    (`'^verdict: [^/\\s]*$'`, an entire multi-line SPICE stub template). The
    60% ceiling above is the only thing between that resolver and "invoked
    means nothing", and it is measuring prose, not dispatch.

    That over-match cannot manufacture a green TODAY because channel (a) — the
    real executor, driven — holds on all 62 gated steps and P0 takes the
    umbrella branch, so the three-channel OR is decided by (a) everywhere and
    (c) never breaks a tie. This test makes that a MEASURED, ENFORCED fact
    instead of a footnote: the day a step's cell would be carried by (c) alone,
    the suite says so, because a branch-blind static scan is not evidence that
    the reaching branch ever executes.
    """
    sole = []
    for sid in F.step_ids():
        if not F.has_gate(sid):
            continue
        ch = channels_for(sid)
        if ch.c and not ch.a and not ch.b:
            sole.append((F.normalize_id(sid), sorted(ch.declared)))
    assert not sole, (
        f"{len(sole)} step(s) are reachable ONLY through channel (c), the "
        f"static runner scan: {sole[:5]}. Channel (c) proves a runner's SOURCE "
        f"can reach a program; it cannot prove the reaching branch executes on "
        f"any project, because every runner branches on IC class, PDK and "
        f"artefact presence. A cell resting on (c) alone is weakly covered and "
        f"needs either a real dispatch proof or an evidence-backed waiver."
    )


#: ``(step, program)`` pairs named in a step's ``programs:`` array that resolve
#: to a real ``programs/<name>.py`` but are reachable through NONE of the three
#: channels, measured 2026-07-27. Residue of the 2026-07 audit's dimension-1
#: DEFECT notes on steps 4/5/6/9.
#:
#: 2026-08-03, vibe-ic#693 — TWO ENTRIES ADDED ON PURPOSE. The two SignalTap
#: gates are declared at step 39 and wired through no channel BY DESIGN, and
#: that is the whole point of listing them: #693's floor is that a shipped,
#: gate-shaped program must never be both unwired and unlisted, and this pin is
#: the only register in the repo whose semantics are exactly "declared in a
#: step's ``programs:`` array and reachable through none of the three
#: channels". Being here is the DISCLOSURE, not permission.
#:
#:   signaltap_recompile_sequence_check — audits a four-stage interactive
#:     SignalTap recompile (quartus_stp -> map -> fit -> asm). The flow's only
#:     FPGA command line is ``quartus_sh --flow compile <base>``, which contains
#:     none of the four tokens, and the published corpus holds 0 compile.log,
#:     0 *.map.rpt and 0 *.sof over 28 run roots. Wiring it anywhere would be
#:     rc=2 NOT-CHECKED on 28/28 — a permanently silent gate.
#:   signaltap_stp_completeness_check — validates a generated ``.stp``. No flow
#:     step produces one and 0 exist in the corpus. It is also not yet safe as a
#:     post-condition of its own declared producer, the MCP tool
#:     ``eda_rtl_signaltap_autogen``, which fails it on its default invocation.
#:
#: Both are driven EXPLICITLY by the agent following
#: ``skills/fpga-signaltap/SKILL.md`` with a board on the bench. If either ever
#: gains a real automatic subject, wire it and delete its line here — this test
#: reddens in that direction too.
#: 2026-08-20, R5 — TWO ENTRIES ADDED, both of the same shape as step 9's
#: ``synth_wrapper_gen``: a step's own PRODUCER, named in ``programs:``, while
#: the step's ``gate`` names the JUDGE instead. Measured on this tree:
#:
#:   submission_template_ingest — step 0.5ic's producer. The step's gate is
#:     ``submission_template_check`` (a different program), so the ingest is
#:     named by no gate. `grep -c` over all eight ``programs/*one_shot_runner*.py``
#:     returns 0 for it, and it is in no umbrella registry.
#:   pad_ring_gen — step 15.5ic's producer, gate ``pad_ring_check``. It had the
#:     same measurement until the Batch73 cmisc arm wired it through
#:     ``phase3_one_shot_runner``. It is deliberately absent from the pin below;
#:     the forward/reverse control beside the census proves dispatch is the only
#:     channel keeping it out.
#:
#: The wider fact behind both was that no runner dispatched a path-specific
#: step. The cmisc arm changed that fact for 15.5ic by adding a real runner
#: branch; submission_template_ingest remains disclosed below because its zero
#: dispatch measurement is unchanged.
#: 2026-08-21 — THREE ENTRIES ADDED, FROM TWO SEPARATE CAUSES, and the two are
#: worth keeping apart because a single-cause story would be wrong here.
#:
#:   ("1.6x", "crosslayer_search_space")
#:   ("1.6x", "crosslayer_rewrite_equivalence")
#:       `7fcbc7397` added step 1.6x with a `programs:` array of three and a
#:       gate that runs exactly one of them, `crosslayer_rewrite_equivalence
#:       _check`. The other two are the PRODUCERS the checker reads after: the
#:       search-space emitter and the equivalence prover. Same shape as the
#:       nine entries below — a generator an agent runs, advertised by the step
#:       and dispatched by no runner.
#:
#:   ("0.5ic", "tapeout_declaration_gen")
#:       NOT from that commit, and this is measured, not assumed:
#:       `git log -S'      - tapeout_declaration_gen'` over the yaml returns
#:       `00d9dc261` (v1.11.4), four releases earlier, which added it to
#:       0.5ic's `programs:` and wired it to nothing. At `ff5071caa`, when this
#:       pin was last set, the entry did not exist in the yaml at all.
#:
#: So this pin was stale for TWO independent reasons before either was noticed,
#: which is the argument for reading it rather than moving it.
#:
#: The other lane recorded the same three entries with a different
#: derivation, kept because it answers a different question — WHY they are
#: unwired rather than WHEN they arrived:
#:
#: on main before the ninth dimension landed; these are what it was red about.
#:
#:   ("0.5ic", "tapeout_declaration_gen")
#:       referenced by exactly one other program, `tapeout_declaration_check`,
#:       which AUDITS its output rather than dispatching it. No gate clause
#:       names it and no runner AST-dispatches it.
#:   ("1.6x", "crosslayer_rewrite_equivalence")
#:   ("1.6x", "crosslayer_search_space")
#:       step 1.6x arrived in v1.11.15 under the message "wire step 1.6x to an
#:       executor". What was wired is the JUDGE, not the tools:
#:       `design_one_shot_runner` dispatches the string constant
#:       `"crosslayer_rewrite_equivalence_check.py"` (AST-confirmed at line
#:       8457) and its own docstring says so in as many words — "Runs the JUDGE
#:       (`crosslayer_rewrite_equivalence_check`), never the tool". The two
#:       TOOLS stay declared on the step and dispatched by nothing, which is
#:       this pin's subject exactly.
#:
#: As the block below already says: being here is the DISCLOSURE, not
#: permission. Wiring any of the three means inventing a dispatch branch, which
#: is a flow change and not a pin repair.
#: 2026-08-26 — TWO ENTRIES REMOVED, in the direction this pin calls good
#: news. `phase1_one_shot_runner` now dispatches step 0.5ic's two producers
#: (`submission_template_ingest`, `tapeout_declaration_gen`) before its mode
#: branch, so both are reachable through channel C. The forward/reverse
#: control below is the same one `pad_ring_gen` got when it left this pin:
#: dispatch, and only dispatch, is what keeps them out.
ORPHAN_DECLARED_PROGRAMS: Tuple[Tuple[str, str], ...] = (
    ("2", "crosslayer_rewrite_equivalence"),
    ("2", "crosslayer_search_space"),
    ("6", "debug_first_pass"),
    ("6", "fpga_test_harness_gen"),
    ("9", "synth_wrapper_gen"),
    ("15", "phase3_backend_step"),
    ("39", "bringup_plan_gen"),
    ("39", "signaltap_recompile_sequence_check"),
    ("39", "signaltap_stp_completeness_check"),
)


def _declared_program_orphans(invoked: Optional[frozenset] = None):
    registry = umbrella_gate_names()
    invoked = runner_invoked() if invoked is None else invoked
    orphans = []
    for sid in F.step_ids():
        gated = set(F.gate_program_tokens(sid))
        for prog in F.declared_programs(sid):
            if F.program_path(prog) is None:
                continue
            if prog in gated or prog in registry or prog in invoked:
                continue
            orphans.append((F.normalize_id(sid), prog))
    return tuple(sorted(orphans))


def test_probe_declared_programs_array_orphans_are_pinned():
    """The ``programs:`` array is OUT of this dimension's cell scope — pinned.

    Dimension 1 as briefed asks about a step's GATE, so every cell is
    correctly green on the steps below: their gates are wired. But the step's
    ``programs:`` array is a second, independent wiring claim, and measured
    live on this tree nine of its entries resolve to a real
    ``programs/<name>.py`` while being named by no gate, registered in no
    umbrella registry, and dispatched by none of the one-shot runners.

    No cell of the 63x8 matrix owns that question. Widening the D1 predicate to
    cover it would have needed four new waivers and would have been the same
    substitution this campaign exists to stop — changing a predicate so a
    finding lands. So the finding is recorded HERE, pinned, outside the cell
    grid: a tenth orphan appearing reddens this test, and one of these nine
    getting wired also reddens it, so the population cannot drift in either
    direction unnoticed. It is reported as an open gap, not as coverage.
    """
    measured = _declared_program_orphans()
    assert measured == tuple(sorted(ORPHAN_DECLARED_PROGRAMS)), (
        f"the set of `programs:` entries wired through NONE of the three "
        f"channels changed: measured {list(measured)!r}, pinned "
        f"{list(sorted(ORPHAN_DECLARED_PROGRAMS))!r}.\n"
        f"Newly orphaned: {sorted(set(measured) - set(ORPHAN_DECLARED_PROGRAMS))} "
        f"— a step now advertises a program nothing runs.\n"
        f"Newly wired: {sorted(set(ORPHAN_DECLARED_PROGRAMS) - set(measured))} "
        f"— good news; remove it from the pin in the same change."
    )


def test_step_0_5ic_producers_left_the_orphan_pin_only_because_a_runner_dispatches_them():
    """Forward/reverse control for the two 2026-08-26 pin removals.

    The pin can only be read as "these got wired" if removing the dispatch
    channel puts them straight back. Both directions are driven here, so a pin
    edit that was not backed by real wiring reddens.
    """
    invoked = runner_invoked()
    for prog in ("submission_template_ingest", "tapeout_declaration_gen"):
        pair = ("0.5ic", prog)
        assert pair not in ORPHAN_DECLARED_PROGRAMS
        assert prog in invoked, runners_invoking(prog)
        assert pair not in _declared_program_orphans(invoked)
        assert pair in _declared_program_orphans(invoked - {prog})


def test_pad_ring_left_the_orphan_pin_only_because_the_runner_dispatches_it():
    """Forward/reverse control for the one Batch73 pin removal."""
    pair = ("15.5ic", "pad_ring_gen")
    invoked = runner_invoked()
    assert pair not in ORPHAN_DECLARED_PROGRAMS
    assert "pad_ring_gen" in invoked, runners_invoking("pad_ring_gen")
    assert pair not in _declared_program_orphans(invoked)
    assert pair in _declared_program_orphans(invoked - {"pad_ring_gen"})


def test_probe_umbrella_dispatch_is_recorded_from_the_real_runner():
    """The umbrella probe must observe REAL subprocess dispatch, not a copy.

    Guards the instrument the P0 cell now rests on: it drives the shipped
    `_run_structural_rtl_gates`, the recording shim is installed on the
    compliance module itself (so a re-implementation cannot be substituted),
    and the module's `subprocess` attribute is restored afterwards.
    """
    mod = compliance_module()
    assert Path(mod.__file__).resolve().parent == PROGRAMS_DIR.resolve()
    run = umbrella_dispatch()
    assert run.harness_error is None, run.harness_error
    assert run.dispatched, (
        "the umbrella probe recorded ZERO subprocess dispatches; the recorder "
        "is not being reached and the P0 cell would be measuring nothing"
    )
    # Every recorded dispatch must be a real programs/<stem>.py.
    stems = all_program_stems()
    unknown = sorted(s for s in run.dispatched if s not in stems)
    assert not unknown, f"umbrella dispatched non-programs: {unknown[:10]}"
    import subprocess as _real_subprocess

    assert getattr(mod, "subprocess") is _real_subprocess, (
        "the recording shim was left installed on flow_compliance_check — "
        "every later test in this process would be measuring the shim"
    )


def test_probe_direct_dispatch_programs_really_dispatch():
    """The `<direct dispatch>` pseudo-registry must be a dispatcher too.

    `umbrella_registry_gate_names()` deliberately excludes these from the P0
    cell's dispatch assertion because a different function subprocesses them.
    Excluding them without measuring them anywhere would move two programs from
    'proved dispatched' to 'assumed dispatched', which is silent absence. So
    they are proved HERE, by driving `_run_yosys_gates` for real against a
    project carrying the .ys script its own finder looks for.
    """
    names = umbrella_registries().get(DIRECT_DISPATCH_KEY, ())
    assert names, (
        f"the {DIRECT_DISPATCH_KEY!r} pseudo-registry is empty; either the "
        f"compliance module stopped subprocessing programs directly, or the "
        f"`PROGRAMS_DIR / \"<name>.py\"` detector stopped matching"
    )
    mod = compliance_module()
    dispatcher = getattr(mod, "_run_yosys_gates", None)
    assert callable(dispatcher), (
        f"{mod.__name__}._run_yosys_gates is {dispatcher!r}; the two "
        f"{DIRECT_DISPATCH_KEY} programs {list(names)} would then be "
        f"registered and never run"
    )
    tmp = Path(tempfile.mkdtemp(prefix="matrix_d1_direct_"))
    real_sub = getattr(mod, "subprocess")
    recorder = _SubprocessRecorder(real_sub, lambda stem: (0, ""))
    try:
        project = tmp / "proj"
        ys = project / "scripts" / "synth.ys"
        ys.parent.mkdir(parents=True)
        ys.write_text("read_verilog top.v\nsynth -top top\n", encoding="utf-8")
        mod.subprocess = recorder
        try:
            dispatcher(project)
        finally:
            mod.subprocess = real_sub
    finally:
        mod.subprocess = real_sub
        shutil.rmtree(tmp, ignore_errors=True)
    dispatched = {Path(c[1]).stem for c in recorder.calls if len(c) > 1}
    missing = sorted(n for n in names if n not in dispatched)
    assert not missing, (
        f"{len(missing)} {DIRECT_DISPATCH_KEY} program(s) were NOT subprocessed "
        f"by the real {mod.__name__}._run_yosys_gates on a project carrying "
        f"{ys.name}: {missing}. Recorded: {sorted(dispatched)}"
    )


def test_probe_umbrella_verdict_is_load_bearing():
    """A registered gate's FAIL must reach the umbrella verdict; rc=2 must skip.

    Without this, `_run_structural_rtl_gates` could dispatch all 241 gates and
    discard every answer — dispatch alone is not enforcement.
    """
    total = sorted(umbrella_gate_names())
    assert total, "no registered structural gates to probe"
    victim = total[0]

    failing = _drive_umbrella(
        lambda stem: ((1, f"{stem}: probe-injected FAIL") if stem == victim
                      else (0, "")))
    assert failing.harness_error is None, failing.harness_error
    assert failing.passed is False, (
        f"one registered structural gate ({victim}) exited 1 and the umbrella "
        f"still reported passed={failing.passed!r} — the 241 dispatches are "
        f"decorative"
    )
    assert any(victim in f for f in failing.fails), (
        f"the umbrella reported passed=False but no fail reason names "
        f"{victim}: {failing.fails[:3]}"
    )

    skipping = _drive_umbrella(
        lambda stem: ((2, "") if stem == victim else (0, "")))
    assert skipping.harness_error is None, skipping.harness_error
    assert skipping.passed is True, (
        f"rc=2 (input-missing) from {victim} was treated as a FAIL: "
        f"{skipping.fails[:3]}"
    )
    assert any(victim in s for s in skipping.skips), (
        f"rc=2 from {victim} produced no NAMED skip entry, so a gate that "
        f"never ran is invisible in the umbrella's report: {skipping.skips[:3]}"
    )


def test_probe_umbrella_step_id_is_a_declared_flow_step():
    sid = umbrella_step_id()
    assert F.has_step(sid), (
        f"{compliance_module().__name__} emits its structural verdict under "
        f"step id {sid!r}, which the flow yaml does not declare"
    )
    assert not F.has_gate(sid), (
        f"step {sid!r} now declares a gate of its own; the umbrella branch in "
        f"test_d1_gate_is_wired_in no longer applies and must be re-derived"
    )


def test_probe_every_cell_is_accounted_for():
    """Every flow step gets exactly one cell, and every cell one parameter.

    The anti-silent-absence check: parametrization is generated from
    `cells_for(1)`, which is generated from the yaml. If those ever diverge,
    a step would have no test and nobody would be told.
    """
    cells = cells_for(DIM)
    step_keys = [F.normalize_id(s) for s in F.step_ids()]
    cell_keys = [F.normalize_id(c.step_id) for c in cells]
    assert cell_keys == step_keys, (
        f"dimension {DIM} enumerates {len(cell_keys)} cells but the flow "
        f"declares {len(step_keys)} steps; "
        f"steps-without-a-cell={sorted(set(step_keys) - set(cell_keys))}, "
        f"cells-without-a-step={sorted(set(cell_keys) - set(step_keys))}"
    )
    assert len(set(cell_keys)) == len(cell_keys), "duplicate step id in the ledger"
    param_keys = [F.normalize_id(p.values[0].step_id) for p in _params()]
    assert param_keys == cell_keys, (
        f"{len(param_keys)} parameters generated for {len(cell_keys)} cells"
    )
    for w in waivers.waivers_for_dim(DIM):
        assert not waivers.validate(w), (
            f"waiver {w.label} is invalid: {waivers.validate(w)}"
        )


def test_probe_waiver_plumbing_yields_a_STRICT_xfail(monkeypatch):
    """A waived d1 cell must produce `xfail(strict=True)`, not a soft skip.

    `waivers.WAIVERS` is empty today and is applied centrally, so this path is
    otherwise unexercised — and an unexercised waiver path is how a waiver
    silently becomes a non-strict xfail that rots forever. Inject one and
    check the mark this module actually attaches.
    """
    sid = F.step_ids()[0]
    probe = waivers.Waiver(
        step_id=sid,
        dim=DIM,
        reason=(
            "probe-only waiver used to prove this module attaches a strict "
            "xfail; it is never registered in waivers.WAIVERS"
        ),
        evidence="programs/tests/test_matrix_d1_wiring.py:test_probe_waiver_plumbing",
    )
    assert not waivers.validate(probe)
    monkeypatch.setattr(
        waivers,
        "waiver_for",
        lambda s, d: probe if (F.normalize_id(s), int(d)) == probe.key else None,
    )
    marked = [p for p in _params() if p.marks]
    assert len(marked) == 1, (
        f"one waiver injected but {len(marked)} parameters came back marked"
    )
    mark = marked[0].marks[0]
    assert mark.name == "xfail", f"waived cell got a {mark.name!r} mark"
    assert mark.kwargs.get("strict") is True, (
        f"waived cell got xfail(strict={mark.kwargs.get('strict')!r}); a "
        f"non-strict xfail lets a fixed gap keep reporting as waived forever"
    )
    assert probe.evidence in mark.kwargs.get("reason", "")


# ══════════════════════════════════════════════════════════════════════
# UNIFORM CELL-STATE INTERFACE (read by programs/tests/test_matrix_63x8_coverage.py)
#
# The coverage meta-test must be able to ask every dimension module the same
# question and get an answer the module itself computes. Anything it derived on
# its own would be a second opinion about cells it does not own — the adjacent
# measurement this campaign removes. Both functions are LIVE: they re-derive
# from the current tree on every call, so a cell that changes state changes its
# answer here without anyone editing a table.
# ══════════════════════════════════════════════════════════════════════
def matrix_na_precondition(step_id):
    """Why this cell is NA, re-derived LIVE, or ``None`` when it is answerable."""
    # Dimension 1 has no NA cell: EVERY step is either gated (channels a/b/c)
    # or IS the umbrella (P0), and both are answerable. There is no "nothing to
    # ask" shape here, so this returns None unconditionally — and that is
    # checked, not assumed: the cell test's umbrella branch asserts P0 is the
    # umbrella step, so a second gate-less step reddens rather than becoming a
    # silent NA.
    del step_id
    return None


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if waivers.waiver_for(step_id, DIM) is not None:
        return "WAIVED"
    return "ENFORCED"
