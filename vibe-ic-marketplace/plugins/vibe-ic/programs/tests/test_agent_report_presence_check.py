"""tests/test_agent_report_presence_check.py — v1.6.24

Five cases covering AGENT_REPORT.md presence + structure:
  1. happy path — all 5 sections present                          PASS
  2. missing one section (Iteration log)                          FAIL
  3. missing the file entirely                                    FAIL
  4. file exists but empty                                        FAIL
  5. synonym matching — "Deliverables" + "Backlog" + "Iterations" PASS
"""
from __future__ import annotations

from pathlib import Path

import pytest

from programs.agent_report_presence_check import audit


def _write_report(project: Path, body: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "AGENT_REPORT.md").write_text(body, encoding="utf-8")


_HAPPY_BODY = """# AGENT_REPORT — benchmark_a v10619-vendor

## Verdict
PASS_WITH_WAIVERS — 21/0/0/28/4/1.

## Acceptance evidence
- `phase2/stage1/fpga/output_files/de10lite_top.sof`
- `phase3/stage4/gds/chip_top_asic.gds`

## Waivers list
16 root waivers, every entry `review_required: true`.

## Discoveries
- 10 chip-AGNOSTIC backlog candidates filed.

## Iteration log
- Wave 1: …
- Wave 9: convergence
"""


def test_happy_path_passes(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_report(p, _HAPPY_BODY)
    verdict, sections, diagnostics = audit(p)
    assert verdict == "PASS", diagnostics
    assert all(s.matched_synonym for s in sections)


def test_missing_section_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    # Drop the "## Iteration log" heading entirely
    body = _HAPPY_BODY.replace("## Iteration log\n", "## Wrap-up\n")
    _write_report(p, body)
    verdict, sections, diagnostics = audit(p)
    assert verdict == "FAIL"
    assert any("Iteration log" in d for d in diagnostics)


def test_missing_file_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, sections, diagnostics = audit(p)
    assert verdict == "FAIL"
    assert any("does not exist" in d for d in diagnostics)


def test_empty_file_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_report(p, "")
    verdict, sections, diagnostics = audit(p)
    assert verdict == "FAIL"
    assert any("empty" in d for d in diagnostics)


def test_synonym_headings_pass(tmp_path: Path) -> None:
    """Authors writing 'Deliverables' / 'Backlog' / 'Iterations' instead
    of the canonical 'Acceptance evidence' / 'Discoveries' / 'Iteration
    log' must still pass — synonym matching is intentional."""
    p = tmp_path / "proj"
    body = """# Report

## Verdict
PASS

## Deliverables
- foo.sof

## Waivers
none

## Backlog
- gap A

## Iterations
- Wave 1
"""
    _write_report(p, body)
    verdict, sections, diagnostics = audit(p)
    assert verdict == "PASS", diagnostics
    matched = {s.matched_synonym for s in sections}
    assert "deliverables" in matched
    assert "backlog" in matched
    assert "iterations" in matched

# --- the exit code is what the flow reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing in its own test file.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    the gate could have started answering 0 to every finding with the suite
    still green.
    """
    import agent_report_presence_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("FAIL", [], []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import agent_report_presence_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("PASS", [], []))
    assert M.main([str(tmp_path)]) == 0


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import agent_report_presence_check as M
    assert M.main([str(tmp_path / "does_not_exist")]) == 2
