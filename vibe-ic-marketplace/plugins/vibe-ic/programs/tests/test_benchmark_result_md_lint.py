"""Tests for benchmark_result_md_lint.py (open-benchmark-methodology § 6)."""
from __future__ import annotations

import benchmark_result_md_lint as mod

# A RESULT.md that hits all seven mandatory sections.
FULL = """\
# Benchmark RESULT

## Headline
Score: 152/156 pass@1; denominator 156; what was measured: functional pass.

## Shape
Shape C — gates.py entry point.

## Score trajectory
Single-shot 149/156; close-loop stage 1 added 3.

## Residual triage
Every fail mapped to category A-H. 062 is Category A (FLOOR); 099 Category D.
The rest are agent-fixable.

## Tool substitution
We substitute iverilog 12 for Synopsys VCS sim.

## Reproduce
Command line: `python3 gates.py`; dataset path /data/verilogeval.

## Sequence / plan status
Per open-benchmark.md roadmap; RTL-Repo intentionally skipped (out-of-scope).
"""


def test_full_result_md_pass(tmp_path):
    p = tmp_path / "RESULT.md"
    p.write_text(FULL)
    rc = mod.main([str(p)])
    assert rc == 0


def test_missing_file_fail(tmp_path):
    rc = mod.main([str(tmp_path / "absent.md")])
    assert rc == 1


def test_empty_file_fail(tmp_path):
    p = tmp_path / "RESULT.md"
    p.write_text("\n\n  \n")
    rc = mod.main([str(p)])
    assert rc == 1


def test_missing_residual_triage_fail(tmp_path):
    # Drop the entire residual-triage section.
    text = FULL.replace(
        "## Residual triage\n"
        "Every fail mapped to category A-H. 062 is Category A (FLOOR); 099 Category D.\n"
        "The rest are agent-fixable.\n", "")
    p = tmp_path / "RESULT.md"
    p.write_text(text)
    rc = mod.main([str(p)])
    assert rc == 1
    missing = mod.lint_text(text)
    assert "residual_triage" in missing


def test_missing_tool_substitution_fail(tmp_path):
    text = FULL.replace(
        "## Tool substitution\n"
        "We substitute iverilog 12 for Synopsys VCS sim.\n", "")
    p = tmp_path / "RESULT.md"
    p.write_text(text)
    rc = mod.main([str(p)])
    assert rc == 1
    assert "tool_substitution" in mod.lint_text(text)


def test_lint_text_full_has_no_missing():
    assert mod.lint_text(FULL) == []


def test_json_report(tmp_path):
    p = tmp_path / "RESULT.md"
    p.write_text(FULL)
    out = tmp_path / "r.json"
    rc = mod.main([str(p), "--json", str(out)])
    assert rc == 0
    import json
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["missing_sections"] == []
