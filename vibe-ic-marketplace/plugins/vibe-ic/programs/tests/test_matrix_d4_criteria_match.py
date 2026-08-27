"""DIMENSION 4 of the 63x8 coverage matrix — **criteria_match**.

    Does what a step's gate MEASURES match what it CLAIMS to measure?

One test per flow step, 63 of them, each ENFORCED against the live tree,
WAIVED with evidence, or holding an NA precondition. Nothing here reads
``.audit_63x8.json``: the audit is history, the repo is the subject.

====================================================================
THE CEILING — READ THIS BEFORE TRUSTING A GREEN RUN
====================================================================
This module catches **"reads the wrong artefact"**. It does NOT catch
**"reads the right artefact and computes the wrong quantity from it."**
That second class is the more dangerous one and two specimens of it were found
in this very campaign:

  (i)  a via-redundancy screen built its universe from the DEF's *declaration*
       (VIAS) section and reported it as *usage* — right file, right parser,
       wrong section, off by 2,240 vias;
  (ii) a convergence loop read the correct STA database but only ever queried
       setup slack, never slew / cap / fanout — it closed on one axis and
       reported closure on all.

Both would pass every assertion below. A gate that opens ``routed.drc.rpt`` and
then counts the wrong thing inside it is, to this module, indistinguishable
from one that counts the right thing. Deciding that needs a semantic model of
each report format, which is per-gate engineering, not a matrix predicate.

Two narrower blind spots, both measured rather than guessed:

  * **9 of the 122 declared artefacts are grounded ONLY by the gate's own
    declaration** — an argv path, a ``files_exist`` entry, a
    ``condition_files_exist`` entry — with no path in any gate program's code
    resolving them (steps 2 x2, 8, 9, 10, 21, 23, 24, 38; most are the
    ``--json`` audit trail the gate writes rather than reads). For those the
    assertion is yaml-vs-yaml consistency: real, because the two lists are
    written independently and do drift, but weaker than yaml-vs-program. The
    rest are grounded by program code or by a filename-prefix table (1).
    The 9 that were grounded by NOTHING when this module was written are now
    grounded by program code: each one's gate was changed to open the artefact
    its step declares. See the ``LOCAL_WAIVERS`` block for the per-step fix.
  * **Grounding proves the gate is WIRED to the artefact, not that it reads it
    substantively.** ``analog_a8_*`` opening a 500-byte non-GDS file and
    calling it a GDS is grounded here and still a defect. That is dimension
    4's shared border with the substance question, and it is not crossed.

What this module DOES decide, live, on every run:

  1. **The gate's declared invocation is one the program accepts.** Each gate
     command is run verbatim; if the program's own parser rejects it (argparse
     ``rc=2`` + a ``prog: error:`` usage line), the clause measures nothing —
     and ``flow_compliance_check._check_program_exit_zero`` maps ``rc == 2``
     onto ``VACUOUS_PASS``, so it measures nothing *and banks a pass*. The one
     live instance this module found — step 2, ``rtl_bug_report_schema_check``
     declaring ``--out`` against a yaml that passes ``--json`` — is fixed in
     the program; this clause is what keeps the next one from shipping.
  2. **Every artefact the step declares is named somewhere the gate can reach.**
     A step that declares ``reports/phase3/em.json`` while its gate searches
     ``*em*.rpt`` only is measuring something adjacent to its own claim.
  3. **A files-only gate checks EVERY ONE of the step's own declared
     deliverables** (steps 1, 12) — entry by entry, because ``required_outputs``
     is ALL-of-N across entries and any-of only inside one. Until 2026-08-06
     this clause asked only whether the gate reached ANY declared alternative,
     which no step with at least one checked artefact could fail; step 1
     declares four alternatives, its gate checks two, and the cell was green.
     A declared entry that no gate clause reads is now a failure, while an
     entry satisfied by one of its ``" OR "`` spellings still passes. See
     ``_assert_files_only_gate_matches_claim`` for the consumer line ranges
     that define each half of that grammar.
  4. **P0's prose claims match the live structural-gate registry** — P0 has no
     ``gate`` key at all, so the NA precondition is asserted and the claim its
     ``notes`` make about ``_STRUCTURAL_RTL_GATES`` is checked against the
     imported module.

See ``matrix_d4_probe`` for how each measurement is taken and why the obvious
cheaper versions (scan ``--help``, substring-match paths, follow imports to
depth 3) were measured and rejected.

====================================================================
SELF-CHECKS
====================================================================
Six non-cell tests at the bottom keep the measurements honest: that the CLI
probe can report a rejection; that the path matcher discriminates the
same-basename/different-directory shape (the step-40 defect); that the
files-only branch separates an any-of SPELLING from a separate DELIVERABLE, in
both directions; that the one excluded module really is a shared path
catalogue; that every waiver is evidence-backed; and that all 63 cells carry
exactly one disposition. (This paragraph said "Three" while five existed — the
count is now derived from the file and must be re-stated when one is added.)
"""
from __future__ import annotations

