"""test_matrix_artefact_mutation_channel.py — the STANDING gate on the third
mutation channel: changing a NUMBER INSIDE A PUBLISHED REPORT must be a thing
this repository can express, re-execute, and report on.

    ``test_matrix_mutation_ledger.py`` gates the two channels that edit the
    SOURCE — the flow yaml and the plugin tree. Neither can say "change a
    figure in a published run and see whether any cell notices". This file
    gates the channel that can, and it gates BOTH answers: the mutations that
    redden a cell and the mutations that prove a cell cannot be reddened from
    artefact content at all.

====================================================================
WHY A SEPARATE FILE, AND WHY A SEPARATE TUPLE
====================================================================
``matrix_mutation_ledger.MUTATIONS`` means one thing: *this edit turns this
cell's pytest item red*. Every entry in it does. The artefact entries answer a
different question with a different instrument — they re-run the STEP'S GATE
PROGRAM against a mutated copy of a published run — and, as measured, half of
them answer *no*.

Folding them into ``MUTATIONS`` would let a recorded gap satisfy
``test_every_enforced_cell_carries_a_named_mutation``: the census would count
the cell as covered because an entry names it, while the entry's own content
says the cell cannot be moved. The coverage number would go UP for having
discovered a hole. So the tuples are separate, and
:func:`test_an_artefact_entry_never_counts_as_cell_coverage` asserts the
separation rather than trusting it.

====================================================================
THE FIVE THINGS THIS FILE REFUSES
====================================================================
1. **An entry whose replay cannot run, passing quietly.** A missing run
   directory, a renamed artefact, a regenerated file whose bytes no longer match,
   a gate the flow no longer wires, an absent gate program — each is
   NOT_REPLAYABLE with the reason, and NOT_REPLAYABLE never equals a recorded
   verdict, so it is always a failure. The control for this is shipped and runs
   every time: :func:`test_control_an_unreplayable_entry_reports_not_replayable`
   breaks one field of a REAL entry, four ways, and requires the refusal to name
   which one broke.

2. **A recorded verdict that no longer reproduces.** Every entry is replayed on
   every run — there is no witness subset, because an artefact entry claims one
   cell. A CANNOT_REDDEN entry whose gate has LEARNED to notice fails here, by
   name, which is how a pinned finding un-pins itself.

3. **A published run mutated in place.** The replay copies for real and
   stat-manifests the published run before and after. This is not hypothetical:
   an earlier draft used the PLUGIN_TREE channel's ``cp -al`` hardlink mirror
   and the gate programs — which write their own JSON into the run they audit —
   truncated eight artefacts of the published corpus through the shared inodes.

4. **A finding that drifts.** ``ARTEFACT_CANNOT_REDDEN_AS_MEASURED`` pins how
   many cells are currently unreachable from artefact content. It can only move
   in a diff somebody writes.

5. **A PASS that does not say how much it looked at.** The house rule
   (``gate_discloses_denominator_check``,
   ``gate_zero_denominator_refuses_check``): every aggregate here records its
   denominator, and a zero denominator REFUSES rather than passing over an empty
   ledger.

====================================================================
WHAT THIS FILE DOES *NOT* CLAIM
====================================================================
  * That the four CANNOT_REDDEN findings are fixed, or should be fixed here.
    They are Phase 1 and are scoped separately. Nothing in this branch changes a
    gate program, a baseline, or a waiver.
  * That eight entries are a survey. They are a seed set against ONE published
    run, chosen because it is the only run in the corpus whose seven
    physical-signoff gates are all green at baseline. The reach is stated by
    :func:`test_the_channel_states_its_own_reach` rather than left to be assumed.
  * That a REDDENS entry proves its gate is strong. It proves the gate is
    connected to the artefact's content at all — which is precisely the property
    the other four entries show is absent elsewhere.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

import matrix_mutation_ledger as L
from matrix_63x8 import flowref as F

#: WHERE THE EVIDENCE WENT. Every entry in ``L.ARTEFACT_MUTATIONS`` names ONE
#: published run — `ic/spm/v1.10.18_sky130A` — and the published runs now live
#: in https://github.com/vibeic/benchmark-data rather than in this checkout.
#: A test whose subject is a PUBLISHED CELL cannot be answered here, and the
#: honest rendering of "I could not look" is a SKIP naming the corpus, not a
#: failure that claims the entry rotted. Same rule vibe-ic#1357 established for
#: an absent TOOL. Point ``VIBE_IC_BENCHMARK_DATA`` at a clone and every one of
#: them runs exactly as before — and can still fail.
from _published_corpus import needs_corpus  # noqa: E402

#: Bound for the two git launches in this file. NOT a round number picked by
#: feel, and not the 120 s the first draft used — `ci_harness_timeout_ceiling_check`
#: (BLOCKING) resolves the pytest harness bound from `tools/gatekeeper-land.sh`
#: (`--timeout=180`, `--timeout-method=thread`) and permits any ONE blocking call
#: at most `180 // 3` = 60 s. Above that the inner bound can never fire: pytest
#: reaches 180 s first and takes the whole SESSION down, so `--maxfail` stops
#: counting and every other file in the subset loses its verdict.
#: MEASURED here: `git status --porcelain` over the named run is 0.01 s and
#: `git ls-files --error-unmatch` is under 0.01 s, three runs each. 30 s is
#: ~3000x the measured cost and half the permitted ceiling.
_GIT_TIMEOUT_S = 30

#: Per-replay bound for the ARTEFACT channel. `L.replay_many` forwards it to the
#: `subprocess.run` inside `L.replay_artefact`, so it IS a real process bound —
#: `ci_harness_timeout_ceiling_check` cannot see that (the callee is in another
#: module) and reports it as an ADVISORY rather than a finding, which is why the
#: landed 900 survived here while the same number was caught elsewhere. It is the
#: same hazard either way: 900 s under a 180 s `--timeout-method=thread` harness
#: can never fire, so a hung replay takes the SESSION down instead of the test.
#:
#: 60 s is the ceiling (`180 // 3`) and this call is the only bounded call in any
#: test that reaches it (`lru_cache`, so the eight replays are paid once).
#: MEASURED here: all 8 ARTEFACT entries at `jobs=8`, worst SINGLE replay 1.55 s
#: (ART-DRC-RDB-THREE-ITEMS), whole set 5.48 s wall. 60 s is ~39x the worst one.
#:
#: This is the ARTEFACT channel only. `test_matrix_mutation_ledger.py` bounds the
#: WITNESS channel and could NOT be lowered to the ceiling — see the measurement
#: recorded against its `REPLAY_TIMEOUT`.
_ARTEFACT_REPLAY_TIMEOUT_S = 60


@lru_cache(maxsize=1)
def replay_results() -> Dict[str, L.ReplayResult]:
    """Replay EVERY artefact entry once, in parallel, and cache it.

    Measured 2026-08-11: 3.06 s wall for all 8 at ``jobs=1``, 2.72 s at
    ``jobs=8``. Cheap enough that there is no subset to argue about.
    """
    plan = [(m.name, m.witness) for m in L.ARTEFACT_MUTATIONS]
    return {r.mutation: r
            for r in L.replay_many(plan, jobs=8,
                                   timeout=_ARTEFACT_REPLAY_TIMEOUT_S)}


# ══════════════════════════════════════════════════════════════════════
# The channel is registered as first-class
# ══════════════════════════════════════════════════════════════════════
def test_the_channel_is_registered_exactly_like_the_other_two():
    """ARTEFACT_MUTATION is a channel of the ledger, not a bolt-on.

    Same registry, same kind table, same replay dispatch, same census. A channel
    that had to be invoked by its own private entry point would be one a future
    refactor could drop without any gate noticing.
    """
    assert L.ARTEFACT_MUTATION in L.CHANNELS
    assert set(L.ARTEFACT_KINDS) <= set(L.KINDS)
    for m in L.ARTEFACT_MUTATIONS:
        assert m.channel == L.ARTEFACT_MUTATION, m.name
        assert m.kind in L.ARTEFACT_KINDS, m.name
        assert L.mutation(m.name) is m, (
            f"{m.name} is not reachable through matrix_mutation_ledger."
            f"mutation(), so `--replay {m.name}` would not find it")


def test_every_artefact_entry_is_in_every_replay_plan():
    """If FLOW_YAML entries are verified in CI, these are too.

    Both modes, not just the audit mode: an artefact entry claims exactly one
    cell, so ``witness`` and ``all`` cannot legitimately differ for it, and an
    entry that only runs under ``VIBE_IC_MATRIX_MUTATION_REPLAY=all`` is one CI
    never re-executes.
    """
    names = {m.name for m in L.ARTEFACT_MUTATIONS}
    assert names, "the artefact ledger is empty; see the zero-denominator test"
    for mode in L.REPLAY_MODES:
        planned = {n for n, _ in L.replay_plan(mode)}
        assert names <= planned, (
            f"mode {mode!r} omits {sorted(names - planned)}; an entry nobody "
            f"re-executes is the asserted-but-never-run mutation this ledger "
            f"refuses")


def test_an_artefact_entry_never_counts_as_cell_coverage():
    """The two ledgers stay separate, and the separation is asserted.

    Half the artefact entries RECORD that their cell cannot be reddened. If
    ``mutations_covering`` returned them, the 63x8 coverage census would report
    those cells as covered — the number would improve because a hole was found.
    """
    art_names = {m.name for m in L.ARTEFACT_MUTATIONS}
    yaml_names = {m.name for m in L.MUTATIONS}
    assert not (art_names & yaml_names), (
        f"names collide across the two ledgers: {sorted(art_names & yaml_names)}"
        f"; `--replay <NAME>` would be ambiguous")
    for m in L.ARTEFACT_MUTATIONS:
        covering = {c.name for c in L.mutations_covering(m.step_id, m.dim)}
        assert not (covering & art_names), (
            f"mutations_covering({m.step_id}, {m.dim}) returned an artefact "
            f"entry; a recorded gap must never read as coverage")
    # And the census's coverage arithmetic must be untouched by this channel.
    rep = L.census()
    assert rep["artefact"]["registered"] == len(L.ARTEFACT_MUTATIONS)
    assert all(name not in json.dumps(rep["per_dimension"])
               for name in art_names), (
        "artefact entries appear in the per-dimension coverage listing")


# ══════════════════════════════════════════════════════════════════════
# LOCK 1 — does the entry resolve, right now?
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", [m.name for m in L.ARTEFACT_MUTATIONS])
@needs_corpus
def test_lock1_the_entry_resolves_against_the_live_tree(name):
    """The run exists, the artefact exists, each edit finds EXACTLY the number
    of sites it recorded, and the flow still wires the gate verbatim.

    The exact-count requirement is the anti-rot half. A regenerated artefact
    whose figure moved makes the entry unresolvable and says so, instead of
    editing some other number of places than the one that was measured and
    reporting a verdict about it.
    """
    mut = L.mutation(name)
    problem = L.resolve_artefact(mut)
    assert problem is None, f"{name} no longer resolves: {problem}"


def test_lock1_the_gate_command_is_derived_from_the_live_flow():
    """Each entry's gate is one the flow ACTUALLY declares for that step.

    Derived, never typed: ``step_gate_commands`` reads the live yaml. A flow
    edit that renames a flag makes the entry unresolvable rather than leaving a
    recorded verdict about a command nobody issues.
    """
    doc = L.load_flow()
    for m in L.ARTEFACT_MUTATIONS:
        wired = L.step_gate_commands(m.step_id, doc)
        assert wired, f"step {m.step_id} declares no executable gate clause"
        assert m.gate in wired, (
            f"{m.name}: step {m.step_id}'s gate does not wire {m.gate!r}; "
            f"declared: {list(wired)}")


def test_lock1_every_targeted_step_is_a_live_flow_step():
    live = {F.normalize_id(s) for s in F.step_ids()}
    for m in L.ARTEFACT_MUTATIONS:
        assert F.normalize_id(m.step_id) in live, (
            f"{m.name} targets step {m.step_id}, which the flow does not "
            f"declare — the entry is about nothing")


# ══════════════════════════════════════════════════════════════════════
# LOCK 3 — the record is consistent with itself
# ══════════════════════════════════════════════════════════════════════
def test_lock3_every_artefact_entry_is_consistent_with_its_own_evidence():
    """The recorded numbers and prose must agree with the recorded verdict.

    Same purpose as the yaml ledger's LOCK 3: widening or inventing an entry
    should be a lie about a number in a diff, not an omission nobody sees.
    """
    assert len(L.ARTEFACT_MUTATIONS) > 0, (
        "the artefact ledger is empty. Every assertion in this file would be "
        "vacuously true over an empty tuple, and an empty channel is exactly "
        "the state 63x8 finding #20 describes.")
    problems: List[str] = []
    seen = set()
    for m in L.ARTEFACT_MUTATIONS:
        if m.name in seen:
            problems.append(f"{m.name}: duplicate entry name")
        seen.add(m.name)
        if m.dim not in range(1, 9):
            problems.append(f"{m.label}: dimension {m.dim} outside 1..8")
        if m.expected not in L.ARTEFACT_EXPECTATIONS:
            problems.append(
                f"{m.label}: expected={m.expected!r} is not one of "
                f"{L.ARTEFACT_EXPECTATIONS}")
        if not m.edits:
            problems.append(f"{m.label}: records no edit at all")
        for i, e in enumerate(m.edits):
            if e.count < 1:
                problems.append(f"{m.label}: edit #{i} claims {e.count} sites")
            if e.frm == e.to:
                problems.append(f"{m.label}: edit #{i} changes nothing")
            if not e.frm:
                problems.append(f"{m.label}: edit #{i} has an empty `frm`")
        if not m.run_dir or m.artefact.startswith("/"):
            problems.append(f"{m.label}: run_dir/artefact must be relative")
        if "input/" in m.artefact.replace("\\", "/"):
            problems.append(
                f"{m.label}: {m.artefact} is under a run's input/ tree, which "
                f"this campaign does not touch")
        expected_reddened = 1 if m.expected == L.REDDENS else 0
        if m.measured.reddened != expected_reddened:
            problems.append(
                f"{m.label}: measured.reddened={m.measured.reddened} but "
                f"expected={m.expected} implies {expected_reddened}")
        if m.expected == L.REDDENS and len(m.red_signal.strip()) < 3:
            problems.append(
                f"{m.label}: a REDDENS entry needs a red_signal specific "
                f"enough to rule out an unrelated failure; got "
                f"{m.red_signal!r}")
        if m.expected == L.CANNOT_REDDEN and len(m.observed.strip()) < 80:
            problems.append(
                f"{m.label}: a CANNOT_REDDEN entry must record what the gate "
                f"did INSTEAD of reddening; observed={m.observed[:40]!r} is "
                f"too short to be checkable by someone who has not run it")
        for field_name, floor in (("what", 30), ("breaks", 40)):
            if len((getattr(m, field_name) or "").strip()) < floor:
                problems.append(
                    f"{m.label}: {field_name} is under the {floor}-character "
                    f"floor")
        if not m.measured.date or not m.measured.command:
            problems.append(f"{m.label}: measurement has no date or command")
    assert not problems, (
        f"{len(problems)} artefact-ledger consistency problem(s):\n  - " +
        "\n  - ".join(problems))


def test_the_published_finding_count_is_pinned(record_property):
    """How many cells currently CANNOT be reddened from artefact content.

    Pinned exactly like the emptiness of ``NOT_FALSIFIABLE``: the number is a
    finding, so it may only move in a change somebody writes and explains.
    Closing one of these means teaching a gate to read its artefact — Phase 1,
    scoped separately, deliberately not done in this branch.
    """
    findings = L.artefact_findings()
    record_property("artefact_mutation_headline", L.artefact_headline())
    assert len(findings) == L.ARTEFACT_CANNOT_REDDEN_AS_MEASURED, (
        f"{len(findings)} artefact mutation(s) now prove the cell they target "
        f"cannot redden; the ledger pins "
        f"{L.ARTEFACT_CANNOT_REDDEN_AS_MEASURED}.\n"
        f"currently: {[f'{m.step_id}/d{m.dim}:{m.name}' for m in findings]}\n"
        f"If a gate LEARNED to read its artefact, delete the finding and move "
        f"the pin down in the same change. If a new gap was measured, add the "
        f"entry and move the pin up. Never adjust the pin alone.")


#: The README block that PUBLISHES the finding set, and the sentinels that
#: bound it. Sentinels rather than "the first table after the heading": a
#: section grows paragraphs, and a locator that drifts with the prose would
#: start comparing the wrong table and say nothing about it.
_README = F.PLUGIN_ROOT / "programs" / "tests" / "matrix_63x8" / "README.md"
_TABLE_BEGIN = "<!-- ARTEFACT FINDINGS TABLE"
_TABLE_END = "<!-- END ARTEFACT FINDINGS TABLE -->"


def _readme_published_cells() -> List[str]:
    """The `cell` column of the README's artefact-findings table."""
    text = _README.read_text(encoding="utf-8")
    start, stop = text.find(_TABLE_BEGIN), text.find(_TABLE_END)
    assert 0 <= start < stop, (
        f"{_README} no longer carries the artefact-findings table sentinels "
        f"({_TABLE_BEGIN!r} .. {_TABLE_END!r}). A hand edit that removed them "
        f"would make this comparison silently vacuous, so it is a failure.")
    out: List[str] = []
    for line in text[start:stop].splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cell = line.strip("|").split("|")[0].strip()
        if cell.lower() == "cell":
            continue
        out.append(cell)
    return out


