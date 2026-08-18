"""Unit tests for design_complexity_estimator.py.

Covers monotonicity of the score, tier mapping, score cap, per-tier
recommendations, and feature extraction from a project directory.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'design_complexity_estimator.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import design_complexity_estimator as dce  # noqa: E402


# ---------------------------------------------------------------------------
# Score behaviour
# ---------------------------------------------------------------------------
def test_empty_design_is_trivial():
    res = dce.estimate(dce.ComplexityFeatures())
    assert res.score == 0.0
    assert res.tier == "TRIVIAL"


def test_score_monotonic_in_loc():
    small = dce.estimate(dce.ComplexityFeatures(loc=200)).score
    big = dce.estimate(dce.ComplexityFeatures(loc=40000)).score
    assert big > small


def test_score_capped_at_100():
    res = dce.estimate(dce.ComplexityFeatures(
        loc=10_000_000, num_modules=10_000, num_clocks=50,
        max_bit_width=4096, sram_count=200, macro_count=200,
        target_freq_mhz=5000))
    assert res.score <= 100.0
    assert res.tier == "COMPLEX"


def test_extra_clocks_increase_score():
    one = dce.estimate(dce.ComplexityFeatures(loc=5000, num_clocks=1)).score
    many = dce.estimate(dce.ComplexityFeatures(loc=5000, num_clocks=6)).score
    assert many > one


def test_tiers_are_ordered():
    scores_tiers = [
        dce.estimate(dce.ComplexityFeatures(loc=loc)).tier
        for loc in (0, 2000, 12000, 60000, 200000)
    ]
    # tiers should be non-decreasing in nominal "size"
    order = ["TRIVIAL", "SMALL", "MEDIUM", "LARGE", "COMPLEX"]
    idx = [order.index(t) for t in scores_tiers]
    assert idx == sorted(idx)


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------
def test_recommendations_present_and_typed():
    res = dce.estimate(dce.ComplexityFeatures(loc=70000, sram_count=10))
    rec = res.recommendations
    assert set(rec) >= {"prefer_catalog_glue", "synth_effort",
                        "run_fpga_early_prototype", "sta_corners", "advice"}
    assert isinstance(rec["prefer_catalog_glue"], bool)


def test_large_designs_prefer_catalog_glue():
    res = dce.estimate(dce.ComplexityFeatures(
        loc=120000, num_modules=200, sram_count=20, macro_count=10))
    assert res.tier in ("LARGE", "COMPLEX")
    assert res.recommendations["prefer_catalog_glue"] is True


def test_trivial_does_not_force_fpga():
    res = dce.estimate(dce.ComplexityFeatures(loc=100))
    assert res.recommendations["run_fpga_early_prototype"] is False


# ---------------------------------------------------------------------------
# Feature extraction from a project dir
# ---------------------------------------------------------------------------
def test_features_from_project(tmp_path):
    (tmp_path / "core.v").write_text(
        "module core(input clk, input rst, output [31:0] dout);\n"
        "  reg [31:0] acc;\n"
        "  always @(posedge clk) acc <= acc + 1;\n"
        "endmodule\n"
        "module sram_bank(input clk);\n"
        "endmodule\n"
    )
    feats = dce.features_from_project(tmp_path)
    assert feats.num_modules == 2
    assert feats.max_bit_width == 32
    assert feats.num_clocks >= 1
    assert feats.sram_count >= 1     # sram_bank matched
    assert feats.loc > 0


def test_features_from_empty_project(tmp_path):
    feats = dce.features_from_project(tmp_path)
    assert feats.num_modules == 0
    assert feats.loc == 0
    assert feats.num_clocks == 1     # floor


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_features_json(tmp_path, capsys):
    feats_file = tmp_path / "feats.json"
    feats_file.write_text(json.dumps({"loc": 70000, "num_modules": 100}))
    rc = dce.main(["--features", str(feats_file)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "score" in out and "tier" in out and "recommendations" in out


def test_cli_project_dir(tmp_path, capsys):
    (tmp_path / "m.v").write_text("module m(input clk); endmodule\n")
    rc = dce.main([str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["features"]["num_modules"] == 1


def test_cli_requires_input(capsys):
    with pytest.raises(SystemExit):
        dce.main([])
