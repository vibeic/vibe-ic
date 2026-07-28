"""test_matrix_d5_deps_correct.py — DIMENSION 5 of the 63 x 8 matrix.

    "Is ``blocks_on`` the true upstream set — no missing edge, no phantom edge?"

One parametrized cell per flow step (63). Every predicate is **recomputed live
from the current source tree** — the flow yaml and the gate programs' ASTs.
Nothing here reads ``.audit_63x8.json``; the audit is history, and asserting on
a stored verdict would measure a JSON file rather than the repository. (Proof
that this matters: the July audit filed step 1/d5 as a DEFECT for omitting the
``D1`` edge. On the current tree step 1 declares ``blocks_on: [D1]`` — the
defect is fixed, and a test that asserted the stored ``DEFECT`` would now be
lying in the opposite direction.)

====================================================================
WHAT "THE TRUE UPSTREAM SET" IS MEASURED AS
====================================================================
The real data-dependency graph:

    producer(X) = the step that declares X in its ``required_outputs``
    consumer(X) = a step that READS X

and the invariant: for every ``(producer P, consumer C)`` pair with ``P != C``,
``P`` must lie in the transitive closure of ``C``'s ``blocks_on``. A consumer
that reads an artefact whose producer it does not block on can run before that
artefact exists — which either crashes or, worse, silently reads a **stale**
artefact left by a previous run and signs off on it.

``producer`` is exact and comes from the yaml: every ``required_outputs`` entry
of every step, split on the literal ``" OR "`` the real consumer splits on
(:func:`flowref.split_any_of`), giving 156 alternatives over 154 distinct paths.

``consumer`` cannot be read off the yaml alone, so it is derived by two
independent layers, both live:

**Layer 1 — YAML-DECLARED READS (exact).** Paths the step's own gate names as
things it looks at: ``files_exist`` entries, ``condition_files_exist`` of an
``optional_program_exit_zero`` clause, the step-level ``condition.files_exist``,
and path-shaped arguments of gate commands. Matched by **exact string
equality** against a producer entry — no directory-containment, no fuzzy
prefixing. (Containment was tried and rejected: step 21 scans the directory
``phase3/stage3/pnr`` with ``--under``, and step 34 later writes
``filled.def`` into it. "21 reads a directory 34 writes into" is not "21
depends on 34", and counting it as one would be exactly the adjacent
measurement this campaign exists to stamp out.)

The value of a ``--json`` flag is excluded: across all 137 gate commands every
one of the 107 distinct ``--json`` values is the checker's own report under
``reports/``, and each of the 11 that collides with a declared artefact
collides with the *same* step's — i.e. it is an OUTPUT, never a read.
``provenance_check``'s ``--output`` is deliberately NOT excluded: there
``--output`` names the artefact whose provenance is being *verified*, i.e. read.

**Layer 2 — GATE-PROGRAM BASENAME ANCHOR.** The step's resolved gate programs
are parsed with :mod:`ast` (never regex-grepped: comments are gone by
construction, and PR #460 is the standing lesson about text scans in a tree
that dispatches dynamically). A program is taken to read artefact ``A`` when
the exact basename of ``A`` occurs as a **standalone string constant** and:

  * ``basename(A)`` is unique across all 154 declared artefacts and carries no
    wildcard — so ``netlist.v`` (steps 9 and 14), ``results.xml``, ``pass.flag``
    and ``*.sp`` are all out of scope by construction rather than by guesswork;
  * the constant is not a bare-expression **docstring** (``ast.Expr`` whose
    value is a string) — ``analog_a5_layout_check``'s module docstring names
    ``drc_clean.flag`` nine times before line 237 constructs the real path;
  * the constant does not occur *only* inside a ``not in`` container — in
    ``spare_cell_preservation_check`` the names ``post_cts.def`` and
    ``post_hold.def`` appear solely in an EXCLUSION list
    (``d.name not in (...)``), which is the opposite of a read.

Both layers then drop two classes of non-dependency:

  * ``P == C`` (a step reading what it produces), and
  * ``C`` is itself a declared producer of ``A`` (co-producers, e.g. steps 9 and
    14 both declare ``phase2/stage2/synth/netlist.v``; A9 and M3 both declare
    ``phase3/mixed_signal/cosim/mixed_signal_results.json``). A co-producer of X
    does not depend on the *other* producer of X.

Measured on the current tree: **14 of 63 steps have at least one derived
cross-step data dependency**, carrying 19 distinct (consumer, producer) pairs
backed by 35 evidence rows.
That is the honest denominator of the layer-1+2 half of this dimension, and it
is stated in :func:`test_d5_derived_dependency_denominator_is_disclosed` so it
can never quietly drift to zero and leave a suite of vacuous passes behind — the
exact shape of the failure this campaign was convened over (a runtime ordering
guard that saw 0 violations because it had been starved of its input).

====================================================================
WHY THAT DENOMINATOR IS NOT THE WHOLE TEST
====================================================================
For the other 49 steps the data-dependency clause is vacuously true, so each
cell additionally carries six structural predicates over the declared graph,
every one of them per-step falsifiable:

  D5-EDGE-UNRESOLVED   every ``blocks_on`` entry names a declared step, and does
                       so with the SAME RAW TYPE. ``flow_compliance_check``'s
                       cascade attribution keys ``parents_of`` on the raw id
                       (flow_compliance_check.py:6567-6575), so
                       ``blocks_on: ["9"]`` against ``id: 9`` resolves nowhere
                       and silently drops the edge, while
                       ``flow_step_execution_coverage_check.load_blocks_on``
                       stringifies and still sees it. Both consumers must agree.
  D5-SELF-EDGE         no step blocks on itself.
  D5-DUP-EDGE          no ``blocks_on`` list repeats a parent.
  D5-FORWARD-EDGE      every parent is DECLARED EARLIER in the yaml. The flow is
                       consumed in canonical declaration order
                       (flow_compliance_check.py:7046-7055) and #503 cascade
                       attribution takes the first FAIL per track walking that
                       same order (flow_compliance_check.py:6672-6690), so a
                       parent declared after its child can never cut its child's
                       cascade.
  D5-CYCLE             the step is not reachable from itself over ``blocks_on``.
  D5-ORPHAN            a non-root step's ancestry reaches a declared root (a step
                       that declares ``blocks_on: []``). D1 and A1 are the only
                       two; a step whose ancestry reaches neither is floating.
  D5-GRAPH-DISAGREE    the runtime consumer
                       ``flow_step_execution_coverage_check.load_blocks_on``
                       resolves this step's parents AND full ancestry
                       identically to the static graph.

====================================================================
CROSS-CHECK AGAINST THE RUNTIME GUARD (as instructed), AND THE DISAGREEMENT
====================================================================
``flow_step_execution_coverage_check`` enforces an ordering invariant at RUN
time. An earlier audit claim that the invariant was unenforced was wrong and was
publicly corrected — but that guard was starved by a separate defect and saw 0
ordering violations where there were 62, so nothing here delegates to it.

It is nonetheless cross-checked, per step, in ``D5-GRAPH-DISAGREE``. One
**disagreement is real and is reported rather than papered over**:
``load_blocks_on`` walks the WHOLE yaml document for any dict carrying ``id``
plus (``name`` or ``blocks_on``), so it admits 71 nodes where the flow declares
63 steps — the 8 extra are the stage grouping objects (``stage1`` … ``stage_phase1``).
They contribute 0 edges today and no stage id collides with a step id, so the
per-step graphs are identical (91 edges both sides). If a stage object ever took
a step's id, the runtime graph's entry for that step would be silently
overwritten; ``D5-GRAPH-DISAGREE`` is what would notice.

The two checks measure different things and neither is assumed right: this file
asks "does the DECLARED graph cover the REAL data flow", the runtime guard asks
"was the declared graph RESPECTED by an actual run".

====================================================================
KNOWN GAPS (stated so nobody mistakes a pass here for a proof)
====================================================================
1. Layer 2 is basename-anchored, so a read of an artefact whose basename is not
   unique across the flow (``netlist.v``, ``results.json``, ``pass.flag``,
   ``spec.json``, every ``*.<ext>`` glob — 41 of the 154 artefacts) is invisible
   to it. Making those visible needs full inter-procedural path resolution
   through ``_path_layout`` + ``_analog_a_check_common``; a prototype resolved
   68/154 full paths, i.e. strictly worse coverage than the basename anchor, so
   it was not shipped as a source of truth.
2. Only GATE programs are parsed. An artefact read by a step's *runner* (
   ``phase3_one_shot_runner`` and friends are not gate programs) is not seen.
3. "Reads" is not "hard-depends": layer 2 cannot tell a mandatory read from a
   best-effort one inside ``try/except`` — deliberately, because the stale-read
   hazard is identical either way, and ``sdc_exception_correlation_check``'s
   swallowed ``except (OSError, ValueError): pass`` is precisely how a missing
   upstream turns into a silently wrong advisory instead of a loud failure.
4. Phantom-edge detection is limited to unresolved / self / duplicate /
   forward-pointing edges. A *semantically* useless but harmless edge (step 11's
   ``blocks_on: [10]`` where the real need is step 9's netlist, or step 24's
   conservative ``[22]``) is NOT flagged: over-approximating a dependency is
   safe, and no program can distinguish "deliberately conservative ordering"
   from "wrong parent" without design intent.
"""
from __future__ import annotations

