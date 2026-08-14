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
THE THIRD CHANNEL — ARTEFACT_MUTATION (63x8 finding #20, at the mechanism)
====================================================================
For its first two channels this ledger could edit the FLOW YAML and it could
edit the PLUGIN TREE. Both change the SOURCE. Neither can express "change a
number inside a PUBLISHED REPORT and see whether anything notices", and that
absence is finding #20 stated at the level where it is actionable: *no cell
reads artefact CONTENT* was never a policy anyone wrote down — it was a
consequence of the ledger having no way to say such a thing.

:data:`ARTEFACT_MUTATIONS` says it. An entry names a published run under
``benchmark-data/``, a file inside it, an exact list of byte substitutions with
the number of sites each must find, the flow step whose gate is re-run, the cell
``(step, dim)`` that bears on the answer, and the verdict that was MEASURED.
:func:`replay_artefact` copies the run FOR REAL, applies the edit, and re-runs
that step's own gate command through ``flow_compliance_check``'s own verdict
mapping — so the entry cannot claim a red the flow would not honour.

**PART OF THE SEED SET PROVES A CELL CANNOT REDDEN, AND THAT IS THE
DELIVERABLE.** Four of the eight entries recorded :data:`CANNOT_REDDEN` when the
channel was seeded on 2026-08-11. THREE were closed the same day, by two
independent pieces of D9 Phase 1 work, and the fourth was answered in a way that
is not a closure and should not be counted as one.

CLOSED — the gate was believing the wrong author:
  * ``ART-ROUTER-FINAL-ITERATION`` (step 21). Rewriting the router's FINAL
    iteration from 0 violations to 12 did not move the gate, while rewriting the
    runner's SUMMARY of that same file to 17 did. That pair said what step 21's
    green was actually a statement about: the runner's arithmetic, not the
    router's result.
  * ``ART-NETLIST-PRIMITIVE-SWAP`` (step 9). Substituting 221 NAND primitives
    for AND did not move the gate, and its own report enumerated the substituted
    cell while passing.

CLOSED — a number was read, reported, and never compared:
  * ``ART-EM-CURRENT-DENSITY`` (step 25). Step 25's gate gained a clause that
    screens the peak segment current against the total current the SAME report
    says the net is supplied with. That authority is declared in the artefact,
    so the comparison is available on every run, and the SAME byte edits that
    recorded STAYED_GREEN now record REDDENED.

NOT CLOSED, AND CORRECTLY SO:
  * ``ART-POWER-FIGURES-X1000`` (step 33) was the same defect as step 25 — a
    number read, reported, never compared — and the difference in outcome is not
    effort, it is whether AN AUTHORITY EXISTS TO COMPARE AGAINST. Step 33's gate
    also gained a comparison clause, total power against L19's
    ``power_budget_uw``, but 0 of the 17 published runs carrying a power report
    declare that budget, so the clause REFUSES (`INCOMPLETE`, naming what it
    lacks) instead of passing. The mutation does not redden it because nothing
    can: there is no authority. **A cell that refuses is not a cell that
    passes**, and the flow's per-step listing now says INCOMPLETE where it used
    to say PASS.

TWO OF THE FOUR ARE NOW CLOSED, and they were ONE DEFECT IN TWO PLACES: the
gate believed a summary written by the RUNNER instead of the output written by
the TOOL. Substituting 221 NAND primitives for AND did not move step 9's gate
while that gate's own report ENUMERATED the substituted cell; rewriting the
router's FINAL iteration from 0 violations to 12 did not move step 21's, while
rewriting the runner's SUMMARY of the same file to 17 did — the pair that said
what the green at step 21 was actually a statement about. Both now redden,
because each gate reads the tool's own artefact and treats a disagreement
between two published statements of one quantity as a finding.

These were published as ledger entries, not hidden as gaps: an entry that says
"this mutation should redden cell X and does not" is precisely the record this
campaign exists to produce. :data:`ARTEFACT_CANNOT_REDDEN_AS_MEASURED` pins the
count so it cannot drift, and each such entry is a PIN, not a waiver — the day a
gate learns to notice, its replay stops matching the record and the gate file
fails by name, demanding the entry be updated in the same change that closes the
gap. That is exactly how the two closures above were forced to declare
themselves: the count moved from 4 to 2 in the same diff.

WHAT THIS CHANNEL COSTS, AND HOW IT IS SCHEDULED. Every artefact entry is
re-executed in BOTH replay modes — there is no "witness subset" to hide in,
because an artefact entry claims exactly one cell. MEASURED 2026-08-11 on this
tree, stated so nobody has to estimate it:

  * the artefact plan ALONE, ``--replay-artefacts --jobs 1``: **3.06 s wall**
    for all 8 entries (2.6 s of it inside the entries);
  * the artefact plan alone at ``--jobs 8``: 2.72 s wall;
  * the FULL witness plan — 16 yaml/tree entries plus these 8 — at
    ``--jobs 8``: **78.18 s wall**, of which the 8 artefact entries account for
    0.4-1.3 s each. The three dimension-7 witnesses alone cost 63-70 s.

So this channel is roughly **4% of the replay budget it joins**, and it needs no
new schedule: it rides the plan the gate file already runs on every CI
invocation. Per entry it copies ~13 MB (one published run) into a temp dir and
removes it, so peak transient disk is bounded by ``jobs`` x 13 MB, not by the
entry count.

If it ever DOES stop being affordable — a much larger corpus, or entries against
multi-GB runs — the honest lever is to move the whole gate file to a scheduled
audit job and say so. NOT to sample the artefact entries: an entry re-executed
only in a mode nobody runs is exactly the asserted-but-never-run mutation the
three locks exist to refuse, and cheapness bought that way is a lie about
coverage rather than a saving.

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
    matrix_mutation_ledger.py --replay-artefacts [--jobs 8]
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
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:  # the shared isolation harness (#996) — see its module docstring
    import _run_isolation as _iso
except ImportError:  # pragma: no cover - exercised by the packaged layout
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _run_isolation as _iso

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


#: Where the PUBLISHED runs live. ``benchmark-data/`` is committed to this
#: repository, so an artefact entry resolves in any checkout; the override
#: exists so a host that relocates the corpus can still replay rather than
#: reporting NOT_REPLAYABLE for every entry.
BENCHMARK_DATA_ENV = "VIBE_IC_BENCHMARK_DATA"
BENCHMARK_DATA_REL = "benchmark-data"

#: ``vibe-ic-marketplace/plugins/vibe-ic`` -> the repository root.
REPO_ROOT: Path = PLUGIN_ROOT.parent.parent.parent


def flow_yaml_path() -> Path:
    override = os.environ.get(FLOW_YAML_ENV)
    return Path(override) if override else PLUGIN_ROOT / FLOW_REL


def benchmark_data_root() -> Path:
    override = os.environ.get(BENCHMARK_DATA_ENV)
    return Path(override) if override else REPO_ROOT / BENCHMARK_DATA_REL


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
# The three mutation channels
# ══════════════════════════════════════════════════════════════════════
FLOW_YAML = "FLOW_YAML"      # edit the flow document; replay via FLOW_YAML_ENV
PLUGIN_TREE = "PLUGIN_TREE"  # edit a file; replay in a hardlink mirror
#: edit a NUMBER INSIDE A PUBLISHED REPORT; replay against a real copy of the
#: run. See "THE THIRD CHANNEL" in the module docstring for why the first two
#: could not express this and why this one cannot use a hardlink mirror.
ARTEFACT_MUTATION = "ARTEFACT_MUTATION"

CHANNELS = (FLOW_YAML, PLUGIN_TREE, ARTEFACT_MUTATION)

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

#: An ARTEFACT_MUTATION entry performs a list of exact byte substitutions in one
#: file of one published run. Each substitution declares how many times its
#: ``frm`` must occur, and the count is checked before anything is written — see
#: :func:`resolve_artefact`.
ARTEFACT_KINDS: Tuple[str, ...] = ("byte_substitution",)

KINDS: Tuple[str, ...] = tuple(sorted(YAML_KINDS)) + TREE_KINDS + ARTEFACT_KINDS


def step_gate_commands(sid: str,
                       doc: Optional[Dict[str, Any]] = None) -> Tuple[str, ...]:
    """Every executable command the LIVE flow wires into ``sid``'s gate.

    DERIVED, never typed. An ARTEFACT_MUTATION entry names one of these strings
    verbatim, so a flow edit that renames a flag, adds an argument or drops the
    clause makes the entry unresolvable instead of leaving a stale proof that
    quietly re-runs a command the flow no longer issues.
    """
    doc = doc if doc is not None else load_flow()
    step = step_by_id(doc, sid)
    if step is None:
        return ()
    clauses: List[Tuple[Dict, str, Any]] = []
    _exec_clauses(step.get("gate"), clauses)
    out: List[str] = []
    for _, _, value in clauses:
        if isinstance(value, list):
            out.extend(v for v in value if isinstance(v, str))
        else:
            cmd = _command_of(value)
            if cmd:
                out.append(cmd)
    return tuple(out)


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


#: The two verdicts an ARTEFACT_MUTATION entry may RECORD. ``STAYED_GREEN`` is
#: not a failure of the ledger — it is the finding the ledger exists to publish.
REDDENS = "REDDENED"
CANNOT_REDDEN = "STAYED_GREEN"

#: The witness was ALREADY RED before the mutation was applied, so the replay
#: measured nothing (vibe-ic#1432). This is NOT a third recordable `expected`
#: value — no ledger entry may declare it — it is what a replay reports when it
#: could not perform the experiment.
#:
#: `replay_artefact`'s docstring already said this ("a mutation against an
#: already-red gate proves nothing and is reported ALREADY_RED, never skipped")
#: and `verdict` already returned it. What was missing is that `proved` and
#: `as_recorded` are both False for it, so the two consumers scored an
#: unmeasurable pair identically to `STAYED_GREEN` — "the gate lost its teeth".
#: That is the same conflation `_vacuous_exit` exists to prevent everywhere else
#: in this repo: COULD NOT LOOK is not LOOKED AND FOUND NOTHING.
#:
#: `policy_direction_pin_check` already handles the identical situation the
#: other way, and in the same words — it ABSTAINS on a call site whose candidate
#: tests are red before any flip, "so a kill proves nothing about this call
#: site". One instrument abstained; this one scored it as a defect.
ALREADY_RED = "ALREADY_RED"
ARTEFACT_EXPECTATIONS = (REDDENS, CANNOT_REDDEN)


@dataclass(frozen=True)
class Edit:
    """One exact byte substitution, with the number of sites it must find.

    ``count`` is the resolution check and the blast-radius check at once: the
    replay refuses to write unless ``frm`` occurs EXACTLY ``count`` times, so a
    regenerated artefact that gained or lost an occurrence reports
    NOT_REPLAYABLE rather than silently editing a different number of places
    than the one that was measured.
    """

    frm: str
    to: str
    count: int


@dataclass(frozen=True)
class ArtefactMutation:
    """A NUMBER INSIDE A PUBLISHED REPORT, changed, and what the gate did.

    This is the record 63x8 finding #20 asks for. An entry names a published run
    directory, a file in it, the exact bytes changed, the flow step whose gate is
    re-run, and the cell ``(step_id, dim)`` that bears on the result — and then
    :func:`replay_artefact` performs the edit on a REAL COPY and re-runs that
    step's own gate command through the flow's own verdict mapping.

    ``expected`` is the measured answer, and BOTH values are first-class:

      * :data:`REDDENS` — the gate's verdict moved PASS -> FAIL, and
        ``red_signal`` names the string in its output that proves it failed
        FOR THIS DEFECT rather than for some unrelated reason.
      * :data:`CANNOT_REDDEN` — the gate's verdict did NOT move. The entry is
        then a published finding: this cell cannot be reddened from artefact
        content by this edit. ``observed`` records what the gate said instead.

    A CANNOT_REDDEN entry is NOT a licence to leave the gap open, and it is not
    a waiver: it is a pin. The moment the gate learns to notice, the replay's
    verdict stops matching ``expected`` and the gate file fails, demanding the
    record be updated in the same change that closes the gap.
    """

    name: str
    dim: int
    #: The flow step whose gate is re-run. With ``dim`` this is the cell.
    step_id: str
    #: Published run root, relative to ``benchmark-data/``.
    run_dir: str
    #: The file inside the run whose bytes are changed.
    artefact: str
    edits: Tuple[Edit, ...]
    #: One of :func:`step_gate_commands` for ``step_id``, VERBATIM.
    gate: str
    #: One line: the edit, in terms someone can perform by hand.
    what: str
    #: The real defect this edit simulates. Why reddening is the RIGHT answer.
    breaks: str
    expected: str
    measured: Measurement
    #: Asserted PRESENT in the mutant output and ABSENT in the baseline output
    #: when ``expected`` is :data:`REDDENS`. Descriptive only otherwise — see
    #: ``observed``, which is where a CANNOT_REDDEN entry carries its evidence.
    red_signal: str = ""
    #: What the gate did INSTEAD of reddening. Required for CANNOT_REDDEN.
    observed: str = ""
    channel: str = ARTEFACT_MUTATION
    kind: str = "byte_substitution"

    @property
    def label(self) -> str:
        return f"d{self.dim}:{self.name}"

    @property
    def cell(self) -> Tuple[str, int]:
        return (str(self.step_id), int(self.dim))

    @property
    def witness(self) -> str:
        """The step replayed on every run. An artefact entry claims one cell,
        so its witness is that cell's step and there is no wider sweep to
        under-sample."""
        return str(self.step_id)

    @property
    def applies_to(self) -> Tuple[str, ...]:
        return (str(self.step_id),)

    @property
    def proves_cell_cannot_redden(self) -> bool:
        return self.expected == CANNOT_REDDEN


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

#: The 2026-08-06 sweep, PLUS a single-step replay on 2026-08-11 for an entry
#: that gained exactly one step. Spelled out rather than folded into
#: :data:`_SWEEP` because the two are different amounts of evidence: the bulk of
#: ``applies_to`` rests on the 63-step sweep, and the added step rests on one
#: replay run on a later tree. An entry using this must name the added step, so
#: a reader can tell which claim rests on which run.
_SWEEP_THEN_ONE = (
    _SWEEP + "   THEN   matrix_mutation_ledger.py --replay {name} --step "
             "{added}   (2026-08-11, the one step this entry gained)")

#: A full re-sweep on 2026-08-11 — same shape as :data:`_SWEEP`, later tree.
_RESWEEP = ("matrix_mutation_ledger.py --replay {name} --jobs 8   "
            "(2026-08-11, every declared step, one pytest run per step)")

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
            "DT1", "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
            "A9", "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2",
            "DT3", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32",
            "33", "34", "36", "37", "38", "39", "M1", "M2", "M3", "M4", "40",
            "41", "42", "43", "44"),
        measured=Measurement(
            date="2026-08-11",
            command=_SWEEP_THEN_ONE.replace("{added}", "12"), reddened=60,
            stayed_green=("35",),
            note="60 red = every one of dimension 2's 60 ENFORCED cells, in one "
                 "sweep. The 2 waived cells (1, 35) and the NA cell (P0) are "
                 "the only steps not reddened: 1 and P0 have no executable "
                 "clause to blind, and 35's gate is files_exist + advisory, "
                 "which is precisely why it is waived. "
                 "STEP 12 WAS ADDED 2026-08-11 and the old note's claim that it "
                 "'has no executable clause to blind' was, by then, false. "
                 "`23d96bf5` (v1.10.0, 'close the matrix_63x8 dimension-2 "
                 "content gap on Step 12') gave step 12 a "
                 "`program_exit_zero: dft_post_optimization_scan_survival_check` "
                 "clause and lifted its dimension-2 waiver in the same change — "
                 "so the very commit that made 12/d2 ENFORCED also created the "
                 "edit site this mutation needs, and nothing re-ran the sweep. "
                 "Replayed 2026-08-11: `--replay D2-BLIND-GATE-PROGRAMS "
                 "--step 12` -> REDDENED in 1.5s."),
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
        # WAS "21" until 2026-08-11. A witness must be GREEN at baseline — this
        # class's own contract, three lines up in `Mutation` — and step 21's
        # dimension-3 cell no longer is, so the entry was proving nothing and
        # said so: `ALREADY_RED`. Re-picked by a rule rather than by taste:
        # the FIRST step in flow-declaration order that is green at baseline.
        # That is D1, measured at 4.1 s (the slowest of the 37 green
        # candidates; the fastest are 38 and DT2 at 1.7 s). Speed is not the
        # criterion and is recorded only so the cost of this choice is visible.
        witness="D1",
        applies_to=(
            "D1", "1", "2", "3", "4", "5", "7", "8", "9", "10", "11", "DT1",
            "12", "13", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "14", "15", "16", "17", "18", "19", "20", "21", "22", "DT2", "DT3",
            "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
            "34", "35", "36", "37", "38", "M2", "M3", "M4"),
        measured=Measurement(
            date="2026-08-11", command=_RESWEEP, reddened=53,
            baseline_red=("12", "15", "17", "19", "20", "21", "22", "23", "24",
                          "25", "26", "30", "32", "M2", "M3", "M4"),
            stayed_green=("6", "39", "M1"),
            note="53 red = every one of dimension 3's 53 ENFORCED cells. 16 of "
                 "them are ALREADY red before the mutation (their declared "
                 "artefacts genuinely do not resolve), so 37 reds are "
                 "attributable to this mutation; the 16 are falsifiable by "
                 "definition and are named here rather than counted twice. The "
                 "3 greens are the waived cells, whose strict xfail correctly "
                 "held. "
                 "BASELINE_RED MOVED 11 -> 16 ON 2026-08-11, and the move is a "
                 "FINDING, not an accommodation. Newly red: 12, 21, 22, 23, 24, "
                 "25, 26. No longer red: 11, 29. Re-measured by the full sweep "
                 "(`--replay D3-UNDECLARED-ARTEFACT --jobs 8`, 53 pairs, 37 "
                 "REDDENED + 16 ALREADY_RED, no other outcome). "
                 "ONE cause for all nine moves: "
                 "`benchmark-data/ic/spm/v1.9.96_gf180mcuD/reports/"
                 "write_ledger.json` (captured 2026-08-06T19:17:51Z) is stale "
                 "with respect to the commit that carries it, in BOTH "
                 "directions — 21 artefacts it records as WRITTEN are absent "
                 "from the commit (all under `phase3/stage3/**` and "
                 "`phase3/stage4/foundry_handoff/**`; step 21's `routed.def` is "
                 "recorded at 481667 B and was never added in any commit, and "
                 "is not gitignored), and 4 specs it records as NOT WRITTEN are "
                 "present in it (step 11's `scan_netlist.v`, `atpg_coverage.rpt` "
                 "and `reports/phase2/dft/coverage.json`, step 12's "
                 "`post_dft_netlist.v`). Because the ledger BINDS those steps to "
                 "that run root, they no longer fall back to the root that does "
                 "carry the artefact, and they redden. "
                 "THE STALE LEDGER IS DELIBERATELY NOT REPAIRED HERE. Re-emitting "
                 "a published run's record is a benchmark-data rewrite that "
                 "would erase the historical fact that the run produced those "
                 "artefacts, and it is not this change's subject. It is left "
                 "RED and published; `test_d3_the_write_ledger_population_is_"
                 "derived_from_the_commit` states the remedy in its own words."),
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
            "M4", "40", "41", "42", "43", "44", "P0"),
        measured=Measurement(
            date="2026-08-11",
            command=_SWEEP_THEN_ONE.replace("{added}", "P0"), reddened=63,
            note="63 red = every one of dimension 5's 63 ENFORCED cells, in one "
                 "sweep, each reddening that cell alone. There is no longer an "
                 "NA cell in this dimension. "
                 "P0 WAS ADDED 2026-08-11 and the old note's claim that it "
                 "'declares no blocks_on key to append to' was, by then, false. "
                 "`332b9985` ('flow: stage membership was declared twice and "
                 "the copies disagreed') gave P0 `blocks_on: [1]`, which "
                 "self-invalidated dimension 5's pinned NA exactly as that pin "
                 "was written to do — step P0's own cell went red demanding "
                 "re-evaluation. The re-evaluation was done, not waived: "
                 "`d5_problems('P0')` is empty, so P0 runs the full predicate as "
                 "an ENFORCED cell. Replayed 2026-08-11: `--replay "
                 "D5-PHANTOM-EDGE --step P0` -> REDDENED in 1.6s."),
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

