"""Unit tests for `signoff_ladder_run.py`."""
import importlib
import json

mod = importlib.import_module("signoff_ladder_run")


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


class TestPerTierChecks:
    def test_drc_pass(self, tmp_path):
        _write_json(tmp_path / "reports/drc/full_deck.json",
                     {"violations": 0})
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "PASS"

    def test_drc_fail(self, tmp_path):
        _write_json(tmp_path / "reports/drc/full_deck.json",
                     {"violations": 1780})
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "FAIL"
        assert r.details["violations"] == 1780

    def test_drc_not_run(self, tmp_path):
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "NOT_RUN"

    def test_pdn_pass(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/pdn.json",
                     {"specialnets": 2})
        r = mod.check_tier_2_pdn(tmp_path)
        assert r.verdict == "PASS"

    def test_pdn_fail_zero_specialnets(self, tmp_path):
        # The spm pilot Tier 2 bug: zero SPECIALNETS = silicon DOA
        _write_json(tmp_path / "reports/pnr/pdn.json",
                     {"specialnets": 0})
        r = mod.check_tier_2_pdn(tmp_path)
        assert r.verdict == "FAIL"

    def test_ir_pass_under_budget(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/ir_drop.json",
                     {"worst_ir_uv": 20.0})
        r = mod.check_tier_2_ir(tmp_path, budget_uv=35.0)
        assert r.verdict == "PASS"

    def test_ir_fail_over_budget(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/ir_drop.json",
                     {"worst_ir_uv": 50.0})
        r = mod.check_tier_2_ir(tmp_path, budget_uv=35.0)
        assert r.verdict == "FAIL"

    def test_decap_pass(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/decap_count.json",
                     {"decap_cells": 2079})  # spm v0.1.48
        r = mod.check_tier_2_decap(tmp_path)
        assert r.verdict == "PASS"

    def test_decap_fail_zero(self, tmp_path):
        # spm v0.1.47 bug: zero decap cells
        _write_json(tmp_path / "reports/pnr/decap_count.json",
                     {"decap_cells": 0})
        r = mod.check_tier_2_decap(tmp_path)
        assert r.verdict == "FAIL"

    def test_antenna_both_clean(self, tmp_path):
        _write_json(tmp_path / "reports/antenna/magic.json",
                     {"violations": 0})
        _write_json(tmp_path / "reports/antenna/klayout.json",
                     {"violations": 0})
        r = mod.check_tier_3_antenna(tmp_path)
        assert r.verdict == "PASS"

    def test_antenna_one_violator(self, tmp_path):
        _write_json(tmp_path / "reports/antenna/magic.json",
                     {"violations": 5})
        _write_json(tmp_path / "reports/antenna/klayout.json",
                     {"violations": 0})
        r = mod.check_tier_3_antenna(tmp_path)
        assert r.verdict == "FAIL"

    def test_lvs_device_pass(self, tmp_path):
        _write_json(tmp_path / "reports/lvs/device_class.json",
                     {"device_class_match": True, "layout": 261,
                      "schematic": 261})
        r = mod.check_tier_4_lvs_device(tmp_path)
        assert r.verdict == "PASS"

    def test_lvs_net_waived(self, tmp_path):
        # spm pilot path: open-source LVS net-level WAIVED (commercial closes)
        _write_json(tmp_path / "reports/lvs/net_level.json",
                     {"verdict": "WAIVED",
                      "rationale": "blackbox-macro open-source gap"})
        r = mod.check_tier_4_5_lvs_net(tmp_path)
        assert r.verdict == "WAIVED"

    def test_latchup_pass(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/tapcell_density.json",
                     {"tapcells_per_mm2": 384})  # spm v0.1.46
        r = mod.check_tier_5_latchup(tmp_path)
        assert r.verdict == "PASS"

    def test_latchup_fail_zero(self, tmp_path):
        # spm v0.1.45 bug: zero tap cells = real silicon latch-up risk
        _write_json(tmp_path / "reports/pnr/tapcell_density.json",
                     {"tapcells_per_mm2": 0})
        r = mod.check_tier_5_latchup(tmp_path)
        assert r.verdict == "FAIL"


class TestAggregateVerdict:
    def test_all_pass_no_waivers(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS")]
        assert mod.aggregate_verdict(tiers) == "PASS"

    def test_any_fail(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                  mod.TierResult("T5", "Latchup", "FAIL")]
        assert mod.aggregate_verdict(tiers) == "FAIL"

    def test_waived_promotes_to_pass_with_waivers(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                  mod.TierResult("T4.5", "LVS net", "WAIVED")]
        assert mod.aggregate_verdict(tiers) == "PASS_WITH_WAIVERS"

    def test_not_run_promotes_to_pass_with_waivers(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                  mod.TierResult("T1.5", "DRC heatmap", "NOT_RUN")]
        assert mod.aggregate_verdict(tiers) == "PASS_WITH_WAIVERS"

    def test_warn_overrides_pass(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                  mod.TierResult("T2", "PDN", "WARN")]
        assert mod.aggregate_verdict(tiers) == "WARN"


class TestRunLadder:
    def test_full_ladder_returns_10_tiers(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        # All NOT_RUN but the ladder must produce 10 tier entries
        assert len(rep.tiers) == 10

    def test_attribution(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        assert "v0.1.51" in rep.as_dict()["emitted_by"]


class TestReportToMarkdown:
    def test_includes_overall_verdict(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        md = mod.report_to_markdown(rep)
        assert "Overall verdict" in md
        assert "PASS_WITH_WAIVERS" in md

    def test_doctrine_quote(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        md = mod.report_to_markdown(rep)
        assert "doctrine" in md.lower()
