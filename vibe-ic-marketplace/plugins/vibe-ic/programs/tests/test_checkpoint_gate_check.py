"""Unit tests for checkpoint_gate_check.py.

Builds in-tmp_path fixture projects (good + failing) for each of the three
phase-transition checkpoints and asserts the JSON verdict + per-check
statuses. Also exercises the graceful-degradation paths (MISSING file,
MISSING-SCORER, empty-file length-floor) so the gate never crashes or
false-flags on unexpected input.
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "checkpoint_gate_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import checkpoint_gate_check as cg  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _w(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _status(rep, name):
    for c in rep.checks:
        if c.name == name:
            return c.status
    raise KeyError(name)


def _ten_l_docs(gen: Path) -> None:
    for n in ["L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
              "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
              "L7_TEST_DEBUG.json", "L8_TIMING.json", "L8_RTL_CONSTANTS.json",
              "L9_INTEGRATION_SPEC.json"]:
        _w(gen / n, "{}")


# ===========================================================================
# Checkpoint 1
# ===========================================================================
def _good_cp1(root: Path) -> None:
    _w(root / "phase1_spec" / "01_prompt.md")
    _w(root / "phase1_spec" / "02_dialog.md")
    _w(root / "phase1_spec" / "03_spec_confirmed.md")
    _w(root / "phase1_spec" / "04_datasheet.md")
    _w(root / "phase1_spec" / "05_appnote.md")
    _ten_l_docs(root / "generated_docs")


def test_cp1_good_files_present(tmp_path):
    _good_cp1(tmp_path)
    rep = cg.run(tmp_path, 1)
    # All required files present.
    for f in ("file:prompt", "file:dialog", "file:spec",
              "file:datasheet", "file:appnote"):
        assert _status(rep, f) == "PASS", f
    # L-layer docs all present -> PASS (delegated to sibling program).
    assert _status(rep, "l_layer_docs") == "PASS"
    # The ds/an/spec scorer outcome is environment-dependent (the scorers
    # ship in the repo-root tools/ dir, OUTSIDE the plugin). Whatever the
    # environment, the status must be one of the documented values and the
    # gate must NOT crash. (Threshold logic itself is tested deterministically
    # below via monkeypatch.)
    for sc in ("ds_quality", "an_quality", "spec_consistency"):
        assert _status(rep, sc) in ("PASS", "FAIL", "MISSING", "MISSING-SCORER")
    # No required FILE is MISSING — only scorer evaluation may be unavailable.
    assert _status(rep, "file:datasheet") == "PASS"
    assert _status(rep, "file:appnote") == "PASS"


def test_cp1_scorers_pass_threshold_monkeypatched(tmp_path, monkeypatch):
    """Deterministic threshold test, independent of repo-root tools/.

    Force a high score from each scorer and 0 spec errors -> PASS verdict.
    """
    _good_cp1(tmp_path)
    fake_tool = tmp_path / "fake_scorer.py"
    fake_tool.write_text("# stub")
    monkeypatch.setattr(cg, "_find_repo_tool", lambda name: fake_tool)

    def fake_run(tool, args):
        # spec_validator is called with --ds/--an; the others with a file path.
        if "--ds" in args:
            return {"consistent": True, "summary": {"errors": 0}}
        return {"total_score": 95}
    monkeypatch.setattr(cg, "_run_json_tool", fake_run)

    rep = cg.checkpoint1(tmp_path)
    assert _status(rep, "ds_quality") == "PASS"
    assert _status(rep, "an_quality") == "PASS"
    assert _status(rep, "spec_consistency") == "PASS"
    assert rep.verdict == "PASS"


def test_cp1_scorers_below_threshold_monkeypatched(tmp_path, monkeypatch):
    """DS=40 (<70) and AN=20 (<56) and 3 spec errors -> all FAIL."""
    _good_cp1(tmp_path)
    fake_tool = tmp_path / "fake_scorer.py"
    fake_tool.write_text("# stub")
    monkeypatch.setattr(cg, "_find_repo_tool", lambda name: fake_tool)

    def fake_run(tool, args):
        if "--ds" in args:
            return {"consistent": False, "summary": {"errors": 3}}
        if str(tmp_path / "generated_docs"):
            pass
        # distinguish ds vs an by the target path argument
        if any("04_datasheet" in a for a in args):
            return {"total_score": 40}
        return {"total_score": 20}
    monkeypatch.setattr(cg, "_run_json_tool", fake_run)

    rep = cg.checkpoint1(tmp_path)
    assert _status(rep, "ds_quality") == "FAIL"
    assert _status(rep, "an_quality") == "FAIL"
    assert _status(rep, "spec_consistency") == "FAIL"
    assert rep.verdict == "FAIL"


def test_cp1_scorer_absent_is_missing_scorer_not_fail(tmp_path, monkeypatch):
    """When the scorer cannot be located, report MISSING-SCORER (graceful)."""
    _good_cp1(tmp_path)
    monkeypatch.setattr(cg, "_find_repo_tool", lambda name: None)
    rep = cg.checkpoint1(tmp_path)
    assert _status(rep, "ds_quality") == "MISSING-SCORER"
    assert _status(rep, "an_quality") == "MISSING-SCORER"
    assert _status(rep, "spec_consistency") == "MISSING-SCORER"
    # MISSING-SCORER alone must NOT flip a PASS to FAIL: files + L-layer pass.
    assert rep.verdict == "PASS"
    assert rep.stats["incomplete"] is True


def test_cp1_missing_appnote_fails(tmp_path):
    _good_cp1(tmp_path)
    (tmp_path / "phase1_spec" / "05_appnote.md").unlink()
    rep = cg.run(tmp_path, 1)
    assert _status(rep, "file:appnote") == "MISSING"
    assert rep.verdict == "FAIL"


def test_cp1_incomplete_l_layer_fails(tmp_path):
    _good_cp1(tmp_path)
    # drop 3 L-layer docs -> phase1_doc_presence_check reports missing
    for n in ["L2_FRS.json", "L5_ADI_SPEC.json", "L7_TEST_DEBUG.json"]:
        (tmp_path / "generated_docs" / n).unlink()
    rep = cg.run(tmp_path, 1)
    assert _status(rep, "l_layer_docs") == "FAIL"
    assert rep.verdict == "FAIL"


def test_cp1_missing_generated_docs_dir(tmp_path):
    _good_cp1(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "generated_docs")
    rep = cg.run(tmp_path, 1)
    # Graceful: reported MISSING (not a crash).
    assert _status(rep, "l_layer_docs") in ("MISSING", "FAIL")
    assert rep.verdict == "FAIL"


# ===========================================================================
# Checkpoint 2
# ===========================================================================
def _good_cp2(root: Path, n_assert: int = 10, drc_violations: int = 0) -> None:
    _w(root / "phase2_design" / "rtl" / "core.sv", "module core; endmodule")
    formal = "module core_formal;\n" + "".join(
        f"  assert property (a{i});\n" for i in range(n_assert)) + "endmodule\n"
    _w(root / "phase2_design" / "rtl" / "core_formal.sv", formal)
    _w(root / "phase2_design" / "synth" / "synth.log",
       "Number of cells: 1234\n0 errors\n")
    _w(root / "phase2_design" / "synth" / "synth_core.v", "// netlist")
    _w(root / "phase2_design" / "pnr" / "core.def", "DESIGN core ;")
    _w(root / "phase2_design" / "gds" / "core.gds", "gds")
    drc = "DRC report\n" + "".join(
        f"violation {i}\n" for i in range(drc_violations))
    _w(root / "phase2_design" / "signoff" / "drc_report.rpt", drc)
    _w(root / "phase2_design" / "schematic" / "core_schematic.md", "# schematic")


def test_cp2_good_files_present(tmp_path):
    _good_cp2(tmp_path, n_assert=10, drc_violations=0)
    rep = cg.run(tmp_path, 2)
    for f in ("file:rtl", "file:formal_sv", "file:synth_log", "file:netlist",
              "file:def", "file:gds", "file:drc_report", "file:schematic"):
        assert _status(rep, f) == "PASS", f
    # SVA count = 10 >= 8 -> PASS (counted directly, no external tool).
    assert _status(rep, "sva_count") == "PASS"
    # DRC = 0 <= 5 -> PASS.
    assert _status(rep, "drc_violations") == "PASS"
    assert rep.stats["fail"] == 0
    assert rep.stats["missing"] == 0
    assert rep.verdict == "PASS"


def test_cp2_too_few_assertions_fails(tmp_path):
    _good_cp2(tmp_path, n_assert=3)
    rep = cg.run(tmp_path, 2)
    assert _status(rep, "sva_count") == "FAIL"
    sva = next(c for c in rep.checks if c.name == "sva_count")
    assert sva.value == 3
    assert sva.threshold == 8
    assert rep.verdict == "FAIL"


def test_cp2_too_many_drc_fails(tmp_path):
    _good_cp2(tmp_path, n_assert=10, drc_violations=9)
    rep = cg.run(tmp_path, 2)
    assert _status(rep, "drc_violations") == "FAIL"
    assert rep.verdict == "FAIL"


def test_cp2_clean_drc_report_no_false_alert(tmp_path):
    """A clean DRC report (the word 'violation' absent) must NOT false-flag."""
    _good_cp2(tmp_path, n_assert=10)
    _w(tmp_path / "phase2_design" / "signoff" / "drc_report.rpt",
       "DRC summary: layout is clean, 0 errors reported.\n")
    rep = cg.run(tmp_path, 2)
    drc = next(c for c in rep.checks if c.name == "drc_violations")
    assert drc.value == 0
    assert drc.status == "PASS"


def test_cp2_no_drc_report_is_skip_not_fail(tmp_path):
    """SKILL.md: DRC check only runs if drc_report.rpt exists."""
    _good_cp2(tmp_path, n_assert=10)
    (tmp_path / "phase2_design" / "signoff" / "drc_report.rpt").unlink()
    rep = cg.run(tmp_path, 2)
    # file:drc_report becomes MISSING (it is a required file), but the
    # violation-count check itself is SKIP not FAIL.
    assert _status(rep, "drc_violations") == "SKIP"


def test_cp2_missing_rtl_fails(tmp_path):
    _good_cp2(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "phase2_design" / "rtl")
    rep = cg.run(tmp_path, 2)
    assert _status(rep, "file:rtl") == "MISSING"
    assert rep.verdict == "FAIL"


def test_cp2_empty_formal_sv_graceful(tmp_path):
    """An empty *_formal.sv must degrade to MISSING, never a spurious count."""
    _good_cp2(tmp_path)
    _w(tmp_path / "phase2_design" / "rtl" / "core_formal.sv", "")  # empty
    rep = cg.run(tmp_path, 2)
    sva = next(c for c in rep.checks if c.name == "sva_count")
    assert sva.status == "MISSING"  # length-floor guard, not FAIL=0


def test_cp2_synth_checks_present(tmp_path):
    _good_cp2(tmp_path)
    rep = cg.run(tmp_path, 2)
    # synth_doctor outcome is environment-dependent (ships outside plugin).
    assert _status(rep, "synth_status") in ("PASS", "FAIL", "MISSING-SCORER")
    assert _status(rep, "cell_count") in ("PASS", "FAIL", "MISSING-SCORER")


def test_cp2_synth_pass_monkeypatched(tmp_path, monkeypatch):
    """Deterministic synth threshold test: PASS status + 1234 cells -> PASS."""
    _good_cp2(tmp_path, n_assert=10)
    fake_tool = tmp_path / "fake_synth.py"
    fake_tool.write_text("# stub")
    monkeypatch.setattr(cg, "_find_repo_tool", lambda name: fake_tool)
    monkeypatch.setattr(cg, "_run_json_tool",
                        lambda tool, args: {"status": "PASS", "cell_count": 1234})
    checks = cg._synth_doctor_checks(tmp_path)
    by = {c.name: c for c in checks}
    assert by["synth_status"].status == "PASS"
    assert by["cell_count"].status == "PASS"
    assert by["cell_count"].value == 1234


def test_cp2_synth_fail_and_zero_cells_monkeypatched(tmp_path, monkeypatch):
    """status=FAIL -> synth_status FAIL; cell_count 0 -> cell_count FAIL."""
    _good_cp2(tmp_path, n_assert=10)
    fake_tool = tmp_path / "fake_synth.py"
    fake_tool.write_text("# stub")
    monkeypatch.setattr(cg, "_find_repo_tool", lambda name: fake_tool)
    monkeypatch.setattr(cg, "_run_json_tool",
                        lambda tool, args: {"status": "FAIL", "cell_count": 0})
    checks = cg._synth_doctor_checks(tmp_path)
    by = {c.name: c for c in checks}
    assert by["synth_status"].status == "FAIL"
    assert by["cell_count"].status == "FAIL"


def test_cp2_synth_doctor_absent_missing_scorer(tmp_path, monkeypatch):
    _good_cp2(tmp_path, n_assert=10)
    monkeypatch.setattr(cg, "_find_repo_tool", lambda name: None)
    checks = cg._synth_doctor_checks(tmp_path)
    assert all(c.status == "MISSING-SCORER" for c in checks)


# ===========================================================================
# Checkpoint 3
# ===========================================================================
def _good_cp3(root: Path, sof_size: int = 100) -> None:
    f = root / "phase3_verify" / "fpga"
    _w(f / "core_fpga.qpf")
    _w(f / "core_fpga.qsf")
    _w(f / "core_fpga.sdc")
    _w(f / "core_fpga_top.sv")
    _w(f / "compile.log")
    _w(f / "core_fpga.sof", "S" * sof_size)
    _w(f / "fit.summary")
    _w(f / "sta.summary")


def test_cp3_good_files_present(tmp_path):
    _good_cp3(tmp_path)
    rep = cg.run(tmp_path, 3)
    for f in ("file:qpf", "file:qsf", "file:sdc", "file:fpga_top",
              "file:compile_log", "file:fit_summary", "file:sta_summary"):
        assert _status(rep, f) == "PASS", f
    assert _status(rep, "sof_file") == "PASS"
    assert rep.verdict == "PASS"


def test_cp3_empty_sof_fails(tmp_path):
    _good_cp3(tmp_path)
    (tmp_path / "phase3_verify" / "fpga" / "core_fpga.sof").write_text("")
    rep = cg.run(tmp_path, 3)
    sof = next(c for c in rep.checks if c.name == "sof_file")
    assert sof.status == "FAIL"
    assert sof.value == 0
    assert rep.verdict == "FAIL"


def test_cp3_missing_sof_fails(tmp_path):
    _good_cp3(tmp_path)
    (tmp_path / "phase3_verify" / "fpga" / "core_fpga.sof").unlink()
    rep = cg.run(tmp_path, 3)
    assert _status(rep, "sof_file") == "MISSING"
    assert rep.verdict == "FAIL"


# ===========================================================================
# Robustness / CLI
# ===========================================================================
def test_nonexistent_project_exit_2(tmp_path):
    rc = cg.main([str(tmp_path / "nope"), "--checkpoint", "1"])
    assert rc == 2


def test_empty_project_does_not_crash(tmp_path):
    """A totally empty project dir must report MISSING everywhere, not crash."""
    for cp in (1, 2, 3):
        rep = cg.run(tmp_path, cp)
        assert rep.verdict == "FAIL"
        # nothing raised; every required file is MISSING
        assert rep.stats["missing"] > 0


def test_cli_json_good_cp2(tmp_path, capsys):
    _good_cp2(tmp_path, n_assert=10, drc_violations=0)
    rc = cg.main([str(tmp_path), "--checkpoint", "2", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["checkpoint"] == 2
    assert data["verdict"] in ("PASS", "FAIL")
    assert isinstance(data["checks"], list)
    # exit code matches verdict
    assert rc == (0 if data["verdict"] == "PASS" else 1)


def test_cli_json_out_written(tmp_path):
    _good_cp1(tmp_path)
    out = tmp_path / "verdict.json"
    cg.main([str(tmp_path), "--checkpoint", "1", "--json-out", str(out)])
    data = json.loads(out.read_text())
    assert data["checkpoint"] == 1
    assert "stats" in data


def test_invalid_checkpoint_raises():
    import pytest
    with pytest.raises(ValueError):
        cg.run(Path("."), 9)