# ══════════════════════════════════════════════════════════════════════
# THE ARTEFACT LEDGER — a number inside a published report, changed
# ══════════════════════════════════════════════════════════════════════
# Every entry below was executed on 2026-08-11 against the tree at 38c8e687.
# Each replay copies the named run with `cp -a` (NOT `cp -al` — see
# `_copy_published_run`), applies the byte edits, and re-runs the step's own
# gate command through `flow_compliance_check._check_program_exit_zero`, which
# is the FLOW's own verdict mapping (rc 2 = VACUOUS_PASS and rc 3 + sentinel =
# PASS_WITH_WAIVERS both count as PASS). An entry therefore cannot claim a red
# the flow itself would not honour.
_ARTEFACT_SWEEP = ("matrix_mutation_ledger.py --replay {name}   "
                   "(2026-08-11, one copy + two gate invocations per entry)")

#: One klayout RDB violation item, in the STRUCTURAL shape the sign-off DRC
#: reports in this corpus use. Three of these are spliced into an EMPTY
#: `<items>` block.
#:
#: The category and cell names are deliberately SYNTHETIC rather than copied
#: from a real rule deck. A fixture that named a real design-rule id would bake
#: a process token into this module, and it would buy nothing: what the gate
#: counts is `<item>` elements, which is asserted by the replay reporting the
#: injected count of 3 back as `real_violation_total`. The names being obviously
#: not-a-real-rule is also what stops one of these leaking into a report and
#: being mistaken for a measurement.
_RDB_ITEM = """  <item>
   <tags/>
   <category>'zzartefactcanary.1'</category>
   <cell>zzartefactcanary_top</cell>
   <visited>false</visited>
   <multiplicity>1</multiplicity>
   <comment/>
   <image/>
   <values>
    <value>edge-pair: (1.0,1.0;1.0,1.1)|(1.2,1.0;1.2,1.1)</value>
   </values>
  </item>
"""