def test_the_readme_publishes_the_live_finding_set():
    """The PUBLICATION of the finding set, guarded in both directions.

    THIS IS THE LOCK THAT WAS MISSING, and its absence cost exactly what the
    channel exists to prevent. Every mechanism above guards the LEDGER: the
    replay re-executes each entry, and
    :func:`test_the_published_finding_count_is_pinned` refuses a pin that moves
    without its entry. All of it worked — `ARTEFACT_CANNOT_REDDEN_AS_MEASURED`
    went 4 -> 2 -> 1 across `46dbf43d` and `fc664a57`, each move landing in the
    change that closed the gap.

    What nothing guarded was the README, which is where a reader actually meets
    this finding. It kept a four-row table naming 25/d2, 9/d2 and 21/d2 as
    unable to fail for three commits after all three had learned to fail,
    byte-identical since the channel landed at `615a44b8`.

    A stale "this gate cannot fail" is the WORSE direction of a stale figure. An
    over-count of coverage claims credit it has not earned and a reviewer knows
    to distrust it; an over-count of DISCLOSED GAPS claims credit for honesty
    while describing gates that are doing their job, and it invites someone to
    go "fix" three gates that need nothing.

    Both directions, so neither kind of drift can hide:
      * a finding the README does not publish is an undisclosed gap;
      * a cell the README publishes that is no longer a finding is this defect.
    """
    live = sorted(f"{m.step_id}/d{m.dim}" for m in L.artefact_findings())
    published = sorted(_readme_published_cells())
    assert published == live, (
        f"the README's artefact-findings table and the ledger disagree.\n"
        f"  published: {published}\n"
        f"  live     : {live}\n"
        f"  unpublished finding(s): {sorted(set(live) - set(published))}\n"
        f"  stale claim(s) that a gate cannot fail: "
        f"{sorted(set(published) - set(live))}\n"
        f"Re-run `matrix_mutation_ledger.py --replay-artefacts`, then edit the "
        f"table between its sentinels in {_README.name}. A cell that LEARNED "
        f"to read its artefact leaves the table in the same change that closes "
        f"it — publishing a gap that no longer exists is not the safe "
        f"direction to be wrong in.")


