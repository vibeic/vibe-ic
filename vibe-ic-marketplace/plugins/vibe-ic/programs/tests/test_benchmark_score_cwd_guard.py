"""Tests for benchmark_score_cwd_guard.py (open-benchmark-methodology § 3)."""
from __future__ import annotations

import benchmark_score_cwd_guard as mod


def test_cwd_equals_design_pass(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    rc = mod.main(["--design", str(d), "--cwd", str(d)])
    assert rc == 0


def test_cwd_not_design_fail(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    rc = mod.main(["--design", str(d), "--cwd", str(other)])
    assert rc == 1


def test_design_not_a_directory_fail(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    rc = mod.main(["--design", str(f), "--cwd", str(tmp_path)])
    assert rc == 1


def test_tb_missing_fail(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    rc = mod.main(["--design", str(d), "--cwd", str(d),
                   "--tb", str(d / "nope.v")])
    assert rc == 1


def test_relative_datafile_resolves_pass(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    (d / "reference.txt").write_text("00\n11\n")
    tb = d / "tb.v"
    tb.write_text('initial $readmemh("reference.txt", mem);\n')
    rc = mod.main(["--design", str(d), "--cwd", str(d), "--tb", str(tb)])
    assert rc == 0


def test_relative_datafile_unresolved_fail(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    tb = d / "tb.v"
    # reference.txt does NOT exist under cwd → must FAIL.
    tb.write_text('initial $readmemh("reference.txt", mem);\n')
    rc = mod.main(["--design", str(d), "--cwd", str(d), "--tb", str(tb)])
    assert rc == 1


def test_absolute_datafile_not_flagged(tmp_path):
    # Absolute path is not cwd-relative; should not cause a FAIL by itself.
    d = tmp_path / "design"
    d.mkdir()
    tb = d / "tb.v"
    tb.write_text('initial $readmemh("/etc/hostname", mem);\n')
    rc = mod.main(["--design", str(d), "--cwd", str(d), "--tb", str(tb)])
    assert rc == 0


def test_json_report(tmp_path):
    d = tmp_path / "design"
    d.mkdir()
    out = tmp_path / "r.json"
    rc = mod.main(["--design", str(d), "--cwd", str(d), "--json", str(out)])
    assert rc == 0
    import json
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