#: The one published run every seed entry uses. Chosen by MEASUREMENT, not by
#: preference: it is the only run in the corpus whose seven physical-signoff
#: gates are ALL green at baseline, and a mutation against an already-red gate
#: proves nothing. The survey that picked it is in the PR body.
_RUN = "ic/spm/v1.10.18_sky130A"

ARTEFACT_MUTATIONS: Tuple[ArtefactMutation, ...] = (
    # ---------------- reddens -----------------------------------------
    ArtefactMutation(
        name="ART-DRC-ROUTER-SUMMARY",
        dim=2, step_id="21", run_dir=_RUN,
        artefact="reports/phase3/drc_router.rpt",
        edits=(Edit("violation report: 0\n"
                    "violation count summary: 0 violation(s) found",
                    "violation report: 17\n"
                    "violation count summary: 17 violation(s) found", 1),),
        gate=("drc_report_check . --mode drc --under phase3/stage3/pnr "
              "--under reports/phase3/drc_router.rpt "
              "--json reports/phase3/drc_router.json"),
        what="rewrite the router DRC summary from 0 violations to 17",
        breaks="a post-route DRC count that is not what the router found. If "
               "this cannot move the gate, a routed design with real spacing "
               "violations ships with a clean-looking report.",
        expected=REDDENS,
        red_signal='"real_violation_total": 17',
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="the gate parses the summary line it is handed and reports the "
                 "injected count back; baseline PASS, mutant FAIL."),
    ),
    ArtefactMutation(
        name="ART-IR-DROP-OVER-BUDGET",
        dim=2, step_id="24", run_dir=_RUN,
        artefact="reports/phase3/ir_drop.json",
        edits=(Edit('"worst_ir_uv": 375.0', '"worst_ir_uv": 300000.0', 1),),
        gate=("ir_drop_report_check . --mode ir_drop "
              "--json reports/phase3/ir_drop_signoff.json"),
        what="raise the recorded worst static IR drop from 375 uV to 300000 uV, "
             "which is 1.67x the run's own recorded 180000 uV budget",
        breaks="a power grid that does not deliver its supply. The published "
               "budget is in the same file, so this is the one artefact edit in "
               "the seed set the gate can settle without any outside reference.",
        expected=REDDENS,
        red_signal="exceeds the 1.8e+05",
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="the gate compares the figure against budget_uv carried in the "
                 "same artefact and names both values in its finding."),
    ),
    ArtefactMutation(
        name="ART-ANTENNA-NET-VIOLATIONS",
        dim=2, step_id="26", run_dir=_RUN,
        artefact="reports/phase3/antenna.rpt",
        edits=(Edit("antenna check: 0 net violations, 0 pin violations\n"
                    "antenna clean: YES",
                    "antenna check: 7 net violations, 0 pin violations\n"
                    "antenna clean: NO", 1),),
        gate=("antenna_report_check . --mode antenna "
              "--json reports/phase3/antenna_signoff.json"),
        what="rewrite the antenna result from 0 net violations / clean YES to "
             "7 net violations / clean NO",
        breaks="unrepaired antenna nets reaching tapeout — gate-oxide damage "
               "that no electrical test after packaging can undo.",
        expected=REDDENS,
        red_signal="Antenna violations present: 7",
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="the gate reads the count and the clean flag from the report "
                 "text; baseline PASS, mutant FAIL naming the injected 7."),
    ),
    ArtefactMutation(
        name="ART-DRC-RDB-THREE-ITEMS",
        dim=2, step_id="31", run_dir=_RUN,
        artefact="reports/phase3/drc_signoff.rpt",
        edits=(Edit(" <items>\n </items>",
                    " <items>\n" + _RDB_ITEM * 3 + " </items>", 1),),
        gate=("drc_report_check . --mode drc --signoff "
              "--under reports/phase3/drc_signoff.rpt "
              "--json reports/phase3/drc_signoff.json"),
        what="splice three klayout RDB violation items into the sign-off DRC "
             "report's EMPTY <items> block",
        breaks="sign-off DRC violations that the published report does carry and "
               "the flow does not act on. This is the artefact-content twin of "
               "the empty-input defect that convened the campaign: the gate is "
               "handed a report with real items in it.",
        expected=REDDENS,
        red_signal='"real_violation_total": 3',
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="the RDB is XML and the gate counts <item> elements, so the "
                 "three spliced items are found as three real violations."),
    ),

    # ---------------- CLOSED IN PHASE 1 ---------------------------------
    # Both entries below were recorded CANNOT_REDDEN on 2026-08-11 and are
    # REDDENS as of 2026-08-11 (D9 Phase 1). They are one defect in two places:
    # THE GATE BELIEVED A SUMMARY WRITTEN BY THE RUNNER INSTEAD OF THE OUTPUT
    # WRITTEN BY THE TOOL. Neither gate was made stricter about violations or
    # about primitives; each was made to READ THE TOOL'S OWN ARTEFACT and to
    # treat a disagreement between two published statements of one quantity as
    # a finding rather than a tie broken silently in the summary's favour.
    #
    # MEASURED BLAST RADIUS over all 107 published run dirs, each gated on a
    # `cp -a` copy: step 21 PASS -> FAIL 0, step 9 PASS -> FAIL 1
    # (`evaluation/phase1_parity/sgmii`, adjudicated by hand — its netlist.v
    # carries signals its own RTL never declares while the tool's own output
    # beside it carries the RTL's, i.e. a stale ghost). No run went FAIL ->
    # PASS. The corroboration is not inert: all 14 published router reports and
    # all 15 gated netlists were corroborated against a tool source, so the
    # zeros above are measured agreement, not absence.
    ArtefactMutation(
        name="ART-ROUTER-FINAL-ITERATION",
        dim=2, step_id="21", run_dir=_RUN,
        artefact="reports/phase3/drc_router.rpt",
        edits=(Edit("    Completing 100% with 0 violations.\n"
                    "[INFO DRT-0199]   Number of violations = 0.\n"
                    "[INFO DRT-0267] cpu time = 00:00:06",
                    "    Completing 100% with 12 violations.\n"
                    "[INFO DRT-0199]   Number of violations = 12.\n"
                    "[INFO DRT-0267] cpu time = 00:00:06", 1),),
        gate=("drc_report_check . --mode drc --under phase3/stage3/pnr "
              "--under reports/phase3/drc_router.rpt "
              "--json reports/phase3/drc_router.json"),
        what="rewrite the router's FINAL detailed-route iteration from "
             "DRT-0199 = 0 violations to 12, leaving the runner's own summary "
             "line at the top of the same file untouched",
        breaks="the router finishing with 12 unresolved violations while the "
               "summary above it still says 0. Same file, same step, same gate "
               "as ART-DRC-ROUTER-SUMMARY, which ALSO reddens — the pair is "
               "the point: before this was closed the gate believed the "
               "runner's summary and never read the tool.",
        expected=REDDENS,
        red_signal='"real_violation_total": 12',
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="CLOSED. `_check_drc` now reads the router's own final "
                 "iteration through the SHARED grammar "
                 "`_signoff_drc_format.router_iter_last_count` — the one "
                 "`phase3_one_shot_runner._drt_final_violations` already uses, "
                 "so the cross-check cannot disagree with the runner by "
                 "reading a different grammar — and raises "
                 "DRC_SUMMARY_CONTRADICTS_TOOL when the summary disagrees. "
                 "The corpus says the disagreement is real and not "
                 "hypothetical: 7 of the 14 published router reports carry a "
                 "summary that contradicts their own tool transcript, which is "
                 "the residue of a runner bug the runner itself has since "
                 "fixed (see the comment at phase3_one_shot_runner:32190) and "
                 "that this gate could not see. Those 7 were already red and "
                 "stay red; what is new is that the gate now says WHY."),
    ),
    ArtefactMutation(
        name="ART-NETLIST-PRIMITIVE-SWAP",
        dim=2, step_id="9", run_dir=_RUN,
        artefact="phase2/stage2/synth/netlist.v",
        edits=(Edit("\\$_NAND_", "\\$_AND_", 221),),
        gate=("synth_netlist_check --netlist phase2/stage2/synth/netlist.v "
              "--json reports/phase2/synth_netlist.json"),
        what="substitute the generic primitive $_NAND_ for $_AND_ at all 221 "
             "instantiation sites in the synthesised netlist",
        breaks="221 gates whose output is inverted with respect to what "
               "synthesis produced — a netlist that no longer implements the "
               "RTL. This is the substitution a bad ECO script or a "
               "mis-ordered techmap pass leaves behind.",
        expected=REDDENS,
        red_signal="CELL_CENSUS_CONTRADICTS_TOOL",
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="CLOSED. The cell census this gate ALREADY enumerated now "
                 "decides something: it is compared against the census of "
                 "`netlist_yosys.v`, the file the synthesiser itself wrote and "
                 "which the runner copies to the audited `netlist.v`. The "
                 "gate's finding names both sides per type ($_AND_ 221 vs 0, "
                 "$_NAND_ 0 vs 221). NOT done, and measured rather than "
                 "preferred: the yosys `stat` block is NOT used as a second "
                 "authority, because one invocation logs a block per netlist "
                 "it writes and on this very run the last block in synth.log "
                 "describes a DIFFERENT file (287 technology-mapped cells vs "
                 "this netlist's 449) — a rule keyed on it would raise a "
                 "contradiction where nothing is wrong."),
    ),

    # ---------------- PROVE THE CELL CANNOT REDDEN ----------------------
    # These two are the deliverable, not the residue. Each is a cell that is
    # ENFORCED, green, and unmoved by a defect of a magnitude no reviewer would
    # call marginal. They are the remaining work list, and they are pinned here
    # so that closing one is a visible diff rather than a silent improvement.
    ArtefactMutation(
        name="ART-EM-CURRENT-DENSITY",
        dim=2, step_id="25", run_dir=_RUN,
        artefact="reports/phase3/em.rpt",
        edits=(Edit("max segment current: 1.963e-04 A",
                    "max segment current: 5.0 A", 1),
               Edit("Maximum current    : 1.96e-04 A",
                    "Maximum current    : 5.00e+00 A", 2)),
        gate=("em_peak_current_authority_check . "
              "--json reports/phase3/em_current_authority.json"),
        what="raise the peak power-grid segment current from 1.963e-04 A to "
             "5.0 A — a factor of about 25000 — in every place the report "
             "states it",
        breaks="an electromigration screen against a current the metal cannot "
               "carry. 5 A through a power-grid segment sized for microamps is "
               "not a marginal call; it is a part that fails in the field.",
        expected=REDDENS,
        red_signal="EM_PEAK_CURRENT_EXCEEDS_SUPPLY",
        observed="CLOSED 2026-08-11. The edits below are BYTE-IDENTICAL to the "
                 "ones that recorded CANNOT_REDDEN — only the gate this entry "
                 "re-runs, and the flow that wires it, changed. Step 25's gate "
                 "became an `all_of` and gained a clause that makes the number "
                 "reach a comparison: `em_peak_current_authority_check` "
                 "delegates the real per-layer J-vs-Jmax screen to "
                 "`em_current_density_check` (614 lines, previously with zero "
                 "references in the flow yaml) and, independently of any PDK, "
                 "screens the peak against the total current the SAME report "
                 "says the net is supplied with — Total power / Supply "
                 "voltage. 5 A against a net supplied with 7.44e-04 A is a "
                 "contradiction inside one artefact, and the limit is 1.0 "
                 "because it is conservation of charge, not a guardband. The "
                 "SIBLING clause `em_report_check` still cannot be moved by "
                 "this edit and that record stands; it was never the clause "
                 "that could.",
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=1,
            note="baseline INCOMPLETE (rc 0 — the Jmax authority is absent in "
                 "every published run, so the clause REFUSES rather than "
                 "passing), mutant FAIL rc 1 naming the injected 5.0 A against "
                 "the 7.4444e-04 A the report itself declares. Corpus blast "
                 "radius measured over 109 discovered published run roots "
                 "BEFORE the wiring: 0 PASS->FAIL at step 25. The peak/supply "
                 "ratio was adjudicated BY HAND on all 13 runs carrying an EM "
                 "report: 0.049-0.712, worst-case 29% headroom."),
    ),
    ArtefactMutation(
        name="ART-POWER-FIGURES-X1000",
        dim=2, step_id="33", run_dir=_RUN,
        artefact="reports/phase3/power.rpt",
        edits=(Edit("e-04", "e-01", 4), Edit("e-05", "e-02", 4),
               Edit("e-06", "e-03", 1), Edit("e-10", "e-07", 3)),
        what="multiply every non-zero figure in the OpenSTA power table by 1000 "
             "by shifting its exponent three decades — internal, switching, "
             "leakage and total, per group and in the Total row",
        breaks="a power report off by three orders of magnitude. The zeros are "
               "deliberately left alone, so the table stays internally "
               "consistent and a reader checking that the rows sum to the "
               "total finds nothing wrong.",
        gate=("power_total_vs_budget_check . "
              "--json reports/phase2/gates/power_budget.json"),
        expected=CANNOT_REDDEN,
        red_signal="",
        observed="STILL CANNOT REDDEN, AND THAT IS NOW THE CORRECT ANSWER "
                 "RATHER THAN A HOLE. Re-pointed 2026-08-11 at the clause step "
                 "33 gained for exactly this defect. The verdict no longer "
                 "moves because it is no longer a PASS: baseline INCOMPLETE, "
                 "mutant INCOMPLETE, both rc 0, and BOTH name the authority "
                 "the run does not have. `power_total_vs_budget_check` "
                 "compares total power against L19's `power_budget_uw` and "
                 "REFUSES when it is unset — MEASURED over the corpus, 0 of "
                 "the 17 published runs carrying a power report declare that "
                 "budget (3 of 195 L19 copies do, and that design publishes no "
                 "power report), so there is not one published run in which "
                 "the comparison could have been made. `flow_compliance_check` "
                 "now reports step 33 as INCOMPLETE rather than PASS on this "
                 "run. A budget is a REQUIREMENT that must arrive in the "
                 "design's own input documents; deriving one from die area, "
                 "supply voltage or a sibling tool's number would be a "
                 "threshold nobody declared, and a ruler fitted to this corpus "
                 "is worse than an admitted absence. The mutation WOULD redden "
                 "a run whose L19 states a budget — asserted directly in "
                 "`programs/tests/test_power_total_vs_budget_check.py`, which "
                 "is where that half of the predicate is proven, because the "
                 "corpus cannot prove it.",
        measured=Measurement(
            date="2026-08-11", command=_ARTEFACT_SWEEP, reddened=0,
            note="12 substitutions applied, exact-count checked; the 12 "
                 "`0.00e+00` entries are correctly untouched because zero "
                 "times 1000 is still zero. Corpus blast radius of the new "
                 "clause, measured over 109 discovered published run roots: "
                 "0 PASS->FAIL at step 33."),
    ),
)