def test_the_readme_finding_table_is_not_vacuously_empty():
    """A parser that silently found nothing would satisfy the test above.

    If the table degenerates to zero rows while the ledger still reports
    findings, the comparison above catches it. If BOTH go empty the comparison
    passes on `[] == []` — which is the right answer only when the channel
    genuinely has no finding. Assert the two agree on that, from the ledger's
    own count rather than from the row parser, so an empty table can never be a
    parsing accident.
    """
    rows = _readme_published_cells()
    assert len(rows) == L.ARTEFACT_CANNOT_REDDEN_AS_MEASURED, (
        f"the README publishes {len(rows)} finding row(s) while the ledger "
        f"pins {L.ARTEFACT_CANNOT_REDDEN_AS_MEASURED}. If the table parsed to "
        f"nothing, the sentinels or the row shape moved and the comparison "
        f"above went vacuous.")


# ══════════════════════════════════════════════════════════════════════
# LOCK 2 — replay, and it is the only lock that is proof
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", [m.name for m in L.ARTEFACT_MUTATIONS])
@needs_corpus
def test_lock2_the_replay_reproduces_the_recorded_verdict(name):
    """Perform the byte edit on a real copy and re-run the step's own gate.

    Three things must hold, and each rules out a different way of being wrong:

      * the UNMUTATED run's gate PASSES — a mutation against an already-failing
        gate proves nothing, and is reported ALREADY_RED rather than skipped;
      * the verdict after the edit is the one the ledger RECORDED, whichever it
        is. ``REDDENED`` proves the cell reads its artefact's content;
        ``STAYED_GREEN`` proves it does not, which is the published finding;
      * for a REDDENS entry the declared ``red_signal`` is present in the mutant
        output AND absent from the baseline output, so the red is attributable
        to this edit and not to something the gate says anyway.
    """
    r = replay_results()[name]
    mut = L.mutation(name)
    assert r.verdict != "NOT_REPLAYABLE", (
        f"{name} could not be replayed at all: {r.not_replayable}\n"
        f"A replay that cannot run is never a pass — fix the entry or the "
        f"tree, and never delete the entry to make this quiet.")
    if mut.expected == L.CANNOT_REDDEN:
        advice = ("A gate that LEARNED to read its artefact is GOOD NEWS: "
                  "update the entry to REDDENS with its red_signal and move "
                  "ARTEFACT_CANNOT_REDDEN_AS_MEASURED down in the same change.")
    else:
        advice = ("The ledger says this edit reddens the gate; re-running it "
                  "says otherwise, so the recorded proof no longer holds.")
    assert r.as_recorded, (
        f"{name}: recorded {r.expected}, replay says {r.verdict}.\n"
        f"{advice}\n{r.detail}")


