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
    # vibe-ic#1052: rc is what the flow reads. `VACUOUS_PASS` printed beside rc 0
    # was credited in the plain PASS tier by every consumer that reads only the
    # exit code, and the printed sentinel survives only the last 300 chars
    # `_check_program_exit_zero` keeps. rc 2 has no such window.
    assert main([str(tmp_path)]) == 2


def test_generated_docs_empty_vacuous(tmp_path: Path) -> None:
    # generated_docs exists but holds no L*.json — nothing extracted yet.
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    verdict, findings, summary = scan(tmp_path)
    assert verdict == "VACUOUS_PASS"
    assert summary["l_docs_scanned"] == 0
    assert main([str(tmp_path)]) == 2


def test_the_vacuous_rc_carries_the_sentinel_TOO(tmp_path: Path, capsys) -> None:
    """Both channels, asserted together.

    `_vacuous_exit` gives both on purpose. Either one alone can regress silently
    while the other keeps this test green, which is how the gate got here.
    """
    assert main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "VACUOUS_PASS:" in (captured.out + captured.err)


def test_a_REAL_clean_doc_set_still_passes(tmp_path: Path) -> None:
    """The positive arm. Without it this change has only shown the gate can
    refuse — a gate that refuses everything is a ban, not a check."""
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L1_DATASHEET.json").write_text('{"chip": "x", "ports": []}')
    (d / "L2_FRS.json").write_text('{"requirements": ["r1"]}')
    verdict, _, summary = scan(tmp_path)
    assert verdict == "PASS", summary
    assert summary["l_docs_scanned"] == 2
    assert main([str(tmp_path)]) == 0


def test_a_TODO_stub_still_FAILS(tmp_path: Path) -> None:
    """And the negative arm stays reachable at rc 1, distinct from rc 2."""
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L1_DATASHEET.json").write_text('{"chip": "__TODO__"}')
    assert main([str(tmp_path)]) == 1


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


# ---------------------------------------------------------------------------
# vibe-ic#693 — this gate is NOT superseded by `gameable_placeholder_scan`.
#
# That program scans the same L*.json for a strictly larger TOKEN set, which
# makes "delete this one" look safe. It is not: the two accept different INPUT
# SHAPES. Handed the generated_docs directory itself — the shape
# skills/phase1-output-verify/SKILL.md documents, and the shape the test above
# pins — `gameable_placeholder_scan` resolves no docs dir and reports
# NO_GENERATED_DOCS / rc 1 on a corpus containing zero placeholders.
#
# This test exists so that a future "consolidate the placeholder scanners"
# change has to confront the fabricated red rather than discover it in a run.
# ---------------------------------------------------------------------------
def test_not_superseded_generated_docs_dir_shape(tmp_path: Path) -> None:
    import subprocess
    import sys as _sys

    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic": "x"}))  # CLEAN

    # this gate: judges the clean corpus correctly
    verdict, _, summary = scan(gd)
    assert verdict == "PASS"
    assert summary["l_docs_scanned"] == 1 and summary["total_todo"] == 0

    # the candidate superset, same target: a red produced by not looking
    other = Path(__file__).parent.parent / "gameable_placeholder_scan.py"
    res = subprocess.run([_sys.executable, str(other), str(gd)],
                         capture_output=True, text=True)
    assert res.returncode == 1
    assert "NO_GENERATED_DOCS" in res.stdout

    # ...and it is right on the PROJECT-dir shape, which is what the flow passes
    res = subprocess.run([_sys.executable, str(other), str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode == 0
    assert "CLEAN" in res.stdout
