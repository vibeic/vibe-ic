"""Unit tests for `regression_failure_route.py`."""
import importlib
import json

import pytest

mod = importlib.import_module("regression_failure_route")


class TestRouteOne:
    def test_timing_to_sta(self):
        f = mod.route_one({"test": "t", "failing_step": "timing"})
        assert f.target_skill == "/sta-review"
        assert f.routed is True

    def test_drc(self):
        f = mod.route_one({"test": "t", "failing_step": "DRC"})
        assert f.target_skill == "/drc-fix"

    def test_functional_to_rtl_repair(self):
        f = mod.route_one({"test": "t", "failing_step": "functional"})
        assert f.target_skill == "/rtl-repair"

    def test_formal(self):
        f = mod.route_one({"test": "t", "failing_step": "formal"})
        assert f.target_skill == "/formal-verify"

    def test_error_token_fallback(self):
        # unknown step, but error_class names a setup violation → STA
        f = mod.route_one({"test": "t", "failing_step": "weird",
                           "error_class": "setup violation -0.12ns"})
        assert f.target_skill == "/sta-review"
        assert f.routed is True

    def test_error_only_record(self):
        f = mod.route_one({"test": "t",
                           "error_class": "spacing < min width on M2"})
        assert f.target_skill == "/drc-fix"


class TestUnrouted:
    def test_unknown_step_unrouted(self):
        f = mod.route_one({"test": "t", "failing_step": "mystery"})
        assert f.target_skill == mod.UNROUTED
        assert f.routed is False

    def test_unknown_error_unrouted(self):
        f = mod.route_one({"test": "t", "error_class": "cosmic ray"})
        assert f.routed is False


class TestHonestFail:
    def test_missing_test_raises(self):
        with pytest.raises(mod.InputError):
            mod.route_one({"failing_step": "drc"})

    def test_no_step_no_error_raises(self):
        with pytest.raises(mod.InputError):
            mod.route_one({"test": "t"})

    def test_non_list_raises(self):
        with pytest.raises(mod.InputError):
            mod.route_all({"x": 1})


class TestCli:
    def test_cli_all_routed_exit0(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([
            {"test": "a", "failing_step": "timing"},
            {"test": "b", "failing_step": "drc"}]))
        out = tmp_path / "o.json"
        rc = mod.main(["--failures-json", str(inp), "--json", str(out)])
        assert rc == 0
        rep = json.loads(out.read_text())
        assert rep["all_routed"] is True
        assert rep["counts_by_skill"]["/sta-review"] == 1

    def test_cli_unrouted_exit1(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([{"test": "a", "failing_step": "???"}]))
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 1

    def test_cli_missing_file_exit2(self, tmp_path):
        rc = mod.main(["--failures-json", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_cli_garbage_exit2(self, tmp_path):
        inp = tmp_path / "g.json"
        inp.write_text("not json at all {{")
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 2

    def test_cli_malformed_record_exit2(self, tmp_path):
        inp = tmp_path / "m.json"
        inp.write_text(json.dumps([{"failing_step": "drc"}]))  # no test
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 2
