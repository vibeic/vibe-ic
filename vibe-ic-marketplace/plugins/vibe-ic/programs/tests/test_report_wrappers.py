"""Tests for thin wrapper programs that delegate to eda_report_audit / signoff_audit.

Updated 2026-04-22 after BENCH-A v0.47 pilot to reflect tightened anti-fabrication
gates: report fixtures must now include a tool-signature string AND meet a
min-size threshold. Hand-typed <500B stubs are rejected.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parent.parent

# Padding to clear MIN_REPORT_BYTES thresholds (1-2 KB per mode).
# Using a long comment-style filler keeps the report plausible.
_PADDING = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB


def _run_wrapper(name: str, project_dir: str) -> int:
    result = subprocess.run(
        [sys.executable, str(PROGRAMS_DIR / name), project_dir],
        capture_output=True, text=True, timeout=10
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
            "Circuits match.\nparameter mismatches: 0\n" + _PADDING
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
        (tmp_path / "design.gds").write_text("GDS")
        (tmp_path / "netlist.v").write_text("module top; endmodule")
        (tmp_path / "timing.rpt").write_text("WNS=0")
        (tmp_path / "drc.rpt").write_text("clean")
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