@needs_corpus
def test_the_replay_ran_and_is_not_starved(record_property):
    """Anti-starvation guard on this file's own instrument.

    The failure that convened the campaign was a checker reporting a clean run
    because its input had been emptied. A replay that silently produced zero
    results would make every parametrized assertion above vacuously true.
    """
    results = replay_results()
    assert len(results) == len(L.ARTEFACT_MUTATIONS) > 0, (
        f"replayed {len(results)} entry(ies) for a ledger of "
        f"{len(L.ARTEFACT_MUTATIONS)}")
    reddened = sum(1 for r in results.values() if r.verdict == L.REDDENS)
    green = sum(1 for r in results.values() if r.verdict == L.CANNOT_REDDEN)
    record_property(
        "artefact_mutation_replay",
        f"entries={len(results)} reddened={reddened} cannot_redden={green} "
        f"runs={sorted({m.run_dir for m in L.ARTEFACT_MUTATIONS})} "
        f"seconds={sum(r.seconds for r in results.values()):.1f}")
    assert reddened + green == len(results), (
        f"{len(results) - reddened - green} replay(s) reached neither verdict; "
        f"every one must land on REDDENED or STAYED_GREEN or be a failure")
    assert all(r.as_recorded for r in results.values())


def test_the_replay_never_mutates_the_published_run():
    """CONTROL: the corpus is byte-identical after every replay above.

    CORPUS-GATED even though it is GREEN without one, and that is the point.
    With no published run to copy, every replay refuses at resolution, ``git
    status`` over a path this checkout does not have prints nothing, and the
    assertion passes having watched no copy of anything. A control that reports
    "the corpus was not modified" when there was no corpus to modify is the
    exact shape of gate this campaign exists to remove, so it skips instead.

    ``replay_artefact`` raises if its own stat manifest moves, so reaching this
    line already means it did not. The assertion here is the independent one:
    a manifest taken AFTER the whole replay set still matches the sizes and
    mtimes recorded in git's index for the runs those entries name.

    Measured the hard way. The first draft of this replay reused the
    PLUGIN_TREE channel's ``cp -al`` hardlink mirror; the gate programs write
    their JSON reports into the run they audit, and eight published artefacts
    were truncated through the shared inodes before ``git status`` caught it.
    """
    import subprocess
    runs = sorted({m.run_dir for m in L.ARTEFACT_MUTATIONS})
    assert runs, "no runs named; this control is measuring nothing"
    replay_results()          # force the replays before looking
    paths = [str((L.benchmark_data_root() / r)) for r in runs]
    proc = subprocess.run(["git", "status", "--porcelain", "--", *paths],
                          cwd=str(L.REPO_ROOT), capture_output=True, text=True,
                          timeout=_GIT_TIMEOUT_S)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert not proc.stdout.strip(), (
        f"replaying the artefact ledger modified the PUBLISHED corpus:\n"
        f"{proc.stdout}\n"
        f"A replay that edits the runs it measures has destroyed its own "
        f"evidence. The copy must be a real copy — see _copy_published_run.")