#: How many artefact entries currently prove the cell they target CANNOT be
#: reddened from artefact content. PINNED, exactly like the emptiness of
#: :data:`NOT_FALSIFIABLE`, so the number can only move in a visible diff.
#: Closing one of these is Phase 1 work.
#:
#: 4 -> 1 on 2026-08-11, in three independent changes that each closed what they
#: measured: ART-ROUTER-FINAL-ITERATION and ART-NETLIST-PRIMITIVE-SWAP (the gate
#: believed a summary the runner wrote instead of the output the tool wrote),
#: then ART-EM-CURRENT-DENSITY (a peak current gained a declared authority to be
#: compared against). Each moved this number in the same change that closed its
#: entry, which is the whole point of pinning it.
#:
#: The one that remains is ART-POWER-FIGURES-X1000, and it is NOT open work in
#: the same sense. Its entry says why staying here is now the correct answer:
#: the cell REFUSES, naming the budget it lacks, and no published run declares
#: the budget that would let it redden. A cell that refuses is not a cell that
#: passes; this count is of cells that pass when they should not.
ARTEFACT_CANNOT_REDDEN_AS_MEASURED: int = 1

#: Cells no constructed mutation could redden. EMPTY as measured 2026-08-06.
#: An entry here is a finding to publish, never a reason to weaken a predicate.
#:
#: NOT the same statement as an ARTEFACT_MUTATION recorded CANNOT_REDDEN: this
#: list is about the dimension modules' own pytest cells, which every entry in
#: :data:`MUTATIONS` still reddens. The four artefact findings say something
#: narrower and newer — the cell cannot be reddened from the CONTENT of the
#: artefact its step publishes — and they are counted separately for exactly
#: that reason.
NOT_FALSIFIABLE: Tuple[NotFalsifiable, ...] = ()