import copy
import re
import shlex
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pytest
import yaml

import matrix_d4_probe as P
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W
from matrix_63x8.cells import cells_for

DIM = 4

#: The cells this dimension waives, PINNED as an exact set. EMPTY since
#: 2026-07-28: all ten dimension-4 waivers were closed by fixing the gates that
#: were not reading what their step declares. Pinned rather than floored so a
#: waiver-free dimension is a recorded fact instead of an empty loop reporting
#: green — see ``test_d4_selfcheck_waivers_are_evidence_backed``.
WAIVED_CELLS_PINNED: frozenset = frozenset()


# ─────────────────────────────────────────────────────────────────────
# Waivers — ONE registry, the one that is consumed
# ─────────────────────────────────────────────────────────────────────
# This module used to carry a `LOCAL_WAIVERS` mirror of its ten dimension-4
# waivers, added while eight agents shared one worktree and a concurrent edit to
# `matrix_63x8.waivers.WAIVERS` could lose an entry. The orchestrator has since
# landed all ten centrally, so `_waiver_for` read the central copy and ignored
# the local one — an edit to the mirror changed nothing a reader ever saw.
#
# #527 deleted the same structure from dimension 3 after its two copies were
# found telling different stories about one accepted gap. The mirror is deleted
# rather than re-synchronised: a waiver is a public admission, and it can have
# exactly one text.
#
# THE REGISTRY NOW HOLDS NO DIMENSION-4 ENTRY AT ALL, and that is the finding.
# All ten of this dimension's waivers were
# closed by fixing what they waived, not by relaxing anything here — the ten
# gates now read the artefacts their steps declare, and every one of the fixes
# is falsifiable (an input that trips it, with a non-zero rc). ``strict=True``
# is what made that the only way through: a fix without a deletion reports
# XPASS -> FAILED, and a deletion without a fix reports FAILED.
#
#   step 2   rtl_bug_report_schema_check accepts the flow's own `--json`
#            (it declared `--out` only, so argparse exited 2 and
#            flow_compliance_check credited rc==2 as VACUOUS_PASS)
#   step 9   synth_netlist_check binds stats.json/area.rpt to the netlist
#            under audit by CONTENT — the emitter records the measured
#            netlist's digest and the gate hashes the file it was handed —
#            plus the zeroed-measurement refusal. (Not by mtime and not by
#            filename: an mtime ordering is created by the runner on every
#            re-synthesis and a filename cannot tell a byte-identical alias
#            from a different design. Both proxies were tried and both were
#            the wrong quantity; see the block comment in the program.)
#   step 11  dft_signoff_check requires the at-speed plan its ENGINE_LIMITED
#            tier calls "documented" to exist, at the path the flow declares
#            when the record names none — the requirement is not opt-in by
#            the document under audit
#   step 14  yosys_script_template_check reads the handoff netlist, not only
#            the recipe that claims to write it; staleness is compared only
#            against scripts whose own write_verilog names that netlist, so a
#            later-phase script that merely CONSUMES it is not evidence
#   step 25  eda_report_audit:em opens em.json and refuses a formatted zero
#   step 28  perc_signoff_check cross-checks the .rpt and the sign-off memo
#            against perc_equivalent.json
#   step 32  postroute_timing_repair_audit reads postroute_timing_repair_decision.json before honouring
#            no_repair_needed.flag, through a path composed FROM the declared
#            literal; and the step's gate condition was widened so the audit
#            actually RUNS on the no-repair branch, which is the only branch the
#            contradiction can appear on
#   step 33  eda_report_audit:power opens power.json and corroborates its
#            source and analysis_mode against the report
#   step 39  fpga_on_board_attestation_check requires the attested bitstream
#            to be the FINAL one step 39 declares
#   P0       cdc_async_input_check is registered in _STRUCTURAL_RTL_GATES, so
#            P0's prose about the audit's gates[] array is now true
# ──────────────────────────────────────────────────────────────────────


def dim_waivers() -> Tuple[W.Waiver, ...]:
    """This dimension's waivers, from the one registry that is consumed."""
    return tuple(W.waivers_for_dim(DIM))


def _waiver_for(step_id) -> Optional[W.Waiver]:
    """The waiver for this cell, or ``None``. Single source: the registry."""
    return W.waiver_for(step_id, DIM)


def _params():
    """One pytest param per d4 cell, xfail(strict) applied at collection time.

    ``strict=True`` is not a style choice: a waived cell that starts passing
    turns the suite RED on XPASS and forces the waiver's deletion. Without it a
    stale waiver is silent absence wearing a hat.
    """
    out = []
    for cell in cells_for(DIM):
        waiver = _waiver_for(cell.step_id)
        marks = (
            [pytest.mark.xfail(strict=True, reason=waiver.xfail_reason)]
            if waiver is not None
            else []
        )
        out.append(pytest.param(cell, marks=marks))
    return out