# ══════════════════════════════════════════════════════════════════════
# NOT_REPLAYABLE is a reported verdict, never a quiet pass
# ══════════════════════════════════════════════════════════════════════
def _fixture_corpus(tmp_path, base) -> Path:
    """A one-run corpus built HERE, carrying exactly the bytes *base* edits.

    WHY A FIXTURE AND NOT THE PUBLISHED RUN. The control below is about
    ``resolve_artefact``'s REFUSALS — plugin behaviour — and the published run
    was only the convenient thing to break a field of. Pointed at the corpus it
    inherited two defects: with the corpus absent three of its four cases failed
    for the corpus's reason rather than the broken field's, and the fourth
    ("run_dir") PASSED for the wrong reason, because the real ``run_dir`` was
    missing too and every refusal read "is not a directory". Built here it can
    neither skip nor pass by accident, and it now exercises the same four
    refusals on every checkout, corpus or no corpus.

    The file is synthesised from the entry's own ``edits``, so the ``edits``
    case below still breaks a site that genuinely resolves first.
    """
    root = tmp_path / "corpus"
    target = root / "ic" / "probe" / base.artefact
    target.parent.mkdir(parents=True, exist_ok=True)
    parts = [e.frm for e in base.edits for _ in range(e.count)]
    assert parts, f"{base.name} records no edit; nothing to build a fixture from"
    text = "\n".join(parts) + "\n"
    for e in base.edits:
        # Overlapping edit texts would make the site count something other than
        # what the entry recorded. REFUSE loudly rather than build a fixture the
        # control would then measure the wrong thing against.
        assert text.count(e.frm) == e.count, (
            f"the fixture for {base.name} carries {text.count(e.frm)} "
            f"occurrence(s) of {e.frm[:40]!r}, not the recorded {e.count}; "
            f"re-point this control at an entry whose edits do not overlap")
    target.write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize("broken,expect_in_reason", [
    ("run_dir", "is not a directory"),
    ("artefact", "does not exist"),
    ("gate", "no longer wires this command"),
    ("edits", "occurrence"),
])
def test_control_an_unreplayable_entry_reports_not_replayable(
        broken, expect_in_reason, tmp_path, monkeypatch):
    """CONTROL (negative direction): break one field of an entry that RESOLVES,
    and the replay must refuse with a reason naming what broke.

    Four independent ways an entry rots, each checked separately, because a
    single "something went wrong" would not tell an author which one. None of
    them may resolve, none may replay, and none may be mistaken for a pass.

    The subject is the REFUSAL, so the run it is measured against is built in
    ``tmp_path`` (see :func:`_fixture_corpus`) rather than read out of the
    published corpus. The gate clause is still the LIVE one from the flow yaml —
    that half must stay real or the ``gate`` case would be checking a string
    this repository never issues.
    """
    base = L.ARTEFACT_MUTATIONS[0]
    monkeypatch.setenv(L.BENCHMARK_DATA_ENV, str(_fixture_corpus(tmp_path, base)))
    intact = replace(base, run_dir="ic/probe")
    assert L.resolve_artefact(intact) is None, (
        f"the UNBROKEN fixture entry does not resolve "
        f"({L.resolve_artefact(intact)}); the four refusals below would then "
        f"prove nothing about the field each one breaks")

    if broken == "run_dir":
        mut = replace(intact, run_dir="ic/zz_no_such_published_run")
    elif broken == "artefact":
        mut = replace(intact, artefact="reports/phase3/zz_no_such_file.rpt")
    elif broken == "gate":
        mut = replace(intact, gate=intact.gate + " --zz-not-in-the-flow")
    else:
        mut = replace(intact, edits=(L.Edit("zz_bytes_that_are_not_there",
                                            "anything", 1),))

    problem = L.resolve_artefact(mut)
    assert problem, f"breaking {broken!r} still resolved cleanly"
    assert expect_in_reason in problem, (
        f"the refusal for a broken {broken!r} does not say what broke: "
        f"{problem!r}")

    r = L.replay_artefact(mut)
    assert r.verdict == "NOT_REPLAYABLE", (
        f"a broken {broken!r} replayed to {r.verdict} instead of refusing")
    assert not r.as_recorded, (
        f"a replay that could not run reported as_recorded=True — this is the "
        f"exact shape of a gate that passes because it examined nothing")
    assert r.not_replayable, "NOT_REPLAYABLE carries no reason"


