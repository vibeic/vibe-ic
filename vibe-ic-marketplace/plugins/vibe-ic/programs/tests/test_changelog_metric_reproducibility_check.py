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

# --- the exit code is what the flow reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing in its own test file.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    the gate could have started answering 0 to every finding with the suite
    still green.
    """
    import changelog_metric_reproducibility_check as M
    # Empty findings with a FAIL verdict: the verdict is what main()
    # maps to the exit code, and constructing this module's own finding
    # dataclass by guessing its fields tests my guess, not the gate.
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("FAIL", []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import changelog_metric_reproducibility_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import changelog_metric_reproducibility_check as M
    assert M.main([str(tmp_path / "does_not_exist")]) == 2
