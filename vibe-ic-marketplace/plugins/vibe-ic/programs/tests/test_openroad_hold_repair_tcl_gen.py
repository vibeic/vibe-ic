"""Unit tests for `openroad_hold_repair_tcl_gen.py`."""
import importlib

mod = importlib.import_module("openroad_hold_repair_tcl_gen")


class TestEvaluatePass:
    def test_default_emits_guardrails(self):
        verdict, rc, report = mod.evaluate(0.0, 5.0, False)
        assert verdict == "PASS"
        assert rc == 0
        tcl = report["tcl"]
        # the hard guardrail literal MUST be present and false
        assert "-allow_setup_violations false" in tcl
        assert "-max_buffer_percent 5" in tcl
        assert "repair_timing -hold" in tcl
        # post-fix verification reports present
        assert "report_worst_slack -min" in tcl
        assert "report_worst_slack -max" in tcl

    def test_guardband_margin(self):
        verdict, rc, report = mod.evaluate(50.0, 3.0, False)
        assert verdict == "PASS"
        assert "-slack_margin 50" in report["tcl"]
        assert "-max_buffer_percent 3" in report["tcl"]

    def test_cap_boundary_5_ok(self):
        verdict, rc, _ = mod.evaluate(0.0, 5.0, False)
        assert verdict == "PASS"


class TestEvaluateFailHonest:
    def test_allow_setup_violations_rejected(self):
        verdict, rc, report = mod.evaluate(0.0, 5.0, True)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "SETUP_VIOLATION_REQUESTED"
        assert report["tcl"] is None

    def test_over_cap_rejected(self):
        verdict, rc, report = mod.evaluate(0.0, 7.5, False)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "BUFFER_PERCENT_OVER_CAP"
        assert report["tcl"] is None

    def test_zero_percent_rejected(self):
        verdict, rc, report = mod.evaluate(0.0, 0.0, False)
        assert verdict == "FAIL"
        assert report["reason"] == "BUFFER_PERCENT_NONPOSITIVE"

    def test_negative_percent_rejected(self):
        verdict, rc, report = mod.evaluate(0.0, -1.0, False)
        assert verdict == "FAIL"
        assert report["reason"] == "BUFFER_PERCENT_NONPOSITIVE"

    def test_nan_margin_rejected(self):
        verdict, rc, report = mod.evaluate(float("nan"), 5.0, False)
        assert verdict == "FAIL"
        assert report["reason"] == "MARGIN_NOT_FINITE"

    def test_inf_buffer_percent_rejected(self):
        verdict, rc, report = mod.evaluate(0.0, float("inf"), False)
        assert verdict == "FAIL"
        assert report["reason"] in ("BUFFER_PERCENT_NOT_FINITE",
                                    "BUFFER_PERCENT_OVER_CAP")


class TestCli:
    def test_cli_writes_tcl(self, tmp_path):
        outtcl = tmp_path / "hold.tcl"
        outjson = tmp_path / "r.json"
        rc = mod.main(["--margin-ps", "0", "--max-buffer-percent", "5",
                       "--out", str(outtcl), "--json", str(outjson)])
        assert rc == 0
        assert "-allow_setup_violations false" in outtcl.read_text()
        import json
        assert json.loads(outjson.read_text())["verdict"] == "PASS"

    def test_cli_reject_over_cap(self, tmp_path):
        outjson = tmp_path / "r.json"
        rc = mod.main(["--max-buffer-percent", "10", "--json", str(outjson)])
        assert rc == 1
        import json
        assert json.loads(outjson.read_text())["verdict"] == "FAIL"
