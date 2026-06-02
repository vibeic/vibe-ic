"""Unit tests for `regression_failure_dedup.py`."""
import importlib
import json

import pytest

mod = importlib.import_module("regression_failure_dedup")


class TestCanonicalize:
    def test_strips_line_numbers(self):
        a = mod.canonicalize("foo.v:123: syntax error")
        b = mod.canonicalize("foo.v:999: syntax error")
        assert a == b

    def test_strips_line_word(self):
        a = mod.canonicalize("error at line 12 in module")
        b = mod.canonicalize("error at line 4096 in module")
        assert a == b

    def test_strips_timestamp(self):
        a = mod.canonicalize("2026-06-01T10:00:00Z assertion failed")
        b = mod.canonicalize("2026-06-02T23:59:59Z assertion failed")
        assert a == b

    def test_strips_abs_path_to_basename(self):
        a = mod.canonicalize("/scratch/run1/tb.v failed")
        b = mod.canonicalize("/tmp/other/tb.v failed")
        assert a == b

    def test_strips_hex_addr(self):
        a = mod.canonicalize("segfault at 0xdeadbeef")
        b = mod.canonicalize("segfault at 0x12345678")
        assert a == b

    def test_distinct_errors_differ(self):
        a = mod.canonicalize("setup violation on path A")
        b = mod.canonicalize("hold violation on path B")
        assert a != b


class TestDedup:
    def test_groups_identical_after_norm(self):
        recs = [
            {"test": "t1", "error": "foo.v:10: bad at 2026-06-01T00:00:00Z"},
            {"test": "t2", "error": "foo.v:55: bad at 2026-06-02T11:22:33Z"},
            {"test": "t3", "error": "totally different error"},
        ]
        groups = mod.dedup(recs)
        assert len(groups) == 2
        # The big group has 2 members
        big = max(groups, key=lambda g: g.count)
        assert big.count == 2
        assert set(big.members) == {"t1", "t2"}

    def test_stable_order(self):
        recs = [{"test": "a", "error": "E1"},
                {"test": "b", "error": "E2"},
                {"test": "c", "error": "E1"}]
        groups = mod.dedup(recs)
        # first-seen order: E1 group first
        assert groups[0].members == ["a", "c"]
        assert groups[1].members == ["b"]

    def test_empty_list_zero_groups(self):
        # honest: no failures => 0 groups, not a vacuous "1 clean group"
        assert mod.dedup([]) == []


class TestHonestFail:
    def test_missing_error_raises(self):
        with pytest.raises(mod.InputError):
            mod.dedup([{"test": "t"}])

    def test_missing_test_raises(self):
        with pytest.raises(mod.InputError):
            mod.dedup([{"error": "boom"}])

    def test_non_list_raises(self):
        with pytest.raises(mod.InputError):
            mod.dedup({"nope": 1})


class TestCli:
    def test_cli_exit0(self, tmp_path):
        inp = tmp_path / "f.json"
        inp.write_text(json.dumps([
            {"test": "t1", "error": "x.v:1: boom"},
            {"test": "t2", "error": "x.v:2: boom"}]))
        out = tmp_path / "o.json"
        rc = mod.main(["--failures-json", str(inp), "--json", str(out)])
        assert rc == 0
        rep = json.loads(out.read_text())
        assert rep["group_count"] == 1
        assert rep["total_failures"] == 2

    def test_cli_missing_file_exit2(self, tmp_path):
        rc = mod.main(["--failures-json", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_cli_garbage_exit2(self, tmp_path):
        inp = tmp_path / "g.json"
        inp.write_text("][")
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 2

    def test_cli_malformed_record_exit2(self, tmp_path):
        inp = tmp_path / "m.json"
        inp.write_text(json.dumps([{"test": "t"}]))  # no error
        rc = mod.main(["--failures-json", str(inp)])
        assert rc == 2