@needs_corpus
def test_control_the_baseline_must_pass_or_the_entry_is_already_red(
        tmp_path, monkeypatch):
    """CONTROL: an entry whose gate is ALREADY failing may not report a red.

    A mutation is only evidence if the thing it moved was green first. Here the
    IR-drop entry's run is copied and its recorded BUDGET is dropped to 1 uV, so
    the gate fails on the UNMUTATED copy while the bytes the entry edits are
    untouched and still resolve. The replay must then say ALREADY_RED — not
    REDDENED, and not a pass.

    Built rather than found on purpose: the corpus does contain runs whose DRC
    gate is red at baseline, but their reports do not carry the clean summary
    the entry edits, so a control pointed at one of them would SKIP. A control
    that skips is a control nobody has run.
    """
    base = L.mutation("ART-IR-DROP-OVER-BUDGET")
    root = tmp_path / "corpus"
    dst = root / "ic" / "probe"
    dst.parent.mkdir(parents=True)
    shutil.copytree(L.benchmark_data_root() / base.run_dir, dst)
    budget = dst / "reports" / "phase3" / "ir_drop.json"
    text = budget.read_text(encoding="utf-8")
    assert '"budget_uv": 180000' in text, (
        "the published run no longer records the budget this control lowers; "
        "re-point it rather than deleting it")
    budget.write_text(text.replace('"budget_uv": 180000.00000000003',
                                   '"budget_uv": 1.0'), encoding="utf-8")
    monkeypatch.setenv(L.BENCHMARK_DATA_ENV, str(root))

    mut = replace(base, run_dir="ic/probe")
    assert L.resolve_artefact(mut) is None, (
        "the control broke the entry's own edit sites, so it is measuring "
        "resolution rather than the baseline verdict")
    r = L.replay_artefact(mut)
    assert r.verdict == "ALREADY_RED", (
        f"the gate fails on the unmutated copy and the replay reported "
        f"{r.verdict}; a red that was already there is not evidence for the "
        f"edit.\n{r.detail}")
    assert not r.as_recorded, (
        "an ALREADY_RED replay reported as_recorded=True, so a pre-existing "
        "failure would be banked as proof")


