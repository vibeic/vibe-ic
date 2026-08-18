"""vibe-ic#1704 - the ratchet's DENOMINATOR moved and the record did not say why.

WHAT HAPPENED. The published corpus moved to `vibeic/benchmark-data`, which ships
only cells that PASS and conform: 4 of them. `step_internal_fail_bubble_up_baseline`
still described the pre-split tree - 22 findings over 16 run trees - so pointing the
suite at the published clone produced three reds, one per recorded number::

    the ratchet baseline cites N run tree(s) that are not in the corpus: [...]
    recorded findings_total=22 but the corpus now carries 1
    recorded denominator (16, 16) != live (4, 4)

Those three are `test_issue1015_ratchet_does_not_claim_paid_debt`'s and they were
RIGHT. Re-deriving the baseline turns them green, and that alone would close the
issue in the exact way the issue forbids: "Do NOT simply lower the numbers to make
the tests green. The point of a ratchet is that the number cannot move without
someone stating why."

WHAT WAS ALREADY GUARDED, AND WHAT WAS NOT. `withdrawn_unexamined` (vibe-ic#1202)
covers the NUMERATOR: a finding that leaves `findings_total` because its run stopped
being published is recorded so the fall can never be read as debt somebody paid. It
says nothing about the DENOMINATOR, and 16 -> 4 is the number that carries the
meaning here: a population that shrinks because nine trees were never published is a
different fact from one that shrinks because nine trees were deleted, and both
render identically as a smaller integer. It also says nothing about a run that left
carrying ZERO findings - three of the twelve did, so they appear in no ledger at all
and the two counts cannot be reconciled from `withdrawn_unexamined` alone.

WHAT THIS MODULE PINS. `_population_shrink` in the baseline states the transition
(`from` -> `to`), itemises every run that left with a reason from a closed
vocabulary, and names what arrived. The predicates below are ARITHMETIC over that
block, not spelling checks over its prose:

    to == the three numbers the record actually carries
    to.runs_swept == from.runs_swept - |left| + |arrived|
    to.findings_total == from.findings_total - sum(left findings) + arrived findings

so a later `--write-baseline` that moves any of the three and leaves this block
behind is RED. It cannot be silenced by deleting the block either: absence is a
failure here, not an exemption.

WHY IN THE TEST TREE. `step_internal_fail_bubble_up_check.py` is on
`tools/ci/protected_landing_transition.json`, whose bytes may only move through a
PREPARE+ACTIVATE pair. The guard needs none of the checker's runtime, and #1015's
own argument applies unchanged: regenerating the baseline fixes today's number and
nothing else - the predicate is what makes the record self-correcting.

NO CORPUS IS NEEDED FOR MOST OF THIS, deliberately. The issue notes the corpus arm
"is the arm nothing runs today", so a guard reachable only there would be a guard
nobody runs. Everything except the last two predicates is a statement about the
record alone and runs in the arm CI has now.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _published_corpus import needs_corpus

PROGRAMS = Path(__file__).resolve().parents[1]
BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"

#: WHY A RUN CAN LEAVE THE SWEPT POPULATION. Closed on purpose: "someone stated
#: why" is only worth anything if the statement has to be one of a few things
#: a reader can act on. Free text would let `_population_shrink` be filled with
#: a shrug and still satisfy every equation below.
REASONS = {
    # the run tree is not a `v<version>_<PDK>` cell, so the publishing contract
    # admits no such directory (a loose IC-level tree, a `clean_run_*` folder)
    "not_published_layout",
    # it IS a cell directory and its own RESULT.md reads FAIL
    "not_published_verdict",
    # the bytes are gone from the source history too - NOT the same fact as
    # either of the above, which is the distinction this whole block exists for
    "deleted",
    # still published, stopped carrying a reports/ tree (the vibe-ic#1202 shape)
    "reports_withdrawn",
}

_NUMBERS = ("runs_swept", "runs_with_reports", "findings_total")


def _record() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _block() -> dict:
    rec = _record()
    assert "_population_shrink" in rec, (
        f"{BASELINE.name} records no `_population_shrink`, so its three "
        f"numbers "
        f"{tuple(rec.get(k) for k in _NUMBERS)} stand with nothing saying how "
        f"they got there. An absent block is the defect, not an exemption from "
        f"it: a ratchet whose population can move in silence is the thing "
        f"vibe-ic#1704 is about.")
    return rec["_population_shrink"]


def test_the_block_is_shaped_like_a_transition():
    """`from`, `to`, and both directions of movement, or it states nothing."""
    b = _block()
    for key in ("from", "to", "runs_that_left", "runs_that_arrived",
                "findings_that_arrived"):
        assert key in b, f"`_population_shrink` is missing `{key}`: {sorted(b)}"
    for end in ("from", "to"):
        for n in _NUMBERS:
            assert isinstance(b[end].get(n), int), (
                f"`_population_shrink.{end}.{n}` is not an integer: "
                f"{b[end].get(n)!r}")


def test_the_transition_ends_where_the_record_actually_stands():
    """THE PREDICATE THAT MAKES THE NEXT MOVE LOUD.

    `to` must be the three numbers the register carries. `--write-baseline`
    rewrites those and carries `_`-prefixed keys forward untouched, so an
    operator who re-records a shrink and says nothing about it leaves a `to`
    describing the previous population - and this goes red naming both.

    It is also what stops the block being decorative: it cannot be written once
    and then quietly outlive the numbers it describes.
    """
    rec, b = _record(), _block()
    live = {n: rec[n] for n in _NUMBERS}
    assert b["to"] == live, (
        f"`_population_shrink.to` says {b['to']} and the register carries "
        f"{live}. Either the numbers moved and nobody stated why - which is "
        f"exactly what this block exists to prevent - or the block was edited "
        f"without re-measuring. Re-derive with --write-baseline against the "
        f"published corpus and restate `_population_shrink`.")


def test_every_departed_run_names_a_reason_from_the_vocabulary():
    b = _block()
    bad = {run: e.get("reason") for run, e in b["runs_that_left"].items()
           if e.get("reason") not in REASONS}
    assert not bad, (
        f"{len(bad)} departed run(s) carry no usable reason: {bad}. Allowed: "
        f"{sorted(REASONS)}. 'The population moved' is the observation, not "
        f"the statement the ratchet asks for.")
    for run, e in b["runs_that_left"].items():
        assert isinstance(e.get("findings"), int) and e["findings"] >= 0, (
            f"`runs_that_left[{run}].findings` is not a count: {e.get('findings')!r}")


def test_the_denominator_movement_is_fully_itemised():
    """Every run in the gap has a name.

    Without this the block could state a 16 -> 4 fall and itemise one run, and
    the other eleven would be exactly as unexplained as they were before -
    the same silence with a heading over it.

    Written as a signed equation rather than `from - to == len(left)` so a
    population that GROWS is describable too; a guard that only understands
    shrinks would have to be edited (or deleted) the first time a cell is
    published, and a guard edited under pressure is a guard removed.
    """
    b = _block()
    expect = (b["from"]["runs_swept"] - len(b["runs_that_left"])
              + len(b["runs_that_arrived"]))
    assert b["to"]["runs_swept"] == expect, (
        f"the swept population went {b['from']['runs_swept']} -> "
        f"{b['to']['runs_swept']}, but the block names "
        f"{len(b['runs_that_left'])} run(s) that left and "
        f"{len(b['runs_that_arrived'])} that arrived, which accounts for "
        f"{expect}. {abs(b['to']['runs_swept'] - expect)} run(s) moved with "
        f"nothing said about them.")


def test_the_numerator_movement_reconciles_against_the_same_runs():
    """The findings must fall by what the named runs were carrying.

    This is the predicate that catches the tempting repair: itemise a couple of
    runs, leave `findings_total` at whatever the sweep now says, and let the
    two numbers drift apart again. It also ties the reason-record to the
    measurement - the per-run counts here came from the same sweep that
    produced `from.findings_total`, so a hand-typed number will not balance.
    """
    b = _block()
    left = sum(e["findings"] for e in b["runs_that_left"].values())
    expect = b["from"]["findings_total"] - left + b["findings_that_arrived"]
    assert b["to"]["findings_total"] == expect, (
        f"findings_total went {b['from']['findings_total']} -> "
        f"{b['to']['findings_total']}, but the runs named as leaving carried "
        f"{left} and {b['findings_that_arrived']} arrived, which accounts for "
        f"{expect}. The difference is a finding that changed state with no "
        f"account of it.")


def test_a_departed_run_is_not_also_a_present_one():
    rec, b = _record(), _block()
    both = sorted(set(b["runs_that_left"]) & set(rec["per_run"]))
    assert not both, (
        f"{both} are recorded as having left the population and are also "
        f"counted in `per_run`. One of the two records is wrong and the "
        f"ratchet is holding a line over a set it cannot name.")


def test_a_departed_run_that_carried_debt_is_on_the_withdrawal_ledger():
    """The two ledgers must agree about the same event.

    `withdrawn_unexamined` (vibe-ic#1202) says a finding left unexamined;
    `_population_shrink` says why its run left. Nothing made them consistent,
    and a run named in one and absent from the other is a record that has two
    answers about a single departure. Runs that left carrying ZERO findings are
    deliberately not required here - they belong on no debt ledger, and they
    are the reason the denominator needs its own account at all.
    """
    rec, b = _record(), _block()
    ledger = {k[3:] if k.startswith("ic/") else k: v
              for k, v in rec["withdrawn_unexamined"].items()}
    wrong = {}
    for run, e in b["runs_that_left"].items():
        if e["findings"] == 0:
            continue
        key = run[3:] if run.startswith("ic/") else run
        if ledger.get(key) != e["findings"]:
            wrong[run] = (e["findings"], ledger.get(key))
    assert not wrong, (
        f"{len(wrong)} departed run(s) disagree between `_population_shrink` "
        f"and `withdrawn_unexamined` (stated, on-ledger): {wrong}. A finding "
        f"whose run is accounted for in one register and not the other is "
        f"debt that can be dropped by consulting the other book.")


# ------------------------------------------------ falsifiable against the tree

@needs_corpus
def test_no_run_recorded_as_departed_is_still_in_the_corpus():
    """The self-consistency above is worth nothing if the block is fiction.

    Everything before this compares the record against itself. This one asks
    the corpus, and it is the arm that turns "the record balances" into "the
    record is true": a run named as having left must not be sitting there with
    a reports/ tree.
    """
    import step_internal_fail_bubble_up_check as SIFBU     # noqa: PLC0415
    from test_issue1015_ratchet_does_not_claim_paid_debt import CORPUS  # noqa: PLC0415

    live = set(SIFBU.check_corpus(CORPUS)["examined_runs"])
    still = sorted(set(_block()["runs_that_left"]) & live)
    assert not still, (
        f"{still} are recorded as having left the published population and the "
        f"sweep of {CORPUS} finds them. The reason recorded against them "
        f"describes something that did not happen.")


@needs_corpus
def test_the_transition_ends_where_the_live_sweep_stands():
    """`to` against the corpus, not against the register.

    `test_the_transition_ends_where_the_record_actually_stands` proves the
    block and the register agree; both could be stale together. This measures.
    """
    import step_internal_fail_bubble_up_check as SIFBU     # noqa: PLC0415
    from test_issue1015_ratchet_does_not_claim_paid_debt import CORPUS  # noqa: PLC0415

    rep = SIFBU.check_corpus(CORPUS)
    assert _block()["to"] == {n: rep[n] for n in _NUMBERS}, (
        f"`_population_shrink.to` is {_block()['to']} and the corpus at "
        f"{CORPUS} measures {{{', '.join(f'{n}: {rep[n]}' for n in _NUMBERS)}}}. "
        f"The population moved again and the account of it did not follow.")


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
