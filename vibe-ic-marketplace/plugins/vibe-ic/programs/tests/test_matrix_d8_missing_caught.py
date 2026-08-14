"""DIMENSION 8 of the 63x8 matrix — ``missing_caught``.

    "If a declared output is MISSING, does the mechanism CATCH it?"

Dimensions 1-7 interrogate the GATE. This one interrogates the CATCHER, and
the catcher is one specific function: :func:`flow_compliance_check.check_step`.
Everything below drives that real function against a real synthesized project
tree and reads its real verdict.

====================================================================
WHAT IS MEASURED, AND WHAT IS HELD CONSTANT
====================================================================
Every cell is decided by TWO halves. The second half is the one that makes the
first falsifiable:

  POSITIVE  materialize every declared ``required_outputs`` entry as a
            non-empty file, run ``check_step`` → the verdict must NOT be
            MISSING.
  NEGATIVE  remove EXACTLY ONE declared entry, re-run → the verdict must
            BECOME MISSING.

The negative half is parametrized over **every (step, entry) pair**, not one
entry per step. That is the whole content of ALL-of-N semantics and it is what
PR #455 established: ``required_outputs`` used to pool evidence across entries,
so a step declaring five artefacts reported PASS on the strength of one. The
regression that reopens that hole is "all but one present", which a
one-entry-per-step probe cannot see. See ``flow_compliance_check.py`` ~line
6160 for the fix's own account of the two verdicts it was measured against
(step 21 declared an absent ``drc.rpt`` and PASSed on ``routed.def``; step 9
declared an absent ``area.rpt OR stats.json`` and PASSed on ``netlist.v``).

**NOTHING in flow_compliance_check is stubbed or monkeypatched.** The real
``check_step``, the real ``_evaluate_gate``, the real ``_glob_first``,
``_evidence_integrity_scan`` and ``_apply_capability_gap`` all run.

What IS held constant is the step's *declared gate*, which is replaced for the
duration of a case by a genuine, minimal gate the real ``_evaluate_gate``
evaluates for real:

    PASS-tier  ``{"files_exist": ["_d8_gate/gate_ok.flag"]}``  (file present)
    FAIL-tier  ``{"files_exist": ["_d8_gate/absent.flag"]}``   (file absent)

This is not a shortcut, it is the isolation the question requires. A step's own
gate runs OpenROAD / KLayout / yosys against a converged tree; on a synthesized
fixture almost every declared gate FAILs, and FAIL is *not* a PASS-tier verdict,
so the MISSING downgrade would never be reachable and both halves of every cell
would report the same thing — a test that measures nothing. Holding the gate at
a known tier is what lets the OUTPUT bookkeeping be the only moving part.
Whether each step's own gate is wired, falsifiable and on-target is dimensions
1, 2 and 4's question, asked by their own modules.

One consequence is stated rather than hidden: substituting the gate empties
``_gate_json_targets(step)``, so the post-gate ``--json`` re-probe (see below)
does not fire during the sweep. That cannot manufacture a false pass — the
re-probe only ever ADDS evidence for a file that exists, and in the negative
half the file was deleted — but the carve-out is real, so
``test_d8_gate_written_json_output_is_reprobed_after_the_gate`` exercises it
with a REAL gate program that really writes its ``--json`` target.

====================================================================
THE VERDICT MUST NOT BE STOLEN FROM A MORE SPECIFIC TIER
====================================================================
The first attempt at the #455 fix returned MISSING the moment any entry was
absent, which pre-empted three verdicts that carry strictly more information:

  * a disclosed capability-gap skip (#675) — an honest deferral read as silence,
  * a genuine FAIL — a defect the gate really detected, erased,
  * a WAIVED deferral — an approved, ticketed gap, erased.

The landed shape downgrades **only PASS-tier** verdicts
(``PASS`` and ``VACUOUS_PASS``). The interaction tests at the bottom pin all
four directions with real constructions, including the one the brief singles
out: a step whose gate legitimately FAILs *and* is missing an output must still
report FAIL, never MISSING.

====================================================================
`` OR `` IS ANY-OF *INSIDE* ONE ENTRY
====================================================================
``required_outputs`` is ALL-of across entries; ``" OR "`` inside a single entry
is any-of — one artefact with several accepted names or locations. Both
directions are asserted: removing ONE alternative of such an entry must NOT
produce MISSING, removing ALL of them must.

====================================================================
NO STORED VERDICT IS ASSERTED
====================================================================
``cells_for(8)`` is used only to ENUMERATE the 63 cells. ``cell.audit_verdict``
is never read. Every predicate here is recomputed from the current flow yaml and
the current ``flow_compliance_check.py`` by executing them.

====================================================================
CELL STATES (63 = 61 + 0 + 2)
====================================================================
  ENFORCED  61 — every step that declares ``required_outputs``.
  WAIVED     0 — ``matrix_63x8.waivers.WAIVERS`` is empty for this dimension.
  NA         2 — ``FS1`` and ``P0`` declare no ``required_outputs`` at all, so
                 there is no declared artefact that can go missing. The NA test
                 asserts that PRECONDITION live: the day either step gains a
                 ``required_outputs`` key the NA self-invalidates and goes red,
                 forcing re-evaluation. It never calls ``pytest.skip()``.

``test_d8_cell_census_is_complete`` proves the three states partition the 63
exactly, so a cell cannot go silently unprobed.

====================================================================
FALSIFIABILITY — every assertion here was mutation-proved
====================================================================
A predicate that cannot fail is worthless however carefully it is worded, so
each one below was reddened before landing. The mutations were applied inside a
HARDLINK MIRROR of the plugin (``cp -al`` then unlink-and-rewrite the mutated
file), never in the shared worktree, and every one was reverted. 10/10 turned
this module red at the intended assertion:

  1. flow yaml — ``FS1`` gains a ``required_outputs`` key
     -> ``test_d8_cell_census_is_complete`` (the NA-population tripwire)
  2. catcher   — the ALL-of-N downgrade neutralised (``if False and ...``)
     -> 190 of the 284 tests, spanning 8 of the 11 test functions
  3. catcher   — the downgrade made unconditional, so MISSING pre-empts every
     tier -> the genuine-FAIL and disclosed-skip interaction tests
  4. catcher   — ``" OR "`` inside one entry evaluated as ALL-of
     -> every ``test_d8_any_of_entry_both_directions`` param (22)
  5. catcher   — ``VACUOUS_PASS`` dropped from the downgraded tiers
     -> ``test_d8_vacuous_pass_is_downgraded_too``
  6. flow yaml — ``DT1``'s condition loses ``any_of: true``, so the fixture can
     no longer separate its condition file from its own declared output
     -> the ``_assert_entry_unsatisfied`` leak guard
  7. catcher   — the post-gate ``--json`` re-probe deleted
     -> ``test_d8_gate_written_json_output_is_reprobed_after_the_gate``
  8. catcher   — the explicit-waiver branch loses its ``return result``
     -> ``test_d8_missing_does_not_preempt_an_explicit_waiver``
  9. catcher   — ``_STUB_TAG_RE`` widened to match the fixture body
     -> ``test_d8_fixture_body_is_inert``
 10. substrate — a placeholder waiver (``reason="TODO"``, no evidence) smuggled
     into ``matrix_63x8.waivers.WAIVERS``
     -> ``test_d8_every_waiver_is_evidence_backed``

Note what #2 and #4 say together: the two halves of the ALL-of-N / any-of
contract are guarded independently, so breaking either one is visible.

====================================================================
KNOWN GAP — stated, not papered over
====================================================================
Three things this module provably does NOT decide:

1. **Undeclared artefacts.** The catcher can only ever catch the absence of an
   artefact the yaml DECLARES. A step that really produces something it never
   lists in ``required_outputs`` can lose it with zero consequence here. That
   is dimension 7's question (``outputs_list_complete``) and no amount of work
   in this file substitutes for it.

2. **Whether each step's REAL gate ever reaches a PASS tier.** The sweep holds
   the gate at a known tier on purpose (see above). If some step's declared
   gate can never resolve PASS or VACUOUS_PASS on a real converged tree, the
   MISSING downgrade is unreachable for that step in practice and this module
   would not say so. Deciding it needs a converged project per step, i.e. the
   real EDA chain, which CI does not have. Dimensions 1, 2 and 4 ask the
   reachability question directly.

   This gap is no longer disclosed HERE and erased THERE. Since 2026-08-09 the
   module answers :func:`matrix_cell_substitution` for every cell, so the split
   travels with the census figure instead of living in this paragraph: the
   generated table in ``matrix_63x8/README.md`` reports the substituted cells in
   their own column and the total never folds them into "enforcing". Measured
   the day the contract landed: 16 of the 61 ENFORCED cells run against the
   step's own gate, 45 against the stand-in.

3. **The ``__WAIVER_HINT__`` (rc=3 / ``PASS_WITH_WAIVERS``) tier.** Producing it
   for real needs a gate program that passed its threshold with a DRC/LVS slot
   credited via a waiver — i.e. a converged tapeout project; no program in
   ``programs/`` emits rc=3 on a synthesizable fixture (measured: every
   candidate returns 0, 1 or 2). The "WAIVED is not pre-empted" property is
   therefore pinned through the two waiver paths that ARE reachable — the
   explicit ``waivers.json`` entry and the ENV_UNAVAILABLE fallback — and the
   rc=3 tier is left explicitly unmeasured rather than assumed equivalent.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/test_matrix_d8_missing_caught.py -q
"""
from __future__ import annotations