# ──────────────────────────────────────────────────────────────────────
# Per-branch predicates
# ──────────────────────────────────────────────────────────────────────
def _exec_clauses(step_id):
    return tuple(
        c
        for c in F.gate_clauses(step_id)
        if c.command is not None and F.program_path(c.program or "") is not None
    )


def _assert_cli_contract(step_id) -> None:
    """Every gate command the yaml declares must be ACCEPTED by its program."""
    violations = P.cli_violations(step_id)
    if not violations:
        return
    lines = []
    for probe in violations:
        if probe.timed_out:
            lines.append(
                f"  `{probe.command}` could not be probed: no exit within "
                f"{P.PROBE_TIMEOUT_S}s, so this clause's CLI contract is "
                f"UNMEASURED rather than proven good"
            )
            continue
        lines.append(
            f"  `{probe.command}`\n"
            f"      -> rc={probe.returncode}, parser said: {probe.parser_error!r}\n"
            f"      -> stderr tail: {probe.stderr_tail}"
        )
    pytest.fail(
        f"step {step_id} / d{DIM} criteria_match: the flow declares "
        f"{len(_exec_clauses(step_id))} executable gate clause(s); "
        f"{len(violations)} of them name an invocation the program itself "
        f"refuses, so the clause measures nothing that the yaml claims:\n"
        + "\n".join(lines)
        + "\n  NOTE: flow_compliance_check._check_program_exit_zero maps rc==2 "
        "onto VACUOUS_PASS, so a rejected invocation is counted as a PASS."
    )


def _assert_artefacts_grounded(step_id) -> None:
    """Every declared artefact must be reachable by the step's own gate."""
    declared = F.required_outputs(step_id)
    if not declared:
        # NA precondition, asserted live: this step genuinely declares no
        # required_outputs, so there is no claimed artefact to compare the
        # gate's reads against. If someone adds one, this fails and the cell
        # is re-evaluated instead of silently staying "covered".
        assert not F.declares_required_outputs(step_id), (
            f"step {step_id} / d{DIM}: required_outputs is DECLARED but empty — "
            f"neither an artefact claim to check nor an honest absence; the "
            f"NA precondition this cell rests on no longer holds"
        )
        return

    ungrounded = [
        (entry, P.nearest_patterns(step_id, entry))
        for entry, hit in P.grounding_report(step_id)
        if hit is None
    ]
    if not ungrounded:
        return

    n_patterns = len(P.code_patterns(step_id)) + len(P.gate_declared_paths(step_id))
    lines = []
    for entry, nearest in ungrounded:
        near = "\n".join(f"        {t}" for t in nearest) or "        (none)"
        lines.append(f"  declared {entry!r}\n      nearest read:\n{near}")
    pytest.fail(
        f"step {step_id} / d{DIM} criteria_match: {len(ungrounded)} of "
        f"{len(declared)} declared required_outputs are named nowhere the gate "
        f"can reach. Gate programs {list(F.gate_programs(step_id))} + their "
        f"direct local imports contribute {n_patterns} distinct read patterns; "
        f"none of them resolves:\n" + "\n".join(lines)
    )