#: The (steps, dimensions, ENFORCED cells) the ledger was built against. Like
#: ``GRID_AS_MEASURED`` in the coverage meta-test, this is the review gate and
#: never an input: every count below is recomputed live.
#:
#: MOVED 481 -> 482 on 2026-08-11, and the move is a FINDING rather than an
#: accommodation, so it is landed in its own commit with the cause named. The
#: grid did not grow a step (63 both before and after) and no cell was waived
#: away; ONE cell changed state. ``332b9985`` ("flow: stage membership was
#: declared twice and the copies disagreed") gave step P0 ``blocks_on: [1]``,
#: which took P0's dimension-5 cell from NA to ENFORCED. Bisected over the 15
#: commits that touched the flow or the dimension modules between ``0387e67a``
#: (where 481 was authored and was CORRECT — 12/d2 WAIVED, 12/d5 ENFORCED,
#: P0/d5 NA) and today: ``23d96bf5`` swapped step 12 between dimensions 2 and 5
#: for a net change of zero, and ``332b9985`` is the only commit that moved the
#: total. Neither re-ran the ledger's sweep, which is why the arithmetic sat
#: one short for three days rather than failing on the day it drifted.
#:
#: The +1 is COVERED, not merely counted: ``D5-PHANTOM-EDGE`` was replayed
#: against P0 on 2026-08-11 and REDDENED it. Raising this number without that
#: replay would be exactly the "widen the baseline until it is green" move the
#: gate exists to refuse.
LEDGER_AS_MEASURED: Tuple[int, int, int] = (63, 8, 482)


# ══════════════════════════════════════════════════════════════════════
# Lookups
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def by_name() -> Dict[str, Any]:
    """Every entry of every channel, by name. Names are globally unique so that
    ``--replay <NAME>`` means one thing; the uniqueness is asserted by the gate
    rather than assumed here."""
    out: Dict[str, Any] = {m.name: m for m in MUTATIONS}
    out.update({m.name: m for m in ARTEFACT_MUTATIONS})
    return out


def mutation(name: str) -> Any:
    try:
        return by_name()[name]
    except KeyError:
        raise KeyError(f"no mutation named {name!r}; known: "
                       f"{sorted(by_name())}") from None


def artefact_mutations_for(sid: str, dim: int) -> Tuple[ArtefactMutation, ...]:
    """Every ARTEFACT_MUTATION entry that targets ``(step, dim)``.

    Deliberately NOT folded into :func:`mutations_covering`. That function
    answers "which entry reddens this cell's pytest item", and an artefact entry
    answers a different question about a different instrument — half of them
    answer *no*. Letting them count as coverage would make the census read
    healthier for having recorded a gap.
    """
    key = (str(sid), int(dim))
    return tuple(m for m in ARTEFACT_MUTATIONS if m.cell == key)


def artefact_findings() -> Tuple[ArtefactMutation, ...]:
    """The entries that prove the cell they target CANNOT redden. THE FINDING."""
    return tuple(m for m in ARTEFACT_MUTATIONS if m.proves_cell_cannot_redden)


def artefact_headline() -> str:
    """The one line this channel is for, fit for the README."""
    return (f"{len(ARTEFACT_MUTATIONS)} artefact mutations registered; "
            f"{len(artefact_findings())} currently prove the cell they target "
            f"cannot redden.")


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


def artefact_run_root(mut: ArtefactMutation) -> Path:
    return benchmark_data_root() / mut.run_dir