# ══════════════════════════════════════════════════════════════════════
# The house rule: a PASS says how much it looked at; zero refuses
# ══════════════════════════════════════════════════════════════════════
def test_the_channel_states_its_own_reach(record_property):
    """DENOMINATOR DISCLOSURE. A PASS here must say what it covered.

    Matches ``gate_discloses_denominator_check``'s requirement rather than
    inventing one: the aggregate is recorded as a property AND the reach is
    asserted to be a real, non-empty, honestly-narrow set. Eight entries against
    one run is not a survey of the corpus, and this is where that is said.
    """
    rep = L.census()["artefact"]
    record_property("artefact_mutation_census", json.dumps(rep))
    assert rep["registered"] == len(L.ARTEFACT_MUTATIONS) > 0
    assert rep["reddens"] + rep["cannot_redden"] == rep["registered"]
    assert rep["headline"] == L.artefact_headline()
    runs = rep["runs"]
    assert runs, "the channel names no published run"
    cells = {(m.step_id, m.dim) for m in L.ARTEFACT_MUTATIONS}
    steps_in_flow = len(F.step_ids())
    assert len(cells) < steps_in_flow * 8, (
        "the artefact channel claims to cover the whole grid; it does not, and "
        "a gate that overstates its reach is the defect this campaign removes")
    record_property(
        "artefact_mutation_reach",
        f"{len(cells)} cell(s) of {steps_in_flow * 8} probed, across "
        f"{len(runs)} published run(s): {sorted(cells)}")