import ast
import functools
import shlex
from collections import Counter
from typing import Dict, List, Set, Tuple

import pytest

from matrix_63x8 import cells as C
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W

DIM = 5

# ══════════════════════════════════════════════════════════════════════
# Producers — exact, from the yaml
# ══════════════════════════════════════════════════════════════════════
_GLOB_CHARS = "*?["


def _norm_path(raw) -> str:
    """Normalise one declared/consumed path to a comparable relative form."""
    text = str(raw).strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


@functools.lru_cache(maxsize=1)
def producers() -> Dict[str, Tuple[str, ...]]:
    """``{artefact_path: (producing step ids, ...)}`` — live, from the yaml.

    Keys are the *alternatives* of each ``required_outputs`` entry, split on the
    literal ``" OR "`` exactly as ``flow_compliance_check`` splits them, because
    ``a OR b`` means "either satisfies this entry" and each alternative is a
    separately-nameable artefact.
    """
    acc: Dict[str, List[str]] = {}
    for sid in F.step_ids():
        for entry in F.required_outputs(sid):
            for alt in F.split_any_of(entry):
                key = _norm_path(alt)
                if not key:
                    continue
                who = acc.setdefault(key, [])
                if F.normalize_id(sid) not in who:
                    who.append(F.normalize_id(sid))
    return {k: tuple(v) for k, v in acc.items()}


