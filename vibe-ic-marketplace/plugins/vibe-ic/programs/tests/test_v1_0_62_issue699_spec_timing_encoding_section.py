#!/usr/bin/env python3
"""ORGANIC #699 (Bucket B) — append the "Spec timing & encoding conventions a
blind RTL author must extract" skill section to agents/ic-expert-agent.md.

This is the LLM-judgment companion to the deterministic #697
`spec_coverage_check.py`: #697 forces the self-TB to COVER each timing/encoding
dimension; #699 captures the irreducible interpretation judgment (deciding
WHICH timing/encoding the prose intends: registered-vs-comb / exact latency /
off-by-one / handshake+synchronizer / byte-order / enumerated-set boundary).

ACCEPTANCE (issue 驗收): the section is present —
  grep -q "enumerated-set" agents/ic-expert-agent.md
  && grep -qiE "registered-vs-comb|exact output latency|synchronizer" ...
  → SECTION-PRESENT

chip-AGNOSTIC: universal RTL spec-reading disciplines, no design literal.
"""
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_AGENT_MD = (Path(__file__).resolve().parents[2]
             / "agents" / "ic-expert-agent.md")


def _text():
    return _AGENT_MD.read_text(encoding="utf-8")


def test_section_present_ACCEPTANCE():
    """The 驗收 grep: 'enumerated-set' AND one of the timing tokens present."""
    t = _text()
    assert "enumerated-set" in t, "#699: enumerated-set boundary discipline missing"
    assert any(tok in t.lower() for tok in
               ("registered-vs-comb", "exact output latency", "synchronizer")), \
        "#699: timing-convention disciplines missing"


def test_all_six_disciplines_covered():
    """Every recurring mis-read class the issue enumerates is named."""
    t = _text().lower()
    for token in ("registered-vs-comb", "exact output latency", "off-by-one",
                  "handshake", "synchronizer", "byte order", "enumerated-set"):
        assert token in t, f"#699: discipline '{token}' not covered"


def test_section_is_697_companion_not_duplicate():
    """The section frames itself as the LLM-judgment companion to the
    deterministic #697 spec_coverage_check (not a re-implementation)."""
    t = _text()
    assert "#699" in t
    assert "spec_coverage_check" in t and "#697" in t, \
        "#699 section should cross-reference the #697 deterministic gate"


def test_chip_agnostic_no_design_literal():
    """The appended section carries no chip/SKU literal — universal disciplines."""
    import sys
    prog = (Path(__file__).resolve().parents[1] / "source_chip_agnostic_check.py")
    r = _pr.run([sys.executable, str(prog),
                        str(Path(__file__).resolve().parents[1].parent)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-500:]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
