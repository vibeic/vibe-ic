"""The full-stack results.json top-level verdict must follow its own evidence.

THE DEFECT, AS PUBLISHED
========================
`_finalize_full_stack_results` computed the top-level `verdict` / `pass` pair
from ONE input — the caller's `connectivity_pass` argument — and wrote it
beside the functional evidence it says nothing about. The published record
therefore read

    "verdict": "PASS", "pass": true,
    "functional_verified": false, "vectors_passed": 0, "vectors_failed": 8

which is a document asserting a pass while its own fields state that nothing
was verified. Measured on this fleet: 338 of 481 published
`sim_full_stack/results.json` carry exactly that shape.

WHAT THE FIX IS
===============
`verdict` / `pass` become a FUNCTION of the evidence in the same object.
`connectivity_verified` — which this producer already published — keeps the
connectivity truth, so nothing that was measured is lost; what goes away is the
unqualified word PASS standing over unverified evidence.

The vocabulary is the schema's OWN: `PASS`, `FAIL` and `UNVERIFIED` are the
per-vector verdict words this same producer emits and the bit-level oracle gate
already reads (`bit_level_full_stack_tb_oracle_check` counts vectors whose
verdict is `UNVERIFIED`). No fourth word is introduced.

chip-AGNOSTIC: pure record-consistency over the producer's own fields.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402


def _unverified_vectors(n: int) -> list[dict]:
    return [{"vector_id": f"v{i}", "expected_bytes": None,
             "actual_bytes": None, "verdict": "UNVERIFIED"} for i in range(n)]


def _golden_vectors(n: int) -> list[dict]:
    return [{"vector_id": f"v{i}", "expected_bytes": ["0x0" + str(i % 10)],
             "actual_bytes": ["0x0" + str(i % 10)], "verdict": "PASS"}
            for i in range(n)]


def _finalize(per_vector, **kw):
    return dosr._finalize_full_stack_results(
        per_vector,
        tb_name=kw.pop("tb_name", "tb.v"),
        dut=kw.pop("dut", "top"),
        source=kw.pop("source", "unit-test"),
        evidence=kw.pop("evidence", "unit-test evidence"),
        opcodes_tested=kw.pop("opcodes_tested", ["0x01"]),
        **kw)


def test_a_record_with_nothing_verified_may_not_publish_the_word_pass():
    """THE DEFECT. Eight UNVERIFIED vectors, 0 passed, 8 failed."""
    r = _finalize(_unverified_vectors(8), connectivity_pass=True)

    assert r["functional_verified"] is False
    assert r["vectors_passed"] == 0
    assert r["vectors_failed"] == 8

    assert r["verdict"] != "PASS", (
        f"verdict={r['verdict']!r} published beside functional_verified="
        f"{r['functional_verified']}, vectors_passed={r['vectors_passed']}, "
        f"vectors_failed={r['vectors_failed']}")
    assert r["pass"] is not True, "pass:true over zero verified vectors"


def test_the_unverified_record_says_unverified_not_fail():
    """Nothing was disproved either — the word has to be the honest one.

    `FAIL` would claim a measured disagreement between the design and a golden.
    None was measured here: there is no golden to disagree with.
    """
    r = _finalize(_unverified_vectors(8), connectivity_pass=True)
    assert r["verdict"] == "UNVERIFIED"


def test_a_measured_golden_mismatch_is_a_fail_not_merely_unverified():
    """A vector that DID carry a golden and did not match is a real failure."""
    vecs = _golden_vectors(3)
    vecs[1]["actual_bytes"] = ["0xff"]
    vecs[1]["verdict"] = "FAIL"
    r = _finalize(vecs, connectivity_pass=True)
    assert r["functional_verified"] is False
    assert r["verdict"] == "FAIL"
    assert r["pass"] is False


def test_pass_survives_when_the_evidence_actually_supports_it():
    """PAIRED GUARD — the fix must not turn a genuinely verified run red."""
    r = _finalize(_golden_vectors(8), connectivity_pass=True)
    assert r["functional_verified"] is True
    assert r["vectors_passed"] == 8
    assert r["verdict"] == "PASS"
    assert r["pass"] is True


def test_the_connectivity_truth_is_still_published_under_its_own_name():
    """PAIRED GUARD — nothing measured is lost, it is only named correctly.

    A consumer that wants the connectivity question answered still has the
    field this producer has always written for it.
    """
    r = _finalize(_unverified_vectors(8), connectivity_pass=True)
    assert r["connectivity_verified"] is True
    r2 = _finalize(_unverified_vectors(8), connectivity_pass=False)
    assert r2["connectivity_verified"] is False
    assert r2["verdict"] == "FAIL"


def test_a_failed_connectivity_run_is_never_promoted_by_the_new_rule():
    """PAIRED GUARD — the rule may only ever be stricter than the old one."""
    r = _finalize(_golden_vectors(8), connectivity_pass=False)
    assert r["verdict"] == "FAIL"
    assert r["pass"] is False
