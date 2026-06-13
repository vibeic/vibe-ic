"""Unit tests for `hold_area_budget_check.py`."""
import importlib

mod = importlib.import_module("hold_area_budget_check")


class TestEvaluatePass:
    def test_within_budget(self):
        # 1200 / 100000 = 1.2% <= 5%
        verdict, rc, report = mod.evaluate(1200.0, 100000.0)
        assert verdict == "PASS"
        assert rc == 0
        assert abs(report["overhead_pct"] - 1.2) < 1e-9

    def test_exactly_at_budget_boundary(self):
        # 5000 / 100000 = 5.0% == cap -> PASS (<=)
        verdict, rc, _ = mod.evaluate(5000.0, 100000.0)
        assert verdict == "PASS"

    def test_before_after_derives_delta(self):
        verdict, rc, report = mod.evaluate(
            None, None, before_total_area=99000.0, after_total_area=100000.0)
        assert verdict == "PASS"
        assert report["hold_buffer_area"] == 1000.0
        assert report["total_cell_area"] == 100000.0

    def test_zero_allowed_explicitly(self):
        verdict, rc, report = mod.evaluate(0.0, 100000.0, allow_zero=True)
        assert verdict == "PASS"
        assert report["reason"] == "NO_HOLD_BUFFERS_NEEDED"


class TestEvaluateFailHonest:
    def test_over_budget_fails(self):
        # 6000 / 100000 = 6% > 5%
        verdict, rc, report = mod.evaluate(6000.0, 100000.0)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "AREA_BUDGET_EXCEEDED"

    def test_missing_total_area_fails(self):
        verdict, rc, report = mod.evaluate(1200.0, None)
        assert verdict == "FAIL"
        assert report["reason"] == "TOTAL_AREA_MISSING_OR_ZERO"

    def test_zero_total_area_fails(self):
        verdict, rc, report = mod.evaluate(1200.0, 0.0)
        assert verdict == "FAIL"
        assert report["reason"] == "TOTAL_AREA_MISSING_OR_ZERO"

    def test_missing_hold_area_fails(self):
        verdict, rc, report = mod.evaluate(None, 100000.0)
        assert verdict == "FAIL"
        assert report["reason"] == "HOLD_AREA_MISSING"

    def test_negative_hold_area_fails(self):
        verdict, rc, report = mod.evaluate(-500.0, 100000.0)
        assert verdict == "FAIL"
        assert report["reason"] == "NEGATIVE_HOLD_AREA"

    def test_zero_without_allow_zero_fails(self):
        verdict, rc, report = mod.evaluate(0.0, 100000.0)
        assert verdict == "FAIL"
        assert report["reason"] == "ZERO_HOLD_AREA_NO_WORK"

    def test_nan_total_fails(self):
        verdict, rc, report = mod.evaluate(1200.0, float("nan"))
        assert verdict == "FAIL"
        assert report["reason"] == "TOTAL_AREA_MISSING_OR_ZERO"


class TestCli:
    def test_cli_json_input_pass(self, tmp_path):
        import json
        inp = tmp_path / "in.json"
        inp.write_text(json.dumps(
            {"hold_buffer_area": 2000.0, "total_cell_area": 100000.0}))
        out = tmp_path / "r.json"
        rc = mod.main([str(inp), "--json", str(out)])
        assert rc == 0
        assert json.loads(out.read_text())["verdict"] == "PASS"

    def test_cli_missing_input_file_fails(self, tmp_path):
        import json
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path / "nope.json"), "--json", str(out)])
        assert rc == 1
        assert json.loads(out.read_text())["verdict"] == "FAIL"

    def test_cli_flags_over_budget(self, tmp_path):
        import json
        out = tmp_path / "r.json"
        rc = mod.main(["--hold-buffer-area", "9000",
                       "--total-cell-area", "100000", "--json", str(out)])
        assert rc == 1
        rep = json.loads(out.read_text())
        assert rep["reason"] == "AREA_BUDGET_EXCEEDED"
