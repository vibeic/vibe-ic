#!/usr/bin/env python3
"""Tests for the --preflight (handoff-time advisory) mode.

The property under test is that the OUTSTANDING list is produced from the SAME
extraction the blocking gate uses, at a point where the artifacts are still
absent, WITHOUT blocking. So each test pairs:
  * the defect present  -> the artifact is named in the advisory output, and
  * the defect absent   -> it is not,
while the exit code stays 0 in every case (a preflight that can block would
stop every correct run, since at handoff nothing has been authored yet).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spec_required_artifact_check as srac  # noqa: E402


L7_CLAUSE = (
    "## 7.0 Plugin Declaration Requirements\n\n"
    "Plugin 在開始 RTL 設計前，**必須**"
    "於 `plugin_output/declaration.json` 聲明:\n"
)


def _mk_run(tmp_path, doc_text=L7_CLAUSE, artifacts=()):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(doc_text, encoding="utf-8")
    for rel in artifacts:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"top_module": "x"}\n', encoding="utf-8")
    return tmp_path


def test_preflight_names_the_outstanding_artifact_and_does_not_block(tmp_path, capsys):
    """Defect present: the spec demands the file, it is absent -> it must be
    NAMED at handoff, and the exit code must still be 0."""
    run = _mk_run(tmp_path)
    rc = srac.main([str(run), "--preflight"])
    out = capsys.readouterr().out
    assert rc == 0, "preflight must never block a run"
    assert "OUTSTANDING" in out
    assert "plugin_output/declaration.json" in out
    # the author needs to know WHERE the requirement came from
    assert "required by:" in out and "L7_verification_plan" in out


def test_preflight_is_quiet_once_the_artifact_exists(tmp_path, capsys):
    """Defect absent: same spec, file authored -> not listed as outstanding."""
    run = _mk_run(tmp_path, artifacts=("plugin_output/declaration.json",))
    rc = srac.main([str(run), "--preflight"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OUTSTANDING" not in out
    assert "already present" in out


def test_preflight_on_a_spec_declaring_nothing_says_so(tmp_path, capsys):
    run = _mk_run(tmp_path, doc_text="# L7\n\nNo mandatory artifact here.\n")
    rc = srac.main([str(run), "--preflight"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NONE" in out


def test_blocking_mode_still_fails_on_the_same_input(tmp_path):
    """The advisory mode must not have softened the real gate: the identical
    project that preflight merely WARNS about must still FAIL the end-of-phase
    assertion."""
    run = _mk_run(tmp_path)
    assert srac.main([str(run)]) == 1
    run2 = _mk_run(tmp_path / "ok", artifacts=("plugin_output/declaration.json",))
    assert srac.main([str(run2)]) == 0


def test_emit_preflight_unit_behaviour(capsys):
    rows = [
        {"artifact_path": "a/b.json", "status": "FAIL_ABSENT",
         "source": "input/docs/L7.md", "clause_text": "**必須** `a/b.json`"},
        {"artifact_path": "c/d.json", "status": "PASS",
         "source": "input/docs/L7.md", "clause_text": "x"},
    ]
    assert srac._emit_preflight(rows) == 0
    out = capsys.readouterr().out
    assert "a/b.json" in out
    assert "c/d.json" not in out          # already satisfied -> not nagged about
    assert "1 spec-declared artifact(s) OUTSTANDING" in out


@pytest.mark.parametrize("status", ["FAIL_ABSENT", "FAIL_EMPTY"])
def test_every_non_pass_status_is_surfaced(capsys, status):
    assert srac._emit_preflight(
        [{"artifact_path": "p.json", "status": status,
          "source": "s", "clause_text": "c"}]) == 0
    assert "p.json" in capsys.readouterr().out