def _assert_files_only_gate_matches_claim(step_id) -> None:
    """A gate with no program must check the step's OWN declared deliverables.

    Steps 1 and 12 gate on file existence alone. The criteria-match question
    for them is whether the paths the gate checks are the artefacts the step
    says it produces — two independently written lists that can and do drift.

    THE UNIT OF OBLIGATION IS THE ENTRY, NOT THE ALTERNATIVE
    -------------------------------------------------------
    This predicate used to flatten ``required_outputs`` into one pool of
    alternatives and then ask only whether the pool intersected the gate::

        alternatives = [alt for e in declared for alt in F.split_any_of(e)]
        covered = [alt for alt in alternatives
                   if any(P.covers(p, alt) for p in checked)]
        assert covered, ...

    Both halves of the yaml's grammar were destroyed by that flattening, and it
    made the branch UNABLE TO GO RED for the defect it exists to catch: ANY ONE
    declared alternative being checked satisfied it. MEASURED on this tree
    before the fix — step 1 declares four alternatives, its gate checks two,
    the remaining two are read by no gate of step 1 at all, and the cell was
    GREEN (``1 passed``).

    The grammar, and where each half is enforced by the real consumer:

      * ACROSS entries the list is **ALL-of-N**. ``flow_compliance_check.py``
        :8966 states it and :8980-:8996 executes it — one ``missing_entries``
        append per unsatisfied ENTRY::

            # EACH declared entry must be satisfied — the list is ALL-of-N ...
            outputs = step.get("required_outputs", [])
            missing_entries: List[str] = []
            for pat in outputs:

        and :9479 demotes a passing gate on the strength of that list::

            if _T.is_done_claim(result.status) and missing_entries:
                result.status = "MISSING"

      * INSIDE one entry ``" OR "`` is **any-of** — the flow's spelling for one
        artefact with several accepted names or locations. Same consumer,
        :8984-:8988, first hit wins and the entry is done::

            for sp in (p.strip() for p in pat.split(" OR ")):
                if _glob_first(project, sp):
                    hit_any = True
                    break

    So the two cases the brief asks to be told apart are told apart by the yaml
    itself, mechanically, with no heuristic:

      "several acceptable spellings of one artefact" = alternatives WITHIN one
      entry, joined by the literal ``" OR "``. Covering any ONE of them covers
      the entry, exactly as the consumer does — failing a step because its gate
      names ``*.sv`` and not also ``*.v`` would be wrong, and does not happen.

      "a separate declared output nobody consumes" = a SEPARATE ENTRY of the
      list, none of whose alternatives any gate path reaches. That is a
      deliverable the step claims and its gate cannot see.

    This is also the rule the EXEC branch of this dimension has always applied:
    ``P.grounding_report`` iterates ``F.required_outputs`` (entries) and
    ``ground()``'s docstring says "grounding ANY alternative grounds the entry
    — that is exactly what ``flow_compliance_check`` does". The files-only
    branch was the only place in dimension 4 holding a step to a weaker
    standard, and it was weaker for no reason other than the step having no
    program to point a static read-closure at.
    """
    checked: List[str] = []
    for clause in F.gate_clauses(step_id):
        checked.extend(clause.files)
    declared = F.required_outputs(step_id)

    assert checked, (
        f"step {step_id} / d{DIM}: gate declares no program and no files_exist "
        f"path, so it measures nothing at all; gate = {F.gate(step_id)!r}"
    )
    assert declared, (
        f"step {step_id} / d{DIM}: gate checks {checked} but the step declares "
        f"no required_outputs, so there is no claim for those checks to match"
    )

    alternatives = [alt for e in declared for alt in F.split_any_of(e)]
    stray = [
        path
        for path in checked
        if not any(P.covers(path, alt) for alt in alternatives)
    ]
    assert not stray, (
        f"step {step_id} / d{DIM} criteria_match: the gate checks {stray}, "
        f"which resolve to none of the {len(alternatives)} artefact(s) the step "
        f"declares ({alternatives}); the gate is measuring something the step "
        f"does not claim to produce"
    )

    # ALL-of-N over ENTRIES, any-of INSIDE one entry. See this function's
    # docstring for the two consumer line ranges that define each half.
    unread = []
    for entry in declared:
        alts = F.split_any_of(entry)
        if not any(P.covers(path, alt) for alt in alts for path in checked):
            unread.append((entry, alts))

    if unread:
        lines = []
        for entry, alts in unread:
            spelling = (
                f"any-of over {list(alts)}"
                if len(alts) > 1
                else "a single path, no ' OR ' alternative"
            )
            lines.append(
                f"  declared entry {entry!r}\n"
                f"      ({spelling}); no path the gate checks resolves any "
                f"alternative of it"
            )
        pytest.fail(
            f"step {step_id} / d{DIM} criteria_match: {len(unread)} of "
            f"{len(declared)} declared required_outputs ENTRIES are read by no "
            f"clause of this step's gate. The gate checks {checked}; the step "
            f"claims to deliver {list(declared)}.\n" + "\n".join(lines) + "\n"
            f"  required_outputs is ALL-of-N across entries "
            f"(flow_compliance_check.py:8966 states it, :8980-:8996 executes "
            f"it, :9479 demotes a passing gate to MISSING on it), so each "
            f"entry above is a SEPARATE deliverable, not an alternative "
            f"spelling of one that is checked. Only ' OR ' INSIDE one entry is "
            f"any-of (same file, :8984-:8988) and an entry satisfied by any "
            f"one of its alternatives is NOT reported here.\n"
            f"  Either the gate is not measuring what the step claims, or the "
            f"step is claiming a deliverable that belongs to another step — "
            f"dimension 4 reports the mismatch and does not choose which side "
            f"is wrong."
        )


_BACKTICKED = re.compile(r"`([A-Za-z_][\w]*)")
_COUNT_CLAIM = re.compile(r"(\d+)\s+(?:[\w-]+\s+){0,3}?gates?\b", re.IGNORECASE)


