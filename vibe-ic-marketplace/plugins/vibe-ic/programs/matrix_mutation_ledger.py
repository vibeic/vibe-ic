#!/usr/bin/env python3
"""matrix_mutation_ledger.py — a cell may not be called ENFORCED until a NAMED,
RUNNABLE mutation has been shown to turn it red.

    "63 steps x 8 dimensions, 481 ENFORCED cells" is a claim about the
    repository. A green run is evidence for it only if a red run were
    POSSIBLE. This module carries, per cell, the mutation that makes the
    red happen — and the machinery that re-executes it rather than
    believing it.

====================================================================
WHY THIS EXISTS (and why the 504-cell coverage meta-test is not enough)
====================================================================
``programs/tests/test_matrix_63x8_coverage.py`` already proves every cell has a
real, collected, non-skipping pytest item in a known state. Its own docstring
says plainly what it does NOT prove: *"``ENFORCED`` here means the module says
this cell's live predicate runs and passes. It does not mean the predicate would
catch every defect of that kind."*

That gap is the whole disease this campaign was opened against. A predicate that
no mutation can move is a certificate, not a measurement, and 481 of them
compose into a headline nobody can falsify. So this ledger asks the one question
the coverage census cannot: **name the change to this repository that makes this
cell fail, and show it doing so.**

Second, the flow grows. The flow-gate page says
``流程長一個步驟，覆蓋就自動變不完整`` — "grow the flow by one step and coverage
automatically becomes incomplete". As a sentence that is a description. What
makes it a *stop* is that :data:`MUTATIONS` records the step ids each mutation
was MEASURED against, as a frozen list, so a 64th step arrives owning eight
cells that no measured mutation covers, and
``programs/tests/test_matrix_mutation_ledger.py`` reddens by name the same
minute the yaml changes. A registry that derived its own applicability
("every step with a gate") would swallow the new step in silence and put the
sentence back to being a description.

====================================================================
HOW "NEVER EXECUTED" IS REFUSED — THE DESIGN DECISION, AND WHY
====================================================================
The requirement is that the gate must NOT be satisfiable by adding a mutation
entry that was never run. A registry is data, and data can be typed. Three
independent locks are applied, because each one alone is forgeable and they fail
in different directions:

**LOCK 1 — the recipe must RESOLVE against the live tree, per step.**
Every entry is a machine-executable edit, not prose: a ``kind`` from
:data:`KINDS` plus parameters. :func:`resolve` re-derives the edit site from the
CURRENT flow yaml (or the current program source) for every step the entry
claims, and an entry naming a step that has no such site is refused. This is
what kills the cheap forgery — most families are structurally narrow.
``D2-BLIND-GATE-PROGRAMS`` needs the step to declare an executable gate clause
(10 of 63 do not); ``D1-UNREACHABLE-CLAUSE`` needs a ``files_exist`` key (32 do
not); ``D4-PROSE-NAMES-A-GHOST`` needs a ``notes`` string. You cannot widen an
entry to a step whose gate is the wrong shape, and the widening is refused at
import-speed with no test run at all.

**LOCK 2 — REPLAY. The ledger's word is not taken for the redness.**
Every entry nominates a ``witness`` step, and :func:`replay` performs the edit
FOR REAL — on an isolated copy, never the worktree — and runs that one cell
through pytest twice: unmutated (must PASS) and mutated (must FAIL, with the
declared :attr:`Mutation.red_signal` present in the failure text). The gate does
this on every witness on every run. An entry for a mutation that cannot actually
redden anything dies here, and it dies whether the author lied, mis-measured, or
was simply overtaken by a refactor six months later.
``VIBE_IC_MATRIX_MUTATION_REPLAY=all`` replays every (entry, step) pair in the
ledger — the audit-grade mode, minutes not seconds.

**LOCK 3 — the evidence must be arithmetically consistent with itself.**
:class:`Measurement` carries the date, the exact pytest node template, the
number of cells the sweep reddened, and the cells that were ALREADY red before
the mutation (redness there is not attributable to it). ``reddened`` must equal
``len(applies_to)`` and ``baseline_red`` must be a subset of it. A fabricator
who widens ``applies_to`` must also alter a count and a subset — a lie about a
number in a diff, rather than an omission nobody sees.

**WHY NOT "just replay everything, always".** Because it costs minutes, and a
gate people disable is worse than a gate that states its own reach. So the reach
is stated: LOCK 1 and LOCK 3 are structural and cover all 481 cells on every
run; LOCK 2 is proof and by default covers one witness per entry. Both numbers
are reported by :func:`census`, and the test asserts them rather than letting a
reader assume the stronger one.

MEASURED 2026-08-06, so nobody has to take the modes on trust:

  * default (``witness``) — 16 of 16 entries REDDENED their witness,
    ``95 passed in 119.43s`` for the whole gate file at ``jobs=8``;
  * audit (``all``) run for two entries in full — ``D5-PHANTOM-EDGE`` 62/62
    steps REDDENED, ``D8-EMPTY-PROMISE`` 61/61 steps REDDENED, 0 failures. The
    remaining 14 entries' ``applies_to`` sets come from the same per-step sweep
    machinery and are re-checkable with one command each.

BIDIRECTIONAL CONTROL, MEASURED. The gate file was run against a PRE-GATE copy
of this tree — the ledger present but ``MUTATIONS = ()``, i.e. the repository as
it was before any cell carried a mutation — and against the real tree:

    pre-gate copy (MUTATIONS emptied)   72 failed, 5 passed
    this tree                           95 passed

The five that survive the pre-gate copy are the properties that genuinely do not
depend on the ledger's contents (the grid-size review gate, the WAIVED/NA
reverse case, canary hygiene, NOT-FALSIFIABLE hygiene, and the structural check
that the ledger forms no second opinion about cell state). The WAIVED/NA reverse
case passing in BOTH directions is the point: this gate must be silent about
cells it does not speak for.

====================================================================
NOT-FALSIFIABLE IS A VERDICT, NOT AN ERROR
====================================================================
A cell for which no mutation could be constructed is recorded in
:data:`NOT_FALSIFIABLE` with the shapes that were tried and what each did
instead. It is the FINDING, and the test reports it loudly. It is never a reason
to weaken a predicate, widen a waiver, or edit a fixture. The empty list is itself
asserted, so a future entry has to be added deliberately.

DO NOT READ AN EMPTY :data:`NOT_FALSIFIABLE` AS "ALL 481 ARE COVERED". This
docstring said exactly that on 2026-08-06 — "every one of the 481 ENFORCED cells
was reddened by at least one executed mutation" — while the same module's own
stdout on the same commit read `d3: 53/63`, `d7: 58/63`, `d2: 59/63`. Both cannot
be true. An independent verifier defeated the coverage claim WITHOUT running a
mutation, purely by reading those two numbers against each other, and was right
to: an empty NOT_FALSIFIABLE means only that no cell was PROVEN unfalsifiable —
a cell with no entry at all was never put to the question. The per-dimension
counts printed on every run are the honest coverage; this list is the honest
failure record. They answer different questions and the gap between them is the
work left to do.

====================================================================
HONEST BOUNDARY
====================================================================
  * A mutation proves the cell is CONNECTED to something. It does not prove the
    predicate is strong. ``D5-PHANTOM-EDGE`` proves step 21's dimension-5 cell
    notices an unresolvable parent; it says nothing about whether it would
    notice a genuinely missing edge. Predicate strength stays each dimension
    module's own problem, documented in its KNOWN GAP section.
  * 13 cells at 1ea6689b are ALREADY red (11 dimension-3 cells whose declared
    artefacts genuinely do not exist, the dimension-3 waived-step aggregate, and
    dimension 4 step 1). An already-red cell is falsifiable by definition and is
    recorded in each measurement's ``baseline_red``; the mutation's *attributable*
    count excludes them, and no witness may be one of them.
  * The ledger measures the eight dimension modules as they stand. It cannot
    tell you that a ninth dimension is missing — that is the coverage census's
    job, and it is asserted there.

USAGE
-----
    matrix_mutation_ledger.py --census
    matrix_mutation_ledger.py --resolve              # LOCK 1 over every entry
    matrix_mutation_ledger.py --replay D5-PHANTOM-EDGE [--step 21]
    matrix_mutation_ledger.py --replay-witnesses [--jobs 8]
    matrix_mutation_ledger.py --emit-flow D5-PHANTOM-EDGE --step 21 --out f.yaml
    matrix_mutation_ledger.py --json out.json

EXIT CODES
----------
    0 = every requested check passed
    1 = a finding (an entry did not resolve, or a replay did not redden)
    2 = usage / io error
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a hard dep of the plugin
    yaml = None  # type: ignore


# ══════════════════════════════════════════════════════════════════════
# Where the tree is
# ══════════════════════════════════════════════════════════════════════
PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
FLOW_REL = Path("flow") / "phase1_phase2_phase3.yaml"

#: The same override the eight dimension modules honour. Set it and this module
#: reads the substituted flow — which is exactly how the "flow grew a step"
#: control is driven, and how every yaml-side replay feeds its mutant in.
FLOW_YAML_ENV = "VIBE_IC_MATRIX_FLOW_YAML"

#: ``witness`` (default) replays one nominated (entry, step) per entry;
#: ``all`` replays every (entry, step) pair the ledger claims.
REPLAY_ENV = "VIBE_IC_MATRIX_MUTATION_REPLAY"
REPLAY_MODES = ("witness", "all")

#: Paths and identifiers a mutation plants. They must NOT exist anywhere in the
#: tree — a canary that collides with a real artefact would make a mutation red
#: for the wrong reason. Asserted by the test.
CANARY_PATH = "reports/zzmatrixcanary/zzmatrixcanary_probe.json"
CANARY_RTL = "phase2/stage1/rtl/zzmatrixcanary_shadow.v"
CANARY_PROGRAM = "zzmatrixcanary_orphan_check"
CANARY_SUFFIX = "_MUTANT"
CANARY_FLAG = "--matrix-mutation-canary"
CANARY_TOKENS: Tuple[str, ...] = (
    CANARY_PATH, CANARY_RTL, CANARY_PROGRAM, CANARY_FLAG, "zzmatrixcanary")


def flow_yaml_path() -> Path:
    override = os.environ.get(FLOW_YAML_ENV)
    return Path(override) if override else PLUGIN_ROOT / FLOW_REL


def load_flow(path: Optional[Path] = None) -> Dict[str, Any]:
    """The flow document, freshly parsed. Never cached — replays swap the file."""
    if yaml is None:  # pragma: no cover - defensive
        raise RuntimeError("PyYAML is required to read the flow")
    return yaml.safe_load((path or flow_yaml_path()).read_text(encoding="utf-8"))


def step_ids(doc: Optional[Dict[str, Any]] = None) -> Tuple[str, ...]:
    """Declared step ids, normalised to ``str``, in declaration order."""
    doc = doc if doc is not None else load_flow()
    return tuple(str(s.get("id")) for s in (doc.get("steps") or []))


def step_by_id(doc: Dict[str, Any], sid: str) -> Optional[Dict[str, Any]]:
    for s in doc.get("steps") or []:
        if str(s.get("id")) == str(sid):
            return s
    return None


# ══════════════════════════════════════════════════════════════════════
# The cell tests each dimension owns
# ══════════════════════════════════════════════════════════════════════
#: ``{dim: (module filename, cell test function)}`` — the pytest node a replay
#: runs. DERIVED nowhere: it is the address of the thing being falsified, and if
#: a module renames its sweep the replay fails to collect and the gate says so
#: (rather than silently measuring zero cells).
CELL_TESTS: Dict[int, Tuple[str, str]] = {
    1: ("test_matrix_d1_wiring.py", "test_d1_gate_is_wired_in"),
    2: ("test_matrix_d2_falsifiable.py", "test_d2_gate_has_a_reachable_fail"),
    3: ("test_matrix_d3_outputs_produced.py", "test_d3_required_outputs_are_produced"),
    4: ("test_matrix_d4_criteria_match.py", "test_d4_gate_measures_what_it_claims"),
    5: ("test_matrix_d5_deps_correct.py",
        "test_d5_blocks_on_covers_the_real_dependency_graph"),
    6: ("test_matrix_d6_skip_discipline.py", "test_d6_skip_discipline"),
    7: ("test_matrix_d7_outputs_list_complete.py",
        "test_d7_required_outputs_list_is_complete"),
    8: ("test_matrix_d8_missing_caught.py", "test_d8_missing_caught"),
}

TESTS_REL = Path("programs") / "tests"


def cell_nodeid(dim: int, sid: str) -> str:
    fname, func = CELL_TESTS[dim]
    return f"{(TESTS_REL / fname).as_posix()}::{func}[step{sid}]"


# ══════════════════════════════════════════════════════════════════════
# The two mutation channels
# ══════════════════════════════════════════════════════════════════════
FLOW_YAML = "FLOW_YAML"      # edit the flow document; replay via FLOW_YAML_ENV
PLUGIN_TREE = "PLUGIN_TREE"  # edit a file; replay in a hardlink mirror

CHANNELS = (FLOW_YAML, PLUGIN_TREE)

_EXEC_KEYS = ("program_exit_zero", "advisory_program_exit_zero",
              "optional_program_exit_zero", "program_exit_zero_any_of")


def _exec_clauses(node: Any, out: List[Tuple[Dict, str, Any]]) -> None:
    """Every ``(owning dict, key, value)`` triple that spells an executable."""
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k in _EXEC_KEYS:
                out.append((node, k, v))
            else:
                _exec_clauses(v, out)
    elif isinstance(node, list):
        for v in node:
            _exec_clauses(v, out)


def _holders_of(node: Any, key: str, out: List[Dict]) -> None:
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k == key:
                out.append(node)
            _holders_of(v, key, out)
    elif isinstance(node, list):
        for v in node:
            _holders_of(v, key, out)


def _command_of(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        return value["command"]
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _rename_program(value: Any, owner: Dict, key: str) -> int:
    """Suffix the program token of one clause. Returns how many it renamed."""
    if isinstance(value, str):
        toks = value.split()
        toks[0] += CANARY_SUFFIX
        owner[key] = " ".join(toks)
        return 1
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        toks = value["command"].split()
        toks[0] += CANARY_SUFFIX
        value["command"] = " ".join(toks)
        return 1
    if isinstance(value, list):
        n = 0
        for i, item in enumerate(value):
            if isinstance(item, str):
                toks = item.split()
                toks[0] += CANARY_SUFFIX
                value[i] = " ".join(toks)
                n += 1
        return n
    return 0


# ---------------------------------------------------------------------
# The edit kinds. Each returns True when it applied, False when the step
# has no such edit site — which is LOCK 1's whole implementation.
# ---------------------------------------------------------------------
def _k_gate_progs_rename(step: Dict, _p: Dict) -> bool:
    clauses: List[Tuple[Dict, str, Any]] = []
    _exec_clauses(step.get("gate"), clauses)
    return sum(_rename_program(v, o, k) for o, k, v in clauses) > 0


def _k_gate_clause_key_rename(step: Dict, _p: Dict) -> bool:
    holders: List[Dict] = []
    _holders_of(step.get("gate"), "files_exist", holders)
    if not holders:
        return False
    holders[0]["files_exist" + CANARY_SUFFIX] = holders[0].pop("files_exist")
    return True


def _k_gate_append_files_exist(step: Dict, _p: Dict) -> bool:
    gate = step.get("gate")
    if not isinstance(gate, dict):
        return False
    clause = {"files_exist": [CANARY_PATH]}
    if isinstance(gate.get("all_of"), list):
        gate["all_of"].append(clause)
    else:
        step["gate"] = {"all_of": [dict(gate), clause]}
    return True


def _k_gate_append_unconditional_optional(step: Dict, params: Dict) -> bool:
    gate = step.get("gate")
    if not isinstance(gate, dict):
        return False
    clause = {"optional_program_exit_zero": {"command": params["command"]}}
    if isinstance(gate.get("all_of"), list):
        gate["all_of"].append(clause)
    else:
        step["gate"] = {"all_of": [dict(gate), clause]}
    return True


def _k_gate_advisory_only(step: Dict, _p: Dict) -> bool:
    clauses: List[Tuple[Dict, str, Any]] = []
    _exec_clauses(step.get("gate"), clauses)
    for _, _, v in clauses:
        cmd = _command_of(v)
        if cmd:
            step["gate"] = {"all_of": [{"advisory_program_exit_zero": cmd}]}
            return True
    return False


def _k_gate_append_cli_flag(step: Dict, _p: Dict) -> bool:
    clauses: List[Tuple[Dict, str, Any]] = []
    _exec_clauses(step.get("gate"), clauses)
    for owner, key, v in clauses:
        if isinstance(v, str):
            owner[key] = v + f" {CANARY_FLAG} 1"
            return True
    return False


def _k_required_outputs_append(step: Dict, _p: Dict) -> bool:
    ro = step.get("required_outputs")
    if not isinstance(ro, list) or not ro:
        return False
    ro.append(CANARY_PATH)
    return True


def _k_required_outputs_rename_first(step: Dict, _p: Dict) -> bool:
    ro = step.get("required_outputs")
    if not isinstance(ro, list) or not ro:
        return False
    ro[0] = CANARY_PATH
    return True


def _k_required_outputs_empty(step: Dict, _p: Dict) -> bool:
    if not isinstance(step.get("required_outputs"), list):
        return False
    step["required_outputs"] = []
    return True


def _k_required_outputs_delete_key(step: Dict, _p: Dict) -> bool:
    if "required_outputs" not in step:
        return False
    del step["required_outputs"]
    return True


def _k_blocks_on_append_phantom(step: Dict, _p: Dict) -> bool:
    bo = step.get("blocks_on")
    if not isinstance(bo, list):
        return False
    bo.append("__PHANTOM" + CANARY_SUFFIX + "__")
    return True


def _k_notes_append_ghost_program(step: Dict, _p: Dict) -> bool:
    notes = step.get("notes")
    if not isinstance(notes, str):
        return False
    step["notes"] = notes + f"\nIndividual gate `{CANARY_PROGRAM}` also runs here.\n"
    return True


#: ``kind -> editor``. FLOW_YAML editors take ``(step dict, params)`` and mutate
#: in place; PLUGIN_TREE editors are handled by :func:`_apply_tree` instead.
YAML_KINDS: Dict[str, Callable[[Dict, Dict], bool]] = {
    "gate_programs_rename": _k_gate_progs_rename,
    "gate_clause_key_rename": _k_gate_clause_key_rename,
    "gate_append_files_exist_clause": _k_gate_append_files_exist,
    "gate_append_unconditional_optional": _k_gate_append_unconditional_optional,
    "gate_advisory_only": _k_gate_advisory_only,
    "gate_append_cli_flag": _k_gate_append_cli_flag,
    "required_outputs_append": _k_required_outputs_append,
    "required_outputs_rename_first": _k_required_outputs_rename_first,
    "required_outputs_empty": _k_required_outputs_empty,
    "required_outputs_delete_key": _k_required_outputs_delete_key,
    "blocks_on_append_phantom": _k_blocks_on_append_phantom,
    "notes_append_ghost_program": _k_notes_append_ghost_program,
}

#: A PLUGIN_TREE entry inserts ``params['insert']`` immediately before
#: ``params['anchor']``, which must occur EXACTLY ONCE in ``params['file']``.
#: The uniqueness requirement is the resolution check: a refactor that moves or
#: duplicates the anchor makes the entry unresolvable rather than silently
#: patching the wrong place.
TREE_KINDS: Tuple[str, ...] = ("insert_before_anchor",)

KINDS: Tuple[str, ...] = tuple(sorted(YAML_KINDS)) + TREE_KINDS


# ══════════════════════════════════════════════════════════════════════
# The records
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Measurement:
    """What was actually run, and what it produced. LOCK 3's input."""

    date: str
    #: The sweep that produced ``applies_to``, as a runnable command.
    command: str
    #: How many cells the sweep turned red. Must equal ``len(applies_to)``.
    reddened: int
    #: Cells already failing BEFORE the mutation, so their redness is not
    #: attributable to it. Must be a subset of ``applies_to``.
    baseline_red: Tuple[str, ...] = ()
    #: Steps the sweep touched that did NOT go red, recorded so the entry's
    #: reach is a measured fact rather than a rounded-up one.
    stayed_green: Tuple[str, ...] = ()
    note: str = ""

    @property
    def attributable(self) -> int:
        return self.reddened - len(self.baseline_red)


