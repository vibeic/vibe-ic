#!/usr/bin/env python3
"""`_ppa/closure.py` — the state machine that turns a declared edge into an act.

WHAT WAS MEASURED, AND WHY THIS FILE EXISTS
===========================================
The canonical flow declares twenty-two `closed_loop:` blocks:

    $ python3 - <<'X'
      import yaml; d=yaml.safe_load(open('flow/phase1_phase2_phase3.yaml'))
      print(len([s for s in d['steps'] if s.get('closed_loop')]))
      X
    22

`closed_loop_edge_check.py` already proves every one of them is a HONEST
declaration — the fallback resolves, the trigger is non-empty, the edge closes a
loop, the declaring step has a gate. It also states, in its own words, the gap
this module is here to close:

    * It does not verify that a runner ACTUALLY re-executes the fallback step.
      No runner reads `closed_loop` today; making one do so is a separate change
      and a larger one.

So on `main` all 22 edges are DECLARED_ONLY *by construction*. A declaration is
a line of YAML. A LOOP is: trigger, classifier, an actuator that really changes
the implementation, the affected steps re-run, the metric RE-MEASURED, promotion
on improvement, ROLLBACK on regression, and a stop condition. This module is the
common machine for that; the per-domain controllers plug into it as data.

THE HONESTY REQUIREMENT IS THE POINT, NOT A CAVEAT
==================================================
An edge with no executable controller is `DECLARED_ONLY` and
`ClosureRun.is_closed_loop_success()` is False for it, permanently and without
an override. A case the controller cannot handle is `HANDOFF_REQUIRED`, never a
pretended repair. A residual violation survives into the record and into the
exit code; it is never summarised away.

This is not a stylistic preference. The failure it prevents is the one this
repository has already shipped twice: a check whose declared invocation cannot
fail, reporting green over a question nobody put.

WHY THE ACTUATOR IS A REGISTRY ENTRY AND NOT A COMMAND STRING
=============================================================
"OpenROAD is allowed" is not an authorisation. `timing.hold.emit_repair_block`
with `margin_ps` in [0, 500] and `max_buffer_percent` in (0, 5] is. Every action
this module can take is an entry in `config/ppa_actuator_registry.yaml` carrying
an action id, a FIXED wrapper (a bare program name resolved under `programs/`),
a typed parameter schema, preconditions, a blast-radius class, resource
ceilings, a rollback kind, and the domains that must be re-measured afterwards.

Three prohibitions are enforced in code and each has its own test:

  * `shell=True` is never used and the registry has no syntax for a shell line.
  * `wrapper.program` must match `^[A-Za-z0-9_]+$` — no separator, no `..`, no
    absolute path — and must resolve to a real file under `programs/`.
  * no parameter may carry a script, a command, or an argv fragment, and a
    `path` parameter must resolve INSIDE the controlled implementation root.
    A parameter that escapes the root is a refusal, not a warning.

WHY THE PARAMETER PLAN IS A DECLARED LADDER AND NOT A SEARCH
============================================================
A controller escalates through an ordered list of parameter dictionaries
declared in the registry. It is deterministic, it is reviewable, and re-running
it on the same inputs takes the same actions in the same order. Candidate
generation, budget allocation and multi-fidelity belong to `_ppa/search.py`,
which is a different lane; a controller that invented its own search would make
the two disagree about what a run cost.

WHAT "RE-MEASURED" MEANS HERE, STATED SO NOBODY HAS TO INFER IT
===============================================================
The controller re-executes the DECLARED measurement command for every domain in
the actuator's `remeasure_domains`, over the changed implementation. A domain
also names the flow steps that a full run would have to re-execute
(`flow_steps`), so the record says what a real re-run would cover even when this
process only re-ran the measurement. A regression in ANY re-measured domain
rolls the iteration back, even when the objective domain improved — that is what
`remeasure_domains` is FOR, and a controller that only looked at its own
objective would trade one domain for another silently.

EXIT-CODE DISCIPLINE (docs/PPA_INTERFACES.md §1) IS ENCODED IN `Outcome`
========================================================================
`Outcome.exit_code()` is the single mapping. `rc=1` is a claim about the design
and is used only when the loop really ran and really left a violation. Anything
this module could not put a question to — an unreadable registry, an unbound
edge, a baseline measurement that refused — is `rc=2` with a printed marker.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - yaml is a hard dependency of the plugin
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _ppa import canonical_json as cj  # noqa: E402

__all__ = [
    "SCHEMA_REGISTRY", "SCHEMA_RUN", "REGISTRY_REL",
    "RegistryError", "PreconditionUnmet", "ParameterError",
    "Binding", "BlastRadius", "Rollback", "Direction", "State", "Outcome",
    "Actuator", "Domain", "Controller", "Registry",
    "Iteration", "ClosureRun", "ClosureController",
    "load_registry", "default_registry_path", "tree_digest",
]

SCHEMA_REGISTRY = "vibeic.ppa.actuator_registry.v1"
SCHEMA_RUN = "vibeic.ppa.closure_run.v1"

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent.parent
REGISTRY_REL = Path("config") / "ppa_actuator_registry.yaml"
PROGRAMS_DIR: Path = PLUGIN_ROOT / "programs"

#: The one override, so a falsifiability replay can repoint the registry at a
#: mutant without editing the shipped file. Named like the flow's own override
#: (`VIBE_IC_MATRIX_FLOW_YAML`) so a reader recognises the shape.
REGISTRY_ENV = "VIBE_IC_PPA_ACTUATOR_REGISTRY"

#: A wrapper is a bare program name. Anything with a separator, a dot segment or
#: a leading slash is refused before it is resolved -- resolving first and
#: checking afterwards is how a `..` gets to be a real path for one instant.
PROGRAM_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

#: Parameter names that would smuggle an unbounded command in through a typed
#: field. The registry may not declare one; the check is on the NAME because the
#: value is attacker-shaped and the name is author-shaped.
FORBIDDEN_PARAM_NAMES = frozenset({
    "argv", "args", "cmd", "command", "script", "shell", "exec", "eval",
    "tcl", "tcl_script", "python", "code", "expr", "extra_args", "raw",
})

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")
_GLOB_TOKEN_RE = re.compile(r"\{glob:([^{}]+)\}")


class RegistryError(ValueError):
    """The registry cannot be read, parsed, or trusted.

    Always maps to rc=2 at a CLI boundary: a registry we could not read is a
    question we could not put, never a finding about a design.
    """


class ParameterError(ValueError):
    """A proposed parameter set violates its declared type or bounds."""


class PreconditionUnmet(RuntimeError):
    """A declared precondition of an actuator does not hold right now."""


class Binding(str, Enum):
    """Whether an actuator can actually be invoked, as CLAIMED by the registry.

    The claim is checked: `Registry.verify_bindings()` refuses a registry whose
    EXECUTABLE entry names a program that is not in the tree. An unchecked
    claim of executability is the same defect as an unexecuted closed_loop.
    """

    EXECUTABLE = "EXECUTABLE"
    DECLARED_ONLY = "DECLARED_ONLY"


class BlastRadius(str, Enum):
    """How much of the implementation an action can disturb.

    Ordered smallest to largest. It is not decoration: `Rollback.NONE` is only
    admissible at NET, and the loader enforces that, because an action that
    cannot be undone and can move a block is an action with no way back.
    """

    NET = "NET"
    INSTANCE = "INSTANCE"
    DECK = "DECK"
    BLOCK = "BLOCK"
    FULL_IMPLEMENTATION = "FULL_IMPLEMENTATION"


_BLAST_ORDER = {b: i for i, b in enumerate(BlastRadius)}


class Rollback(str, Enum):
    SNAPSHOT_RESTORE = "SNAPSHOT_RESTORE"
    INVERSE_ACTION = "INVERSE_ACTION"
    NONE = "NONE"


class Direction(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class State(str, Enum):
    """Spec §10.1. Every transition this module makes is recorded by name.

    The states are written down because a controller that only reports its
    outcome is a controller whose behaviour cannot be reviewed: "it rolled back"
    and "it never actuated" leave the same implementation on disk.
    """

    IDLE = "IDLE"
    TRIGGER_EVALUATED = "TRIGGER_EVALUATED"
    CLASSIFIED = "CLASSIFIED"
    ACTUATOR_SELECTED = "ACTUATOR_SELECTED"
    ACTUATED = "ACTUATED"
    REMEASURED = "REMEASURED"
    JUDGED = "JUDGED"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    STOPPED = "STOPPED"


class Outcome(str, Enum):
    """The terminal verdict, and the ONLY place exit codes are decided."""

    #: The trigger did not fire: the objective was already satisfied. Green, and
    #: honestly so -- nothing was wrong, so nothing was repaired.
    NOT_TRIGGERED = "NOT_TRIGGERED"
    #: The loop ran and the objective is now satisfied.
    CONVERGED = "CONVERGED"
    #: The loop ran, made no further progress, and a violation REMAINS.
    PLATEAU = "PLATEAU"
    #: The loop ran out of its declared budget with a violation REMAINING.
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    #: The controller cannot handle this case. NEVER a pretended repair.
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"
    #: The edge is declared in the flow and has no executable controller.
    DECLARED_ONLY = "DECLARED_ONLY"
    #: The baseline could not be measured, so no claim is available at all.
    NOT_MEASURED = "NOT_MEASURED"

    def exit_code(self) -> int:
        """docs/PPA_INTERFACES.md §1, in one table nobody can bypass."""
        if self in (Outcome.NOT_TRIGGERED, Outcome.CONVERGED):
            return 0
        if self in (Outcome.PLATEAU, Outcome.BUDGET_EXHAUSTED,
                    Outcome.HANDOFF_REQUIRED):
            # The loop really ran and really left a violation standing. That is
            # a finding about the DESIGN, which is what 1 means.
            return 1
        # DECLARED_ONLY and NOT_MEASURED: we did not look, or could not.
        return 2

    def is_success(self) -> bool:
        """Whether this outcome may be displayed as a closed-loop success.

        DECLARED_ONLY is False here and there is no flag that changes it. That
        is the whole honesty requirement, expressed as one method so that a
        reporting layer cannot get it wrong by accident.
        """
        return self in (Outcome.NOT_TRIGGERED, Outcome.CONVERGED)

    def marker(self) -> str:
        """The stderr marker, so a 2 can never read as a silent skip."""
        if self is Outcome.DECLARED_ONLY:
            return "[CANNOT CHECK]"
        if self is Outcome.NOT_MEASURED:
            return "[CANNOT CHECK]"
        if self is Outcome.HANDOFF_REQUIRED:
            return "[HANDOFF REQUIRED]"
        return ""


# ---------------------------------------------------------------------------
# Registry: typed entries, validated at load, never at use.
# ---------------------------------------------------------------------------

_PARAM_TYPES = {"number", "integer", "string", "boolean", "path"}


@dataclass(frozen=True)
class ParamSpec:
    """One typed parameter. `unit` is mandatory for numbers: a bound without a
    unit is a bound on nothing, and this contract already pays for units in the
    metric record."""

    name: str
    type: str
    unit: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    exclusive_minimum: Optional[float] = None
    enum: Optional[Tuple[Any, ...]] = None
    required: bool = True
    default: Any = None
    description: str = ""

    def coerce(self, value: Any) -> Any:
        """Validate `value` against this spec and return the argv-ready form.

        Raises ParameterError. Never clamps: silently clamping an out-of-range
        request would let a caller ask for a runaway budget and be told it got
        what it asked for.
        """
        if self.type == "boolean":
            if not isinstance(value, bool):
                raise ParameterError(
                    f"parameter {self.name!r}: expected boolean, got "
                    f"{type(value).__name__}")
            return value
        if self.type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ParameterError(
                    f"parameter {self.name!r}: expected integer, got "
                    f"{type(value).__name__}")
            self._check_range(float(value))
            return value
        if self.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ParameterError(
                    f"parameter {self.name!r}: expected number, got "
                    f"{type(value).__name__}")
            fv = float(value)
            if fv != fv or fv in (float("inf"), float("-inf")):
                raise ParameterError(
                    f"parameter {self.name!r}: {value!r} is not finite")
            self._check_range(fv)
            return value
        if self.type in ("string", "path"):
            if not isinstance(value, str):
                raise ParameterError(
                    f"parameter {self.name!r}: expected string, got "
                    f"{type(value).__name__}")
            if self.enum is not None and value not in self.enum:
                raise ParameterError(
                    f"parameter {self.name!r}: {value!r} is not one of "
                    f"{list(self.enum)}")
            return value
        raise ParameterError(  # pragma: no cover - load-time guarded
            f"parameter {self.name!r}: unknown type {self.type!r}")

    def _check_range(self, fv: float) -> None:
        if self.enum is not None and fv not in [float(e) for e in self.enum]:
            raise ParameterError(
                f"parameter {self.name!r}: {fv!r} is not one of "
                f"{list(self.enum)}")
        if self.minimum is not None and fv < self.minimum:
            raise ParameterError(
                f"parameter {self.name!r}: {fv} below declared minimum "
                f"{self.minimum}")
        if self.exclusive_minimum is not None and fv <= self.exclusive_minimum:
            raise ParameterError(
                f"parameter {self.name!r}: {fv} is not above declared "
                f"exclusiveMinimum {self.exclusive_minimum}")
        if self.maximum is not None and fv > self.maximum:
            raise ParameterError(
                f"parameter {self.name!r}: {fv} above declared maximum "
                f"{self.maximum} -- the ceiling is the authorisation, so a "
                f"request beyond it is refused, not clamped")


@dataclass(frozen=True)
class Precondition:
    """A named, evaluable condition. Prose preconditions are not preconditions."""

    kind: str            # file_exists | file_absent | file_nonempty
    path: str            # relative to the implementation root; may interpolate

    def holds(self, impl_root: Path, params: Mapping[str, Any]) -> Tuple[bool, str]:
        rendered = _render(self.path, params)
        target = _resolve_inside(impl_root, rendered, what="precondition path")
        if self.kind == "file_exists":
            ok = target.exists()
            return ok, f"file_exists({rendered}) -> {ok}"
        if self.kind == "file_absent":
            ok = not target.exists()
            return ok, f"file_absent({rendered}) -> {ok}"
        if self.kind == "file_nonempty":
            ok = target.is_file() and target.stat().st_size > 0
            return ok, f"file_nonempty({rendered}) -> {ok}"
        raise RegistryError(  # pragma: no cover - load-time guarded
            f"unknown precondition kind {self.kind!r}")


@dataclass(frozen=True)
class Ceilings:
    wall_seconds: float
    max_invocations_per_run: int


@dataclass(frozen=True)
class Actuator:
    action_id: str
    summary: str
    binding: Binding
    program: Optional[str]
    argv_template: Tuple[str, ...]
    parameters: Mapping[str, ParamSpec]
    preconditions: Tuple[Precondition, ...]
    blast_radius: BlastRadius
    ceilings: Ceilings
    rollback: Rollback
    remeasure_domains: Tuple[str, ...]
    #: Where `program` is resolved. A FIELD and not a module global so a test
    #: can exercise the real loader against a real wrapper WITHOUT writing an
    #: executable into the shipped tree -- which `suite_write_guard` forbids
    #: and which would put a fixture on the same shelf as a shipped program.
    #: It is not an environment variable: an ambient override of where code is
    #: found is a loosening nobody would see in a diff.
    programs_dir: Path = PROGRAMS_DIR

    def program_path(self) -> Path:
        """Where the wrapper lives. Callers must have checked `binding` first."""
        if self.program is None:  # pragma: no cover - guarded by callers
            raise RegistryError(
                f"actuator {self.action_id!r} is DECLARED_ONLY and has no "
                f"program")
        return self.programs_dir / f"{self.program}.py"

    def bind_params(self, proposal: Mapping[str, Any]) -> Dict[str, Any]:
        """Type-check a proposal against the declared schema.

        An undeclared key is a REFUSAL, not an ignored extra. An unknown key is
        how a caller believes it configured something it did not.
        """
        unknown = sorted(set(proposal) - set(self.parameters))
        if unknown:
            raise ParameterError(
                f"actuator {self.action_id!r}: undeclared parameter(s) "
                f"{unknown}; declared are {sorted(self.parameters)}")
        bound: Dict[str, Any] = {}
        for name, spec in self.parameters.items():
            if name in proposal:
                bound[name] = spec.coerce(proposal[name])
            elif spec.default is not None:
                bound[name] = spec.coerce(spec.default)
            elif spec.required:
                raise ParameterError(
                    f"actuator {self.action_id!r}: required parameter "
                    f"{name!r} not supplied")
        return bound

    def build_argv(self, impl_root: Path,
                   params: Mapping[str, Any]) -> List[str]:
        """The exact argv. No shell, ever -- there is nowhere to put one.

        Every `path` parameter is resolved against `impl_root` and refused if it
        escapes it, so the blast radius the registry declares is the blast
        radius the process gets.
        """
        rendered: Dict[str, str] = {}
        for name, value in params.items():
            spec = self.parameters[name]
            if spec.type == "path":
                target = _resolve_inside(impl_root, str(value),
                                         what=f"parameter {name!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                rendered[name] = str(target)
            elif spec.type == "boolean":
                rendered[name] = "true" if value else "false"
            elif isinstance(value, float):
                rendered[name] = repr(value) if value != int(value) else str(int(value))
            else:
                rendered[name] = str(value)
        argv = [sys.executable, str(self.program_path())]
        for token in self.argv_template:
            argv.append(_render(token, rendered))
        return argv

    def check_preconditions(self, impl_root: Path,
                            params: Mapping[str, Any]) -> List[str]:
        """Return the list of UNMET preconditions, each as a readable line."""
        unmet: List[str] = []
        for pre in self.preconditions:
            ok, why = pre.holds(impl_root, params)
            if not ok:
                unmet.append(why)
        return unmet


@dataclass(frozen=True)
class Extractor:
    """How a number is lifted out of a measurement's `--json`.

    Declarative on purpose: an extractor that could run code would put a second,
    unreviewed program inside a config file.
    """

    kind: str                       # json_pointer | bool_fraction | list_length
    pointer: str
    flag: Optional[str] = None

    def extract(self, doc: Any) -> Tuple[Optional[float], str]:
        """Return `(value, formula)`. `None` means the document does not carry
        the number -- which is NOT_MEASURED, never 0."""
        node = _json_pointer(doc, self.pointer)
        if node is _MISSING:
            return None, f"{self.kind}({self.pointer}) -> pointer not present"
        if self.kind == "json_pointer":
            if isinstance(node, bool) or not isinstance(node, (int, float)):
                return None, f"json_pointer({self.pointer}) -> not a number"
            return float(node), f"json_pointer({self.pointer})"
        if self.kind == "list_length":
            if not isinstance(node, list):
                return None, f"list_length({self.pointer}) -> not a list"
            return float(len(node)), f"len({self.pointer})"
        if self.kind == "bool_fraction":
            if not isinstance(node, list) or not node:
                # An EMPTY list is not "everything is true". A fraction over a
                # zero denominator is undefined and this repository has paid
                # three times for a check that called it clean.
                return None, (f"bool_fraction({self.pointer}.{self.flag}) -> "
                              f"empty or absent denominator")
            total = len(node)
            hits = 0
            for item in node:
                if not isinstance(item, dict) or self.flag not in item:
                    return None, (f"bool_fraction({self.pointer}.{self.flag}) "
                                  f"-> an element does not carry the flag")
                if item[self.flag]:
                    hits += 1
            return (hits / total,
                    f"count({self.pointer}[].{self.flag}==true)/{total}"
                    f" = {hits}/{total}")
        raise RegistryError(  # pragma: no cover - load-time guarded
            f"unknown extractor kind {self.kind!r}")


@dataclass(frozen=True)
class Domain:
    """One re-measurable question, with the command that answers it."""

    name: str
    metric: str
    unit: str
    direction: Direction
    program: Optional[str]
    argv_template: Tuple[str, ...]
    extract: Optional[Extractor]
    satisfied_op: str                 # ">=" | "<=" | "==" | "<" | ">"
    satisfied_value: float
    #: The flow steps a real re-run would have to re-execute for this domain.
    #: Recorded so the run record says what was NOT re-run in-process.
    flow_steps: Tuple[str, ...]
    binding: Binding
    #: rc values from the measurement program that mean "I could not look".
    undetermined_rcs: Tuple[int, ...] = (2, 3)
    programs_dir: Path = PROGRAMS_DIR

    def program_path(self) -> Path:
        if self.program is None:  # pragma: no cover - guarded by callers
            raise RegistryError(f"domain {self.name!r} has no program")
        return self.programs_dir / f"{self.program}.py"

    def build_argv(self, impl_root: Path, json_out: Path) -> List[str]:
        """The exact argv of the measurement. Two token forms, both declarative.

        `{glob:<pattern>}` expands to every match under the implementation root,
        SORTED, as separate argv items. It is a token form and not a special
        case for one tool because "measure every deck in the tree" is the shape
        every deck-shaped measurement has, and an empty expansion is left empty
        rather than silently dropping the flag -- a measurement invoked over
        nothing must refuse, and its own rc is what says so.
        """
        subs = {"impl_root": str(impl_root), "json_out": str(json_out)}
        argv = [sys.executable, str(self.program_path())]
        for token in self.argv_template:
            m = _GLOB_TOKEN_RE.fullmatch(token)
            if m:
                argv.extend(sorted(str(p) for p in impl_root.rglob(m.group(1))
                                   if p.is_file()))
                continue
            argv.append(_render(token, subs))
        return argv

    def satisfied(self, value: float) -> bool:
        ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
               ">": lambda a, b: a > b, "<": lambda a, b: a < b,
               "==": lambda a, b: a == b}
        return ops[self.satisfied_op](value, self.satisfied_value)

    def improves(self, new: float, old: float) -> bool:
        return new > old if self.direction is Direction.MAXIMIZE else new < old

    def regresses(self, new: float, old: float) -> bool:
        return new < old if self.direction is Direction.MAXIMIZE else new > old


@dataclass(frozen=True)
class Controller:
    """A named binding of one edge to one actuator and one objective domain."""

    controller_id: str
    summary: str
    objective_domain: str
    actuator_id: str
    plan: Tuple[Mapping[str, Any], ...]
    max_iterations: int
    plateau_patience: int
    wall_seconds: float


@dataclass
class Registry:
    path: Path
    actuators: Dict[str, Actuator]
    domains: Dict[str, Domain]
    controllers: Dict[str, Controller]
    #: Flow step id (RAW, as the YAML declares it) -> controller id or None.
    edges: Dict[str, Optional[str]]
    raw: Mapping[str, Any]

    def digest(self) -> str:
        """The identity of the authorisation this run acted under."""
        return cj.digest_of(_plain(self.raw))

    def controller_for_edge(self, edge_id: str) -> Optional[Controller]:
        cid = self.edges.get(edge_id)
        if cid is None:
            return None
        return self.controllers.get(cid)

    def verify_bindings(self) -> List[str]:
        """Every EXECUTABLE claim must resolve to a real file. Returns findings.

        An unverified claim of executability is the same defect one level up as
        an unexecuted `closed_loop`: a promise nothing checks.
        """
        problems: List[str] = []
        for aid, act in sorted(self.actuators.items()):
            if act.binding is Binding.EXECUTABLE:
                if not act.program_path().is_file():
                    problems.append(
                        f"actuator {aid!r} claims EXECUTABLE but "
                        f"{act.program_path()} is not a file")
            elif act.program is not None:
                problems.append(
                    f"actuator {aid!r} is DECLARED_ONLY but names a program "
                    f"{act.program!r}; a DECLARED_ONLY entry must name none, "
                    f"so that the label and the tree cannot disagree")
        for dname, dom in sorted(self.domains.items()):
            if dom.binding is Binding.EXECUTABLE:
                if not dom.program_path().is_file():
                    problems.append(
                        f"domain {dname!r} claims EXECUTABLE but "
                        f"{dom.program_path()} is not a file")
            elif dom.program is not None:
                problems.append(
                    f"domain {dname!r} is DECLARED_ONLY but names a program "
                    f"{dom.program!r}")
        return problems

    def edge_status(self) -> Dict[str, str]:
        """Per declared edge: BOUND or DECLARED_ONLY. The headline number."""
        out: Dict[str, str] = {}
        for edge_id, cid in self.edges.items():
            if cid is None:
                out[edge_id] = Outcome.DECLARED_ONLY.value
                continue
            ctl = self.controllers.get(cid)
            if ctl is None:
                out[edge_id] = Outcome.DECLARED_ONLY.value
                continue
            act = self.actuators.get(ctl.actuator_id)
            dom = self.domains.get(ctl.objective_domain)
            bound = (act is not None and act.binding is Binding.EXECUTABLE
                     and dom is not None and dom.binding is Binding.EXECUTABLE)
            out[edge_id] = "BOUND" if bound else Outcome.DECLARED_ONLY.value
        return out


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def default_registry_path() -> Path:
    env = os.environ.get(REGISTRY_ENV)
    if env:
        return Path(env)
    return PLUGIN_ROOT / REGISTRY_REL


def load_registry(path: Optional[Path] = None,
                  programs_dir: Optional[Path] = None) -> Registry:
    """Parse and VALIDATE. Every refusal here becomes rc=2 at a CLI boundary."""
    path = Path(path) if path is not None else default_registry_path()
    programs_dir = Path(programs_dir) if programs_dir is not None else PROGRAMS_DIR
    if yaml is None:  # pragma: no cover
        raise RegistryError("PyYAML is not importable; the registry cannot be read")
    if not path.is_file():
        raise RegistryError(f"actuator registry not found at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"actuator registry unreadable at {path}: {exc}") from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"actuator registry at {path} is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise RegistryError(f"actuator registry at {path} is not a mapping")
    if doc.get("schema") != SCHEMA_REGISTRY:
        raise RegistryError(
            f"actuator registry at {path} declares schema "
            f"{doc.get('schema')!r}, expected {SCHEMA_REGISTRY!r}")

    actuators = {aid: _load_actuator(aid, spec, programs_dir)
                 for aid, spec in _mapping(doc, "actuators", path).items()}
    domains = {name: _load_domain(name, spec, programs_dir)
               for name, spec in _mapping(doc, "domains", path).items()}
    controllers = {cid: _load_controller(cid, spec, actuators, domains)
                   for cid, spec in _mapping(doc, "controllers", path).items()}

    edges_raw = _mapping(doc, "edges", path)
    edges: Dict[str, Optional[str]] = {}
    for edge_id, spec in edges_raw.items():
        key = str(edge_id)
        if spec is None:
            edges[key] = None
            continue
        if not isinstance(spec, dict):
            raise RegistryError(f"edge {key!r}: expected a mapping or null")
        cid = spec.get("controller")
        if cid is not None and cid not in controllers:
            raise RegistryError(
                f"edge {key!r} names controller {cid!r}, which is not declared")
        edges[key] = cid

    if not edges:
        # A ZERO DENOMINATOR IS A REFUSAL, NOT A PASS. A registry that lists no
        # edge would let every caller report "0 unbound edges" over a document
        # that describes nothing, which is the empty-corpus green this
        # repository has hit in three separate systems.
        raise RegistryError(
            f"actuator registry at {path} declares no edges. An empty edge set "
            f"is a document that answers nothing, not a flow with no loops; "
            f"the flow declares 22.")
    reg = Registry(path=path, actuators=actuators, domains=domains,
                   controllers=controllers, edges=edges, raw=doc)
    return reg


def _mapping(doc: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    node = doc.get(key)
    if node is None:
        raise RegistryError(f"actuator registry at {path} has no {key!r} section")
    if not isinstance(node, dict):
        raise RegistryError(f"actuator registry at {path}: {key!r} is not a mapping")
    return node


def _load_actuator(aid: str, spec: Any, programs_dir: Path) -> Actuator:
    if not isinstance(spec, dict):
        raise RegistryError(f"actuator {aid!r}: entry is not a mapping")
    binding = _enum(Binding, spec.get("binding"), f"actuator {aid!r}.binding")
    wrapper = spec.get("wrapper") or {}
    if not isinstance(wrapper, dict):
        raise RegistryError(f"actuator {aid!r}: wrapper is not a mapping")
    for banned in ("shell", "shell_command", "command_line"):
        if banned in wrapper:
            raise RegistryError(
                f"actuator {aid!r}: wrapper carries {banned!r}. A wrapper is an "
                f"argv, never a shell line; there is no shell in this module "
                f"for it to reach.")
    program = wrapper.get("program")
    argv_template = tuple(str(t) for t in (wrapper.get("argv_template") or ()))
    if binding is Binding.EXECUTABLE:
        if not isinstance(program, str) or not PROGRAM_NAME_RE.match(program):
            raise RegistryError(
                f"actuator {aid!r}: wrapper.program {program!r} is not a bare "
                f"program name matching {PROGRAM_NAME_RE.pattern}")
    elif program is not None:
        raise RegistryError(
            f"actuator {aid!r}: DECLARED_ONLY entries name no program")

    params: Dict[str, ParamSpec] = {}
    for pname, pspec in (spec.get("parameters") or {}).items():
        if pname in FORBIDDEN_PARAM_NAMES:
            raise RegistryError(
                f"actuator {aid!r}: parameter {pname!r} is forbidden -- a typed "
                f"field may not carry a script, a command or an argv fragment")
        if not isinstance(pspec, dict):
            raise RegistryError(f"actuator {aid!r}: parameter {pname!r} is not a mapping")
        ptype = pspec.get("type")
        if ptype not in _PARAM_TYPES:
            raise RegistryError(
                f"actuator {aid!r}: parameter {pname!r} has type {ptype!r}, "
                f"expected one of {sorted(_PARAM_TYPES)}")
        if ptype in ("number", "integer") and not pspec.get("unit"):
            raise RegistryError(
                f"actuator {aid!r}: numeric parameter {pname!r} declares no "
                f"unit; a bound without a unit is a bound on nothing")
        enum = pspec.get("enum")
        params[pname] = ParamSpec(
            name=pname, type=ptype, unit=pspec.get("unit"),
            minimum=pspec.get("minimum"), maximum=pspec.get("maximum"),
            exclusive_minimum=pspec.get("exclusiveMinimum"),
            enum=tuple(enum) if enum is not None else None,
            required=bool(pspec.get("required", True)),
            default=pspec.get("default"),
            description=str(pspec.get("description", "")),
        )

    for token in argv_template:
        for ph in _PLACEHOLDER_RE.findall(token):
            if ph not in params:
                raise RegistryError(
                    f"actuator {aid!r}: argv_template references {{{ph}}}, "
                    f"which is not a declared parameter")
            # MEASURED while writing the round-trip tests: an OPTIONAL parameter
            # with no default that appears in the template builds an argv that
            # cannot be rendered, and the failure surfaced mid-run as a
            # HANDOFF_REQUIRED -- an authorisation defect wearing the costume of
            # a design finding. A template slot must always be fillable, so the
            # parameter behind it is required or it has a default, and either
            # way that is decided HERE and not on the third iteration.
            slot = params[ph]
            if not slot.required and slot.default is None:
                raise RegistryError(
                    f"actuator {aid!r}: argv_template references {{{ph}}}, "
                    f"which is optional and has no default. A template slot "
                    f"that cannot always be filled builds an argv that cannot "
                    f"always be rendered.")

    pres = []
    for p in (spec.get("preconditions") or ()):
        if not isinstance(p, dict) or "kind" not in p or "path" not in p:
            raise RegistryError(
                f"actuator {aid!r}: a precondition needs a kind and a path")
        if p["kind"] not in ("file_exists", "file_absent", "file_nonempty"):
            raise RegistryError(
                f"actuator {aid!r}: unknown precondition kind {p['kind']!r}")
        pres.append(Precondition(kind=str(p["kind"]), path=str(p["path"])))

    blast = _enum(BlastRadius, spec.get("blast_radius"),
                  f"actuator {aid!r}.blast_radius")
    rb = _enum(Rollback, spec.get("rollback"), f"actuator {aid!r}.rollback")
    if rb is Rollback.NONE and _BLAST_ORDER[blast] > _BLAST_ORDER[BlastRadius.NET]:
        raise RegistryError(
            f"actuator {aid!r}: rollback NONE is only admissible at blast "
            f"radius NET; {blast.value} with no way back is an action that "
            f"cannot be undone over something that matters")

    ceil = spec.get("resource_ceilings") or {}
    if not isinstance(ceil, dict) or "wall_seconds" not in ceil \
            or "max_invocations_per_run" not in ceil:
        raise RegistryError(
            f"actuator {aid!r}: resource_ceilings must declare wall_seconds and "
            f"max_invocations_per_run; an unbounded actuator is not authorised, "
            f"it is merely unmeasured")
    ceilings = Ceilings(wall_seconds=float(ceil["wall_seconds"]),
                        max_invocations_per_run=int(ceil["max_invocations_per_run"]))
    if ceilings.wall_seconds <= 0 or ceilings.max_invocations_per_run <= 0:
        raise RegistryError(f"actuator {aid!r}: resource ceilings must be positive")

    rem = tuple(str(d) for d in (spec.get("remeasure_domains") or ()))
    if not rem:
        raise RegistryError(
            f"actuator {aid!r}: remeasure_domains is empty. An action whose "
            f"effect nobody re-measures is an action with no evidence.")

    return Actuator(action_id=aid, summary=str(spec.get("summary", "")),
                    binding=binding, program=program, argv_template=argv_template,
                    parameters=params, preconditions=tuple(pres),
                    blast_radius=blast, ceilings=ceilings, rollback=rb,
                    remeasure_domains=rem, programs_dir=programs_dir)


def _load_domain(name: str, spec: Any, programs_dir: Path) -> Domain:
    if not isinstance(spec, dict):
        raise RegistryError(f"domain {name!r}: entry is not a mapping")
    binding = _enum(Binding, spec.get("binding"), f"domain {name!r}.binding")
    measure = spec.get("measure") or {}
    if not isinstance(measure, dict):
        raise RegistryError(f"domain {name!r}: measure is not a mapping")
    program = measure.get("program")
    if binding is Binding.EXECUTABLE:
        if not isinstance(program, str) or not PROGRAM_NAME_RE.match(program):
            raise RegistryError(
                f"domain {name!r}: measure.program {program!r} is not a bare "
                f"program name matching {PROGRAM_NAME_RE.pattern}")
    elif program is not None:
        raise RegistryError(f"domain {name!r}: DECLARED_ONLY domains name no program")
    ex = measure.get("extract")
    extractor = None
    if ex is not None:
        if not isinstance(ex, dict) or ex.get("kind") not in (
                "json_pointer", "bool_fraction", "list_length"):
            raise RegistryError(f"domain {name!r}: bad extract declaration")
        if ex["kind"] == "bool_fraction" and not ex.get("flag"):
            raise RegistryError(f"domain {name!r}: bool_fraction needs a flag")
        extractor = Extractor(kind=str(ex["kind"]), pointer=str(ex["pointer"]),
                              flag=ex.get("flag"))
    elif binding is Binding.EXECUTABLE:
        raise RegistryError(
            f"domain {name!r}: an EXECUTABLE domain must declare how its number "
            f"is extracted; a measurement nobody can read is not a measurement")
    sat = spec.get("satisfied_when") or {}
    if not isinstance(sat, dict) or sat.get("op") not in (">=", "<=", ">", "<", "=="):
        raise RegistryError(f"domain {name!r}: satisfied_when needs op and value")
    if not isinstance(sat.get("value"), (int, float)) or isinstance(sat.get("value"), bool):
        raise RegistryError(f"domain {name!r}: satisfied_when.value must be a number")
    if not spec.get("unit"):
        raise RegistryError(f"domain {name!r}: a metric without a unit is a number alone")
    if not spec.get("metric"):
        raise RegistryError(f"domain {name!r}: no metric name declared")
    return Domain(
        name=name, metric=str(spec["metric"]), unit=str(spec["unit"]),
        direction=_enum(Direction, spec.get("direction"), f"domain {name!r}.direction"),
        program=program,
        argv_template=tuple(str(t) for t in (measure.get("argv_template") or ())),
        extract=extractor, satisfied_op=str(sat["op"]),
        satisfied_value=float(sat["value"]),
        flow_steps=tuple(str(s) for s in (spec.get("flow_steps") or ())),
        binding=binding,
        undetermined_rcs=tuple(int(r) for r in (measure.get("undetermined_rcs") or (2, 3))),
        programs_dir=programs_dir,
    )


def _load_controller(cid: str, spec: Any, actuators: Mapping[str, Actuator],
                     domains: Mapping[str, Domain]) -> Controller:
    if not isinstance(spec, dict):
        raise RegistryError(f"controller {cid!r}: entry is not a mapping")
    aid = spec.get("actuator")
    if aid not in actuators:
        raise RegistryError(f"controller {cid!r}: actuator {aid!r} is not declared")
    dom = spec.get("objective_domain")
    if dom not in domains:
        raise RegistryError(f"controller {cid!r}: domain {dom!r} is not declared")
    for rd in actuators[aid].remeasure_domains:
        if rd not in domains:
            raise RegistryError(
                f"controller {cid!r}: actuator {aid!r} wants domain {rd!r} "
                f"re-measured and no such domain is declared")
    if dom not in actuators[aid].remeasure_domains:
        raise RegistryError(
            f"controller {cid!r}: its objective domain {dom!r} is not in the "
            f"actuator's remeasure_domains -- the thing being optimised must be "
            f"the thing being re-measured")
    plan = spec.get("plan")
    if not isinstance(plan, list) or not plan:
        raise RegistryError(
            f"controller {cid!r}: plan must be a non-empty ordered list of "
            f"parameter proposals; a controller with no declared ladder would "
            f"have to invent one at runtime")
    for i, proposal in enumerate(plan):
        if not isinstance(proposal, dict):
            raise RegistryError(f"controller {cid!r}: plan[{i}] is not a mapping")
        if actuators[aid].binding is Binding.EXECUTABLE:
            actuators[aid].bind_params(proposal)   # fail at LOAD, not mid-run
    stop = spec.get("stop") or {}
    for key in ("max_iterations", "plateau_patience", "wall_seconds"):
        if key not in stop:
            raise RegistryError(
                f"controller {cid!r}: stop.{key} is required; a loop with no "
                f"declared stop condition is a loop")
    max_it = int(stop["max_iterations"])
    if max_it <= 0:
        raise RegistryError(f"controller {cid!r}: stop.max_iterations must be positive")
    return Controller(
        controller_id=cid, summary=str(spec.get("summary", "")),
        objective_domain=str(dom), actuator_id=str(aid),
        plan=tuple(plan), max_iterations=max_it,
        plateau_patience=int(stop["plateau_patience"]),
        wall_seconds=float(stop["wall_seconds"]),
    )


def _enum(cls, value, where: str):
    try:
        return cls(value)
    except ValueError:
        raise RegistryError(
            f"{where}: {value!r} is not one of "
            f"{[m.value for m in cls]}") from None


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

_MISSING = object()


def _json_pointer(doc: Any, pointer: str) -> Any:
    """RFC-6901 subset. Returns `_MISSING` rather than raising, because an
    absent pointer is a measurement outcome, not a programming error."""
    if pointer in ("", "/"):
        return doc
    node = doc
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            try:
                node = node[int(token)]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return node


def _render(template: str, values: Mapping[str, Any]) -> str:
    def sub(m):
        key = m.group(1)
        if key not in values:
            raise ParameterError(
                f"template {template!r} references {{{key}}}, which was not "
                f"supplied")
        return str(values[key])
    return _PLACEHOLDER_RE.sub(sub, template)


def _resolve_inside(root: Path, rel: str, what: str) -> Path:
    """Resolve `rel` under `root` and REFUSE anything that escapes it.

    The check is on the resolved path, and `root` is resolved too, so a symlink
    inside the tree cannot be used to step out of it -- which is the failure
    mode a plain `..` check misses.
    """
    root_r = Path(root).resolve()
    if os.path.isabs(rel):
        raise ParameterError(
            f"{what}: {rel!r} is absolute; a controlled action addresses paths "
            f"relative to the implementation root")
    target = (root_r / rel).resolve()
    try:
        target.relative_to(root_r)
    except ValueError:
        raise ParameterError(
            f"{what}: {rel!r} resolves to {target}, outside the implementation "
            f"root {root_r}. The blast radius the registry declares is the "
            f"blast radius the action gets.") from None
    return target


def tree_digest(root: Path) -> str:
    """A single identity for the whole implementation tree.

    Used to PROVE a rollback restored what was there: comparing the digest
    before actuation with the digest after restore is a fact, where "we called
    the restore function" is a hope. Symlinks are recorded by their target, not
    followed, so a restored tree that swapped a file for a link to it is a
    different tree and says so.
    """
    root = Path(root)
    entries: Dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            entries[rel] = "symlink:" + os.readlink(p)
        elif p.is_dir():
            entries[rel] = "dir"
        elif p.is_file():
            entries[rel] = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        else:  # pragma: no cover - fifo/socket in an implementation tree
            entries[rel] = "other"
    return cj.digest_of(entries)


def _plain(obj: Any) -> Any:
    """YAML gives tuples/dates in places; canonical_json wants plain JSON."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