@functools.lru_cache(maxsize=1)
def unique_basename_artefacts() -> Dict[str, str]:
    """``{basename: artefact}`` for artefacts whose basename is unambiguous.

    A basename shared by two artefacts (``netlist.v``) or carrying a wildcard
    (``*.sp``) cannot anchor a read to one producer, so it is excluded rather
    than guessed at. 113 of the 154 artefacts qualify on the current tree.
    """
    by_base: Dict[str, Set[str]] = {}
    for art in producers():
        base = art.rsplit("/", 1)[-1]
        by_base.setdefault(base, set()).add(art)
    return {
        base: next(iter(arts))
        for base, arts in by_base.items()
        if len(arts) == 1 and not any(ch in base for ch in _GLOB_CHARS)
    }


# ══════════════════════════════════════════════════════════════════════
# Layer 1 — reads the yaml itself declares
# ══════════════════════════════════════════════════════════════════════
#: Flag whose value is the checker's own report, never a read. Verified on the
#: current tree: all 107 distinct ``--json`` values live under ``reports/`` and
#: every collision with a declared artefact is with the SAME step's own output.
_OUTPUT_ONLY_FLAGS = ("--json",)


def _command_path_args(command: str) -> Set[str]:
    """Path-shaped arguments of one gate command, minus pure-output flags."""
    try:
        tokens = shlex.split(command)
    except ValueError:  # pragma: no cover - defensive: unbalanced quotes
        tokens = command.split()
    out: Set[str] = set()
    skip_next = False
    for tok in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if tok in _OUTPUT_ONLY_FLAGS:
            skip_next = True
            continue
        if any(tok.startswith(f + "=") for f in _OUTPUT_ONLY_FLAGS):
            continue
        if tok.startswith("--") and "=" in tok:
            tok = tok.split("=", 1)[1]
        elif tok.startswith("-"):
            continue
        if "/" in tok:
            out.add(_norm_path(tok))
    return out


@functools.lru_cache(maxsize=None)
def yaml_declared_reads(step_id) -> Tuple[str, ...]:
    """Paths the step's own gate/condition declares that it looks at."""
    out: Set[str] = set()
    for clause in F.gate_clauses(step_id):
        if clause.command:
            out |= _command_path_args(clause.command)
        out |= {_norm_path(p) for p in clause.files}
        out |= {_norm_path(p) for p in clause.condition_files}
    cond = F.step_condition(step_id)
    if cond:
        out |= {_norm_path(p) for p in (cond.get("files_exist") or [])}
    return tuple(sorted(p for p in out if p))


# ══════════════════════════════════════════════════════════════════════
# Layer 2 — reads visible in the gate programs' ASTs
# ══════════════════════════════════════════════════════════════════════
class ProgramUnparseable(Exception):
    """A gate program could not be parsed, so layer 2 is blind for its step."""


