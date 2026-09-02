#!/usr/bin/env python3
"""Three vectors nobody can drive must not look like no vectors at all.

MEASURED — sha256 x sky130A, plugin 1.16.32 (main bcedcdf25):
`known_answer_vector.extract` lifts THREE typed NIST FIPS-180-4 vectors out of
the design's own input, and `bind_vector` refuses all three:

    fips1804_sha256_abc     input field 'message' (24 bits) binds to no input
                            port of this DUT at that width
    fips1804_sha256_448bit  ... (448 bits) ...
    fips1804_sha224_abc     ... (24 bits) ...

The refusals are correct — the DUT is register-mapped, the message arrives as
16 writes to BLOCK0..15 and the digest leaves as 8 reads of DIGEST0..7, so no
single port of any width can carry them. The producer records each one under
`known_answer_vector_unbound`; a sweep of the WHOLE plugin for that key returns
exactly one line, the `setdefault` that writes it. `known_answer_vector_cases`
is the same. Both are written into a dict whose caller reads three other keys
and drops the rest.

So the step reported what it reports for a design with NO vectors: eight
substance-floor TBs stamped `VIBEIC_TB_ORACLE: NONE`. Two different facts, one
appearance — and the one that names a gap in the flow is the invisible one.

The reverse half is most of this file: a design that genuinely states no vector
must not be made to look as if something were missing, the emitted count and
the verdict must not move, and the refuse-to-fabricate paths must be untouched.
Those hold on BOTH trees.

Fixtures are synthetic (`widget`); nothing keys on a chip, an algorithm or a
filename.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR    # noqa: E402


def _census(report: dict) -> str:
    """Ask the tree what it reports, in a way the PRE-FIX tree can answer.

    Reached through `getattr` with the pre-fix behaviour as the default. On a
    tree without the reader the call must not raise: an AttributeError makes
    every case red, including the reverse controls, and a reverse control that
    is red for a reason unrelated to the defect has measured nothing. The
    default is the old tree's real behaviour — it contributed no
    known-answer-vector text to the step's detail line at all.
    """
    fn = getattr(DOSR, "_known_answer_vector_census", lambda _r: "")
    return fn(report)


# ===========================================================================
# forward — vectors that exist and could not be driven must be visible
# ===========================================================================
def test_unbound_vectors_are_reported_at_all():
    line = _census({"known_answer_vector_unbound": [
        {"case": "std_vec_a", "reason": "input field 'payload' (24 bits) "
                                        "binds to no input port of this DUT "
                                        "at that width"}]})
    assert line, ("three vectors the binder refused produced no report at "
                  "all — indistinguishable from a design that has none")


def test_the_report_says_the_vectors_exist():
    line = _census({"known_answer_vector_unbound": [
        {"case": "std_vec_a", "reason": "no port at that width"}]})
    assert "unbound" in line, f"the refusal count is not stated: {line!r}"
    assert "1" in line, f"the number of refused vectors is not stated: {line!r}"


def test_the_report_names_a_case_and_its_reason():
    line = _census({"known_answer_vector_unbound": [
        {"case": "std_vec_a",
         "reason": "input field 'payload' (24 bits) binds to no input port"}]})
    assert "std_vec_a" in line, f"the case is not named: {line!r}"
    assert "24 bits" in line, f"the recorded reason is not carried: {line!r}"


def test_more_than_one_refusal_is_counted_not_hidden():
    line = _census({"known_answer_vector_unbound": [
        {"case": "a", "reason": "r1"},
        {"case": "b", "reason": "r2"},
        {"case": "c", "reason": "r3"}]})
    assert "3 unbound" in line, f"the refusal count is wrong: {line!r}"
    assert "+2 more" in line, (
        f"only one of three refusals is visible and the rest vanish: {line!r}")


def test_bound_vectors_are_counted_too():
    line = _census({"known_answer_vector_cases": [
        {"case": "a", "citation": "s1"}, {"case": "b", "citation": "s2"}]})
    assert "2 bound" in line, f"successful vectors are not counted: {line!r}"


# ===========================================================================
# reverse controls — these hold on BOTH trees
# ===========================================================================
def test_a_design_with_no_vectors_says_nothing():
    """The commonest case must not be made to look as if it were missing
    something. Without this the change would add noise to every other run."""
    assert _census({}) == "", (
        "a design that states no known-answer vector was given a "
        "known-answer-vector report")
    assert _census({"scope": {"total": 8}, "dut_module": "widget"}) == "", (
        "an unrelated report grew a known-answer-vector line")


def test_empty_lists_are_the_same_as_absent():
    assert _census({"known_answer_vector_cases": [],
                    "known_answer_vector_unbound": []}) == "", (
        "empty vector lists produced a report about nothing")


def test_a_malformed_refusal_entry_does_not_crash_the_step():
    """The producer's entry shape is not this reader's to enforce; a step that
    raised here would turn a reporting gap into a run failure."""
    line = _census({"known_answer_vector_unbound": ["not-a-dict"]})
    assert "1 unbound" in line, f"a malformed entry lost the count: {line!r}"


def test_the_census_is_a_suffix_and_decides_nothing():
    """It appends to a detail line. It must not look like a verdict, and it
    must not be able to become one."""
    line = _census({"known_answer_vector_unbound": [
        {"case": "a", "reason": "r"}]})
    assert line.startswith(";"), (
        f"the census is not a suffix of the existing detail line: {line!r}")
    for word in ("PASS", "FAIL", "SKIP", "WAIVED"):
        assert word not in line, (
            f"the census emits a verdict word {word!r}: {line!r}")


def test_an_empty_census_is_the_identity_on_the_detail_line():
    """The step builds its detail line by concatenation. When there is nothing
    to say the census must leave that line byte-identical, on either tree —
    otherwise every run without vectors changes shape for no reason."""
    detail = ("emitted 8/8 unit TB(s) instantiating DUT 'widget' under "
              "/p/sim/tb for Step-4 l10_tb_conformance evidence")
    assert detail + _census({}) == detail, (
        "a run with no known-answer vectors had its detail line rewritten")


def test_success_is_never_described_as_a_refusal():
    """Vectors that DID bind must not be reported with refusal language; the
    whole point is telling the two apart, in both directions."""
    line = _census({"known_answer_vector_cases": [
        {"case": "a", "citation": "s1"}]})
    assert "could NOT be driven" not in line, (
        f"a bound vector was described as unbound: {line!r}")
    assert "unbound" not in line.replace("0 unbound", ""), (
        f"a run with no refusals reads as having some: {line!r}")
