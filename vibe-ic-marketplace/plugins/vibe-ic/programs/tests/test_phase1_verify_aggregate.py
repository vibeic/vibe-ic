"""Unit tests for `phase1_verify_aggregate.py`."""
import importlib
import json

import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
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
        assert d["emitted_by"] == \
            f"phase1_verify_aggregate v{shipped_plugin_version()}"


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


class TestBackingCheckArgShape:
    """Regression for the positional <project> arg-drift: each backing check
    must be invoked with the ARG SHAPE it actually accepts, not <project>
    positionally for all of them."""

    def test_gate_contract_gets_no_positional(self, tmp_path):
        cmd = mod.build_check_cmd("phase1_gate_contract_check.py", tmp_path)
        # gate_contract takes NO positional (only --gates) — passing <project>
        # positionally argparse-errors (exit 2) = spurious FAIL.
        assert not any(str(tmp_path) == a for a in cmd)
        assert cmd[-1].endswith("phase1_gate_contract_check.py")

    def test_docsdir_checks_get_generated_docs_not_project(self, tmp_path):
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L1_DATASHEET.json").write_text("{}")
        for name in ("phase1_doc_presence_check.py",
                     "phase1_consistency_check.py"):
            cmd = mod.build_check_cmd(name, tmp_path)
            assert cmd[-1] == str(docs), (name, cmd)
            assert cmd[-1] != str(tmp_path)

    def test_project_checks_get_project_root(self, tmp_path):
        for name in ("phase1_all_l_docs_present_check.py",
                     "phase1_doc_input_completeness_check.py",
                     "phase1_input_vs_generated_completeness_check.py",
                     "phase1_evidence_grounding_check.py"):
            cmd = mod.build_check_cmd(name, tmp_path)
            assert cmd[-1] == str(tmp_path), (name, cmd)

    def test_resolve_docs_dir_prefers_canonical_then_flat(self, tmp_path):
        # flat only
        flat = tmp_path / "generated_docs"
        flat.mkdir()
        (flat / "L1_DATASHEET.json").write_text("{}")
        assert mod.resolve_docs_dir(tmp_path) == flat
        # canonical present + populated -> wins
        canon = tmp_path / "phase1" / "generated_docs"
        canon.mkdir(parents=True)
        (canon / "L1_DATASHEET.json").write_text("{}")
        assert mod.resolve_docs_dir(tmp_path) == canon

    def test_three_named_checks_pass_via_aggregate(self, tmp_path):
        """End-to-end: the 3 arg-drift victims PASS (exit 0) when the aggregate
        drives them on a valid canonical-layout project."""
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        payload = {
            "L1_DATASHEET": {"ic_name": "x", "class_path": "digital > digital-ic"},
            "L2_FRS": {"requirements": [{"id": "R1", "text": "a"}]},
            "L3_CMD_PROTOCOL": {"protocol_present": False, "reason": "none"},
            "L4_REGMAP": {"registers": [{"name": "CTRL"}]},
            "L5_ADI_SPEC": {"analog_digital_interfaces": []},
            "L6_CONTROL_LOGIC": {"submodule_control_logic": {"a": {}}},
            "L7_TEST_DEBUG": {"test_modes": [{"name": "scan"}]},
            "L8_TIMING_WAVEFORM": {"reset_timing": {"por_to_first_wake_ready_us": 1}},
            "L8_RTL_CONSTANTS": {"clock_frequency_hz": 50000000},
            "L9_INTEGRATION_SPEC": {"top_level_ports": [{"name": "clk"}],
                                    "submodules": ["a"]},
        }
        for name, obj in payload.items():
            (docs / f"{name}.json").write_text(json.dumps(obj))
        rep = mod.verify(tmp_path)
        by_name = {c.name: c for c in rep.check_results}
        for name in ("phase1_gate_contract_check.py",
                     "phase1_doc_presence_check.py",
                     "phase1_consistency_check.py"):
            assert by_name[name].exit_code == 0, (name, by_name[name])