@functools.lru_cache(maxsize=None)
def program_string_constants(basename: str) -> frozenset:
    """Standalone string constants of ``programs/<basename>.py``.

    AST, not text: comments never enter, so the "``# e.g. \"foo_check\"`` counted
    as a call site" failure cannot recur. Two further classes are removed
    because they are provably not path construction:

      * bare-expression strings (module / function / class docstrings, and the
        free-standing comment-strings this codebase uses between defs), and
      * constants that appear ONLY as members of a ``not in`` container, which
        is an exclusion list — the opposite of a read.
    """
    path = F.program_path(basename)
    if path is None:  # pragma: no cover - unresolved gate programs are dim 1
        raise ProgramUnparseable(f"programs/{basename}.py does not exist")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        raise ProgramUnparseable(f"{path}: {exc}") from exc

    docstring_nodes = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }

    total: Counter = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_nodes:
                continue
            total[node.value] += 1
        elif isinstance(node, ast.JoinedStr):
            # f-strings: only the LITERAL segments are usable evidence; a
            # `{var}` hole is explicitly not resolved here (see known gap 1).
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    total[part.value] += 1

    excluded: Counter = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, ast.NotIn):
                continue
            if not isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                continue
            for element in comparator.elts:
                if isinstance(element, ast.Constant) and isinstance(
                    element.value, str
                ):
                    excluded[element.value] += 1

    return frozenset(
        text for text, count in total.items() if excluded[text] < count
    )


# ══════════════════════════════════════════════════════════════════════
# The derived data-dependency graph
# ══════════════════════════════════════════════════════════════════════
@functools.lru_cache(maxsize=None)
def derived_dependencies(step_id) -> Tuple[Tuple[str, str, str], ...]:
    """``((producer_step, artefact, evidence), ...)`` for one consumer step.

    Sorted and deduped. Excludes ``producer == consumer`` and any artefact the
    consumer itself co-produces.
    """
    consumer = F.normalize_id(step_id)
    prod = producers()
    found: Set[Tuple[str, str, str]] = set()

    for read in yaml_declared_reads(step_id):
        for producer in prod.get(read, ()):
            if producer == consumer or consumer in prod[read]:
                continue
            found.add((producer, read, f"yaml gate/condition declares '{read}'"))

    anchors = unique_basename_artefacts()
    for prog in F.gate_programs(step_id):
        constants = program_string_constants(prog)
        for base, art in anchors.items():
            if base not in constants:
                continue
            if consumer in prod[art]:
                continue
            for producer in prod[art]:
                if producer == consumer:
                    continue
                found.add(
                    (
                        producer,
                        art,
                        f"gate program {prog}.py names the string constant "
                        f"'{base}'",
                    )
                )
    return tuple(sorted(found))


# ══════════════════════════════════════════════════════════════════════
# The declared graph
# ══════════════════════════════════════════════════════════════════════
@functools.lru_cache(maxsize=1)
def declaration_order() -> Dict[str, int]:
    return {F.normalize_id(sid): i for i, sid in enumerate(F.step_ids())}


@functools.lru_cache(maxsize=1)
def raw_id_index() -> Dict[object, object]:
    """``{raw id: raw id}`` — identity map used to test RAW-TYPE resolution.

    ``flow_compliance_check`` keys its cascade graph on the untouched yaml id
    (``st.get("id")``), so ``blocks_on: ["9"]`` against ``id: 9`` is a dropped
    edge there even though the stringifying loader still sees it.
    """
    return {step["id"]: step["id"] for step in F.steps()}


@functools.lru_cache(maxsize=1)
def declared_graph() -> Dict[str, Tuple[str, ...]]:
    return {
        F.normalize_id(sid): tuple(F.normalize_id(e) for e in F.blocks_on(sid))
        for sid in F.step_ids()
    }


@functools.lru_cache(maxsize=None)
def ancestors(step: str) -> frozenset:
    """Transitive ``blocks_on`` closure of *step* (BFS, cycle-safe)."""
    graph = declared_graph()
    seen: Set[str] = set()
    queue = list(graph.get(step, ()))
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, ()))
    return frozenset(seen)


@functools.lru_cache(maxsize=1)
def declared_roots() -> Tuple[str, ...]:
    """Steps that declare ``blocks_on`` PRESENT-BUT-EMPTY — the graph's roots.

    Distinct from steps with no ``blocks_on`` key at all (P0): "this is a root"
    and "nobody wrote a dependency list" are different statements.
    """
    return tuple(
        F.normalize_id(sid)
        for sid in F.step_ids()
        if F.declares_blocks_on(sid) and not F.blocks_on(sid)
    )


@functools.lru_cache(maxsize=1)
def runtime_graph() -> Tuple[Dict[str, List[str]], str]:
    """The graph the RUN-TIME ordering guard builds from the same yaml.

    Imported lazily and read through ``F.FLOW_YAML`` at call time so a
    falsifiability run that repoints the substrate at a scratch copy is
    cross-checked against the same mutated file.
    """
    import flow_step_execution_coverage_check as runtime_check

    graph, provenance = runtime_check.load_blocks_on(F.FLOW_YAML)
    return graph, provenance


