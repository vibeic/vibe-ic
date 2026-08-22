"""Tests for benchmark_golden_capture.py — OUR own host-verified golden corpus,
kept separate from the downloaded reference, tagged with plugin version + AI model
(user directive 2026-06-22, for cross-version/model cross-reference)."""
import sqlite3
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_golden_capture as g  # noqa: E402


def _mk_rtl(tmp_path, txt="module TopModule(output zero); assign zero=1'b0; endmodule"):
    f = tmp_path / "s.sv"; f.write_text(txt); return str(f)


def test_capture_writes_row_and_backup(tmp_path):
    db = str(tmp_path / "t.sqlite"); bk = str(tmp_path / "b.jsonl")
    g.capture(db, "verilogeval-v2", "Prob001_zero", _mk_rtl(tmp_path), None,
              "1.1.59", "claude-opus-4-8", backup=bk)
    cx = sqlite3.connect(db)
    rows = list(cx.execute("SELECT problem_id,plugin_version,ai_model,host_verdict FROM vibe_golden_solutions"))
    assert rows == [("Prob001_zero", "1.1.59", "claude-opus-4-8", "PASS")]
    assert Path(bk).read_text().count("\n") == 1  # backup appended


def test_provenance_tags_required(tmp_path):
    db = str(tmp_path / "t.sqlite")
    import pytest
    with pytest.raises(SystemExit):
        g.capture(db, "verilogeval-v2", "P", _mk_rtl(tmp_path), None, "", "claude-opus-4-8")
    with pytest.raises(SystemExit):
        g.capture(db, "verilogeval-v2", "P", _mk_rtl(tmp_path), None, "1.1.59", "")


def test_upsert_same_key_one_row_diff_version_two_rows(tmp_path):
    db = str(tmp_path / "t.sqlite"); bk = str(tmp_path / "b.jsonl")
    rtl = _mk_rtl(tmp_path)
    g.capture(db, "verilogeval-v2", "Prob001_zero", rtl, None, "1.1.59", "claude-opus-4-8", backup=bk)
    g.capture(db, "verilogeval-v2", "Prob001_zero", rtl, None, "1.1.59", "claude-opus-4-8", backup=bk)  # same key -> UPSERT
    g.capture(db, "verilogeval-v2", "Prob001_zero", rtl, None, "1.2.0", "claude-opus-4-8", backup=bk)   # new version -> new row
    cx = sqlite3.connect(db)
    n = cx.execute("SELECT COUNT(*) FROM vibe_golden_solutions").fetchone()[0]
    assert n == 2  # one per (problem, version, model)
    vers = sorted(v for (v,) in cx.execute(
        "SELECT plugin_version FROM vibe_golden_solutions WHERE problem_id='Prob001_zero'"))
    assert vers == ["1.1.59", "1.2.0"]


def test_separate_from_downloaded_reference(tmp_path):
    # our table is vibe_golden_solutions, NOT the problems.reference_solution column
    db = str(tmp_path / "t.sqlite")
    g.init_db(db)
    cx = sqlite3.connect(db)
    tbls = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "vibe_golden_solutions" in tbls
    assert "problems" not in tbls  # we never touch the upstream reference corpus


def test_import_rebuilds_from_backup(tmp_path):
    db = str(tmp_path / "t.sqlite"); bk = str(tmp_path / "b.jsonl")
    rtl = _mk_rtl(tmp_path)
    g.capture(db, "verilogeval-v2", "Prob001_zero", rtl, None, "1.1.59", "claude-opus-4-8", backup=bk)
    g.capture(db, "rtllm", "accu", rtl, None, "1.1.59", "claude-opus-4-8", backup=bk)
    db2 = str(tmp_path / "fresh.sqlite")
    assert g.import_backup(db2, bk) == 2  # disaster recovery from the outside-git JSONL
    cx = sqlite3.connect(db2)
    assert cx.execute("SELECT COUNT(*) FROM vibe_golden_solutions").fetchone()[0] == 2