import json
import shutil
import tempfile
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from matrix_63x8 import cells as C
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W

# The CATCHER under test. Imported as a module (never `from ... import
# check_step`) so that a monkeypatched or reloaded attribute would be visible,
# and so the live capability-gap tables below are read from the module rather
# than copied into this file.
import flow_compliance_check as FCC

DIM = 8

# ──────────────────────────────────────────────────────────────────────
# Fixture vocabulary
# ──────────────────────────────────────────────────────────────────────
#: Where the substituted gate's control file lives. A directory of its own,
#: outside every declared output tree, for two reasons: nothing the fixture
#: writes here can accidentally satisfy a `required_outputs` glob, and
#: `_sibling_self_skip_for_missing` — which scans the *.json siblings of a
#: gate's missing file — finds no JSON here and therefore cannot promote a
#: FAIL-tier control gate into a disclosed skip behind the test's back.
_GATE_DIR = "_d8_gate"
_GATE_OK = f"{_GATE_DIR}/gate_ok.flag"
_GATE_ABSENT = f"{_GATE_DIR}/absent.flag"

#: A real gate the real `_evaluate_gate` resolves to PASS (file present).
PASS_GATE: Dict[str, Any] = {"files_exist": [_GATE_OK]}
#: A real gate the real `_evaluate_gate` resolves to FAIL (file absent).
FAIL_GATE: Dict[str, Any] = {"files_exist": [_GATE_ABSENT]}

#: Body written into every synthesized artefact. Deliberately NOT JSON and
#: deliberately non-empty:
#:   * `_evidence_integrity_scan` FAILs a PASS whose evidence is 0 bytes, and
#:     WAIVEs one tagged `deterministic_stub` / `low_confidence`;
#:   * it also demotes a PASS to SKIPPED-CONDITION when an evidence file is a
#:     JSON object with `"verdict": "SKIPPED-CONDITION"`.
#: Plain prose trips none of those, so the positive half measures the output
#: bookkeeping and not the integrity scan. `test_d8_fixture_body_is_inert`
#: proves this rather than assuming it.
_FIXTURE_BODY = "d8 fixture artefact\n"
_COND_BODY = "d8 condition fixture\n"


# ──────────────────────────────────────────────────────────────────────
# KIND-CORRECT FIXTURE BODIES
#
# This module's question is presence vs absence, so for most artefacts any
# non-empty bytes will do and `_FIXTURE_BODY` is what gets written. But some
# gates OPEN the artefact their step declares rather than only stat()ing it,
# and for those a plain-text placeholder is not "a seeded run tree" — it is a
# corrupt one, and the real gate FAILs on the seeded case for a reason that has
# nothing to do with the missing-output downgrade this module measures.
#
# Measured the day it bit: after step 14's and step 32's gates were changed to
# read `phase2/stage2/synth/netlist.v` and
# `phase3/stage3/eco/eco_trigger_decision.json` (dimension 4 — "the gate must
# read what the step declares"), both dropped out of
# `REAL_GATE_PASS_TIER_STEPS` because the seeded netlist declared no `module`
# and the seeded decision record was not JSON.
#
# The body is chosen by SUFFIX, so it generalises to the next content-aware
# gate instead of naming today's two paths. Presence/absence semantics are
# untouched: every body is non-empty and lands at exactly the same path.
# ──────────────────────────────────────────────────────────────────────
_JSON_BODY = '{"d8_fixture": true}\n'
_JSONL_BODY = '{"d8_fixture": true}\n'
_VERILOG_BODY = (
    "// d8 fixture artefact\n"
    "module d8_fixture_top (input wire clk, output wire q);\n"
    "  assign q = clk;\n"
    "endmodule\n"
)

_KIND_BODIES: Tuple[Tuple[str, str], ...] = (
    (".jsonl", _JSONL_BODY),
    (".json", _JSON_BODY),
    (".sv", _VERILOG_BODY),
    (".v", _VERILOG_BODY),
)


def fixture_body(rel: str) -> str:
    """The body to seed ``rel`` with: kind-correct where a gate parses it."""
    lowered = rel.lower()
    for suffix, body in _KIND_BODIES:
        if lowered.endswith(suffix):
            return body
    return _FIXTURE_BODY

_GLOB_CHARS = "*?["


# ──────────────────────────────────────────────────────────────────────
# Glob -> concrete path
# ──────────────────────────────────────────────────────────────────────
def concretize(pattern: str) -> str:
    """Turn one output pattern into a concrete relative path that MATCHES it.

    Component-wise so a recursive ``**`` becomes a real directory instead of a
    literal, and so a wildcard never eats a path separator:

        ``phase1/generated_docs/L13_*.json``     -> ``phase1/generated_docs/L13_d8.json``
        ``phase2/stage1/sim_professional/**/results.xml``
                                                 -> ``.../sim_professional/d8deep/results.xml``
        ``phase3/analog/*/*.gds``                -> ``phase3/analog/d8/d8.gds``

    The result is never trusted: :func:`_materialize` asserts, through the real
    ``_glob_first``, that the file it just wrote is actually found by the
    pattern it was derived from. A materializer that silently produced a
    non-matching path would turn the POSITIVE half into a false failure and,
    worse, the NEGATIVE half into a false pass.
    """
    parts: List[str] = []
    for comp in pattern.split("/"):
        if comp == "**":
            parts.append("d8deep")
            continue
        out: List[str] = []
        i = 0
        while i < len(comp):
            ch = comp[i]
            if ch == "*":
                out.append("d8")
            elif ch == "?":
                out.append("d")
            elif ch == "[":
                close = comp.find("]", i)
                if close == -1:
                    out.append("[")
                else:
                    inner = comp[i + 1:close]
                    out.append(inner[0] if inner and inner[0] != "!" else "d")
                    i = close
            else:
                out.append(ch)
            i += 1
        parts.append("".join(out))
    return "/".join(parts)


def alternatives(entry: str) -> Tuple[str, ...]:
    """The any-of alternatives of one entry, split exactly as the consumer does."""
    return F.split_any_of(entry)


def _overlaps(a: str, b: str) -> bool:
    """True when two patterns can be satisfied by the same path."""
    return a == b or fnmatchcase(a, b) or fnmatchcase(b, a)


# ──────────────────────────────────────────────────────────────────────
# Project synthesis
# ──────────────────────────────────────────────────────────────────────
def _write(project: Path, rel: str, body: str) -> None:
    """Create ``project/rel`` as a non-empty file.

    An ancestor that already exists as a regular FILE is replaced by a
    directory. That collision is real, not hypothetical: ``FS1``'s condition
    names ``phase2/stage1/rtl`` — a DIRECTORY — and ``_glob_first`` is happy
    with either, so the condition fixture writes a file there; a step declaring
    an output *inside* that directory would then die on ``FileExistsError``
    instead of producing a verdict. A fixture that crashes reports nothing.
    """
    p = project / rel
    parent = p.parent
    ancestors = [parent] + list(parent.parents)
    for anc in reversed(ancestors):
        if anc.is_file():
            anc.unlink()
    parent.mkdir(parents=True, exist_ok=True)
    if p.is_dir():
        raise AssertionError(
            f"fixture conflict: {rel!r} must be a file but a directory already "
            f"occupies that path"
        )
    p.write_text(body, encoding="utf-8")


