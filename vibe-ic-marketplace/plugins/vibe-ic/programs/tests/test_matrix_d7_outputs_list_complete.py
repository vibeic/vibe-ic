"""DIMENSION 7 of the 63x8 matrix — is the ``required_outputs`` LIST complete?

    "Does the step emit an artefact it never declares?"

Not "is the declared file there" (dimension 3). The disease this dimension
exists to catch is quieter: **a step produces a load-bearing artefact that
nothing declares, so nothing checks it exists, so its absence is invisible.**
No gate goes red. A downstream checker simply reads a file that is not there
and takes its "absent" branch, and the run reports PASS.

One cell per flow step, 63 in all, each ending in exactly one of three
machine-checkable states:

  ENFORCED  the live predicate runs and passes            59
  WAIVED    ``xfail(strict=True)`` with an evidence-backed reason   3
  NA        the NA precondition is asserted LIVE           1

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
"""
from __future__ import annotations

from collections import Counter

import pytest

import matrix_d7_artifact_graph as G
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers
from matrix_63x8.cells import cells_for

DIM = 7

#: Number of entries in ``matrix_d7_artifact_graph.RESOLUTION_LIMITS``, pinned
#: as measured 2026-07-27. See ``test_resolution_limits_are_declared``.
RESOLUTION_LIMITS_AS_MEASURED = 5

# ──────────────────────────────────────────────────────────────────────
# Waivers
# ──────────────────────────────────────────────────────────────────────
#: The local mirror, now EMPTY. It existed only while ``matrix_63x8/waivers.py``
#: was being written by eight concurrently-running agents; the entries have
#: landed centrally and :func:`_waiver_for` prefers the central registry, so
#: emptying it is a no-op at the point of use. A new waiver goes to
#: ``waivers.WAIVERS``, not here.
#:
#: Whatever lives there is a CURRENTLY-REAL, source-verified defect, so the
#: xfail is ``strict=True``: the moment the yaml declares the artefact, the
#: cell XPASSes, the suite goes red, and the waiver must be removed. That is
#: the anti-rot mechanism, not a formality — and it is what forced the seven
#: cells closed on 2026-07-28 to be closed in the flow rather than in a table.
PENDING_WAIVERS: tuple = (
    # EMPTY, and it stays empty. The nine entries this tuple carried are now in
    # ``matrix_63x8.waivers.WAIVERS`` — seven of them CLOSED (the artefact is
    # declared; see the flow yaml's per-entry notes), two NARROWED and living
    # centrally. :func:`_waiver_for` prefers the central registry, so the
    # migration is a no-op at the point of use and a new waiver belongs there,
    # not here.
)

_PENDING_BY_KEY = {w.key: w for w in PENDING_WAIVERS}


def _waiver_for(step_id):
    """The waiver at ``(step, 7)`` — central registry first, local mirror second."""
    central = waivers.waiver_for(step_id, DIM)
    if central is not None:
        return central
    return _PENDING_BY_KEY.get((F.normalize_id(step_id), DIM))


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

    findings = G.findings_for(sid)
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
        assert G.writers_of(finding.path), (
            f"{finding.path} has no producer; the unattributable list is "
            "carrying a phantom"
        )


def test_every_cell_lands_in_exactly_one_state():
    """63 cells; ENFORCED + WAIVED + NA == 63, and no cell is in two states.

    The census is derived live, not written down: a step added to the yaml
    lands here as ENFORCED and this arithmetic keeps holding, while a waiver
    for a step that has stopped failing is caught by its own ``strict=True``.
    """
    cells = cells_for(DIM)
    assert len(cells) == len(F.step_ids()) == 63

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

    assert sum(state.values()) == 63, state
    assert state["NA"] >= 1 and state["ENFORCED"] >= 1, state
    # Waivers must not be the majority strategy: if they ever are, this
    # dimension has stopped enforcing anything and should be redesigned.
    assert state["WAIVED"] < state["ENFORCED"], (
        f"more cells waived than enforced: {dict(state)}"
    )


def test_pending_waivers_meet_the_registry_standard():
    """The local mirror is held to ``waivers.validate()``, not to a lower bar.

    The mirror exists only because the shared registry cannot be edited by a
    sibling agent (matrix_63x8/waivers.py docstring). It must therefore be
    indistinguishable in quality from an entry that lands centrally: real
    step, real dimension, substantive reason, checkable evidence.
    """
    problems = {}
    for waiver in PENDING_WAIVERS:
        found = waivers.validate(waiver)
        if found:
            problems[waiver.label] = found
    assert not problems, problems

    keys = [w.key for w in PENDING_WAIVERS]
    assert len(keys) == len(set(keys)), f"duplicate waiver keys: {keys}"
    assert all(w.dim == DIM for w in PENDING_WAIVERS)

    # A mirrored waiver must name a step that is CURRENTLY failing. A mirror
    # entry for a healthy step would be dead weight the strict xfail cannot
    # catch (a waived-but-passing cell XPASSes, but only if the waiver is
    # actually applied — this catches the case where it is applied to a step
    # that has no findings and no NA either).
    inert = [
        w.label
        for w in PENDING_WAIVERS
        if not G.findings_for(w.step_id) and G.na_precondition(w.step_id) is None
    ]
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
