"""Unit tests for `hold_corner_coverage_check.py`."""
import importlib

mod = importlib.import_module("hold_corner_coverage_check")


_FF_TCL = """\
# hold analysis at the fast corner
read_liberty gf180mcu_fd_sc_mcu7t5v0__ff_1p10v_m40c.lib
read_verilog design.v
read_sdc design.sdc
report_checks -path_delay min -slack_max 0
report_worst_slack -min
"""

_SS_TCL = """\
# hold analysis reading the WRONG (slow) corner
read_liberty gf180mcu_fd_sc_mcu7t5v0__ss_0p90v_125c.lib
report_checks -path_delay min -slack_max 0
"""

_NO_HOLD_TCL = """\
read_liberty gf180mcu_fd_sc_mcu7t5v0__ff_1p10v_m40c.lib
report_checks -path_delay max -slack_max 0
report_worst_slack -max
"""

_MCMM_FF_VIEW = """\
set_operating_conditions -analysis_type single ff_1p10v_m40c
report_checks -path_delay min
"""


class TestEvaluatePass:
    def test_ff_liberty_passes(self):
        verdict, rc, report = mod.evaluate(_FF_TCL)
        assert verdict == "PASS"
        assert rc == 0
        assert report["hold_feed_corners"] == ["FF"]

    def test_mcmm_ff_operating_condition_passes(self):
        verdict, rc, report = mod.evaluate(_MCMM_FF_VIEW)
        assert verdict == "PASS"
        assert "FF" in report["hold_feed_corners"]


class TestEvaluateFailHonest:
    def test_ss_liberty_fails(self):
        verdict, rc, report = mod.evaluate(_SS_TCL)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "HOLD_NOT_AT_FF"
        assert "SS" in report["hold_feed_corners"]

    def test_no_hold_analysis_fails(self):
        # setup-only flow: there is no min-path / hold analysis at all
        verdict, rc, report = mod.evaluate(_NO_HOLD_TCL)
        assert verdict == "FAIL"
        assert report["reason"] == "NO_HOLD_ANALYSIS"

    def test_none_input_fails(self):
        verdict, rc, report = mod.evaluate(None)
        assert verdict == "FAIL"
        assert report["reason"] == "INPUT_MISSING"

    def test_empty_input_fails(self):
        verdict, rc, report = mod.evaluate("   \n  ")
        assert verdict == "FAIL"
        assert report["reason"] == "INPUT_EMPTY"

    def test_hold_run_but_no_feed_corner_fails(self):
        # a hold analysis runs but no Liberty/OC corner is identifiable
        txt = "report_checks -path_delay min -slack_max 0\n"
        verdict, rc, report = mod.evaluate(txt)
        assert verdict == "FAIL"
        assert report["reason"] == "NO_FEED_CORNER"


class TestCli:
    def test_cli_ff_pass(self, tmp_path):
        import json
        f = tmp_path / "hold.tcl"
        f.write_text(_FF_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(f), "--json", str(out)])
        assert rc == 0
        assert json.loads(out.read_text())["verdict"] == "PASS"

    def test_cli_ss_fail(self, tmp_path):
        import json
        f = tmp_path / "hold.tcl"
        f.write_text(_SS_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(f), "--json", str(out)])
        assert rc == 1
        assert json.loads(out.read_text())["reason"] == "HOLD_NOT_AT_FF"

    def test_cli_missing_file_fails(self, tmp_path):
        import json
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path / "nope.tcl"), "--json", str(out)])
        assert rc == 1
        assert json.loads(out.read_text())["verdict"] == "FAIL"


# ═════════════════════════════════════════════════════════════════════════
# Added when this gate was first WIRED (Step 23, unconditional).
# ═════════════════════════════════════════════════════════════════════════