def _condition_patterns(step: Dict[str, Any]) -> List[str]:
    """Which of the step's ``condition.files_exist`` patterns the fixture creates.

    A step whose ``condition`` is unsatisfied returns SKIPPED-CONDITION from
    ``check_step`` *before* ``required_outputs`` is ever read, so the fixture
    must satisfy the condition or it would be measuring the condition branch
    and calling it a dimension-8 result.

    One live collision exists: ``DT1``'s condition lists (``any_of: true``) the
    very artefact that is also its single ``required_outputs`` entry
    (``reports/phase2/dft/transition_coverage.json``). Creating it as a
    condition file would make the negative half untestable — the "removed"
    output would still be on disk. Because that condition is any-of, the
    fixture picks a non-colliding alternative instead
    (``phase2/stage2/dft/cut_netlist.v``).

    For an ALL-of condition every pattern must be created; if such a condition
    ever collides with one of its own step's outputs the fixture cannot
    separate them, and :func:`_assert_entry_unsatisfied` says so loudly instead
    of quietly passing. There is no such case today.
    """
    cond = step.get("condition") or {}
    pats = [str(p) for p in (cond.get("files_exist") or [])]
    if not pats:
        return []
    out_alts = [a for e in (step.get("required_outputs") or [])
                for a in alternatives(e)]
    non_colliding = [p for p in pats
                     if not any(_overlaps(p, a) for a in out_alts)]
    if cond.get("any_of") is True:
        return non_colliding or pats
    return pats


def _materialize(project: Path, step: Dict[str, Any],
                 drop_entries: Sequence[str] = (),
                 drop_alts: Sequence[Tuple[str, str]] = (),
                 gate_ok: bool = True) -> Dict[str, List[str]]:
    """Synthesize a run tree for *step*; return ``{entry: [created rel paths]}``.

    ``drop_entries``  entries whose artefacts are NOT created (all alternatives).
    ``drop_alts``     individual ``(entry, alternative)`` pairs not created.
    ``gate_ok``       create the PASS gate's control file.
    """
    (project / _GATE_DIR).mkdir(parents=True, exist_ok=True)
    if gate_ok:
        _write(project, _GATE_OK, "d8 gate control\n")

    for pat in _condition_patterns(step):
        _write(project, concretize(pat), _COND_BODY)

    created: Dict[str, List[str]] = {}
    for entry in (step.get("required_outputs") or []):
        made: List[str] = []
        if entry not in drop_entries:
            for alt in alternatives(entry):
                if (entry, alt) in drop_alts:
                    continue
                rel = concretize(alt)
                _write(project, rel, fixture_body(rel))
                assert FCC._glob_first(project, alt), (
                    f"fixture defect: wrote {rel!r} for pattern {alt!r} but the "
                    f"real _glob_first does not find it — the synthesized tree "
                    f"does not satisfy the entry it claims to satisfy"
                )
                made.append(rel)
        created[entry] = made

    # The condition must STILL hold after the outputs were written — writing an
    # output can replace a condition file with a directory (see `_write`). If
    # it does not, `check_step` returns SKIPPED-CONDITION before it ever reads
    # `required_outputs` and the case would grade the wrong branch.
    unmet = [pat for pat in _condition_patterns(step)
             if not FCC._glob_first(project, pat)]
    assert not unmet, (
        f"step {step.get('id')!r}: fixture defect — condition pattern(s) "
        f"{unmet!r} are not satisfied after the tree was built, so check_step "
        f"would short-circuit to SKIPPED-CONDITION and this case would measure "
        f"the condition branch instead of the output catcher"
    )
    return created


def _stepdict(sid, gate: Dict[str, Any] | None = None,
              required_outputs: Sequence[str] | None = None) -> Dict[str, Any]:
    """A copy of the REAL yaml step with only ``gate`` (and optionally
    ``required_outputs``) substituted. id / name / stage / condition /
    condition_kind are the real ones, so every early-return branch of
    ``check_step`` that keys off them behaves exactly as it does in production.
    """
    step = dict(F.step_by_id(sid))
    step["gate"] = PASS_GATE if gate is None else gate
    if required_outputs is not None:
        step["required_outputs"] = list(required_outputs)
    return step


def _expected_missing_status(sid) -> str:
    """The verdict an absent declared output produces for *sid*, read LIVE.

    Normally ``MISSING``. ``_apply_capability_gap`` converts a MISSING on a
    step registered in ``_PLATFORM_CAPABILITY_GAPS`` into SKIPPED-CONDITION
    naming the flag. That table is EMPTY today (every gap closed), so this
    returns MISSING for all 63 steps — but it is read from the module rather
    than assumed, so re-opening a gap re-points this expectation instead of
    reddening the sweep for the wrong reason.
    """
    raw = F.step_by_id(sid)["id"]
    return ("SKIPPED-CONDITION"
            if isinstance(raw, int) and raw in FCC._PLATFORM_CAPABILITY_GAPS
            else "MISSING")


def _assert_entry_unsatisfied(project: Path, entry: str, sid) -> None:
    """No file in the tree satisfies *entry*. Guards against a fixture leak."""
    leaks = {alt: FCC._glob_first(project, alt) for alt in alternatives(entry)}
    hit = {a: h for a, h in leaks.items() if h}
    assert not hit, (
        f"step {sid}: fixture leak — entry {entry!r} was supposed to be absent "
        f"but the tree still satisfies it via {hit!r}. Some other artefact the "
        f"fixture created (a condition file, or another entry's glob) matches "
        f"it, so this cell's negative half would measure nothing."
    )


def _assert_other_entries_satisfied(project: Path, step: Dict[str, Any],
                                    dropped: str, sid) -> None:
    """Every entry except *dropped* is genuinely on disk."""
    unmet = [e for e in (step.get("required_outputs") or [])
             if e != dropped
             and not any(FCC._glob_first(project, a) for a in alternatives(e))]
    assert not unmet, (
        f"step {sid}: fixture defect — entries {unmet!r} were meant to be "
        f"present alongside the dropped {dropped!r} but nothing on disk "
        f"satisfies them, so a MISSING verdict would not be attributable to "
        f"the dropped entry alone."
    )


def _reasons(result) -> str:
    return " | ".join(str(r) for r in result.reasons)[:600]


# ──────────────────────────────────────────────────────────────────────
# The two halves, as reusable probes
# ──────────────────────────────────────────────────────────────────────
def probe_positive(root: Path, sid) -> None:
    """All declared outputs present + a PASS-tier gate => NOT MISSING."""
    step = _stepdict(sid)
    project = root / "positive"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step)
    result = FCC.check_step(project, step, {})
    assert result.status != "MISSING", (
        f"step {sid}: every one of the {len(step.get('required_outputs') or [])} "
        f"declared required_outputs was synthesized as a non-empty file and the "
        f"gate resolved PASS, yet check_step reported {result.status!r} "
        f"— reasons: {_reasons(result)}"
    )
    assert result.status in ("PASS", "VACUOUS_PASS"), (
        f"step {sid}: expected a PASS-tier verdict from a satisfied fixture, "
        f"measured {result.status!r} — reasons: {_reasons(result)}. The negative "
        f"half below only means something if the positive half is PASS-tier, "
        f"because the MISSING downgrade applies to PASS-tier verdicts only."
    )


