"""The typed known-answer-vector record, and the two doors it must keep shut.

`expected` as prose is what produced this capture — `emit_unit_tbs` carried a
case's expected value into a `//` comment — so the schema refuses a record whose
expected side is not a typed hex VALUE. And §4.05 refuses a vector read from any
design's oracle tree, by path segment rather than by convention.

CONTROL SHAPE, stated: this module is NEW, so its unit tests are necessarily
absent-symbol reds on the control tree. The load-bearing behavioural reds for
this capture live in the extractor, producer and gate commits that follow, where
both trees have the same code under test.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

AES_CASE = {
    "name": "fips197_c1_aes128_ecb",
    "kind": "known_answer_vector",
    "algorithm": "aes",
    "inputs": {"key": "000102030405060708090a0b0c0d0e0f",
               "plaintext": "00112233445566778899aabbccddeeff"},
    "expected_outputs": {"ciphertext": "69c4e0d86a7b0430d8cdb78070b4c55a"},
    "parameters": {"key_len": 128, "mode": "ECB", "operation": "encrypt"},
    "citation": "FIPS-197 Appendix C.1",
    "source": "named_public_standard",
    "evidence": "FIPS-197",
}
SHA_CASE = {
    "name": "fips1804_sha256_abc",
    "kind": "known_answer_vector",
    "algorithm": "sha2",
    "inputs": {"message": "616263"},
    "expected_outputs": {
        "digest": "ba7816bf8f01cfea414140de5dae2223"
                  "b00361a396177a9cb410ff61f20015ad"},
    "parameters": {"digest_len": 256},
    "citation": "FIPS-180-4 SHA-256 one-block example",
    "source": "input_document",
    "evidence": "input/docs/L7_verification_plan.md",
}


def test_both_corpus_shapes_express_in_one_schema():
    """(key, plaintext, ciphertext, mode) and (message, digest), unchanged."""
    import known_answer_vector as K
    assert K.validate(AES_CASE) == []
    assert K.validate(SHA_CASE) == []
    assert K.is_known_answer_vector(AES_CASE)
    assert K.is_known_answer_vector(SHA_CASE)


def test_a_prose_expected_is_refused():
    """The defect this capture is named for, at the schema door."""
    import known_answer_vector as K
    prose = dict(SHA_CASE, expected_outputs={
        "digest": "the SHA-256 digest of the message"})
    errs = K.validate(prose)
    assert errs and any("prose" in e for e in errs), errs
    assert not K.is_known_answer_vector(prose)


def test_a_vector_read_from_the_oracle_is_refused():
    """§4.05, by path segment so it holds for a tree nobody anticipated."""
    import known_answer_vector as K
    for bad in ("input/golden/aes.hjson", "input/oracle/vectors.json",
                "work/reference_model/out.txt", "input/harness/answers.py"):
        ok, why = K.vector_source_is_permitted(bad)
        assert not ok, bad
        assert "4.05" in why, why
        assert K.validate(dict(AES_CASE, evidence=bad)), bad
    ok, _ = K.vector_source_is_permitted("input/docs/L7_verification_plan.md")
    assert ok


def test_designators_are_read_off_the_document_not_guessed():
    import known_answer_vector as K
    found = K.standard_designators(
        "behaviour per NIST FIPS-197 and SP 800-38A; GCM per NIST 800-38D")
    assert "FIPS-197" in found and "SP 800-38A" in found, found
    assert K.standard_designators("a design that names no standard") == []


def test_every_shipped_standard_vector_validates():
    """A table row that cannot pass the schema could never reach a comparator."""
    import known_answer_vector as K
    tables = K.load_standard_tables()
    assert {"FIPS-197", "SP 800-38A", "FIPS-180-4"} <= set(tables), sorted(tables)
    total = 0
    for std, doc in tables.items():
        for v in doc["vectors"]:
            case = dict(v, kind=K.KIND, algorithm=doc["algorithm"],
                        source="named_public_standard", evidence=std)
            assert K.validate(case) == [], (std, v["name"], K.validate(case))
            total += 1
    assert total >= 11, total


def test_the_shipped_tables_carry_no_design_input():
    """The tables are transcriptions of public standards. A design name in one
    would mean a vector had been lifted out of a cell."""
    import known_answer_vector as K
    blob = json.dumps(K.load_standard_tables()).lower()
    for design_token in ("opentitan", "hjson", "golden", "benchmark-data"):
        assert design_token not in blob, design_token