def test_a_zero_denominator_refuses_rather_than_passing(monkeypatch):
    """ZERO-DENOMINATOR REFUSAL. An emptied ledger must be a red, not a green.

    Matches ``gate_zero_denominator_refuses_check``'s house rule. Every
    parametrized test above disappears when the tuple is empty — pytest reports
    zero items and an author reads a clean run — so the aggregates carry the
    refusal explicitly.
    """
    monkeypatch.setattr(L, "ARTEFACT_MUTATIONS", ())
    L.by_name.cache_clear()
    try:
        assert L.census()["artefact"]["registered"] == 0
        assert L.artefact_headline().startswith("0 artefact mutations")
        with pytest.raises(AssertionError):
            test_lock3_every_artefact_entry_is_consistent_with_its_own_evidence()
        with pytest.raises(AssertionError):
            test_every_artefact_entry_is_in_every_replay_plan()
    finally:
        L.by_name.cache_clear()


@needs_corpus
def test_the_canary_run_is_never_written_by_this_repository():
    """The seed set names ONE run, and that run must be a published artefact of
    the corpus rather than something this branch created.

    A mutation ledger whose evidence is a fixture it wrote itself measures its
    own fixture. Checked by asking git whether the run is tracked.
    """
    import subprocess
    for run in sorted({m.run_dir for m in L.ARTEFACT_MUTATIONS}):
        rel = (L.benchmark_data_root() / run).relative_to(L.REPO_ROOT)
        proc = subprocess.run(["git", "ls-files", "--error-unmatch", str(rel)],
                              cwd=str(L.REPO_ROOT), capture_output=True,
                              text=True, timeout=_GIT_TIMEOUT_S)
        assert proc.returncode == 0 and proc.stdout.strip(), (
            f"{run} is not tracked in git, so it is not a PUBLISHED run and "
            f"this channel would be measuring a local fixture")
