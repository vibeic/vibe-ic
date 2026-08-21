"""Tests for v0.1.66 R20 capture: parity tool partial-value-match.

Captured from v0.1.65 parity loop iteration 2: L18_INTERCONNECT had
36 VALUE_MISMATCH findings, almost all of which were prefix/elaboration
variants:
  program: 'All zeros'           agent: 'All zeros (0x0)'
  program: 'Required (no default)' agent: 'Required'
  program: 'Data bus width'        agent: 'Data bus width (i.e. AxSIZE = log2(DATA_WIDTH/8))'

These are SAME meaning + extra parenthetical detail — not a discrepancy.
R20 relaxes VALUE_MISMATCH detection: when one stripped string is a
non-trivial substring of the other AND both ≥3 chars, treat as match.

Doctrine: general (no benchmark-specific), no cheating
(HALLUCINATED still counted; pure-numeric values still require exact
match to avoid '8' silently matching '88').
"""
import importlib
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "l_doc_parity_diff" in sys.modules:
        del sys.modules["l_doc_parity_diff"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("l_doc_parity_diff")


# ── Substring match — both directions ─────────────────────────────────

def test_program_is_substring_of_agent():
    """Program shorter, agent elaborated — match."""
    mod = _load()
    assert mod._is_partial_value_match("All zeros", "All zeros (0x0)")
    assert mod._is_partial_value_match("Required", "Required (no default)")
    assert mod._is_partial_value_match("Data bus width",
                                       "Data bus width (i.e. log2(...))")


def test_agent_is_substring_of_program():
    """Agent shorter, program elaborated — also match."""
    mod = _load()
    assert mod._is_partial_value_match("Required (no default)", "Required")


# ── Anti-false-positive ───────────────────────────────────────────────

def test_short_strings_not_partial_match():
    """Strings under MIN_LEN must NOT partial-match (would false-positive)."""
    mod = _load()
    assert not mod._is_partial_value_match("1", "10")
    assert not mod._is_partial_value_match("ab", "abcd")


def test_pure_numeric_requires_exact():
    """'8' must NOT silently match '88' or '888' even with min-len passed."""
    mod = _load()
    assert not mod._is_partial_value_match("888", "8")
    assert not mod._is_partial_value_match("8", "888")
    # But equal pure-numeric strings still match
    assert mod._is_partial_value_match("888", "888")


def test_non_string_values_skip_partial_match():
    """Lists, dicts, numbers — fall through to exact comparison."""
    mod = _load()
    assert not mod._is_partial_value_match([1, 2, 3], [1, 2, 3, 4])
    assert not mod._is_partial_value_match({"a": 1}, {"a": 1, "b": 2})
    assert not mod._is_partial_value_match(42, 420)


def test_distinct_strings_not_partial_match():
    """Completely-different strings — not a substring either way."""
    mod = _load()
    assert not mod._is_partial_value_match("apple", "orange")
    assert not mod._is_partial_value_match("UNKNOWN_IC", "AMBA AXI")


# ── End-to-end: VALUE_MISMATCH drops on real AMBA AXI ────────────────

def test_value_mismatch_drops_on_real_amba_axi(tmp_path):
    """Re-run l_doc_parity_diff with R20 on the real AMBA AXI generated_docs
    and confirm VALUE_MISMATCH is materially lower than the v0.1.65 baseline
    of 52 (most were partial-match cases)."""
    arm_prog = require_repo("benchmark-data/evaluation/phase1_parity/"
                            "arm_aix/phase1/generated_docs")
    arm_agnt = require_repo("benchmark-data/evaluation/phase1_parity/"
                            "arm_aix/phase1/claude_extracted")
    if not arm_prog.is_dir() or not arm_agnt.is_dir():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    mod = _load()
    _stats, findings = mod.diff_all(arm_prog, arm_agnt, source_text=None)
    from collections import Counter
    cats = Counter(f.category for f in findings)
    assert cats.get("VALUE_MISMATCH", 0) < 52, (
        f"R20 partial-match failed to reduce VALUE_MISMATCH on AMBA AXI; "
        f"got {cats.get('VALUE_MISMATCH', 0)} vs v0.1.65 baseline 52.")


# ── Honest signals still counted ─────────────────────────────────────

def test_completely_different_values_still_flagged(tmp_path):
    """Anti-cheating: when program and agent disagree on FUNDAMENTALLY
    different values, R20 must NOT suppress the finding."""
    mod = _load()
    proj = tmp_path / "prog"
    agnt = tmp_path / "agnt"
    proj.mkdir(); agnt.mkdir()
    import json
    (proj / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "Foo Protocol Specification",
    }))
    (agnt / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "Bar Protocol Specification",
    }))
    _stats, findings = mod.diff_all(proj, agnt, source_text=None)
    from collections import Counter
    cats = Counter(f.category for f in findings)
    # Foo vs Bar share 'Protocol Specification' substring — but they DON'T
    # share a prefix (one isn't a substring of the other since 'Foo' and
    # 'Bar' both prefix the common suffix). Real mismatch — must be flagged.
    assert cats.get("VALUE_MISMATCH", 0) >= 1, (
        f"R20 over-suppressed: Foo vs Bar shouldn't partial-match. "
        f"Findings: {[(f.category, f.key) for f in findings]}")
