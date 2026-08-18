"""Unit tests for `magic_extract_spice_emit.py`.

Pins the deterministic shape of the Magic parasitic-RC extraction TCL
(emit mode) AND the honest-failure semantics of the validator (validate
mode). Chip-agnostic — no cell-specific token is hard-coded into the program.
"""
import importlib
import tempfile
from pathlib import Path

import pytest

mod = importlib.import_module("magic_extract_spice_emit")


# ---------------------------------------------------------------------------
# EMIT
# ---------------------------------------------------------------------------
class TestEmit:
    def test_core_sequence_present(self):
        tcl = mod.build_extraction_tcl("ldo_1v8", "/o/ldo_extracted.spice")
        assert "load ldo_1v8" in tcl
        assert "extract all" in tcl
        assert "ext2spice lvs" in tcl
        assert "ext2spice -o /o/ldo_extracted.spice" in tcl

    def test_chip_agnostic_block_name(self):
        # The block name is a parameter — no hard-coded cell in the program.
        tcl = mod.build_extraction_tcl("my_pll_core", "/x.spice")
        assert "load my_pll_core" in tcl
        assert "MAGIC_EXTRACT_RESIM_DONE my_pll_core" in tcl

    def test_scale_off_default_on(self):
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        assert "ext2spice scale off" in tcl

    def test_scale_off_can_be_disabled(self):
        opts = mod.MagicResimExtractOptions(ext2spice_scale_off=False)
        tcl = mod.build_extraction_tcl("blk", "/o.spice", opts)
        assert "ext2spice scale off" not in tcl

    def test_thresholds_emitted(self):
        opts = mod.MagicResimExtractOptions(cthresh=0.1, rthresh=10.0)
        tcl = mod.build_extraction_tcl("blk", "/o.spice", opts)
        assert "ext2spice cthresh 0.1" in tcl
        assert "ext2spice rthresh 10.0" in tcl

    # ----- honest failure on garbage emit input -----
    def test_empty_block_raises(self):
        with pytest.raises(ValueError):
            mod.build_extraction_tcl("", "/o.spice")

    def test_empty_out_spice_raises(self):
        with pytest.raises(ValueError):
            mod.build_extraction_tcl("blk", "   ")


# ---------------------------------------------------------------------------
# VALIDATE — PASS
# ---------------------------------------------------------------------------
class TestValidatePass:
    def test_emitted_tcl_validates(self):
        # The recipe we emit must itself pass validation (round-trip).
        tcl = mod.build_extraction_tcl("ldo", "/o.spice")
        r = mod.validate_extraction_tcl(tcl, "emitted.tcl")
        assert r.passed is True
        assert r.summary["missing"] == []

    def test_hand_written_conformant(self):
        tcl = (
            "load ldo_core\n"
            "extract all\n"
            "ext2spice lvs\n"
            "ext2spice -o ldo_core.spice\n"
        )
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is True


# ---------------------------------------------------------------------------
# VALIDATE — FAIL (real defects)
# ---------------------------------------------------------------------------
class TestValidateFail:
    def test_missing_ext2spice_lvs_fails(self):
        # The #1 silent defect: no `ext2spice lvs` -> netlist has no .subckt
        # port wrapper, the resim binds the ideal block, false 0% degradation.
        tcl = (
            "load ldo_core\n"
            "extract all\n"
            "ext2spice -o ldo_core.spice\n"
        )
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is False
        assert "ext2spice_lvs" in r.summary["missing"]

    def test_missing_extract_all_fails(self):
        # No `extract all` -> R/C-free netlist -> vacuous 0% degradation PASS.
        tcl = (
            "load ldo_core\n"
            "ext2spice lvs\n"
            "ext2spice -o ldo_core.spice\n"
        )
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is False
        assert "extract_all" in r.summary["missing"]

    def test_comment_does_not_count(self):
        # A required command that appears ONLY in a comment must not satisfy.
        tcl = (
            "load ldo_core\n"
            "# extract all  <- TODO, not actually run\n"
            "ext2spice lvs\n"
            "ext2spice -o ldo.spice\n"
        )
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is False
        assert "extract_all" in r.summary["missing"]


# ---------------------------------------------------------------------------
# VALIDATE — honest failure on absent / garbage input
# ---------------------------------------------------------------------------
class TestValidateGarbage:
    def test_empty_text_fails(self):
        r = mod.validate_extraction_tcl("")
        assert r.passed is False
        assert r.findings[0].rule == "EMPTY_TCL"

    def test_whitespace_only_fails(self):
        r = mod.validate_extraction_tcl("   \n\t\n")
        assert r.passed is False
        assert r.findings[0].rule == "EMPTY_TCL"

    def test_unrelated_text_fails_not_an_extraction(self):
        r = mod.validate_extraction_tcl("the quick brown fox jumps over\n")
        assert r.passed is False
        assert any(f.rule == "NOT_AN_EXTRACTION_TCL" for f in r.findings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCli:
    def test_cli_emit_to_stdout(self, capsys):
        rc = mod.main(["--block", "blk", "--out-spice", "/o.spice"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "load blk" in captured.out
        assert "ext2spice lvs" in captured.out

    def test_cli_emit_requires_block(self):
        rc = mod.main(["--out-spice", "/o.spice"])
        assert rc == 2

    def test_cli_validate_pass(self, tmp_path):
        tcl = tmp_path / "good.tcl"
        tcl.write_text(mod.build_extraction_tcl("blk", "/o.spice"))
        rc = mod.main(["--validate", str(tcl)])
        assert rc == 0

    def test_cli_validate_fail(self, tmp_path):
        tcl = tmp_path / "bad.tcl"
        tcl.write_text("load blk\next2spice -o o.spice\n")  # no extract/lvs
        rc = mod.main(["--validate", str(tcl)])
        assert rc == 1

    def test_cli_validate_missing_file(self):
        rc = mod.main(["--validate", "/no/such/file.tcl"])
        assert rc == 2

    def test_cli_validate_json_report(self, tmp_path):
        tcl = tmp_path / "good.tcl"
        tcl.write_text(mod.build_extraction_tcl("blk", "/o.spice"))
        report = tmp_path / "rep.json"
        rc = mod.main(["--validate", str(tcl), "--json", str(report)])
        assert rc == 0
        assert report.is_file()
        import json
        data = json.loads(report.read_text())
        assert data["passed"] is True
        assert data["mode"] == "validate"