# ---------------------------------------------------------------------------
# Measurement + run records
# ---------------------------------------------------------------------------

@dataclass
class Measurement:
    """One re-measurement of one domain: the canonical metric record plus the
    exit code and the marker that produced it."""

    domain: str
    metric: str
    status: str                    # MEASURED | DERIVED | NOT_MEASURED
    value: Optional[float]
    unit: str
    rc: Optional[int]
    formula: str
    reason: str = ""
    argv: Tuple[str, ...] = ()
    stdout_tail: str = ""

    def usable(self) -> bool:
        """docs/PPA_INTERFACES.md §2: only MEASURED and DERIVED may enter a
        numeric comparison. NOT_MEASURED carries a reason, never a value."""
        return self.status in ("MEASURED", "DERIVED") and self.value is not None

    def record(self, scope: Mapping[str, Any]) -> Dict[str, Any]:
        rec: Dict[str, Any] = {
            "schema": "vibeic.ppa.metric.v1",
            "metric": self.metric,
            "status": self.status,
            "unit": self.unit,
            "scope": dict(scope),
            "source": {"parser": "_ppa/closure.py",
                       "argv": list(self.argv), "rc": self.rc},
        }
        if self.usable():
            rec["value"] = self.value
            rec["formula"] = self.formula
        else:
            # No numeric sentinel. The row is PRINTED, with a reason, and it
            # carries no `value` key at all -- 0 and -1 never mean "not measured".
            rec["reason"] = self.reason or self.formula
        return rec


