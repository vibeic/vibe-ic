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

The value of a ``--json`` flag is excluded: across all 136 gate commands every
one of the distinct ``--json`` values is the checker's own report under
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
    value is a string) — ``analog_a5_layout_check``'s module docstring still
    names ``drc_clean.flag`` and ``lvs_match.flag`` several times, in the
    section EXPLAINING why it no longer reads them, and that prose must not be
    counted as a read;
  * the constant does not occur *only* as an operand of a comparison, or as an
    element of a container being compared against. ``spare_cell_preservation_
    check`` names ``post_cts.def`` and ``post_hold.def`` solely in an EXCLUSION
    list (``d.name not in (...)``), and ``flow_compliance_check`` name-tests
    ``coverage_actual.json`` against ``result.evidence`` — the declared outputs
    of the step it is CHECKING (``Path(artifact_rel).name != _COVERAGE_SELFSKIP_
    ARTIFACT``). Both classify a path the program already holds; neither opens
    anything;
  * the constant is not merely the BINDING SITE of a module-level
    ``NAME = "literal"`` alias. Naming a constant is not using it, and without
    resolving the alias the binding and every use are the same string in
    different positions, so none of them can be classified. The USES are
    counted, each in its own position.

Deliberately NOT excluded, and this was measured rather than assumed: the
literal argument of ``str.endswith`` / ``str.startswith``. A draft of this
narrowing excluded them on the reasoning that a suffix test classifies rather
than reads. It does not — ``stage_on_pass_review`` selects the file it is about
to open with ``next((project / r for r in intent_rel if
r.endswith("L5_ADI_SPEC.json")))`` and then calls ``.read_text()`` on it. The
draft silently dropped four genuine anchors, and NO pair-level measurement could
see it: all four artefacts are produced by ``D1``, which is in every step's
closure. ``test_d5_read_position_analysis_is_not_a_blanket`` is the control that
caught it, and it measures ANCHORS, not pairs, for exactly that reason.

**LAYER 2b — WHERE THE FLOW DECLARES WHAT THE INVOCATION READS.** A gate program
that is DISPATCHED has no single read set. ``stage_on_pass_review`` is one
program wired as a gate on six steps, each with a different ``--stage``, and
every one of its rules reads only the ``intent:`` / ``artefact:`` the flow
declares for the stage it was handed. The whole-program anchor cannot see that
and charges every step with the UNION over all seven stages. Measured on main at
v1.14.22 the union charged six steps (2, 7, 14, 15, 37, 39) with reading
``phase3/stage5_manufacturing/packaging_log.json`` — declared by exactly one
stage, ``stage5_manufacturing``, which no gate command in the flow selects and
whose rule is registered ``enabled=False`` for that reason. Step 42 produces it
and is the LAST step, so the edge each finding asked for was forward or
circular: a charge whose only possible repair is impossible is not a finding
about ``blocks_on``. So for a program in ``_FLOW_DECLARED_READ_PROGRAMS`` the
anchor is INTERSECTED with what the flow declares for THIS invocation. This
does not forgive; it substitutes a better source, the same move layer 3 makes
with ``required_inputs: [{from: X}]``.

Both layers then drop two classes of non-dependency:

  * ``P == C`` (a step reading what it produces), and
  * ``C`` is itself a declared producer of ``A`` (co-producers, e.g. steps 9 and
    14 both declare ``phase2/stage2/synth/netlist.v``; A9 and M3 both declare
    ``phase3/mixed_signal/cosim/mixed_signal_results.json``). A co-producer of X
    does not depend on the *other* producer of X.

Measured on the current tree: **23 of 63 steps have at least one derived
cross-step data dependency**, carrying 29 distinct (consumer, producer) pairs
backed by 70 evidence rows.
That is the honest denominator of the layer-1+2 half of this dimension, and it
is stated in :func:`test_d5_derived_dependency_denominator_is_disclosed` so it
can never quietly drift to zero and leave a suite of vacuous passes behind — the
exact shape of the failure this campaign was convened over (a runtime ordering
guard that saw 0 violations because it had been starved of its input).

WHY IT FELL FROM 37/92 TO 29/70 (v1.14.22 -> here), stated because a SHRINKING
denominator is the shape this guard exists to catch. The read-position rule and
layer 2b removed EIGHT pairs -- ``(2,4) (2,42) (7,42) (14,4) (14,42) (15,42)
(37,42) (39,42)`` -- and no others; those eight were the whole of this
dimension's ENFORCED-CONTRADICTED count. Fourteen more evidence rows went from
pairs that SURVIVED: ``(7,D1) 6->3``, ``(14,D1) 8->5``, ``(15,D1) 5->2``,
``(37,D1) 4->2``, ``(39,D1) 4->1``. Each is an L-doc a DIFFERENT stage's review
reads -- step 7 is ``stage1``, whose ``intent:`` is ``L9_INTEGRATION_SPEC.json``
alone, and it was being charged with reading L1, L5 and L8 because some other
stage's rule does. Exactly one PROGRAM-level anchor was lost,
``(flow_compliance_check, coverage_actual.json)``;
``(stage_on_pass_review, packaging_log.json)`` is still an anchor of the program
and is simply no longer attributed to steps whose stage does not declare it.

The three floors below were re-derived at the same time. They had said
``12 / 16 / 32`` while the live tree measured ``23 / 37 / 92``: the floors are
``>=`` guards, so eleven pairs and sixty rows of drift never reddened anything
and the anti-starvation bound had gone slack by a factor of nearly three. They
now sit on the live post-fix baseline.

WHY IT FELL FROM 14/19/35 (v1.7.68) TO 12/16/31, kept because it is the earlier
half of the same disclosure. The five dimension-5
waivers were closed by fixing the defects, and three of the removed pairs were
themselves the defects — a consumer reading an artefact it must not read:

  * A5 -> A6 (1 pair, 2 artefacts): ``analog_a5_layout_check`` no longer names
    ``drc_clean.flag`` / ``lvs_match.flag``. That read WAS the cycle; the PV
    verdict is A6's, over A6's own richer evidence.
  * 18 -> 21 and 18 -> 34 (2 pairs): ``spare_cell_preservation_check`` is no
    longer a step-18 gate program, so step 18 no longer reaches forward to
    ``routed.def`` / ``filled.def``. The gate still runs at step 34.

Steps 8 and DT2 kept their derived dependencies — they were closed by
DECLARING the edge, not by removing the read, so they still contribute. No
other pair moved: 14 - 2 = 12 steps and 19 - 3 = 16 pairs. Rows are 35 - 4
+ 1 = 32, not 31: the same change added
``phase1/generated_docs/L8_RTL_CONSTANTS.json`` to step D1's
``required_outputs`` (a dimension-7 closure), which turned step 2's
PRE-EXISTING read of that file into a countable evidence row, taking the
(2, D1) pair from 7 rows to 8. Corrected here after the floor was measured to
sit one row BELOW live — exactly the slack the comment on
``_DERIVED_DEP_ROWS_FLOOR`` claims to have eliminated, and enough to absorb
one silently deleted read. The removed rows are still exactly the four
artefacts named above.

