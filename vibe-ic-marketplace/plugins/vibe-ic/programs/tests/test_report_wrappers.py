"""Tests for thin wrapper programs that delegate to eda_report_audit / signoff_audit.

Updated 2026-04-22 after BENCH-A v0.47 pilot to reflect tightened anti-fabrication
gates: report fixtures must now include a tool-signature string AND meet a
min-size threshold. Hand-typed <500B stubs are rejected.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gdsii  # noqa: E402
import _si_signoff_fixture  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# 2026-07-27 (review follow-up): the tape-out GDS slot credits ONLY the flow's
# declared stream-out artefact (phase3/stage4/gds/*.gds), and only when it
# carries real GDSII substance. This file's subject is not the GDS slot; it
# just needs that slot satisfied, so its tape-out artefact is now a real
# minimal GDSII stream at the declared path rather than a text placeholder.

PROGRAMS_DIR = Path(__file__).resolve().parent.parent

# Padding to clear MIN_REPORT_BYTES thresholds (1-2 KB per mode).
# Using a long comment-style filler keeps the report plausible.
_PADDING = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB


def _run_wrapper(name: str, project_dir: str) -> int:
    result = _pr.run(
        [sys.executable, str(PROGRAMS_DIR / name), project_dir],
        capture_output=True, text=True, 
    )
    return result.returncode


class TestDrcReportCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("drc_report_check.py", str(tmp_path)) == 1

    def test_with_report_passes(self, tmp_path):
        """Must contain both category keywords AND a tool signature AND be large
        enough (≥ MIN_REPORT_BYTES['drc'] = 2048). Hand-typed 60-byte stubs
        are now rejected."""
        rpt = tmp_path / "drc_results.rpt"
        rpt.write_text(
            "[INFO drt-0012] OpenROAD detailed_route started\n"
            "Layer M1 spacing violation at (1.2, 3.4): 0.12 um\n"
            "Layer M2 width violation at (5.0, 2.1): 0.15 um\n"
            "Layer M3 via enclosure error at (3.0, 4.5)\n"
            "Total: 0 violations (3 waived)\n"
            "DRC clean\n" + _PADDING
        )
        assert _run_wrapper("drc_report_check.py", str(tmp_path)) == 0

    def test_stub_rejected(self, tmp_path):
        """Anti-fabrication: a tiny hand-typed DRC stub must FAIL."""
        rpt = tmp_path / "drc.rpt"
        rpt.write_text("spacing: 0\nwidth: 0\ntotal: 0 violations\n")  # 45 B
        assert _run_wrapper("drc_report_check.py", str(tmp_path)) == 1


class TestLvsReportCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("lvs_report_check.py", str(tmp_path)) == 1

    def test_with_report_passes(self, tmp_path):
        rpt = tmp_path / "lvs_results.rpt"
        rpt.write_text(
            "Netgen LVS\nNET count: 4921\ndevice count: 1872\n"
            "Number of topologically valid matches: 1872\n"
            # #507: netgen's REAL terminal PASS token is 'Circuits match
            # uniquely.' (the token the runner's #477 step_lvs keys on);
            # the bare 'Circuits match.' is not netgen's verdict line.
            "Final result: Circuits match uniquely.\n"
            "parameter mismatches: 0\n" + _PADDING
        )
        assert _run_wrapper("lvs_report_check.py", str(tmp_path)) == 0

    def test_stub_rejected(self, tmp_path):
        rpt = tmp_path / "lvs.rpt"
        rpt.write_text("net: OK\ndevice: OK\n")
        assert _run_wrapper("lvs_report_check.py", str(tmp_path)) == 1


class TestPowerReportCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("power_report_check.py", str(tmp_path)) == 1

    def test_with_report_passes(self, tmp_path):
        rpt = tmp_path / "power_analysis.rpt"
        rpt.write_text(
            "OpenROAD Power Report\n"
            "Group: sequential   Internal Power: 0.12 mW\n"
            "Group: combinational Switching Power: 0.34 mW\n"
            "Leakage Power: 0.05 mW (static power)\n"
            "Total Power: 0.51 mW\n" + _PADDING
        )
        assert _run_wrapper("power_report_check.py", str(tmp_path)) == 0

    def test_stub_rejected(self, tmp_path):
        rpt = tmp_path / "power.rpt"
        rpt.write_text("leakage: 1 mW\ndynamic: 5 mW\n")
        assert _run_wrapper("power_report_check.py", str(tmp_path)) == 1


class TestEmReportCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("em_report_check.py", str(tmp_path)) == 1

    def test_with_report_passes(self, tmp_path):
        rpt = tmp_path / "em_analysis.rpt"
        rpt.write_text(
            "OpenROAD Electromigration Analysis\n"
            "EM lifetime: 10 years worst-case\n"
            "Javg = 2.5 mA/um  current density\n"
            "Jpeak = 8.1 mA/um  peak current\n"
            "RMS current: 3.2 mA/um\n" + _PADDING
        )
        assert _run_wrapper("em_report_check.py", str(tmp_path)) == 0

    def test_stub_rejected(self, tmp_path):
        rpt = tmp_path / "em.rpt"
        rpt.write_text("Javg = 0.1 mA\nOK\n")
        assert _run_wrapper("em_report_check.py", str(tmp_path)) == 1


class TestIrDropReportCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("ir_drop_report_check.py", str(tmp_path)) == 1

    def test_with_report_passes(self, tmp_path):
        rpt = tmp_path / "ir_drop.rpt"
        rpt.write_text(
            "OpenROAD PSM IR drop analysis\n"
            "power grid mesh nodes: 12458\n"
            "worst voltage drop: 6.8 mV (0.2% Vdd) static IR\n"
            "worst dynamic IR: 9.1 mV (0.3% Vdd)\n" + _PADDING
        )
        assert _run_wrapper("ir_drop_report_check.py", str(tmp_path)) == 0

    def test_stub_rejected(self, tmp_path):
        rpt = tmp_path / "ir_drop.rpt"
        rpt.write_text("IR drop: 6 mV OK\n")
        assert _run_wrapper("ir_drop_report_check.py", str(tmp_path)) == 1


class TestStaReportCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("sta_report_check.py", str(tmp_path)) == 1

    def test_with_report_passes(self, tmp_path):
        rpt = tmp_path / "sta_timing.rpt"
        rpt.write_text(
            "OpenSTA timing report\n"
            "Startpoint: clk_i\nEndpoint: out_q\n"
            "WNS = 0.15 ns\nTNS = 0.0 ns\n"
            "slack (MET)\nsetup check: PASS\nhold check: PASS\n"
            "data arrival time: 2.34 ns\n" + _PADDING
        )
        assert _run_wrapper("sta_report_check.py", str(tmp_path)) == 0

    def test_stub_rejected(self, tmp_path):
        rpt = tmp_path / "sta.rpt"
        rpt.write_text("WNS=0 setup: OK hold: OK\n")
        assert _run_wrapper("sta_report_check.py", str(tmp_path)) == 1


class TestTapeoutSignoffCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("tapeout_signoff_check.py", str(tmp_path)) == 1

    def test_with_evidence_passes(self, tmp_path):
        _gdsii.write_declared_streamout(tmp_path, "design.gds")
        (tmp_path / "netlist.v").write_text("module top; endmodule")
        (tmp_path / "timing.rpt").write_text("WNS=0")
        # #437(a): the tapeout DRC slot now gates on a PARSED violation
        # count — an unparseable "clean" stub is refused, so the fixture
        # carries a parseable zero-count signoff shape.
        (tmp_path / "drc.rpt").write_text("Total violations: 0\n")
        # 2026-07-27: tapeout mode gained a fifth pillar (LVS) — a tape-out is
        # DEFINED by a genuine layout-vs-schematic match, so "with evidence"
        # now means five slots, not four.
        (tmp_path / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
        (tmp_path / "reports/phase3/lvs.rpt").write_text(
            "Netlists match uniquely.\n"
            "Final result: Circuits match uniquely.\n")
        # 2026-07-28: tape-out mode gained an SI (crosstalk-delay) blocking
        # condition — a run whose crosstalk-delay check proved nothing, or
        # never ran, no longer certifies. "With evidence" now includes a
        # PROVED SI verdict.
        _si_signoff_fixture.write_proved_si_report(tmp_path)
        assert _run_wrapper("tapeout_signoff_check.py", str(tmp_path)) == 0


class TestFlowStageCheck:
    def test_empty_dir_fails(self, tmp_path):
        assert _run_wrapper("flow_stage_check.py", str(tmp_path)) == 1

    def test_with_stages_passes(self, tmp_path):
        """All 4 stages must have REAL evidence (not just empty dirs).
        Updated 2026-04-22: threshold tightened 3/4 → 4/4 per LL
        feedback_plugin_usage_discipline.md."""
        (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
        (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
        (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
        (tmp_path / "phase3" / "stage3" / "sta").mkdir(parents=True)
        (tmp_path / "phase2" / "stage2" / "synth" / "synth.log").write_text("synthesis done\n")
        (tmp_path / "phase3" / "stage3" / "pnr" / "pnr.log").write_text("place/route done\n")
        (tmp_path / "phase3" / "stage4" / "gds" / "chip.gds").write_text("binary gds\n")
        (tmp_path / "phase3" / "stage3" / "sta" / "sta_report.rpt").write_text("WNS=0 TNS=0\n")
        assert _run_wrapper("flow_stage_check.py", str(tmp_path)) == 0

    def test_empty_stages_strict_fails(self, tmp_path):
        """Empty stage dirs are NOT sufficient evidence under strict mode."""
        (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
        (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
        (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
        (tmp_path / "phase3" / "stage3" / "sta").mkdir(parents=True)
        assert _run_wrapper("flow_stage_check.py", str(tmp_path)) == 1