def probe_negative(root: Path, sid, entry: str, tag: str) -> None:
    """All declared outputs present EXCEPT *entry* => MISSING (live-expected)."""
    step = _stepdict(sid)
    project = root / f"negative_{tag}"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=(entry,))
    _assert_entry_unsatisfied(project, entry, sid)
    _assert_other_entries_satisfied(project, step, entry, sid)

    result = FCC.check_step(project, step, {})
    expected = _expected_missing_status(sid)
    n = len(step.get("required_outputs") or [])
    assert result.status == expected, (
        f"step {sid}: declared output {entry!r} has NO artefact on disk "
        f"({n - 1} of {n} entries satisfied, gate resolved PASS) but check_step "
        f"reported {result.status!r}, expected {expected!r} — reasons: "
        f"{_reasons(result)}. An absent declared output that a passing gate "
        f"papers over is exactly the all-but-one false PASS (#455)."
    )
    assert any(entry in str(r) for r in result.reasons), (
        f"step {sid}: verdict is {result.status!r} but no reason names the "
        f"absent entry {entry!r} — reasons: {_reasons(result)}. A deduction "
        f"that does not say WHICH artefact is missing is not actionable."
    )


# ──────────────────────────────────────────────────────────────────────
# Parametrization
# ──────────────────────────────────────────────────────────────────────
def _marks(step_id):
    m = W.xfail_mark(step_id, DIM)
    return [m] if m is not None else []


def _cell_params():
    return [pytest.param(c, marks=_marks(c.step_id),
                         id=f"step{F.normalize_id(c.step_id)}")
            for c in C.cells_for(DIM)]


def _entry_params():
    """One param per (step, required_outputs entry) — 126 today."""
    out = []
    for c in C.cells_for(DIM):
        sid = c.step_id
        for i, entry in enumerate(F.required_outputs(sid)):
            out.append(pytest.param(
                sid, i, entry, marks=_marks(sid),
                id=f"step{F.normalize_id(sid)}-out{i}"))
    return out


def _any_of_params():
    """One param per ANY_OF (`" OR "`-bearing) entry — 22 today."""
    out = []
    for c in C.cells_for(DIM):
        sid = c.step_id
        for i, entry in enumerate(F.required_outputs(sid)):
            if F.classify_output(entry) == F.ANY_OF:
                out.append(pytest.param(
                    sid, i, entry, marks=_marks(sid),
                    id=f"step{F.normalize_id(sid)}-anyof{i}"))
    return out


#: The step the interaction tests drive: the first one, in flow declaration
#: order, that declares >= 3 plain-FILE outputs and no `condition`. Resolved
#: LIVE so a flow edit re-points it instead of leaving a dangling literal. >= 3
#: so "one output removed" still leaves two present — the partial-evidence path
#: that reaches the gate, which is the path every interaction below is about.
def _pick_interaction_step():
    for c in C.cells_for(DIM):
        sid = c.step_id
        outs = F.required_outputs(sid)
        if (len(outs) >= 3 and F.step_condition(sid) is None
                and all(F.classify_output(e) == F.FILE for e in outs)):
            return sid
    raise RuntimeError(
        "no flow step declares >= 3 plain-FILE required_outputs without a "
        "condition; the interaction tests need one and must be re-based")


INTERACTION_STEP = _pick_interaction_step()

#: The steps that declare NO ``required_outputs`` at all, AS MEASURED on
#: 2026-07-27 — i.e. the dimension-8 NA population. A TRIPWIRE, not the
#: definition: every predicate in this file recomputes the live set. Its only
#: job is to force a human to look when the population changes.
#:
#: Without it the NA cells rot in the one way the three-state rule forbids.
#: ``test_d8_missing_caught`` branches on ``declares_required_outputs``, so a
#: step that GAINS a ``required_outputs`` key silently slides from NA to
#: ENFORCED and stays green — which is the right runtime behaviour but reports
#: a 61/0/2 split that is no longer true, with nobody told. Pinning the set
#: makes that transition red exactly once, in the place where the split is
#: written down.
NA_STEPS_AS_MEASURED: Tuple[str, ...] = ("FS1", "P0")

#: `flow_compliance_check._PLATFORM_CAPABILITY_GAPS` as measured 2026-07-27.
#:
#: 2026-07-27, adversarial finding (MEDIUM): `_expected_missing_status` reads
#: this table LIVE to decide whether an absent declared output should produce
#: MISSING or a disclosed SKIPPED-CONDITION. That was deliberate — a re-opened
#: gap re-points the expectation instead of reddening the sweep for the wrong
#: reason — but it means THE MECHANISM THAT CAN HIDE A MISSING IS THE SAME
#: MECHANISM THE TEST CONSULTS TO DECIDE WHAT TO EXPECT. Adding
#: ``21: "cap:d8_mutation_probe"`` to the table made step 21 — the step whose
#: historical false PASS motivated this dimension — stop producing a MISSING
#: deduction for an absent declared output, and all 284 tests here stayed
#: GREEN.
#:
#: The table is now PINNED as well as read. Re-opening a capability gap is a
#: legitimate engineering decision, and it still re-points the expectation so
#: the sweep does not fail for the wrong reason — but it reddens THIS test
#: once, in the place where the ENFORCED/WAIVED/NA split is written down, so
#: the decision is conscious rather than silent.
PLATFORM_CAPABILITY_GAPS_AS_MEASURED: Dict[Any, str] = {}

#: Steps declaring FEWER THAN TWO ``required_outputs`` entries, measured
#: 2026-07-27 (27 of 63), re-measured 2026-08-13 (28 of 63). They cannot
#: express "one artefact present, the rest absent", so the pooled-evidence
#: check has no shape to build; the population is pinned so a step that gains a
#: second entry cannot slip past it silently.
#:
#: ``1`` ADDED 2026-08-13. Step 1 (Spec-to-RTL) declared three entries, two of
#: which were ``reports/phase1/extraction_coverage_report.{md,json}`` — a
#: Phase 1 extraction artefact that d4 reported its gate never measured. The
#: declaration moved to D1 (Phase 1 Doc Extraction), which is where the
#: published corpus says it is produced: of the 107 run roots carrying that
#: report, 75 carry NO RTL at all and 105 carry D1's own L1_DATASHEET.json.
#: Step 1 is therefore left declaring only its RTL glob, which is one entry —
#: this pin moving is the intended consequence, recorded here rather than
#: discovered later from a sweep that changed shape.
SINGLE_ENTRY_STEPS_AS_MEASURED: Tuple[str, ...] = (
    "1", "8", "FS1", "DT1", "DT2", "DT3", "12", "A1", "A2", "A3", "A4", "A5",
    "A7", "A9", "14", "16", "17", "20", "22", "27", "29", "35", "36", "37",
    "M4", "42", "44", "P0",
)


# ══════════════════════════════════════════════════════════════════════
# THE 63 CELLS
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cell", _cell_params())
def test_d8_missing_caught(cell, tmp_path):
    """One cell of dimension 8: BOTH halves, over EVERY declared entry.

    ENFORCED for the 61 steps that declare ``required_outputs``; NA — with a
    live, self-invalidating precondition — for the 2 that do not.

    This is the cell-complete verdict. ``test_d8_negative_half_one_declared_
    output_removed`` re-runs the negative half one (step, entry) pair per test
    id, which costs milliseconds and buys per-pair failure isolation; this test
    is what makes the CELL either green or red as a whole.
    """
    sid = cell.step_id

    if not F.declares_required_outputs(sid):
        # NA, asserted rather than skipped: this step declares nothing, so
        # there is no declared artefact whose absence a catcher could catch.
        # The day it gains a `required_outputs` key this goes red and the cell
        # must be re-classified as ENFORCED.
        assert not F.required_outputs(sid), (
            f"step {sid}: flowref reports required_outputs "
            f"{list(F.required_outputs(sid))!r} while declares_required_outputs "
            f"is False — the substrate disagrees with itself"
        )
        raw = F.step_by_id(sid)
        assert "required_outputs" not in raw, (
            f"step {sid}: the dimension-8 NA precondition no longer holds — the "
            f"step now DECLARES required_outputs {raw.get('required_outputs')!r}. "
            f"There is now an artefact that can go missing, so this cell must "
            f"be enforced, not marked N/A."
        )
        return

    entries = F.required_outputs(sid)
    assert entries, (
        f"step {sid}: declares_required_outputs is True but the list is empty "
        f"— an empty declaration cannot be caught and must not read as enforced"
    )
    probe_positive(tmp_path, sid)
    for i, entry in enumerate(entries):
        probe_negative(tmp_path, sid, entry, tag=str(i))