@dataclass(frozen=True)
class Mutation:
    """One named, runnable change that is known to redden a set of cells."""

    name: str
    dim: int
    channel: str
    kind: str
    #: One line: the edit, in terms someone can perform by hand.
    what: str
    #: The real defect this edit simulates. Why reddening is the RIGHT answer.
    breaks: str
    #: A substring the reddened cell's failure text must contain. Guards against
    #: a replay that goes red for an unrelated reason (an import error, say).
    red_signal: str
    #: The step replayed on EVERY run. Must be in ``applies_to`` and must be
    #: green at baseline.
    witness: str
    #: The steps this mutation was MEASURED to redden. FROZEN on purpose: a new
    #: flow step is not in it, so its cells are uncovered and the gate says so.
    applies_to: Tuple[str, ...]
    measured: Measurement
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"d{self.dim}:{self.name}"

    def covers(self, sid: str) -> bool:
        return str(sid) in self.applies_to


@dataclass(frozen=True)
class NotFalsifiable:
    """A cell no constructed mutation could redden. THE FINDING."""

    step_id: str
    dim: int
    tried: Tuple[str, ...]
    observed: str

    @property
    def key(self) -> Tuple[str, int]:
        return (str(self.step_id), self.dim)


# ══════════════════════════════════════════════════════════════════════
# THE LEDGER
# ══════════════════════════════════════════════════════════════════════
# Every entry below was executed on 2026-08-06 against the tree at 1ea6689b, on
# an isolated copy, with the per-step blast radius asserted (`steps_changed ==
# [target]`) and with a negative control run first: a pure
# `yaml.safe_load -> safe_dump` round-trip of the flow, fed through
# VIBE_IC_MATRIX_FLOW_YAML, reproduced the baseline verdict of all 504 cells
# (13 red before, the same 13 red after; the only two extra reds are the two
# modules' own "the override is set" self-guards, which are guards and not
# cells). So no redness recorded here is an artefact of re-serialising the yaml.
_SWEEP = ("matrix_mutation_ledger.py --replay {name} --step <each declared "
          "flow step>   (2026-08-06, 63 steps, one pytest run per step)")

