"""Tests for v0.1.64 R17 capture: SUMMARY denominator must reflect the
canonical L-doc taxonomy size, not the obsolete hardcoded 14.

Captured from v0.1.63 AMBA AXI re-run: runner output 'L docs emitted: 24/14'
because R14 (L14-L18 wiring) and R15 (L19-L23 skeleton) raised the actual
emission target past the v1.6.x baseline of 14. A N/14 print with N > 14
is misleading.
"""
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def test_summary_no_longer_hardcodes_14():
    """The literal '/14' must NOT appear in the SUMMARY print after R17."""
    src = RUNNER.read_text()
    # Find the SUMMARY print line
    m = re.search(r"print\(f.L docs emitted: \{len\(results\)\}/(\S+)\)", src)
    assert m is not None, (
        "SUMMARY print line shape changed — update this test to match.")
    denom_expr = m.group(1)
    assert denom_expr != "14", (
        f"SUMMARY still hardcodes /14; should be dynamic via l_doc_taxonomy. "
        f"Got expression {denom_expr!r}")


def test_summary_uses_taxonomy_count():
    """The denominator must derive from l_doc_taxonomy.all_l_doc_codes()
    (currently 28: L1-L13 + L8C/L8T split + L14-L23 + L24-L27)."""
    src = RUNNER.read_text()
    assert "all_l_doc_codes" in src, (
        "SUMMARY must call all_l_doc_codes() so it stays correct when "
        "the taxonomy grows.")


def test_taxonomy_currently_28_codes():
    """ANTI-REGRESSION: pin the current size so a future taxonomy expansion
    that breaks this test forces an audit. #157 grew the taxonomy from 24 to
    28 by folding the L24-L27 completeness extensions into L_DOCS_V2."""
    if "l_doc_taxonomy" in sys.modules:
        del sys.modules["l_doc_taxonomy"]
    sys.path.insert(0, str(PROGRAMS))
    import l_doc_taxonomy
    codes = l_doc_taxonomy.all_l_doc_codes()
    assert len(codes) == 28, (
        f"Taxonomy size changed from 28 to {len(codes)}. If this was "
        f"intentional, update this test's pinned value. If accidental, "
        f"check what L doc was added/removed.")


def test_summary_print_handles_taxonomy_unavailable():
    """If l_doc_taxonomy import fails at runtime, the SUMMARY must still
    emit (fall back to 14, the pre-R17 baseline)."""
    src = RUNNER.read_text()
    # The print site must be guarded by try/except around the taxonomy import
    m = re.search(r"try:\s*\n\s+from l_doc_taxonomy import all_l_doc_codes",
                  src)
    assert m is not None, (
        "Taxonomy import must be inside a try/except so a missing module "
        "doesn't crash the SUMMARY print.")