def _assert_gateless_step_prose_matches_mechanism(step_id) -> None:
    """P0 declares no ``gate``; check the claim its prose makes instead.

    The NA precondition (no ``gate`` key, no ``required_outputs``) is asserted
    first, so if someone gives P0 a real gate this cell self-invalidates. What
    remains is a genuine criteria-match question: P0's verdict is emitted by
    ``flow_compliance_check._run_structural_rtl_gates`` over
    ``_STRUCTURAL_RTL_GATES``, and the step's own ``name``/``notes`` make
    checkable claims about that registry.
    """
    assert not F.has_gate(step_id), (
        f"step {step_id} / d{DIM}: this cell's NA precondition was 'the step "
        f"declares no gate', but it now declares {F.gate(step_id)!r} — "
        f"re-evaluate the cell against the gate predicate instead"
    )
    assert not F.declares_required_outputs(step_id), (
        f"step {step_id} / d{DIM}: this cell's NA precondition was 'no declared "
        f"required_outputs', but the step now declares "
        f"{F.required_outputs(step_id)!r}"
    )

    step = F.step_by_id(step_id)
    text = f"{step.get('name', '')}\n{step.get('notes', '') or ''}"

    if str(F.PROGRAMS_DIR) not in sys.path:
        sys.path.insert(0, str(F.PROGRAMS_DIR))
    import flow_compliance_check as fcc  # live import, not a text scan

    registry = tuple(getattr(fcc, "_STRUCTURAL_RTL_GATES", ()))
    assert registry, (
        f"step {step_id} / d{DIM}: flow_compliance_check no longer exposes a "
        f"non-empty _STRUCTURAL_RTL_GATES, so P0's prose cannot be checked "
        f"against the mechanism that produces its verdict"
    )
    assert hasattr(fcc, "_run_structural_rtl_gates"), (
        f"step {step_id} / d{DIM}: the notes name "
        f"flow_compliance_check._run_structural_rtl_gates as the mechanism that "
        f"emits this step's verdict; that attribute does not exist"
    )

    named = [n for n in _BACKTICKED.findall(text) if n.endswith("_check")]
    absent = [n for n in named if n not in registry]
    assert not absent, (
        f"step {step_id} / d{DIM} criteria_match: the step's prose names "
        f"{absent} as gate name(s) that appear in the audit JSON's gates[] "
        f"array, but that array is built only from _STRUCTURAL_RTL_GATES "
        f"(flow_compliance_check.py:8019 -> :8085) and the live registry's "
        f"{len(registry)} members do not include them; "
        f"named-and-present = {[n for n in named if n in registry]}"
    )

    claimed_counts = {int(m) for m in _COUNT_CLAIM.findall(text)}
    wrong = sorted(c for c in claimed_counts if c != len(registry))
    assert not wrong, (
        f"step {step_id} / d{DIM} criteria_match: the step's name/notes claim "
        f"{wrong} structural gate(s); the live _STRUCTURAL_RTL_GATES tuple has "
        f"{len(registry)}"
    )


# ──────────────────────────────────────────────────────────────────────
# The 63 cells
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cell", _params(), ids=lambda c: f"step{c.step_id}")
def test_d4_gate_measures_what_it_claims(cell):
    """One cell of dimension 4, recomputed from the current tree every run."""
    sid = cell.step_id

    if not F.has_gate(sid):
        _assert_gateless_step_prose_matches_mechanism(sid)
        return

    if _exec_clauses(sid):
        _assert_cli_contract(sid)
        _assert_artefacts_grounded(sid)
        return

    _assert_files_only_gate_matches_claim(sid)


# ──────────────────────────────────────────────────────────────────────
# Self-checks — these are NOT cells. They keep the two measurements above
# from degrading into predicates that cannot fail.
# ──────────────────────────────────────────────────────────────────────
def test_d4_selfcheck_cli_probe_can_report_a_rejection():
    """The CLI probe must actually detect a refused invocation.

    Built by appending a flag no program declares to a REAL gate command, so
    the only difference from a passing clause is the thing being measured.
    """
    baseline = "cdc_crossing_check . --json reports/phase2/gates/cdc_crossing.json"
    assert baseline in F.gate_commands(3), (
        "the canary is anchored to a real step-3 gate command; the flow no "
        f"longer declares it — step 3 commands are {F.gate_commands(3)}"
    )
    assert not P.probe_cli(baseline).rejected, (
        f"baseline invocation was itself rejected: "
        f"{P.probe_cli(baseline).stderr_tail}"
    )

    poisoned = baseline + " --matrix-d4-canary-flag 1"
    probe = P.probe_cli(poisoned)
    assert probe.rejected, (
        "the CLI probe cannot detect a rejected invocation, so every green "
        "cell of measurement 1 is meaningless: adding an undeclared flag to a "
        f"real gate command produced rc={probe.returncode}, "
        f"parser_error={probe.parser_error!r}, stderr={probe.stderr_tail!r}"
    )


