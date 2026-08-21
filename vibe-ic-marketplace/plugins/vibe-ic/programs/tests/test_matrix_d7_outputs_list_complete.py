"""DIMENSION 7 of the 63x8 matrix — is the ``required_outputs`` LIST complete?

    "Does the step emit an artefact it never declares?"

Not "is the declared file there" (dimension 3). The disease this dimension
exists to catch is quieter: **a step produces a load-bearing artefact that
nothing declares, so nothing checks it exists, so its absence is invisible.**
No gate goes red. A downstream checker simply reads a file that is not there
and takes its "absent" branch, and the run reports PASS.

One cell per flow step, 69 in all, each ending in exactly one of three
machine-checkable states:

  ENFORCED  the live predicate runs and passes           63
  WAIVED    ``xfail(strict=True)`` with an evidence-backed reason    5
  NA        the NA precondition is asserted LIVE          1

Those four numbers are DERIVED, not remembered — ``cells_for(DIM)`` against the
live yaml, counted by ``test_every_cell_lands_in_exactly_one_state``. They read
``63 / 58 / 4 / 1`` here for as long as it took six steps to arrive and one to
leave without anybody restating them, which is the same defect that test's own
pin exists to prevent one step lower down.

====================================================================
WHAT IS MEASURED, AND FROM WHAT
====================================================================
Everything is recomputed at test time from
``flow/phase1_phase2_phase3.yaml`` plus the **AST** of every
``programs/*.py``. ``.audit_63x8.json`` is never consulted for a verdict; it
enumerated the cells and it is history for humans. ``matrix_d7_artifact_graph``
holds the analysis and documents each rule; the four rules in one line each:

  W1  a gate-designated output that something OTHER than its own writer reads
  W2  an artefact the flow produces and a gate consumes, declared by no step
  W3  a file the step's own gate asserts exists, declared by no step
  W4  a gate that designates outputs on a step with no ``required_outputs``

A step fails when ANY rule fires. Everything else the flow writes — a gate's
own ``--json`` report that only its writer reads, a log, a cache — is
classified EVIDENCE / INCIDENTAL and is REPORTED, not enforced
(``test_evidence_class_artefacts_are_genuinely_self_verifying``). Keeping that
split is what makes a green cell mean something.

W1 AND W4 DO NOT SPEAK ABOUT A PRODUCER THE FLOW ITSELF MARKS OPTIONAL
(2026-07-28, #537). Both rules conclude "this belongs in ``required_outputs``",
and ``required_outputs`` is UNCONDITIONAL — ``flow_compliance_check`` returns
MISSING the moment a declared entry is absent. An
``optional_program_exit_zero`` clause runs only when its
``condition_files_exist`` are all present, so its ``--json`` output is
legitimately absent on any project that did not meet the condition, and
declaring it would assert a production the same yaml denies two keys below.
Those artefacts are REPORTED by ``matrix_d7_artifact_graph.conditional_findings``
and graded by ``test_conditional_class_is_earned_from_the_flows_own_gate``;
that the exemption is narrow, and that W1 has not been disabled wholesale, are
each proved by a live yaml mutation below.

====================================================================
THE ANTI-ADJACENCY GUARDS
====================================================================
Two ways this module could have become the very thing the campaign is about,
both closed by a test that goes red if the guard rots:

1. **Believing a flag name.** ``--json`` / ``--out`` / ``--output`` /
   ``--report`` look like outputs. Two of them are not:
   ``provenance_check --output <artefact>`` names the artefact whose
   PROVENANCE is checked, and ``fpga_verification_audit --report <md>`` is
   declared ``help="markdown report to audit"``. Trusting the spelling
   charged step 6 with emitting a file it only reads — a false finding this
   module produced and then killed. Output-ness is now proven per
   ``(program, flag)`` against the receiving program's own AST, following one
   level of argv-forwarding wrapper, and
   ``test_input_shaped_output_flags_are_still_detected_as_inputs`` pins the
   two known inputs so a change to either goes red.

2. **A silently empty analysis.** If the AST scan broke, ``findings_for``
   would return ``()`` for all 63 steps and every cell would go green —
   a vacuous pass, the worst outcome available.
   ``test_artifact_indices_resolve_known_anchors`` pins five independently
   checkable facts (a known runner write, a known declared path, a known
   UNdeclared path, a wrapper-resolved flag, index sizes), so a broken
   analyser fails loudly instead of passing everything.

====================================================================
FALSIFIABILITY
====================================================================
Mutation-proved before landing; each mutation applied to the GUARDED THING
(the yaml / a program), never to a test, and reverted:

  * step 16 ``required_outputs`` minus ``phase3/stage3/cts/clock_plan.json``
    -> W2 fires (the CTS gate reads it; nothing declares it) -> step 16 red.
  * step 33 ``required_outputs`` key deleted
    -> W4 fires on its two gate-designated outputs -> step 33 red.
  * step 19 ``required_outputs`` minus ``phase3/stage3/pnr/post_cts.def``
    -> W3 fires (its own gate asserts that file exists) -> step 19 red.
  * ``provenance_check`` made to write ``args.output``
    -> the input-shaped-flag guard goes red.
  * an ``optional_program_exit_zero`` clause retyped ``program_exit_zero``,
    and (separately) its ``condition_files_exist`` emptied
    -> its output leaves the CONDITIONAL class and W1 fires on it again.
  * the sole declaration of an UNCONDITIONALLY produced, outside-read gate
    output deleted -> W1 fires, proving the optionality exemption did not
    retire the rule.

====================================================================
THE RUN'S OWN RECORD — W2's SECOND PRODUCER ORACLE (2026-08-06)
====================================================================
Everything above is decided from the yaml and from Python ASTs, and W2 asked
"does the flow produce this path" by asking the AST alone. When the answer was
no it dropped the path, with the comment ``externally supplied by design``.
That was a claim this module's own :data:`RESOLUTION_LIMITS` contradicted in
writing: a write performed inside a shelled-out OpenROAD/KLayout script is not
a Python write position and is invisible to an AST.

``programs/step_write_ledger.py`` records the other half — one ``lstat`` walk
of what a run ACTUALLY wrote, residualled against the declaration — and until
2026-08-06 no dimension read it. ``matrix_d7_write_record`` is this
dimension's reader, and it is wired at ONE seam:
``matrix_d7_artifact_graph._w2_population`` consults it only where
``writers_of()`` came back empty. Nothing else changes — not the attribution
cascade, not the ``declaring_entry`` relaxation, not the load-bearing class,
not the waivers. The record may only ever make W2 consider MORE paths; a path
W2 charges today is charged with a record present, absent, or silent about it.
(This is the mirror of dimension 3, where the ledger may only ever SUBTRACT
evidence: d3 asks whether a DECLARED artefact was produced, d7 asks whether
the declaration is COMPLETE, so the safe direction is opposite in each.)

ADMISSIBILITY IS #527's, RESTATED FOR RECORDS. A record decides nothing unless
THE COMMIT CARRIES IT (``git ls-tree -r HEAD``). No ``$HOME`` search, no env
var, no operator-supplied directory, no manifest of machine paths — a cell
whose colour depends on a tree outside the repository is the defect #527
removed from dimension 3. Each residual path is then re-verified LIVE before
it may promote anything: a symlink is not evidence of a write, a zero-byte
file is not a produced artefact, and an untracked path is a property of one
working tree. A record is a claim about the past; it is not evidence about
today.

MEASURED ON THIS COMMIT: no tracked ``reports/write_ledger.json`` exists
anywhere in THIS REPOSITORY, and for a while that sentence was the whole of the
story — the population was empty, W2's oracle was the AST alone, and this
paragraph said :data:`RECORD_BOUND_ROOTS` "pins the empty population". Both
halves stopped being true and the second stopped being true FIRST: the pin
names two roots, and the records are in the PUBLISHED CORPUS —
``benchmark-data/ic/spm/v1.10.18_sky130A`` and
``benchmark-data/ic/spm/v1.9.96_gf180mcuD`` each carry
``reports/write_ledger.json`` tracked at the corpus's own HEAD. Discovery could
not see them, because it searched only this repository after the subtree had
left it, which is exactly the shape vibe-ic#1703 named one dimension over: the
pointer switched the skip OFF without switching discovery ON.
:func:`matrix_d7_write_record.record_roots` now reads an EXPLICITLY OFFERED
corpus as a second tree under the same rule, so the pin is answerable again.
None of this is silent either way: every dimension-7 failure message and every
cell's ``record_property`` carries the
:func:`matrix_d7_write_record.binding_notes` sentence saying which roots
answered and why each other one did not.

MEASURED ON TWO REAL RUNS, which is where the number that matters comes from.
``$HOME/_sky130A_r3_run`` and
``$HOME/campaign_v1544/spm/converge_1.5.44_gf180mcuD`` yield 335 and
264 written-never-declared candidates. **That is not 335 findings, and the
difference is the whole of the work.** Filtered through W2's existing rules —
undeclared, artefact-shaped, gate-read, not a step-condition input — 12 and 9
survive, landing on steps 11, 21, 23, 24, 27, 30, D1, DT2, DT3 and M2; zero
are unattributable. Ten of those cells are green today. The two that are not
inferences at all are ``phase3/stage3/pnr/openroad.log`` and the post-PnR gate
netlist, each recorded in its run's OWN ``provenance.jsonl`` as **openroad's
declared output** and read by the gates of steps 21 and 30 — artefacts a rule
was calling "externally supplied by design" while the run's log said openroad
wrote them. The per-path table is in ``matrix_d7_write_record``'s docstring.
None of it fires here, because none of those trees is in the commit; the day
one is published, :data:`RECORD_BOUND_ROOTS` turns that into a named event and
each promotion must be declared in the yaml or waived with evidence.

MEASURED END TO END, with a real run's record actually committed: 4 -> 13
steps carrying findings, 12 findings gained, **0 lost**, 0 unattributable, 0
of the 335 residual paths refused by the live evidence rules. The twelve are
NOT twelve of the same thing, and the triage is written down in
``matrix_d7_write_record``'s docstring rather than left for the day it fires:
four are real omissions the AST provably cannot see (two of them
:data:`RESOLUTION_LIMITS` entry 1 verbatim — a write whose path root is a
function parameter), three are CONDITIONAL skip sentinels that must NOT be
declared (W2 has no #537 optionality exemption, and giving it one would move
cells that are red today, so it is not done here), one points at a chip name
hardcoded in a plugin program rather than at a missing declaration, and three
land on a step that is already red and waived.

WHY THE OTHER 323 ARE NOT FINDINGS, STATED SO NOBODY RE-DERIVES IT. Of the 335,
328 are captured by no ``required_outputs`` entry; of those, 327 can be charged
to no step by the plugin's own tables, because the one-shot runners carry no
per-step segmentation (:data:`RESOLUTION_LIMITS` entry 2) and because
``provenance.jsonl`` names EDA BINARIES while the flow names plugin programs —
measured overlap between the two vocabularies on both runs, **0 of 164**. The
residual cannot be read per step directly. This binding does not pretend it
can: it answers only the narrower question W2 was already asking, and the step
a promotion lands on is chosen by W2's own cascade.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

import flow_compliance_check as FCC
import matrix_d7_artifact_graph as G
import matrix_d7_write_record as R
import step_write_ledger as SWL
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers
from matrix_63x8.cells import cells_for

# WHERE W2's OBSERVED PRODUCER ORACLE WENT.
#
# `matrix_d7_write_record` binds W2 to the `reports/write_ledger.json` a run
# left behind, and every root that carries one — `RECORD_BOUND_ROOTS` below —
# is a PUBLISHED CELL. Those moved to https://github.com/vibeic/benchmark-data,
# so in this checkout `R.record_roots()` is empty, W2 degrades to the AST alone,
# and the findings that only the OBSERVED half could see disappear. A waived
# cell whose finding disappears XPASSes, and a strict xfail turns that into
# "the waiver is stale — remove it". It is not stale; the evidence for it was
# not readable. A check that cannot measure must never report that it measured,
# so those cells SKIP naming the corpus (vibe-ic#1357's rule for an absent tool,
# applied to an absent corpus) and run untouched wherever the corpus is present.
from _published_corpus import SKIP_REASON, corpus_root, needs_corpus  # noqa: E402

DIM = 7

#: Number of entries in ``matrix_d7_artifact_graph.RESOLUTION_LIMITS``, pinned
#: as measured 2026-07-28. See ``test_resolution_limits_are_declared``.
#: 5 -> 6 with #537: the module now exempts a flow-declared-optional producer
#: from W1/W4 and states, as the sixth limit, that whether such a producer's
#: CONDITION was met is a property of a run tree it never reads.
RESOLUTION_LIMITS_AS_MEASURED = 6

# ─────────────────────────────────────────────────────────────────────
# Waivers — ONE registry, the one that is consumed
# ─────────────────────────────────────────────────────────────────────
# This module used to carry a `PENDING_WAIVERS` mirror of its nine dimension-7
# waivers, added while eight agents shared one worktree and a concurrent edit to
# `matrix_63x8/waivers.py` could lose an entry. The orchestrator has since
# landed all nine centrally, so `_waiver_for` read the central copy and ignored
# the local one — the mirror's own comment predicted it would become "dead
# weight that should be deleted" once that happened, and it had.
#
# #527 deleted the same structure from dimension 3 after its two copies were
# found telling different stories about one accepted gap. The mirror is deleted
# rather than re-synchronised: a waiver is a public admission, and it can have
# exactly one text.
#
# THE REGISTRY NOW HOLDS FOUR DIMENSION-7 ENTRIES, not nine. Five were CLOSED
# on 2026-07-28 by DECLARING the artefact in the flow yaml (steps D1, 21, 25,
# 28, 31 — see the yaml's per-entry notes), each mutation-controlled: strip the
# declaration and the cell goes red. The four that remain are 7, 23 and M1
# (narrowed), and FS1 (reopened with a sharper reason after its closure turned
# out to rest on the compliance checker accepting an artefact it had created
# itself).


def dim_waivers():
    """This dimension's waivers, from the one registry that is consumed."""
    return tuple(waivers.waivers_for_dim(DIM))


