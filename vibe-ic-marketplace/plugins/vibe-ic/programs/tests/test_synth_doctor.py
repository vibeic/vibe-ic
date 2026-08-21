"""Unit tests for `synth_doctor.py` and `pnr_doctor.py`.

Doctrine: the synth-doctor SKILL.md documents a 10+10 log-pattern -> canonical-fix
classifier. These tests feed canonical Yosys / OpenROAD error-log snippets
(chip-AGNOSTIC, no benchmark name) and assert the correct pattern + a non-empty
fix; then feed a clean log and assert NO false match (the no-false-alert
contract: deny-list + length-floor + UNKNOWN-only-on-real-error).
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

synth = importlib.import_module("synth_doctor")
pnr = importlib.import_module("pnr_doctor")

SYNTH_SCRIPT = Path(__file__).parent.parent / "synth_doctor.py"
PNR_SCRIPT = Path(__file__).parent.parent / "pnr_doctor.py"
assert SYNTH_SCRIPT.exists() and PNR_SCRIPT.exists()


# --------------------------------------------------------------------------- #
# synth_doctor — canonical Yosys-log snippets per documented pattern.
# --------------------------------------------------------------------------- #
SYNTH_CASES = {
    "UNPACKED_ARRAY": "ERROR: Unpacked array used as module port is not supported.",
    "MULTI_DRIVER": "Warning: signal out_reg is driven by multiple drivers.",
    "RETURN_IN_FUNC": "ERROR: return statement is not allowed inside a function.",
    "PAST_IN_COMB": "ERROR: System function \\$past used in combinational context.",
    "AUTOMATIC_IN_FF": "ERROR: Local declaration in unnamed block is only "
                       "supported in SystemVerilog mode!",
    "LATCH_INFERENCE": "Warning: inferring a latch for signal state_next.",
    "MODULE_NOT_FOUND": "ERROR: Module \\sub_unit not found in design.",
    "WIDTH_MISMATCH": "Warning: width mismatch in assignment, truncating from "
                      "16 bits to 12 bits.",
    "SYNTAX_ERROR": "ERROR: syntax error, unexpected TOK_ID near 'endmodule'.",
}


class TestSynthClassifyLine:
    @pytest.mark.parametrize("pattern,line", list(SYNTH_CASES.items()))
    def test_each_canonical_pattern_matches(self, pattern, line):
        assert synth.classify_line(line) == pattern

    def test_benign_progress_line_no_match(self):
        # Deny-list: clean Yosys progress lines must not classify.
        for benign in (
            "=== design hierarchy ===",
            "Executing AST frontend.",
            "Number of errors: 0",
            "Warnings: 0 errors, 0 warnings",
            "Yosys synthesis successfully finished.",
        ):
            assert synth.classify_line(benign) is None

    def test_empty_line_no_match(self):
        assert synth.classify_line("") is None
        assert synth.classify_line("   ") is None


class TestSynthClassifyLog:
    def test_each_pattern_produces_fix_and_confidence(self):
        for pattern, line in SYNTH_CASES.items():
            res = synth.diagnose(line)
            assert res["verdict"] == "DIAGNOSED"
            f = res["findings"][0]
            assert f["matched_pattern"] == pattern
            assert f["canonical_fix"]  # non-empty
            assert 0.0 <= f["confidence"] <= 1.0
            assert set(f) >= {"matched_pattern", "canonical_fix", "confidence"}

    def test_clean_log_no_false_match(self):
        clean = (
            "=== begin synthesis ===\n"
            "Executing Verilog-2005 frontend.\n"
            "Successfully finished Verilog frontend.\n"
            "Number of cells: 1234\n"
            "Warnings: 0 errors, 0 warnings\n"
            "Yosys synthesis successfully finished.\n"
        )
        res = synth.diagnose(clean)
        assert res["verdict"] == "CLEAN"
        assert res["findings"] == []

    def test_short_or_empty_log_is_clean_not_unknown(self):
        # Length-floor: a tiny / empty log degrades to CLEAN, never UNKNOWN spam.
        for text in ("", "   ", "ok"):
            res = synth.diagnose(text)
            assert res["verdict"] == "CLEAN"
            assert res["findings"] == []

    def test_unrecognised_error_is_unknown_only_when_nothing_matched(self):
        res = synth.diagnose("ERROR: some entirely novel tool failure xyz")
        assert res["verdict"] == "MANUAL_REVIEW"
        assert res["findings"][0]["matched_pattern"] == "UNKNOWN"
        assert res["findings"][0]["auto_fixable"] is False

    def test_unknown_suppressed_when_a_real_pattern_matched(self):
        # A novel warning alongside a known pattern must not add UNKNOWN noise.
        text = ("Warning: inferring a latch for signal q.\n"
                "Warning: some novel unclassified warning here.\n")
        res = synth.diagnose(text)
        pats = {f["matched_pattern"] for f in res["findings"]}
        assert "LATCH_INFERENCE" in pats
        assert "UNKNOWN" not in pats

    def test_dedup_repeated_signature(self):
        text = "\n".join(["Warning: width mismatch in assignment, truncating "
                          "from 16 bits to 8 bits."] * 5)
        res = synth.diagnose(text)
        assert res["count"] == 1
        assert res["findings"][0]["matched_pattern"] == "WIDTH_MISMATCH"


class TestSynthCli:
    def _run(self, tmp_path, text, *extra):
        log = tmp_path / "synth.log"
        log.write_text(text)
        return subprocess.run(
            [sys.executable, str(SYNTH_SCRIPT), str(log), *extra],
            capture_output=True, text=True)

    def test_cli_json_pattern(self, tmp_path):
        r = self._run(tmp_path, SYNTH_CASES["MULTI_DRIVER"], "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["findings"][0]["matched_pattern"] == "MULTI_DRIVER"

    def test_cli_fix_includes_recipe(self, tmp_path):
        r = self._run(tmp_path, SYNTH_CASES["UNPACKED_ARRAY"], "--fix")
        assert r.returncode == 0
        assert "FIX:" in r.stdout and "packed" in r.stdout.lower()

    def test_cli_clean_log_exit0_no_pattern(self, tmp_path):
        r = self._run(tmp_path, "Yosys synthesis successfully finished.\n"
                                "Warnings: 0 errors, 0 warnings\n")
        assert r.returncode == 0
        assert "CLEAN" in r.stdout

    def test_cli_missing_log_graceful(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(SYNTH_SCRIPT),
             str(tmp_path / "nope.log"), "--json"],
            capture_output=True, text=True)
        assert r.returncode == 2          # MISSING, not a crash
        assert json.loads(r.stdout)["verdict"] == "MISSING"


# --------------------------------------------------------------------------- #
# pnr_doctor — canonical OpenROAD P&R-log snippets per documented pattern.
# --------------------------------------------------------------------------- #
PNR_CASES = {
    "DRT_ZERO_NET": "[ERROR DRT-0305] Net zero_ of signal type GROUND is not "
                    "routable.",
    "SITE_NOT_FOUND": "[ERROR IFP-0018] Unable to find site: FreeSite",
    "MISSING_TRACKS": "[ERROR PPL-0021] Horizontal routing tracks not found.",
    "NO_CLOCK": "Warning: design has no clocks defined for CTS.",
    "GPL_DIVERGE": "[ERROR GPL-0307] Global placement diverged, HPWL is nan.",
    "CONGESTION": "Warning: routing congestion detected, 42 gcells with overflow.",
    "DRC_SPACING": "ERROR: 17 spacing violations found during detailed route.",
    "TIMING_FAIL": "Setup timing failed: worst slack = -0.350 ns (negative slack).",
}


class TestPnrClassifyLine:
    @pytest.mark.parametrize("pattern,line", list(PNR_CASES.items()))
    def test_each_canonical_pattern_matches(self, pattern, line):
        assert pnr.classify_line(line) == pattern

    def test_power_net_not_zero_net(self):
        # DRT_POWER_NET must NOT swallow the zero_ case (that's DRT_ZERO_NET).
        line = "Net VDD of signal type POWER given to detailed router."
        assert pnr.classify_line(line) == "DRT_POWER_NET"
        assert pnr.classify_line(PNR_CASES["DRT_ZERO_NET"]) == "DRT_ZERO_NET"

    def test_benign_progress_line_no_match(self):
        for benign in (
            "=== Detailed Routing ===",
            "Starting global placement.",
            "0 DRC violations found.",
            "no DRC violations.",
            "[INFO DRT-0019] Done with detailed routing.",
            "End of OpenROAD flow.",
        ):
            assert pnr.classify_line(benign) is None


class TestPnrClassifyLog:
    def test_each_pattern_produces_fix_and_confidence(self):
        for pattern, line in PNR_CASES.items():
            res = pnr.diagnose(line)
            assert res["verdict"] == "DIAGNOSED", pattern
            f = res["findings"][0]
            assert f["matched_pattern"] == pattern
            assert f["canonical_fix"]
            assert 0.0 <= f["confidence"] <= 1.0
            assert set(f) >= {"matched_pattern", "canonical_fix", "confidence"}

    def test_non_auto_fixable_patterns_have_zero_confidence(self):
        # DRT_POWER_NET + TIMING_FAIL are documented as not blindly auto-fixable.
        for line, pat in (
            ("Net VDD of signal type POWER given to detailed router.",
             "DRT_POWER_NET"),
            (PNR_CASES["TIMING_FAIL"], "TIMING_FAIL"),
        ):
            f = pnr.diagnose(line)["findings"][0]
            assert f["matched_pattern"] == pat
            assert f["confidence"] == 0.0
            assert f["auto_fixable"] is False

    def test_zero_net_recipe_is_full_confidence(self):
        f = pnr.diagnose(PNR_CASES["DRT_ZERO_NET"])["findings"][0]
        assert f["confidence"] == 1.0
        assert "hilomap" in f["canonical_fix"]

    def test_clean_log_no_false_match(self):
        clean = (
            "=== Global Placement ===\n"
            "Starting detailed routing.\n"
            "0 DRC violations found.\n"
            "no DRC violations.\n"
            "Detailed routing completed successfully.\n"
            "End of OpenROAD flow.\n"
        )
        res = pnr.diagnose(clean)
        assert res["verdict"] == "CLEAN"
        assert res["findings"] == []

    def test_short_log_is_clean(self):
        for text in ("", "   ", "ok"):
            assert pnr.diagnose(text)["verdict"] == "CLEAN"

    def test_drc_report_scanned_with_source_tag(self):
        log = "Detailed routing completed.\n"
        drc = "ERROR: 5 spacing violations near metal2.\n"
        res = pnr.diagnose(log, drc)
        assert any(f["matched_pattern"] == "DRC_SPACING"
                   and f["source"] == "drc_report" for f in res["findings"])

    def test_unrecognised_error_is_unknown_only_when_nothing_matched(self):
        res = pnr.diagnose("[ERROR XYZ-9999] some entirely novel router crash")
        assert res["verdict"] == "MANUAL_REVIEW"
        assert res["findings"][0]["matched_pattern"] == "UNKNOWN"


class TestPnrCli:
    def _run(self, tmp_path, text, *extra):
        log = tmp_path / "pnr.log"
        log.write_text(text)
        return subprocess.run(
            [sys.executable, str(PNR_SCRIPT), str(log), *extra],
            capture_output=True, text=True)

    def test_cli_json_pattern(self, tmp_path):
        r = self._run(tmp_path, PNR_CASES["DRT_ZERO_NET"], "--json")
        assert r.returncode == 0
        assert json.loads(r.stdout)["findings"][0]["matched_pattern"] \
            == "DRT_ZERO_NET"

    def test_cli_drc_flag(self, tmp_path):
        log = tmp_path / "pnr.log"
        log.write_text("Detailed routing completed.\n")
        drc = tmp_path / "drc.rpt"
        drc.write_text("ERROR: 3 spacing violations found.\n")
        r = subprocess.run(
            [sys.executable, str(PNR_SCRIPT), str(log),
             "--drc", str(drc), "--json"],
            capture_output=True, text=True)
        assert r.returncode == 0
        pats = {f["matched_pattern"] for f in json.loads(r.stdout)["findings"]}
        assert "DRC_SPACING" in pats

    def test_cli_clean_exit0(self, tmp_path):
        r = self._run(tmp_path, "Detailed routing completed successfully.\n"
                                "0 DRC violations found.\n")
        assert r.returncode == 0
        assert "CLEAN" in r.stdout

    def test_cli_missing_log_graceful(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(PNR_SCRIPT),
             str(tmp_path / "nope.log"), "--json"],
            capture_output=True, text=True)
        assert r.returncode == 2
        assert json.loads(r.stdout)["verdict"] == "MISSING"
