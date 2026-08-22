"""v0.2.66 canned cross-design report removal regressions.

Pins the #436 fix (ORGANIC-20260606-cross-ic-recycled-canned-pass-reports,
CRITICAL): the runner emitted CANNED signoff-class PASS reports that were
byte-identical across four different ICs and cited ANOTHER chip's signals,
scenarios, and testbench — a coverage PASS listing half-duplex
GET_ID/GET_STATE scenarios on chips whose own L3 says no opcodes, a CDC
trio citing a 3-FF `id_rx_syn` synchroniser on `id_bus` in projects with
no such signals (one with NO RTL at all), and a source-complexity advisory
reporting nonzero loc for a zero-RTL project.

Defenses pinned here:
  * CDC trio is generated from the PROJECT'S OWN RTL clock-edge scan —
    single-clock → honest PASS with crossings=[], multi-clock →
    SKIPPED-CONDITION (real CDC tool required), no RTL → SKIPPED-CONDITION;
    the canned `id_bus`/`id_rx_syn` constants are gone from the source.
  * coverage cites only THIS project's reference-TB transcript; the canned
    GET_ID scenario list is gone; no transcript → SKIPPED-CONDITION.
  * design_complexity features count only the canonical design RTL dir —
    a zero-RTL project reports loc=0.

chip-AGNOSTIC: source-shape pins + synthetic fixtures.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import design_complexity_estimator as DCE  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_RUNNER_SRC = (PLUGIN / "programs" / "design_one_shot_runner.py").read_text()


# ── source pins: the canned constants are GONE ─────────────────────────────

def test_canned_cdc_signals_removed_from_source():
    assert "id_rx_syn{1,2,3}" not in _RUNNER_SRC
    assert '"signal": "id_bus"' not in _RUNNER_SRC


def test_canned_coverage_scenarios_removed_from_source():
    assert '"GET_ID", "GET_STATE", "GET_INFO"' not in _RUNNER_SRC


def test_cdc_emit_is_rtl_scan_driven():
    i = _RUNNER_SRC.index("Step 3: CDC / RDC")
    window = _RUNNER_SRC[i:i + 3600]
    assert "SKIPPED-CONDITION" in window           # no-RTL / multi-clock
    assert "clock-edge scan" in window             # honest single-clock PASS
    assert "#436" in window


def test_coverage_emit_is_transcript_driven():
    i = _RUNNER_SRC.index("Coverage manifest (#436)")
    window = _RUNNER_SRC[i:i + 1800]
    assert "ref_logs" in window
    assert "SKIPPED-CONDITION" in window


# ── complexity features scope to the canonical design RTL ─────────────────

def test_zero_rtl_project_reports_zero_loc(tmp_path):
    # pure-analog shape: canonical rtl dir EMPTY, analog behavioral .v
    # present elsewhere — must NOT count as design source
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    ana = tmp_path / "analog" / "hardmacro"
    ana.mkdir(parents=True)
    (ana / "opamp_behav.v").write_text(
        "module opamp(input a, output y);\n  assign y = a;\nendmodule\n" * 40)
    feats = DCE.features_from_project(tmp_path)
    assert feats.loc == 0
    assert feats.num_modules == 0
    assert feats.sram_count == 0


def test_canonical_rtl_is_counted(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\nendmodule\n")
    feats = DCE.features_from_project(tmp_path)
    assert feats.loc > 0 and feats.num_modules == 1


def test_legacy_layout_fallback_still_works(tmp_path):
    # no canonical layout at all → the legacy sweep remains
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "core.v").write_text(
        "module core(input clk);\nendmodule\n")
    feats = DCE.features_from_project(tmp_path)
    assert feats.num_modules == 1