====================================================================
WHY THAT DENOMINATOR IS NOT THE WHOLE TEST
====================================================================
For the other 49 steps the data-dependency clause is vacuously true, so each
cell additionally carries six structural predicates over the declared graph,
every one of them per-step falsifiable:

  D5-EDGE-UNRESOLVED   every ``blocks_on`` entry names a declared step, and does
                       so with the SAME RAW TYPE. ``flow_compliance_check``'s
                       cascade attribution keys ``parents_of`` on the raw id
                       (flow_compliance_check.py:6965-6973), so
                       ``blocks_on: ["9"]`` against ``id: 9`` resolves nowhere
                       and silently drops the edge, while
                       ``flow_step_execution_coverage_check.load_blocks_on``
                       stringifies and still sees it. Both consumers must agree.
  D5-SELF-EDGE         no step blocks on itself.
  D5-DUP-EDGE          no ``blocks_on`` list repeats a parent.
  D5-FORWARD-EDGE      every parent is DECLARED EARLIER in the yaml. The flow is
                       consumed in canonical declaration order
                       (flow_compliance_check.py:7444-7453) and #503 cascade
                       attribution takes the first FAIL per track walking that
                       same order (flow_compliance_check.py:7070-7088), so a
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
per-step graphs are identical (93 edges both sides). If a stage object ever took
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
   hazard is identical either way. ``sdc_exception_correlation_check`` was the
   worked example: its swallowed ``except (OSError, ValueError): pass`` turned a
   missing upstream into a silently wrong advisory instead of a loud failure.
   Its step-8 cell has since been closed — the edge is declared and the program
   reports the per-source read STATUS — but the GAP is unchanged: a best-effort
   read is still indistinguishable from a mandatory one here, so this dimension
   goes on treating both as dependencies.
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

