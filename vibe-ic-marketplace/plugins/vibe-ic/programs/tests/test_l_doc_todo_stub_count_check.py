"""tests/test_l_doc_todo_stub_count_check.py

D3 program-first capture of the phase1-output-verify "Completeness"
checklist (item 1): "open every L doc, count __TODO__ strings. >0 means
incomplete extraction." Strict threshold == 0.

Coverage:
  * PASS                 — zero __TODO__ across all L docs
  * real FAIL            — a __TODO__ left in any L doc (the runner's own
                           unresolved-field sentinel) => incomplete
  * count across docs    — total counts every occurrence, names the docs
  * missing-data honesty — generated_docs absent => VACUOUS_PASS;
                           generated_docs present but empty => VACUOUS_PASS;
                           never a silent clean PASS
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.l_doc_todo_stub_count_check import scan, main


def _w(proj: Path, layer_file: str, payload: dict) -> None:
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / layer_file).write_text(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# PASS
# ---------------------------------------------------------------------------
def test_clean_docs_pass(tmp_path: Path) -> None:
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo",
                                       "pin_table": [{"name": "clk"}]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {"ports": [{"name": "clk"}]})
    verdict, findings, summary = scan(tmp_path)
    assert verdict == "PASS", findings
    assert summary["total_todo"] == 0
    assert summary["l_docs_scanned"] == 2
    assert main([str(tmp_path)]) == 0


# ---------------------------------------------------------------------------
# real FAIL — a __TODO__ stub left behind
# ---------------------------------------------------------------------------
def test_todo_stub_fails(tmp_path: Path) -> None:
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo",
                                       "pin_table": [{"name": "clk"}]})
    # phase2-style unresolved tester field, the runner's own sentinel.
    _w(tmp_path, "L13_DELIVERABLES.json", {
        "tester": {"name": "__TODO__", "vendor": "__TODO__"},
    })
    verdict, findings, summary = scan(tmp_path)
    assert verdict == "FAIL", findings
    assert summary["total_todo"] == 2
    assert summary["docs_with_todo"] == 1
    flagged = {f.file for f in findings}
    assert "L13_DELIVERABLES.json" in flagged
    assert main([str(tmp_path)]) == 1


def test_counts_across_multiple_docs(tmp_path: Path) -> None:
    _w(tmp_path, "L1_DATASHEET.json", {"x": "__TODO__"})
    _w(tmp_path, "L3_CMD_PROTOCOL.json", {"a": "__TODO__", "b": "__TODO__"})
    verdict, findings, summary = scan(tmp_path)
    assert verdict == "FAIL"
    assert summary["total_todo"] == 3
    assert summary["docs_with_todo"] == 2


# ---------------------------------------------------------------------------
# missing-data honesty
# ---------------------------------------------------------------------------
def test_no_generated_docs_vacuous(tmp_path: Path) -> None:
    verdict, findings, summary = scan(tmp_path)
    assert verdict == "VACUOUS_PASS"
    assert summary["generated_docs"] is None
    assert summary["l_docs_scanned"] == 0
    assert main([str(tmp_path)]) == 0


def test_generated_docs_empty_vacuous(tmp_path: Path) -> None:
    # generated_docs exists but holds no L*.json — nothing extracted yet.
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    verdict, findings, summary = scan(tmp_path)
    assert verdict == "VACUOUS_PASS"
    assert summary["l_docs_scanned"] == 0


def test_bad_target_returns_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2


# ---------------------------------------------------------------------------
# pointing the CLI at the generated_docs dir directly also works
# ---------------------------------------------------------------------------
def test_direct_generated_docs_dir(tmp_path: Path) -> None:
    gd = tmp_path / "generated_docs"
    gd.mkdir()
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"x": "__TODO__"}))
    verdict, findings, summary = scan(gd)
    assert verdict == "FAIL"
    assert summary["total_todo"] == 1
