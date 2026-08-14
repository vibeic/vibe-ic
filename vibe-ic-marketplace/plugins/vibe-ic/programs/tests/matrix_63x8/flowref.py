"""matrix_63x8.flowref — LIVE, cached accessors over the flow yaml.

Everything here is recomputed from
``<plugin_root>/flow/phase1_phase2_phase3.yaml`` on first access and then
memoised for the process. Nothing in this module reads ``.audit_63x8.json``:
the audit is history, the yaml is the repo. If a step is added, removed or
re-gated, every accessor below changes with it — which is precisely what makes
the 504<!--figure:ledger_cells-->-cell ledger self-invalidating.

====================================================================
THE GRAMMAR, AS MEASURED (not as remembered)
====================================================================
Every claim below was checked against the yaml at
``flow/phase1_phase2_phase3.yaml`` (63<!--figure:flow_steps--> steps) and,
where the semantics live in
a consumer rather than in the data, against that consumer's source.

--------------------------------------------------------------------
1. Steps
--------------------------------------------------------------------
``yaml.safe_load(...)["steps"]`` is a list of 63<!--figure:flow_steps--> dicts.
**Step ids are mixed types**: 44<!--figure:flow_steps_int--> ``int`` (1..44)
and 19<!--figure:flow_steps_str--> ``str`` (``D1``, ``P0``, ``FS1``, ``DT1``
``DT2`` ``DT3``, ``A1``-``A9`` minus ``A0``, ``M1``-``M4``). Never assume int;
never sort them naively. Use :func:`normalize_id` (``str()``) for dict keys and
:func:`step_ids` for the raw, declaration-ordered tuple.

Key presence, DERIVED — every digit below is written by
``tools/gen_matrix_63x8_census.py`` from the yaml, and the ``<!--figure:...-->``
anchor beside it names the binding that produced it. Do not hand-edit them:
run ``--fix-figures``, and ``--check`` fails on drift (vibe-ic#961).

    gate
        present on 62<!--figure:gate_declared--> steps,
        non-empty on 62<!--figure:gated_steps--> (absent on P0 only)
    required_outputs
        present on 61<!--figure:required_output_declared--> steps,
        non-empty on 61<!--figure:required_output_steps--> (absent on FS1 and P0)
    blocks_on
        present on 63<!--figure:blocks_on_declared--> steps,
        non-empty on 62<!--figure:blocks_on_nonempty--> (declared on every step;
        PRESENT-BUT-EMPTY on D1 and A1, the two genuine graph roots)

The ``present`` column is a PRESENCE count. ``blocks_on`` is non-empty on only
62<!--figure:blocks_on_nonempty--> steps. Any test that conflates the two will
be wrong about D1 and A1.

Top-level ``total_steps: 44`` counts the numeric steps ONLY. It is NOT
``len(steps)``. Do not assert ``total_steps == 63``.

--------------------------------------------------------------------
2. ``required_outputs`` — ALL-of across entries, any-of inside one entry
--------------------------------------------------------------------
The list is **ALL-of-N**: every entry must be satisfied. This is not inferable
from the yaml alone — it lives in the consumer, and it is load-bearing enough
that it was once the opposite. See ``programs/flow_compliance_check.py`` around
line 6150::

    # EACH declared entry must be satisfied - the list is ALL-of-N ...
    # It used to be any-of-N: evidence was accumulated across entries and
    # MISSING fired only when the COMBINED evidence list was empty, so a step
    # declaring five outputs passed this check on the strength of one.

Within a single entry, ``" OR "`` is **any-of**: it spells one artefact that
legitimately has several accepted names or locations (a cocotb ``results.xml``
OR a sim ``*.log`` OR a ``pass.flag``; a ``drc_clean.flag`` OR a ``.lyrdb``).
The consumer splits on the literal ``" OR "`` (spaces included) and strips each
alternative — :func:`split_any_of` reproduces exactly that.

Live entry census — 136<!--figure:required_output_entries--> entries over
61<!--figure:required_output_steps--> steps, classified by
:func:`classify_output` (digits derived; see the anchor note in §1):

    FILE          102<!--figure:required_outputs_file-->
        plain relative path, no wildcard, no " OR "
    GLOB          12<!--figure:required_outputs_glob-->
        wildcard, no " OR " (e.g. ``phase1/generated_docs/L13_*.json``)
    ANY_OF        22<!--figure:required_outputs_any_of-->
        contains " OR " (each alternative may itself be a glob; one entry —
        step 4 — uses a recursive ``**`` alternative)
    PROGRAM_EXIT   0<!--figure:required_outputs_program_exit-->
        *** see below ***

**Contradiction with the brief, reported deliberately**: there is NO
``program_exit_zero: "<cmd>"`` form anywhere in ``required_outputs``. All
136<!--figure:required_output_entries--> entries are plain strings; not one contains the token ``program_exit_zero``.
That form exists only inside ``gate`` clauses (§3). :data:`PROGRAM_EXIT` is
still returned by :func:`classify_output` for forward compatibility, but on the
current yaml it never fires — a sibling that branches on it is writing dead
code, and a sibling that *asserts* on it is asserting on nothing.

Glob resolution is ``pathlib.Path.glob`` relative to the project root, so
``**`` is recursive. Two non-obvious fallbacks in the real consumer
(``flow_compliance_check._glob_first``) mean a naive glob will produce FALSE
NEGATIVES against a real run tree:
  * a ``reports/<rest>`` pattern that misses is re-probed as
    ``reports/<subdir>/<rest>`` for each known category subdir; and
  * a ``phase{1,2,3}/analog/<tail>`` pattern that misses is re-probed under the
    single canonical analog dir.
This module deliberately does NOT reimplement those fallbacks: it hands back
raw entries. Anything that resolves an entry against a real project tree must
either call the real helper or document that it is using the strict form.

--------------------------------------------------------------------
3. ``gate`` grammar
--------------------------------------------------------------------
Top-level shapes over 62<!--figure:gated_steps--> gates — how many gates carry
each key (a gate may carry more than one, so these do not partition):

    {'all_of': [...]}                 48<!--figure:gate_shape_all_of-->
    {'program_exit_zero': <str|dict>} 13<!--figure:gate_shape_program_exit_zero-->
                                      (dict form once, on step 16:
                                       {'command': '...'} )
    {'files_exist': [...]}             1<!--figure:gate_shape_files_exist-->
                                      (step 1, with 'any_of': True)

Clause census, NORMALISED by :func:`gate_clauses` over every gated step. This
replaces a hand-counted table of raw ``all_of`` members: the raw table counted
a different population from the accessor this module tells you to use, so the
two could not be reconciled by a reader and only one of them was derived.

    program_exit_zero          104<!--figure:gate_clauses_program_exit_zero-->  MANDATORY
    advisory_program_exit_zero 37<!--figure:gate_clauses_advisory_program_exit_zero-->  NON-BLOCKING
    files_exist                32<!--figure:gate_clauses_files_exist-->
    optional_program_exit_zero 28<!--figure:gate_clauses_optional_program_exit_zero-->  conditional
    json_field_true             1<!--figure:gate_clauses_json_field_true-->
    ------------------------------
    total                     202<!--figure:gate_clauses_total-->, of which
                              165<!--figure:blocking_clauses--> block

Three different exit-zero kinds with three different force levels:
  * ``program_exit_zero``          — blocking.
  * ``advisory_program_exit_zero`` — runs, reports, does NOT block. A test that
    treats an advisory clause as enforcement is measuring something adjacent.
  * ``optional_program_exit_zero`` — blocking **only when** every path in
    ``condition_files_exist`` is present. This is the flow's legitimate skip
    mechanism and therefore the main surface for dimension 6.
Use :func:`gate_clauses` (typed) rather than re-walking the dict.

--------------------------------------------------------------------
4. Program resolution
--------------------------------------------------------------------
A gate command's FIRST whitespace token is the program basename. All
160<!--figure:gate_program_tokens_distinct--> distinct tokens across the
169<!--figure:gate_commands_total--> gate commands resolve to
``programs/<token>.py`` — there are 0<!--figure:gate_programs_unresolved-->
unresolvable tokens and zero commands
that shell out via ``python3 <file>``. :func:`gate_programs` returns only
tokens that resolve to a file that actually exists, so it is a live statement
about the source tree, not about the yaml's spelling. Use
:func:`gate_program_tokens` when you need the declared-but-possibly-missing
form (that difference IS the dimension-1 wiring question).

61<!--figure:steps_naming_a_program--> of the
62<!--figure:gated_steps--> gated steps name at least one program. Step 1 has a
file-existence-only gate and legitimately names none.

--------------------------------------------------------------------
5. ``blocks_on``
--------------------------------------------------------------------
97<!--figure:blocks_on_edges--> edges, mixed types
(80<!--figure:blocks_on_edges_int--> int, 17<!--figure:blocks_on_edges_str--> str),
every target resolving to a declared step id — no dangling references at time of writing. Compare with
:func:`normalize_id` on both sides; the real consumers stringify
(``{str(id): [str(e) for e in blocks_on]}``).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

StepId = Union[str, int]

# ──────────────────────────────────────────────────────────────────────
# Tree anchors
# ──────────────────────────────────────────────────────────────────────
_MANIFEST_REL = Path(".claude-plugin") / "plugin.json"


def _find_plugin_root(start: Path) -> Path:
    """Walk up from *start* to the directory holding the plugin manifest.

    Duplicated (8 lines) from ``programs/tests/_plugin_tree.py`` on purpose:
    this package must be importable without the tests conftest having run, so
    it cannot depend on ``sys.path`` having the tests dir on it.
    """
    cur = start if start.is_dir() else start.parent
    for cand in (cur, *cur.parents):
        if (cand / _MANIFEST_REL).is_file():
            return cand
    raise RuntimeError(
        f"plugin manifest {_MANIFEST_REL} not found walking up from {start}"
    )


PLUGIN_ROOT: Path = _find_plugin_root(Path(__file__).resolve())
FLOW_YAML: Path = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"
PROGRAMS_DIR: Path = PLUGIN_ROOT / "programs"

#: Env var that redirects :data:`FLOW_YAML` at a mutated copy.
#:
#: This exists for ONE purpose: proving a predicate is falsifiable. "Mutate the
#: thing the test guards and prove the test goes red" is a hard requirement of
#: this campaign, and the thing most predicates guard is the flow yaml — which
#: is shared by eight concurrent agents and must never be edited in place.
#: Point this at a scratch copy instead, then call :func:`clear_caches`.
#:
#: It is also a loaded gun: a suite run with it set is measuring a file nobody
#: reviewed. ``test_matrix_63x8_ledger.py`` asserts it is UNSET, so a normal run
#: cannot silently be redirected.
FLOW_YAML_ENV = "VIBE_IC_MATRIX_FLOW_YAML"

_override = os.environ.get(FLOW_YAML_ENV)
if _override:
    FLOW_YAML = Path(_override)

# ──────────────────────────────────────────────────────────────────────
# Output-entry classification
# ──────────────────────────────────────────────────────────────────────
FILE = "FILE"
GLOB = "GLOB"
ANY_OF = "ANY_OF"
PROGRAM_EXIT = "PROGRAM_EXIT"

OUTPUT_KINDS: Tuple[str, ...] = (FILE, GLOB, ANY_OF, PROGRAM_EXIT)

#: The literal separator the real consumer splits on. Spaces are part of it —
#: ``flow_compliance_check`` does ``pat.split(" OR ")``, so a path component
#: containing the bare word "OR" is not an alternation.
ANY_OF_SEP = " OR "

_GLOB_CHARS = "*?["

# ──────────────────────────────────────────────────────────────────────
# Gate-clause kinds
# ──────────────────────────────────────────────────────────────────────
K_PROGRAM = "program_exit_zero"
K_ADVISORY = "advisory_program_exit_zero"
K_OPTIONAL = "optional_program_exit_zero"
K_FILES = "files_exist"
K_JSON_FIELD = "json_field_true"

GATE_CLAUSE_KINDS: Tuple[str, ...] = (
    K_PROGRAM,
    K_ADVISORY,
    K_OPTIONAL,
    K_FILES,
    K_JSON_FIELD,
)

#: Clause kinds that name a program to execute.
EXEC_CLAUSE_KINDS: Tuple[str, ...] = (K_PROGRAM, K_ADVISORY, K_OPTIONAL)


@dataclass(frozen=True)
class GateClause:
    """One normalised clause of a step's gate.

    ``kind`` is one of :data:`GATE_CLAUSE_KINDS`. Only the fields relevant to
    that kind are populated; the rest keep their empty defaults. ``raw`` is a
    stable JSON dump of the original clause so a clause stays hashable and a
    failure message can quote the source form verbatim.
    """

    kind: str
    command: Optional[str] = None
    program: Optional[str] = None
    files: Tuple[str, ...] = ()
    any_of: bool = False
    condition_files: Tuple[str, ...] = ()
    json_file: Optional[str] = None
    json_field: Optional[str] = None
    json_expect: Optional[str] = None
    raw: str = ""

    @property
    def is_advisory(self) -> bool:
        """True when the clause runs but cannot block the step."""
        return self.kind == K_ADVISORY

    @property
    def is_conditional(self) -> bool:
        """True when the clause only blocks if its condition files exist."""
        return self.kind == K_OPTIONAL

    @property
    def is_blocking(self) -> bool:
        """True when a non-zero exit / missing file fails the step outright.

        ``optional_program_exit_zero`` counts as blocking here because it DOES
        fail the step when its condition is met; whether the condition is
        reachable is a separate (dimension-6) question.
        """
        return self.kind != K_ADVISORY


# ──────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def load_flow() -> Dict[str, Any]:
    """Parse and return the whole flow yaml document (cached)."""
    with FLOW_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def steps() -> Tuple[Dict[str, Any], ...]:
    """All step dicts in declaration order (63 at time of writing)."""
    return tuple(load_flow()["steps"])


@lru_cache(maxsize=1)
def step_ids() -> Tuple[StepId, ...]:
    """Step ids in declaration order, **raw mixed types** (str and int)."""
    return tuple(s["id"] for s in steps())


def normalize_id(step_id: StepId) -> str:
    """Canonical dict key for a step id. ``1`` and ``'1'`` collapse to ``'1'``.

    This mirrors what the real consumers do
    (``{str(id): [str(e) for e in blocks_on]}`` in ``flow_compliance_check``).
    """
    return str(step_id)


@lru_cache(maxsize=1)
def _by_id() -> Dict[str, Dict[str, Any]]:
    return {normalize_id(s["id"]): s for s in steps()}


def step_by_id(step_id: StepId) -> Dict[str, Any]:
    """The step dict for *step_id*. Accepts either the int or the str form.

    Raises ``KeyError`` with the full id list when the step does not exist —
    a step that vanished from the yaml should be loud, not silently skipped.
    """
    key = normalize_id(step_id)
    table = _by_id()
    if key not in table:
        raise KeyError(
            f"no step {step_id!r} in {FLOW_YAML}; declared ids: {list(table)}"
        )
    return table[key]


def has_step(step_id: StepId) -> bool:
    return normalize_id(step_id) in _by_id()


# ──────────────────────────────────────────────────────────────────────
# Per-step fields
# ──────────────────────────────────────────────────────────────────────
def step_name(step_id: StepId) -> str:
    return str(step_by_id(step_id).get("name", ""))


def step_stage(step_id: StepId) -> str:
    return str(step_by_id(step_id).get("stage", ""))


def has_gate(step_id: StepId) -> bool:
    """True when the step DECLARES a ``gate`` key at all."""
    return step_by_id(step_id).get("gate") is not None


def gate(step_id: StepId) -> Optional[Dict[str, Any]]:
    """The raw ``gate`` dict, or ``None`` when the step declares no gate."""
    g = step_by_id(step_id).get("gate")
    return g if isinstance(g, dict) else None


def step_condition(step_id: StepId) -> Optional[Dict[str, Any]]:
    """The step-level ``condition`` (applicability predicate), if declared.

    22 steps carry one; every one measured is ``{'files_exist': [...]}``
    optionally with ``any_of: True``. A step whose condition is unsatisfied is
    SKIPPED-CONDITION rather than FAIL — the dimension-6 surface.
    """
    c = step_by_id(step_id).get("condition")
    return c if isinstance(c, dict) else None


def declared_programs(step_id: StepId) -> Tuple[str, ...]:
    """The step's ``programs:`` list (documentation), NOT its gate commands.

    42 steps declare this. It is prose-level metadata: a program listed here is
    not necessarily wired into the gate, and that gap is exactly the
    dimension-1 question. Use :func:`gate_programs` for what actually runs.
    """
    return tuple(step_by_id(step_id).get("programs") or ())


def declared_skills(step_id: StepId) -> Tuple[str, ...]:
    return tuple(step_by_id(step_id).get("skills") or ())


def closed_loop(step_id: StepId) -> Optional[Dict[str, Any]]:
    cl = step_by_id(step_id).get("closed_loop")
    return cl if isinstance(cl, dict) else None


@lru_cache(maxsize=None)
def required_outputs(step_id: StepId) -> Tuple[str, ...]:
    """Raw, UNSPLIT ``required_outputs`` entries. Empty tuple when undeclared.

    ALL-of across the tuple; ``" OR "`` inside one element is any-of. See the
    module docstring, §2.
    """
    return tuple(step_by_id(step_id).get("required_outputs") or ())


@lru_cache(maxsize=None)
def blocks_on(step_id: StepId) -> Tuple[StepId, ...]:
    """Raw ``blocks_on`` entries, mixed types, in declaration order.

    Empty tuple both when the key is ABSENT and when it is declared EMPTY
    (D1, A1). Use :func:`declares_blocks_on` to tell those apart — they mean
    different things: "nobody wrote a dependency list" vs "this is a root".

    The ABSENT case has NO example on the current yaml. P0 was the only step
    without the key and #929 gave it one, so every step now declares
    ``blocks_on`` and the two cases are told apart by D1/A1 alone. The
    distinction is kept because it is a property of the accessor, not of
    today's yaml — but a reader must not go looking for the absent step.
    """
    return tuple(step_by_id(step_id).get("blocks_on") or ())


def declares_blocks_on(step_id: StepId) -> bool:
    """True when the ``blocks_on`` KEY is present, even if the list is empty."""
    return "blocks_on" in step_by_id(step_id)


def declares_required_outputs(step_id: StepId) -> bool:
    """True when the ``required_outputs`` KEY is present."""
    return "required_outputs" in step_by_id(step_id)


# ──────────────────────────────────────────────────────────────────────
# required_outputs entry classification
# ──────────────────────────────────────────────────────────────────────
def classify_output(entry: str) -> str:
    """Classify one ``required_outputs`` entry as FILE | GLOB | ANY_OF |
    PROGRAM_EXIT.

    Order of tests matters and is deliberate:
      1. ``" OR "`` anywhere  -> ANY_OF   (its alternatives may be globs)
      2. ``program_exit_zero`` prefix -> PROGRAM_EXIT (never seen; see §2)
      3. a wildcard char      -> GLOB
      4. otherwise            -> FILE
    """
    if not isinstance(entry, str):
        raise TypeError(f"required_outputs entry must be str, got {entry!r}")
    text = entry.strip()
    if ANY_OF_SEP in entry:
        return ANY_OF
    if text.startswith("program_exit_zero:") or text.startswith(
        "program_exit_zero "
    ):
        return PROGRAM_EXIT
    if any(ch in text for ch in _GLOB_CHARS):
        return GLOB
    return FILE


def split_any_of(entry: str) -> Tuple[str, ...]:
    """Split one entry into its any-of alternatives, exactly as the consumer
    does (``entry.split(" OR ")`` then ``.strip()``).

    A non-alternation entry yields a 1-tuple, so callers never need to branch.
    """
    return tuple(p.strip() for p in entry.split(ANY_OF_SEP) if p.strip())


def is_glob(pattern: str) -> bool:
    """True when *pattern* contains a wildcard understood by ``Path.glob``."""
    return any(ch in pattern for ch in _GLOB_CHARS)


# ──────────────────────────────────────────────────────────────────────
# Gate walking
# ──────────────────────────────────────────────────────────────────────
def _raw(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # pragma: no cover - defensive
        return repr(obj)


def _exec_clause(kind: str, value: Any) -> Optional[GateClause]:
    """Build a clause for one of the three *_program_exit_zero kinds.

    Handles all three spellings seen in the yaml: a bare command string, a
    ``{'command': ...}`` dict (step 16), and the optional form's
    ``{'command': ..., 'condition_files_exist': [...]}``.
    """
    command: Optional[str] = None
    cond: Tuple[str, ...] = ()
    if isinstance(value, str):
        command = value
    elif isinstance(value, dict):
        cmd = value.get("command")
        if isinstance(cmd, str):
            command = cmd
        cf = value.get("condition_files_exist")
        if isinstance(cf, list):
            cond = tuple(str(x) for x in cf)
    if command is None:
        return None
    tokens = command.split()
    return GateClause(
        kind=kind,
        command=command,
        program=tokens[0] if tokens else None,
        condition_files=cond,
        raw=_raw({kind: value}),
    )


def _walk_gate(node: Any, out: List[GateClause]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_gate(item, out)
        return
    if not isinstance(node, dict):
        return

    for kind in EXEC_CLAUSE_KINDS:
        if kind in node:
            clause = _exec_clause(kind, node[kind])
            if clause is not None:
                out.append(clause)

    if K_FILES in node and isinstance(node[K_FILES], list):
        out.append(
            GateClause(
                kind=K_FILES,
                files=tuple(str(x) for x in node[K_FILES]),
                # `any_of` is a SIBLING boolean of files_exist, not a nested
                # clause: {'files_exist': [...], 'any_of': True}. 8 clauses use
                # it inside all_of plus 1 at gate top level (step 1).
                any_of=bool(node.get("any_of") is True),
                raw=_raw(node),
            )
        )

    if K_JSON_FIELD in node and isinstance(node[K_JSON_FIELD], dict):
        jf = node[K_JSON_FIELD]
        out.append(
            GateClause(
                kind=K_JSON_FIELD,
                json_file=str(jf.get("file")) if jf.get("file") is not None else None,
                json_field=(
                    str(jf.get("field")) if jf.get("field") is not None else None
                ),
                json_expect=(
                    str(jf.get("expect")) if jf.get("expect") is not None else None
                ),
                raw=_raw(node),
            )
        )

    if "all_of" in node:
        _walk_gate(node["all_of"], out)
    if "any_of" in node and isinstance(node["any_of"], list):
        # Not present in the current yaml (every `any_of` seen is the sibling
        # boolean form) but cheap to support so a future list form is not
        # silently dropped.
        _walk_gate(node["any_of"], out)


@lru_cache(maxsize=None)
def gate_clauses(step_id: StepId) -> Tuple[GateClause, ...]:
    """Every gate clause of *step_id*, flattened and typed.

    Empty tuple for a step with no gate (P0). Nesting is flattened: the current
    yaml is at most one level deep (``all_of`` -> clause), but the walker is
    recursive so a future nested form does not silently vanish.
    """
    g = gate(step_id)
    if g is None:
        return ()
    out: List[GateClause] = []
    _walk_gate(g, out)
    return tuple(out)


def gate_commands(step_id: StepId) -> Tuple[str, ...]:
    """Full command strings of every exec clause, in declaration order."""
    return tuple(
        c.command for c in gate_clauses(step_id) if c.command is not None
    )


def gate_program_tokens(step_id: StepId) -> Tuple[str, ...]:
    """Program basenames as DECLARED in the gate, deduped, order preserved.

    Includes tokens that do NOT resolve to a file. The difference between this
    and :func:`gate_programs` is a live statement about wiring: a token here but
    not there names a program the yaml believes in and the tree does not have.
    """
    seen: List[str] = []
    for clause in gate_clauses(step_id):
        if clause.program and clause.program not in seen:
            seen.append(clause.program)
    return tuple(seen)


@lru_cache(maxsize=None)
def program_path(basename: str) -> Optional[Path]:
    """``programs/<basename>.py`` if it exists on disk, else ``None``.

    Existence only — resolution here is a filesystem fact, deliberately not an
    import, because importing 127 programs to answer "is it wired" would be
    both slow and a different question.
    """
    if not basename:
        return None
    cand = PROGRAMS_DIR / f"{basename}.py"
    return cand if cand.is_file() else None


@lru_cache(maxsize=None)
def gate_programs(step_id: StepId) -> Tuple[str, ...]:
    """Gate-named program basenames that RESOLVE to an existing file.

    Order-preserving, deduped. This is the accessor most siblings want: it is
    simultaneously a statement about the yaml (the name is declared) and about
    the tree (the file is there).
    """
    return tuple(
        tok for tok in gate_program_tokens(step_id) if program_path(tok) is not None
    )


def unresolved_gate_programs(step_id: StepId) -> Tuple[str, ...]:
    """Gate-named basenames with NO matching ``programs/<name>.py``.

    Zero across all 63 steps at time of writing. A non-empty result is a
    dimension-1 wiring defect, live.
    """
    return tuple(
        tok for tok in gate_program_tokens(step_id) if program_path(tok) is None
    )


# ──────────────────────────────────────────────────────────────────────
# Whole-flow convenience
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def all_gate_programs() -> Tuple[str, ...]:
    """Every resolved gate program across the whole flow, sorted and deduped."""
    acc = set()
    for sid in step_ids():
        acc.update(gate_programs(sid))
    return tuple(sorted(acc))


@lru_cache(maxsize=1)
def dependency_graph() -> Dict[str, Tuple[str, ...]]:
    """``{normalized_id: (normalized upstream ids, ...)}`` for all 63 steps.

    Stringified on both sides, matching the real consumers.
    """
    return {
        normalize_id(sid): tuple(normalize_id(e) for e in blocks_on(sid))
        for sid in step_ids()
    }


def set_flow_yaml(path: Path) -> None:
    """Repoint :data:`FLOW_YAML` and drop every memo.

    Falsifiability harness only — see :data:`FLOW_YAML_ENV`. Callers MUST
    restore the original path (``set_flow_yaml(ORIGINAL)``) in a ``finally``,
    and must re-import / rebuild anything that snapshotted the flow at import
    time (``cells.ALL_CELLS`` does).
    """
    global FLOW_YAML
    FLOW_YAML = Path(path)
    clear_caches()


def clear_caches() -> None:
    """Drop every memo. For tests that rewrite the yaml under a tmp path."""
    for fn in (
        load_flow,
        steps,
        step_ids,
        _by_id,
        required_outputs,
        blocks_on,
        gate_clauses,
        program_path,
        gate_programs,
        all_gate_programs,
        dependency_graph,
    ):
        fn.cache_clear()


__all__ = [
    "StepId",
    "PLUGIN_ROOT",
    "FLOW_YAML",
    "FLOW_YAML_ENV",
    "PROGRAMS_DIR",
    "FILE",
    "GLOB",
    "ANY_OF",
    "PROGRAM_EXIT",
    "OUTPUT_KINDS",
    "ANY_OF_SEP",
    "GateClause",
    "GATE_CLAUSE_KINDS",
    "EXEC_CLAUSE_KINDS",
    "K_PROGRAM",
    "K_ADVISORY",
    "K_OPTIONAL",
    "K_FILES",
    "K_JSON_FIELD",
    "load_flow",
    "steps",
    "step_ids",
    "normalize_id",
    "step_by_id",
    "has_step",
    "step_name",
    "step_stage",
    "has_gate",
    "gate",
    "step_condition",
    "declared_programs",
    "declared_skills",
    "closed_loop",
    "required_outputs",
    "declares_required_outputs",
    "blocks_on",
    "declares_blocks_on",
    "classify_output",
    "split_any_of",
    "is_glob",
    "gate_clauses",
    "gate_commands",
    "gate_program_tokens",
    "gate_programs",
    "unresolved_gate_programs",
    "program_path",
    "all_gate_programs",
    "dependency_graph",
    "clear_caches",
    "set_flow_yaml",
]
