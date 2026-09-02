"""Phase 1 now has somewhere to put a DECLARED reference output.

`opentitan_aes` states "NIST FIPS-197 / SP 800-38A 標準測試向量 ... 經自建 TB 由
TL-UL register interface 驅動" in its own brief, and L10 came back with 103 rows
— every one a DV process checklist milestone, none of them that sentence.

Bidirectional: a design that NAMES a standard whose algorithm it also declares
gets typed vectors; a design that names none gets none and says so, because the
honest `cap:cpu_functional_oracle` route must stay reachable and no vector may
be manufactured.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]

DECLARES = """# widget hash core

## 7.1 Functional verification

The core computes SHA-256 over the message block. Conformance is measured
against the NIST FIPS-180-4 test vectors.
"""

DECLARES_NONE = """# widget hash core

## 7.1 Functional verification

The core computes a digest over the message block. Conformance is measured
against the reference implementation supplied by the customer.
"""


def _run_phase1(tmp_path, doc: str, name="widget"):
    proj = tmp_path / "proj"
    d = proj / "input" / "docs"
    d.mkdir(parents=True)
    (d / "L7_verification_plan.md").write_text(doc)
    (proj / "input" / "phase1_prompt.md").write_text(
        "Build a hash core with a register-mapped interface.\n")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(proj), "--ic-name", name],
        capture_output=True, text=True, timeout=1800)
    l10 = json.loads((proj / "phase1" / "generated_docs"
                      / "L10_TEST_CASES.json").read_text())
    return r, l10


def _vectors(l10):
    return [c for c in l10.get("test_cases") or []
            if c.get("kind") == "known_answer_vector"]


def test_a_named_standard_becomes_typed_l10_vectors(tmp_path):
    """The load-bearing red."""
    _r, l10 = _run_phase1(tmp_path, DECLARES)
    vecs = _vectors(l10)
    assert vecs, json.dumps(l10.get("known_answer_vector_census"))
    for v in vecs:
        # expected is a VALUE, not prose — the whole point of the capture.
        assert v["expected_outputs"], v
        for field, val in v["expected_outputs"].items():
            int(val, 16)
        assert v["inputs"], v
        assert v["citation"], v
        assert v["source"] == "named_public_standard", v
    names = {v["name"] for v in vecs}
    assert "fips1804_sha256_abc" in names, sorted(names)


def test_a_design_naming_no_standard_gets_no_vectors_and_says_so(tmp_path):
    """Over-reach control, and it must pass on BOTH trees: the honest
    no-oracle route stays reachable and nothing is manufactured."""
    _r, l10 = _run_phase1(tmp_path, DECLARES_NONE)
    assert _vectors(l10) == []
    census = l10.get("known_answer_vector_census")
    if census is not None:            # absent on a tree without the extractor
        assert census.get("standards_named_by_the_input") == [], census


def test_the_census_is_published_even_when_it_finds_nothing(tmp_path):
    """A reader must be able to tell "no oracle was declared" from "one was
    declared and nothing extracted it"."""
    _r, l10 = _run_phase1(tmp_path, DECLARES_NONE)
    assert "known_answer_vector_census" in l10, sorted(l10)
    assert l10.get("known_answer_vector_count") == 0, l10.get(
        "known_answer_vector_count")


def test_the_algorithm_gate_is_real(tmp_path):
    """A standard the design names but whose algorithm it does not declare
    yields nothing — citing SP 800-38D for a counter definition must not hand a
    design AES vectors it never asked for."""
    import known_answer_vector as K
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    vecs, named = K.vectors_from_named_standards(
        "The counter follows NIST SP 800-38A Appendix B.1.")
    assert "SP 800-38A" in named, named
    assert vecs == [], [v["name"] for v in vecs]
    vecs2, _ = K.vectors_from_named_standards(
        "An AES-128 core per NIST SP 800-38A Appendix F.")
    assert vecs2, "the same standard WITH the algorithm declared must resolve"