@pytest.mark.parametrize("sid,index,entry", _entry_params())
def test_d8_negative_half_one_declared_output_removed(sid, index, entry,
                                                      tmp_path):
    """NEGATIVE: remove exactly ONE declared entry — the verdict must flip.

    Parametrized over every (step, entry) pair. With one param per step, an
    all-but-one regression in a 5-output step would be invisible on four of the
    five entries.
    """
    probe_negative(tmp_path, sid, entry, tag=str(index))


# ══════════════════════════════════════════════════════════════════════
# `" OR "` — any-of INSIDE one entry, both directions
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid,index,entry", _any_of_params())
def test_d8_any_of_entry_both_directions(sid, index, entry, tmp_path):
    """One alternative removed => NOT missing. ALL removed => MISSING.

    ``" OR "`` inside one entry spells a single artefact with several accepted
    names or locations (a cocotb ``results.xml`` OR a sim ``*.log`` OR a
    ``pass.flag``). Treating it as ALL-of would make every such step
    permanently MISSING; treating the ENTRY list as any-of is the #455 bug.
    Both mistakes are excluded here.
    """
    alts = alternatives(entry)
    assert len(alts) >= 2, (
        f"step {sid}: entry {entry!r} classified ANY_OF but splits into "
        f"{len(alts)} alternative(s) — {alts!r}"
    )
    step = _stepdict(sid)
    expected_missing = _expected_missing_status(sid)

    # Direction A — drop ONE alternative at a time; the entry stays satisfied.
    for j, alt in enumerate(alts):
        project = tmp_path / f"anyof_{index}_drop{j}"
        project.mkdir(parents=True, exist_ok=True)
        _materialize(project, step, drop_alts=((entry, alt),))
        survivors = [a for a in alts if FCC._glob_first(project, a)]
        assert survivors, (
            f"step {sid}: fixture defect — dropping alternative {alt!r} of "
            f"{entry!r} left NO alternative satisfied, so direction A cannot "
            f"be measured"
        )
        result = FCC.check_step(project, step, {})
        assert result.status != expected_missing, (
            f"step {sid}: alternative {alt!r} of the any-of entry {entry!r} was "
            f"removed while {survivors!r} still satisfy it, yet check_step "
            f"reported {result.status!r} — reasons: {_reasons(result)}. "
            f"' OR ' inside one entry is ANY-of; requiring every alternative "
            f"would make the step unsatisfiable by construction."
        )

    # Direction B — drop EVERY alternative; the entry is genuinely absent.
    project = tmp_path / f"anyof_{index}_dropall"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=(entry,))
    _assert_entry_unsatisfied(project, entry, sid)
    result = FCC.check_step(project, step, {})
    assert result.status == expected_missing, (
        f"step {sid}: NONE of the {len(alts)} alternatives of {entry!r} "
        f"({', '.join(alts)}) exists, yet check_step reported "
        f"{result.status!r}, expected {expected_missing!r} — reasons: "
        f"{_reasons(result)}. An any-of entry with zero alternatives satisfied "
        f"is an absent required output."
    )


# ══════════════════════════════════════════════════════════════════════
# ALL-of-N: the regression PR #455 closed
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cell", _cell_params())
def test_d8_only_one_declared_output_present_is_still_missing(cell, tmp_path):
    """The pre-#455 shape: evidence pooled across entries, so ONE artefact
    carried the rest. For every multi-entry step, keep only the FIRST entry and
    drop the others — the verdict must still be MISSING.
    """
    sid = cell.step_id
    outs = F.required_outputs(sid)
    if len(outs) < 2:
        # 2026-07-27, adversarial finding (LOW): this branch used to assert
        # `len(F.required_outputs(sid)) == len(outs)` — the same lru_cached call
        # on both sides, i.e. `x == x`. It could not fail under any repo state,
        # and 27 of the 63 params took it and reported PASS having asserted
        # nothing. The precondition is now PINNED against a measured population,
        # the way NA_STEPS_AS_MEASURED is: a step that gains a second entry
        # leaves the pin, reddens HERE, and is then covered by the real
        # assertion below.
        key = F.normalize_id(sid)
        assert key in SINGLE_ENTRY_STEPS_AS_MEASURED, (
            f"step {key} declares {len(outs)} required_output(s) — fewer than "
            f"the 2 this shape needs — but it is not in the measured "
            f"single-entry population {SINGLE_ENTRY_STEPS_AS_MEASURED!r}. "
            f"Either the flow changed and the pin is stale, or this cell is "
            f"silently opting out of the pooled-evidence check. Re-measure and "
            f"update the pin in the same change."
        )
        return
    step = _stepdict(sid)
    project = tmp_path / "onlyfirst"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=tuple(outs[1:]))
    result = FCC.check_step(project, step, {})
    expected = _expected_missing_status(sid)
    assert result.status == expected, (
        f"step {sid}: only 1 of {len(outs)} declared outputs exists "
        f"({outs[0]!r} present; {list(outs[1:])!r} absent) and the gate resolved "
        f"PASS, yet check_step reported {result.status!r}, expected "
        f"{expected!r} — reasons: {_reasons(result)}. This is the exact shape "
        f"that let step 21 PASS on routed.def with drc.rpt absent."
    )


# ══════════════════════════════════════════════════════════════════════
# THE MISSING DOWNGRADE MUST NOT STEAL A MORE SPECIFIC VERDICT
# ══════════════════════════════════════════════════════════════════════
def _interaction_tree(tmp_path: Path, name: str, gate: Dict[str, Any],
                      drop_last: bool) -> Tuple[Path, Dict[str, Any], str]:
    sid = INTERACTION_STEP
    outs = list(F.required_outputs(sid))
    dropped = outs[-1]
    step = _stepdict(sid, gate=gate)
    project = tmp_path / name
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step,
                 drop_entries=(dropped,) if drop_last else (),
                 gate_ok=(gate is PASS_GATE))
    return project, step, dropped


def test_d8_missing_does_not_preempt_a_genuine_gate_fail(tmp_path):
    """A step whose gate legitimately FAILs *and* is missing an output must
    still report FAIL.

    This is the interaction the first attempt at the #455 fix got wrong: it
    returned MISSING as soon as any entry was absent, which erased a defect the
    gate had actually detected. FAIL is counter-evidence; MISSING is the
    absence of evidence. Replacing the former with the latter destroys
    information.
    """
    project, step, dropped = _interaction_tree(
        tmp_path, "fail", FAIL_GATE, drop_last=True)
    result = FCC.check_step(project, step, {})
    assert result.status == "FAIL", (
        f"step {INTERACTION_STEP}: gate {FAIL_GATE!r} really FAILs (its file "
        f"does not exist) AND declared output {dropped!r} is absent; check_step "
        f"reported {result.status!r} — reasons: {_reasons(result)}. A real "
        f"gate defect must survive the required_outputs downgrade."
    )
    # Control: the same gate with every output present is also FAIL, so the
    # verdict above is the gate's, not an artefact of the missing entry.
    project2, step2, _ = _interaction_tree(
        tmp_path, "fail_control", FAIL_GATE, drop_last=False)
    control = FCC.check_step(project2, step2, {})
    assert control.status == "FAIL", (
        f"step {INTERACTION_STEP}: control with ALL outputs present and the same "
        f"failing gate reported {control.status!r}, not FAIL — the FAIL above "
        f"cannot be attributed to the gate"
    )