def _runtime_ancestors(step: str, graph: Dict[str, List[str]]) -> Set[str]:
    seen: Set[str] = set()
    queue = list(graph.get(step, []))
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, []))
    return seen


# ══════════════════════════════════════════════════════════════════════
# The predicate
# ══════════════════════════════════════════════════════════════════════
def d5_problems(step_id) -> List[str]:
    """Every dimension-5 defect of *step_id*, measured live. Empty == healthy.

    Each string names the MEASURED value, not the expectation.
    """
    sid = F.normalize_id(step_id)
    problems: List[str] = []
    order = declaration_order()
    graph = declared_graph()
    parents = graph[sid]

    # ── D5-EDGE-UNRESOLVED / D5-SELF-EDGE / D5-DUP-EDGE ──────────────
    raw_index = raw_id_index()
    raw_edges = list(F.step_by_id(step_id).get("blocks_on") or [])
    for raw in raw_edges:
        if raw not in raw_index:
            norm = F.normalize_id(raw)
            hint = (
                f" — a step {norm!r} exists but is declared as "
                f"{type(F.step_by_id(norm)['id']).__name__}, not "
                f"{type(raw).__name__}; flow_compliance_check.py:6567-6575 keys "
                f"the cascade graph on the RAW id, so this edge resolves to "
                f"nothing there"
                if F.has_step(norm)
                else " — no step with that id is declared at all"
            )
            problems.append(
                f"D5-EDGE-UNRESOLVED: step {sid} blocks_on {raw!r} "
                f"({type(raw).__name__}){hint}"
            )
    seen_counts = Counter(F.normalize_id(e) for e in raw_edges)
    for parent, count in sorted(seen_counts.items()):
        if count > 1:
            problems.append(
                f"D5-DUP-EDGE: step {sid} lists parent {parent!r} {count} times "
                f"in blocks_on {list(raw_edges)!r}"
            )
    if sid in seen_counts:
        problems.append(
            f"D5-SELF-EDGE: step {sid} blocks on itself (blocks_on="
            f"{list(raw_edges)!r})"
        )

    # ── D5-FORWARD-EDGE ──────────────────────────────────────────────
    for parent in parents:
        if parent == sid or parent not in order:
            continue
        if order[parent] > order[sid]:
            problems.append(
                f"D5-FORWARD-EDGE: step {sid} (yaml declaration index "
                f"{order[sid]}) blocks_on {parent!r}, which is declared LATER "
                f"at index {order[parent]}; the flow is evaluated in canonical "
                f"declaration order (flow_compliance_check.py:7046-7055) and "
                f"#503 cascade attribution takes the first FAIL per track in "
                f"that same order (flow_compliance_check.py:6672-6690), so "
                f"{parent!r} can never cut {sid}'s cascade"
            )

    # ── D5-CYCLE ─────────────────────────────────────────────────────
    if sid in ancestors(sid):
        cycle = sorted(a for a in ancestors(sid) if sid in ancestors(a))
        problems.append(
            f"D5-CYCLE: step {sid} is in its own blocks_on ancestry; the "
            f"mutually-reachable set is {cycle}"
        )

    # ── D5-ORPHAN ────────────────────────────────────────────────────
    roots = declared_roots()
    if sid not in roots:
        reached = ancestors(sid) & set(roots)
        if not reached:
            problems.append(
                f"D5-ORPHAN: step {sid}'s blocks_on ancestry "
                f"{sorted(ancestors(sid))} reaches none of the declared roots "
                f"{list(roots)}; it is not anchored to the flow's entry points"
            )

    # ── D5-MISSING-EDGE (the data-dependency invariant) ──────────────
    closure = ancestors(sid)
    for producer, artefact, evidence in derived_dependencies(step_id):
        if producer in closure:
            continue
        would_cycle = sid in ancestors(producer)
        would_be_forward = (
            producer in order and order[producer] > order[sid]
        )
        consequence = ""
        if would_cycle:
            consequence = (
                f"; the edge cannot simply be added — {producer} already has "
                f"{sid} in its own ancestry, so the real dependency is "
                f"CIRCULAR and one side of it is wrong"
            )
        elif would_be_forward:
            consequence = (
                f"; the edge cannot simply be added — {producer} is declared "
                f"LATER in the yaml (index {order[producer]} vs {order[sid]}), "
                f"so it would be a forward edge"
            )
        problems.append(
            f"D5-MISSING-EDGE: step {sid} reads '{artefact}', declared as a "
            f"required_output of step {producer}, but {producer} is not in "
            f"{sid}'s blocks_on closure (blocks_on={list(parents)}, closure="
            f"{sorted(closure)}). Evidence: {evidence}{consequence}"
        )

    # ── D5-GRAPH-DISAGREE (cross-check, not delegation) ──────────────
    rt_graph, provenance = runtime_graph()
    if provenance != "LOADED":
        problems.append(
            f"D5-GRAPH-DISAGREE: the run-time ordering guard "
            f"flow_step_execution_coverage_check.load_blocks_on returned "
            f"provenance {provenance!r} for {F.FLOW_YAML}, so it enforces "
            f"nothing about step {sid}"
        )
    else:
        rt_parents = list(rt_graph.get(sid, []))
        if rt_parents != list(parents):
            problems.append(
                f"D5-GRAPH-DISAGREE: static blocks_on for step {sid} is "
                f"{list(parents)} but the run-time guard's loader sees "
                f"{rt_parents}"
            )
        rt_anc = _runtime_ancestors(sid, rt_graph)
        if rt_anc != set(closure):
            problems.append(
                f"D5-GRAPH-DISAGREE: static ancestry of step {sid} is "
                f"{sorted(closure)} but the run-time guard's loader computes "
                f"{sorted(rt_anc)}"
            )

    return problems


