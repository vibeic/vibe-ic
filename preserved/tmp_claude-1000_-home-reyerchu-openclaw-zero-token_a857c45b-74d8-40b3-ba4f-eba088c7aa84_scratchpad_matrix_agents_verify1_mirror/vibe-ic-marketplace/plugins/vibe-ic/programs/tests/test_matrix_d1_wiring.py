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
        out["<direct dispatch>"] = tuple(direct)
    return out


@lru_cache(maxsize=1)
def umbrella_gate_names() -> frozenset:
    acc: Set[str] = set()
    for members in umbrella_registries().values():
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
