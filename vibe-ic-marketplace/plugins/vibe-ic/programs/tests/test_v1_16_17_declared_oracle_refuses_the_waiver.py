"""A case that STATES its reference output cannot claim there is no model.

`cap:cpu_functional_oracle` is registered as covering "a `functional_vector`
L10 case ... whose oracle is the instruction-set model this pass did not
author". opentitan_aes is a counterexample: its own brief states NIST FIPS-197 /
SP 800-38A vectors, a published and machine-checkable reference output. What was
absent was a schema and a producer, not a model.

Bidirectional, and the direction that matters is BOTH: a case carrying typed
`expected_outputs` must be refused the waiver, and a case that genuinely binds
no reference output must still get it — the waiver is narrowed to what it always
claimed, not out of existence.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

KAV_CASE = {
    "name": "fips197_c1_aes128_ecb",
    "kind": "known_answer_vector",
    "inputs": {"key": "000102030405060708090a0b0c0d0e0f",
               "plaintext": "00112233445566778899aabbccddeeff"},
    "expected_outputs": {"ciphertext": "69c4e0d86a7b0430d8cdb78070b4c55a"},
    "citation": "FIPS-197 Appendix C.1",
    "source": "named_public_standard",
    "evidence": "FIPS-197",
    "expected": "the ciphertext of the FIPS-197 C.1 block",
}
NO_ORACLE_CASE = {
    "name": "boot_from_reset",
    "kind": "functional_vector",
    "expected": "the core fetches its first instruction",
}


def test_a_declared_reference_output_refuses_the_waiver():
    """The load-bearing red."""
    import l10_tb_conformance_check as C
    verdict, detail = C.resolve_case_oracle(KAV_CASE, None)
    assert verdict != "waivable", (verdict, detail)
    assert verdict == "pinned", (verdict, detail)
    assert "expected_outputs" in str(detail), detail


def test_a_case_with_no_reference_output_still_gets_the_waiver():
    """Over-reach control, and it must pass on BOTH trees: the waiver exists
    for cases that really do lack a model and keeps its scope."""
    import l10_tb_conformance_check as C
    verdict, _detail = C.resolve_case_oracle(NO_ORACLE_CASE, None)
    assert verdict != "pinned", verdict


def test_the_two_scopes_still_agree():
    """#761's invariant: the producer's kind scope and this gate's are ONE
    definition. Adding a kind to the producer must not fork them."""
    import l10_tb_conformance_check as C
    import testbench_gen as T
    assert set(C._FUNCTIONAL_VECTOR_KINDS) == set(T.SCAFFOLD_KINDS)


def test_the_new_kind_is_in_scope_for_both():
    """A `known_answer_vector` must be gradeable by the consumer and emittable
    by the producer, or it is the two-private-scopes defect one level down."""
    import l10_tb_conformance_check as C
    import testbench_gen as T
    assert "known_answer_vector" in T.SCAFFOLD_KINDS
    assert C.is_functional_vector({"kind": "known_answer_vector"})