# ═════════════════════════════════════════════════════════════════════
# Accepted gaps — ONE registry, the one that is consumed
# ═════════════════════════════════════════════════════════════════════
# This module used to carry a `_LOCAL_WAIVERS` mirror of its five dimension-5
# waivers, added while eight agents shared one worktree and a concurrent edit to
# `matrix_63x8.waivers.WAIVERS` could lose an entry. The orchestrator has since
# landed all five centrally, so `_waiver_for` read the central copy and ignored
# the local one — an edit to the mirror changed nothing a reader ever saw.
#
# #527 deleted the same structure from dimension 3 after its two copies were
# found telling different stories about one accepted gap. The mirror is deleted
# rather than re-synchronised: a waiver is a public admission, and it can have
# exactly one text.
#
# Every one of these waivers is a LIVE, REPRODUCED defect, not an
# un-mechanisable cell: the predicate genuinely fails on the current tree.
# ``strict=True`` is therefore load-bearing in the strongest way — the day the
# dependency is fixed, the cell XPASSes, the suite goes red, and the waiver must
# be deleted.


def dim_waivers() -> Tuple[W.Waiver, ...]:
    """This dimension's waivers, from the one registry that is consumed."""
    return tuple(W.waivers_for_dim(DIM))


def _waiver_for(step_id):
    """The waiver for this cell, or ``None``. Single source: the registry."""
    return W.waiver_for(step_id, DIM)


def _is_na(step_id) -> bool:
    """NA precondition: the step declares no ``blocks_on`` KEY and no gate.

    There is no upstream set to be right or wrong about, and no gate that could
    read another step's artefact. Asserted live in the cell test, so adding
    either key to the step self-invalidates the NA.
    """
    return not F.declares_blocks_on(step_id) and not F.has_gate(step_id)


#: The steps recorded as NA when this module landed (v1.7.68). Pinned so the
#: classification is self-invalidating IN THE CELL, not only in the census: if
#: P0 ever gains a ``blocks_on`` key or a gate, ``step P0``'s own test goes red
#: and demands re-evaluation, and if any other step LOSES both it goes red too.
#: An NA that silently re-classifies itself is the "silent absence wearing a
#: hat" the campaign forbids.
_NA_BASELINE = frozenset({"P0"})


def _params():
    out = []
    for cell in C.cells_for(DIM):
        waiver = _waiver_for(cell.step_id)
        marks = (
            [pytest.mark.xfail(strict=True, reason=waiver.xfail_reason)]
            if waiver
            else []
        )
        out.append(pytest.param(cell, marks=marks))
    return out