MUTATIONS: Tuple[Mutation, ...] = (
    # ---------------- dimension 1 — wiring -----------------------------
    Mutation(
        name="D1-BLIND-GATE-PROGRAMS",
        dim=1, channel=FLOW_YAML, kind="gate_programs_rename",
        what="suffix the program token of EVERY executable clause in the step's "
             "gate with _MUTANT, so the gate names checkers that do not exist",
        breaks="the wire between the flow yaml and programs/. This is the shape "
               "a rename or a delete leaves behind: the step still declares a "
               "gate, and nothing on the other end answers to it.",
        red_signal="step",
        witness="21",
        applies_to=(
            "D1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "FS1",
            "DT1", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2", "DT3",
            "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
            "34", "35", "36", "37", "38", "39", "M1", "M2", "M3", "M4", "40",
            "41", "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=60,
            stayed_green=(),
            note="3 steps have no executable gate clause at all and are "
                 "structurally out of this entry's reach: 1 and 12 (files_exist "
                 "only) and P0 (no gate key). They are covered by "
                 "D1-UNREACHABLE-CLAUSE and D1-ORPHAN-UMBRELLA-GATE."),
    ),
    Mutation(
        name="D1-UNREACHABLE-CLAUSE",
        dim=1, channel=FLOW_YAML, kind="gate_clause_key_rename",
        what="rename the gate's `files_exist` KEY to `files_exist_MUTANT`, so "
             "the clause is still written down and is dispatched by nothing",
        breaks="a gate clause that survives a schema change in name only. The "
               "step reads as gated; the evaluator walks past it.",
        red_signal="step",
        witness="21",
        applies_to=("1", "4", "5", "6", "7", "9", "10", "11", "12", "A1", "A2",
                    "A3", "A4", "A5", "A7", "15", "17", "18", "19", "20", "21",
                    "22", "23", "27", "28", "29", "30", "32", "34", "37"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=30,
            stayed_green=("35",),
            note="carries steps 1 and 12, whose program-free gates put legs 1 "
                 "and 3 of the dimension-1 cell out of reach; step 35 keeps a "
                 "second reachable channel and stayed green, which is why its "
                 "green is recorded rather than rounded away."),
    ),
    Mutation(
        name="D1-ORPHAN-UMBRELLA-GATE",
        dim=1, channel=PLUGIN_TREE, kind="insert_before_anchor",
        what="add a registry entry with no backing program to "
             "`_STRUCTURAL_RTL_GATES` in programs/flow_compliance_check.py",
        breaks="the P0 umbrella advertising a checker it cannot dispatch — the "
               "exact shape mutation proof 4/5 in the dimension-1 module's own "
               "docstring names, and the only channel P0 has (it declares no "
               "gate key, so no yaml edit can reach its cell).",
        red_signal=CANARY_PROGRAM,
        witness="P0",
        applies_to=("P0",),
        params={
            "file": "programs/flow_compliance_check.py",
            "anchor": "_STRUCTURAL_RTL_GATES: tuple[str, ...] = (\n",
            "insert_after": True,
            "insert": f'    "{CANARY_PROGRAM}",\n',
        },
        measured=Measurement(
            date="2026-08-06",
            command="matrix_mutation_ledger.py --replay D1-ORPHAN-UMBRELLA-GATE",
            reddened=1,
            note="run in a `cp -al` hardlink mirror with unlink-then-write, so "
                 "the shared worktree is never written; the unmutated mirror was "
                 "run first and the cell passed."),
    ),

    # ---------------- dimension 2 — falsifiable ------------------------
    Mutation(
        name="D2-BLIND-GATE-PROGRAMS",
        dim=2, channel=FLOW_YAML, kind="gate_programs_rename",
        what="suffix the program token of EVERY executable clause in the step's "
             "gate with _MUTANT",
        breaks="THE DISEASE ITSELF for this dimension: a gate that currently "
               "reaches a real, content-earned FAIL becomes one that can only "
               "reach PROGRAM_NOT_FOUND. The cell's own words for it are 'step "
               "K gate CANNOT FAIL on anything a project DID'.",
        red_signal="CANNOT FAIL",
        witness="21",
        applies_to=(
            "D1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "FS1",
            "DT1", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2", "DT3",
            "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
            "34", "36", "37", "38", "39", "M1", "M2", "M3", "M4", "40", "41",
            "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=59,
            stayed_green=("35",),
            note="59 red = every one of dimension 2's 59 ENFORCED cells, in one "
                 "sweep. The 3 waived cells (1, 12, 35) and the NA cell (P0) "
                 "are the only steps not reddened: 1/12/P0 have no executable "
                 "clause to blind, and 35's gate is files_exist + advisory, "
                 "which is precisely why it is waived."),
    ),

    # ---------------- dimension 3 — outputs produced -------------------
    Mutation(
        name="D3-UNDECLARED-ARTEFACT",
        dim=3, channel=FLOW_YAML, kind="required_outputs_rename_first",
        what="rewrite the step's FIRST required_outputs entry to a path nothing "
             "in the repository produces",
        breaks="a declared deliverable that no run root contains. Same shape as "
               "deleting the artefact, reached from the declaration end — which "
               "is the end a CI host without the campaign's run trees can move.",
        red_signal="step",
        witness="21",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "7", "8", "9", "10", "11", "DT1",
            "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2", "DT3",
            "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
            "34", "35", "36", "37", "38", "M2", "M3", "M4"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=53,
            baseline_red=("11", "15", "17", "19", "20", "29", "30", "32",
                          "M2", "M3", "M4"),
            stayed_green=("6", "39", "M1"),
            note="53 red = every one of dimension 3's 53 ENFORCED cells. 11 of "
                 "them were ALREADY red at 1ea6689b (their declared artefacts "
                 "genuinely do not exist), so 42 reds are attributable to this "
                 "mutation; the 11 are falsifiable by definition and are named "
                 "here rather than counted twice. The 3 greens are the waived "
                 "cells, whose strict xfail correctly held."),
    ),

    # ---------------- dimension 4 — criteria match ---------------------
    Mutation(
        name="D4-UNGATED-DELIVERABLE",
        dim=4, channel=FLOW_YAML, kind="required_outputs_append",
        what="append one entry to the step's required_outputs that no clause of "
             "its gate reads",
        breaks="the step claiming a deliverable its own gate does not measure — "
               "the precise mismatch dimension 4 exists to report, arrived at "
               "from the claim side.",
        red_signal="required_outputs",
        witness="21",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
            "DT1", "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
            "A9", "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2",
            "DT3", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32",
            "33", "34", "35", "36", "37", "38", "39", "M1", "M2", "M3", "M4",
            "40", "41", "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=61,
            baseline_red=("1",),
            note="the 2 steps not reached declare no required_outputs at all "
                 "(FS1, P0) and are carried by D4-CLI-CONTRACT and "
                 "D4-PROSE-NAMES-A-GHOST."),
    ),
    Mutation(
        name="D4-CLI-CONTRACT",
        dim=4, channel=FLOW_YAML, kind="gate_append_cli_flag",
        what="append an unrecognised flag to the step's first string-valued "
             "gate command",
        breaks="a gate whose program exits 2 on argv it does not understand "
               "while the flow keeps reading the clause as satisfied — the "
               "rc==2 -> VACUOUS_PASS defect, reached from the gate side.",
        red_signal="step",
        witness="FS1",
        applies_to=("2", "3", "5", "6", "7", "8", "9", "10", "11", "FS1",
                    "DT1", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
                    "A8", "A9", "17", "19", "20", "22", "DT2", "DT3", "23",
                    "24", "25", "26", "28", "29", "30", "31", "34", "35", "36",
                    "37", "38", "39", "M1", "M2", "M3", "M4", "40", "41", "42",
                    "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=50,
            stayed_green=("D1", "21", "33"),
            note="carries FS1, the one step with a gate and no required_outputs. "
                 "D1/21/33 stayed green because their first clause's program "
                 "hardens or hand-rolls argv — recorded, not rounded away; the "
                 "dimension-4 census reached them at clause #1 instead."),
    ),
    Mutation(
        name="D4-PROSE-NAMES-A-GHOST",
        dim=4, channel=FLOW_YAML, kind="notes_append_ghost_program",
        what="add a backticked checker name to the step's `notes` that the live "
             "structural-gate registry does not contain",
        breaks="the umbrella step's prose advertising a gate that does not "
               "exist. P0 declares no gate and no required_outputs, so its "
               "notes are the only surface a yaml edit can move.",
        red_signal=CANARY_PROGRAM,
        witness="P0",
        applies_to=("P0",),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=1,
            stayed_green=("FS1", "DT1", "A5", "A6", "18", "22", "DT2", "DT3",
                          "38", "M1", "M2", "40", "43", "44"),
            note="deliberately narrow: only P0's cell checks its notes against "
                 "the live registry (`_STRUCTURAL_RTL_GATES`, 246 members, read "
                 "by live import). 14 other steps carry notes and stayed green; "
                 "that is the correct answer for them and it is recorded."),
    ),

    # ---------------- dimension 5 — deps correct -----------------------
    Mutation(
        name="D5-PHANTOM-EDGE",
        dim=5, channel=FLOW_YAML, kind="blocks_on_append_phantom",
        what="append a step id that does not exist to the step's blocks_on",
        breaks="a dependency edge that resolves to nothing — what a rename or a "
               "deletion upstream leaves behind, and the state in which the "
               "runtime ordering guard silently stops constraining the step.",
        red_signal="step",
        witness="21",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
            "FS1", "DT1", "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
            "A8", "A9", "14", "15", "16", "17", "18", "19", "20", "21", "22",
            "DT2", "DT3", "23", "24", "25", "26", "27", "28", "29", "30", "31",
            "32", "33", "34", "35", "36", "37", "38", "39", "M1", "M2", "M3",
            "M4", "40", "41", "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=62,
            note="62 red = every one of dimension 5's 62 ENFORCED cells, in one "
                 "sweep, each reddening that cell alone. P0 is the single NA "
                 "cell and declares no blocks_on key to append to."),
    ),

    # ---------------- dimension 6 — skip discipline --------------------
    Mutation(
        name="D6-UNCONDITIONAL-OPTIONAL",
        dim=6, channel=FLOW_YAML, kind="gate_append_unconditional_optional",
        what="append an `optional_program_exit_zero` clause with NO "
             "`condition_files_exist`, i.e. a gate clause switched off by "
             "declaration rather than by a condition anything can check",
        breaks="a gate that is optional always, which is a skip nobody has to "
               "disclose because nobody wrote the word skip.",
        red_signal="step",
        witness="21",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
            "FS1", "DT1", "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
            "A8", "A9", "14", "15", "16", "17", "18", "19", "20", "21", "22",
            "DT3", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32",
            "33", "34", "35", "36", "37", "38", "39", "M1", "M2", "M3", "M4",
            "40", "41", "42", "43", "44"),
        params={"command":
                "clock_plan_check . --json reports/phase2/gates/zzmatrixcanary.json"},
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=61,
            stayed_green=("DT2",),
            note="61 red = every ENFORCED dimension-6 cell except P0, which "
                 "declares no gate to append to and is carried by "
                 "D6-UMBRELLA-ALWAYS-SKIPS. DT2 is the one waived cell and its "
                 "strict xfail correctly held."),
    ),
    Mutation(
        name="D6-ADVISORY-ONLY-GATE",
        dim=6, channel=FLOW_YAML, kind="gate_advisory_only",
        what="replace the step's whole gate with a single "
             "`advisory_program_exit_zero` running that step's own first gate "
             "command",
        breaks="the break the dimension-6 module's docstring names: the gate "
               "passes with no blocking clause and no disclosure prefix, so a "
               "step that measures nothing is counted as a step that passed.",
        red_signal="step",
        witness="21",
        applies_to=(
            "D1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "FS1",
            "DT1", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT3", "23",
            "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34",
            "35", "36", "37", "38", "39", "M1", "M2", "M3", "M4", "40", "41",
            "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=59,
            stayed_green=("DT2",),
            note="a second, independent lever on 59 of the same cells; kept "
                 "because it charges a different leg (L1b) than "
                 "D6-UNCONDITIONAL-OPTIONAL (L4), so a change that blinds one "
                 "leg does not blind the dimension."),
    ),
    Mutation(
        name="D6-UMBRELLA-ALWAYS-SKIPS",
        dim=6, channel=PLUGIN_TREE, kind="insert_before_anchor",
        what="hoist `_run_structural_rtl_gates`'s no-RTL early return to the "
             "top of the function, so the P0 umbrella skips on every input",
        breaks="a skip taken unconditionally while still being reported as "
               "SKIPPED-CONDITION. The cell's own words: 'L2 SKIP NOT SHOWN "
               "CONDITIONAL: every constructed input resolves this step to a "
               "skip tier'.",
        red_signal="L2 SKIP NOT SHOWN CONDITIONAL",
        witness="P0",
        applies_to=("P0",),
        params={
            "file": "programs/flow_compliance_check.py",
            "anchor": "    # Compute thin-input eligibility once. Only matters "
                      "when the flag\n",
            "insert": "    return None, [], [_P0_NO_RTL_NOTE], []  "
                      "# D6-UMBRELLA-ALWAYS-SKIPS\n",
        },
        measured=Measurement(
            date="2026-08-06",
            command="matrix_mutation_ledger.py --replay D6-UMBRELLA-ALWAYS-SKIPS",
            reddened=1,
            note="hardlink mirror, unlink-then-write; the unmutated mirror was "
                 "run first and stepP0 passed in 43.05s."),
    ),

    # ---------------- dimension 7 — outputs list complete --------------
    Mutation(
        name="D7-GATE-PROBES-A-GHOST",
        dim=7, channel=FLOW_YAML, kind="gate_append_files_exist_clause",
        what="append a `files_exist` clause to the step's gate naming a file no "
             "step's required_outputs declares",
        breaks="rule W3 — the step's own gate asserts a file exists and no step "
               "promises to produce it. That artefact is load-bearing and "
               "invisible to the flow's own accounting.",
        red_signal="W3",
        witness="21",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "6", "8", "9", "10", "11", "DT1",
            "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2", "DT3",
            "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34",
            "35", "36", "37", "38", "39", "M2", "M3", "M4", "40", "41", "42",
            "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=58,
            stayed_green=("7", "FS1", "23", "M1"),
            note="58 red = every one of dimension 7's 58 ENFORCED cells, in one "
                 "sweep. The 4 greens are exactly its 4 waived cells."),
    ),
    Mutation(
        name="D7-UNDECLARED-KEY",
        dim=7, channel=FLOW_YAML, kind="required_outputs_delete_key",
        what="delete the step's `required_outputs` key entirely",
        breaks="rule W4 — the gate designates outputs and the step promises "
               "none. The regression a step rewrite leaves behind when the "
               "author moves the deliverables and forgets the list.",
        red_signal="W4",
        witness="21",
        applies_to=("2", "3", "4", "5", "6", "8", "9", "10", "11", "DT1", "13",
                    "A3", "A7", "A8", "A9", "15", "16", "17", "18", "19", "20",
                    "21", "22", "DT2", "DT3", "24", "25", "26", "27", "28",
                    "29", "30", "31", "32", "33", "34", "35", "36", "37", "38",
                    "M2", "M3", "M4", "40", "41", "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=48,
            stayed_green=("D1", "1", "7", "12", "A1", "A2", "A4", "A5", "A6",
                          "14", "23", "39", "M1"),
            note="13 steps stayed green and the reason is measured, not "
                 "guessed: emptying the promise makes the cell NA for a step "
                 "whose gate designates no provable output, and the cell "
                 "returns before the rules run. Those steps are carried by "
                 "D7-GATE-PROBES-A-GHOST and D7-RENAMED-DELIVERABLE."),
    ),
    Mutation(
        name="D7-RENAMED-DELIVERABLE",
        dim=7, channel=FLOW_YAML, kind="required_outputs_rename_first",
        what="rewrite the step's FIRST required_outputs entry to a path nothing "
             "produces, keeping the list non-empty",
        breaks="rule W3/W2 for the steps whose gate probes a file the list "
               "used to name. Renaming rather than deleting is what keeps the "
               "cell out of its NA branch, which is why it reaches steps "
               "D7-UNDECLARED-KEY cannot.",
        red_signal="step",
        witness="12",
        applies_to=("1", "2", "4", "8", "10", "11", "12", "A1", "A2", "A4",
                    "A5", "A7", "15", "16", "17", "18", "19", "20", "21", "22",
                    "DT3", "26", "27", "28", "29", "30", "31", "32", "34",
                    "35", "36", "38"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=32,
            stayed_green=("D1", "3", "5", "6", "7", "9", "DT1", "13", "A3",
                          "A6", "A8", "A9", "14", "DT2", "23", "24", "25",
                          "33", "37", "39", "M1", "M2", "M3", "M4", "40", "41",
                          "42", "43", "44"),
            note="third, independent lever; kept because it is the only one of "
                 "the three that moves the DECLARATION rather than the gate."),
    ),

    # ---------------- dimension 8 — missing caught ---------------------
    Mutation(
        name="D8-EMPTY-PROMISE",
        dim=8, channel=FLOW_YAML, kind="required_outputs_empty",
        what="empty the step's required_outputs list while KEEPING the key",
        breaks="a step that still looks like it declares deliverables and "
               "promises nothing, so the catcher has nothing to find missing "
               "and reports a clean run over an empty input — the starved-"
               "checker shape this whole campaign was convened over.",
        red_signal="step",
        witness="21",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
            "DT1", "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
            "A9", "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2",
            "DT3", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32",
            "33", "34", "35", "36", "37", "38", "39", "M1", "M2", "M3", "M4",
            "40", "41", "42", "43", "44"),
        measured=Measurement(
            date="2026-08-06", command=_SWEEP, reddened=61,
            note="61 red = every one of dimension 8's 61 ENFORCED cells, in one "
                 "sweep. The 2 steps not reached (FS1, P0) declare no "
                 "required_outputs and are dimension 8's 2 NA cells."),
    ),
)

