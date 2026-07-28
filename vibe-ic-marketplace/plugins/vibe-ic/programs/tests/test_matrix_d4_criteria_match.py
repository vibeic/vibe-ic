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
    other 113 are grounded by program code (103) or by a filename-prefix table
    (1) — plus the 9 waived below.
  * **Grounding proves the gate is WIRED to the artefact, not that it reads it
    substantively.** ``analog_a8_*`` opening a 500-byte non-GDS file and
    calling it a GDS is grounded here and still a defect. That is dimension
    4's shared border with the substance question, and it is not crossed.

What this module DOES decide, live, on every run:

  1. **The gate's declared invocation is one the program accepts.** Each gate
     command is run verbatim; if the program's own parser rejects it (argparse
     ``rc=2`` + a ``prog: error:`` usage line), the clause measures nothing —
     and ``flow_compliance_check._check_program_exit_zero`` maps ``rc == 2``
     onto ``VACUOUS_PASS``, so it measures nothing *and banks a pass*. One live
     instance (step 2) is waived below with its reproduction.
  2. **Every artefact the step declares is named somewhere the gate can reach.**
     A step that declares ``reports/phase3/em.json`` while its gate searches
     ``*em*.rpt`` only is measuring something adjacent to its own claim.
  3. **A files-only gate checks the step's own deliverables** (steps 1, 12).
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
Three non-cell tests at the bottom keep the measurements honest: that the CLI
probe can report a rejection, that the path matcher discriminates the
same-basename/different-directory shape (the step-40 defect), and that the one
excluded module really is a shared path catalogue.
"""
from __future__ import annotations

import re
import shlex
import sys
from typing import List, Optional, Tuple

import pytest

import matrix_d4_probe as P
from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W
from matrix_63x8.cells import cells_for

DIM = 4


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

    covered = [
        alt for alt in alternatives if any(P.covers(p, alt) for p in checked)
    ]
    assert covered, (
        f"step {step_id} / d{DIM} criteria_match: none of the step's declared "
        f"artefacts {alternatives} is among the {len(checked)} path(s) the gate "
        f"checks ({checked})"
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
        f"(flow_compliance_check.py:7621 -> :7687) and the live registry's "
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

    ``validate()`` rejects a placeholder reason, a reason under 40 chars, and
    an empty or trivial evidence string, so a cell cannot be quietly parked
    behind "flaky" or "not implemented".

    Reads the ONE registry. The module-local ``LOCAL_WAIVERS`` mirror this used
    to validate was deleted: ``_waiver_for`` had preferred the central copy for
    some time, so validating the mirror graded a table nothing read.
    """
    assert dim_waivers(), f"dimension {DIM} declares no waiver at all"
    problems = [
        f"{waiver.label}: {issue}"
        for waiver in dim_waivers()
        for issue in W.validate(waiver)
    ]
    assert not problems, "\n".join(problems)


def test_d4_selfcheck_every_cell_has_exactly_one_disposition():
    """63 cells, each ENFORCED or WAIVED, none silently absent.

    The parametrized test body has no unconditional ``skip`` and no early
    ``return`` that skips every assertion — each of the three branches ends in
    at least one live assertion — so "has a disposition" reduces to: the ledger
    still holds one cell per declared step, and every waived cell traces to a
    registry entry this module can name.
    """
    cells = cells_for(DIM)
    assert len(cells) == len(F.step_ids()) == 63, (
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
    assert len(cells) - len(waived) == 53, (
        f"{len(cells) - len(waived)} cells are enforced; this module was "
        f"reported as enforcing 53. Update the report, or explain the change."
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
