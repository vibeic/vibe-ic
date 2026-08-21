"""ORGANIC #570, #556, #562 — phase3_one_shot_runner new helpers:
  #570: _docker_timeout_isolate renames partial outputs on rc=124
  #556: _sdc_period_ps reads smallest create_clock period from SDC files
  #562: _build_spare_postfix_tcl emits FIRM lock + check_placement catch
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── #570 ──────────────────────────────────────────────────────────────────────

def test_570_rename_partial_on_timeout(tmp_path):
    f = tmp_path / "routed.def"
    f.write_text("partial content")
    R._docker_timeout_isolate([f])
    assert not f.exists()
    partial = f.with_suffix(".def.timeout.partial")
    assert partial.is_file()
    assert partial.read_text() == "partial content"


def test_570_skip_nonexistent_file(tmp_path):
    missing = tmp_path / "does_not_exist.def"
    # Must not raise
    R._docker_timeout_isolate([missing])
    assert not missing.exists()


def test_570_multiple_outputs(tmp_path):
    files = [tmp_path / f"out{i}.def" for i in range(3)]
    for f in files:
        f.write_text("data")
    R._docker_timeout_isolate(files)
    for f in files:
        assert not f.exists()
        assert f.with_suffix(".def.timeout.partial").is_file()


# ── #556 ──────────────────────────────────────────────────────────────────────

def test_556_reads_single_create_clock(tmp_path):
    sdc = tmp_path / "design.sdc"
    sdc.write_text("create_clock -name clk -period 10.0 [get_ports clk]\n")
    # Build project structure
    proj = tmp_path / "proj"
    (proj / "input" / "constraints").mkdir(parents=True)
    (proj / "input" / "constraints" / "design.sdc").write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n"
    )
    result = R._sdc_period_ps(proj)
    assert result == 10000  # 10 ns → 10000 ps


def test_556_returns_smallest_period(tmp_path):
    proj = tmp_path / "proj2"
    cdir = proj / "phase2" / "stage2" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "fast.sdc").write_text(
        "create_clock -period 2.5 [get_ports clk_fast]\n"
        "create_clock -period 5.0 [get_ports clk_slow]\n"
    )
    result = R._sdc_period_ps(proj)
    assert result == 2500  # smallest is 2.5 ns → 2500 ps


def test_556_returns_none_when_no_sdc(tmp_path):
    proj = tmp_path / "empty_proj"
    proj.mkdir()
    result = R._sdc_period_ps(proj)
    assert result is None


def test_556_ignores_malformed_period(tmp_path):
    proj = tmp_path / "proj3"
    cdir = proj / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "bad.sdc").write_text(
        "create_clock -name clk -period abc [get_ports clk]\n"
    )
    result = R._sdc_period_ps(proj)
    assert result is None


# ── #562 ──────────────────────────────────────────────────────────────────────

def _spare_plan_with_instances():
    return {
        "instances": [
            {"name": "spare_AND2_0", "cell": "sky130_fd_sc_hd__and2_1",
             "type": "combinational", "llx": 10.0, "lly": 5.0},
            {"name": "spare_DFF_0", "cell": "sky130_fd_sc_hd__dfxtp_1",
             "type": "sequential", "llx": 20.0, "lly": 5.0},
        ]
    }


def test_562_postfix_tcl_contains_firm_set():
    tcl = R._build_spare_postfix_tcl(_spare_plan_with_instances())
    assert "setPlacementStatus FIRM" in tcl


def test_562_postfix_tcl_catch_check_placement():
    tcl = R._build_spare_postfix_tcl(_spare_plan_with_instances())
    assert "catch {check_placement" in tcl


def test_562_postfix_tcl_no_instances_returns_comment():
    tcl = R._build_spare_postfix_tcl({"instances": []})
    assert "no physical spare instances" in tcl
    assert "setPlacementStatus" not in tcl


def test_562_postfix_tcl_all_spare_names_present():
    plan = _spare_plan_with_instances()
    tcl = R._build_spare_postfix_tcl(plan)
    for inst in plan["instances"]:
        assert inst["name"] in tcl
