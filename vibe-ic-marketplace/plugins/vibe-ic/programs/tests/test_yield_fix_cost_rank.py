"""Tests for yield_fix_cost_rank.py — the yield-diagnostic fix-cost
ordinal ranking spec table.

Covers: PASS (correct cost ordering), the real FAIL (unclassifiable fix /
bad input), and missing-data honesty (no vacuous PASS).
"""
import importlib
import json

mod = importlib.import_module("yield_fix_cost_rank")


class TestSpecOrdinalTable:
    def test_order_cheapest_first(self):
        # verbatim spec: test tweak < metal ECO < base-layer ECO < respin
        assert mod.CLASS_COST_ORDINAL["test_tweak"] < mod.CLASS_COST_ORDINAL["metal_eco"]
        assert mod.CLASS_COST_ORDINAL["metal_eco"] < mod.CLASS_COST_ORDINAL["base_layer_eco"]
        assert mod.CLASS_COST_ORDINAL["base_layer_eco"] < mod.CLASS_COST_ORDINAL["respin"]

    def test_all_classes_have_label_and_desc(self):
        for c in mod.REMEDIATION_CLASSES:
            assert c in mod.CLASS_COST_ORDINAL
            assert c in mod.CLASS_COST_LABEL
            assert c in mod.CLASS_DESC


class TestClassify:
    def test_test_tweak(self):
        assert mod.classify_fix("Relax test margin on BIN_X") == "test_tweak"
        assert mod.classify_fix("re-bin the failing parts") == "test_tweak"

    def test_metal_eco(self):
        assert mod.classify_fix("Metal ECO on clock tree") == "metal_eco"
        assert mod.classify_fix("metal-only reroute") == "metal_eco"

    def test_base_layer_eco_not_captured_by_metal(self):
        # "base-layer ECO" must NOT fall into metal_eco despite containing "ECO"
        assert mod.classify_fix("base-layer ECO to fix diffusion") == "base_layer_eco"

    def test_respin_wins(self):
        assert mod.classify_fix("full respin with new mask set") == "respin"

    def test_unknown_is_none(self):
        # no spec keyword -> None (caller treats as UNCLASSIFIED, no guessing)
        assert mod.classify_fix("buy a faster tester from the vendor") is None
        assert mod.classify_fix("") is None


class TestRank:
    def test_sorted_cheapest_first(self):
        fixes = [
            {"fix": "full respin"},
            {"fix": "Relax test margin on BIN_X"},
            {"fix": "base-layer ECO"},
            {"fix": "Metal ECO on clock tree"},
        ]
        ranked, unclassified = mod.rank_fixes(fixes)
        assert unclassified == []
        order = [e["class"] for e in ranked]
        assert order == ["test_tweak", "metal_eco", "base_layer_eco", "respin"]
        assert [e["rank"] for e in ranked] == [1, 2, 3, 4]

    def test_stable_within_class(self):
        fixes = [
            {"fix": "test tweak A"},
            {"fix": "test tweak B"},
        ]
        ranked, _ = mod.rank_fixes(fixes)
        assert ranked[0]["fix"] == "test tweak A"
        assert ranked[1]["fix"] == "test tweak B"

    def test_explicit_class_field(self):
        ranked, unclassified = mod.rank_fixes([{"fix": "do the thing",
                                                "class": "respin"}])
        assert unclassified == []
        assert ranked[0]["class"] == "respin"

    def test_uplift_and_risk_verbatim_not_synthesised(self):
        ranked, _ = mod.rank_fixes([{"fix": "metal ECO", "expected_uplift": "+5%",
                                     "risk": "Re-run P&R"}])
        assert ranked[0]["expected_uplift"] == "+5%"
        assert ranked[0]["risk"] == "Re-run P&R"


# ---------- CLI: PASS ----------
class TestCliPass:
    def test_pass_json_file(self, tmp_path, capsys):
        f = tmp_path / "fixes.json"
        f.write_text(json.dumps([
            {"fix": "respin"},
            {"fix": "test margin relax"},
        ]))
        op = tmp_path / "out.json"
        rc = mod.main([str(f), "--json", str(op)])
        assert rc == 0
        rep = json.loads(op.read_text())
        assert rep["verdict"] == "PASS"
        # cheapest first
        assert rep["ranked"][0]["class"] == "test_tweak"
        assert rep["ranked"][1]["class"] == "respin"

    def test_pass_single_fix(self):
        assert mod.main(["--fix", "Metal ECO on clock tree"]) == 0

    def test_markdown_emitted(self, tmp_path):
        f = tmp_path / "fixes.json"
        f.write_text(json.dumps([{"fix": "metal ECO", "expected_uplift": "+5%",
                                  "risk": "Re-run P&R"}]))
        op = tmp_path / "out.json"
        mod.main([str(f), "--json", str(op)])
        rep = json.loads(op.read_text())
        assert "Proposed fixes (by cost)" in rep["markdown"]
        assert "+5%" in rep["markdown"]


# ---------- CLI: the real FAIL ----------
class TestCliFail:
    def test_fail_unclassifiable_fix(self, tmp_path, capsys):
        f = tmp_path / "fixes.json"
        f.write_text(json.dumps([
            {"fix": "test margin relax"},
            {"fix": "ask the foundry nicely"},   # matches no spec class
        ]))
        rc = mod.main([str(f)])
        assert rc == 1
        assert "UNCLASSIFIED_FIX" in capsys.readouterr().out

    def test_fail_unparseable_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json")
        assert mod.main([str(f)]) == 1

    def test_fail_not_a_list(self, tmp_path):
        f = tmp_path / "obj.json"
        f.write_text(json.dumps({"foo": "bar"}))
        assert mod.main([str(f)]) == 1

    def test_fail_empty_list(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("[]")
        assert mod.main([str(f)]) == 1


# ---------- missing-data honesty ----------
class TestHonesty:
    def test_skip_on_missing_file(self):
        assert mod.main(["/no/such/fixes.json"]) == 2

    def test_no_input_fails(self):
        # no file, no --fix -> honest FAIL, not vacuous PASS
        assert mod.main([]) == 1