#: Cells no constructed mutation could redden. EMPTY as measured 2026-08-06.
#: An entry here is a finding to publish, never a reason to weaken a predicate.
NOT_FALSIFIABLE: Tuple[NotFalsifiable, ...] = ()

#: The (steps, dimensions, ENFORCED cells) the ledger was built against. Like
#: ``GRID_AS_MEASURED`` in the coverage meta-test, this is the review gate and
#: never an input: every count below is recomputed live.
LEDGER_AS_MEASURED: Tuple[int, int, int] = (63, 8, 481)


# ══════════════════════════════════════════════════════════════════════
# Lookups
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def by_name() -> Dict[str, Mutation]:
    return {m.name: m for m in MUTATIONS}


def mutation(name: str) -> Mutation:
    try:
        return by_name()[name]
    except KeyError:
        raise KeyError(f"no mutation named {name!r}; known: "
                       f"{sorted(by_name())}") from None


def mutations_for(dim: int) -> Tuple[Mutation, ...]:
    return tuple(m for m in MUTATIONS if m.dim == dim)


def mutations_covering(sid: str, dim: int) -> Tuple[Mutation, ...]:
    """Every ledger entry MEASURED to redden ``(step, dim)``."""
    return tuple(m for m in MUTATIONS if m.dim == dim and m.covers(str(sid)))


