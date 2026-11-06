"""The known-answer-vector census describes what the ladder EMITTED.

MEASURED (sha256 x sky130A, front door): `l10_unit_tb_gen` reported

    known-answer vectors: 0 bound, 3 unbound -- the vectors exist and could
    NOT be driven, e.g. fips1804_sha256_abc: ... register-bus route: this
    driver drives a (plaintext -> ciphertext) block vector ...

while all three FIPS known-answer TBs had been written, by the next rung of
the same ladder (`_emit_case_stated_vector_bus`), and passed. The known-answer
rung records its refusal before the ladder moves on; the census read that
intermediate refusal as the case's final state.

Drives the real ladder (`testbench_gen.emit_unit_tbs`) over the stated-vector
fixture the landed R-0915-113(2) deck transcribes, then the runner's own
census over the producer's report.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import testbench_gen as T                                        # noqa: E402
import test_r0915_113_2_a_stated_vector_over_the_declared_bus as SV  # noqa: E402


#: The known-answer row exactly as Phase 1 emits it (the deck's transcription
#: omits `source`, and `known_answer_vector.validate` then refuses the kind,
#: so the known-answer rung never runs and never records a refusal).
ABC = dict(SV.ABC, source="named_public_standard", algorithm="sha2",
           evidence="FIPS-180-4",
           transport={"kind": "undeclared",
                      "evidence": "neither L9.interface_type nor L3.opcodes "
                                  "is stated"})
CASES = [ABC] + [c for c in SV.CASES if c["name"] != ABC["name"]]


def _run(tmp_path: Path) -> dict:
    import json
    p = SV._project(tmp_path)
    # the producer reads the cases from the project's L10, not an argument
    (p / "phase1" / "generated_docs" / "L10_TEST_CASES.json").write_text(
        json.dumps({"schema_version": 2, "doc_class": "test_cases",
                    "ic_name": "sha256", "test_cases": CASES}))
    T._L4_CACHE.clear()
    report: dict = {}
    T.emit_unit_tbs(p, "sha256", report=report)
    return report


def test_a_vector_a_later_rung_drove_is_not_reported_unbound(tmp_path):
    """RED on main: the ABC vector is in known_answer_vector_unbound."""
    report = _run(tmp_path)
    driven = {c["case"] for c in report.get("stated_vector_cases", [])}
    assert ABC["name"] in driven                      # it WAS emitted
    unbound = {c.get("case") for c in
               report.get("known_answer_vector_unbound", [])}
    assert ABC["name"] not in unbound, report.get(
        "known_answer_vector_unbound")


def test_the_driven_vector_says_which_rung_drove_it_and_why_the_first_refused(
        tmp_path):
    report = _run(tmp_path)
    rows = {c["case"]: c for c in report.get("known_answer_vector_cases", [])}
    row = rows.get(ABC["name"])
    assert row is not None, report.get("known_answer_vector_cases")
    assert row["driven_by"] == "_emit_case_stated_vector_bus"
    assert "binds to no input port" in row["first_refusal"]