# ══════════════════════════════════════════════════════════════════════
# The 63 cells
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cell", _params(), ids=lambda c: f"step{c.step_id}")
def test_d5_blocks_on_covers_the_real_dependency_graph(cell):
    """One cell of dimension 5, recomputed from the live tree.

    ENFORCED cells run the full predicate. WAIVED cells run the SAME predicate
    under ``xfail(strict=True)`` — nothing is skipped, so the day the gap closes
    the cell XPASSes and the suite goes red. The single NA cell asserts its NA
    precondition instead, so adding a ``blocks_on`` key or a gate to it fails
    this test rather than silently widening a hole.
    """
    sid = F.normalize_id(cell.step_id)

    if sid in _NA_BASELINE:
        # NA — asserted, not skipped. The classification itself is checked
        # first, so a step that stops qualifying reddens its own cell.
        assert _is_na(cell.step_id), (
            f"step {sid} was classified NA for dimension 5 because it declared "
            f"neither a blocks_on key nor a gate; it now declares "
            f"blocks_on_key={F.declares_blocks_on(cell.step_id)} "
            f"gate_clauses={len(F.gate_clauses(cell.step_id))}. The NA has "
            f"self-invalidated — dimension 5 must be enforced for it"
        )
        assert not F.declares_blocks_on(cell.step_id), (
            f"NA no longer holds: step {sid} now declares blocks_on="
            f"{list(F.blocks_on(cell.step_id))!r}; dimension 5 must be "
            f"re-evaluated for it"
        )
        assert not F.has_gate(cell.step_id), (
            f"NA no longer holds: step {sid} now declares a gate with "
            f"{len(F.gate_clauses(cell.step_id))} clause(s) naming programs "
            f"{list(F.gate_programs(cell.step_id))!r}, which can read other "
            f"steps' artefacts; dimension 5 must be re-evaluated for it"
        )
        assert not F.required_outputs(cell.step_id), (
            f"NA no longer holds: step {sid} now declares required_outputs="
            f"{list(F.required_outputs(cell.step_id))!r}"
        )
        return

    assert not _is_na(cell.step_id), (
        f"step {sid} is ENFORCED for dimension 5 but now declares neither a "
        f"blocks_on key nor a gate, i.e. it silently became NA; the "
        f"classification must be made explicitly, not by attrition"
    )
    problems = d5_problems(cell.step_id)
    assert not problems, (
        f"step {sid}: {len(problems)} dimension-5 defect(s)\n  - "
        + "\n  - ".join(problems)
    )


# ══════════════════════════════════════════════════════════════════════
# Anti-vacuity and anti-rot guards on the module itself
# ══════════════════════════════════════════════════════════════════════
def test_d5_covers_every_cell_exactly_once():
    """63 cells, each parametrized exactly once, in flow order."""
    ids = [F.normalize_id(p.values[0].step_id) for p in _params()]
    assert len(ids) == len(F.step_ids()) == 63, (
        f"parametrized {len(ids)} cells over {len(F.step_ids())} flow steps"
    )
    assert ids == [F.normalize_id(s) for s in F.step_ids()], (
        "cell order drifted from flow declaration order"
    )
    assert len(set(ids)) == len(ids), (
        f"duplicate cells: "
        f"{[k for k, v in Counter(ids).items() if v > 1]}"
    )


def test_d5_state_census_is_exhaustive():
    """Every cell is ENFORCED, WAIVED or NA — no fourth, silent state."""
    waived = {
        F.normalize_id(s)
        for s in F.step_ids()
        if _waiver_for(s) is not None
    }
    na = {
        F.normalize_id(s)
        for s in F.step_ids()
        if _is_na(s) and F.normalize_id(s) not in waived
    }
    assert na == set(_NA_BASELINE), (
        f"the live NA set is {sorted(na)} but the pinned baseline is "
        f"{sorted(_NA_BASELINE)}; a cell changed state without the "
        f"classification being updated"
    )
    enforced = {F.normalize_id(s) for s in F.step_ids()} - waived - na
    assert len(enforced) + len(waived) + len(na) == len(F.step_ids()), (
        f"census does not partition: enforced={len(enforced)} "
        f"waived={len(waived)} na={len(na)} steps={len(F.step_ids())}"
    )
    assert na == {"P0"}, (
        f"NA set is {sorted(na)}; only P0 lacks both a blocks_on key and a "
        f"gate on the current tree — a change here means dimension 5's NA "
        f"rationale must be re-derived"
    )
    assert not (waived & na), f"cell in two states at once: {sorted(waived & na)}"


def test_d5_derived_dependency_denominator_is_disclosed():
    """The data-dependency clause must not quietly become vacuous.

    This is the anti-starvation guard. The failure this campaign was convened
    over is a checker that reported a clean run because its input had been
    emptied; a dimension-5 module whose ``consumer`` relation silently resolved
    to zero pairs would pass all 63 cells and mean nothing. So the measured
    denominator is asserted to be non-trivial and is printed in the failure
    message when it moves.
    """
    with_deps = [
        F.normalize_id(s) for s in F.step_ids() if derived_dependencies(s)
    ]
    pairs = {
        (F.normalize_id(s), p)
        for s in F.step_ids()
        for p, _art, _ev in derived_dependencies(s)
    }
    assert len(with_deps) >= 10, (
        f"only {len(with_deps)} of {len(F.step_ids())} steps have any derived "
        f"cross-step data dependency ({with_deps}); the consumer relation has "
        f"collapsed and the D5-MISSING-EDGE clause is now vacuous for "
        f"{len(F.step_ids()) - len(with_deps)} cells"
    )
    assert len(pairs) >= 15, (
        f"only {len(pairs)} distinct (consumer, producer) pairs derived; the "
        f"v1.7.68 baseline is 19 over 14 steps and the floor is 15. "
        f"Pairs: {sorted(pairs)}"
    )