def _waiver_for(step_id):
    """The waiver at ``(step, 7)``, or ``None``. Single source: the registry."""
    return waivers.waiver_for(step_id, DIM)


# ──────────────────────────────────────────────────────────────────────
# Parametrisation
# ──────────────────────────────────────────────────────────────────────
def _params():
    out = []
    for cell in cells_for(DIM):
        w = _waiver_for(cell.step_id)
        marks = (
            [pytest.mark.xfail(strict=True, reason=w.xfail_reason)] if w else []
        )
        out.append(pytest.param(cell, marks=marks))
    return out


def _describe(step_id, findings):
    """A failure message that quotes the MEASURED artefacts, not the rule."""
    lines = [
        f"step {step_id}: required_outputs is INCOMPLETE — "
        f"{len(findings)} load-bearing artefact(s) it never declares.",
        f"  declared ({len(F.required_outputs(step_id))} entries): "
        f"{list(F.required_outputs(step_id))}",
    ]
    for f in findings:
        lines.append(f"  * {f}")
    # Name what was EXEMPTED beside what was charged. Otherwise a reader
    # fixing this step cannot tell an artefact the rules deliberately skipped
    # from one they never saw.
    exempt = G.conditional_findings(step_id)
    if exempt:
        lines.append(
            f"  [{len(exempt)} further undeclared artefact(s) NOT charged — "
            f"the flow marks the producer optional_program_exit_zero:]"
        )
        for f in exempt:
            lines.append(f"    - {f.path} (condition: see gate)")
    # WHICH producer oracle answered. Stated in BOTH directions on purpose:
    # if only the bound case were annotated, "the AST alone decided this"
    # would become the meaning of SILENCE and a reader would be inferring it
    # from the absence of a line.
    lines.append(f"  [write record: {'; '.join(R.binding_notes())}]")
    return "\n".join(lines)


@pytest.mark.parametrize("cell", _params(), ids=lambda c: f"step{c.step_id}")
def test_d7_required_outputs_list_is_complete(cell, record_property):
    """Every load-bearing artefact step S emits is named in S's required_outputs.

    A cell with a waiver reaches the same assertion; ``xfail(strict=True)``
    turns its expected failure green and its unexpected PASS red, which is
    what forces a stale waiver out.
    """
    sid = cell.step_id

    na = G.na_precondition(sid)
    if na is not None:
        # NA is ASSERTED, never skipped: declare either half and this reddens.
        assert not F.declares_required_outputs(sid), (
            f"step {sid}: the NA no longer holds — required_outputs "
            f"{list(F.required_outputs(sid))} is now declared, so this cell has "
            f"a real dimension-7 question and must be enforced, not NA"
        )
        assert not G.gate_output_targets(sid), (
            f"step {sid}: the NA no longer holds — its gate now designates "
            f"outputs {list(G.gate_output_targets(sid))} with no "
            f"required_outputs list to capture them"
        )
        record_property("d7_state", f"NA:{na}")
        return

    evidence = G.evidence_findings(sid)
    record_property("d7_evidence_undeclared", [f.path for f in evidence])
    # WHICH producer oracle W2 had available for this cell — published on
    # every cell, green or red, so "the AST alone" is a recorded property of
    # the run rather than something a reader has to assume.
    record_property("d7_write_record_binding", list(R.binding_notes()))
    record_property(
        "d7_record_promoted",
        [f.path for f in G.findings_for(sid)
         if f.rule == G.W2 and R.observed_producers_of(f.path)
         and not G.writers_of(f.path)],
    )
    # The exempted class is recorded on the cell too, so "W1 skipped it" is a
    # published property of the run and not a silent branch in the analyser.
    record_property(
        "d7_conditional_undeclared",
        [f.path for f in G.conditional_findings(sid)],
    )

    findings = G.findings_for(sid)
    # A WAIVED cell with nothing to show, on a tree where W2's OBSERVED half
    # observed nothing and there is no corpus to read it from, is UNMEASURABLE
    # rather than healed: the finding its waiver names may be exactly one of the
    # record-promoted ones that vanished with the published cells. Reporting the
    # strict-xfail XPASS would tell an author to delete a waiver on the strength
    # of evidence nobody read. All four conditions are required, so a cell that
    # genuinely healed still XPASSes wherever the record binding is alive.
    if (not findings and _waiver_for(sid) is not None
            and not R.observed_writes() and corpus_root() is None):
        pytest.skip(SKIP_REASON)
    assert not findings, _describe(sid, findings)


# ──────────────────────────────────────────────────────────────────────
# Guards on the analysis itself
# ──────────────────────────────────────────────────────────────────────
def test_artifact_indices_resolve_known_anchors():
    """The AST analysis is alive.

    If the write scan, the literal scan or the declaration matcher broke, every
    one of the 63 cells above would find nothing and pass — 63 green cells
    measuring nothing at all. Each anchor below is independently checkable
    against the tree, and each is a fact the analysis MUST reproduce.
    """
    writers = G.writers_of("phase3/stage3/cts/clock_plan.json")
    assert "phase3_one_shot_runner" in writers, (
        "the write index no longer sees the runner emitting clock_plan.json "
        f"(programs/phase3_one_shot_runner.py:21228); got writers={sorted(writers)}"
    )

    lit = G.literal_index()
    assert "phase3/stage3/cts/clock_plan.json" in lit, (
        "the literal index no longer sees cts_quality_check.py:99 naming "
        "phase3/stage3/cts/clock_plan.json"
    )
    assert "cts_quality_check" in lit["phase3/stage3/cts/clock_plan.json"]

    assert G.declaring_entry("phase3/stage3/cts/clock_plan.json") is not None, (
        "step 16 declares phase3/stage3/cts/clock_plan.json; the declaration "
        "matcher no longer sees it, which would turn every declared artefact "
        "into a false finding"
    )
    assert G.declaring_entry("reports/phase3/sta_mcorner_ocv.rpt") is None, (
        "reports/phase3/sta_mcorner_ocv.rpt is declared by no step; the "
        "matcher now claims it is, which would hide real findings"
    )

    # Index sizes: a rough floor, so a scan that collapses to a handful of
    # entries fails here rather than quietly greening 63 cells.
    assert len(G.write_index()) >= 100, (
        f"write index collapsed to {len(G.write_index())} tails — the AST write "
        f"scan is broken"
    )
    assert len(lit) >= 500, f"literal index collapsed to {len(lit)} paths"


def test_input_shaped_output_flags_are_still_detected_as_inputs():
    """``--output`` / ``--report`` are NOT outputs for these two programs.

    This is the guard against measuring the flag's NAME instead of the
    program's behaviour. Both were live false positives before the check
    existed: believing the spelling charged step 6 with emitting
    reports/fpga_verification_report.md, which its gate only reads.

    If either program is changed to actually write the path, this reddens and
    forces the classification to be re-derived rather than silently drifting.
    """
    assert G.flag_value_is_written("provenance_check", "--output") is False, (
        "provenance_check --output names the artefact whose provenance is "
        "checked (programs/provenance_check.py:137,186) — an INPUT. The "
        "classifier now says otherwise."
    )
    assert G.flag_value_is_written("fpga_verification_audit", "--report") is False, (
        'fpga_verification_audit declares --report as help="markdown report to '
        'audit" (programs/fpga_verification_audit.py:326) — an INPUT. The '
        "classifier now says otherwise."
    )
    # ...and a positive control, so the function is not just always False.
    assert G.flag_value_is_written("cts_quality_check", "--json") is True, (
        "cts_quality_check writes Path(args.json) (programs/cts_quality_check.py"
        ":617-618); the classifier no longer detects any write and would drop "
        "every gate-designated output"
    )


def test_argv_forwarding_wrapper_flags_resolve_through_the_delegate():
    """A thin wrapper's ``--json`` is resolved through the program it forwards to.

    ``em_report_check`` parses nothing itself: it rebuilds argv and calls
    another program's ``main`` (its module docstring says so at
    programs/em_report_check.py:51-58). A classifier that stopped at the
    wrapper would report "never writes its --json" and silently drop the
    outputs of a whole family of sign-off steps — the PR #460 mistake in a new
    costume.
    """
    assert G.flag_value_is_written("em_report_check", "--json") is True, (
        "em_report_check's --json no longer resolves through its delegate; "
        f"local modules seen: {G._local_modules('em_report_check')}"
    )


def test_evidence_class_artefacts_are_genuinely_self_verifying():
    """The REPORTED (not enforced) class really is self-verifying.

    An undeclared gate output is exempted from enforcement only when its ONLY
    reader is the program that wrote it — the audit's own standard ("the gate
    program both produces and checks them in the same invocation"). If an
    exempted artefact turns out to have an outside reader, the exemption is
    laundering a real finding and this goes red.
    """
    leaked = []
    for sid in F.step_ids():
        for finding in G.evidence_findings(sid):
            readers = G._consumers_of_output(finding.path, finding.producer)
            if readers:
                leaked.append((F.normalize_id(sid), finding.path, readers))
    assert not leaked, (
        "EVIDENCE-class artefacts with an outside reader — these are "
        f"LOAD_BEARING and must be enforced, not reported: {leaked}"
    )
    total = sum(len(G.evidence_findings(s)) for s in F.step_ids())
    assert total > 0, (
        "no EVIDENCE-class artefacts found at all; the gate-output extraction "
        "has collapsed and the enforced rules are running on an empty set"
    )


def test_conditional_class_is_earned_from_the_flows_own_gate():
    """The W1/W4 optionality exemption is derived from the yaml, per path.

    The exemption is the one thing in this dimension that turns a red cell
    green without anybody declaring anything, so it is the one thing most able
    to launder a real omission. Every claim it rests on is re-derived HERE
    from ``flowref.gate_clauses`` — not by calling the analyser's own
    predicate back — so a bug in :func:`conditional_output_targets` is caught
    rather than confirmed:

      * the path really is designated by at least one of the step's clauses;
      * EVERY clause of that step designating it is
        ``optional_program_exit_zero`` (one unconditional writer and the
        artefact is produced on every run, so it belongs in the list);
      * every one of those clauses carries a NON-EMPTY
        ``condition_files_exist`` (an ``optional_`` clause with no condition
        runs always, and its output is unconditional);
      * the path is genuinely UNdeclared, so the exemption is not being
        applied to a non-finding; and
      * it has a reader outside its own writer, i.e. it is exactly what W1
        would have charged — not something ``evidence_findings`` already
        covers.
    """
    population = [
        (F.normalize_id(sid), f)
        for sid in F.step_ids()
        for f in G.conditional_findings(sid)
    ]
    # THE FLOOR. An empty class makes every loop below run zero times, and a
    # green result would mean the exemption is unexamined rather than sound.
    assert population, (
        "no step has a gate output that the flow marks "
        "`optional_program_exit_zero` AND something outside its writer reads, "
        "so the W1/W4 optionality exemption is asserting nothing. If the flow "
        "genuinely no longer has one, remove the exemption in the same change "
        "rather than leaving an unexercised branch in the analyser."
    )

    for sid, finding in population:
        clauses = [
            c for c in F.gate_clauses(sid)
            if any(p == finding.path for p, _prog in G.clause_output_targets(c))
        ]
        assert clauses, (
            f"step {sid}: {finding.path} is exempted from W1 but NO gate "
            f"clause of this step designates it as a written output — the "
            f"exemption is being applied to a path the gate does not produce"
        )
        wrong_kind = [c.kind for c in clauses if c.kind != F.K_OPTIONAL]
        assert not wrong_kind, (
            f"step {sid}: {finding.path} is exempted as conditionally "
            f"produced, but {len(wrong_kind)} clause(s) of kind {wrong_kind} "
            f"write it unconditionally. It is produced on every run and must "
            f"be enforced, not exempted."
        )
        unconditioned = [c.raw for c in clauses if not c.condition_files]
        assert not unconditioned, (
            f"step {sid}: {finding.path} is exempted as conditionally "
            f"produced, but an optional_program_exit_zero clause carries no "
            f"condition_files_exist, so it runs on every project exactly like "
            f"a plain program_exit_zero: {unconditioned}"
        )
        assert G.declaring_entry(finding.path) is None, (
            f"step {sid}: {finding.path} is declared after all — the "
            f"conditional class is carrying a non-finding"
        )
        assert finding.consumers, (
            f"step {sid}: {finding.path} has no reader outside its writer, so "
            f"it is EVIDENCE and belongs in evidence_findings(); the two "
            f"reported classes must partition, not overlap"
        )

    # ...and they really do partition: nothing is reported twice.
    for sid in F.step_ids():
        cond = {f.path for f in G.conditional_findings(sid)}
        ev = {f.path for f in G.evidence_findings(sid)}
        assert not (cond & ev), (
            f"step {F.normalize_id(sid)}: {sorted(cond & ev)} is reported as "
            f"BOTH conditional and evidence"
        )