def resolve_artefact(mut: ArtefactMutation,
                     doc: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """``None`` when the entry could be replayed RIGHT NOW; else why it cannot.

    This is LOCK 1 for the third channel, and it is four independent checks
    because an artefact entry can rot in four unrelated ways:

      1. the published run was moved or deleted;
      2. the file inside it was renamed;
      3. the artefact was REGENERATED and the bytes the edit names are gone, or
         now occur a different number of times — the exact-count requirement is
         what turns "the number moved" into a refusal rather than a silent edit
         of a different set of sites than the one that was measured;
      4. the FLOW no longer wires the gate the entry re-runs, or wires it with
         different arguments. Matched verbatim against
         :func:`step_gate_commands`, so a renamed flag is a resolution failure
         and not a replay that quietly measures a command nobody issues.

    Whatever it returns is a REASON, and the caller reports NOT_REPLAYABLE with
    it. Nothing here is ever a skip.
    """
    root = artefact_run_root(mut)
    if not root.is_dir():
        return (f"published run {mut.run_dir!r} is not a directory under "
                f"{benchmark_data_root()} — the entry names a run this "
                f"checkout does not have")
    target = root / mut.artefact
    if not target.is_file():
        return (f"{mut.artefact!r} does not exist in {mut.run_dir!r}; the "
                f"artefact the edit names was renamed or removed")
    doc = doc if doc is not None else load_flow()
    if step_by_id(doc, mut.step_id) is None:
        return (f"step {mut.step_id} is not declared in {flow_yaml_path()}")
    wired = step_gate_commands(mut.step_id, doc)
    if mut.gate not in wired:
        return (f"step {mut.step_id}'s gate no longer wires this command "
                f"verbatim: {mut.gate!r}. The flow declares "
                f"{list(wired)!r}, so the recorded verdict is about a gate "
                f"invocation the flow no longer issues")
    if _gate_program_path(mut.gate) is None:
        return (f"the gate program {mut.gate.split()[0]!r} does not exist "
                f"under {PLUGIN_ROOT / 'programs'} — the tool the entry "
                f"measures is absent, so its verdict cannot be reproduced")
    try:
        text = target.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:  # pragma: no cover - defensive
        return f"cannot read {mut.artefact}: {exc}"
    for i, edit in enumerate(mut.edits):
        hits = text.count(edit.frm)
        if hits != edit.count:
            return (f"edit #{i} expects {edit.count} occurrence(s) of "
                    f"{edit.frm[:60]!r} in {mut.artefact} and the published "
                    f"file has {hits}; the artefact changed under the entry "
                    f"and the recorded edit no longer lands where it was "
                    f"measured")
    return None


def _gate_program_path(cmd: str) -> Optional[Path]:
    """The program file a gate command names, resolved the way the flow does."""
    parts = cmd.split()
    if not parts:
        return None
    name = parts[0]
    path = (PLUGIN_ROOT / "programs" /
            (name if name.endswith(".py") else f"{name}.py"))
    return path if path.is_file() else None


def unresolved() -> Tuple[Tuple[str, str, str], ...]:
    """``((mutation name, step, problem), ...)`` over the WHOLE ledger.

    Covers all three channels: the yaml/tree entries per (entry, step) pair and
    the artefact entries per entry, since an artefact entry claims one cell.
    """
    doc = load_flow()
    out: List[Tuple[str, str, str]] = []
    for m in MUTATIONS:
        for sid in m.applies_to:
            problem = resolve(m, sid, doc)
            if problem:
                out.append((m.name, sid, problem))
    for a in ARTEFACT_MUTATIONS:
        problem = resolve_artefact(a, doc)
        if problem:
            out.append((a.name, a.step_id, problem))
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
    #: What the ledger RECORDED for this pair. ``REDDENED`` for every FLOW_YAML
    #: and PLUGIN_TREE entry — those channels have no other expressible answer —
    #: and either value for an ARTEFACT_MUTATION entry.
    expected: str = "REDDENED"
    #: Set when the replay could not be performed at all. Carries the reason, and
    #: makes :attr:`as_recorded` False, so a replay that could not run is never
    #: a quiet pass.
    not_replayable: str = ""
    channel: str = FLOW_YAML

    @property
    def proved(self) -> bool:
        """The cell went PASS -> FAIL, and failed for the declared reason."""
        return (self.applied and not self.not_replayable
                and self.baseline_rc == 0
                and self.mutant_rc not in (None, 0) and self.signal_seen)

    @property
    def verdict(self) -> str:
        if self.not_replayable:
            return "NOT_REPLAYABLE"
        if self.proved:
            return "REDDENED"
        if not self.applied:
            return "NO_EDIT_SITE"
        if self.baseline_rc != 0:
            return ALREADY_RED
        if self.mutant_rc in (None, 0):
            return "STAYED_GREEN"
        return "RED_FOR_ANOTHER_REASON"

    @property
    def unmeasurable(self) -> bool:
        """The witness was red BEFORE the edit, so nothing was demonstrated.

        Distinct from :attr:`proved` being False. A pair that stays green under
        a mutation is a finding about the GATE; a pair whose baseline was
        already red is a finding about the TREE, and reading the second as the
        first is how a red witness comes to look like a gate that lost its
        teeth (vibe-ic#1432).

        Deliberately NOT a skip: these are counted, disclosed and ratcheted by
        `test_the_replay_actually_ran_and_is_not_starved`, because a gate that
        stops catching AND whose witness happens to be red must not become
        invisible.
        """
        return self.verdict == ALREADY_RED

    @property
    def as_recorded(self) -> bool:
        """The replay reproduced what the ledger RECORDED.

        For every FLOW_YAML and PLUGIN_TREE entry ``expected`` is ``REDDENED``
        and this is identical to :attr:`proved` — those channels are unchanged
        by the third one arriving. For an ARTEFACT_MUTATION entry recorded
        ``STAYED_GREEN`` this is the pin: the day the gate learns to notice, the
        verdict stops matching and the gate file says so by name.
        """
        return self.verdict == self.expected


def _cell_rc_from_report(junit: Path, proc_rc: int) -> Tuple[Optional[int], str]:
    """``(cell rc, why-unreadable)`` from pytest's OWN report of the one cell.

    ``0``/``1`` is the CELL's colour. ``None`` means the report did not carry
    exactly one testcase, and the reason is returned rather than folded into a
    colour — a replay that could not read its cell must be NOT_REPLAYABLE, never
    a quiet ALREADY_RED.

    A ``skipped`` testcase maps to 0, which is what the exit status already
    said: the two locks that consume this ask whether the cell went PASS ->
    FAIL, and a skip is not a fail. It is only ever a witness's BASELINE that
    could be skipped, and LOCK 2's `proved` still requires the mutant arm to go
    non-zero with the declared signal, so a skip cannot manufacture a red.
    """
    if not junit.is_file():
        return None, (f"pytest wrote no report (process rc={proc_rc}) — the "
                      f"session died before it could record the cell")
    try:
        cases = ET.parse(junit).getroot().iter("testcase")
    except ET.ParseError as exc:
        return None, f"pytest report unparseable (process rc={proc_rc}): {exc}"
    cases = list(cases)
    if len(cases) != 1:
        return None, (f"pytest reported {len(cases)} testcase(s), not 1 "
                      f"(process rc={proc_rc}) — the nodeid selected nothing, "
                      f"or collection produced more than the cell")
    bad = [c for c in cases[0] if c.tag in ("failure", "error")]
    return (1 if bad else 0), ""


def _run_cell(dim: int, sid: str, cwd: Path, flow_override: Optional[Path],
              timeout: int) -> Tuple[Optional[int], str, str]:
    """Run the one cell and return ``(cell rc, output, why-unreadable)``.

    THE COLOUR COMES FROM THE REPORT, NOT FROM THE EXIT STATUS (vibe-ic#1412).
    A pytest process exits non-zero for the cell OR for anything the SESSION
    decided, and the two are not the same claim. The measured instance: the
    plugin's own ``conftest.py`` loads ``suite_write_guard``, which discovers
    its subject with ``git rev-parse --show-toplevel`` from its own file. In the
    ``cp -al`` mirror this function is handed, that resolves to whatever
    repository happens to enclose ``TMPDIR`` — and the mirror's own
    ``__pycache__`` is UNTRACKED there whenever that repository's ignore rules
    are not this one's, so the guard sets ``session.exitstatus = 1`` while the
    cell itself reports ``1 passed``. LOCK 2 then read ``baseline rc=1`` and
    called a green cell ALREADY_RED — on clean main, for no reason but where
    the operator's scratch directory sat.

    Both directions were broken, and the other one is worse: a mutant arm whose
    session went red for its own reasons, with the declared ``red_signal``
    string anywhere in the output, would have been recorded REDDENED for a
    mutation that moved nothing.

    ``PYTEST_DISABLE_PLUGIN_AUTOLOAD`` already pins what the child loads from
    the HOST for exactly this reason; this pins what it loads from the REPO.
    The output is still the whole stdout+stderr, because ``red_signal`` is
    matched against it.
    """
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if flow_override is None:
        env.pop(FLOW_YAML_ENV, None)
    else:
        env[FLOW_YAML_ENV] = str(flow_override)
    # OUTSIDE `cwd`: the report is this function's instrument, and an instrument
    # that lands in the tree under measurement perturbs the next gate to look.
    holder = Path(tempfile.mkdtemp(prefix="matmut_cellreport_"))
    junit = holder / "cell.xml"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", cell_nodeid(dim, sid),
             "-q", "-p", "no:randomly", "--no-header", "-rN",
             "--junit-xml", str(junit)],
            cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
            env=env)
        out = (proc.stdout or "") + (proc.stderr or "")
        rc, why = _cell_rc_from_report(junit, proc.returncode)
        return rc, out, why
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def replay(mut: Mutation, sid: Optional[str] = None,
           timeout: int = 900) -> ReplayResult:
    """Perform the mutation FOR REAL on an isolated copy and measure the cell.

    Never writes to the shared worktree. FLOW_YAML entries write one mutated
    yaml into a scratch dir and feed it through :data:`FLOW_YAML_ENV`;
    PLUGIN_TREE entries build a ``cp -al`` hardlink mirror of the plugin and
    unlink-then-write inside it. Both are removed afterwards.

    ARTEFACT_MUTATION entries are dispatched to :func:`replay_artefact`, which
    copies a published run FOR REAL — see its docstring for why a hardlink
    mirror is unsafe there and safe here.
    """
    import time
    if isinstance(mut, ArtefactMutation):
        return replay_artefact(mut, timeout=timeout)
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
            base_rc, _, base_why = _run_cell(
                mut.dim, sid, PLUGIN_ROOT, None, timeout)
            mut_rc, out, mut_why = _run_cell(
                mut.dim, sid, PLUGIN_ROOT, mutant, timeout)
            patched = "flow/phase1_phase2_phase3.yaml (substituted)"
        else:
            mirror = scratch / "mirror"
            subprocess.run(["cp", "-al", str(PLUGIN_ROOT), str(mirror)],
                           check=True, capture_output=True)
            for pyc in mirror.rglob("__pycache__"):
                shutil.rmtree(pyc, ignore_errors=True)
            base_rc, _, base_why = _run_cell(mut.dim, sid, mirror, None, timeout)
            patched = apply_to_tree(mut, mirror)
            if patched is None:
                return ReplayResult(
                    mut.name, mut.dim, sid, False, base_rc, None, False,
                    f"anchor for {mut.name} is absent or not unique in "
                    f"{mut.params.get('file')}", time.time() - started,
                    "REDDENED",
                    f"baseline arm: {base_why}" if base_why else "",
                    mut.channel)
            for pyc in mirror.rglob("__pycache__"):
                shutil.rmtree(pyc, ignore_errors=True)
            mut_rc, out, mut_why = _run_cell(mut.dim, sid, mirror, None, timeout)
        seen = mut.red_signal in out
        tail = "\n".join(l for l in out.strip().splitlines() if l.strip())[-1200:]
        # An arm whose cell could not be READ has no colour, and a colourless
        # arm must not be scored. NOT_REPLAYABLE carries the reason; silence
        # here is how "could not look" becomes "looked and it was red".
        unreadable = "; ".join(
            f"{arm} arm: {why}"
            for arm, why in (("baseline", base_why), ("mutant", mut_why)) if why)
        return ReplayResult(
            mut.name, mut.dim, sid, True, base_rc, mut_rc, seen,
            f"patched {patched}; baseline rc={base_rc}, mutant rc={mut_rc}, "
            f"red_signal {mut.red_signal!r} "
            f"{'present' if seen else 'ABSENT'}"
            f"{('; UNREADABLE — ' + unreadable) if unreadable else ''}"
            f"\n--- mutant tail ---\n{tail}",
            time.time() - started, "REDDENED", unreadable, mut.channel)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------
