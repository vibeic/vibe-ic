"""Unit tests for `regression_severity_classify.py`."""
import importlib
import json

import pytest

mod = importlib.import_module("regression_severity_classify")


def _rec(test="t", prev="pass", branch="main", retry=False, err="assert"):
    return {"test": test, "prev_status": prev, "branch_type": branch,
            "retry_pass": retry, "error_class": err}


class TestClassifyOne:
    def test_p0_green_to_red_protected(self):
        f = mod.classify_one(_rec(prev="pass", branch="main", retry=False,
                                  err="assertion failed"))
        assert f.severity == "P0"

    def test_p0_release_branch(self):
        f = mod.classify_one(_rec(prev="pass", branch="release"))
        assert f.severity == "P0"

    def test_p1_new_failure_feature_branch(self):
        f = mod.classify_one(_rec(prev="absent", branch="feature"))
        assert f.severity == "P1"

    def test_p1_green_to_red_feature_branch_not_p0(self):
        # was-green-now-red but on a feature branch is NOT a tape-out blocker
        f = mod.classify_one(_rec(prev="pass", branch="feature"))
        assert f.severity == "P1"

    def test_p2_flaky_beats_p0(self):
        # retry_pass=True takes precedence even on a protected branch
        f = mod.classify_one(_rec(prev="pass", branch="main", retry=True))
        assert f.severity == "P2"

    def test_p3_environmental_beats_everything(self):
        f = mod.classify_one(_rec(prev="pass", branch="main", retry=False,
                                  err="FlexLM license checkout failed"))
        assert f.severity == "P3"

    def test_p3_disk_full(self):
        f = mod.classify_one(_rec(err="write failed: no space left on device"))
        assert f.severity == "P3"


class TestHonestFail:
    def test_missing_field_raises(self):
        bad = {"test": "t", "prev_status": "pass"}  # missing 3 keys
        with pytest.raises(mod.InputError):
            mod.classify_one(bad)

    def test_bad_prev_status_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_one(_rec(prev="maybe"))

    def test_non_bool_retry_raises(self):
        bad = _rec()
        bad["retry_pass"] = "yes"
        with pytest.raises(mod.InputError):
            mod.classify_one(bad)

    def test_empty_test_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_one(_rec(test="   "))

    def test_non_list_top_level_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_all({"not": "a list"})


class TestReportAndCli:
    def test_build_report_counts(self):
        recs = [_rec(prev="pass", branch="main"),       # P0
                _rec(prev="absent", branch="feature"),  # P1
                _rec(retry=True)]                        # P2
        rep = mod.build_report(mod.classify_all(recs))
        assert rep["counts_by_severity"]["P0"] == 1
        assert rep["p0_present"] is True
        assert rep["total"] == 3

    def test_cli_exit1_on_p0(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([_rec(prev="pass", branch="main")]))
        out = tmp_path / "o.json"
        rc = mod.main(["--failures-json", str(inp), "--json", str(out)])
        assert rc == 1
        assert json.loads(out.read_text())["p0_present"] is True

    def test_cli_exit0_no_p0(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([_rec(retry=True)]))  # P2 only
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 0

    def test_cli_missing_file_exit2(self, tmp_path):
        rc = mod.main(["--failures-json", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_cli_garbage_exit2(self, tmp_path):
        inp = tmp_path / "g.json"
        inp.write_text("{ not json ]")
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 2

    def test_cli_malformed_record_exit2(self, tmp_path):
        inp = tmp_path / "m.json"
        inp.write_text(json.dumps([{"test": "t"}]))  # missing fields
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 2
