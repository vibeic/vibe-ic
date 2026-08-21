#!/usr/bin/env python3
"""A RESULT.md that cites an audit as evidence must ship that audit's INPUT.

THE DEFECT (vibe-ic#1293). `benchmark_triage_absorption_audit` is deterministic
and its verdict depends entirely on a `triage_records.json` it is pointed at.
Five published `RESULT.md` cite it as machine evidence for their sign-off. ONE
of them published that file:

    verilogeval_human/RESULT.md                       no input
    verilogeval_human/run_cleanroom_v1481/RESULT.md   no input
    verilogeval_v2/RESULT.md                          no input
    verilogeval_v2/run_cleanroom_v1481/RESULT.md      no input
    cvdp/run_v1239_converge/RESULT.md                 triage_records.json

So four published PASS claims rest on an audit nobody can re-run. This is the
§4.05 / #527 class -- evidence must be reproducible from the REPOSITORY rather
than from one run or one host -- landing in published results rather than in a
test. It is the same shape as a ledger recording a live run directory it did
not ship.

WHY A FROZEN INVENTORY RATHER THAN A BARE FAILURE. The four already shipped.
Reddening main over them would say "fix this now", and there is no honest fix:
those runs did not capture the input, and authoring a plausible
`triage_records.json` after the fact would convert an unverifiable claim into a
FALSE one, which is strictly worse. So the four are RECORDED, and the rule that
matters is applied to everything else:

    a NEW citation without its input FAILS -- the list cannot absorb one
    an inventory entry that GAINS its input FAILS with "delete the entry"

Exact-set equality in both directions, the idiom `gate_discloses_denominator_
check._EMPTY_PROJECT_SILENT_PASS` already uses here. The count of what is still
unverifiable is printed by the test that owns it instead of living in a reason
field inside a checker registry, where no gate surfaces it and no reader of the
RESULT.md will ever see it.

chip-AGNOSTIC: it reasons about file presence beside a published record.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]
EVAL = REPO / "benchmark-data" / "evaluation"

#: The audit whose input this pins, and the file it reads.
AUDIT = "benchmark_triage_absorption_audit"
INPUT_NAME = "triage_records.json"

#: MEASURED 2026-08-13 on `a38902d16` (v1.10.35). Published records that cite
#: the audit and did NOT ship its input. Each is unverifiable and stays that
#: way: the runs are historical and did not capture the file.
#:
#: This list may only SHRINK, and only by a run republishing with its input --
#: never by writing one after the fact, which would make the claim false rather
#: than unverifiable.
UNVERIFIABLE_CITATIONS = frozenset({
    "verilogeval_human/RESULT.md",
    "verilogeval_human/run_cleanroom_v1481/RESULT.md",
    "verilogeval_v2/RESULT.md",
    "verilogeval_v2/run_cleanroom_v1481/RESULT.md",
})


def _citing_records():
    """Every RESULT.md under the evaluation corpus that cites the audit."""
    out = []
    if not EVAL.is_dir():
        return out
    for md in sorted(EVAL.rglob("RESULT.md")):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if AUDIT in text:
            out.append(md)
    return out


def _rel(md: Path) -> str:
    return str(md.relative_to(EVAL))


def _has_input(md: Path) -> bool:
    return (md.parent / INPUT_NAME).is_file()


@pytest.fixture(scope="module")
def citing():
    records = _citing_records()
    if not records:
        pytest.skip(f"no RESULT.md under {EVAL} cites {AUDIT}")
    return records


def test_the_population_is_not_empty(citing):
    """NON-VACUITY. Every assertion below is over this set.

    If the corpus stops citing the audit entirely, the rule is satisfied by
    having nothing to check -- which is the vacuous pass this repo removes, so
    it is stated rather than assumed.
    """
    assert len(citing) >= 2, [_rel(m) for m in citing]


def test_no_NEW_citation_ships_without_its_input(citing):
    """THE RULE. A record citing the audit must ship the file it reads.

    A citation is a claim that a machine checked something. Without the input
    the claim cannot be re-run by anyone, so it is a claim about a measurement
    rather than a measurement.
    """
    missing = {_rel(m) for m in citing if not _has_input(m)}
    unexpected = missing - UNVERIFIABLE_CITATIONS
    assert not unexpected, (
        f"{len(unexpected)} published record(s) cite {AUDIT} as evidence "
        f"without shipping the {INPUT_NAME} it reads, so the PASS they claim "
        f"cannot be re-verified by anyone: {sorted(unexpected)}. Publish the "
        f"input beside the record; do NOT author one after the fact.")


def test_the_inventory_cannot_keep_claiming_a_defect_that_is_FIXED(citing):
    """The other direction, so the list can only shrink by a visible edit."""
    missing = {_rel(m) for m in citing if not _has_input(m)}
    stale = UNVERIFIABLE_CITATIONS - missing
    assert not stale, (
        f"these records now ship {INPUT_NAME} and must be deleted from "
        f"UNVERIFIABLE_CITATIONS: {sorted(stale)}")


def test_the_inventory_names_records_that_actually_exist(citing):
    """A frozen list may not name something the corpus does not carry.

    Without this the inventory could be padded with paths that never existed,
    and the count it publishes would stop meaning anything.
    """
    live = {_rel(m) for m in citing}
    phantom = UNVERIFIABLE_CITATIONS - live
    assert not phantom, (
        f"UNVERIFIABLE_CITATIONS names records that do not cite {AUDIT} (or "
        f"do not exist): {sorted(phantom)}")


def test_PAIRED_at_least_one_citation_DOES_ship_its_input(citing):
    """THE TWIN. Without it, "four are unverifiable" could be "all of them".

    A rule that every citation fails is not a rule about publishing evidence;
    it is a rule nobody can satisfy. This names the one that does, so the bar
    is demonstrably reachable.
    """
    ok = {_rel(m) for m in citing if _has_input(m)}
    assert ok, (
        f"no record ships {INPUT_NAME}, so the requirement has never been met "
        f"and this test cannot show it is meetable")


def test_the_residual_is_PUBLISHED_not_merely_tolerated(citing):
    """The count is the point: it is what is still wrong, printed on every run.

    An inventory that is only consulted on failure is an excuse list. This
    prints it whether or not anything is broken.
    """
    missing = sorted(_rel(m) for m in citing if not _has_input(m))
    print(f"\n[{AUDIT}] {len(citing)} citing record(s); "
          f"{len(missing)} cannot be re-verified: {missing}")
    assert len(UNVERIFIABLE_CITATIONS) == len(missing), (
        UNVERIFIABLE_CITATIONS, missing)
