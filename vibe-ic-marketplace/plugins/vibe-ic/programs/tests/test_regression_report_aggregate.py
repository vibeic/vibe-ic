"""Unit tests for `regression_report_aggregate.py`."""
import importlib
import json

import pytest

mod = importlib.import_module("regression_report_aggregate")


def _job(name="j", p=0, f=0, e=0, t=0):
    return {"job": name, "pass": p, "fail": f, "error": e, "timeout": t}


class TestSummarizeJob:
    def test_pass_pct(self):
        s = mod.summarize_job(_job("a", p=9, f=1))
        assert s.total == 10
        assert s.pass_pct == 90.0

    def test_zero_total(self):
        s = mod.summarize_job(_job("a"))
        assert s.total == 0
        assert s.pass_pct == 0.0

    def test_all_outcomes_counted(self):
        s = mod.summarize_job(_job("a", p=1, f=2, e=3, t=4))
        assert s.total == 10


class TestAggregate:
    def test_overall(self):
        rep = mod.aggregate([_job("a", p=8, f=2), _job("b", p=10)])
        assert rep["totals"]["total"] == 20
        assert rep["overall_pass_pct"] == 90.0

    def test_trend_up(self):
        rep = mod.aggregate([_job("a", p=9, f=1)], prev_pass_pct=80.0)
        assert rep["trend"] == "up"
        assert rep["trend_delta"] == 10.0

    def test_trend_down(self):
        rep = mod.aggregate([_job("a", p=7, f=3)], prev_pass_pct=90.0)
        assert rep["trend"] == "down"

    def test_trend_flat(self):
        rep = mod.aggregate([_job("a", p=9, f=1)], prev_pass_pct=90.0)
        assert rep["trend"] == "flat"

    def test_zero_pass_is_honest_zero(self):
        # a run with zero passing tests is honest 0%, not a vacuous PASS
        rep = mod.aggregate([_job("a", f=5)])
        assert rep["overall_pass_pct"] == 0.0

    def test_p0_carried(self):
        rep = mod.aggregate([_job("a", p=1)], p0_count=3)
        assert rep["p0_count"] == 3


class TestHonestFail:
    def test_missing_counter_raises(self):
        with pytest.raises(mod.InputError):
            mod.aggregate([{"job": "a", "pass": 1}])  # missing fail/error/to

    def test_negative_count_raises(self):
        with pytest.raises(mod.InputError):
            mod.aggregate([_job("a", p=-1)])

    def test_bool_count_raises(self):
        bad = _job("a")
        bad["pass"] = True
        with pytest.raises(mod.InputError):
            mod.aggregate([bad])

    def test_missing_job_name_raises(self):
        with pytest.raises(mod.InputError):
            mod.aggregate([{"pass": 1, "fail": 0, "error": 0, "timeout": 0}])

    def test_non_list_raises(self):
        with pytest.raises(mod.InputError):
            mod.aggregate({"x": 1})


class TestMarkdown:
    def test_has_dashboard_and_table(self):
        rep = mod.aggregate([_job("a", p=9, f=1)], p0_count=2)
        md = mod.report_to_markdown(rep, date="2026-06-01")
        assert "Summary dashboard" in md
        assert "Per-job" in md
        assert "90.0%" in md
        assert "P0 (tape-out blockers): **2**" in md


class TestCli:
    def test_cli_exit0_no_gate(self, tmp_path):
        inp = tmp_path / "j.json"
        inp.write_text(json.dumps([_job("a", p=10)]))
        out = tmp_path / "o.json"
        mdf = tmp_path / "o.md"
        rc = mod.main(["--jobs-json", str(inp), "--json", str(out),
                       "--md", str(mdf)])
        assert rc == 0
        assert json.loads(out.read_text())["overall_pass_pct"] == 100.0
        assert "Per-job" in mdf.read_text()

    def test_cli_below_gate_exit1(self, tmp_path):
        inp = tmp_path / "j.json"
        inp.write_text(json.dumps([_job("a", p=5, f=5)]))
        rc = mod.main(["--jobs-json", str(inp), "--min-pass-pct", "90"])
        assert rc == 1

    def test_cli_above_gate_exit0(self, tmp_path):
        inp = tmp_path / "j.json"
        inp.write_text(json.dumps([_job("a", p=95, f=5)]))
        rc = mod.main(["--jobs-json", str(inp), "--min-pass-pct", "90"])
        assert rc == 0

    def test_cli_missing_file_exit2(self, tmp_path):
        rc = mod.main(["--jobs-json", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_cli_garbage_exit2(self, tmp_path):
        inp = tmp_path / "g.json"
        inp.write_text("nope")
        rc = mod.main(["--jobs-json", str(inp)])
        assert rc == 2

    def test_cli_malformed_exit2(self, tmp_path):
        inp = tmp_path / "m.json"
        inp.write_text(json.dumps([{"job": "a", "pass": 1}]))
        rc = mod.main(["--jobs-json", str(inp)])
        assert rc == 2