def test_d4_selfcheck_a_WILDCARD_root_still_spans_namespaces():
    """The namespace guard must not over-tighten into a second false ruler.

    The guard refuses a float-match across top-level namespaces, but a pattern
    whose ROOT is a glob is a deliberate "anywhere under the project" read and
    must keep grounding. Measured: of 132 grounded entries across every gated
    step, exactly ONE rests on a cross-namespace match, and it is this one.

    Pinned against the REAL step-31 entry rather than against a literal pair,
    so that if the flow stops declaring it this test says so instead of
    quietly proving something about a string.
    """
    entry = "reports/phase3/erc.rpt"
    assert entry in F.required_outputs(31), (
        f"this test is anchored to step 31 declaring {entry!r}; it no longer "
        f"does, so the exemption it pins is pinned to nothing — step 31 "
        f"declares {F.required_outputs(31)}"
    )
    hit = P.ground(31, entry)
    assert hit is not None, (
        "the wildcard-root exemption regressed: step 31's own declared "
        f"{entry!r} is no longer grounded, so the namespace guard has "
        "over-tightened into a false negative"
    )
    assert P.covers("*/phase3/erc.rpt", entry), (
        "a glob-rooted pattern must still span namespaces"
    )


def test_d4_selfcheck_exec_branch_can_fail_on_an_UNGROUNDED_output(monkeypatch):
    """The EXEC branch must be able to reject a declared output nobody reads.

    It could not. Injecting `reports/phase1/ZZZ_CANARY_NOBODY_CHECKS_THIS.json`
    into D1's `required_outputs` left dimension 4 fully green, because
    `shape_match` floats a pattern (`**` + pattern, either direction) and
    `phase1/*.json` — read from `l_doc_cross_consistency_check` — is a
    contiguous TAIL of `reports/phase1/<anything>.json`. `phase1/` and
    `reports/phase1/` are two different trees.

    So every green EXEC-branch cell was green on an axis the ruler could not
    fail on, which is this campaign's own defect sited in its instrument. The
    files-only branch caught step 1; this half caught nothing.

    Driven through `_assert_artefacts_grounded` rather than through `covers`,
    because the matcher passing is necessary and not sufficient: `ground()`
    has three channels and any one of them re-grounding the canary would put
    the hole straight back.
    """
    sid = "D1"
    assert _exec_clauses(sid), (
        f"this self-check is anchored to step {sid} taking the EXEC branch; it "
        f"no longer does, so the branch it proves is not the branch it runs"
    )
    canary = "reports/phase1/ZZZ_CANARY_NOBODY_CHECKS_THIS.json"
    real = list(F.required_outputs(sid))
    assert real, f"step {sid} declares no required_outputs to extend"

    monkeypatch.setattr(F, "required_outputs", lambda s: (real + [canary]) if s == sid else F.required_outputs(s))
    P.grounding_report.cache_clear() if hasattr(P.grounding_report, "cache_clear") else None
    with pytest.raises(BaseException) as excinfo:
        _assert_artefacts_grounded(sid)
    assert canary in str(excinfo.value), (
        f"the EXEC branch failed, but not because of the canary: {excinfo.value}"
    )


def test_d4_selfcheck_matcher_discriminates_wrong_directory():
    """The path matcher must not call a same-basename/different-dir pair a hit.

    This is the step-40 / step-42 defect shape: the checker searched
    ``manufacturing/mask_set_received.json`` while the flow declared
    ``phase3/stage5_manufacturing/mask_set_received.json``. A substring or
    basename matcher calls that grounded and re-hides the defect.
    """
    declared = "phase3/stage5_manufacturing/mask_set_received.json"
    assert P.covers(declared, declared)
    assert not P.covers("manufacturing/mask_set_received.json", declared), (
        "the matcher accepts a different directory with the same basename; "
        "the step-40 path-mismatch defect would pass unnoticed"
    )
    assert not P.covers("flow_compliance_check.log", "phase2/stage1/sim/*.log"), (
        "the matcher lets a program's own log file ground a step's declared "
        "simulation log"
    )
    assert P.covers("*drc*.rpt", "reports/phase3/routed.drc.rpt"), (
        "the matcher rejects a genuine discovery glob"
    )


def _with_step_12_outputs(
    tmp_path: Path, outputs: List[str], tag: str, gate_checks: str
) -> Path:
    """A scratch copy of the flow yaml whose step 12 declares *outputs* under
    a SYNTHETIC single-clause, files-only gate that checks *gate_checks*.

    Step 12 was chosen as the id to graft this onto because it used to BE the
    simplest files-only gate in the flow. It no longer is: 2026-08-08 gave it
    a real ``program_exit_zero`` clause
    (``dft_post_optimization_scan_survival_check``) closing a dimension-2 gap
    — a genuine, separate fix, not a defect of this control. The gate is
    therefore no longer "copied through untouched": it is OVERWRITTEN to the
    one-``files_exist``-path, no-``any_of``, no-program shape this control
    needs, so the only variable between the two cases below is still the
    shape of ``required_outputs`` and nothing about step 12's real gate
    leaks in. *gate_checks* is a single real PATH (never an ``" OR "``
    entry-DSL string, which ``files_exist`` does not parse) — the caller
    passes the plain ``netlist`` variable in both the FORWARD and REVERSE
    case, matching "the gate ... checks only the first path" either way.
    """
    doc = copy.deepcopy(F.load_flow())
    hits = [s for s in doc["steps"] if F.normalize_id(s["id"]) == "12"]
    assert len(hits) == 1, f"expected exactly one step 12, got {len(hits)}"
    hits[0]["required_outputs"] = list(outputs)
    hits[0]["gate"] = {"files_exist": [gate_checks]}
    hits[0].pop("programs", None)
    out = tmp_path / f"flow_{tag}.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return out


