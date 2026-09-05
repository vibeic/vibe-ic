"""The anchor gate must read the TYPED `(inputs, expected_outputs)` oracle pair.

A `known_answer_vector` case pins its answer as a mapping of output name to
literal — the sharpest anchor a case can carry. `known_answer_vector.py:35`
documents the field, `known_answer_vector_tb_gen.py` / `oracle_tb_gen.py` /
`register_bus_driver_gen.py` build the comparison from it, and the sibling gate
`l10_tb_conformance_check._PINNED_ORACLE_FIELDS` already registers it.

`l10_test_case_oracle_anchor_check._EXPECT_KEYS` did not, so such a case was
reported `NO_EXPECTED` — "a TB built from it cannot fail" — while a TB
generator standing next to it built exactly that comparison. Its
`_STIMULUS_KEYS` already carried the plural `inputs`, so the gate read the
stimulus half of the pair and not the answer half.

MEASURED (opentitan_aes, v1.17.22): 8 of 8 executable cases NO_EXPECTED, gate
rc=1, Phase-1 stage compliance FAIL, Step 2 of the Phase-2 audit FAIL.

BOTH DIRECTIONS: widening a roster can only find more anchors, so the tests
that matter are the ones proving it still REFUSES — an absent expectation and
an alphanumeric-free one. All fixtures are synthesised and neutral.
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "l10_test_case_oracle_anchor_check.py"
sys.path.insert(0, str(SCRIPT.parent))
import l10_test_case_oracle_anchor_check as chk  # noqa: E402


def _build(tmp_path, case):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
        {"signals": [{"name": "widget_result", "direction": "output"}]}))
    (docs / "L10_TEST_CASES.json").write_text(
        json.dumps({"test_cases": [case]}, ensure_ascii=False))
    return chk.audit(docs / "L10_TEST_CASES.json", docs)


def _cats(rep):
    return [f["category"] for f in rep["findings"] if f["severity"] == "ERROR"]


_TYPED_PAIR = {
    "name": "kav_typed_pair",
    "kind": "known_answer_vector",
    "inputs": {"key": "112233445566778899aabbccddeeff00",
               "block": "0f1e2d3c4b5a69788796a5b4c3d2e1f0"},
    "expected_outputs": {"widget_result": "a1b2c3d4e5f60718293a4b5c6d7e8f90"},
}


def test_typed_pair_anchors(tmp_path):
    cats = _cats(_build(tmp_path, dict(_TYPED_PAIR)))
    # Pre-fix this was ["NO_EXPECTED"].
    assert "NO_EXPECTED" not in cats, (
        f"a case pinning its answer in `expected_outputs` carries an oracle; "
        f"got {cats}")
    assert cats == [], f"expected a clean anchor, got {cats}"


def test_every_roster_name_the_sibling_gate_registers_is_readable(tmp_path):
    # Membership, not count: each field the sibling gate calls a PINNED oracle
    # must be one this gate can read as an expectation.
    import l10_tb_conformance_check as sib
    missing = [f for f in sib._PINNED_ORACLE_FIELDS
               if f not in chk._EXPECT_KEYS]
    assert missing == [], (
        f"these pinned-oracle field name(s) are unreadable by the anchor "
        f"gate: {missing}")


def test_a_case_with_no_expectation_at_all_still_refuses(tmp_path):
    case = {k: v for k, v in _TYPED_PAIR.items() if k != "expected_outputs"}
    case["name"] = "kav_no_answer"
    assert "NO_EXPECTED" in _cats(_build(tmp_path, case))


def test_an_empty_expected_outputs_mapping_still_refuses(tmp_path):
    case = dict(_TYPED_PAIR)
    case["name"] = "kav_empty_answer"
    case["expected_outputs"] = {}
    cats = _cats(_build(tmp_path, case))
    assert cats and cats[0] in ("NO_EXPECTED", "VACUOUS_EXPECTED"), (
        f"an empty answer mapping is not an oracle; got {cats}")


def test_an_alphanumeric_free_expected_outputs_still_refuses(tmp_path):
    case = dict(_TYPED_PAIR)
    case["name"] = "kav_bullet_answer"
    case["expected_outputs"] = {"widget_result": "--"}
    assert "VACUOUS_EXPECTED" in _cats(_build(tmp_path, case))
