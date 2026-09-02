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
  WAIVED     0 — ``flow_matrix.waivers.WAIVERS`` is empty for this dimension.
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
     into ``flow_matrix.waivers.WAIVERS``
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
   generated table in ``flow_matrix/README.md`` reports the substituted cells in
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
import re
import shutil
import tempfile
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from flow_matrix import cells as C
from flow_matrix import flowref as F
from flow_matrix import waivers as W

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
# `phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json` (dimension 4 — "the gate must
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

# ──────────────────────────────────────────────────────────────────────
# PATH-CORRECT FIXTURE BODIES
#
# The suffix table below stopped being enough the moment two artefacts of the
# SAME kind needed different content. Measured 2026-08-19: step 4's own gate
# runs `verilator_coverage_measure`, which classifies the JSON at
# `reports/phase2/coverage/coverage_actual.json` and reports
#
#     the file at the declared coverage path is a 'another producer' payload
#     written by another producer, so line/toggle/branch was never measured here
#
# for `_JSON_BODY`. Step 4 therefore FAILed on the fully seeded tree and dropped
# out of REAL_GATE_PASS_TIER_STEPS — the shrink
# `test_d8_downgrade_is_reachable_through_each_steps_own_real_gate` names. It has
# been red since the pin landed (d4136c3053), on its own commit and on every one
# since, so the pin never matched the tree it claims to measure.
#
# WHAT THESE NUMBERS ARE, AND ARE NOT. They are not a coverage result: nothing
# here was simulated, and no run this tree describes ever existed. They are the
# same kind of stand-in as `_VERILOG_BODY`'s `module d8_fixture_top` — a
# well-formed artefact of the right SHAPE, so a content-aware gate can reach a
# verdict and the MISSING-output downgrade this module measures stays reachable.
# A fixture that cannot satisfy a gate does not measure that gate; it only
# measures the fixture. The counters clear `coverage_closure`'s 80 % goal
# deliberately — at 0 % the step FAILs on the goal instead of on the missing
# output, which is the same "failing for an unrelated reason" the suffix table
# was introduced to end.
#
# NO NARRATIVE FIELDS. `verilator_coverage_measure.artefact_looks_tool_generated`
# rejects `note` / `notes` / `source` / `tool` carrying estimation language, and
# `classify_coverage_artefact` calls a bare percentage with no `totals` a
# FORGERY. Only the `totals` container is written, so the payload cannot be read
# as a coverage CLAIM — it is counters, or it is nothing.
_COVERAGE_BODY = (
    '{"totals": {'
    '"line": {"covered": 100, "total": 100, "pct": 100.0}, '
    '"toggle": {"covered": 100, "total": 100, "pct": 100.0}, '
    '"branch": {"covered": 100, "total": 100, "pct": 100.0}}}\n'
)

#: Keyed by the tail of the declared path, consulted BEFORE the suffix table.
#: The mechanism exists so the NEXT content-aware gate is a one-line addition
#: rather than a second special case grown beside this one.
#:
#: `coverage_verilator.json` is where the MEASUREMENT lives — the coverage
#: producer's own path, split out from `coverage_actual.json` once it was
#: measured that the latter has a second producer (design_one_shot_runner's
#: functional verdict) which always won the path. Step 4's gate reads the
#: measurement path, so that is the one whose body must be coverage-shaped.
_PATH_BODIES: Tuple[Tuple[str, str], ...] = (
    ("reports/phase2/coverage/coverage_verilator.json", _COVERAGE_BODY),
    ("reports/phase2/coverage/coverage_actual.json", _COVERAGE_BODY),
)


_KIND_BODIES: Tuple[Tuple[str, str], ...] = (
    (".jsonl", _JSONL_BODY),
    (".json", _JSON_BODY),
    (".sv", _VERILOG_BODY),
    (".v", _VERILOG_BODY),
)


def fixture_body(rel: str) -> str:
    """The body to seed ``rel`` with: path-correct first, then kind-correct."""
    for tail, body in _PATH_BODIES:
        if rel == tail or rel.endswith("/" + tail):
            return body
    lowered = rel.lower()
    for suffix, body in _KIND_BODIES:
        if lowered.endswith(suffix):
            return body
    return _FIXTURE_BODY


# ──────────────────────────────────────────────────────────────────────
# THE WRONG BODY — present, parseable, and saying the run FAILED
#
# `fixture_body` above answers "what does a declared output look like when the
# step produced one". This answers "...when the step produced a BAD one". The
# distinction is the whole of the content arm: every body below lands at the
# SAME path, through the SAME writer, and satisfies the SAME glob as its right
# counterpart, so an UNMOVED verdict can never be explained by "nothing was
# there" — which is the failure this dimension's existing arm already covers
# and must not be allowed to impersonate.
#
# Each body is the same KIND as the right one — a `.json` that `json.loads`, a
# `.v` carrying a matched `module`/`endmodule`, text shaped like a tool report
# — and each says IN ITS CONTENT that the thing it reports on failed. An
# unparseable body would be refused on kind and would prove nothing about
# whether anything reads the content; an absent one is the other arm.
# ──────────────────────────────────────────────────────────────────────
_WRONG_JSON = json.dumps(
    {
        "d8_fixture": True,
        "status": "FAIL", "verdict": "FAIL", "result": "FAIL",
        "passed": False, "ok": False, "clean": False,
        "violations": 17, "errors": 17, "failures": 17,
        "violation_count": 17, "error_count": 17,
    },
    indent=2, sort_keys=True) + "\n"

_WRONG_JSONL = json.dumps(
    {"d8_fixture": True, "status": "FAIL", "passed": False, "violations": 17},
    sort_keys=True) + "\n"

_WRONG_VERILOG = (
    "// d8 fixture artefact - PRESENT, PARSEABLE, WRONG\n"
    "module d8_fixture_top (input wire clk, output wire q);\n"
    "  // `q` is declared an output and is never driven. The module parses and\n"
    "  // elaborates; what it describes is broken.\n"
    "endmodule\n"
)

_WRONG_TEXT = (
    "d8 fixture artefact\n"
    "ERROR: 17 violation(s) found\n"
    "violation report: 17\n"
    "violation count summary: 17 violation(s) found\n"
    "RESULT: FAIL\n"
)

#: Keyed by the SAME suffixes ``_KIND_BODIES`` declares, and iterated through
#: ``_KIND_BODIES`` below rather than through its own keys, so a kind added to
#: the right-body table cannot silently fall through to the text default here.
#: ``test_d8_every_seeded_kind_has_a_wrong_counterpart`` asserts the two agree.
_WRONG_BY_SUFFIX: Dict[str, str] = {
    ".jsonl": _WRONG_JSONL,
    ".json": _WRONG_JSON,
    ".sv": _WRONG_VERILOG,
    ".v": _WRONG_VERILOG,
}


def wrong_body(rel: str) -> str:
    """The body to seed ``rel`` with when it must be PRESENT but WRONG."""
    lowered = rel.lower()
    for suffix, _right in _KIND_BODIES:
        if lowered.endswith(suffix):
            return _WRONG_BY_SUFFIX[suffix]
    return _WRONG_TEXT

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
                 gate_ok: bool = True,
                 wrong_entries: Sequence[str] = ()) -> Dict[str, List[str]]:
    """Synthesize a run tree for *step*; return ``{entry: [created rel paths]}``.

    ``drop_entries``  entries whose artefacts are NOT created (all
                      alternatives), AND whose alternatives no other entry may
                      re-create — see the note below the condition loop.
    ``drop_alts``     individual ``(entry, alternative)`` pairs not created.
    ``gate_ok``       create the PASS gate's control file.
    ``wrong_entries`` entries created at the SAME paths with :func:`wrong_body`
                      instead of :func:`fixture_body` — present, parseable, and
                      saying the run failed. Routed through this one writer on
                      purpose: a separate materializer for the wrong tree could
                      drift from the right one, and then a verdict that did not
                      move would be a fact about two different trees rather
                      than about the bytes in one file.
    """
    (project / _GATE_DIR).mkdir(parents=True, exist_ok=True)
    if gate_ok:
        _write(project, _GATE_OK, "d8 gate control\n")

    for pat in _condition_patterns(step):
        _write(project, concretize(pat), _COND_BODY)

    # ── ENTRIES MAY SHARE AN ALTERNATIVE, AND A DROP HAS TO REACH ALL OF THEM
    # `" OR "` inside one entry is any-of and the entry list is all-of, so
    # `(A OR C) AND (B OR C)` is the flow's way of spelling `(A AND B) OR C` —
    # one shared escape hatch under a conjunction. Step 5 is the first shipped
    # step written that way (#1974 added `formal_authoring_request.json OR
    # formal_not_applicable.json` to BOTH of its formal entries), and a
    # per-entry materializer cannot separate them: dropping entry 0 still left
    # entry 0's own alternatives on disk, written on entry 1's behalf, and
    # `_assert_entry_unsatisfied` correctly refused to measure the cell —
    # 5 of this file's cases, MEASURED red at ab83f1a70.
    #
    # A `drop_entries` drop is therefore a fact about the TREE, not about one
    # entry's turn in this loop: no file this fixture writes may satisfy ANY
    # alternative of a dropped entry, whichever entry asked for it.
    #
    # THE TEST IS THE FILE IT WOULD WRITE, not the pattern it came from. The
    # candidate is `concretize(alt)`, and it is suppressed when that concrete
    # path matches a dropped alternative read as a glob — which is the same
    # question `_glob_first` will ask of the finished tree. Comparing the two
    # PATTERNS instead over-suppresses in the one shape the flow really uses:
    # step 22 declares `parasitic.spef OR *.spef`, whose two alternatives
    # overlap as patterns while `concretize` gives them different names, and a
    # pattern-level rule deleted a live any-of case (MEASURED: step22-anyof0
    # went red on that cut).
    #
    # `drop_alts` is deliberately NOT widened here. It is the any-of DIRECTION-A
    # probe — "one alternative of THIS entry is gone, the entry survives on
    # another" — so it is scoped to the (entry, alternative) pair it names and
    # the entry's own siblings must still be written.
    #
    # THE SEPARATION IS ASSERTED, NEVER ASSUMED. When suppression would leave a
    # SURVIVING entry with no alternative at all, the two entries cannot be told
    # apart on any tree and this fixture says so loudly instead of quietly
    # building a tree that measures something else.
    _dropped_alts = [alt for entry in drop_entries for alt in alternatives(entry)]

    def _dropped_here(entry: str, alt: str) -> bool:
        if (entry, alt) in drop_alts:
            return True
        rel = concretize(alt)
        return any(rel == d or fnmatchcase(rel, d) for d in _dropped_alts)

    created: Dict[str, List[str]] = {}
    for entry in (step.get("required_outputs") or []):
        made: List[str] = []
        if entry not in drop_entries:
            _alts = alternatives(entry)
            _keep = [a for a in _alts if not _dropped_here(entry, a)]
            assert _keep or not _alts, (
                f"step {step.get('id')!r}: entry {entry!r} shares EVERY one of "
                f"its alternatives {list(_alts)!r} with the dropped "
                f"{list(drop_entries)!r}, so no tree satisfies one and not the "
                f"other and this cell's negative half is not measurable as "
                f"declared. That is a finding about the DECLARATION, not a "
                f"reason to build a tree that measures something else."
            )
            for alt in _alts:
                if alt not in _keep:
                    continue
                rel = concretize(alt)
                _write(project, rel, (wrong_body(rel) if entry in wrong_entries
                                      else fixture_body(rel)))
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

