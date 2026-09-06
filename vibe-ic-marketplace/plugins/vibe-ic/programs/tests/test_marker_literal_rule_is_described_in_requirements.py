"""The source-literal marker rule the rejection reason relies on is DESCRIBED.

v1.17.67 fixed the rejection reason (it now names the LITERAL-in-source
requirement instead of claiming the test "must print" a marker it does print)
but did not describe that requirement anywhere in the task the author reads
BEFORE writing the challenge. The envelope contract
(``test_review_envelope_contract.py``) went red on exactly that: the term
'LITERAL' appeared in a reason and in no requirement.

This module pins the other half so the description cannot be dropped again
without a named failure: the task's own ``review_requirements`` states, up
front, that both markers are matched against the challenge SOURCE TEXT.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_CONTRACT = _PROGRAMS / "tests" / "test_review_envelope_contract.py"
_spec = importlib.util.spec_from_file_location("_envelope_contract", _CONTRACT)
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)


def _requirements(tmp_path: Path) -> dict:
    return _contract._task(tmp_path)["review_requirements"]


def test_the_marker_rule_states_it_is_a_source_text_check(tmp_path):
    rule = _requirements(tmp_path)["semantic_fail_verification_test"]
    assert "marker_form" in rule, (
        "the task must describe HOW the markers are matched, not only WHICH "
        "strings they are")
    text = rule["marker_form"]
    assert "LITERAL" in text
    assert "SOURCE" in text.upper()
    assert "%s" in text, "the description must show the form that trips it"
    assert "$display" in text, "the description must name the remedy"


def test_both_marker_strings_stay_named_beside_the_rule(tmp_path):
    rule = _requirements(tmp_path)["semantic_fail_verification_test"]
    assert rule["pass_marker"] == "VIBEIC_AI_CHALLENGE=PASS"
    assert rule["fail_marker"] == "VIBEIC_AI_CHALLENGE=FAIL"


def test_the_description_reaches_the_blob_the_contract_test_reads(tmp_path):
    """The contract test searches the whole serialized requirements; the
    description is worthless to it if it is not serializable there."""
    assert "LITERAL" in json.dumps(_requirements(tmp_path))