# ──────────────────────────────────────────────────────────────────────
# The optionality exemption, mutation-controlled
# ──────────────────────────────────────────────────────────────────────
def _mutated_flow(tmp_path: Path, name: str, edit) -> Path:
    """Write a scratch copy of the flow with *edit* applied to its document.

    The real yaml is NEVER touched: this worktree is shared, and a test that
    edits the file it grades would corrupt every sibling that runs after it.
    """
    doc = yaml.safe_load(F.FLOW_YAML.read_text(encoding="utf-8"))
    edit(doc)
    out = tmp_path / name
    out.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return out


class _SwappedFlow:
    """Point flowref at *path*, drop both modules' memos, restore on exit."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._original: Optional[Path] = None

    def __enter__(self):
        self._original = F.FLOW_YAML
        F.set_flow_yaml(self._path)   # clears flowref's caches
        G.clear_flow_caches()
        return self

    def __exit__(self, *exc):
        F.set_flow_yaml(self._original)
        G.clear_flow_caches()
        return False


def _w1_paths(step_id) -> Tuple[str, ...]:
    return tuple(
        f.path for f in G.findings_for(step_id) if f.rule == G.W1
    )


def _unconditional_declared_anchor():
    """``(step, path, entry)`` for a live W1 anchor, or ``None``.

    A gate output that is produced UNCONDITIONALLY (``program_exit_zero``),
    read by something other than its writer, and declared by its own step at
    that exact path with a basename no other entry shares. Deleting that one
    entry must make W1 fire — and because every condition is re-measured here,
    the anchor follows the flow instead of rotting into a hard-coded pair.
    """
    basename_uses = Counter(
        os.path.basename(d) for d in G._all_declared() if d
    )
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        declared = G.declared_entries().get(key, frozenset())
        for clause in F.gate_clauses(sid):
            if clause.kind != F.K_PROGRAM:
                continue
            for path, prog in G.clause_output_targets(clause):
                if path not in declared:
                    continue
                if basename_uses[os.path.basename(path)] != 1:
                    continue
                if not G._consumers_of_output(path, prog):
                    continue
                for entry in F.required_outputs(sid):
                    if entry.strip().lstrip("./") == path:
                        return key, path, entry
    return None


def test_w1_still_fires_on_an_unconditionally_produced_undeclared_output(tmp_path):
    """The optionality exemption narrowed W1; it did not retire it.

    On the live tree W1 now charges NOTHING — both artefacts it used to charge
    come from ``optional_program_exit_zero`` clauses. A rule that fires on
    nothing is indistinguishable from a rule that has been switched off, and
    "switched off" is the failure mode this whole change could most easily
    have been. So the rule is proved live the same way W3 is: mutate the
    guarded thing (the yaml) and require the red.

    The mutation is the smallest one that can matter — delete the ONE
    ``required_outputs`` entry that declares an unconditionally-produced,
    outside-read gate output — and the step must be charged for exactly that
    path.
    """
    anchor = _unconditional_declared_anchor()
    assert anchor is not None, (
        "no gate output in the flow is unconditionally produced, outside-read "
        "and declared at its exact path by its own step, so W1's live "
        "falsifiability cannot be demonstrated. Do not delete this test to "
        "make that go away: if the population is genuinely empty, W1 governs "
        "nothing and must be removed with its reason stated."
    )
    step, path, entry = anchor
    assert not _w1_paths(step), (
        f"step {step} already carries a W1 finding before the mutation, so "
        f"this test cannot attribute the red to the deleted declaration"
    )

    def strip(doc):
        for s in doc["steps"]:
            if F.normalize_id(s["id"]) == step:
                s["required_outputs"] = [
                    e for e in s["required_outputs"] if e != entry
                ]

    mutated = _mutated_flow(tmp_path, "w1_declaration_stripped.yaml", strip)
    with _SwappedFlow(mutated):
        assert entry not in F.required_outputs(step), "mutation did not apply"
        assert path in _w1_paths(step), (
            f"step {step}: {entry!r} was deleted from required_outputs and W1 "
            f"did NOT charge {path} — an unconditionally produced, "
            f"outside-read, undeclared gate output. W1 has stopped enforcing."
        )

    # Restored, and the tree is measurably back where it started.
    assert entry in F.required_outputs(step)
    assert not _w1_paths(step)


def _conditional_anchor():
    """``(step, path)`` of a CONDITIONAL finding a later W1 charge is owed to.

    "Otherwise clean" is what makes the control a control. Step 23 also
    carries a conditional output, but it is red for sixteen unrelated W2
    findings, so a red observed after mutating it would prove much less about
    the exemption than the same red on a quiet step. The anchor was therefore
    the conditional finding whose step has no other finding AT ALL — on the
    flow as shipped in 2026-07 that was step 27, and it was found by
    measurement rather than named.

    THAT REQUIREMENT WAS A CLIFF, and it fell off. Step 27 acquired ONE
    unrelated ``W2`` finding — on ``reports/phase3/si_mcf_sta.json``, the
    condition trigger of the very clause whose OUTPUT is the anchor, a
    different path under a different rule — and the search returned ``None``.
    Both parametrisations then aborted on their own precondition with "this
    control measures nothing", so one unrelated red silently deleted a
    negative control instead of degrading it.

    So the requirement is split into the part that is LOAD-BEARING and the
    part that is merely PREFERABLE, and only the first can disqualify:

    * hard — ``path`` must carry no ``W1`` charge yet. Every assertion this
      control makes is about ``path`` under W1 (:func:`_w1_paths`), so this is
      exactly what buys attributability: a W1 charge seen after the mutation
      cannot have been there before. A finding under another rule, or under
      W1 on another path, can neither produce nor mask it.
    * soft — the step should be as quiet as possible, so the CELL's red is
      attributable too and not only the path's. This is a ranking, not a
      filter: candidates are ordered by how many findings their step carries,
      flow order breaking ties.

    A step with no finding at all therefore still wins whenever the flow
    supplies one — the anchor the author chose is not quietly given up — and
    when none exists the control keeps measuring on the quietest step there
    is instead of measuring nothing. Both halves are guarded:
    :func:`test_the_anchor_search_takes_the_least_perturbed_candidate` and
    :func:`test_the_anchor_search_survives_an_unrelated_finding_on_every_step`.
    """
    candidates = []
    for order, sid in enumerate(F.step_ids()):
        findings = G.conditional_findings(sid)
        if not findings:
            continue
        path = findings[0].path
        if path in _w1_paths(sid):
            continue        # a later W1 charge here would not be the mutation's
        candidates.append(
            (len(G.findings_for(sid)), order, F.normalize_id(sid), path)
        )
    if not candidates:
        return None
    _noise, _order, step, path = min(candidates)
    return step, path


def _anchor_candidates():
    """``{step: findings-on-that-step}`` for every step the search may pick.

    The guards below need the population the ranking ranges over, and they
    must read it the same way :func:`_conditional_anchor` does or they would
    be grading a different corpus.
    """
    out = {}
    for sid in F.step_ids():
        findings = G.conditional_findings(sid)
        if not findings:
            continue
        if findings[0].path in _w1_paths(sid):
            continue
        out[F.normalize_id(sid)] = len(G.findings_for(sid))
    return out


def _manufacture_a_second_candidate(monkeypatch) -> str:
    """Give the flow a SECOND anchor candidate, and return its step.

    A preference between candidates cannot be observed on a flow that supplies
    one, and this control used to SKIP in that case. A skip is a green that
    tested nothing — the failure mode this whole module exists to remove — and
    it is not hypothetical here: disposing step 27's promotion (#1215/#1619)
    takes the live population from two candidates to one, so the ranking would
    have gone unguarded on the very tree the fix is aimed at.

    So the subject is manufactured instead, the way
    :func:`test_w4_exemption_is_exercised_on_a_mutated_flow` manufactures W4's:
    the NOISIEST step that carries no conditional finding is given a synthetic
    one. Noisiest on purpose — the ranking must be seen preferring the quiet
    live candidate over a loud manufactured one, which is the direction that
    can actually fail.
    """
    real_cond = G.conditional_findings
    step = max(
        (sid for sid in F.step_ids() if not real_cond(sid)),
        key=lambda sid: (len(G.findings_for(sid)), F.normalize_id(sid)),
    )
    key = F.normalize_id(step)

    class _Synthetic:
        rule = G.C1
        path = "reports/phase3/SYNTHETIC_second_candidate.json"

        def __str__(self):
            return f"{self.rule}: {self.path}"

    monkeypatch.setattr(
        G, "conditional_findings",
        lambda sid: ((_Synthetic(),) if F.normalize_id(sid) == key
                     else real_cond(sid)),
    )
    return key


def test_the_anchor_search_takes_the_least_perturbed_candidate(monkeypatch):
    """The quietest candidate wins, and the preference is COMPUTED.

    The ranking is what keeps "otherwise clean" a preference instead of a
    cliff, and a preference nobody checks is a comment. Two arms, and neither
    is allowed to skip: when the live flow supplies fewer than two candidates
    the second is manufactured (see above), so this runs on every tree.

      RANKING   the chosen step carries the fewest findings of any candidate.
                A search returning the first candidate in flow order passes
                "is not None" and fails this.
      MOVES     inflate the winner's findings past the runner-up's and the
                anchor must MOVE. A ranking pinned to a step id, or read off
                anything but the measurement, survives arm 1 and dies here.
    """
    if len(_anchor_candidates()) < 2:
        _manufacture_a_second_candidate(monkeypatch)
    candidates = _anchor_candidates()
    assert len(candidates) >= 2, (
        f"only {len(candidates)} anchor candidate(s) even after manufacturing "
        f"one, so the preference cannot be observed and this control would be "
        f"asserting nothing: {candidates}"
    )

    anchor = _conditional_anchor()
    assert anchor is not None
    step, _path = anchor
    assert candidates[step] == min(candidates.values()), (
        f"the search chose step {step}, which carries {candidates[step]} "
        f"finding(s), while a candidate with {min(candidates.values())} "
        f"exists: {candidates}. The control would then be attributing a red "
        f"on a noisier step than it had to."
    )

    runner_up = min((s for s in candidates if s != step),
                    key=lambda s: (candidates[s], s))
    real = G.findings_for

    class _Unrelated:
        rule = G.W2
        path = "reports/phase3/UNRELATED_ranking_probe.json"

        def __str__(self):
            return f"{self.rule}: {self.path}"

    louder = tuple(_Unrelated() for _ in range(candidates[runner_up] + 1))
    monkeypatch.setattr(
        G, "findings_for",
        lambda sid: (tuple(real(sid)) + louder
                     if F.normalize_id(sid) == step else real(sid)),
    )
    moved = _conditional_anchor()
    assert moved is not None and moved[0] == runner_up, (
        f"step {step} was made noisier than step {runner_up} "
        f"({candidates[step] + len(louder)} findings vs {candidates[runner_up]}) "
        f"and the search still returned {moved}. The preference is not being "
        f"computed from the findings."
    )


def test_the_anchor_search_survives_an_unrelated_finding_on_every_step(
        monkeypatch):
    """PAIRED GUARD: the failure that deleted this control must not recur.

    One ``W2`` finding on one unrelated path returned ``None`` from the old
    search. Reproduce the general form of it — an unrelated finding on EVERY
    step, so no step is silent under every rule — and require that a usable
    anchor still comes back.

    "Usable" is the second half and it carries the weight: returning any old
    step would satisfy ``is not None`` while destroying the attributability
    the anchor exists for, so the returned path is required to be free of W1
    exactly as the control's own precondition requires.
    """
    real = G.findings_for

    class _Unrelated:
        rule = G.W2
        path = "reports/phase3/UNRELATED_never_a_real_artifact.json"

        def __str__(self):
            return f"{self.rule}: {self.path}"

    monkeypatch.setattr(
        G, "findings_for", lambda sid: tuple(real(sid)) + (_Unrelated(),)
    )
    anchor = _conditional_anchor()
    assert anchor is not None, (
        "one unrelated finding on every step deleted the anchor entirely, "
        "which is the exact failure this ranking exists to prevent"
    )
    step, path = anchor
    assert path not in _w1_paths(step), (
        f"the search returned step {step} / {path}, which already carries "
        f"a W1 charge; a charge seen after the mutation would not be the "
        f"mutation's and the control would be measuring nothing"
    )


@pytest.mark.parametrize(
    "mutation",
    ["retype_clause_unconditional", "empty_condition_files"],
)
def test_the_exemption_rests_on_the_flows_optionality_and_nothing_else(
    tmp_path, mutation
):
    """Take the optionality away and the cell goes red again.

    Two independent ways to remove it, because the exemption has two
    conditions and either alone would be a hole:

      ``retype_clause_unconditional``  the clause becomes
          ``program_exit_zero``. The producer now runs on every project, the
          artefact is produced unconditionally, and it must be declared.
      ``empty_condition_files``       the clause stays ``optional_`` but its
          ``condition_files_exist`` is emptied. ``flow_compliance_check``
          blocks on such a clause exactly like a plain one, so the VOCABULARY
          alone must not buy an exemption — only a real condition does.

    Both mutate the yaml, never a test. If either fails to redden the anchor's
    path, that path is exempt for a reason other than the one this change
    claims. The anchor is whatever :func:`_conditional_anchor` measures, never
    a step named here — naming one is how this control came to depend on the
    flow keeping step 27 quiet.
    """
    anchor = _conditional_anchor()
    assert anchor is not None, (
        "no exempted path is free of a W1 charge, so removing the optionality "
        "cannot be shown to redden anything and this control measures nothing"
    )
    step, path = anchor
    assert path not in _w1_paths(step), (
        f"step {step} already carries a W1 charge on {path} before the "
        f"mutation, so a charge seen afterwards would not be the mutation's "
        f"and this control could attribute nothing. Findings on the step: "
        f"{[str(f) for f in G.findings_for(step)]}"
    )

    def edit(doc):
        for s in doc["steps"]:
            if F.normalize_id(s["id"]) != step:
                continue
            for clause in (s.get("gate") or {}).get("all_of") or []:
                spec = clause.get(F.K_OPTIONAL)
                if not isinstance(spec, dict):
                    continue
                if path not in str(spec.get("command", "")):
                    continue
                if mutation == "retype_clause_unconditional":
                    del clause[F.K_OPTIONAL]
                    clause[F.K_PROGRAM] = spec["command"]
                else:
                    spec["condition_files_exist"] = []

    mutated = _mutated_flow(tmp_path, f"d7_{mutation}.yaml", edit)
    with _SwappedFlow(mutated):
        assert path not in {
            p for p, _w, _c in G.conditional_output_targets(step)
        }, (
            f"step {step}: after {mutation!r} the flow no longer declares "
            f"{path}'s producer conditional, yet the analyser still exempts "
            f"it — the exemption is not reading the gate"
        )
        assert path in _w1_paths(step), (
            f"step {step}: after {mutation!r} the producer of {path} runs "
            f"unconditionally and nothing declares the artefact, so W1 must "
            f"charge it. It did not: findings were "
            f"{[str(f) for f in G.findings_for(step)]}"
        )

    # And back: the exemption returns with the flow's own optionality.
    assert path in {p for p, _w, _c in G.conditional_output_targets(step)}
    assert path not in _w1_paths(step)


def _no_list_but_writes_anchor():
    """``(step, paths)`` of a step with NO ``required_outputs`` whose gate writes.

    W4's whole subject. On the current flow that is FS1 alone, and its two
    outputs come from plain ``program_exit_zero`` clauses — which is exactly
    why W4's optionality exemption has no live subject and must be proved on a
    mutated flow instead of asserted into the source and never exercised.
    """
    for sid in F.step_ids():
        if F.declares_required_outputs(sid):
            continue
        targets = G.gate_output_targets(sid)
        if targets:
            return F.normalize_id(sid), tuple(p for p, _w in targets)
    return None


@pytest.mark.parametrize(
    "condition, w4_expected",
    [
        # A real condition: production IS conditional, so an absent
        # `required_outputs` key has nothing it was obliged to hold.
        (["phase2/stage1/rtl"], False),
        # The same clause KIND with an empty condition list runs on every
        # project, so the outputs are unconditional and W4 must still charge
        # them. Spelling `optional_` must not be enough on its own.
        ([], True),
    ],
    ids=["real_condition_exempts", "empty_condition_does_not"],
)
def test_w4_exemption_is_exercised_on_a_mutated_flow(tmp_path, condition,
                                                     w4_expected):
    """W4 skips a conditionally-produced output — proved, not asserted.

    W1 and W4 share one premise ("this belongs in ``required_outputs``") and
    therefore one defect, so #537 fixed both. But every step in the current
    flow that omits ``required_outputs`` produces its gate outputs
    UNCONDITIONALLY, so W4's half of the fix governs nothing on this tree: a
    mutation that deletes it changes no verdict, which means shipping it
    without this test would ship an unexecuted branch.

    So the subject is manufactured, in a scratch copy of the yaml: retype the
    anchor step's gate clauses ``optional_program_exit_zero`` and require W4
    to behave the way the fix claims — silent when the condition is real,
    unchanged when the condition list is empty.
    """
    anchor = _no_list_but_writes_anchor()
    assert anchor is not None, (
        "no step declares gate outputs without a required_outputs key, so W4 "
        "governs nothing at all and should be removed rather than exempted"
    )
    step, paths = anchor
    before = {f.path for f in G.findings_for(step) if f.rule == G.W4}
    assert before == set(paths), (
        f"step {step}: W4 charges {sorted(before)} but the gate designates "
        f"{sorted(paths)} — the baseline for this control is not what it "
        f"claims to be"
    )

    def retype(doc):
        for s in doc["steps"]:
            if F.normalize_id(s["id"]) != step:
                continue
            for clause in (s.get("gate") or {}).get("all_of") or []:
                cmd = clause.pop(F.K_PROGRAM, None)
                if cmd is None:
                    continue
                clause[F.K_OPTIONAL] = {
                    "command": cmd,
                    "condition_files_exist": list(condition),
                }

    mutated = _mutated_flow(tmp_path, f"d7_w4_{len(condition)}.yaml", retype)
    with _SwappedFlow(mutated):
        assert G.gate_output_targets(step), (
            "the retyped clauses no longer designate any output — the "
            "mutation broke the subject instead of changing its optionality"
        )
        assert not F.declares_required_outputs(step), "mutation changed the key"
        after = {f.path for f in G.findings_for(step) if f.rule == G.W4}
        if w4_expected:
            assert after == set(paths), (
                f"step {step}: its gate clauses are optional_program_exit_zero "
                f"with an EMPTY condition_files_exist, so they run on every "
                f"project and their outputs are unconditional. W4 must still "
                f"charge {sorted(paths)}; it charged {sorted(after)}."
            )
        else:
            assert not after, (
                f"step {step}: its gate now declares every output "
                f"conditionally produced (on {condition}), so an absent "
                f"required_outputs key is not an incomplete list. W4 charged "
                f"{sorted(after)} anyway."
            )
            # And the artefacts are not lost: with no outside reader they are
            # the EVIDENCE class, still reported.
            reported = {f.path for f in G.evidence_findings(step)} | {
                f.path for f in G.conditional_findings(step)
            }
            assert set(paths) <= reported, (
                f"step {step}: {sorted(set(paths) - reported)} was exempted "
                f"from W4 and is reported by NEITHER evidence_findings nor "
                f"conditional_findings — the exemption made it invisible"
            )

    assert {f.path for f in G.findings_for(step) if f.rule == G.W4} == set(paths)


def test_unattributable_findings_are_surfaced_not_dropped():
    """Artefacts real enough to name but not chargeable to one step stay visible.

    W2's attribution cascade can end without a unique owner. Those findings
    are enforced against no cell — charging one of eleven candidates would be
    a guess reported as a finding — so they must at least be printable, and
    every one must be a genuine produced+consumed+undeclared artefact.
    """
    # 2026-07-27, adversarial finding (LOW): this test was a bare `for` over a
    # list measured live at LENGTH ZERO, so it passed having evaluated no
    # assertion at all — a W2 cascade that silently stopped producing
    # unattributable findings would have been indistinguishable from today's
    # healthy zero. The residue is legitimately empty; what has to be non-empty
    # is the POPULATION it is the residue OF. Assert that floor first, so
    # "0 unattributable" is a measured outcome of a live cascade rather than a
    # dead function.
    population = G._w2_population()
    assert population, (
        "the W2 attribution cascade returned an EMPTY population, so both the "
        "attributed findings and the unattributable residue are trivially "
        "empty and this dimension's consumer-anchored rule is measuring "
        "nothing. Expected the live tree to yield produced+consumed artefacts."
    )
    attributed = [p for p in population if p[1] is not None]
    assert attributed, (
        f"the W2 cascade found {len(population)} produced+consumed+undeclared "
        f"artefact(s) and could attribute NONE of them; the owner cascade is "
        f"dead, and every finding would silently land in the unattributable "
        f"bucket that is enforced against no cell"
    )
    unattributable = G.unattributable_findings()
    assert len(unattributable) == len(population) - len(attributed), (
        f"the unattributable list ({len(unattributable)}) is not the residue "
        f"of the cascade ({len(population)} total, {len(attributed)} "
        f"attributed) — findings are being dropped between the two"
    )
    for finding in unattributable:
        assert G.declaring_entry(finding.path) is None, (
            f"{finding.path} is declared after all; the unattributable list is "
            "carrying a non-finding"
        )
        assert G.writers_of(finding.path) or R.observed_producers_of(finding.path), (
            f"{finding.path} has no producer under EITHER oracle — no "
            f"programs/*.py write position resolves it and no admissible run "
            f"record observed a run writing it; the unattributable list is "
            f"carrying a phantom"
        )


def test_every_cell_lands_in_exactly_one_state():
    """69 cells; ENFORCED + WAIVED + NA == 69, and no cell is in two states.

    The census is derived live, not written down: a step added to the yaml
    lands here as ENFORCED and this arithmetic keeps holding, while a waiver
    for a step that has stopped failing is caught by its own ``strict=True``.
    """
    cells = cells_for(DIM)
<<<<<<< HEAD
    # 68 -> 69, and the previous number was wrong rather than stale. Two steps
    # moved and only one of them was counted:
    #   `1.6x` ARRIVED at v1.11.15 (ppa(phase4): wire step 1.6x to an executor)
    #   `37.5self` was RETIRED at v1.11.18 (the general precheck was never a
    #       third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    #       every design that reaches that step, and the operator's container
    #       runs IN ADDITION wherever the PDK ships a precheck and its template
    #       was fetched. A PDK with no shuttle precheck is the same step with
    #       one fewer arm, not a different route.)
    # v1.11.18 wrote `69 -> 68` by DECREMENTING, and the count it decremented
    # from predated `1.6x`. That is precisely the failure this pin exists to
    # make loud, so the number is re-derived rather than adjusted: the live
    # yaml carries 69 step ids, `1.6x` among them and `37.5self` not.
    # A step arriving OR leaving must force a human to say the number out loud.
=======
    # 69 -> 68: step `37.5self` (General Precheck) is RETIRED, and the census
    # goes back DOWN. The owner's 2026-08-20 decision: the general precheck was
    # never a third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    # every design that reaches that step, and the operator's container runs IN
    # ADDITION wherever the PDK ships a precheck and its template was fetched.
    # A PDK with no shuttle precheck is the same step with one fewer arm, not a
    # different route. Re-stated by hand, as the census comments here require:
    # a step LEAVING must force a human to say the number just as loudly as one
    # arriving. RE-DERIVED from the live yaml, never decremented by hand.
<<<<<<< HEAD
    # RE-DERIVED 2026-08-21, 68 -> 69. NOT decremented or incremented by
    # hand: measured with `len(F.step_ids())` on the live yaml. The
    # population moved +'0.5ic', +'1.6x' (v1.11.15), -'37.5self'
    # (v1.11.18) and this pin was moved for none of them, which is why it
    # was already red on main before the ninth dimension landed.
>>>>>>> origin/jm9/d9-verdict-consumed
    assert len(cells) == len(F.step_ids()) == 69
=======
    assert len(cells) == len(F.step_ids()) == 69   # 68 -> 69: step 1.6x
>>>>>>> origin/jmatrix/63x8-main-reds

    state = Counter()
    for cell in cells:
        sid = cell.step_id
        is_na = G.na_precondition(sid) is not None
        is_waived = _waiver_for(sid) is not None
        assert not (is_na and is_waived), (
            f"step {sid} is both NA and WAIVED — a cell must be in exactly one "
            "state"
        )
        state["NA" if is_na else ("WAIVED" if is_waived else "ENFORCED")] += 1

<<<<<<< HEAD
    # 68 -> 69, and the previous number was wrong rather than stale. Two steps
    # moved and only one of them was counted:
    #   `1.6x` ARRIVED at v1.11.15 (ppa(phase4): wire step 1.6x to an executor)
    #   `37.5self` was RETIRED at v1.11.18 (the general precheck was never a
    #       third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    #       every design that reaches that step, and the operator's container
    #       runs IN ADDITION wherever the PDK ships a precheck and its template
    #       was fetched. A PDK with no shuttle precheck is the same step with
    #       one fewer arm, not a different route.)
    # v1.11.18 wrote `69 -> 68` by DECREMENTING, and the count it decremented
    # from predated `1.6x`. That is precisely the failure this pin exists to
    # make loud, so the number is re-derived rather than adjusted: the live
    # yaml carries 69 step ids, `1.6x` among them and `37.5self` not.
    # A step arriving OR leaving must force a human to say the number out loud.
=======
    # 69 -> 68: step `37.5self` (General Precheck) is RETIRED, and the census
    # goes back DOWN. The owner's 2026-08-20 decision: the general precheck was
    # never a third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    # every design that reaches that step, and the operator's container runs IN
    # ADDITION wherever the PDK ships a precheck and its template was fetched.
    # A PDK with no shuttle precheck is the same step with one fewer arm, not a
    # different route. Re-stated by hand, as the census comments here require:
    # a step LEAVING must force a human to say the number just as loudly as one
    # arriving. RE-DERIVED from the live yaml, never decremented by hand.
<<<<<<< HEAD
    # RE-DERIVED 2026-08-21, 68 -> 69. NOT decremented or incremented by
    # hand: measured with `len(F.step_ids())` on the live yaml. The
    # population moved +'0.5ic', +'1.6x' (v1.11.15), -'37.5self'
    # (v1.11.18) and this pin was moved for none of them, which is why it
    # was already red on main before the ninth dimension landed.
>>>>>>> origin/jm9/d9-verdict-consumed
    assert sum(state.values()) == 69, state
=======
    assert sum(state.values()) == 69, state   # 68 -> 69: step 1.6x
>>>>>>> origin/jmatrix/63x8-main-reds
    assert state["NA"] >= 1 and state["ENFORCED"] >= 1, state
    # Waivers must not be the majority strategy: if they ever are, this
    # dimension has stopped enforcing anything and should be redesigned.
    assert state["WAIVED"] < state["ENFORCED"], (
        f"more cells waived than enforced: {dict(state)}"
    )


def test_waivers_meet_the_registry_standard():
    """This dimension's waivers are held to ``waivers.validate()``.

    Reads the ONE registry. The module-local ``PENDING_WAIVERS`` mirror this
    used to validate was deleted: ``_waiver_for`` had preferred the central
    copy for some time, so validating the mirror graded a table nothing read.

    THE FLOOR IS ASSERTED FIRST (2026-07-28, adversarial finding, LOW). The
    mirror-reading version of this test looped zero times once the mirror went
    empty: ``problems`` was ``{}``, the assertion held, and the test passed
    having evaluated nothing. An empty subject is a measurement of nothing, so
    it is a failure, not a pass.
    """
    assert dim_waivers(), f"dimension {DIM} declares no waiver at all"
    # And the cell census must agree that these are the waivers IN FORCE —
    # otherwise the validated list could be a stale one no cell consults, and
    # the quality bar would be applied to the wrong entries.
    applied = {F.normalize_id(c.step_id) for c in cells_for(DIM)
               if _waiver_for(c.step_id) is not None}
    assert applied == {F.normalize_id(w.step_id) for w in dim_waivers()}, (
        f"the waivers this dimension APPLIES {sorted(applied)} are not the "
        f"ones validated here "
        f"{sorted(F.normalize_id(w.step_id) for w in dim_waivers())}"
    )
    problems = {}
    for waiver in dim_waivers():
        found = waivers.validate(waiver)
        if found:
            problems[waiver.label] = found
    assert not problems, problems

    keys = [w.key for w in dim_waivers()]
    assert len(keys) == len(set(keys)), f"duplicate waiver keys: {keys}"
    assert all(w.dim == DIM for w in dim_waivers())

    # A waiver must name a step that is CURRENTLY failing. An entry for a
    # healthy step would be dead weight the strict xfail cannot catch (a
    # waived-but-passing cell XPASSes, but only if the waiver is actually
    # applied — this catches the case where it is applied to a step that has
    # no findings and no NA either).
    inert = [
        w.label
        for w in dim_waivers()
        if not G.findings_for(w.step_id) and G.na_precondition(w.step_id) is None
    ]
    # Same unmeasurable state as the cell test above, reached from the registry
    # side: with W2's OBSERVED half empty and no corpus to read it from, a
    # record-promoted finding is invisible and its waiver looks like dead
    # weight. "Remove them" would be advice founded on evidence nobody read.
    # Everything else in this test has already been asserted by the time this
    # line is reached; only the LAST claim is the one that cannot be made.
    if inert and not R.observed_writes() and corpus_root() is None:
        pytest.skip(SKIP_REASON)
    assert not inert, (
        f"waivers whose step has no findings — remove them: {inert}"
    )


def test_na_cells_are_exactly_the_steps_with_nothing_to_compare():
    """NA is derived, never listed.

    A step is NA for dimension 7 only when it declares no ``required_outputs``
    AND its gate designates no output — there is then no artefact and no list,
    so the question has no content. Every other step is answerable and must be
    enforced or waived.
    """
    na = [F.normalize_id(s) for s in F.step_ids() if G.na_precondition(s)]
    for sid in na:
        assert not F.declares_required_outputs(sid)
        assert not G.gate_output_targets(sid)
    for sid in F.step_ids():
        if F.normalize_id(sid) in na:
            continue
        assert F.declares_required_outputs(sid) or G.gate_output_targets(sid), (
            f"step {sid} declares no required_outputs and designates no gate "
            "output, so it should be NA but is not"
        )


def test_resolution_limits_are_declared():
    """DOCUMENTATION-SHAPE CHECK — NOT a predicate of this dimension.

    The dimension states what it cannot see, in-tree, and this asserts the
    statement is present and has not been silently emptied.

    2026-07-27, adversarial finding (LOW), accepted as written: the assertion
    is satisfied by any N strings over 60 characters. It cannot detect a stated
    limit that has become FALSE, nor a new blind spot nobody wrote down.
    Deciding either needs the engineering judgement the limits describe. So it
    is labelled here for what it is — a shape check that must not be counted as
    coverage of dimension 7 — and the count is PINNED rather than floored, so a
    limit deleted in a refactor reddens instead of passing the >= test.
    """
    assert len(G.RESOLUTION_LIMITS) == RESOLUTION_LIMITS_AS_MEASURED, (
        f"matrix_d7_artifact_graph.RESOLUTION_LIMITS now has "
        f"{len(G.RESOLUTION_LIMITS)} entries, pinned at "
        f"{RESOLUTION_LIMITS_AS_MEASURED}. Adding a limit is expected when a "
        f"new blind spot is found; DELETING one means the dimension is "
        f"claiming to see something it previously could not. Either way, say "
        f"which in the same change and update the pin."
    )
    for limit in G.RESOLUTION_LIMITS:
        assert len(limit) > 60, limit


# ══════════════════════════════════════════════════════════════════════
# THE RUN'S OWN WRITE RECORD — W2's SECOND PRODUCER ORACLE
#
# `_w2_population` used to drop a gate-read, undeclared path with
#     if not producers: continue  # externally supplied by design
# whenever no `programs/*.py` write position resolved it. The three tests below
# are the control for replacing that inference with a measurement, and they are
# bidirectional by construction: the FORWARD case fails against the
# byte-identical pre-change `matrix_d7_artifact_graph.py`, and three REVERSE
# cases must still pass on both sides.
# ══════════════════════════════════════════════════════════════════════
_GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "d7", "GIT_AUTHOR_EMAIL": "d7@example.invalid",
            "GIT_COMMITTER_NAME": "d7", "GIT_COMMITTER_EMAIL": "d7@example.invalid"}


def _start_run(probe: Path) -> None:
    """Drop the emitter's own t0 marker, then wait out the mtime clock.

    ``mark_run_start`` stamps ``time.time()``; a file inode's mtime comes from
    the kernel's COARSE realtime clock, which lags by up to one timer tick. So
    a file genuinely created after t0 can carry an mtime a few milliseconds
    BEFORE it, and ``in_run_window`` (``mtime >= t0``) then reads false — the
    emitter would report an empty residual and this control would pass while
    measuring nothing. MEASURED on this host: t0 1785994463.5058, mtime of a
    file written immediately after it 1785994463.5048.

    Irrelevant on a real run, where writes land seconds to hours after t0.
    Here it is the difference between a control and a no-op, so the wait is
    explicit rather than left to luck.
    """
    assert SWL.mark_run_start(probe)
    time.sleep(0.05)


@contextlib.contextmanager
def _probe_run_root(prefix: str):
    """A throwaway run tree that is its OWN git repository.

    It has to be a real repo, not a directory: the admissibility rule this
    control exists to exercise is "the COMMIT carries the record", answered by
    ``git ls-tree -r HEAD``. A probe that could not be committed would let the
    control pass without ever testing the rule.

    Kept UNDER 20 FILES on purpose. ``step_write_ledger.mtime_fidelity``
    declares a tree flattened when ``n >= 20 and (distinct <= 4 or
    top_mtime_share >= 0.5)``, and a probe built inside one second trips both
    disjuncts — the emitter would then WITHHOLD the very residual under test
    and the control would be measuring the withholding, not the binding.
    """
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        env = {**os.environ, **_GIT_ENV}

        def git(*args):
            return subprocess.run(["git", *args], cwd=str(tmp), check=True,
                                  capture_output=True, env=env)

        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "root")

        def commit(*paths: str):
            if paths:
                git("add", "--", *paths)
            git("commit", "-q", "--allow-empty", "-m", "probe")

        yield tmp, commit
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _w2_dropped_candidates() -> Tuple[Tuple[str, str], ...]:
    """``((path, owning step), ...)`` — every path W2 drops for "no producer".

    Derived LIVE from the same three indices ``_w2_population`` uses, and the
    owner from the same cascade, so this control cannot go stale against a
    yaml edit and cannot silently start probing a path the rule no longer
    considers. A hard-coded path would do both.
    """
    same_dir = G._same_dir_declarers()
    consumers = G._gate_consumers()
    skip = G._step_condition_basenames()
    out: List[Tuple[str, str]] = []
    for path in sorted(consumers):
        if "*" in path or "?" in path or not G.is_artifact_path(path):
            continue
        if os.path.basename(path) in skip or G.declaring_entry(path):
            continue
        if G.writers_of(path):
            continue                      # the AST already calls it produced
        if path.startswith(SWL._D7_INPUT_PREFIXES):
            continue                      # the emitter excludes run INPUTS
        cons = consumers[path]
        decl = same_dir.get(os.path.dirname(path), frozenset())
        both = decl & cons
        owner = (next(iter(both)) if len(both) == 1 else
                 next(iter(cons)) if len(cons) == 1 else
                 next(iter(decl)) if len(decl) == 1 else None)
        if owner is not None:
            out.append((path, owner))
    return tuple(out)


def _plant_record(probe: Path, commit, path: str) -> Dict[str, Any]:
    """Write *path*, run the REAL emitter, commit both. Returns the record.

    The record is never hand-written. If ``step_write_ledger`` changes what it
    records, this control changes with it or it breaks — which is the point: a
    control asserting against a fixture shaped like the record stops testing
    the record.
    """
    _start_run(probe)                     # t0, so the run window is KNOWN
    target = probe / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("// written by a tool this plugin only shells out to\n")
    commit(path)
    res = SWL.emit(probe)
    assert res.get("ok"), res
    commit(R.RECORD_REL)
    return json.loads((probe / R.RECORD_REL).read_text())


def _bind(monkeypatch, probe: Path, rel: str = "probe") -> None:
    """Point the record reader at *probe* and drop every derived memo."""
    monkeypatch.setattr(
        R, "record_roots", lambda: (R.RecordRoot(rel=rel, path=probe),))
    R.clear_caches()
    G.clear_flow_caches()


def _unbind() -> None:
    R.clear_caches()
    G.clear_flow_caches()


def test_d7_a_run_record_promotes_a_write_the_ast_cannot_see(monkeypatch):
    """THE CONTROL for "no Python program writes it" == "the flow does not".

    FORWARD — a path some gate READS, that no step DECLARES, and that no
    ``programs/*.py`` write position resolves, is dropped by ``_w2_population``
    as "externally supplied by design". A run then writes it, its own write
    ledger records it in ``written_never_declared``, and the commit carries
    that ledger. The path is produced, consumed and declared by nobody — W2's
    exact predicate — and the owning step must be charged.
    **This assertion fails against the byte-identical pre-change
    ``matrix_d7_artifact_graph.py``**, which drops the path before it can be
    attributed.

    REVERSE A — the record is REMOVED and nothing else changes: the finding
    disappears and the step's findings are byte-for-byte what they were
    before. Backward compatibility, asserted rather than described; this half
    passes against the pre-change file too, by construction.

    REVERSE B — the record may only ADD. Every finding the step had WITHOUT a
    record it still has WITH one. A binding that could take a finding away
    would be a route around a rule, not a sharpening of one.

    REVERSE C — the promotion is not "any file in the run tree". A second
    file, written by the same run and recorded by the same ledger, but that NO
    gate reads, must NOT become a finding: W2 asks for produced AND consumed,
    and a rule that fires on everything a run writes would charge 335 paths on
    a real run instead of 12.
    """
    candidates = _w2_dropped_candidates()
    assert candidates, (
        "no gate-read, undeclared path is dropped by W2 for lack of a Python "
        "producer, so this control has nothing to exercise. If the flow "
        "genuinely reached that state, delete the record oracle in the same "
        "change rather than leaving an unexercised branch.")

    chosen: Optional[Tuple[str, str]] = None
    for path, owner in candidates:
        with _probe_run_root("d7_record_pick_") as (probe, commit):
            doc = _plant_record(probe, commit, path)
            if any(r.get("rel") == path
                   for r in doc["residual"]["written_never_declared"]):
                chosen = (path, owner)
                break
    assert chosen is not None, (
        f"the emitter reported none of the {len(candidates)} candidate paths "
        f"in its written_never_declared residual, so this control cannot "
        f"exercise the binding. Check step_write_ledger's own exclusions "
        f"(_D7_INPUT_PREFIXES, claimed_patterns) against the candidate list.")
    path, owner = chosen

    with _probe_run_root("d7_record_bind_") as (probe, commit):
        # ---- baseline: the AST alone, exactly today's answer ---------
        _unbind()
        before = tuple(str(f) for f in G.findings_for(owner))
        assert not any(f.path == path for f in G.findings_for(owner)), (
            f"{path} is already charged to step {owner} without any record; "
            f"this control cannot show what the record added")

        doc = _plant_record(probe, commit, path)
        assert any(r.get("rel") == path
                   for r in doc["residual"]["written_never_declared"]), doc[
                       "residual"]["written_never_declared"][:5]

        # A companion write nobody reads — REVERSE C's subject.
        quiet = "phase3/stage3/pnr/d7_probe_unread_artefact.log"
        (probe / quiet).parent.mkdir(parents=True, exist_ok=True)
        (probe / quiet).write_text("nobody reads this\n")
        commit(quiet)
        res = SWL.emit(probe)          # re-emit so the record covers both files
        assert res.get("ok"), res
        commit(R.RECORD_REL)

        # ---- FORWARD -------------------------------------------------
        _bind(monkeypatch, probe)
        assert R.observed_producers_of(path), (
            f"the record does not observe {path!r}; the reader refused it — "
            f"{R.binding_notes()}")
        after = G.findings_for(owner)
        promoted = [f for f in after if f.path == path]
        assert promoted, (
            f"step {owner}'s gate reads {path!r}, no step declares it, and "
            f"the run's own committed write ledger records the run writing it "
            f"({R.observed_producers_of(path)}) — yet W2 still calls it "
            f"'externally supplied by design'. Findings now: "
            f"{[str(f) for f in after]}; record says: {R.binding_notes()}")
        assert promoted[0].rule == G.W2, promoted[0]
        assert promoted[0].producer.startswith(R.OBSERVED_PREFIX), (
            f"an OBSERVED producer must be labelled as one, so a reader can "
            f"tell it from an AST-derived producer: {promoted[0].producer!r}")

        # ---- REVERSE B: the record may only ADD ----------------------
        assert set(before) <= {str(f) for f in after}, (
            f"the record REMOVED a finding step {owner} had without it: "
            f"{sorted(set(before) - {str(f) for f in after})}")

        # ---- REVERSE C: produced AND consumed, not produced alone ----
        assert R.observed_producers_of(quiet), (
            "the companion file is not in the record either, so REVERSE C is "
            "asserting nothing")
        charged = [f for s in F.step_ids() for f in G.findings_for(s)
                   if f.path == quiet]
        assert not charged, (
            f"a file the run wrote that NO gate reads was charged as a "
            f"dimension-7 finding: {charged}. W2 requires produced AND "
            f"consumed; without that this binding would charge every one of a "
            f"real run's 335 undeclared writes.")

        # ---- REVERSE A: no record -> exactly the pre-binding answer --
        (probe / R.RECORD_REL).unlink()
        _bind(monkeypatch, probe)
        assert not R.observed_producers_of(path), R.binding_notes()
        assert tuple(str(f) for f in G.findings_for(owner)) == before, (
            "a run tree with no write record must be decided exactly as it "
            "was before this binding existed")
    _unbind()


def test_d7_a_record_is_a_claim_about_the_past_not_evidence_about_today(
        monkeypatch):
    """The three evidence rules, re-applied live, each with its own reverse.

    The record says a run wrote a path. That is a statement about the past.
    Before it may promote anything the artefact is re-verified from ``lstat``
    RIGHT NOW, because a record that outlived its artefact would let a
    dimension charge a step on the strength of a JSON file:

      * a SYMLINK is not evidence of a write — an alias is not content;
      * a ZERO-BYTE file is not a produced artefact;
      * an UNTRACKED path is a property of one working tree, and ``git clean
        -xdf`` must not be able to change a cell's colour (#527).

    Each is asserted against a record that DOES name the path — the emitter is
    re-run over the good tree first, so the refusal is the live rule's doing
    and not the record's silence — and the reverse case (the good artefact,
    same record) must promote.
    """
    candidates = _w2_dropped_candidates()
    assert candidates, "no candidate path; see the FORWARD control"

    for label, damage in (
        ("deleted", lambda p: p.unlink()),
        ("emptied", lambda p: p.write_text("")),
        ("aliased", lambda p: (p.unlink(),
                               p.symlink_to(Path("..") / "real.txt"))),
    ):
        picked = None
        for path, owner in candidates:
            with _probe_run_root(f"d7_record_{label}_") as (probe, commit):
                doc = _plant_record(probe, commit, path)
                if not any(r.get("rel") == path
                           for r in doc["residual"]["written_never_declared"]):
                    continue
                picked = path
                target = probe / path
                (target.parent / "real.txt").write_text("elsewhere\n")

                # REVERSE: the good artefact + this very record -> promoted.
                _bind(monkeypatch, probe)
                assert R.observed_producers_of(path), (
                    f"[{label}] the reader refused the intact tree, so the "
                    f"refusal below would prove nothing: {R.binding_notes()}")

                damage(target)
                _bind(monkeypatch, probe)
                assert not R.observed_producers_of(path), (
                    f"[{label}] the record promoted {path!r} although the "
                    f"artefact is {label} — a record is a claim about the "
                    f"past, not evidence about today")
                assert R.rejections(), (
                    f"[{label}] the refusal was silent; every rejected "
                    f"residual path must be reported under its own name")
                break
        assert picked, f"[{label}] no usable candidate path"
    _unbind()


def test_d7_an_uncommitted_record_may_not_decide_a_cell(monkeypatch):
    """#527, restated for records — and both directions of it.

    A record can only make a cell REDDER. An untracked one would therefore let
    ``git clean -xdf`` change a verdict and let two checkouts of one commit
    disagree, which is exactly the host-dependence #527 removed from dimension
    3, arriving from the other side. So the rule is not "records never bind";
    it is "a record binds once the repository carries it", and this asserts
    the transition rather than either end of it.
    """
    candidates = _w2_dropped_candidates()
    assert candidates, "no candidate path; see the FORWARD control"

    for path, owner in candidates:
        with _probe_run_root("d7_record_track_") as (probe, commit):
            _start_run(probe)
            target = probe / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("// produced by a shelled-out tool\n")
            commit(path)
            assert SWL.emit(probe).get("ok")          # written, NOT committed
            doc = json.loads((probe / R.RECORD_REL).read_text())
            if not any(r.get("rel") == path
                       for r in doc["residual"]["written_never_declared"]):
                continue

            _bind(monkeypatch, probe)
            assert not R.observed_producers_of(path), (
                "an UNCOMMITTED write record changed a verdict: the colour of "
                "this cell would then depend on whether somebody had run "
                "step_write_ledger in their working tree")
            assert any("not consulted" in n.lower() or "NOT consulted" in n
                       for n in R.binding_notes()), R.binding_notes()

            commit(R.RECORD_REL)
            _bind(monkeypatch, probe)
            assert R.observed_producers_of(path), (
                f"the commit now carries the record and it still does not "
                f"bind: {R.binding_notes()}")
            assert any(f.path == path for f in G.findings_for(owner))
            break
    else:                                              # pragma: no cover
        pytest.fail("no candidate path survived the emitter's own exclusions")
    _unbind()


def test_d7_a_record_whose_emitter_withheld_the_residual_is_refused(monkeypatch):
    """An EMPTY residual and a WITHHELD one are different facts.

    ``step_write_ledger`` refuses to report ``written_never_declared`` when the
    run window is unknown or when the tree's mtimes are flattened — measured,
    a git checkout stamps every tracked file with one mtime, and the published
    cell ``benchmark-data/ic/spm/v1.5.66_gf180mcuD`` has 216 files across 3
    distinct mtimes. Both cases produce an EMPTY residual.

    Because this binding can only ADD, an empty residual is harmless to the
    verdict. It is NOT harmless to the REASON printed beside it: "the run wrote
    nothing undeclared" and "the record declined to answer" would read
    identically. So a withheld record is refused BY NAME, and the note says
    which of the two it was.

    The consequence is stated in ``matrix_d7_write_record``'s docstring and is
    the honest cost of this rule: a record published inside a git working tree
    will normally be refused here.
    """
    with _probe_run_root("d7_record_withheld_") as (probe, commit):
        # No t0 marker and no orchestrator summary -> the window is UNKNOWN and
        # the emitter withholds the D7 residual. Its own doing, not this test's.
        (probe / "phase3" / "stage3" / "pnr").mkdir(parents=True)
        (probe / "phase3" / "stage3" / "pnr" / "openroad.log").write_text("x\n")
        commit("phase3/stage3/pnr/openroad.log")
        assert SWL.emit(probe).get("ok")
        commit(R.RECORD_REL)
        doc = json.loads((probe / R.RECORD_REL).read_text())
        assert not doc["run_window"]["known"], doc["run_window"]
        assert doc["residual"]["written_never_declared_total"] == 0
        assert doc["undetermined"], (
            "the emitter no longer says WHY it withheld; this control rests on "
            "that sentence")

        _bind(monkeypatch, probe)
        assert R.observed_writes() == {}, R.observed_writes()
        note = " ".join(R.binding_notes())
        assert "WITHHELD" in note and "run window is unknown" in note, note

        # REVERSE: give the same tree a t0 marker, re-emit, and it binds.
        _start_run(probe)
        (probe / "phase3" / "stage3" / "pnr" / "openroad.log").write_text("yy\n")
        commit("phase3/stage3/pnr/openroad.log")
        assert SWL.emit(probe).get("ok")
        commit(R.RECORD_REL)
        _bind(monkeypatch, probe)
        assert R.observed_writes(), (
            f"the same tree with a known run window must bind: "
            f"{R.binding_notes()}")
    _unbind()


#: Run roots whose write record this dimension consults. MEASURED 2026-08-06
#: and EMPTY: ``git ls-tree -r --name-only HEAD | grep -c write_ledger.json``
#: is 0 — ``step_write_ledger`` landed the same day and no run tree has been
#: re-published since — so W2's producer oracle is the AST alone and every one
#: of the 63 cells is decided exactly as it was before the binding.
#:
#: The pin is what makes the first published record a LOUD, NAMED event. The
#: per-step promotions this module's docstring tabulates (12 on
#: ``_sky130A_r3_run``, 9 on ``converge_1.5.44_gf180mcuD``, over steps 11, 21,
#: 23, 24, 27, 30, D1, DT2, DT3 and M2) were measured against run trees the
#: commit does not carry. On the day one of them IS carried, this test reddens
#: and each promotion must be re-measured and then either DECLARED in the flow
#: yaml or waived with evidence — not discovered later from a cell that
#: quietly changed colour.
#:
#: THE DAY CAME, AND THE PIN MOVES ONLY NOW THAT THE PROMOTIONS ARE DISPOSED
#: (#1215). ``benchmark-data/ic/spm/v1.10.18_sky130A`` was published carrying
#: ``reports/write_ledger.json``, the test reddened, and it stayed red through
#: four closed PRs because the dispositions were the decision — not the pin.
#: Re-measured rather than inherited from the issue. TWO records are carried,
#: consulted, and between them refuse 273 of their residual paths on live
#: re-verification:
#:
#:     v1.10.18_sky130A   captured 2026-08-09   399 candidates, 144 refused
#:     v1.9.96_gf180mcuD  captured 2026-08-08   394 candidates, 129 refused
#:
#: The A/B against a forced-empty ``observed_writes()`` over all 63 steps
#: leaves **5** promotions on 5 steps, with **0** findings lost — the one
#: direction this binding may never move:
#:
#:     step D1  reports/audit/phase1/expert_parse_track.json   DECLARED
#:     step 23  reports/phase3/sta/post_route_signoff_corner.json  DECLARED
#:     step 24  reports/phase3/dynamic_ir.json                 DECLARED
#:     step 27  reports/phase3/si_mcf_sta.json                 DECLARED
#:     step 34  reports/phase3/cmp_fill_emit.json              WAIVED
#:
#: Five, not the seven the issue measured against a different pair of roots:
#: step 11's ``dft/coverage.yml`` and M2's ``L21_POWER_INTENT.json`` were
#: declared separately before this change, and the second root was withdrawn
#: and later re-published from the run's own later capture (#1529).
#:
#: The four DECLARED are named in ``flow/phase1_phase2_phase3.yaml`` on the
#: step that PRODUCES them, each with its blast radius measured by
#: ``flow_compliance_check.check_step`` over the manifest run roots — on a
#: fresh copy per arm, because ``check_step`` runs the gate and the gate
#: writes the artefact, so two arms sharing one tree is not an A/B. Each is
#: also recorded PRODUCED_BY_RUN in ``matrix_d3_output_manifest.json``,
#: because the yaml half alone is a HALF FIX that relocates the red into
#: dimension 3 rather than removing it (measured: d7 6 -> 1, d3 6 -> 10).
#: Step 34 is WAIVED instead, on the measured fact that nothing reads it: its
#: apparent consumer is ``metal_fill_emit``'s own default-output constant,
#: counted as a read by :func:`matrix_d7_artifact_graph._gate_consumers`.
#:
#: The pin therefore names a population whose every promotion has a
#: disposition. It is BOOKKEEPING, deliberately last, and it cannot be used as
#: evidence that the dispositions happened —
#: :func:`test_d7_the_write_record_population_is_named_root_by_root` asserts
#: both halves of the invariant so that a pin naming a root which contributes
#: nothing is as loud as a population that grew quietly.
RECORD_BOUND_ROOTS: Tuple[str, ...] = (
    "benchmark-data/ic/spm/v1.10.18_sky130A",
    "benchmark-data/ic/spm/v1.9.96_gf180mcuD",
)


class _FakeObservation:
    """The one field :func:`pin_complaints` reads off an observation."""

    def __init__(self, root: str) -> None:
        self.root = root


def pin_complaints(pinned, measured, observed, notes):
    """Everything wrong with the pin, as SENTENCES. Empty means clean.

    A pure predicate over the four things the pin is a claim about, taking
    them as arguments rather than reading :mod:`matrix_d7_write_record`
    itself, so the assertion over the SHIPPED tree and the paired guards below
    run the exact same code. A guard exercising a private copy of this logic
    would prove only that the copy works — the failure mode
    ``test_flow_declares_no_output_twice`` names for the same reason.

    *observed* is ``observed_writes()``: ``{path: (Observation, ...)}``, or
    ``None`` when the reader could not answer at all.
    """
    out = []
    pinned_set, measured_set = set(pinned), set(measured)
    if measured_set != pinned_set:
        out.append(
            f"the set of run roots whose write record decides this dimension "
            f"changed.\n  measured: {sorted(measured_set)}\n"
            f"  pinned:   {sorted(pinned_set)}\n"
            f"  per root: {list(notes)}\n"
            f"Every promotion count in this module's docstring was measured "
            f"against the pinned set. Re-measure them, then move the pin — a "
            f"population that grows quietly is how a dimension stops "
            f"describing what it measures.")
    if not notes or not all(n and n.strip() for n in notes):
        out.append(
            "the reader published no reason at all; a degrade to the "
            "pre-binding behaviour must never be silent")
    if not pinned_set:
        if observed:
            out.append(
                f"no root is bound, yet the observation index is non-empty: "
                f"{sorted(observed)[:5]}")
        return out
    # THE OTHER HALF, which had never been written because the population had
    # always been empty (#1215). Without it, moving the pin trades one
    # unasserted state for another: `measured` is derived from
    # `observed_writes() is not None`, and `{} is not None` is True — so a
    # binding that went INERT (records stop being read, or every observation
    # is refused) would still report every root as bound and this test would
    # still pass, while the pin went on claiming that a named root decides
    # this dimension and nothing decided it.
    if not observed:
        out.append(
            f"the pin names {sorted(pinned_set)}, yet the binding observed "
            f"NOTHING at all. A pinned population with an empty observation "
            f"index is the pre-binding behaviour wearing the binding's "
            f"name.\n  per root: {list(notes)}")
        return out
    contributing = {o.root for obs in observed.values() for o in obs}
    if contributing != pinned_set:
        out.append(
            f"a pinned root must CONTRIBUTE, not merely load.\n"
            f"  pinned:       {sorted(pinned_set)}\n"
            f"  contributing: {sorted(contributing)}\n"
            f"  silent:       {sorted(pinned_set - contributing)}\n"
            f"  unpinned:     {sorted(contributing - pinned_set)}\n"
            f"A root that loads and then promotes nothing is "
            f"indistinguishable here from one that was never consulted, "
            f"which is the state this pin exists to make loud.")
    return out


@needs_corpus
def test_d7_the_write_record_population_is_named_root_by_root():
    """Backward compatibility, stated rather than assumed.

    "A run with no record keeps today's behaviour" is only honest if a reader
    can see WHICH runs those are and WHY. This asserts the pinned population
    and, for every root, that the reader returns a SENTENCE — no record,
    untracked, wrong schema, withheld residual — so a degrade to the
    pre-binding behaviour is never silent. Since #1215 it also asserts the
    NON-EMPTY half: a pinned root that contributes nothing is as loud as a
    population that grew quietly.
    """
    _unbind()
    observed = R.observed_writes()
    measured = tuple(sorted(
        r.label for r in R.record_roots() if observed is not None
        and R._load(r)[0] is not None))
    assert pin_complaints(
        RECORD_BOUND_ROOTS, measured, observed, R.binding_notes()) == []


def test_the_pin_FIRES_when_the_binding_goes_inert():
    """PAIRED GUARD, and the reason the non-empty half exists at all.

    The state: the records still load, so every pinned root is `measured`,
    but the binding produces no observation whatsoever. Before #1215 this was
    invisible — `{} is not None` is True, `measured` still equalled the pin,
    and the test passed while nothing decided the dimension.
    """
    pinned = ("benchmark-data/ic/spm/v1.10.18_sky130A",)
    complaints = pin_complaints(pinned, pinned, {}, ("consulted",))
    assert complaints, "an inert binding must not read as a bound one"
    assert "observed NOTHING at all" in complaints[0]


def test_the_pin_FIRES_when_a_pinned_root_contributes_nothing():
    """PAIRED GUARD: the pin may not name a root that promotes nothing.

    Two roots load and only one is ever the source of an observation. The
    silent one is named, so it cannot be mistaken for a root that was simply
    quiet this time.
    """
    pinned = ("root/loud", "root/silent")
    observed = {"reports/x.json": (_FakeObservation("root/loud"),)}
    complaints = pin_complaints(pinned, pinned, observed, ("consulted",))
    assert complaints, "a pinned root that contributes nothing must be loud"
    assert "root/silent" in complaints[0] and "silent:" in complaints[0]


def test_the_pin_FIRES_on_an_unpinned_root_that_contributes():
    """PAIRED GUARD, the other direction: growth must stay loud.

    The half that already existed, re-proved through the shared predicate so
    that refactoring the assertion cannot have quietly dropped it.
    """
    complaints = pin_complaints(
        (), ("benchmark-data/ic/spm/v1.10.18_sky130A",), {}, ("consulted",))
    assert complaints, "a population that grew must not read as unchanged"
    assert "changed" in complaints[0]


def test_the_pin_is_SILENT_on_a_healthy_binding():
    """The other half of every guard above: it must not fire on the good state.

    Without this, all three guards could be satisfied by a predicate that
    complains unconditionally — a check that always fires measures nothing.
    """
    pinned = ("root/loud",)
    observed = {"reports/x.json": (_FakeObservation("root/loud"),)}
    assert pin_complaints(pinned, pinned, observed, ("consulted",)) == []


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
    return G.na_precondition(step_id)


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if _waiver_for(step_id) is not None:
        return "WAIVED"
    return "ENFORCED"


# ══════════════════════════════════════════════════════════════════════
# THE AUDITOR MAY NOT AUTHOR ITS OWN EVIDENCE
#
# Dimension 7 closes cells by DECLARING an artefact. That only means anything
# if the declaration is answered by the run. On 2026-07-28 a change to
# `flow_compliance_check.check_step` suppressed the early MISSING return for
# any step ALL of whose declared outputs are its own gate's `--json` targets,
# so the gate ran, wrote the declared file, and a post-gate probe accepted THAT
# FILE as the evidence the step was done. MEASURED on a copy of
# benchmark-data/ic/ibex: step 8 (SDC validation — a step no dimension-7 work
# touched) went from a correct MISSING to PASS on
# `reports/phase2/sdc_check.json`, a path the audit itself had just created and
# which 12 other tracked roots really do carry. No test in the 151-file suite
# noticed. These two do.
# ══════════════════════════════════════════════════════════════════════
_SELF_EVIDENCE_BODY = "d7 self-evidence fixture\n"


def _steps_by_self_produced_share():
    """``(all_self, partial)`` — steps whose declared outputs its OWN gate writes.

    ``all_self``  EVERY declared entry is a `--json` target of this step's gate.
    ``partial``   at least one is, and at least one is not.
    Derived live from the yaml through the production `_gate_json_targets`, so
    a yaml edit moves a step between the buckets instead of rotting a list.
    """
    all_self: List[Dict[str, Any]] = []
    partial: List[Dict[str, Any]] = []
    for sid in F.step_ids():
        step = F.step_by_id(sid)
        outs = list(step.get("required_outputs") or [])
        if not outs or not step.get("gate"):
            continue
        targets = FCC._gate_json_targets(step)
        self_written = [o for o in outs if o in targets]
        if not self_written:
            continue
        (all_self if len(self_written) == len(outs) else partial).append(step)
    return all_self, partial


def _seed_conditions(project: Path, step: Dict[str, Any]) -> None:
    """Satisfy the step's ``condition.files_exist`` so check_step reaches outputs.

    An unsatisfied condition returns SKIPPED-CONDITION *before* required_outputs
    is read, and a fixture that graded that branch would be measuring the
    condition and calling it a dimension-7 result.
    """
    cond = (step.get("condition") or {}).get("files_exist") or []
    for pat in cond:
        rel = pat.replace("*", "d7").replace("?", "d")
        p = project / rel
        for anc in reversed([p.parent] + list(p.parent.parents)):
            if anc.is_file():
                anc.unlink()
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(_SELF_EVIDENCE_BODY)


def test_a_step_whose_gate_is_its_only_producer_stays_missing():
    """check_step must not answer "was it produced?" with a file it produced.

    The tree holds the step's conditions and NONE of its declared outputs. The
    honest verdict is MISSING and the honest side effect is none: the audit has
    no way to learn that the RUN produced the artefact, so it may not say it
    did. Reintroducing the withdrawn `_gate_is_sole_producer` exemption makes
    both assertions fail — the status becomes the gate's own verdict and the
    declared file appears on disk, written by this test's own audit.
    """
    all_self, _partial = _steps_by_self_produced_share()
    # THE FLOOR. With an empty population every loop below runs zero times and
    # a green result would mean nothing.
    assert all_self, (
        "no step in the flow declares outputs that are ALL its own gate's "
        "`--json` targets, so this test asserts nothing. If the flow genuinely "
        "has no such step any more, delete this test in the same change."
    )
    for step in all_self:
        sid = step["id"]
        outs = list(step["required_outputs"])
        tmp = Path(tempfile.mkdtemp(prefix="d7_selfevidence_"))
        try:
            project = tmp / "proj"
            project.mkdir()
            _seed_conditions(project, step)
            result = FCC.check_step(project, step, {})
            assert result.status == "MISSING", (
                f"step {sid} declares {outs}, every one of which only its own "
                f"gate writes, and NONE of them was on disk when the audit "
                f"began — yet check_step returned {result.status!r} with "
                f"evidence {list(result.evidence)!r}. An auditor may not "
                f"certify a step on an artefact it created during its own run."
            )
            left = [o for o in outs if (project / o).exists()]
            assert not left, (
                f"step {sid}: the audit created its own declared output(s) "
                f"{left} in the project it was auditing. Whatever verdict was "
                f"reached, the next audit of this tree will read them as run "
                f"evidence."
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def test_self_certified_evidence_is_named_and_refusable():
    """The PARTIAL case: credited by default, but never silently.

    A step with some real evidence does not hit the early MISSING return, so
    its gate runs and writes the declared `--json` output the run never made.
    That credit is kept — only four of the flow's declared-and-self-written
    artefacts have any producer outside their own gate, so refusing by default
    would fail runs that are not defective — but it is now NAMED on the step
    line, and `--strict-audit-evidence` refuses it. Both directions are
    asserted here so neither can quietly stop working.
    """
    _all_self, partial = _steps_by_self_produced_share()
    assert partial, (
        "no step declares a MIX of self-written and externally-written "
        "outputs, so this test asserts nothing; delete it in the same change "
        "that removes the last such step."
    )
    checked = 0
    for step in partial:
        sid = step["id"]
        outs = list(step["required_outputs"])
        targets = FCC._gate_json_targets(step)
        self_written = sorted(o for o in outs if o in targets)
        others = [o for o in outs if o not in targets]
        tmp = Path(tempfile.mkdtemp(prefix="d7_selfevidence_partial_"))
        try:
            project = tmp / "proj"
            project.mkdir()
            _seed_conditions(project, step)
            for entry in others:
                for alt in F.split_any_of(entry):
                    rel = alt.replace("**/", "d7deep/").replace("*", "d7")
                    p = project / rel
                    for anc in reversed([p.parent] + list(p.parent.parents)):
                        if anc.is_file():
                            anc.unlink()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(_SELF_EVIDENCE_BODY)
                    break
            lenient = FCC.check_step(project, step, {})
            created = [o for o in self_written if (project / o).exists()]
            if not created:
                # This step's gate did not write its declared `--json` target
                # on this fixture (a conditional clause, or the program
                # refused). There is nothing self-certified to grade; the next
                # step may still have something. Never counted as a pass.
                continue
            checked += 1
            named = [r for r in lenient.reasons
                     if "SELF-CERTIFIED EVIDENCE" in r]
            assert named, (
                f"step {sid}: the audit created {created} and the report never "
                f"said so — reasons were {list(lenient.reasons)!r}"
            )
            for rel in created:
                assert any(rel in r for r in named), (
                    f"step {sid}: {rel} was created by the audit but the "
                    f"SELF-CERTIFIED EVIDENCE line does not name it: {named!r}"
                )
            # And the strict form must actually refuse it, on a FRESH tree —
            # the lenient run above left the file behind, which is precisely
            # what makes the default non-idempotent.
            shutil.rmtree(project)
            project.mkdir()
            _seed_conditions(project, step)
            for entry in others:
                for alt in F.split_any_of(entry):
                    rel = alt.replace("**/", "d7deep/").replace("*", "d7")
                    p = project / rel
                    for anc in reversed([p.parent] + list(p.parent.parents)):
                        if anc.is_file():
                            anc.unlink()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(_SELF_EVIDENCE_BODY)
                    break
            strict = FCC.check_step(project, step, {},
                                    strict_audit_evidence=True)
            assert strict.status not in ("PASS", "VACUOUS_PASS"), (
                f"step {sid}: --strict-audit-evidence still resolved to "
                f"{strict.status!r} while its declared output(s) {created} "
                f"existed only because this audit wrote them"
            )
            left = [rel for rel in created if (project / rel).exists()]
            assert not left, (
                f"step {sid}: --strict-audit-evidence left its own output "
                f"{left} in the audited tree, so a second strict audit would "
                f"read it as run evidence and report PASS"
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    assert checked, (
        "no partial step's gate wrote its declared `--json` target on the "
        "synthesized fixture, so neither the advisory nor the strict refusal "
        "was exercised — this test measured nothing"
    )


# ──────────────────────────────────────────────────────────────────────
# vibe-ic#1265 — the write-detector and the ATOMIC writers
# ──────────────────────────────────────────────────────────────────────
#: The three shapes an atomic helper call actually arrives in. All three name
#: the destination FIRST, which is what makes them invisible to a detector that
#: only knows `p.write_text(...)` — there the path is the ATTRIBUTE VALUE, here
#: it is `args[0]`.
_ATOMIC_CALL_SHAPES = '''
from pathlib import Path
import _atomic_output
import _atomic_artefact
import _atomic_artefact as _aa
from _atomic_output import atomic_write_text

def a(project):
    _atomic_output.atomic_write_text(project / "reports" / "alpha.json", "{}")

def b(project):
    _atomic_artefact.atomic_write_text(project / "reports" / "beta.json", "{}")

def c(project):
    atomic_write_text(project / "reports" / "gamma.json", "{}")

def d(project):
    (project / "reports" / "delta.json").write_text("{}")

def e(project):
    helper_write(project / "reports" / "epsilon.json", "{}")

def f(project):
    _atomic_artefact.write_text(project / "reports" / "zeta.json", "{}")

def g(project):
    _aa.write_json(project / "reports" / "eta.json", {})

def h(project):
    (project / "reports" / "theta.json").write_text(
        project / "reports" / "NOT_A_DESTINATION.json")

def i(project):
    _aa.publish(project / "reports" / "omega.json", "{}")
'''


def _detected(src: str) -> set:
    import ast as _ast
    return {"/".join(t) for t in G._collect_writes(_ast.parse(src))}


def test_d7_the_write_detector_sees_an_atomic_write(monkeypatch):
    """A program converted to an atomic writer must still read as a WRITE.

    WHY THIS EXISTS (vibe-ic#1265). The detector recognised `open()`,
    `p.open("w")`, `p.write_text` and `p.write_bytes` — every one of which
    carries the path as the ATTRIBUTE VALUE. An atomic helper carries it as
    `args[0]` instead, so the moment a program was converted the delegate walk
    saw NO WRITE at all, and dimension 7 stopped being able to say that the
    program produces its declared output. MEASURED on the byte-identical
    pre-change file: all three atomic shapes below are MISSED and only
    `delta.json` is seen.

    That is not a hypothetical conversion. vibe-ic#1241's group (d) is
    SEVENTEEN programs to be routed through exactly this call, and each one
    would have gone silent here.

    THE VOCABULARY IS MODULE-AGNOSTIC ON PURPOSE, and this test pins that
    rather than describing it: `_atomic_output.atomic_write_text` (#1265) and
    `_atomic_artefact.atomic_write_text` (#1110) are two open candidates for
    the same primitive and the arbitration is not settled. A detector keyed on
    the winning module would report NO WRITE for every program converted
    through the other name — the same defect, one module over — so both are
    asserted, together with the bare `from ... import` form.
    """
    seen = _detected(_ATOMIC_CALL_SHAPES)
    for want in ("reports/alpha.json",      # module-qualified, _atomic_output
                 "reports/beta.json",       # module-qualified, _atomic_artefact
                 "reports/gamma.json"):     # bare, after `from ... import`
        assert want in seen, (
            f"{want} was written by an atomic helper and the detector did not "
            f"see it; d7 would report this program as producing nothing. "
            f"detected={sorted(seen)}")


def test_d7_the_plain_write_shapes_still_resolve(monkeypatch):
    """PAIRED GUARD, direction one: the old shapes are not traded away.

    Widening a detector by rewriting how it resolves a call is exactly where
    the previously-working half gets dropped, so the plain attribute form is
    asserted in the same fixture that exercises the new one.
    """
    assert "reports/delta.json" in _detected(_ATOMIC_CALL_SHAPES)


def test_d7_a_first_argument_is_not_a_write_on_its_own(monkeypatch):
    """PAIRED GUARD, direction two: the rule is a VOCABULARY, not "args[0]".

    The cheap way to make the shapes above resolve is to treat the first
    argument of every call as a destination. That would report a write for any
    function that merely RECEIVES a path — `_load(p)`, `_check(p)`, a helper
    that reads it — and dimension 7 would start charging steps for artefacts
    nothing produces. `helper_write` is not in `_ATOMIC_WRITERS`, so its
    argument must not be counted, and this test fails the moment the
    implementation stops consulting the set.
    """
    seen = _detected(_ATOMIC_CALL_SHAPES)
    assert "reports/epsilon.json" not in seen, (
        "a call NOT in the atomic vocabulary had its first argument counted "
        f"as a write — the rule has become 'args[0]', not a vocabulary. "
        f"detected={sorted(seen)}")
    assert "helper_write" not in G._ATOMIC_WRITERS


def test_d7_the_write_detector_sees_a_SHADOWING_atomic_write(monkeypatch):
    """vibe-ic#1452 — the drop-in atomic writers must read as writes too.

    #1265 taught this detector the atomic helpers whose names are NEW
    (`atomic_write_text`), by name alone. It did not teach it the ones that
    KEEP the name of the `Path` method they replace and move the destination
    to the first argument — `_atomic_artefact.write_text(p, data)`, whose own
    docstring says it is "signature-compatible on purpose" so that converting
    a call site is "deleting `.write_text(` and calling this instead".

    That shape hit the pre-existing `elif fn.attr in ("write_text",
    "write_bytes")` branch, which reads the destination off the RECEIVER — and
    the receiver is the module alias `_aa`, which resolves to no path at all.
    So the write silently vanished. MEASURED on the byte-identical pre-change
    tree: 32 such call sites across 8 programs, and 21 declared artefact paths
    that no oracle could attribute to any producer, among them
    `eco_trigger_decision.json` — which `phase3_one_shot_runner` writes on the
    line above the one that appends it to `written`.

    This is #1265's defect recurring through the OTHER conversion route, which
    is exactly what that row's own comment predicted would happen if the
    vocabulary were keyed on the wrong thing.
    """
    seen = _detected(_ATOMIC_CALL_SHAPES)
    for want in ("reports/zeta.json",   # module-qualified drop-in write_text
                 "reports/eta.json"):   # module-qualified drop-in write_json
        assert want in seen, (
            f"{want} was written by a drop-in atomic helper and the detector "
            f"did not see it; d7 would report this program as producing "
            f"nothing. detected={sorted(seen)}")


def test_d7_a_shadowing_writer_does_not_steal_the_receiver_form(monkeypatch):
    """PAIRED GUARD: when the RECEIVER is the path, it stays the destination.

    `write_text` names two different calls — the `Path` method, whose
    destination is the receiver, and the drop-in helper, whose destination is
    `args[0]`. Reading `args[0]` unconditionally would make every
    `p.write_text(payload)` report a write to whatever it PASSES, which for a
    program that writes one artefact naming another is a producer attributed
    to the wrong path. `h()` in the fixture writes `theta.json` and passes a
    second artefact-shaped path as CONTENT; only the first is a write.
    """
    seen = _detected(_ATOMIC_CALL_SHAPES)
    assert "reports/theta.json" in seen, (
        f"the plain Path.write_text form was traded away. detected={sorted(seen)}")
    assert "reports/NOT_A_DESTINATION.json" not in seen, (
        "a path passed as CONTENT to Path.write_text was counted as a write — "
        f"the receiver stopped winning. detected={sorted(seen)}")


def test_d7_the_shadowing_rule_is_a_vocabulary_too(monkeypatch):
    """PAIRED GUARD, direction two: not "any attribute call's first argument".

    The cheap way to make the shapes above resolve is to count `args[0]` for
    every attribute call whose receiver is not a path. That would charge a
    program for every helper it merely HANDS a path to. `_aa.publish(...)` is
    not in `_SHADOWING_ATOMIC_WRITERS`, so it must not be counted, and this
    fails the moment the implementation stops consulting the set.
    """
    seen = _detected(_ATOMIC_CALL_SHAPES)
    assert "reports/omega.json" not in seen, (
        "an attribute call NOT in the shadowing vocabulary had its first "
        f"argument counted as a write. detected={sorted(seen)}")
    assert "publish" not in G._SHADOWING_ATOMIC_WRITERS


def test_d7_both_write_walks_share_one_atomic_vocabulary(monkeypatch):
    """The module carries TWO traversals that must agree about what a write is.

    `_collect_writes` and the delegate walk inside `flag_value_is_written` are
    separate copies of the same shapes — the second exists to answer "does the
    program this gate names write its --json target". They are bound to ONE
    frozen set so the vocabulary cannot drift even though the traversals can;
    asserting the shared name is what keeps a future edit from teaching one
    walk and silently leaving the other blind, which is the failure this whole
    row is about.
    """
    assert isinstance(G._ATOMIC_WRITERS, frozenset) and G._ATOMIC_WRITERS
    # vibe-ic#1452 — the drop-in writers are a SECOND vocabulary with the same
    # obligation, and it is asserted here rather than in a test of its own so
    # that the next set added to this module has an obvious place to be named.
    assert (isinstance(G._SHADOWING_ATOMIC_WRITERS, frozenset)
            and G._SHADOWING_ATOMIC_WRITERS)
    src = Path(G.__file__).read_text(encoding="utf-8")
    assert src.count("_SHADOWING_ATOMIC_WRITERS") >= 3, (
        "the drop-in atomic vocabulary is referenced fewer than three times "
        "(its definition plus both walks), so one traversal is not consulting "
        "it and can go blind on its own")
    assert src.count("_ATOMIC_WRITERS") >= 3, (
        "the atomic vocabulary is referenced fewer than three times "
        "(its definition plus both walks), so one traversal is not consulting "
        "it and can go blind on its own")