# The flow's own emitter writes the sign-off corner liberty and then
# interpolates one `read_liberty` per HARD-MACRO liberty into the SAME hold
# script, narrowing multi-corner macro libs to the TYPICAL ones on purpose.
# The first version of this gate demanded that EVERY designator classify FF,
# so every macro-bearing design was failed `HOLD_NOT_AT_FF ['FF','TT']` for a
# hold sign-off that was in fact at FF. The corpus hid it: the only two runs
# that retained the script belong to a macro-free design.
_HOLD_TCL_WITH_MACRO = """\
read_liberty /pdk/lib/stdcells__ff_n40C_1v95.lib
read_liberty /proj/input/pdk_local/sram_1rw_64x32/lib/sram_1rw_64x32_tt_1p80V_25C.lib
read_verilog top_pnr.v
link_design top
read_sdc constraint.sdc
puts $_f "=== HOLD corner: process=FF liberty=/pdk/lib/stdcells__ff_n40C_1v95.lib ==="
report_worst_slack -min
report_checks -path_delay min
"""


class TestMacroLibrariesAreNotTheSignoffCorner:
    def test_typ_macro_liberty_does_not_fail_an_ff_hold_run(self):
        verdict, rc, report = mod.evaluate(_HOLD_TCL_WITH_MACRO)
        assert verdict == "PASS", report
        assert rc == 0

    def test_a_declared_hold_view_outranks_other_libraries(self):
        _v, _rc, report = mod.evaluate(_HOLD_TCL_WITH_MACRO)
        assert report["corner_basis"] == "declared_hold_view"
        assert report["judged_corners"] == ["FF"]

    def test_no_fast_corner_anywhere_is_still_a_fail(self):
        """The repair must not silence the defect: strip the FF liberty and
        only slow/typical libraries feed the hold analysis."""
        txt = _HOLD_TCL_WITH_MACRO.replace("__ff_n40C_1v95", "__ss_100C_1v60") \
                                  .replace("process=FF", "process=SS")
        verdict, rc, report = mod.evaluate(txt)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "HOLD_NOT_AT_FF"


class TestDeclaredStance:
    """The DURABLE record: `hold_process_corner` in mcorner_ocv_stance.json.
    It survives when the Tcl is pruned from a published run, and it is what
    the run actually decided."""

    def test_ff_stance_passes(self):
        verdict, rc, report = mod.evaluate_stance(
            {"setup_process_corner": "SS", "hold_process_corner": "FF",
             "multi_process_corner": True})
        assert (verdict, rc) == ("PASS", 0)

    def test_tt_stance_fails(self):
        """The runner falls back to TT when the PDK has no fast liberty. A
        hold role assigned to TT under-reports hold violations, and no wired
        gate asked whether that assignment was legitimate."""
        verdict, rc, report = mod.evaluate_stance(
            {"setup_process_corner": "TT", "hold_process_corner": "TT",
             "multi_process_corner": False, "report": None})
        assert (verdict, rc) == ("FAIL", 1)
        assert report["reason"] == "HOLD_NOT_AT_FF"

    def test_no_declared_corner_is_not_checked(self):
        verdict, rc, report = mod.evaluate_stance(
            {"setup_process_corner": None, "hold_process_corner": None})
        assert rc == 2
        assert report["reason"] == "NO_DECLARED_HOLD_CORNER"

    def test_unreadable_stance_is_not_checked(self):
        verdict, rc, report = mod.evaluate_stance(None)
        assert rc == 2


class TestProjectDirectoryMode:
    """rc=2 is what lets the gate be wired UNCONDITIONALLY: gating a corner
    gate on the corner artefact is how an unreported corner became
    indistinguishable from a met one."""

    def test_project_without_any_hold_record_is_not_checked(self, tmp_path):
        rc = mod.main([str(tmp_path)])
        assert rc == 2

    def test_project_prefers_the_stance_over_the_tcl(self, tmp_path):
        import json
        (tmp_path / "reports/phase3").mkdir(parents=True)
        (tmp_path / "reports/phase3/mcorner_ocv_stance.json").write_text(
            json.dumps({"hold_process_corner": "TT",
                        "multi_process_corner": False, "report": None}))
        (tmp_path / "phase3/stage3/sta").mkdir(parents=True)
        (tmp_path / "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl").write_text(
            _FF_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path), "--json", str(out)])
        assert rc == 1
        rep = json.loads(out.read_text())
        assert rep["mode"] == "stance"
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_project_falls_back_to_the_hold_tcl(self, tmp_path):
        import json
        (tmp_path / "phase3/stage3/sta").mkdir(parents=True)
        (tmp_path / "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl").write_text(
            _FF_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path), "--json", str(out)])
        assert rc == 0
        assert json.loads(out.read_text())["verdict"] == "PASS"