# ARTEFACT_MUTATION replay
# ---------------------------------------------------------------------
def _flow_module():
    """``flow_compliance_check``, imported lazily.

    The replay uses the FLOW'S OWN verdict mapping rather than a raw exit code,
    because the flow does not treat every non-zero rc as a failure: rc 2 is
    VACUOUS_PASS and rc 3 with the waiver sentinel is PASS_WITH_WAIVERS, and
    both count as PASS at the step. An artefact entry that scored a raw rc could
    therefore claim a red the flow would never honour. Import is ~0.07 s.
    """
    programs = str(PLUGIN_ROOT / "programs")
    if programs not in sys.path:
        sys.path.insert(0, programs)
    import flow_compliance_check  # noqa: PLC0415 - deliberately lazy
    return flow_compliance_check


def _run_gate(cmd: str, project: Path) -> Tuple[int, str]:
    """Run one gate command against ``project``. ``(0|1, FULL output)``.

    ``0`` means the FLOW would call this clause satisfied. The argv and the
    rc-to-verdict mapping both come from ``flow_compliance_check`` rather than
    being re-invented here — this must run the gate exactly as the flow runs it,
    or a recorded red is a red in a harness nobody ships.

    The one thing NOT delegated is the output: the flow truncates its snippet
    for its report, and a truncated snippet made ``red_signal`` matching a
    function of where the interesting line happened to fall. The full stdout and
    stderr are returned so the signal check means what it says.
    """
    fcc = _flow_module()
    argv = fcc._resolve_program_cmd(cmd, cwd=project)
    if not argv:
        return 1, f"program not found: {cmd.split()[0]}"
    proc = subprocess.run(argv, cwd=str(project), capture_output=True,
                          text=True, timeout=fcc._pl.gate_timeout_s())
    out = (proc.stdout or "") + (proc.stderr or "")
    rc = proc.returncode
    if rc == 0 or rc == 2:                       # 2 = VACUOUS_PASS
        return 0, out
    if rc == fcc._WAIVER_EXIT_CODE and fcc._stdout_signals_waiver(proc.stdout):
        return 0, out                            # 3 + sentinel = WITH_WAIVERS
    return 1, out


def _copy_published_run(src: Path, dst: Path) -> None:
    """A REAL copy of a published run. Never a hardlink mirror.

    The PLUGIN_TREE channel gets away with ``cp -al`` because the LEDGER is the
    only writer into that mirror and it unlinks before writing. This channel
    cannot: its replay RUNS GATE PROGRAMS inside the copy, and those programs
    write their own JSON reports into ``reports/`` with an ordinary open-for-
    write. Through a hardlink that truncates the PUBLISHED file.

    MEASURED, not reasoned: an earlier draft of this replay used ``cp -al`` and
    left eight JSON artefacts of the published run modified in the worktree
    (`git status` named them; they were restored from HEAD).

    DELEGATED to :func:`_run_isolation.copy_run` (#996). That module is where
    this hazard is now stated once, because three separate pieces of work hit
    it on one day and each wrote its own careful treatment. The behaviour is
    unchanged in the direction that matters — a real copy, refused if it shares
    an inode with the source — and STRENGTHENED in one: the shared helper
    compares the ``(dev, ino)`` sets of the whole tree, where the check below
    looks at ``st_nlink`` of the single edited artefact. A published run whose
    OTHER files were hardlinked would have passed here and does not there.
    """
    _iso.copy_run(src, dst)


def _stat_manifest(root: Path) -> Dict[str, Tuple[int, int]]:
    """``{relative path: (size, mtime_ns)}`` for every file under ``root``.

    Taken before and after a replay and compared. Cheap (one ``stat`` per file,
    no reads) and it catches the failure that actually happened: a gate program
    truncating a shared inode. A pure "did we copy correctly" assertion would
    not have — the copy was correct; the SHARING was the defect.

    DELEGATED to :func:`_run_isolation.snapshot` (#996), narrowed back to the
    ``(size, mtime_ns)`` pair this module compares so the equality below keeps
    meaning exactly what it did. The shared snapshot also carries ``dev``/``ino``,
    which are deliberately dropped here: an inode number changing under an
    unchanged size and mtime is a re-copy, not a perturbation of the content
    this replay is measuring.
    """
    return {k: (s.size, s.mtime_ns) for k, s in _iso.snapshot(root).items()}