def test_d4_selfcheck_files_only_branch_separates_spelling_from_deliverable(
    tmp_path,
):
    """BIDIRECTIONAL control for the files-only branch's entry-level rule.

    Two scratch flows, IDENTICAL in every byte that matters except the shape of
    step 12's ``required_outputs``. The same two paths appear in both, the gate
    is the same in both and checks only the first path. The single difference is
    ``", "`` (two list entries) versus ``" OR "`` (one any-of entry):

      FORWARD  ``["<netlist>", "<a report the gate never checks>"]``
               -> two ENTRIES, the second read by nothing -> MUST FAIL.
               Against the pre-fix predicate this PASSED: its
               ``assert covered`` was satisfied by the netlist alone.

      REVERSE  ``["<netlist> OR <the same report>"]``
               -> ONE entry with two accepted spellings, one of them checked
               -> MUST STILL PASS. This is the half that stops the fix from
               degenerating into "every alternative must be checked", which
               would red every legitimate either-or in the flow — step 1's
               ``*.sv OR *.v`` and the 22 other ANY_OF entries among them.

    Without the reverse case a stricter predicate looks like an improvement and
    is actually a different defect, so both directions are asserted here rather
    than one being left to a reviewer's imagination.
    """
    original = F.FLOW_YAML
    netlist = "phase2/stage2/synth/post_dft_netlist.v"
    unread = "reports/phase2/post_dft_area.rpt"

    # Precondition, asserted so this control self-invalidates loudly if the
    # predicate it exercises changes shape. Step 12's own REAL gate is no
    # longer checked here — 2026-08-08 gave it a genuine exec clause of its
    # own, so `_with_step_12_outputs` now synthesizes the single-clause,
    # files-only shape this control needs rather than mirroring it; see that
    # helper's docstring.
    assert not P.covers(netlist, unread), (
        f"the control needs {unread!r} to be an artefact the gate's "
        f"{netlist!r} does NOT resolve, or the FORWARD case proves nothing"
    )

    try:
        F.set_flow_yaml(
            _with_step_12_outputs(tmp_path, [netlist, unread], "fwd", netlist)
        )
        assert F.required_outputs(12) == (netlist, unread)
        # BOTH failure spellings: the branch uses `pytest.fail` (which raises
        # `Failed`, a BaseException — `pytest.raises(Exception)` does NOT catch
        # it) and plain `assert` above it. Naming both keeps the control valid
        # whichever one a later edit uses.
        with pytest.raises((AssertionError, pytest.fail.Exception)) as caught:
            _assert_files_only_gate_matches_claim(12)
        message = str(caught.value)
        assert unread in message, (
            "the files-only branch went red but did not name the declared "
            f"output nobody reads; message was:\n{message}"
        )
        assert "ALL-of-N" in message, (
            "the failure does not tell the reader WHY a second entry is an "
            f"obligation rather than an alternative; message was:\n{message}"
        )

        F.set_flow_yaml(
            _with_step_12_outputs(
                tmp_path, [f"{netlist} OR {unread}"], "rev", netlist
            )
        )
        assert F.required_outputs(12) == (f"{netlist} OR {unread}",)
        assert F.split_any_of(F.required_outputs(12)[0]) == (netlist, unread)
        # MUST NOT raise: one entry, two accepted spellings, one of them checked.
        _assert_files_only_gate_matches_claim(12)
    finally:
        F.set_flow_yaml(original)

    # The restore must be real — a leaked scratch path would silently repoint
    # every later test in this process at a file nobody reviewed.
    assert F.FLOW_YAML == original
    assert F.required_outputs(12) == (netlist,)


def test_d4_selfcheck_catalogue_exclusion_is_justified():
    """The one excluded module must really be a shared path CATALOGUE.

    Excluding a module from the read closure is a way to make a predicate
    stricter; it must never become a way to hide a module that carries real
    reads. The exclusion is therefore checked against the tree.
    """
    for name in P.CATALOGUE_MODULES:
        path = F.PROGRAMS_DIR / f"{name}.py"
        assert path.is_file(), f"excluded module {name} does not exist"
        strings, _ = P._module_facts(path)
        literals = {s for s in strings if P.is_path_shaped(s)}
        importers = [
            program
            for sid in F.step_ids()
            for program in F.gate_programs(sid)
            if name in P._module_facts(F.PROGRAMS_DIR / f"{program}.py")[1]
        ]
        assert len(literals) >= 80 and len(importers) >= 20, (
            f"{name} is excluded from the read closure on the grounds that it "
            f"is a shared path catalogue, but it now holds {len(literals)} path "
            f"literals and is imported by {len(set(importers))} gate programs — "
            f"the exclusion no longer describes it and may be hiding real reads"
        )