def test_d8_missing_does_not_preempt_a_disclosed_skip(tmp_path):
    """A gate that resolves to a DISCLOSED capability-gap skip keeps
    SKIPPED-CONDITION even when a declared output is absent.

    Built for real: the gate demands a file that does not exist, and a co-located
    sibling honestly self-reports ``verdict: SKIPPED-CONDITION``. The real
    ``_sibling_self_skip_for_missing`` (#675) turns that into a
    ``__SKIP_HINT__`` and ``check_step`` promotes the step. An honest deferral
    downgraded to MISSING would read as silence — the disease this campaign is
    about, applied to the disclosure mechanism itself.
    """
    sid = INTERACTION_STEP
    outs = list(F.required_outputs(sid))
    dropped = outs[-1]
    skip_dir = "_d8_skip"
    step = _stepdict(sid, gate={"files_exist": [f"{skip_dir}/results.json"]})
    project = tmp_path / "skip"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=(dropped,), gate_ok=False)
    _write(project, f"{skip_dir}/engine_not_run.json", json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "reason": "d8 fixture: no proof engine wired on this host",
    }))
    result = FCC.check_step(project, step, {})
    assert result.status == "SKIPPED-CONDITION", (
        f"step {sid}: the gate's artefact is absent but a sibling honestly "
        f"self-reports a skip, and declared output {dropped!r} is also absent; "
        f"check_step reported {result.status!r} — reasons: {_reasons(result)}. "
        f"The required_outputs downgrade must apply to PASS-tier verdicts only."
    )
    assert getattr(result, "self_skip_disclosed", False), (
        f"step {sid}: verdict is SKIPPED-CONDITION but self_skip_disclosed is "
        f"{getattr(result, 'self_skip_disclosed', None)!r} — the disclosure flag "
        f"the report keys off was not set"
    )


def test_d8_missing_does_not_preempt_an_explicit_waiver(tmp_path):
    """An approved waivers.json entry wins over an absent declared output.

    A waiver is a dated, attributed deferral. Reporting MISSING instead would
    both lose the approver and double-count one gap as two deductions.
    """
    sid = INTERACTION_STEP
    raw_id = F.step_by_id(sid)["id"]
    project, step, dropped = _interaction_tree(
        tmp_path, "waived", FAIL_GATE, drop_last=True)
    waivers = {raw_id: {"reason": "d8 fixture: approved deferral",
                        "approver": "d8-matrix"}}
    result = FCC.check_step(project, step, waivers)
    assert result.status == "WAIVED", (
        f"step {sid}: an explicit waiver is on file for id {raw_id!r} and "
        f"declared output {dropped!r} is absent; check_step reported "
        f"{result.status!r} — reasons: {_reasons(result)}"
    )
    assert any("d8-matrix" in str(r) for r in result.reasons), (
        f"step {sid}: WAIVED but no reason names the approver — reasons: "
        f"{_reasons(result)}"
    )


def test_d8_env_unavailable_waiver_converts_the_missing_it_produced(tmp_path):
    """The ENV_UNAVAILABLE tier is a FALLBACK: it applies only because the
    natural verdict was MISSING.

    This pins the ordering from the other side. The downgrade must fire first
    (otherwise the fallback has nothing to convert) and the conversion must
    then preserve the natural verdict as a breadcrumb, so the report says
    "artefact absent because the tool is not on this host" rather than either
    a bare MISSING or a bare WAIVED.
    """
    sid = INTERACTION_STEP
    raw_id = F.step_by_id(sid)["id"]
    project, step, dropped = _interaction_tree(
        tmp_path, "envwaived", PASS_GATE, drop_last=True)
    waivers = {raw_id: {"reason": "d8 fixture: tool absent on host",
                        "approver": "d8-matrix", "_env_unavailable": True}}
    result = FCC.check_step(project, step, waivers)
    assert result.status == "WAIVED", (
        f"step {sid}: ENV_UNAVAILABLE waiver + absent output {dropped!r} "
        f"reported {result.status!r} — reasons: {_reasons(result)}"
    )
    assert any("natural" in str(r) for r in result.reasons), (
        f"step {sid}: the ENV_UNAVAILABLE conversion dropped the natural "
        f"verdict breadcrumb — reasons: {_reasons(result)}. A waiver that hides "
        f"what it converted cannot be audited."
    )
    # Without the waiver the very same tree must be MISSING — otherwise the
    # WAIVED above proves nothing about the fallback ordering.
    bare = FCC.check_step(project, step, {})
    assert bare.status == _expected_missing_status(sid), (
        f"step {sid}: the identical tree WITHOUT the waiver reported "
        f"{bare.status!r}, so the ENV_UNAVAILABLE conversion above was not "
        f"converting a MISSING — reasons: {_reasons(bare)}"
    )


def test_d8_vacuous_pass_is_downgraded_too(tmp_path):
    """VACUOUS_PASS is PASS-tier, so an absent output downgrades it.

    Real construction, no stub: ``mixed_signal_merge_check`` exits 2 on a tree
    with no mixed-signal artefacts, which ``_check_program_exit_zero`` maps to
    the ``__VACUOUS_HINT__`` tier. A gate that vacuously passed certainly has
    not certified an absent artefact into existence.
    """
    sid = INTERACTION_STEP
    outs = list(F.required_outputs(sid))
    dropped = outs[-1]
    gate = {"program_exit_zero":
            f"mixed_signal_merge_check . --json {_GATE_DIR}/ms.json"}

    control_dir = tmp_path / "vac_control"
    control_dir.mkdir(parents=True, exist_ok=True)
    step = _stepdict(sid, gate=gate)
    _materialize(control_dir, step, gate_ok=False)
    control = FCC.check_step(control_dir, step, {})
    assert control.status == "VACUOUS_PASS", (
        f"step {sid}: the fixture gate was supposed to resolve VACUOUS_PASS "
        f"with all outputs present, measured {control.status!r} — reasons: "
        f"{_reasons(control)}. Without that tier this test measures nothing."
    )

    project = tmp_path / "vac_missing"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=(dropped,), gate_ok=False)
    result = FCC.check_step(project, step, {})
    assert result.status == _expected_missing_status(sid), (
        f"step {sid}: gate resolved VACUOUS_PASS and declared output "
        f"{dropped!r} is absent, but check_step reported {result.status!r} — "
        f"reasons: {_reasons(result)}. VACUOUS_PASS is a PASS tier; the "
        f"downgrade must reach it."
    )


def test_d8_gate_written_json_output_is_reprobed_after_the_gate(tmp_path):
    """The one narrow carve-out: an output THIS step's own gate writes via
    ``--json`` is re-probed AFTER the gate, and only that one.

    Without the re-probe such an entry reports MISSING on a project's first
    evaluation and PASS on the second, purely because the first created it —
    a verdict that changes with how many times it has been run is not a
    measurement. The scope must stay verbatim-narrow: a SECOND absent output
    that no gate command names still yields MISSING.

    Real gate, real write: ``mixed_signal_merge_check`` emits its ``--json``
    report and exits 2. 11 real (step, entry) pairs in the current flow are
    their own gate's ``--json`` target, so this branch is live, not theoretical.
    """
    sid = INTERACTION_STEP
    outs = list(F.required_outputs(sid))
    written = f"{_GATE_DIR}/gate_written.json"
    unwritten = f"{_GATE_DIR}/never_written.json"
    gate = {"program_exit_zero":
            f"mixed_signal_merge_check . --json {written}"}

    step = _stepdict(sid, gate=gate, required_outputs=outs + [written])
    assert written in FCC._gate_json_targets(step), (
        f"fixture defect: {written!r} is not recognised as a --json target of "
        f"{gate!r} by the real _gate_json_targets"
    )
    project = tmp_path / "reprobe"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=(written,), gate_ok=False)
    assert not (project / written).exists(), "fixture defect: target pre-exists"
    result = FCC.check_step(project, step, {})
    assert result.status == "VACUOUS_PASS", (
        f"step {sid}: {written!r} was absent before the gate ran and the gate "
        f"itself writes it, so the post-gate re-probe should have satisfied the "
        f"entry; check_step reported {result.status!r} — reasons: "
        f"{_reasons(result)}"
    )
    assert (project / written).is_file(), (
        f"fixture defect: the gate did not actually write {written!r}, so the "
        f"re-probe was never exercised"
    )

    # Narrow scope: a second absent output that NO gate command names is still
    # caught, so the carve-out cannot be widened into a blanket excuse.
    step2 = _stepdict(sid, gate=gate,
                      required_outputs=outs + [written, unwritten])
    assert unwritten not in FCC._gate_json_targets(step2)
    project2 = tmp_path / "reprobe_narrow"
    project2.mkdir(parents=True, exist_ok=True)
    _materialize(project2, step2, drop_entries=(written, unwritten),
                 gate_ok=False)
    result2 = FCC.check_step(project2, step2, {})
    assert result2.status == _expected_missing_status(sid), (
        f"step {sid}: {unwritten!r} is absent and is NOT a --json target of any "
        f"gate command, yet check_step reported {result2.status!r} — reasons: "
        f"{_reasons(result2)}. The post-gate re-probe must not excuse an "
        f"artefact the gate never claimed to write."
    )
    assert any(unwritten in str(r) for r in result2.reasons), (
        f"step {sid}: MISSING but the reason does not name {unwritten!r} — "
        f"reasons: {_reasons(result2)}"
    )


