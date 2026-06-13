#!/usr/bin/env python3
"""Tests for rx_classifier_thresholds_match_l8_check.py (Wave 14 / v0.119.47)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent / "rx_classifier_thresholds_match_l8_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


def _make_project(tmp_path: Path,
                  l8_table: dict | None,
                  rtl_files: dict[str, str],
                  waiver: str | None = None) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if l8_table is not None:
        (proj / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
            json.dumps({"rx_classifier_ticks": l8_table}, indent=2))
    for fname, body in rtl_files.items():
        (proj / "phase2" / "stage1" / "rtl" / fname).write_text(body)
    if waiver:
        (proj / "waivers.json").write_text(json.dumps(
            {"rx_classifier_thresholds_simplified_intentional": waiver}))
    return proj


# ----------------------------------------------------------------------

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "rx_classifier" in r.stdout.lower()


def test_full_match_pass(tmp_path):
    """RTL declares all six L8 thresholds as localparams → PASS."""
    rtl = """
    module rx_phy(input clk, input id_bus_in, output reg [7:0] rx_byte);
      localparam int H1_MIN_TICKS = 1;
      localparam int H1_MAX_TICKS = 195;
      localparam int H0_MIN_TICKS = 196;
      localparam int H0_MAX_TICKS = 636;
      localparam int BR_MIN_TICKS = 637;
      localparam int BR_MAX_TICKS = 1314;
      reg [15:0] low_cnt;
      always @(posedge clk) begin
        if (low_cnt > H0_MIN_TICKS) rx_byte <= 8'h00;
      end
    endmodule
    """
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 195,
        "h0_min": 196, "h0_max": 636,
        "br_min": 637, "br_max": 1314,
    }, {"rx_phy.sv": rtl})
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_single_threshold_collapse_fail(tmp_path):
    """Reproduces the v0.119.46 case: L8 has 6 thresholds, RTL only 1."""
    rtl = """
    module rx_phy(input clk, output reg [7:0] rx_byte);
      localparam int T_BIT_DECODE_THRESHOLD = 200;
      reg [15:0] low_cnt;
      always @(posedge clk) begin
        if (low_cnt > T_BIT_DECODE_THRESHOLD) rx_byte <= 8'h00;
      end
    endmodule
    """
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 195,
        "h0_min": 196, "h0_max": 636,
        "br_min": 637, "br_max": 1314,
    }, {"rx_phy.sv": rtl})
    r = _run([str(proj), "--json"])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["verdict"] == "FAIL"
    missing = set(out["summary"]["missing"])
    # The single threshold (200) is within tolerance of nothing in L8
    # (closest is h1_max=195 → diff 5). So h0_max, h1_min, h1_max,
    # br_min, br_max all missing. (h0_min=196 ±1 also misses 200.)
    assert "h0_max" in missing
    assert "h1_min" in missing
    assert "h1_max" in missing
    assert "br_min" in missing
    assert "br_max" in missing


def test_value_mismatch_fail(tmp_path):
    """RTL has 6 localparams but H0_MAX=600 vs L8=612 → FAIL."""
    rtl = """
    module rx_phy(input clk, output reg [7:0] rx_byte);
      localparam int H1_MIN_TICKS = 1;
      localparam int H1_MAX_TICKS = 195;
      localparam int H0_MIN_TICKS = 196;
      localparam int H0_MAX_TICKS = 600;
      localparam int BR_MIN_TICKS = 637;
      localparam int BR_MAX_TICKS = 1314;
      reg [15:0] cnt;
      always @(posedge clk) if (cnt > H0_MIN_TICKS) cnt <= 0;
    endmodule
    """
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 195,
        "h0_min": 196, "h0_max": 612,
        "br_min": 637, "br_max": 1314,
    }, {"rx_phy.sv": rtl})
    r = _run([str(proj), "--json"])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["verdict"] == "FAIL"
    assert "h0_max" in out["summary"]["missing"]


def test_within_tolerance_pass(tmp_path):
    """RTL has H0_MAX=611, L8=612 → within ±1 tolerance → PASS."""
    rtl = """
    module rx_phy(input clk, output reg [7:0] rx_byte);
      localparam int H1_MIN_TICKS = 1;
      localparam int H1_MAX_TICKS = 195;
      localparam int H0_MIN_TICKS = 196;
      localparam int H0_MAX_TICKS = 611;
      localparam int BR_MIN_TICKS = 637;
      localparam int BR_MAX_TICKS = 1314;
      reg [15:0] cnt;
      always @(posedge clk) if (cnt > H0_MIN_TICKS) cnt <= 0;
    endmodule
    """
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 195,
        "h0_min": 196, "h0_max": 612,
        "br_min": 637, "br_max": 1314,
    }, {"rx_phy.sv": rtl})
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "[PASS]" in r.stdout


def test_extra_rtl_threshold_warn(tmp_path):
    """RTL has all 6 L8 values + 1 extra unjustified magic → WARN."""
    rtl = """
    module rx_phy(input clk, output reg [7:0] rx_byte);
      localparam int H1_MIN_TICKS = 1;
      localparam int H1_MAX_TICKS = 195;
      localparam int H0_MIN_TICKS = 196;
      localparam int H0_MAX_TICKS = 636;
      localparam int BR_MIN_TICKS = 637;
      localparam int BR_MAX_TICKS = 1314;
      localparam int EXTRA_THRESHOLD_TICKS = 999;
      reg [15:0] cnt;
      always @(posedge clk) if (cnt > EXTRA_THRESHOLD_TICKS) cnt <= 0;
    endmodule
    """
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 195,
        "h0_min": 196, "h0_max": 636,
        "br_min": 637, "br_max": 1314,
    }, {"rx_phy.sv": rtl})
    r = _run([str(proj), "--json"])
    # WARN exits 0 (non-fatal)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "WARN"
    extras_vals = {e["value"] for e in out["summary"]["extras"]}
    assert 999 in extras_vals


def test_no_l8_classifier_skip(tmp_path):
    """L8 lacks rx_classifier_ticks → SKIP."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L8.json").write_text(json.dumps(
        {"some_other_field": 123}))
    (proj / "phase2" / "stage1" / "rtl" / "rx_phy.sv").write_text(
        "module rx_phy; localparam X = 1; endmodule\n")
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "SKIP"


def test_with_waiver_pass(tmp_path):
    """Explicit waiver ≥40 chars → PASS_WITH_WAIVER even when collapsed."""
    rtl = """
    module rx_phy(input clk, output reg [7:0] rx_byte);
      localparam int T_BIT_DECODE_THRESHOLD = 200;
      reg [15:0] cnt;
      always @(posedge clk) if (cnt > T_BIT_DECODE_THRESHOLD) cnt <= 0;
    endmodule
    """
    proj = _make_project(
        tmp_path,
        {"h1_min": 1, "h1_max": 195, "h0_min": 196,
         "h0_max": 636, "br_min": 637, "br_max": 1314},
        {"rx_phy.sv": rtl},
        waiver=("Single-threshold classifier is intentional for this MVP "
                "because the host bit timing is well-controlled and the "
                "vendor table will be re-introduced in v2."),
    )
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS_WITH_WAIVER"