@dataclass
class Iteration:
    index: int
    states: List[str] = field(default_factory=list)
    proposal: Mapping[str, Any] = field(default_factory=dict)
    argv: Tuple[str, ...] = ()
    actuator_rc: Optional[int] = None
    actuator_note: str = ""
    changed_implementation: bool = False
    digest_before: str = ""
    digest_after: str = ""
    digest_restored: str = ""
    measurements: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    objective_before: Optional[float] = None
    objective_after: Optional[float] = None
    decision: str = ""
    decision_reason: str = ""


@dataclass
class ClosureRun:
    edge_id: str
    controller_id: Optional[str]
    outcome: Outcome
    reason: str
    registry_digest: str
    baseline: Optional[Dict[str, Any]] = None
    #: Every re-measured domain at baseline, not just the objective. A domain
    #: with no baseline cannot be shown to have regressed, so the collateral
    #: guard would be blind on the first iteration -- which it was, measured.
    baseline_all: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    final: Optional[Dict[str, Any]] = None
    final_all: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    iterations: List[Iteration] = field(default_factory=list)
    residual: Optional[Dict[str, Any]] = None
    promoted: int = 0
    rolled_back: int = 0
    collateral: List[Dict[str, Any]] = field(default_factory=list)
    flow_steps_not_rerun: List[str] = field(default_factory=list)

    def is_closed_loop_success(self) -> bool:
        """The ONE predicate a reporting layer may ask. There is no override.

        A collateral regression REVOKES the success even when the objective
        converged: a loop that improved its own number and left a re-measured
        neighbour worse than it found it has not closed a loop, it has moved a
        violation. `exit_code` follows this, not the other way round.
        """
        return self.outcome.is_success() and not self.collateral

    def exit_code(self) -> int:
        if self.collateral and self.outcome.exit_code() == 0:
            # The loop ran and left a domain worse. That is a finding about the
            # design, so it is 1 -- never the 0 the objective alone would give.
            return 1
        return self.outcome.exit_code()

    def to_record(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "schema": SCHEMA_RUN,
            "edge": self.edge_id,
            "controller": self.controller_id,
            "outcome": self.outcome.value,
            "closed_loop_success": self.is_closed_loop_success(),
            "reason": self.reason,
            "registry_digest": self.registry_digest,
            "baseline": self.baseline,
            "baseline_all": self.baseline_all,
            "final": self.final,
            "final_all": self.final_all,
            "residual": self.residual,
            "promoted": self.promoted,
            "rolled_back": self.rolled_back,
            "collateral_regressions": self.collateral,
            # Stated, not implied: this process re-ran the MEASUREMENTS. These
            # are the flow steps a real re-run would additionally have to
            # execute, and naming them is the difference between a limitation
            # and a lie.
            "flow_steps_not_rerun_in_process": sorted(set(self.flow_steps_not_rerun)),
            "iterations": [
                {
                    "index": it.index,
                    "states": it.states,
                    "proposal": _plain(dict(it.proposal)),
                    "argv": list(it.argv),
                    "actuator_rc": it.actuator_rc,
                    "actuator_note": it.actuator_note,
                    "changed_implementation": it.changed_implementation,
                    "digest_before": it.digest_before,
                    "digest_after": it.digest_after,
                    "digest_restored": it.digest_restored,
                    "measurements": it.measurements,
                    "objective_before": it.objective_before,
                    "objective_after": it.objective_after,
                    "decision": it.decision,
                    "decision_reason": it.decision_reason,
                }
                for it in self.iterations
            ],
        }
        body["digest"] = cj.digest_of(body)
        return body


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

