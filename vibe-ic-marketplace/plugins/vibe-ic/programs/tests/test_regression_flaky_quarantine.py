"""Unit tests for `regression_flaky_quarantine.py`."""
import importlib
import json

import pytest

mod = importlib.import_module("regression_flaky_quarantine")


class TestClassifyTest:
    def test_stable_pass(self):
        v = mod.classify_test({"test": "t", "results": ["pass", "pass"]})
        assert v.verdict == "stable_pass"
        assert v.quarantine is False
        assert v.ticket is None

    def test_stable_fail(self):
        v = mod.classify_test({"test": "t", "results": ["fail", "fail"]})
        assert v.verdict == "stable_fail"
        assert v.quarantine is False

    def test_flaky_passes_on_retry(self):
        v = mod.classify_test({"test": "t", "results": ["fail", "pass"]})
        assert v.verdict == "flaky"
        assert v.quarantine is True
        assert v.ticket and "QUARANTINE" in v.ticket
        assert v.flakiness == 0.5

    def test_bool_results_accepted(self):
        v = mod.classify_test({"test": "t", "results": [False, True]})
        assert v.verdict == "flaky"

    def test_flakiness_ratio(self):
        v = mod.classify_test({"test": "t",
                               "results": ["fail", "pass", "pass", "pass"]})
        assert v.flakiness == 0.25


class TestHonestFail:
    def test_empty_results_raises(self):
        # no data is NOT a vacuous pass
        with pytest.raises(mod.InputError):
            mod.classify_test({"test": "t", "results": []})

    def test_missing_results_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_test({"test": "t"})

    def test_missing_test_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_test({"results": ["pass"]})

    def test_invalid_token_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_test({"test": "t", "results": ["pass", "maybe"]})

    def test_non_list_top_level_raises(self):
        with pytest.raises(mod.InputError):
            mod.classify_all({"x": 1})


class TestCli:
    def test_cli_flaky_exit1(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([
            {"test": "flak", "results": ["fail", "pass"]},
            {"test": "good", "results": ["pass", "pass"]}]))
        out = tmp_path / "o.json"
        rc = mod.main(["--tests-json", str(inp), "--json", str(out)])
        assert rc == 1
        rep = json.loads(out.read_text())
        assert rep["quarantine_count"] == 1
        assert rep["quarantined"] == ["flak"]

    def test_cli_no_flaky_exit0(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([{"test": "g", "results": ["pass"]}]))
        rc = mod.main(["--tests-json", str(inp)])
        assert rc == 0

    def test_cli_missing_file_exit2(self, tmp_path):
        rc = mod.main(["--tests-json", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_cli_garbage_exit2(self, tmp_path):
        inp = tmp_path / "g.json"
        inp.write_text("@@@")
        rc = mod.main(["--tests-json", str(inp)])
        assert rc == 2

    def test_cli_malformed_exit2(self, tmp_path):
        inp = tmp_path / "m.json"
        inp.write_text(json.dumps([{"test": "t", "results": []}]))
        rc = mod.main(["--tests-json", str(inp)])
        assert rc == 2