def test_d4_selfcheck_waivers_are_evidence_backed():
    """Every waiver this dimension relies on must satisfy the shared validator.

    THE VALIDATION LOOP IS EMPTY TODAY, and saying so is the point of this
    paragraph. All ten of this dimension's waivers were closed by fixing the
    gates, so the comprehension below iterates zero times and ``W.validate``
    is never called. (Its d8 sibling,
    ``test_matrix_d8_missing_caught.test_d8_every_waiver_is_evidence_backed``,
    says the same about its own empty registry.)

    AN EMPTY LOOP MUST NOT REPORT GREEN ON ITS OWN, so the set is PINNED, not
    floored. #530 guarded this with ``assert dim_waivers()`` — correct while
    the dimension still had ten entries, and a permanent red the moment it has
    none. The pin below says the same thing in the direction that survives a
    dimension being genuinely waiver-free: the day a waiver is added, this line
    reddens, and the loop underneath is what will grade it.

    What the loop WOULD check: ``validate()`` rejects a placeholder reason, a
    reason under 40 chars, and an empty or trivial evidence string, so a cell
    cannot be quietly parked behind "flaky" or "not implemented".

    Reads the ONE registry. The module-local ``LOCAL_WAIVERS`` mirror this used
    to validate was deleted: ``_waiver_for`` had preferred the central copy for
    some time, so validating the mirror graded a table nothing read.
    """
    live = {w.label for w in dim_waivers()}
    assert live == WAIVED_CELLS_PINNED, (
        f"dimension {DIM}'s waiver set changed to {sorted(live)}; it is pinned "
        f"at {sorted(WAIVED_CELLS_PINNED)}. Adding one is a public admission "
        f"and must be argued for in the same change that pins it here; "
        f"removing one means the gap is closed and the cell is enforced."
    )
    # The census must agree the pinned set is the set IN FORCE, so the pin
    # cannot go stale in the direction of describing waivers nobody applies.
    applied = {F.normalize_id(c.step_id) for c in cells_for(DIM)
               if _waiver_for(c.step_id) is not None}
    assert applied == {F.normalize_id(w.step_id) for w in dim_waivers()}, (
        f"cells this dimension WAIVES {sorted(applied)} do not match the "
        f"registry entries {sorted(F.normalize_id(w.step_id) for w in dim_waivers())}"
    )
    problems = [
        f"{waiver.label}: {issue}"
        for waiver in dim_waivers()
        for issue in W.validate(waiver)
    ]
    assert not problems, "\n".join(problems)


def test_d4_selfcheck_every_cell_has_exactly_one_disposition():
    """68 cells, each ENFORCED or WAIVED, none silently absent.

    The parametrized test body has no unconditional ``skip`` and no early
    ``return`` that skips every assertion — each of the three branches ends in
    at least one live assertion — so "has a disposition" reduces to: the ledger
    still holds one cell per declared step, and every waived cell traces to a
    registry entry this module can name.
    """
    cells = cells_for(DIM)
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
    assert len(cells) == len(F.step_ids()) == 68, (
        f"the flow declares {len(F.step_ids())} steps; dimension {DIM} carries "
        f"{len(cells)} cells — the ledger and the yaml have diverged"
    )
    waived = {
        F.normalize_id(c.step_id)
        for c in cells
        if _waiver_for(c.step_id) is not None
    }
    known = {w.key[0] for w in dim_waivers()}
    assert waived == known, (
        f"waived cells {sorted(waived)} do not match the one registry this "
        f"module reads {sorted(known)}"
    )
    # WAS 53. The change, explained as the message below demands: the ten
    # cells this dimension waived were CLOSED by fixing the gates, not by
    # relaxing the predicate — see the LOCAL_WAIVERS block at the top for the
    # per-step fix and `git log` for the diff. Nothing in `_assert_*` above
    # changed, so the same predicate that failed those ten now passes them.
    # The number stays hard-coded on purpose: deriving it from `waived` would
    # make this assertion unfalsifiable, and a NEW waiver must force a human
    # to re-state the census rather than slip in silently.
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
    assert len(cells) - len(waived) == 68 and not waived, (
        f"{len(cells) - len(waived)} cells are enforced and {len(waived)} are "
        f"waived; this module was reported as enforcing all 63 with no "
        f"waiver. Update the report, or explain the change."
    )


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
    # Dimension 4 has no NA cell: every step declares a gate whose criteria can
    # be compared against what its programs read, and P0's umbrella is compared
    # against its own registry. Returning None unconditionally is the honest
    # answer, and the census test below asserts the NA count stays 0.
    del step_id
    return None


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if _waiver_for(step_id) is not None:
        return "WAIVED"
    return "ENFORCED"
