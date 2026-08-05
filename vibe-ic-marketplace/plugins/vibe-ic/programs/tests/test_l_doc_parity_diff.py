"""Unit tests for `l_doc_parity_diff.py`."""
import importlib
import json

import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("l_doc_parity_diff")


class TestFlatten:
    def test_nested_dict(self):
        out = mod._flatten_keys({"a": {"b": {"c": 1}}})
        assert "a.b.c" in out
        assert out["a.b.c"] == 1

    def test_list_kept_intact(self):
        out = mod._flatten_keys({"a": [1, 2, 3]})
        assert out["a"] == [1, 2, 3]

    def test_empty(self):
        assert mod._flatten_keys({}) == {}


class TestIsEmpty:
    def test_none(self):
        assert mod._is_empty(None)
    def test_empty_str(self):
        assert mod._is_empty("")
    def test_empty_list(self):
        assert mod._is_empty([])
    def test_empty_dict(self):
        assert mod._is_empty({})
    def test_nonempty(self):
        assert not mod._is_empty("x")
        assert not mod._is_empty([1])


class TestDiffSingleLDoc:
    def _write(self, tmp_path, name, data):
        p = tmp_path / name
        p.write_text(json.dumps(data))
        return p

    def test_clean_parity_no_findings(self, tmp_path):
        p = self._write(tmp_path, "L1_DATASHEET.json",
                         {"ic_name": "X", "fields": {"a": 1}})
        a = self._write(tmp_path, "L1_DATASHEET.json.agent",
                         {"ic_name": "X", "fields": {"a": 1}})
        # Make symlink-like setup: agent is in separate dir
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        ap = self._write(agent_dir, "L1_DATASHEET.json",
                          {"ic_name": "X", "fields": {"a": 1}})
        stats, findings = mod.diff_single_l_doc(p, ap)
        assert stats.total_divergences == 0

    def test_absent_in_program(self, tmp_path):
        prog = self._write(tmp_path, "L1.json", {"a": "x"})
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        ag = self._write(agent_dir, "L1.json", {"a": "x", "b": "y"})
        stats, findings = mod.diff_single_l_doc(prog, ag)
        absent = [f for f in findings if f.category == "ABSENT_IN_PROGRAM"]
        assert len(absent) == 1
        assert absent[0].key == "b"

    def test_value_mismatch(self, tmp_path):
        prog = self._write(tmp_path, "L1.json", {"a": "wrong"})
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        ag = self._write(agent_dir, "L1.json", {"a": "right"})
        stats, findings = mod.diff_single_l_doc(prog, ag)
        vm = [f for f in findings if f.category == "VALUE_MISMATCH"]
        assert len(vm) == 1
        assert vm[0].program_value == "wrong"
        assert vm[0].agent_value == "right"

    def test_hallucinated_arm_boilerplate(self, tmp_path):
        prog = self._write(tmp_path, "L1.json",
                            {"ic_name": "SUCH ARM TECHNOLOGY"})
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        ag = self._write(agent_dir, "L1.json",
                          {"ic_name": "AMBA AXI Protocol"})
        stats, findings = mod.diff_single_l_doc(prog, ag)
        halluc = [f for f in findings if f.category == "HALLUCINATED"]
        assert len(halluc) == 1
        assert "license boilerplate" in halluc[0].why

    def test_hallucinated_opcode_in_non_opcode_doc(self, tmp_path):
        prog = self._write(tmp_path, "L3.json",
                            {"opcodes": [{"opcode_hex": "0x16"}]})
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        ag = self._write(agent_dir, "L3.json", {"channels": ["AR", "R"]})
        stats, findings = mod.diff_single_l_doc(prog, ag)
        halluc = [f for f in findings if f.category == "HALLUCINATED"]
        assert any("opcode" in f.why for f in halluc)

    def test_shape_mismatch(self, tmp_path):
        prog = self._write(tmp_path, "L1.json", {"a": 1, "b": 2})
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        ag = self._write(agent_dir, "L1.json", {"a": 1, "c": 3})
        stats, findings = mod.diff_single_l_doc(prog, ag)
        sm = [f for f in findings if f.category == "SHAPE_MISMATCH"]
        assert len(sm) == 1


class TestParityStats:
    def test_clean_is_100_pct(self):
        s = mod.LDocStats("L1", 100, 100, 5, 5, 0, 0, 0, 0)
        assert s.parity_pct == 100.0

    def test_half_divergent(self):
        s = mod.LDocStats("L1", 100, 100, 5, 10, 5, 0, 0, 0)
        # divergences=5, agent_keys=10 → parity = 50%
        assert s.parity_pct == 50.0

    def test_more_divergences_than_keys_clamps_to_0(self):
        s = mod.LDocStats("L1", 100, 100, 5, 1, 100, 0, 0, 0)
        assert s.parity_pct == 0.0


class TestMarkdownEmit:
    def test_includes_attribution(self):
        md = mod.report_to_markdown([], [])
        assert "l_doc_parity_diff.py" in md
        assert f"(v{shipped_plugin_version()})." in md

    def test_hallucination_section_when_present(self):
        s = mod.LDocStats("L1", 100, 100, 5, 5, 0, 1, 0, 0)
        f = mod.Finding(l_doc="L1", category="HALLUCINATED",
                         key="x", program_value="bad",
                         agent_value=None, why="hallucination")
        md = mod.report_to_markdown([s], [f])
        assert "## Hallucinations (PRIORITY)" in md
        assert "bad" in md

    def test_doctrine_quote(self):
        md = mod.report_to_markdown([], [])
        assert "Doctrine" in md
