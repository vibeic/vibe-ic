"""Unit tests for `phase1_verify_aggregate.py`."""
import importlib
import json

import pytest

mod = importlib.import_module("phase1_verify_aggregate")


class TestLDocPresence:
    def test_finds_l_doc_when_present(self, tmp_path):
        (tmp_path / "generated_docs").mkdir()
        (tmp_path / "generated_docs" / "L1_PRODUCT_VISION.json").write_text(
            json.dumps({"vision": "x"}))
        presence = mod.scan_l_doc_presence(tmp_path)
        assert presence["L1_PRODUCT_VISION"] is True

    def test_missing_l_doc_returns_false(self, tmp_path):
        (tmp_path / "generated_docs").mkdir()
        presence = mod.scan_l_doc_presence(tmp_path)
        assert all(v is False for v in presence.values())

    def test_short_name_alias_accepted(self, tmp_path):
        (tmp_path / "generated_docs").mkdir()
        (tmp_path / "generated_docs" / "L1.json").write_text("{}")
        presence = mod.scan_l_doc_presence(tmp_path)
        assert presence["L1_PRODUCT_VISION"] is True


class TestAggregator:
    def _check(self, name, exit_code):
        return mod.CheckResult(name=name, exit_code=exit_code,
                                stdout_tail="", stderr_tail="")

    def test_all_pass_with_all_docs(self):
        presence = {d: True for d in mod.L_DOCS}
        checks = [self._check("a", 0), self._check("b", 0)]
        rep = mod.aggregate(mod.Path("/x"), checks, presence)
        assert rep.verdict == "PASS"

    def test_missing_doc_fails(self):
        presence = {d: True for d in mod.L_DOCS}
        presence["L7_REGISTER_MAP"] = False
        rep = mod.aggregate(mod.Path("/x"),
                             [self._check("a", 0)], presence)
        assert rep.verdict == "FAIL"

    def test_failed_check_fails(self):
        presence = {d: True for d in mod.L_DOCS}
        rep = mod.aggregate(mod.Path("/x"),
                             [self._check("a", 1)], presence)
        assert rep.verdict == "FAIL"

    def test_attribution(self):
        rep = mod.aggregate(mod.Path("/x"), [],
                             {d: True for d in mod.L_DOCS})
        d = rep.as_dict()
        assert "v0.1.50" in d["emitted_by"]


class TestMarkdownEmit:
    def test_table_present(self):
        rep = mod.aggregate(mod.Path("/x"), [],
                             {d: True for d in mod.L_DOCS})
        md = mod.report_to_markdown(rep)
        assert "| L doc | Present |" in md

    def test_refuse_to_overclaim(self):
        rep = mod.aggregate(mod.Path("/x"), [],
                             {d: True for d in mod.L_DOCS})
        md = mod.report_to_markdown(rep)
        assert "Refuse to overclaim" in md