def test_d5_producer_map_is_live_and_non_empty():
    """The producer half of the relation is read from the yaml, not a snapshot."""
    prod = producers()
    assert len(prod) >= 150, (
        f"producer map has {len(prod)} artefacts; the yaml declares "
        f"{sum(len(F.required_outputs(s)) for s in F.step_ids())} "
        f"required_outputs entries over "
        f"{sum(1 for s in F.step_ids() if F.declares_required_outputs(s))} steps"
    )
    anchors = unique_basename_artefacts()
    assert 80 <= len(anchors) <= len(prod), (
        f"{len(anchors)} unique-basename anchors out of {len(prod)} artefacts — "
        f"outside the range that makes layer 2 meaningful"
    )
    # Every anchor must still map back to exactly one producing step set.
    for base, art in anchors.items():
        assert prod[art], f"anchor {base!r} -> {art!r} has no producer"


def test_d5_every_gate_program_is_parseable():
    """Layer 2 is blind for any gate program it cannot parse — fail loud."""
    blind = {}
    for sid in F.step_ids():
        for prog in F.gate_programs(sid):
            try:
                program_string_constants(prog)
            except ProgramUnparseable as exc:
                blind.setdefault(prog, []).append(
                    (F.normalize_id(sid), str(exc))
                )
    assert not blind, (
        f"{len(blind)} gate program(s) unparseable, so dimension 5's layer-2 "
        f"read detection is blind for their steps: {blind}"
    )


def test_d5_runtime_ordering_guard_loads_the_same_edges():
    """Whole-graph cross-check against the RUN-TIME ordering guard.

    Reported, not delegated to. The two sides disagree on NODE count by design
    (the runtime loader walks the whole document and admits the 8 stage grouping
    objects); they must agree on every EDGE, and no stage id may collide with a
    step id — a collision would silently overwrite that step's parents in the
    runtime graph.
    """
    rt_graph, provenance = runtime_graph()
    assert provenance == "LOADED", (
        f"flow_step_execution_coverage_check.load_blocks_on returned "
        f"{provenance!r} for {F.FLOW_YAML}; the run-time ordering invariant is "
        f"unenforceable from this yaml"
    )
    static = declared_graph()
    static_edges = sum(len(v) for v in static.values())
    rt_edges = sum(len(v or []) for v in rt_graph.values())
    assert rt_edges == static_edges, (
        f"run-time loader sees {rt_edges} blocks_on edges, static graph sees "
        f"{static_edges}"
    )
    for sid, parents in static.items():
        assert list(rt_graph.get(sid, [])) == list(parents), (
            f"step {sid}: static parents {list(parents)} vs run-time loader "
            f"{list(rt_graph.get(sid, []))}"
        )
    extra = sorted(set(rt_graph) - set(static))
    assert all(not (rt_graph.get(n) or []) for n in extra), (
        f"the run-time loader admits non-step node(s) carrying edges: "
        f"{ {n: rt_graph[n] for n in extra if rt_graph.get(n)} }"
    )


def test_d5_waivers_meet_the_registry_bar():
    """This dimension's waivers obey the shared validator.

    Reads the ONE registry. The module-local ``_LOCAL_WAIVERS`` mirror this
    used to validate was deleted: ``_waiver_for`` had preferred the central
    copy for some time, so validating the mirror graded a table nothing read.
    """
    assert dim_waivers(), f"dimension {DIM} declares no waiver at all"
    problems = {}
    for waiver in dim_waivers():
        found = W.validate(waiver)
        if found:
            problems[waiver.label] = found
    assert not problems, f"invalid dimension-{DIM} waiver(s): {problems}"
    assert all(w.dim == DIM for w in dim_waivers()), (
        f"waivers_for_dim({DIM}) returned a foreign dimension: "
        f"{[w.label for w in dim_waivers() if w.dim != DIM]}"
    )
    keys = [w.key for w in dim_waivers()]
    assert len(set(keys)) == len(keys), f"duplicate waiver keys: {keys}"


def test_d5_every_waiver_names_a_declared_step():
    """A waiver for a step that no longer exists is a rotted waiver."""
    unknown = [
        w.label
        for w in dim_waivers()
        if not F.has_step(w.step_id)
    ]
    assert not unknown, f"waiver(s) for steps absent from the flow: {unknown}"


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
    if not _is_na(step_id):
        return None
    return ("declares no `blocks_on` KEY and no gate, so there is no upstream "
            "set to be right or wrong about and no gate that could read "
            "another step's artefact")


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if _waiver_for(step_id) is not None:
        return "WAIVED"
    return "ENFORCED"