def test_d8_missing_output_outranks_the_stub_backed_waiver(tmp_path):
    """MEASURED ORDER, recorded so a future reorder is deliberate.

    ``_evidence_integrity_scan`` downgrades a PASS whose evidence is tagged
    ``deterministic_stub`` to WAIVED (#434). It runs only on a PASS, and the
    required_outputs downgrade has already fired by then — so when BOTH apply,
    the verdict is MISSING, not WAIVED. Pinned in both directions: with every
    output present the same stub evidence really does yield WAIVED, so the
    MISSING above is the downgrade winning and not the stub scan failing to
    fire.
    """
    sid = INTERACTION_STEP
    outs = list(F.required_outputs(sid))
    dropped = outs[-1]
    step = _stepdict(sid)

    control = tmp_path / "stub_control"
    control.mkdir(parents=True, exist_ok=True)
    _materialize(control, step)
    _write(control, concretize(outs[0]), json.dumps({
        "verdict": "PASS", "deterministic_stub": True}))
    r_control = FCC.check_step(control, step, {})
    assert r_control.status == "WAIVED", (
        f"step {sid}: stub-tagged evidence with ALL outputs present reported "
        f"{r_control.status!r}, expected WAIVED (#434) — reasons: "
        f"{_reasons(r_control)}. Without that the comparison below is empty."
    )

    project = tmp_path / "stub_missing"
    project.mkdir(parents=True, exist_ok=True)
    _materialize(project, step, drop_entries=(dropped,))
    _write(project, concretize(outs[0]), json.dumps({
        "verdict": "PASS", "deterministic_stub": True}))
    result = FCC.check_step(project, step, {})
    assert result.status == _expected_missing_status(sid), (
        f"step {sid}: evidence is stub-tagged AND declared output {dropped!r} "
        f"is absent; check_step reported {result.status!r} — reasons: "
        f"{_reasons(result)}. The absent artefact is the harder fact and is "
        f"what the verdict must report."
    )


# ══════════════════════════════════════════════════════════════════════
# FIXTURE SELF-CHECKS — the tests above are only worth their assertions
# if the fixture is inert and the census is complete.
# ══════════════════════════════════════════════════════════════════════
def test_d8_fixture_body_is_inert(tmp_path):
    """The synthesized artefact body must trip none of the evidence-integrity
    downgrades, or the positive half would be measuring the wrong mechanism.

    EVERY body `fixture_body` can return is checked, not just the default: a
    kind-correct body that tripped the stub-tag or self-report scan would flip
    the positive half of every case that seeds that kind, silently.
    """
    bodies = {"_FIXTURE_BODY": _FIXTURE_BODY}
    bodies.update({suffix: body for suffix, body in _KIND_BODIES})
    for label, body in bodies.items():
        assert body.strip(), f"{label} body is empty — 0-byte evidence FAILs"
        assert not FCC._STUB_TAG_RE.search(body), (
            f"{label} body {body!r} matches the stub tag regex — every "
            f"positive half seeding that kind would come back WAIVED "
            f"instead of PASS"
        )
        assert '"verdict"' not in body, (
            f"{label} body carries a verdict field — _evidence_integrity_scan "
            f"would read it as a self-report"
        )
    project = tmp_path / "inert"
    project.mkdir(parents=True, exist_ok=True)
    for i, (label, body) in enumerate(bodies.items()):
        rel = f"probe/artefact{i}{label if label.startswith('.') else '.txt'}"
        _write(project, rel, body)
        result = FCC.StepResult(id=1, name="probe", stage="stage1",
                                status="PASS")
        result.evidence.append(rel)
        scanned = FCC._evidence_integrity_scan(project, result)
        assert scanned.status == "PASS", (
            f"the {label} fixture body was downgraded to {scanned.status!r} by "
            f"the real evidence-integrity scan — reasons: {_reasons(scanned)}"
        )


def test_d8_cell_census_is_complete():
    """The 63 cells partition into ENFORCED / WAIVED / NA with nothing left over.

    Silent absence is the failure mode this campaign exists to remove, so the
    partition is computed live and asserted, not written down.
    """
    cells = C.cells_for(DIM)
    assert len(cells) == len(F.step_ids()), (
        f"dimension {DIM} has {len(cells)} cells but the flow declares "
        f"{len(F.step_ids())} steps"
    )
    waived = [c for c in cells if W.is_waived(c.step_id, DIM)]
    na = [c for c in cells
          if not W.is_waived(c.step_id, DIM)
          and not F.declares_required_outputs(c.step_id)]
    enforced = [c for c in cells
                if not W.is_waived(c.step_id, DIM)
                and F.declares_required_outputs(c.step_id)]
    assert len(enforced) + len(waived) + len(na) == len(cells), (
        f"census does not partition: {len(enforced)} enforced + {len(waived)} "
        f"waived + {len(na)} na != {len(cells)} cells"
    )
    # Every enforced cell must actually have been parametrized into the
    # negative sweep, or it is enforced in name only.
    probed = {F.normalize_id(p.values[0]) for p in _entry_params()}
    unprobed = [F.normalize_id(c.step_id) for c in enforced
                if F.normalize_id(c.step_id) not in probed]
    assert not unprobed, (
        f"steps {unprobed!r} are classified ENFORCED but contribute no "
        f"(step, output) pair to the negative sweep"
    )
    live_na = tuple(F.normalize_id(c.step_id) for c in na)
    assert live_na == NA_STEPS_AS_MEASURED, (
        f"the dimension-8 NA population changed: measured {live_na!r}, pinned "
        f"{NA_STEPS_AS_MEASURED!r}. A step that gained required_outputs is now "
        f"ENFORCED (good) but the reported ENFORCED/WAIVED/NA split "
        f"({len(enforced)}/{len(waived)}/{len(na)}) is stale — update "
        f"NA_STEPS_AS_MEASURED and the module docstring's census in the same "
        f"change, so the three-state accounting stays true."
    )


#: Steps whose REAL (un-substituted) gate reaches a PASS tier on the seeded
#: fixture, measured 2026-07-27, re-measured 2026-07-28. See
#: ``test_d8_downgrade_is_reachable_through_each_steps_own_real_gate``.
#:
#: RE-MEASURED, and it GREW, which is the safe direction. `fixture_body` now
#: seeds a `.json` artefact with parseable JSON and a `.v`/`.sv` artefact with
#: a real `module`, because dimension-4 work made several gates OPEN the
#: artefact their step declares instead of only stat()ing it. Two steps that
#: could not reach a PASS tier on a plain-text placeholder now can:
#:
#:   D1  its Phase-1 gates parse the seeded `generated_docs/L*.json`
#:   28  `perc_signoff_check` parses the seeded `perc_equivalent.json`
#:
#: Nothing was lost (steps 14 and 32 stayed in after the same fixture change;
#: they had dropped out on the text placeholder alone). The population is
#: pinned rather than derived so the SHRINKING direction still has to be
#: explained by a human — see this constant's test.
REAL_GATE_PASS_TIER_STEPS: Tuple[str, ...] = (
    "D1", "1", "2", "4", "12", "A1", "A2", "A4", "A5", "A6", "A8", "14",
    "28", "30", "32", "35", "38",
)
# 2026-07-28: the SET is unchanged (lost: none, gained: none). This tuple is
# compared in flow DECLARATION order, and the dimension-5 fix moved A6's yaml
# block from after step 39 to between A5 and A7 to remove the flow's only
# forward edge (A7 declares `blocks_on: [A6]`). Only A6's position in this
# tuple moved with it.

_PASS_TIER_LABELS = frozenset({"PASS", "VACUOUS_PASS", "VACUOUS-PASS"})


