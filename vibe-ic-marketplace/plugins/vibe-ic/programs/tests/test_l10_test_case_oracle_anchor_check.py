"""Smoke tests for l10_test_case_oracle_anchor_check.py.

NEGATIVE CONTROL IS THE POINT. Every behaviour below is asserted in BOTH
directions: a deliberately-gutted layer must FAIL, and the well-formed
counterpart built from the SAME fixture must PASS. A test that can only
observe the passing direction cannot tell a working gate from a gate
that returns 0 unconditionally, so each pair shares one builder and
differs only in the field under test.

All fixtures are SYNTHESISED neutral data. No real design's files, no
vendor part number, no PDK name, no pin literal from any shipped design
appears here.
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "l10_test_case_oracle_anchor_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import l10_test_case_oracle_anchor_check as chk  # noqa: E402


# ---------------------------------------------------------------------------
# fixture builders — synthesised, neutral
# ---------------------------------------------------------------------------
def _docs(tmp_path):
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_sibling(docs, name="L17_CHANNEL_SIGNal.json", signals=None):
    """A neutral sibling L-doc that DECLARES observable names.

    This is what makes the OBSERVABLE anchor family derivable at run time
    instead of hardcoded.
    """
    signals = signals or ["widget_ready", "widget_error", "frob_count"]
    (docs / name).write_text(json.dumps(
        {"signals": [{"name": s, "direction": "output"} for s in signals]}))


def _write_l10(docs, cases):
    (docs / "L10_TEST_CASES.json").write_text(
        json.dumps({"test_cases": cases}, ensure_ascii=False))


def _run(tmp_path):
    return chk.main([str(tmp_path)])


def _errors(tmp_path):
    docs = _docs(tmp_path)
    rep = chk.audit(docs / "L10_TEST_CASES.json", docs)
    return [f["category"] for f in rep["findings"] if f["severity"] == "ERROR"]


# ---------------------------------------------------------------------------
# 1. ORACLE ANCHOR — the core semantic claim
# ---------------------------------------------------------------------------
_GOOD_CASE = {
    "name": "tc_frob_readback",
    "kind": "functional_vector",
    "stimulus": "drive a frob request",
    "expected": "widget_ready asserted and frob_count == 8'h2A",
}


def test_anchored_case_passes(tmp_path):
    docs = _docs(tmp_path)
    _write_sibling(docs)
    _write_l10(docs, [dict(_GOOD_CASE)])
    assert _run(tmp_path) == 0
    assert _errors(tmp_path) == []


def test_NEGATIVE_control_unanchored_expected_fails(tmp_path):
    """GUTTED: same case, expected text stripped of every anchor family."""
    docs = _docs(tmp_path)
    _write_sibling(docs)
    gutted = dict(_GOOD_CASE)
    gutted["expected"] = "behaves as described in the plan"
    _write_l10(docs, [gutted])
    assert _run(tmp_path) == 1
    assert "NO_ORACLE_ANCHOR" in _errors(tmp_path)


def test_literal_only_anchor_passes(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_lit", "kind": "functional_vector",
                       "stimulus": "x", "expected": "returns 0xDEAD"}])
    assert _run(tmp_path) == 0


def test_bare_hex_digest_is_a_literal_anchor(tmp_path):
    """A space-separated digest carries no 0x prefix but IS an oracle.

    Regression guard: an earlier draft of the literal rule required a
    0x prefix or a unit, and would have rejected a perfectly checkable
    expected digest. Synthesised digest, not copied from any design.
    """
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_digest", "kind": "functional_vector",
                       "stimulus": "hash an empty message",
                       "expected": "a1b2c3d4 e5f60718 293a4b5c 6d7e8f90"}])
    assert _run(tmp_path) == 0


def test_relation_only_anchor_passes(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_rel", "kind": "functional_vector",
                       "stimulus": "write then read",
                       "expected": "readback value == written value"}])
    assert _run(tmp_path) == 0


def test_observable_anchor_is_derived_not_hardcoded(tmp_path):
    """Same expected text: anchors only when a sibling DECLARES the name.

    This is the both-directions proof that the OBSERVABLE family comes
    from the design's own inputs. Nothing about the text changes between
    the two halves — only whether the run declares the name.
    """
    docs = _docs(tmp_path)
    case = {"name": "tc_obs", "kind": "functional_vector",
            "stimulus": "assert request", "expected": "widget_ready follows"}
    _write_l10(docs, [case])
    assert _run(tmp_path) == 1, "undeclared name must not anchor"
    assert "NO_ORACLE_ANCHOR" in _errors(tmp_path)

    _write_sibling(docs)  # now the design declares widget_ready
    assert _run(tmp_path) == 0, "declared name must anchor"
    assert _errors(tmp_path) == []


# ---------------------------------------------------------------------------
# 2. HANDLE
# ---------------------------------------------------------------------------
def test_legal_unique_handle_passes(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [
        {"name": "tc_a", "kind": "functional_vector", "expected": "0x01"},
        {"name": "tc_b", "kind": "functional_vector", "expected": "0x02"},
    ])
    assert _run(tmp_path) == 0


def test_NEGATIVE_control_illegal_handle_fails(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [
        {"name": "tc a/b", "kind": "functional_vector", "expected": "0x01"}])
    assert _run(tmp_path) == 1
    assert "ILLEGAL_HANDLE" in _errors(tmp_path)


def test_NEGATIVE_control_duplicate_handle_fails(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [
        {"name": "tc_dup", "kind": "functional_vector", "expected": "0x01"},
        {"name": "tc_dup", "kind": "functional_vector", "expected": "0x02"},
    ])
    assert _run(tmp_path) == 1
    assert "DUPLICATE_HANDLE" in _errors(tmp_path)


def test_NEGATIVE_control_missing_handle_fails(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"kind": "functional_vector", "expected": "0x01"}])
    assert _run(tmp_path) == 1
    assert "NO_HANDLE" in _errors(tmp_path)


# ---------------------------------------------------------------------------
# 3. DISTINCTNESS
# ---------------------------------------------------------------------------
def test_NEGATIVE_control_expected_restating_stimulus_fails(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_echo", "kind": "functional_vector",
                       "stimulus": "drive 0x55", "expected": "drive 0x55"}])
    assert _run(tmp_path) == 1
    assert "EXPECTED_RESTATES_STIMULUS" in _errors(tmp_path)


def test_NEGATIVE_control_checkmark_expected_fails(tmp_path):
    """A tick mark is the purest form of a case that credits itself."""
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_tick", "kind": "functional_vector",
                       "stimulus": "release reset", "expected": "✅"}])
    assert _run(tmp_path) == 1
    assert "VACUOUS_EXPECTED" in _errors(tmp_path)


def test_NEGATIVE_control_empty_expected_fails(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_empty", "kind": "functional_vector",
                       "stimulus": "s", "expected": ""}])
    assert _run(tmp_path) == 1
    assert "NO_EXPECTED" in _errors(tmp_path)


# ---------------------------------------------------------------------------
# 4. SCOPE — the exemption must be granted by the DESIGN, not by a waiver
# ---------------------------------------------------------------------------
def test_doc_kind_entry_is_skipped_honestly(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "vi_entry", "kind": "verification_intent",
                       "stimulus": "n/a", "expected": "intent satisfied"}])
    assert _run(tmp_path) == 0
    rep = chk.audit(docs / "L10_TEST_CASES.json", docs)
    assert rep["summary"]["cases_doc_kind_skipped"] == 1
    assert rep["summary"]["cases_executable"] == 0


def test_NEGATIVE_control_same_entry_as_functional_vector_fails(tmp_path):
    """Identical text, executable kind => must FAIL.

    Proves the doc-kind skip is a scope rule and not a hole: the only
    difference between this and the previous test is the design's own
    declared kind.
    """
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "vi_entry", "kind": "functional_vector",
                       "stimulus": "n/a", "expected": "intent satisfied"}])
    assert _run(tmp_path) == 1
    assert "NO_ORACLE_ANCHOR" in _errors(tmp_path)


# ---------------------------------------------------------------------------
# 5. SKIP paths must not masquerade as PASS
# ---------------------------------------------------------------------------
def test_missing_l10_skips(tmp_path):
    _docs(tmp_path)
    assert chk.main([str(tmp_path)]) == 2


def test_empty_case_array_skips(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [])
    assert chk.main([str(tmp_path)]) == 2


# ---------------------------------------------------------------------------
# 6. Waiver
# ---------------------------------------------------------------------------
def test_waiver_suppresses_only_with_a_real_justification(tmp_path):
    docs = _docs(tmp_path)
    _write_l10(docs, [{"name": "tc_x", "kind": "functional_vector",
                       "stimulus": "s", "expected": "no anchor at all here"}])
    assert _run(tmp_path) == 1

    (tmp_path / "waivers.json").write_text(json.dumps({chk.WAIVER_KEY: "too short"}))
    assert _run(tmp_path) == 1, "a stub justification must not waive"

    (tmp_path / "waivers.json").write_text(json.dumps({
        chk.WAIVER_KEY: "x" * (chk.WAIVER_MIN + 1)}))
    assert _run(tmp_path) == 0
