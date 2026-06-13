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
