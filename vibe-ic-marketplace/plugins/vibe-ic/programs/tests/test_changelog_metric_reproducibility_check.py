"""Tests for changelog_metric_reproducibility_check (v1.6.38)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from programs.changelog_metric_reproducibility_check import audit


def _mk_plugin(tmp_path: Path, changelog: str = "",
               source_files: dict = None) -> Path:
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    if changelog:
        (root / "CHANGELOG.md").write_text(textwrap.dedent(changelog))
    for rel, body in (source_files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return root


def test_metric_appears_in_source_passes(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path,
        changelog="v1.6.x — IR drop peak 5.231 mV measured.\n",
        source_files={
            "programs/ir.py": """
                def emit_ir(power_pw):
                    drop_mv = power_pw * 0.001
                    print(f"peak {5.231} mV computed")
                    return drop_mv
            """,
        })
    v, findings = audit(root)
    assert v == "PASS", findings


def test_metric_missing_from_source_fails(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path,
        changelog="v1.6.x — IR drop peak 5.231 mV measured.\n",
        source_files={
            "programs/ir.py": """
                def emit_ir(power_pw):
                    return power_pw * 0.001
            """,
        })
    v, findings = audit(root)
    assert v == "FAIL"
    assert any("5.231" in f.metric for f in findings)


def test_no_changelog_is_vacuous(tmp_path: Path) -> None:
    """Without CHANGELOG.md the gate stays out of the way."""
    root = _mk_plugin(tmp_path, changelog="",
                      source_files={"programs/p.py": "x = 1"})
    v, findings = audit(root)
    assert v == "VACUOUS_PASS"


def test_multiple_metrics_some_unreproducible(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path,
        changelog=(
            "v1.6.x — IR 5.231 mV, EM 0.018 mA/μm, DFT 70%\n"
        ),
        source_files={
            "programs/p.py": """
                def emit():
                    a = 5.231
                    b = 70
                    return a, b
            """,
        })
    v, findings = audit(root)
    # 0.018 isn't reproduced anywhere; should be flagged
    assert v == "FAIL"
    assert any("0.018" in f.metric for f in findings)


def test_metric_in_test_fixture_satisfies(tmp_path: Path) -> None:
    """Metric appearing in tests/ is acceptable evidence."""
    root = _mk_plugin(tmp_path,
        changelog="v1.6.x — DFT 70% coverage\n",
        source_files={
            "tests/test_dft.py": """
                def test_dft():
                    coverage = 70.0
                    assert coverage > 50
            """,
        })
    v, findings = audit(root)
    assert v == "PASS", findings


def test_percent_unit_recognised(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path,
        changelog="v1.6.x — coverage 70%\n",
        source_files={"programs/p.py": "x = 1"})
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.metric.endswith("%") for f in findings)


def test_unit_units_variants_recognised(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path,
        changelog="EM 0.018 mA/um — see source\n",
        source_files={"programs/p.py": "x = 0.018"})
    v, findings = audit(root)
    assert v == "PASS"