def replay_artefact(mut: ArtefactMutation, timeout: int = 900) -> ReplayResult:
    """Change the number in the published report, and ask the gate.

    Copy the run, run the step's gate (must PASS — a mutation against an
    already-red gate proves nothing and is reported ALREADY_RED, never skipped),
    apply the byte edits, run the same gate again, and record whether the
    verdict moved. The published run is stat-manifested before and after and the
    two must be identical.

    ``timeout`` is accepted for symmetry with :func:`replay`; the per-gate
    budget is the flow's own (``VIBE_IC_GATE_TIMEOUT_S``, default 900 s),
    because the point is to run the gate exactly as the flow runs it.
    """
    import time
    started = time.time()

    def fail(reason: str) -> ReplayResult:
        return ReplayResult(mut.name, mut.dim, str(mut.step_id), False, None,
                            None, False, reason, time.time() - started,
                            mut.expected, reason, ARTEFACT_MUTATION)

    problem = resolve_artefact(mut)
    if problem:
        return fail(problem)

    src = artefact_run_root(mut)
    before = _stat_manifest(src)
    scratch = Path(tempfile.mkdtemp(prefix=f"artmut_{mut.name}_"))
    try:
        run = scratch / "run"
        _copy_published_run(src, run)
        target = run / mut.artefact
        if target.stat().st_nlink != 1:
            return fail(
                f"the copy of {mut.artefact} shares its inode with the "
                f"published run (st_nlink={target.stat().st_nlink}); writing "
                f"it would modify benchmark-data in place")

        base_rc, base_out = _run_gate(mut.gate, run)
        if base_rc != 0:
            return ReplayResult(
                mut.name, mut.dim, str(mut.step_id), True, base_rc, None, False,
                f"the gate is ALREADY failing on the unmutated run: "
                f"{mut.gate}\n{base_out[-1200:]}",
                time.time() - started, mut.expected, "", ARTEFACT_MUTATION)

        text = target.read_text(encoding="utf-8", errors="surrogateescape")
        for i, edit in enumerate(mut.edits):
            hits = text.count(edit.frm)
            if hits != edit.count:
                return fail(f"edit #{i} found {hits} site(s), recorded "
                            f"{edit.count} (checked again on the copy)")
            text = text.replace(edit.frm, edit.to)
        target.unlink()
        target.write_text(text, encoding="utf-8", errors="surrogateescape")

        mut_rc, mut_out = _run_gate(mut.gate, run)
        seen = bool(mut.red_signal) and mut.red_signal in mut_out
        # A signal that is present in the BASELINE output too proves nothing
        # about the mutation. Free two-arm control, inside every replay.
        seen_at_baseline = bool(mut.red_signal) and mut.red_signal in base_out
        if mut.expected == REDDENS and seen_at_baseline:
            return fail(f"red_signal {mut.red_signal!r} is present in the "
                        f"UNMUTATED run's gate output too, so it cannot "
                        f"evidence the mutation")
        tail = "\n".join(l for l in mut_out.strip().splitlines()
                         if l.strip())[-1200:]
        detail = (f"run {mut.run_dir} -> copy; edited {mut.artefact} "
                  f"({sum(e.count for e in mut.edits)} site(s)); gate "
                  f"{mut.gate.split()[0]}: baseline PASS, mutant "
                  f"{'FAIL' if mut_rc else 'PASS'}; red_signal "
                  f"{mut.red_signal!r} "
                  f"{'present' if seen else 'absent'}\n"
                  f"--- mutant gate output tail ---\n{tail}")
        return ReplayResult(
            mut.name, mut.dim, str(mut.step_id), True, base_rc, mut_rc,
            seen if mut.expected == REDDENS else True, detail,
            time.time() - started, mut.expected, "", ARTEFACT_MUTATION)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        after = _stat_manifest(src)
        if after != before:
            changed = sorted(set(before) ^ set(after)) or sorted(
                k for k in before if before[k] != after.get(k))
            raise RuntimeError(
                f"{mut.name}: the PUBLISHED run {mut.run_dir} changed during "
                f"its own replay — {changed[:12]}. A replay that edits the "
                f"corpus it measures has destroyed the thing it was proving.")


def replay_mode() -> str:
    return os.environ.get(REPLAY_ENV, "witness").strip().lower() or "witness"


def replay_plan(mode: Optional[str] = None) -> Tuple[Tuple[str, str], ...]:
    """``((mutation name, step), ...)`` the current mode will re-execute.

    EVERY artefact entry is in BOTH modes. That is not an oversight and it is
    not free — see the cost note in the module docstring. An artefact entry
    claims exactly one cell, so ``witness`` and ``all`` cannot differ for it,
    and an entry that is only re-executed in an audit mode nobody runs is the
    asserted-but-never-run mutation this ledger was built to refuse.
    """
    mode = (mode or replay_mode())
    if mode not in REPLAY_MODES:
        raise ValueError(
            f"{REPLAY_ENV}={mode!r} is not one of {REPLAY_MODES}. The replay "
            f"lock has no off switch: an entry nobody re-executes is exactly "
            f"the asserted-but-never-run mutation this ledger refuses.")
    artefacts = tuple((m.name, m.witness) for m in ARTEFACT_MUTATIONS)
    if mode == "all":
        return tuple((m.name, s)
                     for m in MUTATIONS for s in m.applies_to) + artefacts
    return tuple((m.name, m.witness) for m in MUTATIONS) + artefacts


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
        "artefact": {
            "registered": len(ARTEFACT_MUTATIONS),
            "reddens": len(ARTEFACT_MUTATIONS) - len(artefact_findings()),
            "cannot_redden": len(artefact_findings()),
            "cannot_redden_cells": [f"{m.step_id}/d{m.dim}:{m.name}"
                                    for m in artefact_findings()],
            "runs": sorted({m.run_dir for m in ARTEFACT_MUTATIONS}),
            "benchmark_data": str(benchmark_data_root()),
            "headline": artefact_headline(),
        },
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
    ap.add_argument("--replay-artefacts", action="store_true",
                    help="replay every ARTEFACT_MUTATION entry")
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

    if a.census or not (a.resolve or a.replay or a.replay_witnesses
                        or a.replay_artefacts):
        rep = census()
        report["census"] = rep
        print(f"=== matrix_mutation_ledger ({rep['flow_yaml']}) ===")
        print(f"  {rep['steps']} steps x {rep['dimensions']} dimensions = "
              f"{rep['grid']} cells; {rep['entries']} mutation entries")
        for d, per in rep["per_dimension"].items():
            print(f"  {d}: {per['covered']}/{per['considered']} cells carry a "
                  f"named mutation  [{', '.join(per['entries'])}]")
        art = rep["artefact"]
        print(f"  ARTEFACT_MUTATION: {art['headline']}")
        for line in art["cannot_redden_cells"]:
            print(f"    CANNOT REDDEN FROM ARTEFACT CONTENT: {line}")
        print(f"  replay mode: {rep['replay_mode']} "
              f"({rep['replay_pairs']} pair(s) re-executed per run)")
        if rep["not_falsifiable"]:
            print(f"  NOT-FALSIFIABLE: {rep['not_falsifiable']}")

    if a.resolve:
        bad = unresolved()
        report["unresolved"] = [
            {"mutation": n, "step": s, "problem": p} for n, s, p in bad]
        pairs = (sum(len(m.applies_to) for m in MUTATIONS)
                 + len(ARTEFACT_MUTATIONS))
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
    elif a.replay_artefacts:
        plan = [(m.name, m.witness) for m in ARTEFACT_MUTATIONS]

    if plan:
        print(f"\nLOCK 2 — replaying {len(plan)} (entry, step) pair(s), "
              f"jobs={a.jobs}")
        results = replay_many(plan, jobs=a.jobs, timeout=a.timeout)
        report["replay"] = [r.__dict__ | {"verdict": r.verdict} for r in results]
        for r in results:
            # `as_recorded`, not `proved`: an ARTEFACT_MUTATION entry that
            # RECORDS `STAYED_GREEN` is reproducing a published finding when it
            # stays green, and reporting it as a failure would push an author
            # toward deleting the record instead of closing the gap.
            mark = "ok  " if r.as_recorded else "FAIL"
            note = ("" if r.expected == "REDDENED"
                    else "  [recorded finding: the cell CANNOT redden]")
            print(f"  [{mark}] {r.mutation} @ step {r.step_id}: {r.verdict} "
                  f"({r.seconds:.1f}s){note}")
            if not r.as_recorded:
                rc = 1
                print(f"        expected {r.expected}, got {r.verdict}")
                print("        " + r.detail.replace("\n", "\n        "))

    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
