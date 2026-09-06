"""The challenge marker check scans SOURCE TEXT, so its reason must say so.

A challenge written as

    $display("VIBEIC_AI_CHALLENGE=%s", bad ? "FAIL" : "PASS");

prints the required marker perfectly at run time, and is still rejected, because
neither literal string appears in the file. The old reason read "verification
test must print VIBEIC_AI_CHALLENGE=PASS", which sends the author to debug the
one thing that is already correct. Measured cost: three rejected reviews in one
run before the cause was found.
"""
import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_SRC = (_PROGRAMS / "benchmark_dispatch.py").read_text(errors="replace")


def _reason_block() -> str:
    i = _SRC.find("VIBEIC_AI_CHALLENGE=PASS\" not in source")
    assert i != -1, "the marker source-check moved; re-anchor this test"
    return _SRC[i - 400: i + 1600]


def test_reason_does_not_claim_the_test_must_PRINT_the_marker():
    """RED before the fix: the reason said 'must print', which is false for the
    exact input that trips it."""
    block = _reason_block()
    assert not re.search(r'must print VIBEIC_AI_CHALLENGE', block), (
        "the reason still says the test must PRINT the marker; a format-string "
        "challenge does print it and is still rejected")


def test_reason_names_the_source_literal_requirement():
    block = _reason_block()
    assert "LITERAL" in block
    assert "contain VIBEIC_AI_CHALLENGE=PASS" in block
    assert "contain VIBEIC_AI_CHALLENGE=FAIL" in block


def test_reason_names_the_format_string_as_the_trap_and_the_remedy():
    block = _reason_block()
    assert "%s" in block, "the reason must show the format-string form that trips it"
    assert "$display" in block, "the reason must name the remedy concretely"


def test_both_markers_are_still_actually_required():
    """The message changed; the CHECK must not have been loosened."""
    block = _reason_block()
    assert '"VIBEIC_AI_CHALLENGE=PASS" not in source' in block
    assert '"VIBEIC_AI_CHALLENGE=FAIL" not in source' in block
