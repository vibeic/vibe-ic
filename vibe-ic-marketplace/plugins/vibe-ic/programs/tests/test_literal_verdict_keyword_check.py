"""Tests for literal_verdict_keyword_check (v1.6.38 anti-fabrication gate)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from programs.literal_verdict_keyword_check import audit


def _mk_plugin(tmp_path: Path, code: str) -> Path:
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "module.py").write_text(textwrap.dedent(code))
    return root


def test_hardcoded_coverage_pct_caught(tmp_path: Path) -> None:
    """The v1.6.37 DFT escape: `coverage_pct = 70.0` literal."""
    root = _mk_plugin(tmp_path, """
        def emit_dft_scan_chain(project):
            coverage_pct = 70.0
            return coverage_pct
    """)
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.attribute == "coverage_pct" for f in findings)


def test_hardcoded_jmax_caught(tmp_path: Path) -> None:
    """The v1.6.37 EM escape: `j_max_ma_per_um = 2.0` literal."""
    root = _mk_plugin(tmp_path, """
        def emit_em_report(project):
            j_max = 2.0
            return j_max
    """)
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.attribute == "j_max" for f in findings)


def test_source_comment_satisfies(tmp_path: Path) -> None:
    """Same line `# source:` annotation accepts the literal."""
    root = _mk_plugin(tmp_path, """
        def emit_em_report(project):
            j_max = 2.0  # source: input/pdk/spice/HSPICE/SOA.lib
            return j_max
    """)
    v, findings = audit(root)
    assert v == "PASS", findings


def test_source_comment_above_line_satisfies(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, """
        def emit_em_report(project):
            # source: input/pdk/spice/HSPICE/SOA.lib (M1-M4 EM, 110C, 10yr)
            j_max = 2.0
            return j_max
    """)
    v, findings = audit(root)
    assert v == "PASS"


def test_computed_from_satisfies(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, """
        def emit_ir_drop(project, peak):
            # computed_from: peak * grid_resistance
            drop_mv = peak * 1e3
            threshold_mv = 50.0  # default: 5% of 1.0V Vdd budget
            return drop_mv, threshold_mv
    """)
    v, findings = audit(root)
    assert v == "PASS"


def test_non_emitter_function_not_audited(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, """
        def helper():
            coverage_pct = 70.0
            return coverage_pct
    """)
    v, findings = audit(root)
    assert v == "PASS"


def test_non_watched_attribute_ignored(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, """
        def emit_widget(project):
            chunk_size = 1024
            return chunk_size
    """)
    v, findings = audit(root)
    assert v == "PASS"


def test_docstring_annotation_suppresses(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, '''
        def emit_si(project):
            """Compute SI. literal-verdict: reviewed."""
            coupling_ratio = 0.10
            return coupling_ratio
    ''')
    v, findings = audit(root)
    assert v == "PASS"


def test_no_programs_dir_is_vacuous(tmp_path: Path) -> None:
    v, findings = audit(tmp_path / "empty")
    assert v == "VACUOUS_PASS"