#: Steps declaring FEWER THAN TWO ``required_outputs`` entries, RE-MEASURED
#: 2026-08-16 (26 of 63). They cannot express "one artefact present, the rest
#: absent", so the pooled-evidence check has no shape to build; the population
#: is pinned so a step that gains a second entry cannot slip past it silently.
#:
#: THREE CHANGES vs the 2026-07-27 measurement, and they are independent:
#:
#:   + "1"   this change moves `reports/phase1/extraction_coverage_report.{md,json}`
#:           off step 1, taking it from THREE entries to ONE. It therefore joins
#:           the population, and d8 says so itself: "step 1 declares 1
#:           required_output(s) — fewer than the 2 this shape needs — but it is
#:           not in the measured single-entry population ... Re-measure and
#:           update the pin in the same change."
#:
#:   - "29"  step 29 declares TWO entries (`.../sim_postlayout/results.log OR
#:           .../pass.flag` and `reports/phase2/gates/post_layout_sim.json`) and
#:           does so on clean `24ff9530` as well, so it was already stale before
#:           this change and is NOT this change's doing. It is dropped because
#:           the count in this comment is a claim: measured over the flow, the
#:           population is 26 on main and 27 here, and leaving "29" in would have
#:           made the stated figure wrong in the other direction after adding
#:           "1". The membership assertion is one-directional — it fires only
#:           when a single-entry step is ABSENT from this tuple — which is why a
#:           stale member sat here without reddening anything.
#:
#:   - "27"  step 27 now declares both its noise/glitch report and the MCF
#:           crosstalk-delay verdict. It therefore has two ALL-of entries and
#:           leaves this fewer-than-two population; retaining it would silently
#:           disable the partial-evidence shape this pin exists to measure.
#:   - "37.5self"  ARRIVED and then LEFT, both times RE-DERIVED. It joined this
#:           population at v1.11.4 declaring exactly one output, and on
#:           2026-08-20 the owner retired the STEP: the general precheck was
#:           never a third route, it is a second ARM of `37.5ic`. So the member
#:           is gone because the step is gone, and `37.5ic` does NOT come back
#:           into this population — it now declares five outputs, not one.
#:           RE-DERIVED A FOURTH TIME rather than deleted by hand:
#:           `[k for k in step_ids() if len(required_outputs(k)) < 2]` was
#:           recomputed on this tree and answers 26 members, and the tuple below
#:           is that answer. The recomputation also says, as a by-product, that
#:           no other member had gone stale in the meantime.
SINGLE_ENTRY_STEPS_AS_MEASURED: Tuple[str, ...] = (
    # 2026-08-31: 26 -> 24 members. Steps 14 and 37 LEFT. v1.13.78 gave the
    # on-pass review a verdict source with an executed producer, so each of
    # those steps now WRITES a per-stage compliance report and reads it on the
    # next clause; the artefact was not declared, d7 went red on it, and
    # declaring it took both steps from one required_output to two. They are
    # out of this population because they are no longer single-entry, not
    # because anything was removed from them: the change that moved them is
    # purely additive (+6 lines, 0 removed) and every other member is unmoved.
    #
    # RE-DERIVED, not hand-edited. This tuple is exactly what
    # `[k for k in step_ids() if len(required_outputs(k)) < 2]` answers on this
    # tree, in flow order — recomputed in full rather than by deleting the two
    # names, so the recomputation also certifies that no OTHER member went
    # stale in the meantime (it says: 0 joined). The file's own note above
    # says why that matters: a hand-edited tuple is how v1.10.38 shipped a
    # 28-entry pin over a 27-step population.
    # 2026-08-21: 26 -> 27 members. Step 1.6x JOINED — `7fcbc7397` added it with
    # exactly one required_output (`reports/crosslayer/rewrite_equivalence
    # _check.json`), which is what this population means. 37.5ic and 37.5self
    # are still out of it for the reasons below; nothing else moved.
    #
    # RE-DERIVED, not appended: this tuple is exactly what
    # `[k for k in step_ids() if len(required_outputs(k)) < 2]` answers on this
    # tree, in flow order. The file's own note says why that matters — a
    # hand-edited tuple is how v1.10.38 shipped a 28-entry pin over a 27-step
    # population.
    #
    # 2026-08-20: 26 members. Step 37.5ic LEFT this population when 69ce9260d
    # made the release documents an output of it (1 entry -> 3) and is further
    # out of it now (5 entries); step 37.5self JOINED at v1.11.4 with one output
    # and LEFT with the step itself when the general precheck became 37.5ic's
    # second ARM.
    "1",
    "8",
    "FS1",
    "DT1",
    "12",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A7",
    "A9",
    "16",
    "17",
    "20",
    "22",
    "DT2",
    "DT3",
    "35",
    "36",
    "M4",
    "42",
    "44",
    "P0",
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


def test_d8_gate_written_json_output_is_refused_as_run_evidence(tmp_path):
    """An output THIS step's own gate writes via ``--json`` is the AUDITOR's,
    not the RUN's — refused on every pass, and the refusal is idempotent.

    HISTORY, BECAUSE THE ANSWER HERE REVERSED AND THE REASON MATTERS. This test
    used to require the opposite: a post-gate RE-PROBE that CREDITED such an
    entry, on the argument that without it the entry "reports MISSING on a
    project's first evaluation and PASS on the second, purely because the first
    created it — a verdict that changes with how many times it has been run is
    not a measurement". The objection was right and it has been answered, twice
    over, in the mechanism rather than in this expectation:

      #1981 `f8ec1ed66`  tagged the recreated file `audit_created`, excluded it
                         from run evidence, and deleted it again to buy the
                         idempotence — which made a read-only auditor mutate
                         the tree it audits and destroyed the `--json` audit
                         trail the flow DECLARES as a required_output.
      #2005 `2fedbf6b7`  bought the same idempotence from the right budget:
                         `_is_gate_verdict_document` classifies by WHAT THE
                         DOCUMENT IS, so pass 1 and pass 2 reach the SAME
                         verdict with nothing deleted.

    So the count-of-passes objection is discharged, and what this test now
    measures is the property it was always about — the verdict does not depend
    on how many times the auditor has run — plus the refusal itself. Crediting
    an artefact that exists only because the audit wrote it is self-certified
    evidence; ``test_matrix_d7_outputs_list_complete`` grades the same
    invariant across all 22 shipped steps that declare one.

    The scope must stay verbatim-narrow, and the second half below is
    unchanged: a SECOND absent output that no gate command names is still
    reported MISSING, and by name.

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
    assert (project / written).is_file(), (
        f"fixture defect: the gate did not actually write {written!r}, so the "
        f"refusal below was never exercised — and the auditor must NOT have "
        f"deleted it either: the flow declares this path and #2005 removed the "
        f"delete that made the audit mutate the tree it reads"
    )
    assert result.status not in ("PASS", "VACUOUS_PASS"), (
        f"step {sid}: {written!r} exists only because this step's own gate "
        f"wrote it during the audit, yet check_step reported {result.status!r} "
        f"— a done claim resting on the auditor's own document. Reasons: "
        f"{_reasons(result)}"
    )
    assert any("audit" in str(r).lower() and written in str(r)
               for r in result.reasons), (
        f"step {sid}: the verdict is {result.status!r} but no reason names "
        f"{written!r} as audit-created — a refusal that does not say WHICH "
        f"artefact it refused is not actionable. Reasons: {_reasons(result)}"
    )
    assert written not in result.evidence, (
        f"step {sid}: {written!r} was refused in the reasons and still "
        f"credited as run evidence {list(result.evidence)!r}"
    )

    # IDEMPOTENCE, WHICH IS THE PROPERTY THE ORIGINAL EXPECTATION WAS DEFENDING.
    # Run the audit AGAIN on the tree the first audit left. The file is now
    # present BEFORE the gate, so a timing-only reading would credit on pass 2
    # what it refused on pass 1 — "MISSING once and PASS forever after".
    again = FCC.check_step(project, step, {})
    assert again.status == result.status, (
        f"step {sid}: pass 1 reported {result.status!r} and pass 2 "
        f"{again.status!r} on an unchanged tree — a verdict that depends on "
        f"how many times the auditor has run is not a measurement. Reasons: "
        f"{_reasons(again)}"
    )
    assert written not in again.evidence, (
        f"step {sid}: the artefact pass 1 refused became run evidence on "
        f"pass 2: {list(again.evidence)!r}"
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
#: RE-MEASURED 2026-08-14 on v1.10.40 (75776dbbb), and it GREW again — `4`
#: joined. Lost: none. The cause is a gate that became MORE honest, not a
#: fixture change:
#:
#:   `fe1f0615e` (#1115/#1173) taught `professional_tb_check` to print
#:   `VACUOUS_PASS` for a `NOT_APPLICABLE` verdict instead of returning a bare
#:   rc 0 that `flow_compliance_check` recorded as PASS — in that commit's own
#:   words, "the producer emitted nothing and the checker read the absence as
#:   consent".
#:
#: Step 4's SEEDED status moved with it, measured through this module's own
#: `_materialize` + `FCC.check_step` at both revisions:
#:
#:   3d13e2c59 (v1.10.39)   WAIVED         in_pass_tier=False
#:   75776dbbb (v1.10.40)   VACUOUS_PASS   in_pass_tier=True
#:
#: and the WAIVED came from the same clause: v1.10.39 reported "WAIVED-DEFERRED:
#: gate program signalled PASS_WITH_WAIVERS (#651)" plus two PARTIALLY-VACUOUS
#: lines, all of which v1.10.40 replaces with one "vacuous: gate program
#: signalled VACUOUS_PASS (input not applicable): professional_tb_check".
#:
#: NOTHING ABOUT STEP 4 ITSELF MOVED. Read through `flowref`'s accessor (not a
#: re-walk of the yaml — the population is 63, and a hand walk keyed by `id`
#: collects 71), step 4 is byte-identical across the two revisions: same gate
#: (md5 cb7dc043), same `required_outputs`. `flow_compliance_check.check_step`
#: is byte-identical too (195e2d64), as is `vacuous_testbench_check`. Only
#: `professional_tb_check.py` changed.
#:
#: So this is the GROWING direction, which this constant's test names as the
#: benign one: one more step's real gate now reaches the tier at which the
#: MISSING downgrade fires, so one more cell's enforcement is measurable rather
#: than substituted-gate-only.
REAL_GATE_PASS_TIER_STEPS: Tuple[str, ...] = (
    # 2026-08-21: GAINED "1.6x", lost nothing. `7fcbc7397` added the step and
    # its real gate reaches a PASS tier on the seeded fixture, so it joins the
    # population this pin exists to watch. The direction matters and is worth
    # restating: a SHRINKING set is the alarming shape (production gates losing
    # the tier at which the MISSING downgrade fires); a growing one is a new
    # step arriving, which is this.
    #
    # 2026-09-02, SHRINK, 17 -> 8. NINE steps left, and the alarm above did its
    # job: it named them. Every one is accounted for below, with the tier it
    # reaches now, the landing that moved it and that landing's own reason —
    # and none of the nine is a gate that "stopped reading". They are three
    # deliberate tightenings of the flow arriving at a SYNTHESIZED tree:
    #
    #   #1978 `bf6292fa3` — an rc=2 non-verdict that carries no explicit
    #       `reason_class`, and whose prose no recogniser matches, is an
    #       EXECUTION_ERROR, which is not skip-eligible. A gate that examined
    #       NOTHING is therefore no longer a PASS tier. On a fixture tree that
    #       carries the declared artefacts and no design content, that is the
    #       honest answer, and it is the answer this file must not launder.
    #   #1980 `867f807a7` — the same typing reaching the ADVISORY slot, so an
    #       advisory clause's rc=2 lands on DISCLOSED_INCOMPLETE.
    #   #1981/#2005 `f8ec1ed66`/`2fedbf6b7` — a declared output that is this
    #       step's own gate `--json` target AND holds that gate's verdict
    #       document is refused as run evidence on every pass, so the step
    #       reports MISSING until a producer outside the gate supplies it.
    #   #1973 `7d1da41d7` — `phase1_expert_parse_track` exits 1, not 2, when
    #       the expert handoff was emitted and never consumed, so D1's own gate
    #       now hard-FAILs on any tree with no consumed expert answer.
    #
    # THE NINE ARE NOT DROPPED, THEY ARE MOVED — to
    # :data:`REAL_GATE_LEFT_THE_PASS_TIER`, which pins the exact tier each one
    # reaches now and is asserted by the same test. Deleting a name from a
    # shrinking pin is how a shrink becomes invisible on the NEXT change; this
    # keeps all seventeen under assertion and only moves nine of them from
    # "reaches a PASS tier" to "reaches exactly this instead".
    #
    # 2026-09-03, GROWTH, 8 -> 9: "38" RETURNS, and it returns from
    # REAL_GATE_LEFT_THE_PASS_TIER rather than arriving from nowhere — the
    # move that map exists to force. Its entry there said the whole reason in
    # its own words: "audit-created refusal of reports/phase3/
    # foundry_handoff_audit.json (#2005); ITS GATE STILL PASSES". The gate was
    # never the problem; the refusal was, and it was the over-broad half of it.
    # `foundry_handoff_package_check` is listed BOTH under step 38's
    # `programs:` and as its own gate, so its stamp on the document is the same
    # whichever process ran it, and `_is_gate_verdict_document` answered "the
    # auditor's" for a document that pre-dated the audit. It now answers
    # "content cannot decide" for that one shape and the timing evidence
    # decides instead. Steps 2 and 28 STAY in the map below: each is held out
    # by an independent #1978 finding (rc=2 EXECUTION_ERROR typing; zero PERC
    # categories) that this change does not touch and must not launder.
    "1", "A1", "A2", "A5", "A6", "A8", "32", "35", "38",
)

#: The steps whose real gate USED to reach a PASS tier on the seeded fixture
#: and no longer does — name -> the tier it reaches now, MEASURED on
#: ab83f1a70 in the pinned runtime image.
#:
#: This is the other half of the shrink guard above, and it is asserted, not
#: annotated. Without it a shrink costs one deletion and is then unwatched:
#: the step could go from INCOMPLETE to a silent PASS, or from MISSING to
#: FAIL, and nothing here would notice. With it, the nine remain under
#: assertion in the position they actually occupy.
#:
#: A step LEAVING this map is good news and still reddens: it means the tier
#: moved, and if it moved back into a PASS tier it belongs in
#: REAL_GATE_PASS_TIER_STEPS above, in the same change that says why.
#:
#: MEASURED, per step, on the seeded tree through the step's OWN gate:
#:
#:   D1  FAIL        `phase1_expert_parse_track` rc 1 (HANDOFF_EMITTED, #1973)
#:   2   INCOMPLETE  rc=2 clauses typed EXECUTION_ERROR (#1978). RE-MEASURED
#:                   2026-09-03: MISSING -> INCOMPLETE, and NOT a move toward
#:                   a PASS tier. Two findings held this step out and only the
#:                   OUTER one moved: the audit-created refusal of
#:                   `reports/crosslayer/rewrite_equivalence_check.json`
#:                   (#2005) set the status to MISSING, which pre-empted the
#:                   #1978 verdict underneath it. With the refusal narrowed to
#:                   the shape content can actually decide, the #1978 finding
#:                   is what the reader now sees, and it is the true one: the
#:                   artefact was PRESENT the whole time, so "an output is
#:                   missing" was the wrong sentence about this tree.
#:   4   INCOMPLETE  `vacuous_testbench_check` / `professional_tb_check` /
#:                   `functional_state_transition_coverage_check` (#1978)
#:   12  INCOMPLETE  `dft_post_optimization_scan_survival_check`: Step 11's own
#:                   output is absent, so nothing was measured (#1978)
#:   14  INCOMPLETE  `stage_on_pass_review` + `yosys_tiecell_recipe_order_check`
#:                   through the advisory slot (#1980)
#:   A4  INCOMPLETE  `analog_corner_lib_realism_lint` rc 2 — its own docstring
#:                   says "no analog decks anywhere ... NOT a pass over the
#:                   design" (#1980)
#:   28  INCOMPLETE  `perc_signoff_check` zero categories (#1978). RE-MEASURED
#:                   2026-09-03, MISSING -> INCOMPLETE, same cause as step 2:
#:                   the outer audit-created refusal of `reports/phase2/gates/
#:                   perc_signoff.json` (#2005) is gone and the #1978 finding
#:                   it masked is what reports now. Still out of the PASS tier,
#:                   on its own merits.
#:   30  INCOMPLETE  `spice_correlation_check` `no_spef` — BLOCKED_BY_UPSTREAM,
#:                   which is not skip-eligible (#1978)
#:
#: 2026-09-03 — "38" LEFT THIS MAP and is back in REAL_GATE_PASS_TIER_STEPS
#: above; see the note there. Its line is kept here, commented, so the reason
#: it was ever in the map does not have to be re-derived if it returns:
#:   38  MISSING     audit-created refusal of `reports/phase3/
#:                   foundry_handoff_audit.json` (#2005); its gate still PASSes
REAL_GATE_LEFT_THE_PASS_TIER: Dict[str, str] = {
    "D1": "FAIL",
    "2": "INCOMPLETE",
    "4": "INCOMPLETE",
    "12": "INCOMPLETE",
    "14": "INCOMPLETE",
    "A4": "INCOMPLETE",
    "28": "INCOMPLETE",
    "30": "INCOMPLETE",
}
# 2026-07-28: the SET is unchanged (lost: none, gained: none). This tuple is
# compared in flow DECLARATION order, and the dimension-5 fix moved A6's yaml
# block from after step 39 to between A5 and A7 to remove the flow's only
# forward edge (A7 declares `blocks_on: [A6]`). Only A6's position in this
# tuple moved with it.

# vibe-ic#901, 2026-08-22 — PARTIALLY-VACUOUS joins the set, and NOT as a
# convenience: without it steps 4 and D1 drop straight out of the sweep and the
# pinned tuple SHRINKS, which the assertion below correctly calls the shape that
# matters ("production gates stopped being able to reach the tier at which the
# MISSING downgrade fires"). Nothing about those two steps changed — the tier
# they already reached was split in two by a count, and this reader was still
# spelling only one half of it. Adding the word keeps the measured set at the
# same 18 steps; it does not widen enforcement, it stops a rename from silently
# narrowing it.
_PASS_TIER_LABELS = frozenset({"PASS", "VACUOUS_PASS", "VACUOUS-PASS",
                               "PARTIALLY-VACUOUS", "PARTIALLY_VACUOUS"})


@lru_cache(maxsize=1)
def _real_gate_seeded_status() -> Dict[str, str]:
    """``{step: seeded status}`` through each step's OWN gate, for EVERY step
    that declares outputs and has a gate — not only the PASS-tier ones.

    Split out of :func:`_real_gate_sweep` so the shrink guard can assert what
    the steps that LEFT the PASS tier report now. A pin that only lists the
    survivors stops watching a step the moment it drops out, which is the one
    moment it most needs watching: the next move (INCOMPLETE -> a quiet PASS,
    MISSING -> FAIL) would then be invisible. One sweep serves both readings so
    the two cannot disagree and the fixture is built once per step.
    """
    out: Dict[str, str] = {}
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
            out[key] = FCC.check_step(full, step, {}).status
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return out


@lru_cache(maxsize=1)
def _real_gate_sweep() -> Dict[str, Tuple[str, str]]:
    """``{step: (seeded status, status after dropping one declared output)}``
    using each step's OWN gate, for every step whose real gate reaches a PASS
    tier on the seeded fixture."""
    out: Dict[str, Tuple[str, str]] = {}
    seeded_all = _real_gate_seeded_status()
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        seeded = seeded_all.get(key)
        if seeded is None or seeded not in _PASS_TIER_LABELS:
            continue
        step = dict(F.step_by_id(sid))  # the REAL gate, not PASS_GATE
        tmp = Path(tempfile.mkdtemp(prefix="d8_realgate_"))
        try:
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
    output then move the step off that tier? 8 steps qualify today (14 when
    this was written, 17 at its widest). It does NOT close the gap — most
    steps' real gates FAIL or report INCOMPLETE on a synthesized tree and need
    a converged project no CI has — but it converts "2 steps measured with a
    real gate" into a named, pinned population that cannot shrink silently.

    TWO PINS, ONE POPULATION. `REAL_GATE_PASS_TIER_STEPS` names the steps that
    reach the tier; `REAL_GATE_LEFT_THE_PASS_TIER` names the ones that left AND
    the tier each reaches instead. Both are asserted here. The second exists
    because 2026-09-02's shrink (17 -> 8) would otherwise have been discharged
    by deleting nine names, after which nothing in this repository watched
    those nine again.
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
        f"gained: {sorted(set(measured) - set(REAL_GATE_PASS_TIER_STEPS))}. "
        f"A step that left belongs in REAL_GATE_LEFT_THE_PASS_TIER with the "
        f"tier it reaches instead — it must not simply be deleted from here."
    )

    # THE OTHER HALF OF THE SHRINK GUARD. The nine steps that left the PASS
    # tier stay under assertion at the tier they actually reach, so a further
    # move is a named failure and not a silent one.
    seeded_all = _real_gate_seeded_status()
    left_now = {k: seeded_all.get(k) for k in REAL_GATE_LEFT_THE_PASS_TIER}
    moved = {k: (v, left_now[k]) for k, v in REAL_GATE_LEFT_THE_PASS_TIER.items()
             if left_now[k] != v}
    assert not moved, (
        f"a step recorded in REAL_GATE_LEFT_THE_PASS_TIER no longer reports "
        f"the tier it was pinned at: {moved!r} (pinned, measured). A move back "
        f"INTO a PASS tier is the repair this map exists to make visible — "
        f"return the step to REAL_GATE_PASS_TIER_STEPS in the change that "
        f"earns it. Any other move is a new fact about that step's own gate "
        f"and must be recorded with its cause."
    )
    assert not (set(REAL_GATE_LEFT_THE_PASS_TIER) & set(measured)), (
        f"a step is in BOTH pins: "
        f"{sorted(set(REAL_GATE_LEFT_THE_PASS_TIER) & set(measured))}. It "
        f"cannot both reach a PASS tier and have left it."
    )

    survivors = {k: v for k, v in sweep.items() if v[1] in _PASS_TIER_LABELS}
    assert not survivors, (
        f"with one declared output removed, these steps' OWN gates still "
        f"resolved to a PASS tier: {survivors!r}. FAIL and MISSING are both "
        f"acceptable — FAIL means the gate itself noticed, which is stronger — "
        f"but a PASS tier means the artefact vanished with no consequence."
    )


# ══════════════════════════════════════════════════════════════════════
# THE CONTENT ARM — a declared output that is PRESENT, PARSEABLE and WRONG
#
# WHY IT EXISTS
# -------------
# Everything above this line reddens on ABSENCE. `probe_negative` removes a
# declared output and requires the verdict to move; `_real_gate_sweep` does the
# same through each step's own gate. Not one of them asks what happens when the
# artefact IS there and says the wrong thing, and the consumer gives a reason to
# expect the answer is "nothing": `required_outputs` is resolved by
# `flow_compliance_check._glob_first`, which asks whether a path exists and asks
# nothing else. Dimension 2 measured the same shape from the other side and
# wrote it down — a `files_exist` clause is satisfied by a ZERO-BYTE file, and
# step 21's `routed.def` PASSes at 25 bytes of `VERSION 5.8 ; / END DESIGN`.
#
# An existence check wearing the clothes of a correctness check is the disease
# this campaign was opened to find. This arm is the instrument that says, per
# step and by measurement rather than by reading the source, WHICH it is here.
#
# WHAT IT MEASURES
# ----------------
# The same population `_real_gate_sweep` uses — the steps whose OWN gate reaches
# a PASS tier on the seeded fixture, because a step whose gate cannot reach that
# tier has no verdict for content to move. For each of them, TWO trees that
# differ in the bytes of ONE file and in nothing else:
#
#     right   every declared output present, `fixture_body`
#     wrong   the same, except entry[0] carries `wrong_body` — same path, same
#             kind, same glob, content that says the run failed
#
# and `check_step`'s full verdict SIGNATURE (status + sorted reasons, project
# root scrubbed) on each. MOVED when the signature differs; UNMOVED when the
# flow said exactly the same thing about a good artefact and a bad one.
#
# The reasons are part of the signature deliberately. "The status stayed PASS
# but the flow named the defect" is a materially different finding from "the
# flow emitted the identical sentence", and folding them together would hide
# the half that is good news.
#
# WHAT IT DOES NOT CLAIM
# ----------------------
#   * That an UNMOVED step's gate is wrong. `wrong_body` is a GENERIC corruption
#     — a JSON object that self-reports failure, an undriven Verilog output, a
#     report that says 17 violations. A gate can be entirely correct and still
#     not read the field this body corrupts. What UNMOVED says is narrower and
#     still worth saying: on the tree this suite can build, this step's declared
#     output is decided by its PRESENCE alone.
#   * That the population is the flow. It is 16 of 63 steps, and the reason the
#     other 45 are absent is recorded above by
#     `test_d8_downgrade_is_reachable_through_each_steps_own_real_gate`.
#   * That the corpus was consulted. It was not — this arm is hermetic, and the
#     published-run channel that DOES mutate real artefacts is
#     `matrix_mutation_ledger.ARTEFACT_MUTATIONS`, which needs a benchmark-data
#     clone this checkout does not carry.
# ══════════════════════════════════════════════════════════════════════
_CONTENT_MOVED = "MOVED"
_CONTENT_UNMOVED = "UNMOVED"


def _content_state(right_sig, wrong_sig) -> str:
    """MOVED / UNMOVED from two verdict signatures.

    Shared by the sweep and by the positive control ON PURPOSE. Without that,
    a sweep that hard-coded UNMOVED would keep every assertion in
    CONTENT_ARM_AS_MEASURED green — the pinned population is 16 UNMOVED today,
    so "always UNMOVED" and "correctly UNMOVED" are indistinguishable from the
    census alone. Routing the control through this same function makes the
    control the thing that fails when the decision stops deciding.
    """
    return _CONTENT_MOVED if right_sig != wrong_sig else _CONTENT_UNMOVED


def _verdict_signature(project: Path, result) -> Tuple[str, Tuple[str, ...]]:
    """``(status, sorted reasons)`` with the scratch root scrubbed.

    The root is scrubbed because it is a different `mkdtemp` on every tree, so
    leaving it in would make EVERY pair of signatures differ and the arm would
    report MOVED for all 16 steps without a single gate having read a byte.
    Sorted because the reason list's order is not part of what the flow says.
    """
    root = str(project)
    return result.status, tuple(sorted(
        str(r).replace(root, "<project>") for r in result.reasons))


@lru_cache(maxsize=1)
def _content_arm_sweep() -> Dict[str, Dict[str, Any]]:
    """``{step: record}`` for every step in the real-gate PASS-tier population.

    The record carries the bytes that were actually written, read back off disk
    BEFORE the tree is removed, so the controls below grade what the gate was
    handed rather than what this module intended to hand it.
    """
    population = _real_gate_sweep()
    out: Dict[str, Dict[str, Any]] = {}
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        if key not in population:
            continue
        step = dict(F.step_by_id(sid))          # the REAL gate, not PASS_GATE
        entries = list(F.required_outputs(sid))
        if not entries:
            continue
        entry = entries[0]
        tmp = Path(tempfile.mkdtemp(prefix="d8_content_"))
        try:
            right = tmp / "right"
            right.mkdir(parents=True)
            made = _materialize(right, step)
            right_sig = _verdict_signature(
                right, FCC.check_step(right, step, {}))

            wrong = tmp / "wrong"
            wrong.mkdir(parents=True)
            _materialize(wrong, step, wrong_entries=(entry,))
            wrong_sig = _verdict_signature(
                wrong, FCC.check_step(wrong, step, {}))

            rels = tuple(made.get(entry, ()))
            out[key] = {
                "entry": entry,
                "rels": rels,
                "right_bytes": {r: (right / r).read_bytes() for r in rels},
                "wrong_bytes": {r: (wrong / r).read_bytes() for r in rels},
                # Asked of the CONSUMER's own resolver, on the wrong tree: the
                # entry must still be satisfied there, or "the verdict did not
                # move" would be a statement about an absent file.
                "unresolved_alts": tuple(
                    a for a in alternatives(entry)
                    if not FCC._glob_first(wrong, a)),
                "right": right_sig,
                "wrong": wrong_sig,
                "state": _content_state(right_sig, wrong_sig),
            }
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return out


#: THE FINDING, PINNED. What each step in the real-gate PASS-tier population
#: does when its first declared output is present, parseable and wrong.
#:
#: MEASURED 2026-08-19 on `397b3f25f` in the pinned container image:
#:
#:     absence moves the verdict   16 of 16     (the arm this file already had)
#:     content moves the verdict    0 of 16     (this arm)
#:
#: The asymmetry is the whole result. Of the 16, twelve answer VACUOUS_PASS —
#: the gate DISCLOSED that it did not engage, which is the honest tier and not
#: a false pass — and four (`1`, `32`, `35`, `38`) answer a plain PASS with no
#: disclosure at all: `check_step` was handed a declared output whose own
#: content says the run failed, and reported the step green.
#:
#: PINNED rather than asserted-to-be-empty, and asserted in BOTH directions:
#:
#:   UNMOVED -> MOVED   good news, and it must still be written down. A gate
#:                      that LEARNS to read its artefact closes a hole, and the
#:                      diff that closes it is where that gets recorded.
#:   MOVED -> UNMOVED   a gate stopped reading content. Nothing else in this
#:                      repository would notice.
#:   a step JOINS       it arrives unpinned and this reddens by name, so the
#:                      population can never grow into an unmeasured cell.
#:
#: A step LEAVING the population is NOT graded here: that is the shrink guard
#: `test_d8_downgrade_is_reachable_through_each_steps_own_real_gate` already
#: owns, and duplicating it would report one defect as two.
CONTENT_ARM_AS_MEASURED: Dict[str, str] = {
    "D1": _CONTENT_UNMOVED, "1": _CONTENT_UNMOVED, "2": _CONTENT_UNMOVED,
    # 4 REJOINS the population with `_COVERAGE_BODY`. Measured, not assumed:
    # UNMOVED — corrupting the coverage artefact's content does not move step 4's
    # verdict, because the gate that reads it (`verilator_coverage_measure`) is
    # reached through an ADVISORY clause on this tree. That is a content channel
    # the flow HAS and does not act on, which is exactly the gap the D8 content
    # arm exists to make visible rather than to hide.
    "4": _CONTENT_UNMOVED,
    "12": _CONTENT_UNMOVED, "A1": _CONTENT_UNMOVED, "A2": _CONTENT_UNMOVED,
    "A4": _CONTENT_UNMOVED, "A5": _CONTENT_UNMOVED, "A6": _CONTENT_UNMOVED,
    "A8": _CONTENT_UNMOVED, "14": _CONTENT_UNMOVED, "28": _CONTENT_UNMOVED,
    "30": _CONTENT_UNMOVED,
    # 32 / 35 / 38: UNMOVED -> MOVED, taught by the #433c self-FAIL demotion in
    # flow_compliance_check.py (_SELF_FAIL_VERDICTS). Before it, a step whose own
    # declared output carried `"verdict": "FAIL"` was reported green: check_step
    # opened the artefact, parsed it, read `verdict`, compared it against exactly
    # one value (SKIPPED-CONDITION) and let every other value through — so a PASS
    # contradicted by its own evidence stayed a PASS.
    #
    # MEASURED on the seeded tree, not assumed. All THREE carry the new reason
    # verbatim in the wrong arm and not in the right one:
    #     VERDICT_SELF_REPORTS_FAIL (#433c): declared output(s) carry a
    #     machine-readable verdict saying the run FAILED — a PASS contradicted by
    #     its own evidence is not a PASS: <rel>: verdict='FAIL'
    # naming phase3/stage3/postroute_timing_repair/repair_log.json (32), reports/phase3/dfm_screen.json
    # (35) and phase3/stage4/foundry_handoff/mask_spec.json (38).
    #
    # 35 is worth the extra line, because reading it wrongly was one careless
    # glance away: pytest's own failure report TRUNCATES its reason list, so 35
    # first appeared to flip PASS -> FAIL with an unchanged list — a verdict that
    # moved for no stated cause, which is precisely what this file exists to
    # refuse. Reading the arms directly showed the reason IS there. That is why
    # `test_the_content_move_names_its_cause` below asserts it mechanically
    # instead of leaving it to whoever reads the next failure.
    "32": _CONTENT_MOVED, "35": _CONTENT_MOVED,
    "38": _CONTENT_MOVED,
}


#: THE BLIND SET — gradable steps whose verdict does NOT move on wrong content.
#:
#: A step is GRADABLE when the wrong tree really rewrote something (`rels`), every
#: alternative still resolves (so the wrong tree is a WRONGNESS and not an ABSENCE),
#: and at least one rewritten file is of a kind the flow can read at all. For such a
#: step, UNMOVED is not a neutral fact: it says the flow opened a readable artefact,
#: found it wrong, and reported the step at the SAME tier as the correct one.
#:
#: MEASURED on the seeded tree, 2026-08-19: 8 of the 16 PASS-tier steps are gradable,
#: and 5 of those 8 are blind. Those five are recorded here rather than asserted away,
#: because the honest options were to record them or to pretend the arm has no blind
#: spot, and a census that cannot say "here is what I still cannot see" is the same
#: instrument this whole module exists to replace.
#:
#: A RATCHET, NOT A BASELINE THAT ABSORBS. The set may only SHRINK. A step that
#: becomes blind is named and reddens; a step that stops being blind is ALSO named and
#: reddens, so the pin cannot quietly rot into a description of an older tree. Neither
#: direction can be answered by editing this set alone — the failure message says which
#: happened and asks for the change that caused it.
#: 2026-08-21, SHRINK: "2" removed. The test below asks for the shrink to be
#: recorded and for the change that caused it to be named, and the honest naming
#: is NOT "a gate learned to read its artefact" — nothing about step 2's gate
#: changed. Step 2 was never gradable. Both of its declared outputs are its own
#: gate's `--json` destinations, so the content arm was rewriting files the gate
#: truncates before it computes anything, and the suffix proxy in `_gradable`
#: called that a content channel because the filenames end in `.json`. The
#: measurement it produced was a statement about the proxy, not about step 2.
#:
#: The same correction is why 1.6x did NOT enter this set when it arrived.
#:
#: WHAT IS NO LONGER WATCHED HERE IS DISCLOSED, NOT DROPPED — see
#: :data:`CONTENT_ARM_UNGRADABLE_SELF_WRITTEN` below, which names every step in
#: this position and is re-derived live so it cannot rot into a description of
#: an older tree.
#: 2026-08-21, MERGE: "2" RESTORED. It was removed on the yaml INFERENCE that
#: step 2's only content-bearing declared output is its own gate's `--json`
#: target. The on-disk MEASUREMENT disagrees — the file survives the gate — so
#: step 2 is gradable after all, it is UNMOVED, and UNMOVED on a gradable row
#: is what this set means. Removing it was my error; the measurement puts it
#: back, and the record of why is above CONTENT_ARM_UNGRADABLE_SELF_WRITTEN.
#: 2026-09-02, SHRINK: "2", "28", "A4" and "D1" removed — and NOT because a
#: gate learned to read its artefact. All four LEFT the PASS-tier population
#: this arm sweeps, for the reasons recorded on
#: :data:`REAL_GATE_LEFT_THE_PASS_TIER`: a step the content arm cannot reach
#: cannot be blind, because blindness is a statement about a row the arm
#: graded. The four are still under assertion — at their new tier, on that map
#: — so nothing about them went unwatched; what changed is which instrument
#: watches them. If any of the four returns to the PASS tier it will arrive
#: here unpinned and this test will say so by name.
CONTENT_ARM_BLIND: Tuple[str, ...] = ("A1",)

#: Steps the content arm CANNOT grade because every content-bearing artefact it
#: rewrites is written by that step's own gate. Not a waiver and not a pass: it
#: is the denominator this arm is missing, published so a reader can see the
#: shape of what it cannot see.
#:
#: MEASURED over the live yaml: four steps declare a required_outputs set that
#: is entirely their own gate's `--json` / `--out` destinations — 1.6x, 2, 8 and
#: 36 — of which 1.6x and 2 reach the PASS tier the content arm sweeps. Closing
#: this is a FLOW change, not a matrix one: the step would have to declare an
#: artefact some other producer writes, and for 1.6x that is not currently
#: possible (the step is unconditional by design and a design that ran no
#: cross-layer search produces no upstream report).
#: 2026-08-21, MERGE: "2" REMOVED, and the test that removed it is
#: `test_the_two_readings_of_self_written_agree`, written for exactly this
#: merge. Two lanes answered "is this row gradable?" two ways and they part on
#: step 2. MEASURED:
#:
#:   step 2    declared output rewritten : reports/phase2/lint/rtl_hygiene.json
#:             yaml says the gate writes it : YES (it is a --json target)
#:             SURVIVED the gate on disk    : YES
#:   step 1.6x yaml says the gate writes it : YES
#:             SURVIVED the gate on disk    : NO
#:
#: The yaml INFERENCE reads a `--json` target and concludes the gate overwrites
#: it. That over-predicts for any clause that does not actually run: step 2's
#: path is named by a clause whose program never wrote it, so the file survived
#: and the content arm CAN grade the step. The on-disk MEASUREMENT is what
#: happened, and it is the reading this file acts on.
#:
#: So the two lanes were not both right here, as they were on the entries pin.
#: The inference was coarser and it is the one that lost, on evidence.
CONTENT_ARM_UNGRADABLE_SELF_WRITTEN: Tuple[str, ...] = ()

#: Kinds the flow can read at all. Anything else is not a content channel, so a step
#: that rewrites only those is NOT gradable and its UNMOVED means nothing about blindness.
_CONTENT_BEARING_SUFFIXES: Tuple[str, ...] = (".json", ".jsonl")


#: Paths a step's OWN gate writes, from the `--json` / `--out` of its own gate
#: commands. Re-derived from the live yaml, never listed.
def _gate_written_paths(step_id) -> frozenset:
    out = set()
    for clause in F.gate_clauses(step_id):
        cmd = clause.command or ""
        for flag in ("--json", "--out"):
            for m in re.finditer(re.escape(flag) + r"\s+(\S+)", cmd):
                out.add(m.group(1))
    return frozenset(out)


def _survived_the_gate(rec) -> Tuple[str, ...]:
    """The rewritten files still carrying the WRONG body once the gate had run.

    ``wrong_bytes`` is read off disk AFTER ``check_step`` returns, so this is a
    measurement, not an inference from the yaml: if the bytes on disk are no
    longer the ones the harness wrote, something in the run replaced them.

    The something is usually the step's own gate. A step may declare, as a
    ``required_outputs`` entry, the very path its gate passes to ``--json`` —
    and then the gate WRITES that file during ``_evaluate_gate``, before the
    output bookkeeping ever opens it. The wrong content is gone by the time
    anything could grade it.
    """
    return tuple(
        rel for rel, body in (rec.get("wrong_bytes") or {}).items()
        if body == wrong_body(rel).encode("utf-8"))


def _gradable(rec, step_id=None) -> bool:
    """Is this row's UNMOVED/MOVED a judgement about CONTENT at all?

    THE SURVIVAL CLAUSE (2026-08-21). It is not enough that the harness WROTE a
    wrong body; the wrong body has to still be there when the verdict is taken.
    Otherwise UNMOVED says "the gate overwrote the file", which is not the same
    finding as "the gate read the file and did not care", and this arm exists to
    tell those two apart.

    MEASURED across the whole real-gate PASS-tier population on this tree, and
    the discrimination is narrow rather than sweeping: **one** step is
    un-graded by it. `1.6x` declares exactly one output,
    `reports/crosslayer/rewrite_equivalence_check.json`, which is the same path
    its own gate command passes to `--json`. Survival 0 of 1. Every other
    gradable step survives in full — 2, 28, 32, 35, 38, A1, A4 and D1 all 1/1 or
    2/2 — so no step leaves `CONTENT_ARM_BLIND` because of this clause and the
    disclosed blind set does not shrink.

    Reproduced directly before the clause was written: seed
    `rewrite_equivalence_check.json` with `wrong_body`, run the real
    `check_step`, read the file back. `verdict` goes `"FAIL"` -> absent and the
    bytes differ — the gate rewrote its own report. Without this clause `1.6x`
    was charged as NEWLY BLIND, and the failure message diagnosed it as "a gate
    that stopped reading", which is the opposite of what happened: no gate
    stopped reading, a step arrived whose only declared artefact is one its gate
    produces. Charging it would have been the campaign's own disease — measuring
    something adjacent and reporting it as if it answered the question.
    """
    rels = rec.get("rels") or ()
    if not rels or rec.get("unresolved_alts"):
        return False
    return any(str(r).lower().endswith(_CONTENT_BEARING_SUFFIXES)
               for r in _survived_the_gate(rec))


def test_a_readable_artefact_that_is_wrong_is_not_worth_the_same_as_a_right_one():
    """The blind set may shrink and may not grow, and every change is named.

    `CONTENT_ARM_AS_MEASURED` records WHETHER each row moved. It cannot, alone,
    tell a row that did not move because the flow has no channel to read from a
    row that did not move because the flow read the channel and did not act. The
    first is a capability gap; the second is a gate reporting a wrong artefact as
    good as a right one. Grading only the first would let the second be legitimised
    by pinning it UNMOVED, which nothing else in this repository forbids.
    """
    sweep = _content_arm_sweep()
    assert sweep, "the content arm measured ZERO steps — a broken measurement"

    gradable = {k for k, rec in sweep.items() if _gradable(rec, k)}
    assert gradable, (
        "NO step is gradable: every row rewrote only kinds the flow cannot read, so "
        "the content arm is measuring nothing at all. That is a dead instrument, not "
        "a clean one."
    )
    blind = {k for k in gradable if sweep[k]["state"] == _CONTENT_UNMOVED}
    pinned = set(CONTENT_ARM_BLIND)

    # THE DISCLOSURE IS ASSERTED, not merely written down. Every PASS-tier step
    # the arm dropped for rewriting only its own gate's outputs must be named in
    # CONTENT_ARM_UNGRADABLE_SELF_WRITTEN, in both directions, so the set cannot
    # quietly grow (a step slipping out of the arm's reach unnoticed) or rot.
    self_written_only = sorted(
        k for k, rec in sweep.items()
        if not _gradable(rec, k)
        and any(str(r).lower().endswith(_CONTENT_BEARING_SUFFIXES)
                for r in (rec.get("rels") or ()))
        and not rec.get("unresolved_alts")
    )
    assert self_written_only == sorted(CONTENT_ARM_UNGRADABLE_SELF_WRITTEN), (
        f"the set of steps the content arm cannot grade changed: measured "
        f"{self_written_only}, pinned "
        f"{sorted(CONTENT_ARM_UNGRADABLE_SELF_WRITTEN)}. A step ENTERING this "
        f"set has left the arm's reach and must be named; a step LEAVING it has "
        f"gained an artefact its own gate does not write, which is the fix and "
        f"should be recorded as one."
    )

    grew = sorted(blind - pinned)
    healed = sorted(pinned - blind)
    assert not grew and not healed, (
        f"the blind set changed. NEWLY BLIND {grew}: a step now reports a readable "
        f"artefact that is WRONG at the same tier as one that is right — that is a "
        f"gate that stopped reading, and it must be fixed, not pinned. "
        f"NO LONGER BLIND {healed}: a gate learned to read its artefact; record the "
        f"shrink here and name the change that taught it. "
        f"gradable={sorted(gradable)} blind={sorted(blind)} pinned={sorted(pinned)}"
    )


def test_the_survival_clause_is_load_bearing_and_narrow():
    """MUTATION ARM for `_gradable`'s survival clause, in both directions.

    LOAD-BEARING: with the clause reverted — grading on what the harness WROTE
    rather than on what survived — at least one step re-enters the gradable
    population as blind, and the ratchet above would charge it. If nothing
    re-enters, the clause is dead weight and this test says so.

    NARROW: the clause may not quietly un-grade a step that really is blind. The
    set it removes is asserted by name, so widening it — a gate that starts
    rewriting an artefact it used to merely read — reddens here rather than
    silently shrinking the disclosed blind set.
    """
    recs = _content_arm_sweep()

    def gradable_ignoring_survival(rec) -> bool:
        rels = rec.get("rels") or ()
        if not rels or rec.get("unresolved_alts"):
            return False
        return any(str(r).lower().endswith(_CONTENT_BEARING_SUFFIXES)
                   for r in rels)

    with_clause = {k for k, r in recs.items() if _gradable(r)}
    without_clause = {k for k, r in recs.items()
                      if gradable_ignoring_survival(r)}
    removed = without_clause - with_clause

    assert not (with_clause - without_clause), (
        f"the survival clause ADDED {sorted(with_clause - without_clause)} to "
        f"the gradable population; it may only ever remove")
    expected_removed = set(CONTENT_ARM_UNGRADABLE_SELF_WRITTEN)
    assert removed == expected_removed, (
        f"the survival clause un-grades {sorted(removed)}, pinned "
        f"{sorted(expected_removed)}.\n"
        f"Newly un-graded: {sorted(removed - expected_removed)} — a step's declared "
        f"artefact is now being overwritten by its own gate before the verdict "
        f"is taken, which removes it from this arm's reach and must be a "
        f"decision, not a diff.\n"
        f"No longer un-graded: {sorted(expected_removed - removed)} — its artefact now "
        f"survives the gate, so it re-enters the population and its blindness "
        f"becomes a real finding again.")
    for key in removed:
        assert key not in CONTENT_ARM_BLIND, (
            f"{key} is un-graded by the survival clause AND named in "
            f"CONTENT_ARM_BLIND; a step cannot be both out of reach and a "
            f"recorded blind spot")


def test_the_content_move_names_its_cause():
    """A MOVED row must carry a reason the unmoved arm does not.

    The census records THAT a verdict moved. It cannot, on its own, tell a gate
    that learned to read its artefact from a gate that became flaky, or from a
    harness that started failing for an unrelated reason — all three read as
    UNMOVED -> MOVED. So the wrong arm must name at least one cause the right arm
    does not, and that named cause is what a later reader has to work with.

    This is not hypothetical bookkeeping. Step 35 was pinned MOVED off a pytest
    report that TRUNCATED its reason list, so it looked like a verdict that moved
    with nothing to attribute it to. It was not, but nothing in the file would
    have caught it if it had been.
    """
    sweep = _content_arm_sweep()
    assert sweep, "the content arm measured ZERO steps — a broken measurement"
    unexplained = {}
    for key, rec in sweep.items():
        if rec["state"] != _CONTENT_MOVED:
            continue
        right, wrong = rec["right"], rec["wrong"]
        gained = [r for r in wrong[1] if r not in set(right[1])]
        if not gained:
            unexplained[key] = (right[0], wrong[0])
    assert not unexplained, (
        f"{len(unexplained)} step(s) moved with no reason the unmoved arm did "
        f"not already carry: {unexplained}. A verdict that changes without "
        f"naming what changed it cannot be told from one that changed by "
        f"accident, and the census would record both identically."
    )


def test_d8_a_present_but_wrong_declared_output_is_measured_not_assumed():
    """Per step: does the flow say anything different about a WRONG artefact?"""
    sweep = _content_arm_sweep()
    # The house rule: a zero denominator REFUSES rather than passing over an
    # empty ledger. With no population there is no measurement, and a green
    # here would read as "content is fine everywhere".
    assert sweep, (
        "the content arm measured ZERO steps: `_real_gate_sweep` returned an "
        "empty PASS-tier population, so no step's own gate reached a verdict "
        "for content to move. That is a broken measurement, not a clean one — "
        "see test_d8_downgrade_is_reachable_through_each_steps_own_real_gate"
    )

    live = {k: rec["state"] for k, rec in sweep.items()}
    unpinned = sorted(k for k in live if k not in CONTENT_ARM_AS_MEASURED)
    assert not unpinned, (
        f"steps {unpinned!r} entered the real-gate PASS-tier population and "
        f"have no recorded content-arm state. Measure them and record the "
        f"result in CONTENT_ARM_AS_MEASURED in the same change: a step that "
        f"joins the population unmeasured is a cell whose artefact content "
        f"nothing in this repository has ever asked about. "
        f"Measured now: { {k: live[k] for k in unpinned} }"
    )

    changed = {k: (CONTENT_ARM_AS_MEASURED[k], live[k])
               for k in sorted(live) if CONTENT_ARM_AS_MEASURED[k] != live[k]}
    if changed:
        detail = []
        for k, (was, now) in changed.items():
            rec = sweep[k]
            detail.append(
                f"  step {k}: {was} -> {now}\n"
                f"      entry   {rec['entry']}\n"
                f"      right   {rec['right'][0]} :: "
                f"{list(rec['right'][1])[:2]}\n"
                f"      wrong   {rec['wrong'][0]} :: "
                f"{list(rec['wrong'][1])[:2]}")
        pytest.fail(
            f"the content arm disagrees with its pin on {len(changed)} of "
            f"{len(live)} measured step(s):\n"
            + "\n".join(detail)
            + "\n\nUNMOVED -> MOVED is a gate that learned to read its own "
              "artefact: record it in CONTENT_ARM_AS_MEASURED and say which "
              "change taught it. MOVED -> UNMOVED is a gate that stopped, and "
              "is the direction nothing else here would catch.")


def test_d8_the_wrong_fixture_is_present_parseable_and_still_satisfies_the_entry():
    """THE CONTROL. Without it, every UNMOVED above could mean "I wrote nothing".

    An UNMOVED verdict is only evidence about content if the wrong tree really
    differs from the right one in CONTENT and in nothing else. Four ways it
    could fail to, each of which would turn this whole arm into a green that
    measured an empty directory — the exact shape dimension 2 named ABSENCE_RED
    and refused:

      * the file is not there            -> absence, which the other arm owns
      * the file is 0 bytes              -> ditto, in a thinner disguise
      * its bytes equal the right body   -> the two trees are the same tree
      * it no longer satisfies the entry -> `_glob_first` never saw it
    """
    sweep = _content_arm_sweep()
    assert sweep, "the content arm measured ZERO steps; nothing to control"

    problems: List[str] = []
    checked = 0
    for key, rec in sorted(sweep.items()):
        entry = rec["entry"]
        if not rec["rels"]:
            problems.append(
                f"step {key}: entry {entry!r} produced no files at all")
            continue
        if rec["unresolved_alts"]:
            problems.append(
                f"step {key}: after corrupting {entry!r} the consumer's own "
                f"_glob_first no longer resolves {list(rec['unresolved_alts'])}"
                f" — the wrong tree is an ABSENCE, not a wrong content")
        for rel in rec["rels"]:
            checked += 1
            blob = rec["wrong_bytes"][rel]
            if not blob:
                problems.append(f"step {key}: {rel} was written 0 bytes")
                continue
            if blob == rec["right_bytes"][rel]:
                problems.append(
                    f"step {key}: {rel} — the wrong body is BYTE-IDENTICAL to "
                    f"the right body, so this step's UNMOVED verdict compares "
                    f"a tree with itself and means nothing")
            low = rel.lower()
            try:
                if low.endswith(".jsonl"):
                    for line in blob.decode("utf-8").splitlines():
                        if line.strip():
                            json.loads(line)
                elif low.endswith(".json"):
                    json.loads(blob.decode("utf-8"))
                elif low.endswith((".v", ".sv")):
                    text = blob.decode("utf-8")
                    assert "module " in text and "endmodule" in text, (
                        "no module/endmodule pair")
                else:
                    blob.decode("utf-8")
            except Exception as exc:                     # noqa: BLE001
                problems.append(
                    f"step {key}: {rel} does not parse as its own kind "
                    f"({exc}) — an unparseable artefact is refused on KIND and "
                    f"proves nothing about whether anything reads its content")

    assert not problems, (
        f"{len(problems)} defect(s) in the wrong fixture, over {checked} "
        f"corrupted file(s) across {len(sweep)} step(s):\n  - "
        + "\n  - ".join(problems))


def test_d8_every_seeded_kind_has_a_wrong_counterpart():
    """A kind added to `fixture_body` must not fall through to the text body.

    `wrong_body` iterates `_KIND_BODIES` so the two tables always agree on
    WHICH suffixes are special; this asserts they also agree on WHAT each one
    is. Add `.def` to the right table without adding it here and the wrong tree
    would seed a DEF path with prose, which fails on kind rather than on
    content and would quietly re-classify that step as unmeasurable.
    """
    right_suffixes = {suffix for suffix, _ in _KIND_BODIES}
    assert right_suffixes == set(_WRONG_BY_SUFFIX), (
        f"the seeded-kind tables disagree: fixture_body handles "
        f"{sorted(right_suffixes)}, wrong_body handles "
        f"{sorted(_WRONG_BY_SUFFIX)}")
    for suffix, right in _KIND_BODIES:
        rel = f"probe{suffix}"
        assert wrong_body(rel) != right, (
            f"{suffix}: the wrong body equals the right body")
        assert fixture_body(rel) == right, (
            f"{suffix}: fixture_body no longer returns the pinned right body")
    assert wrong_body("probe.rpt") == _WRONG_TEXT
    assert wrong_body("probe.rpt") != _FIXTURE_BODY


#: THE POSITIVE CONTROL's subject, anchored to the flow rather than described.
#: Step 39 is the ONLY step in the flow whose gate carries a `json_field_true`
#: clause, i.e. the only place the flow spells out a CONTENT contract for one of
#: its own declared outputs — the file is both `required_outputs[1]` and the
#: artefact the clause reads. If that clause moves, the flow can redden on
#: content; if it stops, the arm above lost its only witness.
_CONTENT_CONTROL_STEP = 39
_CONTENT_CONTROL_ARTEFACT = "reports/phase2/fpga/on_board_pass.json"
_CONTENT_CONTROL_FIELD = "all_scenarios_passed"


def test_d8_the_content_arm_can_observe_a_move(tmp_path):
    """THE POSITIVE CONTROL: a present, parseable, WRONG artefact going red.

    Sixteen UNMOVED verdicts are worth nothing if the instrument cannot report
    a MOVED one — that is the same "predicate that cannot fail" the matrix
    README forbids, one level up. So drive the one clause in the whole flow
    that declares a content contract, through the same `check_step` and the
    same signature comparison the arm uses, and require the verdict to move
    BECAUSE OF THE BYTES.

    The two trees differ in exactly one field of one file. Both files are
    present, non-empty and valid JSON; only the value is wrong. The step's
    OTHER clause needs hardware evidence no synthesized tree can carry, so the
    STATUS is FAIL on both sides — which is why this control grades the REASONS
    and not the status. "The verdict moved" and "the step passed" are different
    claims, and only the first one is being made here.
    """
    sid = _CONTENT_CONTROL_STEP
    step = dict(F.step_by_id(sid))

    # Anchored, not assumed: if the flow drops or re-points this clause the
    # control must say so rather than measure some other file.
    clauses = [c for c in F.gate_clauses(sid) if "json_field_true" in str(c)]
    gate_text = str(step.get("gate"))
    assert _CONTENT_CONTROL_ARTEFACT in gate_text, (
        f"step {sid}'s gate no longer names {_CONTENT_CONTROL_ARTEFACT!r}; the "
        f"content control has lost its subject. gate={gate_text[:400]}")
    assert _CONTENT_CONTROL_FIELD in gate_text, (
        f"step {sid}'s gate no longer reads the field "
        f"{_CONTENT_CONTROL_FIELD!r}. gate={gate_text[:400]}")
    assert _CONTENT_CONTROL_ARTEFACT in list(F.required_outputs(sid)), (
        f"{_CONTENT_CONTROL_ARTEFACT!r} is no longer one of step {sid}'s "
        f"required_outputs, so it is no longer the same question this arm asks "
        f"of the other 16 steps: {list(F.required_outputs(sid))}")
    assert clauses, f"step {sid}: no json_field_true clause resolved"

    right_body = json.dumps(
        {_CONTENT_CONTROL_FIELD: True,
         "scenarios": [{"name": "d8", "passed": True}]}, indent=2) + "\n"
    wrong_body_ = json.dumps(
        {_CONTENT_CONTROL_FIELD: False,
         "scenarios": [{"name": "d8", "passed": False}]}, indent=2) + "\n"

    sigs = {}
    for label, body in (("right", right_body), ("wrong", wrong_body_)):
        project = tmp_path / label
        project.mkdir(parents=True)
        _materialize(project, step)
        (project / _CONTENT_CONTROL_ARTEFACT).write_text(body)
        # Both sides are PRESENT and PARSEABLE, asked of the consumer's own
        # resolver and of json itself, before either verdict is read.
        assert FCC._glob_first(project, _CONTENT_CONTROL_ARTEFACT), (
            f"{label}: the consumer's resolver does not find "
            f"{_CONTENT_CONTROL_ARTEFACT}")
        assert json.loads(
            (project / _CONTENT_CONTROL_ARTEFACT).read_text())[
                _CONTENT_CONTROL_FIELD] is (label == "right")
        sigs[label] = _verdict_signature(
            project, FCC.check_step(project, step, {}))

    assert _content_state(sigs["right"], sigs["wrong"]) == _CONTENT_MOVED, (
        f"step {sid}: the flow said the IDENTICAL thing about "
        f"{_CONTENT_CONTROL_ARTEFACT} stating {_CONTENT_CONTROL_FIELD}=true "
        f"and stating it false. This is the arm's only witness that a content "
        f"red is expressible at all; with it gone, every UNMOVED in "
        f"CONTENT_ARM_AS_MEASURED is uninformative rather than a finding. "
        f"signature={sigs['right']}")

    marker = f"{_CONTENT_CONTROL_FIELD} = False"
    named = [r for r in sigs["wrong"][1] if marker in r]
    assert named, (
        f"step {sid}: the verdict moved but no reason names the field that "
        f"moved it. A content red that cannot say WHICH value was wrong is not "
        f"actionable. reasons={list(sigs['wrong'][1])}")
    assert not [r for r in sigs["right"][1] if marker in r], (
        f"step {sid}: the RIGHT tree also reports {marker!r}, so the reason is "
        f"not attributable to the corrupted byte. reasons={list(sigs['right'][1])}")


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
# UNIFORM CELL-STATE INTERFACE (read by programs/tests/test_flow_matrix_coverage.py)
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


def test_the_pin_is_the_MEASURED_population_not_a_SUPERSET_of_it():
    """The pin must EQUAL the live single-entry population, not contain it.

    WHY THIS EXISTS, and it is not hypothetical — v1.10.38 shipped the defect.
    The membership assertion above lives inside ``if len(outs) < 2``, so it can
    only fire in ONE direction:

        a step that DROPS to a single entry   -> absent from the pin -> RED here
        a step that RISES OUT of the population -> takes the else branch,
                                                   never consults the pin, and
                                                   its entry rots silently

    MEASURED on `162b5bde4` (v1.10.38), which relocated the extraction-coverage
    entries off step 1 and then APPENDED "1" to this tuple instead of
    re-deriving it::

        pin                     28 entries, containing BOTH "1" and "29"
        measured population     27
        step 29 on that commit  declares TWO required_outputs
                                (sim_postlayout/results.log OR pass.flag,
                                 reports/phase2/gates/post_layout_sim.json)
        d8                      294 passed -- it could not see any of that

    A one-directional ratchet accumulates stale members forever, and every
    landing that moves a step's declaration is another chance to add one. Set
    equality is what makes the pin a MEASUREMENT rather than a floor: a stale
    entry reddens the moment it goes stale, and nobody has to remember to look.
    """
    measured, seen = set(), set()
    for cell in _cell_params():
        c = cell.values[0] if hasattr(cell, "values") else cell
        key = F.normalize_id(c.step_id)
        if key in seen:
            continue
        seen.add(key)
        if len(F.required_outputs(c.step_id)) < 2:
            measured.add(key)

    pinned = set(SINGLE_ENTRY_STEPS_AS_MEASURED)
    assert pinned == measured, (
        f"the pin and the flow disagree.\n"
        f"  pinned but NO LONGER single-entry (stale, invisible to the "
        f"membership assert): {sorted(pinned - measured)}\n"
        f"  single-entry but NOT pinned (the case that assert already "
        f"catches): {sorted(measured - pinned)}\n"
        f"  re-derive the tuple rather than adding to it — appending is how "
        f"v1.10.38 shipped a 28-entry pin over a 27-step population.")


def test_the_two_readings_of_self_written_agree():
    """THE MERGE, AS A TEST. Two lanes answered "is this row gradable?" two
    ways -- inference from the yaml (`_gate_written_paths`) and measurement off
    disk (`_survived_the_gate`). They agree on this tree, and that agreement is
    asserted rather than assumed, because the day they part is the day a gate
    started writing a declared output under a name the yaml does not spell.
    """
    sweep = _content_arm_sweep()
    assert sweep, "the content arm measured ZERO steps -- a broken measurement"
    disagree = []
    for step_id, rec in sweep.items():
        rels = rec.get("rels") or ()
        if not rels or rec.get("unresolved_alts"):
            continue
        readable = [r for r in rels
                    if str(r).lower().endswith(_CONTENT_BEARING_SUFFIXES)]
        if not readable:
            continue
        inferred = any(str(r) not in _gate_written_paths(step_id)
                       for r in readable)
        measured = _gradable(rec, step_id)
        if inferred != measured:
            disagree.append((step_id, inferred, measured))
    # ONE DIVERGENCE IS MEASURED AND PINNED, in BOTH directions, so this test
    # still fires for any new one. The message below anticipated a divergence
    # in one direction — a gate WRITING a declared output the command does not
    # name. Measured on this tree it is the OTHER direction:
    #
    #   step 2  reports/phase2/lint/rtl_hygiene.json
    #           the gate command NAMES it as a `--json` target
    #           the file SURVIVED the gate on disk
    #
    # so the command names a target its program did not write on this fixture.
    # That is why the inference (False) and the measurement (True) disagree, and
    # it is why the measurement is the reading this file acts on: a `--json`
    # flag is an intention, and only the disk says what happened.
    #
    # 2026-09-02: the step-2 divergence is GONE, and not because either reading
    # changed its mind. Step 2 left the PASS-tier population this sweep walks
    # (see REAL_GATE_LEFT_THE_PASS_TIER — #1978 typed its unclassified rc=2
    # clauses, then #2005 refused its own gate's verdict document as run
    # evidence), so there is no longer a step-2 row for the two readings to
    # disagree about. The set is EMPTY, which is the state this test was
    # written hoping for; it is not weaker for being empty — the sweep is still
    # asserted non-empty above, and any NEW divergence in either direction
    # still reddens by name.
    KNOWN_DIVERGENCE: set = set()
    unexpected = [d for d in disagree if tuple(d) not in KNOWN_DIVERGENCE]
    stale = [d for d in KNOWN_DIVERGENCE if d not in {tuple(x) for x in disagree}]
    assert not unexpected and not stale, (
        "the yaml inference and the on-disk measurement disagree about which "
        "rows are gradable, and not in the way already recorded. NEW: "
        + repr(unexpected) + "; NO LONGER DIVERGING: " + repr(stale) +
        ". The measurement is the one this file acts on; a divergence means a "
        "gate writes a declared output under a path the gate command does not "
        "name, or names one it does not write — either way a finding about "
        "that gate, and either way it must be named here rather than absorbed.")