class ClosureController:
    """Runs ONE declared edge to a terminal outcome.

    The constructor takes an implementation root separate from the project root
    because the snapshot/restore blast containment is over the IMPLEMENTATION,
    and a controller that snapshotted the whole project would also roll back the
    evidence of what it did.
    """

    def __init__(self, registry: Registry, impl_root: Path,
                 workdir: Path, now=time.monotonic):
        self.registry = registry
        self.impl_root = Path(impl_root).resolve()
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._now = now

    # -- measurement -------------------------------------------------------
    def measure(self, domain: Domain, tag: str) -> Measurement:
        if domain.binding is not Binding.EXECUTABLE:
            return Measurement(
                domain=domain.name, metric=domain.metric, status="NOT_MEASURED",
                value=None, unit=domain.unit, rc=None,
                formula="", reason=(
                    f"domain {domain.name!r} is DECLARED_ONLY: no measurement "
                    f"program is bound, so nothing was measured"))
        json_out = self.workdir / f"measure_{domain.name.replace('.', '_')}_{tag}.json"
        argv = domain.build_argv(self.impl_root, json_out)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=600, cwd=str(self.impl_root))
        except (OSError, subprocess.SubprocessError) as exc:
            return Measurement(
                domain=domain.name, metric=domain.metric, status="NOT_MEASURED",
                value=None, unit=domain.unit, rc=None, formula="",
                reason=f"measurement command could not be executed: {exc}",
                argv=tuple(argv))
        tail = (proc.stdout or "")[-400:]
        if proc.returncode in domain.undetermined_rcs:
            # The measurement program itself said "I could not look". Repeating
            # that honestly is the whole point; turning it into a number here
            # would launder a refusal into a fact.
            return Measurement(
                domain=domain.name, metric=domain.metric, status="NOT_MEASURED",
                value=None, unit=domain.unit, rc=proc.returncode, formula="",
                reason=(f"measurement exited {proc.returncode} (declared "
                        f"UNDETERMINED): {(proc.stderr or proc.stdout or '').strip()[-300:]}"),
                argv=tuple(argv), stdout_tail=tail)
        if not json_out.is_file():
            return Measurement(
                domain=domain.name, metric=domain.metric, status="NOT_MEASURED",
                value=None, unit=domain.unit, rc=proc.returncode, formula="",
                reason=(f"measurement exited {proc.returncode} but wrote no "
                        f"{json_out.name}; there is no document to read a "
                        f"number out of"),
                argv=tuple(argv), stdout_tail=tail)
        try:
            import json as _json
            doc = _json.loads(json_out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Measurement(
                domain=domain.name, metric=domain.metric, status="INVALID",
                value=None, unit=domain.unit, rc=proc.returncode, formula="",
                reason=f"measurement artefact exists but cannot be parsed: {exc}",
                argv=tuple(argv), stdout_tail=tail)
        value, formula = domain.extract.extract(doc)  # type: ignore[union-attr]
        if value is None:
            return Measurement(
                domain=domain.name, metric=domain.metric, status="NOT_MEASURED",
                value=None, unit=domain.unit, rc=proc.returncode, formula=formula,
                reason=f"the artefact does not carry the number: {formula}",
                argv=tuple(argv), stdout_tail=tail)
        # The number is computed FROM parsed fields, so it is DERIVED and it
        # carries its formula -- docs/PPA_INTERFACES.md §2 and §3.
        status = "DERIVED" if domain.extract.kind != "json_pointer" else "MEASURED"
        return Measurement(domain=domain.name, metric=domain.metric, status=status,
                           value=value, unit=domain.unit, rc=proc.returncode,
                           formula=formula, argv=tuple(argv), stdout_tail=tail)

    def _scope(self, tag: str) -> Dict[str, Any]:
        return {"stage": "closure_loop", "implementation_root": str(self.impl_root),
                "at": tag}

    # -- snapshot / restore -----------------------------------------------
    def _snapshot(self, index: int) -> Path:
        dest = self.workdir / f"snapshot_{index}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.impl_root, dest, symlinks=True)
        return dest

    def _restore(self, snap: Path) -> None:
        shutil.rmtree(self.impl_root)
        shutil.copytree(snap, self.impl_root, symlinks=True)

    # -- the loop ----------------------------------------------------------
    def run_edge(self, edge_id: str) -> ClosureRun:
        edge_id = str(edge_id)
        reg_digest = self.registry.digest()
        if edge_id not in self.registry.edges:
            # Not a refusal about a design: the caller named an edge the
            # registry does not carry, which is a bad invocation upstream. The
            # CLI turns this into rc=3; here it is NOT_MEASURED so that no
            # caller can read it as green.
            return ClosureRun(edge_id=edge_id, controller_id=None,
                              outcome=Outcome.NOT_MEASURED,
                              reason=f"edge {edge_id!r} is not declared in the registry",
                              registry_digest=reg_digest)
        ctl = self.registry.controller_for_edge(edge_id)
        if ctl is None:
            return ClosureRun(
                edge_id=edge_id, controller_id=None, outcome=Outcome.DECLARED_ONLY,
                reason=(f"edge {edge_id!r} is declared in the flow and has no "
                        f"executable controller. It is not a closed loop and "
                        f"must not be displayed as one."),
                registry_digest=reg_digest)
        return self.run_controller(ctl.controller_id, edge_id=edge_id)

    def run_controller(self, controller_id: str,
                       edge_id: Optional[str] = None) -> ClosureRun:
        """Run ONE controller against the implementation root.

        Separate from `run_edge` because a controller can be real and useful
        while being bound to no flow edge -- which is exactly the state of
        `pnr.deck.hold_block_emission` today, and pretending otherwise by
        inventing an edge for it is the overclaim this lane exists to prevent.
        """
        reg_digest = self.registry.digest()
        ctl = self.registry.controllers.get(controller_id)
        if ctl is None:
            return ClosureRun(
                edge_id=edge_id or "", controller_id=controller_id,
                outcome=Outcome.NOT_MEASURED,
                reason=f"controller {controller_id!r} is not declared in the registry",
                registry_digest=reg_digest)
        edge_id = edge_id if edge_id is not None else ""

        actuator = self.registry.actuators[ctl.actuator_id]
        objective = self.registry.domains[ctl.objective_domain]
        if actuator.binding is not Binding.EXECUTABLE or \
                objective.binding is not Binding.EXECUTABLE:
            return ClosureRun(
                edge_id=edge_id, controller_id=ctl.controller_id,
                outcome=Outcome.DECLARED_ONLY,
                reason=(f"controller {ctl.controller_id!r} binds actuator "
                        f"{actuator.action_id!r} ({actuator.binding.value}) and "
                        f"domain {objective.name!r} ({objective.binding.value}); "
                        f"a loop needs both EXECUTABLE"),
                registry_digest=reg_digest)

        run = ClosureRun(edge_id=edge_id, controller_id=ctl.controller_id,
                         outcome=Outcome.NOT_MEASURED, reason="",
                         registry_digest=reg_digest)
        remeasure = [self.registry.domains[d] for d in actuator.remeasure_domains]
        for d in remeasure:
            run.flow_steps_not_rerun.extend(d.flow_steps)

        # STATE: IDLE -> TRIGGER_EVALUATED
        #
        # EVERY re-measured domain is measured at baseline, not just the
        # objective. MEASURED while building this: with only the objective
        # baselined, iteration 0 of `pnr.deck.hold_block_emission` PROMOTED a
        # change that took `missing_required` from 0 to 3 -- it destroyed the
        # mandatory set_wire_rc / repair_design / repair_timing -setup chain,
        # the exact silicon-DOA shape the measurement exists to catch -- because
        # a domain with no baseline has nothing to regress FROM. A collateral
        # guard that cannot fire on the first iteration is not a guard.
        baseline_ms = {dom.name: self.measure(dom, "baseline") for dom in remeasure}
        base = baseline_ms[objective.name]
        run.baseline = base.record(self._scope("baseline"))
        run.baseline_all = {name: m.record(self._scope("baseline"))
                            for name, m in baseline_ms.items()}
        if not base.usable():
            run.outcome = Outcome.NOT_MEASURED
            run.reason = (f"the baseline could not be measured, so there is no "
                          f"claim to make in either direction: {base.reason}")
            run.final = run.baseline
            return run
        if objective.satisfied(base.value):  # type: ignore[arg-type]
            run.outcome = Outcome.NOT_TRIGGERED
            run.reason = (f"{objective.metric} = {base.value} already satisfies "
                          f"{objective.satisfied_op} {objective.satisfied_value}; "
                          f"the trigger did not fire and nothing was actuated")
            run.final = run.baseline
            return run

        current = float(base.value)  # type: ignore[arg-type]
        best_records = dict(run.baseline_all)
        started = self._now()
        stagnant = 0
        invocations = 0
        outcome: Optional[Outcome] = None
        reason = ""

        for index, proposal in enumerate(ctl.plan):
            if index >= ctl.max_iterations:
                outcome, reason = Outcome.BUDGET_EXHAUSTED, (
                    f"stop.max_iterations = {ctl.max_iterations} reached with "
                    f"{objective.metric} = {current}, still not "
                    f"{objective.satisfied_op} {objective.satisfied_value}")
                break
            if invocations >= actuator.ceilings.max_invocations_per_run:
                outcome, reason = Outcome.BUDGET_EXHAUSTED, (
                    f"actuator ceiling max_invocations_per_run = "
                    f"{actuator.ceilings.max_invocations_per_run} reached")
                break
            elapsed = self._now() - started
            if elapsed > ctl.wall_seconds:
                outcome, reason = Outcome.BUDGET_EXHAUSTED, (
                    f"stop.wall_seconds = {ctl.wall_seconds} exceeded "
                    f"({elapsed:.1f}s)")
                break

            it = Iteration(index=index, proposal=dict(proposal))
            it.states.append(State.CLASSIFIED.value)
            it.objective_before = current
            run.iterations.append(it)

            # STATE: ACTUATOR_SELECTED — bind and check preconditions.
            try:
                params = actuator.bind_params(proposal)
            except ParameterError as exc:
                it.decision, it.decision_reason = "REFUSED", str(exc)
                outcome, reason = Outcome.HANDOFF_REQUIRED, (
                    f"plan[{index}] does not satisfy the actuator's declared "
                    f"parameter schema: {exc}")
                break
            unmet = actuator.check_preconditions(self.impl_root, params)
            if unmet:
                it.decision, it.decision_reason = "REFUSED", "; ".join(unmet)
                outcome, reason = Outcome.HANDOFF_REQUIRED, (
                    f"preconditions of {actuator.action_id!r} do not hold: "
                    f"{'; '.join(unmet)}")
                break
            it.states.append(State.ACTUATOR_SELECTED.value)

            it.digest_before = tree_digest(self.impl_root)
            snap = self._snapshot(index)

            # STATE: ACTUATED
            try:
                argv = actuator.build_argv(self.impl_root, params)
            except ParameterError as exc:
                it.decision, it.decision_reason = "REFUSED", str(exc)
                outcome, reason = Outcome.HANDOFF_REQUIRED, (
                    f"the action could not be constructed within its declared "
                    f"blast radius: {exc}")
                break
            it.argv = tuple(argv)
            invocations += 1
            try:
                proc = subprocess.run(
                    argv, capture_output=True, text=True,
                    timeout=actuator.ceilings.wall_seconds,
                    cwd=str(self.impl_root))
                it.actuator_rc = proc.returncode
                it.actuator_note = (proc.stdout or proc.stderr or "").strip()[-300:]
            except subprocess.TimeoutExpired:
                it.actuator_rc = None
                it.actuator_note = (
                    f"actuator exceeded its declared wall_seconds ceiling "
                    f"({actuator.ceilings.wall_seconds}s) and was killed")
            except OSError as exc:
                it.actuator_rc = None
                it.actuator_note = f"actuator could not be executed: {exc}"
            it.states.append(State.ACTUATED.value)
            it.digest_after = tree_digest(self.impl_root)
            it.changed_implementation = it.digest_after != it.digest_before

            if it.actuator_rc != 0:
                # The actuator itself refused or died. That is a handoff, not a
                # repair and not a regression -- and whatever it left behind is
                # rolled back so the next reader sees the baseline, not a
                # half-applied action.
                self._restore(snap)
                it.digest_restored = tree_digest(self.impl_root)
                it.states.append(State.ROLLED_BACK.value)
                run.rolled_back += 1
                it.decision = "ROLLED_BACK"
                it.decision_reason = (
                    f"actuator exited {it.actuator_rc}: {it.actuator_note}")
                outcome, reason = Outcome.HANDOFF_REQUIRED, (
                    f"actuator {actuator.action_id!r} refused plan[{index}] "
                    f"(rc={it.actuator_rc}); the controller does not have an "
                    f"action for this case: {it.actuator_note}")
                break

            # STATE: REMEASURED — every domain the action can disturb.
            it.states.append(State.REMEASURED.value)
            after: Dict[str, Measurement] = {}
            for dom in remeasure:
                m = self.measure(dom, f"iter{index}")
                after[dom.name] = m
                it.measurements[dom.name] = m.record(self._scope(f"iter{index}"))

            obj_m = after[objective.name]
            it.states.append(State.JUDGED.value)
            if not obj_m.usable():
                self._restore(snap)
                it.digest_restored = tree_digest(self.impl_root)
                it.states.append(State.ROLLED_BACK.value)
                run.rolled_back += 1
                it.decision = "ROLLED_BACK"
                it.decision_reason = (
                    f"the objective could not be re-measured after the action: "
                    f"{obj_m.reason}")
                outcome, reason = Outcome.NOT_MEASURED, (
                    f"the implementation was changed and the objective could "
                    f"not be re-measured, so the effect of the action is "
                    f"unknown; the change was rolled back: {obj_m.reason}")
                break
            it.objective_after = obj_m.value

            # A regression in ANY re-measured domain rolls back, even when the
            # objective improved. That is what remeasure_domains is FOR.
            collateral: List[str] = []
            for dom in remeasure:
                if dom.name == objective.name:
                    continue
                m = after[dom.name]
                prev = best_records.get(dom.name)
                prev_value = prev.get("value") if isinstance(prev, dict) else None
                if m.usable() and isinstance(prev_value, (int, float)) \
                        and dom.regresses(float(m.value), float(prev_value)):
                    collateral.append(
                        f"{dom.metric}: {prev_value} -> {m.value} "
                        f"({dom.direction.value})")

            improved = objective.improves(float(obj_m.value), current)
            if collateral:
                self._restore(snap)
                it.digest_restored = tree_digest(self.impl_root)
                it.states.append(State.ROLLED_BACK.value)
                run.rolled_back += 1
                it.decision = "ROLLED_BACK"
                it.decision_reason = ("collateral regression: " + "; ".join(collateral))
                stagnant += 1
            elif improved:
                it.states.append(State.PROMOTED.value)
                run.promoted += 1
                it.decision = "PROMOTED"
                it.decision_reason = (
                    f"{objective.metric}: {current} -> {obj_m.value} "
                    f"({objective.direction.value})")
                current = float(obj_m.value)
                for dom in remeasure:
                    if after[dom.name].usable():
                        best_records[dom.name] = after[dom.name].record(
                            self._scope(f"iter{index}"))
                stagnant = 0
                if objective.satisfied(current):
                    outcome, reason = Outcome.CONVERGED, (
                        f"{objective.metric} = {current} now satisfies "
                        f"{objective.satisfied_op} {objective.satisfied_value}")
                    break
            else:
                # No improvement is a ROLLBACK, not a shrug: leaving a neutral
                # or worse implementation in place would make the next
                # iteration measure something nobody chose.
                self._restore(snap)
                it.digest_restored = tree_digest(self.impl_root)
                it.states.append(State.ROLLED_BACK.value)
                run.rolled_back += 1
                it.decision = "ROLLED_BACK"
                it.decision_reason = (
                    f"{objective.metric}: {current} -> {obj_m.value} is not an "
                    f"improvement ({objective.direction.value})")
                stagnant += 1

            if outcome is None and stagnant >= ctl.plateau_patience:
                outcome, reason = Outcome.PLATEAU, (
                    f"{stagnant} consecutive iterations produced no improvement "
                    f"(stop.plateau_patience = {ctl.plateau_patience}); "
                    f"{objective.metric} = {current}, still not "
                    f"{objective.satisfied_op} {objective.satisfied_value}")
                break

        if outcome is None:
            outcome, reason = (
                (Outcome.CONVERGED, f"{objective.metric} = {current} satisfies "
                                    f"{objective.satisfied_op} "
                                    f"{objective.satisfied_value}")
                if objective.satisfied(current) else
                (Outcome.BUDGET_EXHAUSTED,
                 f"the declared plan of {len(ctl.plan)} proposal(s) is exhausted "
                 f"with {objective.metric} = {current}, still not "
                 f"{objective.satisfied_op} {objective.satisfied_value}"))

        if run.iterations:
            run.iterations[-1].states.append(State.STOPPED.value)
        run.outcome = outcome
        run.reason = reason
        final_ms = {dom.name: self.measure(dom, "final") for dom in remeasure}
        final = final_ms[objective.name]
        run.final = final.record(self._scope("final"))
        run.final_all = {name: m.record(self._scope("final"))
                         for name, m in final_ms.items()}
        # A domain that finished worse than it started is stated by name, even
        # when the run is a success by its objective. A loop that improved its
        # own number and left a neighbour worse has not closed anything.
        run.collateral = []
        for dom in remeasure:
            b, f = baseline_ms[dom.name], final_ms[dom.name]
            if b.usable() and f.usable() and dom.regresses(float(f.value),
                                                           float(b.value)):
                run.collateral.append({
                    "metric": dom.metric, "unit": dom.unit,
                    "from": b.value, "to": f.value,
                    "direction": dom.direction.value,
                })
        if not outcome.is_success():
            # The residual survives into the record and into the exit code. It
            # is never summarised away, and it is stated in the SAME terms the
            # trigger used so a reader can compare them directly.
            run.residual = {
                "metric": objective.metric,
                "unit": objective.unit,
                "value": final.value if final.usable() else None,
                "status": final.status,
                "target": {"op": objective.satisfied_op,
                           "value": objective.satisfied_value},
                "satisfied": bool(final.usable()
                                  and objective.satisfied(float(final.value))),
                "visible": True,
                "note": ("this violation was NOT repaired by the controller and "
                         "remains open"),
            }
        return run