def not_falsifiable_for(sid: str, dim: int) -> Optional[NotFalsifiable]:
    key = (str(sid), int(dim))
    for nf in NOT_FALSIFIABLE:
        if nf.key == key:
            return nf
    return None


# ══════════════════════════════════════════════════════════════════════
# LOCK 1 — does the recipe resolve, right now, on this step?
# ══════════════════════════════════════════════════════════════════════
def apply_to_flow(mut: Mutation, sid: str,
                  doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Perform a FLOW_YAML mutation on ``doc`` in place. ``None`` = no edit site.

    The blast radius is the caller's to check; :func:`replay` asserts that the
    only step whose dict changed is the target, because a mutation that moves
    two steps cannot attribute its red to either.
    """
    if mut.channel != FLOW_YAML:
        raise ValueError(f"{mut.name} is a {mut.channel} mutation")
    step = step_by_id(doc, sid)
    if step is None:
        return None
    editor = YAML_KINDS.get(mut.kind)
    if editor is None:
        raise ValueError(f"{mut.name}: unknown FLOW_YAML kind {mut.kind!r}")
    return doc if editor(step, dict(mut.params)) else None


def apply_to_tree(mut: Mutation, root: Path) -> Optional[str]:
    """Perform a PLUGIN_TREE mutation inside ``root``. ``None`` = no edit site.

    Uses unlink-then-write so a hardlink mirror is never written THROUGH to the
    shared worktree. Returns the patched file's path (relative) on success.
    """
    if mut.channel != PLUGIN_TREE:
        raise ValueError(f"{mut.name} is a {mut.channel} mutation")
    rel = mut.params["file"]
    anchor = mut.params["anchor"]
    insert = mut.params["insert"]
    target = root / rel
    if not target.is_file():
        return None
    src = target.read_text(encoding="utf-8")
    if src.count(anchor) != 1:
        return None
    new = (src.replace(anchor, anchor + insert, 1)
           if mut.params.get("insert_after")
           else src.replace(anchor, insert + anchor, 1))
    target.unlink()
    target.write_text(new, encoding="utf-8")
    return rel


def resolve(mut: Mutation, sid: str,
            doc: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """``None`` when the edit site exists RIGHT NOW; else why it does not.

    This is LOCK 1. It runs over every (entry, step) pair on every gate run and
    costs one yaml parse — no pytest, no subprocess.
    """
    if mut.channel == FLOW_YAML:
        doc = doc if doc is not None else load_flow()
        if step_by_id(doc, sid) is None:
            return (f"step {sid} is not declared in "
                    f"{flow_yaml_path()} — the entry names a step the flow "
                    f"does not have")
        probe = copy.deepcopy(doc)
        if apply_to_flow(mut, sid, probe) is None:
            return (f"step {sid} has no edit site for kind {mut.kind!r}; the "
                    f"entry claims a step whose {'gate' if 'gate' in mut.kind else 'declaration'} "
                    f"is the wrong shape, so the recorded red cannot be "
                    f"reproduced")
        return None
    rel = mut.params.get("file")
    target = PLUGIN_ROOT / str(rel)
    if not target.is_file():
        return f"{rel} does not exist under {PLUGIN_ROOT}"
    src = target.read_text(encoding="utf-8")
    hits = src.count(mut.params.get("anchor", ""))
    if hits != 1:
        return (f"the anchor occurs {hits} times in {rel} (must be exactly 1); "
                f"a moved or duplicated anchor means the recorded edit no "
                f"longer lands where it was measured")
    return None


def unresolved() -> Tuple[Tuple[str, str, str], ...]:
    """``((mutation name, step, problem), ...)`` over the WHOLE ledger."""
    doc = load_flow()
    out: List[Tuple[str, str, str]] = []
    for m in MUTATIONS:
        for sid in m.applies_to:
            problem = resolve(m, sid, doc)
            if problem:
                out.append((m.name, sid, problem))
    return tuple(out)


# ══════════════════════════════════════════════════════════════════════
# LOCK 2 — replay
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ReplayResult:
    mutation: str
    dim: int
    step_id: str
    applied: bool
    baseline_rc: Optional[int]
    mutant_rc: Optional[int]
    signal_seen: bool
    detail: str
    seconds: float = 0.0

    @property
    def proved(self) -> bool:
        """The cell went PASS -> FAIL, and failed for the declared reason."""
        return (self.applied and self.baseline_rc == 0
                and self.mutant_rc not in (None, 0) and self.signal_seen)

    @property
    def verdict(self) -> str:
        if self.proved:
            return "REDDENED"
        if not self.applied:
            return "NO_EDIT_SITE"
        if self.baseline_rc != 0:
            return "ALREADY_RED"
        if self.mutant_rc in (None, 0):
            return "STAYED_GREEN"
        return "RED_FOR_ANOTHER_REASON"


def _run_cell(dim: int, sid: str, cwd: Path,
              flow_override: Optional[Path], timeout: int) -> Tuple[int, str]:
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if flow_override is None:
        env.pop(FLOW_YAML_ENV, None)
    else:
        env[FLOW_YAML_ENV] = str(flow_override)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", cell_nodeid(dim, sid),
         "-q", "-p", "no:randomly", "--no-header", "-rN"],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def replay(mut: Mutation, sid: Optional[str] = None,
           timeout: int = 900) -> ReplayResult:
    """Perform the mutation FOR REAL on an isolated copy and measure the cell.

    Never writes to the shared worktree. FLOW_YAML entries write one mutated
    yaml into a scratch dir and feed it through :data:`FLOW_YAML_ENV`;
    PLUGIN_TREE entries build a ``cp -al`` hardlink mirror of the plugin and
    unlink-then-write inside it. Both are removed afterwards.
    """
    import time
    sid = str(sid or mut.witness)
    started = time.time()
    scratch = Path(tempfile.mkdtemp(prefix=f"matmut_{mut.name}_"))
    try:
        if mut.channel == FLOW_YAML:
            base = load_flow()
            doc = copy.deepcopy(base)
            if apply_to_flow(mut, sid, doc) is None:
                return ReplayResult(mut.name, mut.dim, sid, False, None, None,
                                    False,
                                    f"no edit site on step {sid} for kind "
                                    f"{mut.kind!r}", time.time() - started)
            moved = [str(a.get("id"))
                     for a, b in zip(doc["steps"], base["steps"]) if a != b]
            if moved != [sid]:
                return ReplayResult(
                    mut.name, mut.dim, sid, False, None, None, False,
                    f"blast radius {moved} != ['{sid}'] — a mutation that "
                    f"moves more than its target cannot attribute its red",
                    time.time() - started)
            mutant = scratch / "flow.yaml"
            mutant.write_text(
                yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                encoding="utf-8")
            base_rc, _ = _run_cell(mut.dim, sid, PLUGIN_ROOT, None, timeout)
            mut_rc, out = _run_cell(mut.dim, sid, PLUGIN_ROOT, mutant, timeout)
            patched = "flow/phase1_phase2_phase3.yaml (substituted)"
        else:
            mirror = scratch / "mirror"
            subprocess.run(["cp", "-al", str(PLUGIN_ROOT), str(mirror)],
                           check=True, capture_output=True)
            for pyc in mirror.rglob("__pycache__"):
                shutil.rmtree(pyc, ignore_errors=True)
            base_rc, _ = _run_cell(mut.dim, sid, mirror, None, timeout)
            patched = apply_to_tree(mut, mirror)
            if patched is None:
                return ReplayResult(
                    mut.name, mut.dim, sid, False, base_rc, None, False,
                    f"anchor for {mut.name} is absent or not unique in "
                    f"{mut.params.get('file')}", time.time() - started)
            for pyc in mirror.rglob("__pycache__"):
                shutil.rmtree(pyc, ignore_errors=True)
            mut_rc, out = _run_cell(mut.dim, sid, mirror, None, timeout)
        seen = mut.red_signal in out
        tail = "\n".join(l for l in out.strip().splitlines() if l.strip())[-1200:]
        return ReplayResult(
            mut.name, mut.dim, sid, True, base_rc, mut_rc, seen,
            f"patched {patched}; baseline rc={base_rc}, mutant rc={mut_rc}, "
            f"red_signal {mut.red_signal!r} "
            f"{'present' if seen else 'ABSENT'}\n--- mutant tail ---\n{tail}",
            time.time() - started)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def replay_mode() -> str:
    return os.environ.get(REPLAY_ENV, "witness").strip().lower() or "witness"


def replay_plan(mode: Optional[str] = None) -> Tuple[Tuple[str, str], ...]:
    """``((mutation name, step), ...)`` the current mode will re-execute."""
    mode = (mode or replay_mode())
    if mode not in REPLAY_MODES:
        raise ValueError(
            f"{REPLAY_ENV}={mode!r} is not one of {REPLAY_MODES}. The replay "
            f"lock has no off switch: an entry nobody re-executes is exactly "
            f"the asserted-but-never-run mutation this ledger refuses.")
    if mode == "all":
        return tuple((m.name, s) for m in MUTATIONS for s in m.applies_to)
    return tuple((m.name, m.witness) for m in MUTATIONS)


def replay_many(plan: Sequence[Tuple[str, str]], jobs: int = 8,
                timeout: int = 900) -> Tuple[ReplayResult, ...]:
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return tuple(pool.map(
            lambda pair: replay(mutation(pair[0]), pair[1], timeout), plan))


# ══════════════════════════════════════════════════════════════════════
# Census
# ══════════════════════════════════════════════════════════════════════
def census(states: Optional[Dict[Tuple[str, int], str]] = None) -> Dict[str, Any]:
    """What the ledger covers, recomputed from the live flow every call.

    ``states`` is ``{(step, dim): 'ENFORCED'|'WAIVED'|'NA'}`` supplied by the
    caller — the eight dimension modules own that answer and this module
    deliberately forms no second opinion about it. Omit it and the census
    reports the ledger's reach over the whole grid instead.
    """
    steps = step_ids()
    dims = tuple(sorted(CELL_TESTS))
    grid = [(s, d) for s in steps for d in dims]
    covered = {(s, d): [m.name for m in mutations_covering(s, d)] for s, d in grid}
    if states is None:
        target = grid
    else:
        target = [k for k in grid if states.get(k) == "ENFORCED"]
    uncovered = [k for k in target if not covered[k] and not not_falsifiable_for(*k)]
    return {
        "flow_yaml": str(flow_yaml_path()),
        "steps": len(steps),
        "dimensions": len(dims),
        "grid": len(grid),
        "considered": len(target),
        "entries": len(MUTATIONS),
        "covered": sum(1 for k in target if covered[k]),
        "uncovered": [f"{s}/d{d}" for s, d in uncovered],
        "not_falsifiable": [f"{nf.step_id}/d{nf.dim}" for nf in NOT_FALSIFIABLE],
        "replay_mode": replay_mode(),
        "replay_pairs": len(replay_plan()),
        "per_dimension": {
            f"d{d}": {
                "considered": sum(1 for s, dd in target if dd == d),
                "covered": sum(1 for s, dd in target if dd == d and covered[(s, dd)]),
                "entries": [m.name for m in mutations_for(d)],
            } for d in dims},
    }


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--resolve", action="store_true",
                    help="LOCK 1 over every (entry, step) pair")
    ap.add_argument("--replay", metavar="NAME")
    ap.add_argument("--replay-witnesses", action="store_true")
    ap.add_argument("--step", metavar="ID")
    ap.add_argument("--emit-flow", metavar="NAME",
                    help="write the mutated flow yaml and exit (no pytest)")
    ap.add_argument("--out", metavar="PATH")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--json", dest="json_out", metavar="PATH")
    a = ap.parse_args(argv)

    report: Dict[str, Any] = {}
    rc = 0

    if a.emit_flow:
        mut = mutation(a.emit_flow)
        sid = str(a.step or mut.witness)
        doc = load_flow()
        if apply_to_flow(mut, sid, doc) is None:
            print(f"[FAIL] {mut.label}: no edit site on step {sid}")
            return 1
        out = Path(a.out or "mutated_flow.yaml")
        out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                       encoding="utf-8")
        print(f"wrote {out}  ({mut.label} on step {sid})")
        print(f"replay it with: {FLOW_YAML_ENV}={out} python3 -m pytest "
              f"{cell_nodeid(mut.dim, sid)}")
        return 0

    if a.census or not (a.resolve or a.replay or a.replay_witnesses):
        rep = census()
        report["census"] = rep
        print(f"=== matrix_mutation_ledger ({rep['flow_yaml']}) ===")
        print(f"  {rep['steps']} steps x {rep['dimensions']} dimensions = "
              f"{rep['grid']} cells; {rep['entries']} mutation entries")
        for d, per in rep["per_dimension"].items():
            print(f"  {d}: {per['covered']}/{per['considered']} cells carry a "
                  f"named mutation  [{', '.join(per['entries'])}]")
        print(f"  replay mode: {rep['replay_mode']} "
              f"({rep['replay_pairs']} pair(s) re-executed per run)")
        if rep["not_falsifiable"]:
            print(f"  NOT-FALSIFIABLE: {rep['not_falsifiable']}")

    if a.resolve:
        bad = unresolved()
        report["unresolved"] = [
            {"mutation": n, "step": s, "problem": p} for n, s, p in bad]
        pairs = sum(len(m.applies_to) for m in MUTATIONS)
        print(f"\nLOCK 1 — {pairs} (entry, step) pair(s) checked against "
              f"{flow_yaml_path()}")
        if bad:
            rc = 1
            for n, s, p in bad:
                print(f"  [FAIL] {n} @ step {s}: {p}")
        else:
            print("  every recorded edit site still exists")

    plan: List[Tuple[str, str]] = []
    if a.replay:
        mut = mutation(a.replay)
        plan = ([(mut.name, str(a.step))] if a.step
                else [(mut.name, s) for s in mut.applies_to])
    elif a.replay_witnesses:
        plan = list(replay_plan("witness"))

    if plan:
        print(f"\nLOCK 2 — replaying {len(plan)} (entry, step) pair(s), "
              f"jobs={a.jobs}")
        results = replay_many(plan, jobs=a.jobs, timeout=a.timeout)
        report["replay"] = [r.__dict__ | {"verdict": r.verdict} for r in results]
        for r in results:
            mark = "ok  " if r.proved else "FAIL"
            print(f"  [{mark}] {r.mutation} @ step {r.step_id}: {r.verdict} "
                  f"({r.seconds:.1f}s)")
            if not r.proved:
                rc = 1
                print("        " + r.detail.replace("\n", "\n        "))

    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