@lru_cache(maxsize=1)
def _real_gate_sweep() -> Dict[str, Tuple[str, str]]:
    """``{step: (seeded status, status after dropping one declared output)}``
    using each step's OWN gate, for every step whose real gate reaches a PASS
    tier on the seeded fixture."""
    out: Dict[str, Tuple[str, str]] = {}
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        if not F.declares_required_outputs(sid) or not F.has_gate(sid):
            continue
        step = dict(F.step_by_id(sid))  # the REAL gate, not PASS_GATE
        tmp = Path(tempfile.mkdtemp(prefix="d8_realgate_"))
        try:
            full = tmp / "full"
            full.mkdir(parents=True)
            try:
                _materialize(full, step)
            except AssertionError:
                continue
            seeded = FCC.check_step(full, step, {}).status
            if seeded not in _PASS_TIER_LABELS:
                continue
            outs = list(F.required_outputs(sid))
            dropped = tmp / "dropped"
            dropped.mkdir(parents=True)
            _materialize(dropped, step, drop_entries=(outs[0],))
            out[key] = (seeded, FCC.check_step(dropped, step, {}).status)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def test_d8_downgrade_is_reachable_through_each_steps_own_real_gate():
    """The 61-cell sweep substitutes a gate. This one does not.

    2026-07-27, adversarial finding (MEDIUM), accepted: the cell sweep replaces
    every step's gate with ``{"files_exist": ["_d8_gate/gate_ok.flag"]}`` so the
    gate verdict is held at a known tier and the MISSING downgrade is reachable
    at all. That is what makes those cells falsifiable, and it is disclosed as
    KNOWN GAP #2 — but it means a change making every program-backed gate
    resolve to a disclosed skip (so the PASS-tier-only downgrade becomes
    unreachable in production for ~60 of the 62 gated steps) left 282 of 284
    tests green. Only two tests here drive a REAL gate program.

    This test drives each step's OWN gate, unmodified, and asks the production
    question for every step where it is answerable at all: on a fully seeded
    tree, does the real gate reach a PASS tier, and does removing one declared
    output then move the step off that tier? 16 steps qualify today (14 when
    this was written; `fixture_body` now seeds kind-correct JSON / Verilog, and
    D1 and 28 joined). It does NOT close the gap — 45 steps' real gates FAIL on
    a synthesized tree and need a converged project no CI has — but it converts
    "2 steps measured with a real gate" into a named, pinned population that
    cannot shrink silently.
    """
    sweep = _real_gate_sweep()
    measured = tuple(sorted(sweep, key=lambda k: list(
        map(F.normalize_id, F.step_ids())).index(k)))
    assert measured == REAL_GATE_PASS_TIER_STEPS, (
        f"the set of steps whose REAL gate reaches a PASS tier on the seeded "
        f"fixture changed: measured {list(measured)!r}, pinned "
        f"{list(REAL_GATE_PASS_TIER_STEPS)!r}. A SHRINKING set is the shape "
        f"that matters: it means production gates stopped being able to reach "
        f"the tier at which the MISSING downgrade fires, so those cells' "
        f"enforcement became substituted-gate-only without anyone saying so. "
        f"Lost: {sorted(set(REAL_GATE_PASS_TIER_STEPS) - set(measured))}; "
        f"gained: {sorted(set(measured) - set(REAL_GATE_PASS_TIER_STEPS))}."
    )
    survivors = {k: v for k, v in sweep.items() if v[1] in _PASS_TIER_LABELS}
    assert not survivors, (
        f"with one declared output removed, these steps' OWN gates still "
        f"resolved to a PASS tier: {survivors!r}. FAIL and MISSING are both "
        f"acceptable — FAIL means the gate itself noticed, which is stronger — "
        f"but a PASS tier means the artefact vanished with no consequence."
    )


def test_d8_platform_capability_gap_table_is_pinned():
    """A re-opened capability gap must redden this suite once, by name.

    ``_expected_missing_status`` reads ``_PLATFORM_CAPABILITY_GAPS`` live to
    decide what an absent declared output should produce. Reading it live is
    right — otherwise a legitimate re-opening would fail the sweep for the
    wrong reason — but reading it live ALONE means the exact mechanism that can
    convert a MISSING deduction into a disclosed skip is also the mechanism
    that decides what this dimension expects to see. Adding one step to that
    table silently removed that step from dimension-8 enforcement with all 284
    tests still green.

    Pinning it does not forbid the mechanism; it forbids using it without
    telling this census. When the table legitimately changes, update
    ``PLATFORM_CAPABILITY_GAPS_AS_MEASURED`` and say in the same change which
    cells stop being enforced.
    """
    live = dict(getattr(FCC, "_PLATFORM_CAPABILITY_GAPS", {}))
    assert live == PLATFORM_CAPABILITY_GAPS_AS_MEASURED, (
        f"flow_compliance_check._PLATFORM_CAPABILITY_GAPS changed: measured "
        f"{live!r}, pinned {PLATFORM_CAPABILITY_GAPS_AS_MEASURED!r}.\n"
        f"Every step id in that table has its MISSING deduction converted to a "
        f"disclosed SKIPPED-CONDITION by _apply_capability_gap, so its "
        f"dimension-8 cell no longer enforces 'a declared output that vanishes "
        f"is caught'. Steps newly exempted: "
        f"{sorted(set(map(str, live)) - set(map(str, PLATFORM_CAPABILITY_GAPS_AS_MEASURED)))}. "
        f"Update the pin and record the coverage change, or remove the gap."
    )
    # And the reader must actually be keyed off it, or the pin guards nothing.
    assert "_PLATFORM_CAPABILITY_GAPS" in _expected_missing_status.__doc__, (
        "_expected_missing_status no longer documents its dependency on the "
        "capability-gap table; this pin may be guarding a table nobody reads"
    )


def test_d8_every_waiver_is_evidence_backed():
    """A dimension-8 waiver must say what a program cannot decide, with
    independently checkable evidence. Empty registry passes vacuously today and
    the assertion is what keeps that honest if one is ever added."""
    for w in W.waivers_for_dim(DIM):
        problems = W.validate(w)
        assert not problems, f"waiver {w.label} is not admissible: {problems}"


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
    if F.declares_required_outputs(step_id):
        return None
    return ("declares no required_outputs, so there is no declared artefact "
            "whose absence a catcher could catch")


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if W.waiver_for(step_id, DIM) is not None:
        return "WAIVED"
    return "ENFORCED"


def matrix_cell_substitution(step_id) -> Optional[str]:
    """Was this cell's ENFORCED verdict measured against the step's OWN gate?

    ``None`` for the steps whose real gate reaches a PASS tier on the seeded
    fixture — those are decided by ``check_step`` driving the gate the flow
    yaml actually declares. A disclosure for the rest, whose verdict comes from
    the substituted stand-in described in KNOWN GAP #2.

    The split is RE-DERIVED from :func:`_real_gate_sweep`, the same live
    measurement ``test_d8_downgrade_is_reachable_through_each_steps_own_real_gate``
    grades against ``REAL_GATE_PASS_TIER_STEPS``. Reading the pinned tuple
    directly would make this a fact about a tuple; reading the sweep makes it a
    fact about the tree, and weakening the sweep still has to get past that
    test's shrink guard.

    Why it is reported at all: the substitution was always disclosed HERE, in
    prose, and always erased THERE, in the one census figure a reader quotes.
    45 of 61 is not a footnote to 61 — it is most of it.
    """
    if matrix_cell_state(step_id) != "ENFORCED":
        return None
    if F.normalize_id(step_id) in _real_gate_sweep():
        return None
    return (
        "the 61-cell sweep replaces this step's declared gate with the minimal "
        "stand-in {\"files_exist\": [\"_d8_gate/gate_ok.flag\"]} so the gate "
        "verdict is held at a known PASS tier and the MISSING downgrade is "
        "reachable at all; this step's OWN gate FAILs on a synthesized fixture "
        "(it needs a converged project no CI has), so what this cell proves is "
        "that the CATCHER downgrades a PASS-tier verdict when a declared "
        "output vanishes — not that this step's gate ever reaches that tier in "
        "production. See KNOWN GAP #2 and "
        "test_d8_downgrade_is_reachable_through_each_steps_own_real_gate."
    )