#: The cells this dimension waives, PINNED as an exact set. Was EMPTY from
#: 2026-07-28 (all five original dimension-5 waivers were closed by declaring
#: the missing edge, removing a read that was itself the defect, or
#: reordering a declaration) until 2026-08-08, when step 12 gained
#: ``12/d5``: a new content clause (dft_post_optimization_scan_survival_check,
#: closing a dimension-2 gap) reads an artefact TWO steps declare as their own
#: required_output (9, the true producer, already in step 12's closure; 14, a
#: pre-existing duplicate declaration that would be a circular edge) — see the
#: waiver's own reason/evidence in ``matrix_63x8/waivers.py`` for why the
#: duplicate was not simply deleted. Pinned rather than floored so a waiver
#: set is a recorded fact instead of an empty loop reporting green — see
#: ``test_d5_waivers_meet_the_registry_bar``.
WAIVED_CELLS_PINNED: frozenset = frozenset({"12/d5"})

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

    Thin wrapper over :func:`read_position_constants`, which is the analysis and
    which the tests drive directly from source text so every exclusion is proven
    by a case written to exercise it.
    """
    path = F.program_path(basename)
    if path is None:  # pragma: no cover - unresolved gate programs are dim 1
        raise ProgramUnparseable(f"programs/{basename}.py does not exist")
    return read_position_constants(
        path.read_text(encoding="utf-8", errors="replace"), origin=str(path)
    )


def _module_string_aliases(tree: ast.Module) -> Dict[str, str]:
    """``{NAME: literal}`` for MODULE-LEVEL ``NAME = "literal"`` bindings.

    A gate program that names an artefact usually names it ONCE, at module
    level, and then refers to the NAME. Without resolving that, the binding site
    and every use are the same string in different syntactic positions, and the
    position analysis below can classify none of them.

    Only single-target, module-level, plain-string bindings are resolved, and a
    name bound twice or bound to anything else is dropped entirely: an alias
    this cannot prove is an alias must keep counting as a read.
    """
    aliases: Dict[str, str] = {}
    rebound: Set[str] = set()
    for node in tree.body:
        target = value = None
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target is None:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            rebound.add(target)
        elif target in aliases and aliases[target] != value.value:
            rebound.add(target)
        else:
            aliases[target] = value.value
    for name in rebound:
        aliases.pop(name, None)
    return aliases


def read_position_constants(source: str, origin: str = "<source>") -> frozenset:
    """String constants of one gate program that occur in READ position.

    AST, not text: comments never enter, so the "``# e.g. \"foo_check\"`` counted
    as a call site" failure cannot recur. Three classes are removed because each
    is provably not path construction:

      * bare-expression strings (module / function / class docstrings, and the
        free-standing comment-strings this codebase uses between defs);
      * the BINDING SITE of a module-level ``NAME = "literal"`` alias. Naming a
        constant is not using it; the USES of the name are counted, each in its
        own position. Without this, a program that names an artefact once at
        module level and then only COMPARES against the name is indistinguishable
        from one that opens it;
      * constants that appear ONLY as an operand of an ``ast.Compare`` — either
        directly, or as an element of a container being compared against. This
        SUPERSEDES the earlier ``not in``-container rule, which was this same
        idea drawn one operator wide. ``x not in (a, b)`` and
        ``Path(p).name != a`` are both the program CLASSIFYING a path it already
        holds; neither opens anything.

    A constant that occurs even ONCE outside those positions still counts. That
    is the point, and it is what keeps this from becoming an amnesty: a program
    that name-tests a literal AND builds a path from it is a reader and stays
    charged (``test_d5_compare_position_does_not_forgive_a_real_read``).

    NOT EXCLUDED, and this was measured rather than assumed: the literal argument
    of ``str.endswith`` / ``str.startswith``. ``stage_on_pass_review`` selects the
    file it is about to open with
    ``next((project / r for r in intent_rel if r.endswith("L5_ADI_SPEC.json")))``
    and then calls ``.read_text()`` on it — a suffix test there IS the read. An
    earlier draft of this function excluded those arguments and silently dropped
    four genuine anchors; ``test_d5_read_position_analysis_is_not_a_blanket`` is
    what caught it and is what keeps it caught.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ProgramUnparseable(f"{origin}: {exc}") from exc

    docstring_nodes = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    aliases = _module_string_aliases(tree)
    binding_nodes: Set[int] = set()
    for node in tree.body:
        value = None
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in aliases):
            value = node.value
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id in aliases):
            value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            binding_nodes.add(id(value))

    def one_literal(node) -> Tuple[str, int]:
        """``(text, node id)`` when ``node`` IS one string literal, else ``("", 0)``."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value, id(node)
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id in aliases):
            return aliases[node.id], id(node)
        return "", 0

    def countable(node) -> Tuple[str, int]:
        text, nid = one_literal(node)
        if not text or nid in docstring_nodes or nid in binding_nodes:
            return "", 0
        return text, nid

    total: Counter = Counter()
    for node in ast.walk(tree):
        text, _nid = countable(node)
        if text:
            total[text] += 1
        elif isinstance(node, ast.JoinedStr):
            # f-strings: only the LITERAL segments are usable evidence; a
            # `{var}` hole is explicitly not resolved here (see known gap 1).
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    total[part.value] += 1

    excluded: Counter = Counter()

    def count_compare_operand(node) -> None:
        text, _nid = countable(node)
        if text:
            excluded[text] += 1
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for element in node.elts:
                count_compare_operand(element)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left] + list(node.comparators):
                count_compare_operand(operand)

    return frozenset(
        text for text, count in total.items() if excluded[text] < count
    )


# ══════════════════════════════════════════════════════════════════════
# LAYER 2b — WHERE THE FLOW DECLARES WHAT THE INVOCATION READS
# ══════════════════════════════════════════════════════════════════════
#: Gate programs that are DISPATCHED, and whose reads the flow therefore
#: declares per invocation instead of leaving to be reconstructed from the
#: program's AST. ``{program: (selector flag, yaml key of the declaration)}``.
#:
#: WHY THIS EXISTS. ``stage_on_pass_review`` is ONE program wired as a gate on
#: SIX steps, each with a different ``--stage``. Its rules are registered per
#: stage and every one of them reads only ``decl["intent"]`` / ``decl["artefact"]``
#: — the block the flow declares for the stage it was given. The basename anchor
#: cannot see that: it takes the constants of the WHOLE program and charges
#: every step that runs it, i.e. the UNION over all seven stages. Measured on
#: main at v1.14.22 that union charged six steps (2, 7, 14, 15, 37, 39) with
#: reading ``phase3/stage5_manufacturing/packaging_log.json``, which is declared
#: by exactly one stage — ``stage5_manufacturing``, which NO gate command in the
#: flow selects, and whose rule is registered ``enabled=False`` for that reason.
#: Step 42 produces that artefact and is the LAST step in the flow, so the edge
#: the finding asked for was a forward or circular one in every case: a charge
#: whose only possible repair is impossible is not a finding about ``blocks_on``.
#:
#: WHAT IT DOES NOT DO. It does not forgive; it SUBSTITUTES a better source. For
#: a program listed here the anchor is intersected with what the flow declares
#: for THIS invocation — so a read the flow declares is still charged, and a
#: read of an artefact the flow does NOT declare is charged as a dimension-7
#: question against the declaration rather than silently believed. The same move
#: layer 3 makes with ``required_inputs: [{from: X}]``: where the flow writes the
#: answer down, read it instead of reconstructing it.
_FLOW_DECLARED_READ_PROGRAMS: Dict[str, Tuple[str, str]] = {
    "stage_on_pass_review": ("--stage", "on_pass_review"),
}

#: Keys inside that block naming paths the invocation READS. ``intent`` is what
#: the review is checked against and ``artefact`` is what it reviews; both are
#: opened. ``intent_deny`` is a word list, not a path list, and is not here.
_FLOW_DECLARED_READ_KEYS: Tuple[str, ...] = ("intent", "artefact")


@functools.lru_cache(maxsize=None)
def flow_declaration_blocks(key: str) -> Dict[str, Dict]:
    """``{node id: node[key]}`` for every node in the flow that carries ``key``.

    Walks the whole document rather than ``steps()``: the ``on_pass_review``
    blocks hang off the STAGE objects, which are not steps.
    """
    found: Dict[str, Dict] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            block = node.get(key)
            if isinstance(block, dict) and node.get("id") is not None:
                found[str(node["id"])] = block
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(F.load_flow())
    return found


@functools.lru_cache(maxsize=None)
def flow_declared_program_reads(step_id) -> Dict[str, Tuple[str, ...]]:
    """``{program: paths the flow declares THIS step's invocation of it reads}``.

    Only programs in `_FLOW_DECLARED_READ_PROGRAMS` appear. A program that is
    listed but whose selector or declaration cannot be resolved is OMITTED, not
    given an empty list: an unresolvable declaration must fall back to the
    whole-program anchor rather than silently forgiving every artefact.
    """
    out: Dict[str, Set[str]] = {}
    for command in F.gate_commands(step_id):
        try:
            tokens = shlex.split(command)
        except ValueError:  # pragma: no cover - defensive: unbalanced quotes
            tokens = command.split()
        if not tokens:
            continue
        program = tokens[0].rsplit("/", 1)[-1]
        if program.endswith(".py"):
            program = program[:-3]
        spec = _FLOW_DECLARED_READ_PROGRAMS.get(program)
        if spec is None:
            continue
        flag, key = spec
        selected = None
        for index, token in enumerate(tokens):
            if token == flag and index + 1 < len(tokens):
                selected = tokens[index + 1]
            elif token.startswith(flag + "="):
                selected = token.split("=", 1)[1]
        if selected is None:
            continue
        block = flow_declaration_blocks(key).get(selected)
        if block is None:
            continue
        paths: Set[str] = set()
        for field in _FLOW_DECLARED_READ_KEYS:
            for entry in (block.get(field) or []):
                normalised = _norm_path(entry)
                if normalised:
                    paths.add(normalised)
        out.setdefault(program, set()).update(paths)
    return {program: tuple(sorted(paths)) for program, paths in out.items()}


def _declared_by_flow(artefact: str, declared: Tuple[str, ...]) -> bool:
    """Is ``artefact`` one of ``declared``, or inside a directory it names?

    Containment is used HERE and refused in layer 1, and the two are different
    questions. Layer 1's rejected case was "step 21 scans a directory step 34
    later writes into", i.e. an ADJACENCY inferred from two unrelated
    declarations. Here the flow has declared, in one block, that this invocation
    reads this directory — ``artefact: [phase1/generated_docs/]`` is how the
    stage-1 review says it reads the L-docs, and there is no other way for it to
    say so.
    """
    return any(artefact == entry or artefact.startswith(entry + "/")
               for entry in declared)


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
    by_flow = flow_declared_program_reads(step_id)
    for prog in F.gate_programs(step_id):
        constants = program_string_constants(prog)
        declared = by_flow.get(prog)
        for base, art in anchors.items():
            if base not in constants:
                continue
            if declared is not None and not _declared_by_flow(art, declared):
                # The flow declares what THIS invocation reads and this is not
                # in it; the whole-program anchor is the union over every other
                # invocation of the same program. See `_FLOW_DECLARED_READ_PROGRAMS`.
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
# LAYER 3 — WHAT THE FLOW ITSELF SAYS, which layers 1 and 2 never asked
# ══════════════════════════════════════════════════════════════════════
#: Layers 1 and 2 RECONSTRUCT the consumer relation from evidence: paths the
#: gate names, string constants the gate program holds. That reconstruction is
#: careful and it is live, and it finds 16 pairs over 12 steps.
#:
#: The flow WRITES THE ANSWER DOWN. `required_inputs: [{from: X, path: …}]` is
#: the flow stating, in its own grammar, which step this one reads from — 75
#: intra-flow pairs over 54 of the 63 steps. This dimension asks "is blocks_on
#: the true upstream set" and, until this layer, checked it against a 16-pair
#: reconstruction while a 69-pair declaration sat unread in the same file.
#:
#: This is not a hypothesis about the field's meaning. `flow_dependency_graph_
#: check`'s own docstring states it: P0 "gained the ordering edge its own
#: `required_inputs: [{from: 1}]` had always implied". And the flow says it at
#: step 1, at the point of the repair: "The dependency was always REAL and
#: never DECLARED … Declaring the edge arms the guard that already exists."
#:
#: THE FAIL-SAFE CLASS, BY STRUCTURE: a `from` value naming no step this flow
#: declares is an input from OUTSIDE the flow — the user's documents, the PDK,
#: a board. No `blocks_on` edge to a step that does not exist is possible, so
#: demanding one would accuse every genuine entry point. Decided with the same
#: test `flow_dependency_graph_check` uses for a dangling reference, never by
#: matching the word `external`: a word list with one word in it is still a
#: word list.
@functools.lru_cache(maxsize=None)
def declared_input_dependencies(step_id) -> Tuple[Tuple[str, str], ...]:
    """``((producer_step, evidence), ...)`` from this step's `required_inputs`.

    Only entries whose ``from`` names a step THIS FLOW DECLARES. Deduped and
    sorted; ``producer == consumer`` dropped (a step declaring it reads its own
    output is not an ordering dependency).
    """
    consumer = F.normalize_id(step_id)
    out: Set[Tuple[str, str]] = set()
    for entry in (F.step_by_id(step_id).get("required_inputs") or []):
        if not isinstance(entry, dict) or entry.get("from") is None:
            continue
        raw = entry["from"]
        producer = F.normalize_id(raw)
        if not F.has_step(producer) or producer == consumer:
            continue
        what = entry.get("path") or entry.get("outputs") or "outputs"
        out.add((producer,
                 f"required_inputs declares `from: {raw}` for {what!r}"))
    return tuple(sorted(out))


@functools.lru_cache(maxsize=None)
def external_input_declarations(step_id) -> Tuple[str, ...]:
    """``from`` values that name no declared step — inputs from outside."""
    out: Set[str] = set()
    for entry in (F.step_by_id(step_id).get("required_inputs") or []):
        if isinstance(entry, dict) and entry.get("from") is not None:
            if not F.has_step(F.normalize_id(entry["from"])):
                out.add(str(entry["from"]))
    return tuple(sorted(out))


#: SHRINK-ONLY. The steps whose layer-3 edge is a KNOWN, FILED, DEFERRED
#: defect: vibe-ic#1070. Every one of them is a real unguarded dependency and
#: the repair is one yaml list each; the owner deferred it on SEQUENCING —
#: declaring these edges is transitive and would newly put the producer into
#: the ancestry of 44 / 14 / 4 of the 63 steps, which on an already-red main
#: destroys the only delta the repair agents have to read.
#:
#: This register may only SHRINK. A NEW step in this state fails immediately;
#: these three are named, evidenced and pointed at the issue rather than
#: silently forgiven. When #1070 lands, this set empties and
#: `test_d5_the_deferred_register_only_shrinks` reddens if it does not.
# 2026-08-14: EMPTIED. vibe-ic#1070 landed for all three edges, so the debt
# this register recorded no longer exists and the shrink-only doctrine above
# says the entry goes. Measured live on `ab5a23a28` — each edge is both still
# READ and now ORDERED, which is exactly the condition
# `test_d5_the_deferred_register_only_shrinks` was written to detect:
#
#     A1 -> D1 : reads_it=True  ORDERED=True    (A1 gained `blocks_on: [D1]`)
#     25 -> 24 : reads_it=True  ORDERED=True
#     M1 -> 37 : reads_it=True  ORDERED=True
#
# Emptied rather than deleted outright: a NEW step entering this state must
# still land here and be named, evidenced and pointed at an issue rather than
# silently forgiven.
_DEFERRED_LAYER3_EDGES: Dict[str, Tuple[str, ...]] = {}

#: The edges the register carried until #1070 paid the debt.
#:
#: This exists for ONE reason: with the register empty, the paired control
#: below compares an empty measured set against an empty registered set and
#: passes while asserting NOTHING. A control that forgives nothing and checks
#: nothing is worse than no control, because the file still reads as though it
#: were policing three defects. So the control now also asserts the debt STAYED
#: paid, which is a live guard rather than a vacuous one: drop any of these
#: three `blocks_on` declarations again and it reddens.
_FORMERLY_DEFERRED_LAYER3_EDGES: Tuple[Tuple[str, str], ...] = (
    ("A1", "D1"),
    ("25", "24"),
    ("M1", "37"),
)



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
                f"{type(raw).__name__}; flow_compliance_check.py:6965-6973 keys "
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
                f"declaration order (flow_compliance_check.py:7444-7453) and "
                f"#503 cascade attribution takes the first FAIL per track in "
                f"that same order (flow_compliance_check.py:7070-7088), so "
                f"{parent!r} can never cut {sid}'s cascade"
            )

    # ── CL-* — the closed_loop FALLBACK edge, dimension 5's other edge set
    # A `closed_loop.fallback_to` IS a dependency edge, and until 2026-08-20
    # nothing in this repository read one. MEASURED at 46db018669: 19
    # `closed_loop:` declarations in the flow, ZERO consumers anywhere in the
    # plugin — and this module's own substrate shipped the accessor
    # (`flowref.closed_loop`, exported in `__all__`) with no caller. A
    # `fallback_to` naming a step that does not exist would have passed every
    # gate here, so the convergence edges the flow's close-loop story rests on
    # were, as a class, unfalsifiable.
    #
    # Dimension 5 owns "is the declared edge set the true one", so it owns this
    # edge set too. The predicate is NOT restated here: `closed_loop_edge_check`
    # is the ONE implementation and this module calls it, so the program a
    # reviewer runs by hand and the cell the matrix reddens cannot drift apart —
    # the failure mode `_ORFS_PNR_KNOB_PARAMS` names in its own header ("a second
    # list of names that would drift away from it").
    #
    # Steps with no `closed_loop` get an empty list, so this adds no cell and
    # moves no existing verdict: measured over the shipped flow, `d5_problems`
    # is unchanged for every step and the 19 declaring steps stay green.
    import closed_loop_edge_check as _cl

    _cl_raw_ids, _cl_by = _cl.build_index(list(F.steps()))
    problems.extend(
        _cl.problems_for_step(F.step_by_id(step_id), _cl_raw_ids, _cl_by))

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

    # ── D5-DECLARED-INPUT-UNORDERED (layer 3) ────────────────────────
    # The half of "is blocks_on the true upstream set" that reads the flow's
    # own answer instead of reconstructing one. Deliberately SEPARATE from
    # D5-MISSING-EDGE: that clause's evidence is an artefact read, this one's
    # is a DECLARATION, and collapsing them would lose which of the two found
    # the defect — the distinction that decides whether the repair is an edge
    # or a corrected `required_inputs` entry.
    for producer, evidence in declared_input_dependencies(step_id):
        if producer in closure:
            continue
        if producer in _DEFERRED_LAYER3_EDGES.get(sid, ()):
            continue                      # named in the shrink-only register
        problems.append(
            f"D5-DECLARED-INPUT-UNORDERED: step {sid} declares it reads step "
            f"{producer}'s output, but {producer} is not in {sid}'s blocks_on "
            f"closure (blocks_on={list(parents)}, closure={sorted(closure)}), "
            f"so flow_step_execution_coverage_check's ordering guard cannot "
            f"red {sid} when {producer} FAILs. Evidence: {evidence}"
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
# THE REGISTRY NOW HOLDS NO DIMENSION-5 ENTRY AT ALL. All five were labelled
# "LIVE DEFECT, reproduced" and all five have been CLOSED by fixing the defect,
# not by relaxing anything here — the predicate above is byte-for-byte the one
# that failed them:
#
#   step 8  — `sdc_exception_correlation_check` reads step 3's
#             `reports/phase2/cdc/crossing.json`; step 8 now declares
#             `blocks_on: [7, 3]`, and the program reports the per-source read
#             STATUS so an unread file can no longer masquerade as "no async
#             pair found". Each finding cites only the sources actually read
#             and names the unread ones, so the PARTIAL case (L8 present,
#             crossing.json absent) can no longer assert "no matching CDC
#             crossing" about a file that was never opened.
#   DT2     — its condition names step 22's SPEF while it was declared at yaml
#             index 14 (step 22 at 34), so the edge would have been FORWARD.
#             DT2 and DT3 are now declared after step 22 and DT2 declares
#             `blocks_on: [DT1, 22]`.
#   A5      — CIRCULAR: A5's gate required A6's `drc_clean.flag` /
#             `lvs_match.flag` while A6 declares `blocks_on: [A5]`. Broken on
#             the A5 side (A6 consumes A5's layout, and the A6 STEP is what
#             writes those flags), with A6's block-list roots fixed first so
#             nothing went unmeasured. A5 had no waiver path, so A6 — now the
#             only per-block PV gate — refuses to let a step waiver cover an
#             ABSENT measurement (`_NON_WAIVABLE_RULES`); a measured DRC/LVS
#             defect stays waivable, which is the flow-wide mechanism.
#   18      — UNSATISFIABLE BY EDGE: `spare_cell_preservation_check` at the
#             spare-INSERTION step resolved forward to steps 21/34's DEFs. The
#             gate now runs only at step 34, whose closure contains them, and
#             the program FAILs (RECORD_ARTEFACT_MISMATCH) when the
#             name-bearing final artefacts disagree about which recorded
#             spares they contain — a CONTENT test, so a leftover DEF can no
#             longer vouch for a spare the shipped netlist lost. Not an mtime
#             test: the runner writes the OpenROAD artefacts BEFORE it
#             serialises `spare_cells.json`, so "older than the record" is the
#             shape of every correct run.
#   A7      — the flow's only FORWARD edge: A6 was declared at index 52 and A7
#             at 23. A6's block was MOVED between A5 and A7; nothing about A6
#             itself changed.


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


#: The steps recorded as NA for this dimension. Pinned so the classification is
#: self-invalidating IN THE CELL, not only in the census: a step that gains a
#: ``blocks_on`` key or a gate reddens its own test and demands re-evaluation,
#: and a step that LOSES both goes red too. An NA that silently re-classifies
#: itself is the "silent absence wearing a hat" the campaign forbids.
#:
#: EMPTY as re-measured here, and the emptiness is the pin FIRING, not the pin
#: being removed. It held ``{"P0"}`` from v1.7.68. ``332b9985`` ("flow: stage
#: membership was declared twice and the copies disagreed") gave P0
#: ``blocks_on: [1]``, so ``_is_na("P0")`` became False and step P0's own cell
#: went red with the sentence this comment promised it would print — "the NA has
#: self-invalidated — dimension 5 must be enforced for it". The demanded
#: re-evaluation was then DONE rather than waived: ``d5_problems("P0")`` is ``[]``
#: on the live tree, so P0 now runs the full dimension-5 predicate as an ENFORCED
#: cell like the other 62, and ``D5-PHANTOM-EDGE`` was replayed against it to
#: prove the cell can still be reddened.
#:
#: An empty set here does NOT disarm the guard. The ENFORCED branch asserts
#: ``not _is_na(...)`` for every cell, so the day any step drops both its
#: ``blocks_on`` key and its gate it reddens rather than drifting into a silent
#: NA — which is the direction this pin was always the weaker half of.
_NA_BASELINE: frozenset = frozenset()


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
    # 69 -> 68: step `37.5self` (General Precheck) is RETIRED, and the census
    # goes back DOWN. The owner's 2026-08-20 decision: the general precheck was
    # never a third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    # every design that reaches that step, and the operator's container runs IN
    # ADDITION wherever the PDK ships a precheck and its template was fetched.
    # A PDK with no shuttle precheck is the same step with one fewer arm, not a
    # different route. Re-stated by hand, as the census comments here require:
    # a step LEAVING must force a human to say the number just as loudly as one
    # arriving. RE-DERIVED from the live yaml, never decremented by hand.
    # RE-DERIVED 2026-08-21, 68 -> 69. NOT decremented or incremented by
    # hand: measured with `len(F.step_ids())` on the live yaml. The
    # population moved +'0.5ic', +'1.6x' (v1.11.15), -'37.5self'
    # (v1.11.18) and this pin was moved for none of them, which is why it
    # was already red on main before the ninth dimension landed.
    assert len(ids) == len(F.step_ids()) == 68, (
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
    # The NA rationale, RE-DERIVED over the whole population rather than
    # restated as a second literal. The line here used to be
    # `assert na == {"P0"}` — a hardcoded copy of the pin asserted four lines
    # above, so the two had to be edited together and neither checked the
    # thing they were both about: that "NA" means, for every step, exactly
    # "declares no blocks_on key and no gate". That is now measured on all 63.
    misfiled = sorted(
        F.normalize_id(s) for s in F.step_ids()
        if (F.normalize_id(s) in na) != _is_na(s)
        and F.normalize_id(s) not in waived
    )
    assert not misfiled, (
        f"dimension 5's NA rationale does not hold for {misfiled}: a cell is "
        f"NA if and only if it declares neither a blocks_on key nor a gate, "
        f"and these disagree with that derivation"
    )
    # 69 -> 68: step `37.5self` (General Precheck) is RETIRED, and the census
    # goes back DOWN. The owner's 2026-08-20 decision: the general precheck was
    # never a third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    # every design that reaches that step, and the operator's container runs IN
    # ADDITION wherever the PDK ships a precheck and its template was fetched.
    # A PDK with no shuttle precheck is the same step with one fewer arm, not a
    # different route. Re-stated by hand, as the census comments here require:
    # a step LEAVING must force a human to say the number just as loudly as one
    # arriving. RE-DERIVED from the live yaml, never decremented by hand.
    # RE-DERIVED 2026-08-21, 68 -> 69. NOT decremented or incremented by
    # hand: measured with `len(F.step_ids())` on the live yaml. The
    # population moved +'0.5ic', +'1.6x' (v1.11.15), -'37.5self'
    # (v1.11.18) and this pin was moved for none of them, which is why it
    # was already red on main before the ninth dimension landed.
    assert len(F.step_ids()) == 68, (
        f"the NA rationale was re-derived over {len(F.step_ids())} steps, not "
        f"63; the population moved and this census states a figure for a grid "
        f"it no longer describes"
    )
    assert enforced, (
        f"dimension 5 enforces ZERO of its {len(F.step_ids())} cells "
        f"(waived={len(waived)} na={len(na)}); a census over an empty enforced "
        f"set proves nothing and must refuse rather than pass"
    )
    assert not (waived & na), f"cell in two states at once: {sorted(waived & na)}"


# ── the anti-starvation floor, RE-DERIVED after the d5 closures ────────────
# The closures shrank the denominator (v1.7.68: 14 steps / 19 pairs / 35 rows
# -> 12 / 16 / 31, itemised in the module docstring), and the floor was left
# at the pre-closure slack of 10/15. That is the guard's own failure mode: a
# floor with slack lets the NEXT pair-removing change land inside tolerance,
# which is precisely the silent shrink it exists to catch.
#
# The floor is therefore pinned to the LIVE measurement, not below it. Any
# downward move — one pair, one row — fails and has to be re-derived
# deliberately, with the reason written into the docstring the way the last
# three removals were. Upward moves (a new declared read, a new step) are
# free: this is a floor, not an equality pin.
_DERIVED_DEP_STEPS_FLOOR = 23
_DERIVED_DEP_PAIRS_FLOOR = 29
_DERIVED_DEP_ROWS_FLOOR = 70

# Cells whose layer-1+2 data-dependency clause is EMPTY BY CONSTRUCTION, and
# why. Both were closed by DELETING a cross-step read, so for exactly these
# two the D5-MISSING-EDGE clause measures zero pairs — an honest zero, but one
# that must be stated rather than left to be discovered. Their cells are
# carried by the six structural predicates (D5-EDGE-UNRESOLVED / D5-SELF-EDGE
# / D5-DUP-EDGE / D5-FORWARD-EDGE / D5-CYCLE / D5-ORPHAN / D5-GRAPH-DISAGREE),
# each of which is per-step falsifiable and each of which goes red under
# reintroduction.
_VACUOUS_BY_CLOSURE = {
    "A5": ("analog_a5_layout_check no longer names drc_clean.flag / "
           "lvs_match.flag — that read was the A5<->A6 cycle"),
    "18": ("spare_cell_preservation_check is no longer a step-18 gate "
           "program, so step 18 no longer reaches forward to routed.def / "
           "filled.def"),
}


def test_d5_derived_dependency_denominator_is_disclosed():
    """The data-dependency clause must not quietly become vacuous.

    This is the anti-starvation guard. The failure this campaign was convened
    over is a checker that reported a clean run because its input had been
    emptied; a dimension-5 module whose ``consumer`` relation silently resolved
    to zero pairs would pass all 63 cells and mean nothing. So the measured
    denominator is asserted against the live floor and is printed in the
    failure message when it moves.
    """
    with_deps = [
        F.normalize_id(s) for s in F.step_ids() if derived_dependencies(s)
    ]
    pairs = {
        (F.normalize_id(s), p)
        for s in F.step_ids()
        for p, _art, _ev in derived_dependencies(s)
    }
    rows = sum(len(derived_dependencies(s)) for s in F.step_ids())
    assert len(with_deps) >= _DERIVED_DEP_STEPS_FLOOR, (
        f"only {len(with_deps)} of {len(F.step_ids())} steps have any derived "
        f"cross-step data dependency ({sorted(with_deps)}); the floor is the "
        f"live baseline {_DERIVED_DEP_STEPS_FLOOR}. The consumer relation "
        f"shrank: name the removed read and why it is not a dependency, in "
        f"the module docstring, then re-derive this floor."
    )
    assert len(pairs) >= _DERIVED_DEP_PAIRS_FLOOR, (
        f"only {len(pairs)} distinct (consumer, producer) pairs derived; the "
        f"floor is the live baseline {_DERIVED_DEP_PAIRS_FLOOR} over "
        f"{_DERIVED_DEP_STEPS_FLOOR} steps (v1.7.68 was 19 over 14, shrunk by "
        f"the d5 closures — see the module docstring). "
        f"Pairs: {sorted(pairs)}"
    )
    assert rows >= _DERIVED_DEP_ROWS_FLOOR, (
        f"only {rows} evidence rows back those {len(pairs)} pairs; the floor "
        f"is the live baseline {_DERIVED_DEP_ROWS_FLOOR}. A pair kept alive "
        f"by fewer artefacts than before is a shrink the pair count alone "
        f"cannot see."
    )


def test_d5_cells_with_no_derived_dependency_are_named_not_silent():
    """The two cells closed by DELETING a read measure ZERO pairs.

    That is an honest zero — neither step reads another step's artefact any
    more — but an unstated one would let "this clause found nothing" pass for
    "this clause found nothing wrong". It is asserted here so the vacuity is
    a documented property with a reason attached, and so that a future change
    which re-introduces a cross-step read into either gate has to update this
    table rather than quietly re-populate the denominator.
    """
    for sid, why in _VACUOUS_BY_CLOSURE.items():
        assert derived_dependencies(sid) == (), (
            f"step {sid} now derives {derived_dependencies(sid)}; the d5 "
            f"closure removed its only cross-step read ({why}). If the read "
            f"is back on purpose, update _VACUOUS_BY_CLOSURE and the "
            f"denominator floors."
        )
    # ... and the vacuity is BOUNDED: it is these two and no others beyond the
    # steps that never had a derived read at all.
    empty = {F.normalize_id(s) for s in F.step_ids()
             if not derived_dependencies(s)}
    assert set(_VACUOUS_BY_CLOSURE) <= empty
    assert len(F.step_ids()) - len(empty) >= _DERIVED_DEP_STEPS_FLOOR


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


# ══════════════════════════════════════════════════════════════════════
# THE READ-POSITION ANALYSIS, AND THE CONTROLS THAT KEEP IT HONEST
# ══════════════════════════════════════════════════════════════════════
#: SHRINK-ONLY. What layer 2 stopped charging when the read-position analysis
#: and layer 2b landed, and the site that earns each one. Every entry is an
#: ADMISSION: `test_d5_the_narrowing_register_names_live_subjects` requires each
#: to still describe a LIVE suppression of a charge this dimension would
#: otherwise make. When the site changes, the entry stops describing anything
#: and that test reddens until it is deleted or the narrowing is re-argued.
#: A register that outlives its subject is an amnesty.
#:
#: ``(program, basename, consumers it charged, why it is not a read)``
_NARROWED_LIVE_SUBJECTS: Tuple[Tuple[str, str, Tuple[str, ...], str], ...] = (
    (
        "stage_on_pass_review",
        "packaging_log.json",
        ("2", "7", "14", "15", "37", "39"),
        "named only by R5_PACKAGE_CANNOT_BOND_DESIGN, which the flow declares "
        "under stage5_manufacturing's `on_pass_review.artefact`. No gate "
        "command passes `--stage stage5_manufacturing`, and the rule is "
        "registered `enabled=False` into `_DECLARED_NOT_ENABLED` for exactly "
        "that reason. Suppressed by layer 2b.",
    ),
    (
        "flow_compliance_check",
        "coverage_actual.json",
        ("2", "14"),
        "flow_compliance_check.py `Path(artifact_rel).name != "
        "_COVERAGE_SELFSKIP_ARTIFACT`, over `result.evidence` — the declared "
        "outputs of the step BEING CHECKED. The constant classifies a path the "
        "scan already holds. Suppressed by the compare-position rule.",
    ),
)


def test_d5_read_position_analysis_excludes_only_what_it_claims():
    """Each exclusion fires, and each retention survives — driven from source.

    Written against source text rather than a real gate program so every branch
    is exercised by a case authored to exercise it, and so a future edit to a
    real program cannot quietly become this test's only subject.
    """
    source = '''
"""module docstring naming docstring_only.json"""
from pathlib import Path

ALIAS_COMPARED = "alias_compared.json"
ALIAS_OPENED = "alias_opened.json"
REBOUND = "rebound_one.json"
REBOUND = "rebound_two.json"

def f(root, given):
    if Path(given).name != ALIAS_COMPARED:
        pass
    if Path(given).name == "eq_only.json":
        pass
    if given not in ("not_in_only.json",):
        pass
    if given in ["in_only.json"]:
        pass
    if given.endswith("suffix_selected.json"):
        return (root / given).read_text()
    open(root / ALIAS_OPENED)
    return (root / "built_only.json").read_text()
'''
    live = read_position_constants(source, origin="<fixture>")
    for excluded in ("docstring_only.json", "alias_compared.json",
                     "eq_only.json", "not_in_only.json", "in_only.json"):
        assert excluded not in live, (
            f"{excluded!r} occurs ONLY where the program classifies a path it "
            f"already holds; layer 2 must not charge a read for it"
        )
    for retained in ("alias_opened.json", "built_only.json",
                     "suffix_selected.json", "rebound_one.json",
                     "rebound_two.json"):
        assert retained in live, (
            f"{retained!r} must still count: it is used to build or select a "
            f"path that is opened, or its name is bound more than once and the "
            f"alias must therefore not be resolved at all"
        )


def test_d5_compare_position_does_not_forgive_a_real_read():
    """Paired control, one literal at a time: adding a comparison changes nothing.

    A narrowing check's hazard is the NEW BLIND SPOT it creates, so the true
    positive is hidden inside it: the same literal is first only built from,
    then compared against AND built from. An implementation that counted
    occurrences the wrong way round, or stopped at the first comparison it saw,
    would silently drop the read and nothing else here would notice.
    """
    built = 'def f(root):\n    return (root / "x.json").read_text()\n'
    compared_and_built = (
        'def f(root, given):\n'
        '    if given == "x.json" or given not in ("x.json",):\n'
        '        return (root / "x.json").read_text()\n'
        '    return None\n'
    )
    compared_only = (
        'def f(given):\n'
        '    return given == "x.json" or given not in ("x.json",)\n'
    )
    assert "x.json" in read_position_constants(built, origin="<built>")
    assert "x.json" in read_position_constants(
        compared_and_built, origin="<compared_and_built>"
    ), ("a literal the program BUILDS a path from stays a read however many "
        "times it is also compared against")
    assert "x.json" not in read_position_constants(
        compared_only, origin="<compared_only>"
    ), "the exclusion must actually fire when every occurrence is a comparison"


def test_d5_read_position_analysis_is_not_a_blanket():
    """The two narrowed programs still register every read they really make.

    THIS TEST IS THE REASON THE FIRST DRAFT OF `read_position_constants` WAS
    WITHDRAWN. That draft also excluded the literal argument of
    `str.endswith` / `str.startswith`, on the reasoning that a suffix test
    classifies rather than reads. It does not: `stage_on_pass_review` selects
    the file it is about to open with
    `next((project / r for r in intent_rel if r.endswith("L5_ADI_SPEC.json")))`
    and then calls `.read_text()` on it. The draft dropped that anchor and three
    more, and NO pair-level measurement could see it — every one of those
    artefacts is produced by D1, which is in every step's closure. Only an
    anchor-level control sees an over-narrowing that costs no pair, and this is
    that control.
    """
    expected = {
        "stage_on_pass_review": {
            "L1_DATASHEET.json", "L5_ADI_SPEC.json",
            "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
            "packaging_log.json",
        },
        "flow_compliance_check": {
            "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
            "L9_INTEGRATION_SPEC.json", "extraction_patterns.json",
        },
    }
    anchors = set(unique_basename_artefacts())
    for program, must_keep in sorted(expected.items()):
        live = program_string_constants(program) & anchors
        missing = sorted(must_keep - live)
        assert not missing, (
            f"{program}.py no longer registers a read of {missing}; the "
            f"read-position analysis has widened past what it was authored for "
            f"(live anchors: {sorted(live)})"
        )


def test_d5_flow_declared_reads_resolve_for_every_dispatched_program():
    """Layer 2b must RESOLVE, per step, or it is silently doing nothing.

    A selector flag that stopped being passed, a stage id that was renamed, or a
    declaration block that moved would all leave `flow_declared_program_reads`
    returning `{}` — and `{}` means "fall back to the whole-program anchor",
    which passes quietly while the narrowing it is supposed to apply applies
    nowhere. So the steps it resolves for are pinned, and so is the fact that
    each resolution names at least one path.
    """
    resolved = {
        F.normalize_id(sid): flow_declared_program_reads(sid)
        for sid in F.step_ids()
    }
    for program in _FLOW_DECLARED_READ_PROGRAMS:
        wired = {sid for sid in resolved
                 if program in F.gate_programs(sid)}
        answered = {sid for sid, got in resolved.items() if program in got}
        assert wired, (
            f"{program} is registered in _FLOW_DECLARED_READ_PROGRAMS but is no "
            f"longer any step's gate program; delete the entry"
        )
        assert wired == answered, (
            f"{program} is a gate program of {sorted(wired)} but layer 2b "
            f"resolves a declaration for only {sorted(answered)}. An "
            f"unresolved dispatch falls back to the whole-program anchor and "
            f"the narrowing silently stops applying"
        )
        for sid in sorted(answered):
            assert resolved[sid][program], (
                f"step {sid}: the flow declares an EMPTY read set for "
                f"{program}; an empty declaration would forgive every artefact"
            )


def test_d5_the_narrowing_register_names_live_subjects():
    """`_NARROWED_LIVE_SUBJECTS` must keep describing live suppression.

    Four things per entry, each a different way the entry could go stale:

      1. the program still holds the raw basename somewhere in its source;
      2. the artefact is still a unique-basename artefact, so the anchor could
         still fire on it;
      3. the narrowing is still what silences it — the charge is absent from the
         named consumers' live `derived_dependencies`;
      4. the suppression still MATTERS — the producer is still outside each
         named consumer's closure, so without the narrowing this would still be
         a D5-MISSING-EDGE and not a charge that has since been declared.

    Without (4) this would go on passing over a register that had stopped
    forgiving anything, which is the vacuous pass this dimension exists to
    refuse.
    """
    anchors = unique_basename_artefacts()
    prod = producers()
    stale: List[str] = []
    for program, basename, consumers, why in _NARROWED_LIVE_SUBJECTS:
        path = F.program_path(program)
        assert path is not None, f"{program}.py is no longer a resolvable gate program"
        if basename not in path.read_text(encoding="utf-8", errors="replace"):
            stale.append(f"{program}.py no longer contains {basename!r} at all")
            continue
        if basename not in anchors:
            stale.append(f"{basename!r} is no longer a unique-basename artefact")
            continue
        artefact = anchors[basename]
        for consumer in consumers:
            if not F.has_step(consumer):
                stale.append(f"{consumer} is no longer a declared step")
                continue
            if program not in F.gate_programs(consumer):
                stale.append(
                    f"{program} is no longer a gate program of step {consumer}"
                )
                continue
            charged = {art for _p, art, _e in derived_dependencies(consumer)}
            if artefact in charged:
                stale.append(
                    f"step {consumer} is charged with reading {artefact} again; "
                    f"the entry is wrong or the read is real. Reason on file: {why}"
                )
                continue
            unordered = [p for p in prod[artefact]
                         if p != consumer and p not in ancestors(consumer)]
            if not unordered:
                stale.append(
                    f"step {consumer} -> {artefact}: every producer "
                    f"{sorted(prod[artefact])} is now in its closure, so this "
                    f"would no longer be a D5-MISSING-EDGE; delete the entry"
                )
    assert not stale, (
        "the narrowing register no longer describes live suppression — it may "
        "only SHRINK, and shrinking means deleting the entry: " + "; ".join(stale)
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

    THE LOOP IS EMPTY TODAY. All five dimension-5 waivers — every one of them
    labelled "LIVE DEFECT, reproduced" — were closed by fixing the dependency,
    so ``W.validate`` is never called below. An empty loop must not report
    green on its own, so the set is PINNED, not floored: #530's
    ``assert dim_waivers()`` was correct while five entries existed and is a
    permanent red once none do. The pin reddens the day a waiver is added, and
    the loop underneath is what grades it.
    """
    live = {w.label for w in dim_waivers()}
    assert live == WAIVED_CELLS_PINNED, (
        f"dimension {DIM}'s waiver set changed to {sorted(live)}; it is pinned "
        f"at {sorted(WAIVED_CELLS_PINNED)}. Adding one is a public admission "
        f"and must be argued for in the same change that pins it here."
    )
    applied = {F.normalize_id(sid) for sid in F.step_ids()
               if _waiver_for(sid) is not None}
    assert applied == {F.normalize_id(w.step_id) for w in dim_waivers()}, (
        f"cells this dimension WAIVES {sorted(applied)} do not match the "
        f"registry entries "
        f"{sorted(F.normalize_id(w.step_id) for w in dim_waivers())}"
    )
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


# ══════════════════════════════════════════════════════════════════════
# LAYER 3's own anti-starvation and anti-forgiveness guards
# ══════════════════════════════════════════════════════════════════════
#: Live floors, same idiom as the layer-1+2 trio above: a FLOOR, so a new
#: `required_inputs` entry is free and a silent shrink is not.
#:
#: RE-DERIVED 2026-08-31, 54/69 -> 58/76, and the reason is worth stating because
#: it is the failure mode this whole trio guards against, one level up. These are
#: `>=` guards, so the tree growing past them costs nothing and reddens nothing —
#: which means a floor written as "the live baseline" stops BEING the live
#: baseline the first time the flow grows, silently, and the ratchet it is
#: supposed to be can no longer see a shrink back to the old number. Measured on
#: `781d24727` [v1.14.22]: declared 54/69, live 58/76. The layer-1+2 trio above
#: had drifted further (12/16/32 declared against 23/37/92 live, nearly 3x) and
#: was re-derived in the same change. NOTHING here moved them: this layer reads
#: `required_inputs`, and that change touched `required_outputs`.
_DECLARED_DEP_STEPS_FLOOR = 58
_DECLARED_DEP_PAIRS_FLOOR = 76


def test_d5_declared_input_denominator_is_disclosed():
    """Layer 3 must not quietly become vacuous either.

    The measured figures on the tree that added this layer, and the reason the
    layer exists at all:

        layer 1+2 (RECONSTRUCTED from artefact reads) : 12 steps, 16 pairs
        layer 3   (DECLARED by the flow itself)       : 54 steps, 69 pairs

    A dimension asking "is `blocks_on` the true upstream set" was checking it
    against the 16 and had never read the 69. If `required_inputs` is ever
    renamed, restructured or emptied, this clause resolves to zero pairs and
    all 63 cells go green on a question nobody asked — the exact starvation
    shape `test_d5_derived_dependency_denominator_is_disclosed` exists for.
    """
    steps = [sid for sid in F.step_ids() if declared_input_dependencies(sid)]
    pairs = {(F.normalize_id(sid), p)
             for sid in F.step_ids()
             for p, _ in declared_input_dependencies(sid)}
    assert len(steps) >= _DECLARED_DEP_STEPS_FLOOR, (
        f"layer-3 consumer relation SHRANK: {len(steps)} steps declare an "
        f"intra-flow `required_inputs.from`, floor is "
        f"{_DECLARED_DEP_STEPS_FLOOR}. A shrinking denominator is how this "
        f"clause becomes a suite of vacuous passes."
    )
    assert len(pairs) >= _DECLARED_DEP_PAIRS_FLOOR, (
        f"layer-3 pairs SHRANK: {len(pairs)} < {_DECLARED_DEP_PAIRS_FLOOR}"
    )


def test_d5_external_inputs_are_named_not_silently_dropped():
    """The fail-safe class, counted rather than assumed.

    Layer 3 declines every `from` that names no declared step. That discount
    is correct — no edge to a non-existent step is possible — and it is also
    the one place layer 3 could silently forgive everything: if `has_step`
    ever started returning False for real ids, every pair would be discounted
    as "external" and the clause would go green over nothing.
    """
    external = {F.normalize_id(sid): external_input_declarations(sid)
                for sid in F.step_ids() if external_input_declarations(sid)}
    total_from = sum(
        1 for sid in F.step_ids()
        for e in (F.step_by_id(sid).get("required_inputs") or [])
        if isinstance(e, dict) and e.get("from") is not None
    )
    n_ext = sum(len(v) for v in external.values())
    assert n_ext < total_from / 2, (
        f"{n_ext} of {total_from} `required_inputs.from` values resolve to no "
        f"declared step. Layer 3 discounts every one of them, so at this "
        f"proportion the clause is forgiving more than it measures: {external}"
    )
    assert external, (
        "no step declares an input from outside the flow, so the fail-safe "
        "branch of layer 3 is unreachable and untested on this tree"
    )


def test_d5_the_deferred_register_only_shrinks():
    """`_DEFERRED_LAYER3_EDGES` is an admission, not an exemption.

    Every entry must still be a LIVE defect. When vibe-ic#1070 lands, each
    edge gains its `blocks_on` declaration, the entry stops describing
    anything, and this test reddens until it is deleted — so the register
    cannot outlive the debt it records, which is how a shrink-only baseline
    turns into a permanent amnesty.
    """
    stale = []
    for sid, producers_ in sorted(_DEFERRED_LAYER3_EDGES.items()):
        assert F.has_step(sid), f"deferred register names unknown step {sid!r}"
        closure = ancestors(sid)
        declared = {p for p, _ in declared_input_dependencies(sid)}
        for producer in producers_:
            if producer not in declared:
                stale.append(f"{sid} no longer declares it reads {producer}")
            elif producer in closure:
                stale.append(
                    f"{sid} -> {producer} is now ORDERED (closure="
                    f"{sorted(closure)}); vibe-ic#1070 has landed for this "
                    f"edge, so delete the register entry"
                )
    assert not stale, (
        "the deferred-edge register no longer describes live defects — it may "
        "only SHRINK, and shrinking means deleting the entry: " + "; ".join(stale)
    )


def test_d5_the_deferred_register_is_the_only_thing_holding_those_cells_green():
    """Paired control: remove the forgiveness and the three cells must go red.

    A register that forgives nothing is indistinguishable from no register,
    and would let a future edit quietly drop the real charge while this file
    still looked like it was tracking three defects.
    """
    # deduped by (consumer, producer): A1 declares `from: D1` TWICE, once for
    # L1_DATASHEET.json and once for L5_ADI_SPEC.json. Two declarations, one
    # missing edge — the register records edges, so the comparison must too.
    charged = {(sid, producer)
               for sid in _DEFERRED_LAYER3_EDGES
               for producer, _ in declared_input_dependencies(sid)
               if producer not in ancestors(sid)}
    registered = {(sid, p)
                  for sid, ps in _DEFERRED_LAYER3_EDGES.items() for p in ps}
    assert charged == registered, (
        f"the register and the live measurement disagree: measured "
        f"{sorted(charged)}, registered {sorted(registered)}"
    )

    # ANTI-VACUITY. The comparison above is {} == {} while the register is
    # empty, so on its own it would assert nothing. These three edges are the
    # debt #1070 paid; requiring them to STAY ordered keeps this control live.
    for sid, producer in _FORMERLY_DEFERRED_LAYER3_EDGES:
        assert producer in ancestors(sid), (
            f"{sid} -> {producer} was a deferred layer-3 edge until #1070 "
            f"declared it, and it is unordered again (closure="
            f"{sorted(ancestors(sid))}). The debt this register recorded has "
            f"come back; re-open the entry rather than re-deleting this check."
        )
