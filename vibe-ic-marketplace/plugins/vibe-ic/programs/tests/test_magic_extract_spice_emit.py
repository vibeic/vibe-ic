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
        # NOTE (vibe-ic#1953): this test used to assert `ext2spice rthresh
        # 10.0`. Magic REFUSES that — `exttospice: integer value or
        # "infinite" expected.` — and keeps the previous threshold, so the
        # old assertion pinned a line the tool throws away. rthresh is
        # rendered as an integer now; cthresh does take a float.
        opts = mod.MagicResimExtractOptions(cthresh=0.1, rthresh=10)
        tcl = mod.build_extraction_tcl("blk", "/o.spice", opts)
        assert "ext2spice cthresh 0.1" in tcl
        assert "ext2spice rthresh 10" in tcl
        assert "ext2spice rthresh 10.0" not in tcl

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


# ===========================================================================
# vibe-ic#1953 — the recipe defeated its own audit.
#
# Every literal below is a FIRST-HAND MEASUREMENT, not a quotation: Magic 8.3
# rev 664 (`hpretl/iic-osic-tools`), PDK sky130A, on two throwaway layouts
# built for the purpose (a 200um metal1 wire; an nfet + a 200um metal1 route).
# Reproduction notes and the raw artefacts: `_find/` at the branch root.
#
#   M1  `ext2spice lvs` RESETS both thresholds:
#         default        cthresh=2.0        rthresh=infinite
#         after set 0    cthresh=0.0        rthresh=infinite
#         after `lvs`    cthresh=infinite   rthresh=infinite   <-- reset
#         re-asserted    cthresh=0.0        rthresh=0
#       cthresh=infinite drops EVERY capacitance.
#
#   M2  `ext2spice rthresh 0.0` is a parse error —
#         `exttospice: integer value or "infinite" expected.`
#       — so the assignment is refused and rthresh keeps its old value.
#       The emitter formats a Python float, so even re-asserting after `lvs`
#       would leave rthresh=infinite. (`cthresh` does accept a float.)
#
#   M3  `extresist all` before `extract all` has no `.ext` to read, so no
#       `.res.ext` is written at all.
#
#   M4  Same layout, the recipe the emitter produces verbatim vs the fixed
#       order:   main -> 0 R, 0 C, no .res.ext   |   fixed -> 0 R, 9 C, 8 lines
#
#   M5  R is not recoverable on magic 8.3 / sky130A even fully armed
#       (`extract do resistance` + `extresist extout on` +
#        `extresist threshold 0` + `ext2spice extresist on` still yields 0 R).
#       So the audit must DISCLOSE the achieved depth, and must refuse only
#       the genuinely parasitic-free netlist.
# ===========================================================================

# The recipe main's emitter produced, byte-for-byte, for `--block rcdev`.
BROKEN_RECIPE_AS_SHIPPED = """\
load rcdev
select top cell
extract style ngspice
extresist all
extract all
ext2spice scale off
ext2spice cthresh 0.0
ext2spice rthresh 0.0
ext2spice lvs
ext2spice -o /w/Adev.spice
"""

# What magic actually wrote when fed BROKEN_RECIPE_AS_SHIPPED: no R, no C.
# This is the netlist the emitter's own trailing comment forbids.
MAGIC_OUTPUT_FROM_BROKEN_RECIPE = """\
* NGSPICE file created from rcdev.ext - technology: sky130A

.subckt rcdev IN OUT
X0 a_1400_0# a_600_n1000# a_0_0# VSUBS sky130_fd_pr__nfet_01v8 ad=30 pd=26 as=30 ps=26 w=10 l=4
.ends
"""

# What magic wrote from the SAME layout with the order corrected: 9 real caps.
MAGIC_OUTPUT_FROM_FIXED_RECIPE = """\
* NGSPICE file created from rcdev.ext - technology: sky130A

.subckt rcdev IN OUT
X0 a_1400_0.t0 a_600_n1000# a_0_0.t0 w_0_n1000# sky130_fd_pr__nfet_01v8 ad=30 pd=26 as=30 ps=26 w=10 l=4
C0 OUT IN 0.01408f
C1 OUT a_600_n1000# 0.01933f
C2 IN a_600_n1000# 0.23177f
C3 OUT a_78000_0# 1.60958f
C4 OUT w_0_n1000# 53.26654f
C5 IN w_0_n1000# 1.41691f
C6 a_600_n1000# w_0_n1000# 5.79276f
C7 a_0_0.t0 w_0_n1000# 0.75809f
C8 a_1400_0.t0 w_0_n1000# 0.20725f
.ends
"""

# `.res.ext` from the fixed recipe (8 lines of real records) vs the broken
# recipe, which produced no file at all.
RES_EXT_FROM_FIXED_RECIPE = """\
scale 1000 1 500000
killnode "a_0_0#"
rnode "a_0_0.t0" 0 758.085 600 1000 0
killnode "a_1400_0#"
rnode "a_1400_0.t0" 0 207.251 1400 1000 0
rnode "IN" 0 1026.23 0 400 0
rnode "OUT" 0 1827.94 79800 400 0
device msubckt sky130_fd_pr__nfet_01v8 600 0 601 1  "w_0_n1000#" "a_600_n1000#" 1600 0 "a_0_0.t0" 2000 1200000,5200 "a_1400_0.t0" 2000 1200000,5200
"""

# `extresist all` ran but had nothing to write past the header — the shape
# the issue measured on the real block (1 line, just `scale`).
RES_EXT_VACUOUS = "scale 1000 1 500000\n"


def _idx(tcl: str, needle: str) -> int:
    """0-based line index of the first UNCOMMENTED line matching `needle`."""
    for i, ln in enumerate(tcl.splitlines()):
        if needle in ln.split("#", 1)[0]:
            return i
    raise AssertionError(f"{needle!r} not found in emitted TCL:\n{tcl}")


class TestEmitOrderIsLoadBearing:
    """M1/M3: the order is not cosmetic — magic's state machine depends on it."""

    def test_extract_all_precedes_extresist_all(self):
        # M3: extresist reads the .ext that `extract all` writes. Before it,
        # there is nothing to read and no .res.ext is produced.
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        assert _idx(tcl, "extract all") < _idx(tcl, "extresist all")

    def test_ext2spice_lvs_precedes_the_threshold_overrides(self):
        # M1: `ext2spice lvs` sets cthresh/rthresh back to `infinite`, so a
        # threshold written before it is discarded and every parasitic drops.
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        lvs = _idx(tcl, "ext2spice lvs")
        assert lvs < _idx(tcl, "ext2spice cthresh")
        assert lvs < _idx(tcl, "ext2spice rthresh")

    def test_thresholds_precede_the_write(self):
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        write = _idx(tcl, "ext2spice -o ")
        assert _idx(tcl, "ext2spice cthresh") < write
        assert _idx(tcl, "ext2spice rthresh") < write

    def test_rthresh_is_emitted_as_an_integer(self):
        # M2: magic refuses `ext2spice rthresh 0.0` outright.
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        tok = [ln.split()[-1] for ln in tcl.splitlines()
               if ln.split("#", 1)[0].strip().startswith("ext2spice rthresh")][0]
        assert tok == "infinite" or tok.lstrip("-").isdigit(), (
            f"magic wants an integer or 'infinite'; emitter wrote {tok!r}")

    def test_non_integral_rthresh_is_refused_not_silently_mangled(self):
        with pytest.raises(ValueError):
            mod.build_extraction_tcl(
                "blk", "/o.spice",
                mod.MagicResimExtractOptions(rthresh=2.5))

    def test_integral_float_rthresh_is_accepted_and_normalised(self):
        tcl = mod.build_extraction_tcl(
            "blk", "/o.spice", mod.MagicResimExtractOptions(rthresh=10.0))
        assert "ext2spice rthresh 10" in tcl
        assert "ext2spice rthresh 10.0" not in tcl

    def test_resistance_extraction_is_armed_when_extresist_is_emitted(self):
        # `extresist all` on its own extracts nothing: the extractor has to be
        # told to do resistance, told to write the file, and ext2spice told to
        # splice it in.
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        assert "extract do resistance" in tcl
        assert "extresist extout on" in tcl
        assert "ext2spice extresist on" in tcl
        assert _idx(tcl, "extract do resistance") < _idx(tcl, "extract all")

    def test_extresist_can_be_turned_off_wholesale(self):
        opts = mod.MagicResimExtractOptions(extresist=False)
        tcl = mod.build_extraction_tcl("blk", "/o.spice", opts)
        live = [ln.split("#", 1)[0].strip() for ln in tcl.splitlines()]
        assert not [ln for ln in live if "extresist" in ln], live
        assert "extract all" in tcl          # capacitance extraction remains

    def test_extract_style_is_unambiguous(self):
        # M5-adjacent: `extract style ngspice` is ambiguous on magic 8.3 —
        # "The extraction styles are: ngspice(), ngspice(orig), ngspice(si)…"
        # — and silently leaves the style unchanged.
        tcl = mod.build_extraction_tcl("blk", "/o.spice")
        style = [ln.strip() for ln in tcl.splitlines()
                 if ln.split("#", 1)[0].strip().startswith("extract style")]
        assert style == ["extract style ngspice()"], style


class TestValidatorRefusesTheBrokenRecipe:
    """The audit that should have caught this. On main it PASSes the recipe."""

    def test_the_recipe_as_shipped_is_refused(self):
        r = mod.validate_extraction_tcl(BROKEN_RECIPE_AS_SHIPPED, "shipped.tcl")
        assert r.passed is False, (
            "the validator PASSED the exact recipe that produced a "
            "parasitic-free netlist — a detector that never says no")

    def test_it_names_the_threshold_reset(self):
        r = mod.validate_extraction_tcl(BROKEN_RECIPE_AS_SHIPPED)
        rules = {f.rule for f in r.findings}
        assert "ORDER_THRESHOLD_BEFORE_LVS" in rules, rules

    def test_it_names_the_extresist_inversion(self):
        r = mod.validate_extraction_tcl(BROKEN_RECIPE_AS_SHIPPED)
        rules = {f.rule for f in r.findings}
        assert "ORDER_EXTRESIST_BEFORE_EXTRACT" in rules, rules

    def test_it_names_the_float_rthresh(self):
        r = mod.validate_extraction_tcl(BROKEN_RECIPE_AS_SHIPPED)
        rules = {f.rule for f in r.findings}
        assert "RTHRESH_NOT_INTEGER" in rules, rules

    def test_lvs_after_the_write_is_refused(self):
        tcl = ("load blk\nextract all\next2spice -o o.spice\next2spice lvs\n")
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is False
        assert "ORDER_LVS_AFTER_WRITE" in {f.rule for f in r.findings}

    def test_extract_after_the_write_is_refused(self):
        tcl = ("load blk\next2spice lvs\next2spice -o o.spice\nextract all\n")
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is False
        assert "ORDER_EXTRACT_AFTER_WRITE" in {f.rule for f in r.findings}

    # ----- negative control: the ORDER rules must not fire on a good recipe --
    def test_a_correctly_ordered_hand_written_recipe_still_passes(self):
        tcl = (
            "load ldo_core\n"
            "extract all\n"
            "extresist all\n"
            "ext2spice lvs\n"
            "ext2spice cthresh 0.0\n"
            "ext2spice rthresh 0\n"
            "ext2spice -o ldo_core.spice\n"
        )
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is True, [f.rule for f in r.findings]

    def test_a_recipe_with_no_threshold_overrides_at_all_still_passes(self):
        # Not setting a threshold is legal (magic's defaults apply); only
        # setting one and then having `lvs` throw it away is the defect.
        tcl = "load b\nextract all\next2spice lvs\next2spice -o b.spice\n"
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is True, [f.rule for f in r.findings]

    def test_ext2spice_extresist_on_is_not_mistaken_for_the_write(self):
        # `ext2spice <unknown-word>` IS magic's write form (it reads the word
        # as a cell name), so the subcommand set has to be known — otherwise
        # `ext2spice extresist on` reads as a write placed before `lvs`.
        tcl = (
            "load b\nextract all\next2spice lvs\n"
            "ext2spice extresist on\next2spice -o b.spice\n"
        )
        r = mod.validate_extraction_tcl(tcl)
        assert r.passed is True, [f.rule for f in r.findings]

    def test_the_emitted_recipe_passes_the_order_aware_validator(self):
        r = mod.validate_extraction_tcl(
            mod.build_extraction_tcl("ldo", "/o.spice"), "emitted.tcl")
        assert r.passed is True, [f.rule for f in r.findings]


class TestNetlistAudit:
    """The trailing audit COMMENT, made executable against what magic wrote."""

    def test_the_broken_recipes_real_output_is_refused(self):
        a = mod.audit_extracted_netlist(MAGIC_OUTPUT_FROM_BROKEN_RECIPE)
        assert a.passed is False
        assert "NO_PARASITICS" in {f.rule for f in a.findings}
        assert a.depth == "NONE"

    def test_the_fixed_recipes_real_output_is_accepted(self):
        a = mod.audit_extracted_netlist(MAGIC_OUTPUT_FROM_FIXED_RECIPE)
        assert a.passed is True, [f.rule for f in a.findings]
        assert a.summary["capacitors"] == 9
        assert a.summary["resistors"] == 0

    def test_the_achieved_depth_is_disclosed_never_silent(self):
        # M5: C-only is the real depth on magic 8.3 / sky130A. It passes, but
        # it is never allowed to read as full RC.
        a = mod.audit_extracted_netlist(MAGIC_OUTPUT_FROM_FIXED_RECIPE)
        assert a.depth == "C_ONLY"
        assert "PARASITIC_DEPTH_C_ONLY" in {f.rule for f in a.findings}

    def test_full_rc_is_reported_as_rc(self):
        txt = (".subckt b A B\nR0 A n1 12.5\nC0 n1 B 3f\n.ends\n")
        a = mod.audit_extracted_netlist(txt)
        assert a.passed is True
        assert a.depth == "RC"
        assert a.summary["resistors"] == 1

    def test_c_only_is_refused_when_resistance_is_required(self):
        a = mod.audit_extracted_netlist(
            MAGIC_OUTPUT_FROM_FIXED_RECIPE, require_resistance=True)
        assert a.passed is False
        assert "RESISTANCE_REQUIRED_BUT_ABSENT" in {f.rule for f in a.findings}

    def test_a_missing_subckt_wrapper_is_refused(self):
        # No `.subckt` => `ext2spice lvs` never took => the resim would bind
        # the ideal block and report a false 0% degradation.
        txt = "* netlist\nC0 a b 1f\nR0 b c 2\n"
        a = mod.audit_extracted_netlist(txt)
        assert a.passed is False
        assert "NO_SUBCKT" in {f.rule for f in a.findings}

    def test_an_empty_netlist_is_refused(self):
        a = mod.audit_extracted_netlist("   \n\t\n")
        assert a.passed is False
        assert a.findings[0].rule == "EMPTY_NETLIST"

    # ----- .res.ext, the other half of the measured failure ------------------
    def test_a_vacuous_res_ext_is_reported(self):
        a = mod.audit_extracted_netlist(
            MAGIC_OUTPUT_FROM_FIXED_RECIPE, res_ext_text=RES_EXT_VACUOUS)
        assert "EXTRESIST_PRODUCED_NOTHING" in {f.rule for f in a.findings}
        assert a.summary["res_ext_records"] == 0

    def test_an_absent_res_ext_is_reported(self):
        # The broken recipe did not create the file at all.
        a = mod.audit_extracted_netlist(
            MAGIC_OUTPUT_FROM_BROKEN_RECIPE, res_ext_text=None,
            extresist_expected=True)
        assert "EXTRESIST_PRODUCED_NOTHING" in {f.rule for f in a.findings}

    def test_a_real_res_ext_is_counted(self):
        a = mod.audit_extracted_netlist(
            MAGIC_OUTPUT_FROM_FIXED_RECIPE,
            res_ext_text=RES_EXT_FROM_FIXED_RECIPE)
        assert a.summary["res_ext_records"] == 7
        assert "EXTRESIST_PRODUCED_NOTHING" not in {f.rule for f in a.findings}

    def test_a_vacuous_res_ext_is_fatal_when_resistance_is_required(self):
        a = mod.audit_extracted_netlist(
            MAGIC_OUTPUT_FROM_FIXED_RECIPE, res_ext_text=RES_EXT_VACUOUS,
            require_resistance=True)
        assert a.passed is False


class TestAuditCli:
    def test_cli_audit_refuses_the_broken_recipes_output(self, tmp_path):
        sp = tmp_path / "broken.spice"
        sp.write_text(MAGIC_OUTPUT_FROM_BROKEN_RECIPE)
        assert mod.main(["--audit-netlist", str(sp)]) == 1

    def test_cli_audit_accepts_the_fixed_recipes_output(self, tmp_path):
        sp = tmp_path / "fixed.spice"
        sp.write_text(MAGIC_OUTPUT_FROM_FIXED_RECIPE)
        assert mod.main(["--audit-netlist", str(sp)]) == 0

    def test_cli_audit_missing_file_is_usage_error(self):
        assert mod.main(["--audit-netlist", "/no/such/x.spice"]) == 2

    def test_cli_audit_json_report_carries_the_depth(self, tmp_path):
        sp = tmp_path / "fixed.spice"
        sp.write_text(MAGIC_OUTPUT_FROM_FIXED_RECIPE)
        rep = tmp_path / "audit.json"
        assert mod.main(["--audit-netlist", str(sp), "--json", str(rep)]) == 0
        import json as _json
        data = _json.loads(rep.read_text())
        assert data["mode"] == "audit"
        assert data["depth"] == "C_ONLY"

    def test_cli_audit_reads_the_res_ext(self, tmp_path):
        sp = tmp_path / "fixed.spice"
        sp.write_text(MAGIC_OUTPUT_FROM_FIXED_RECIPE)
        rx = tmp_path / "fixed.res.ext"
        rx.write_text(RES_EXT_VACUOUS)
        assert mod.main(["--audit-netlist", str(sp), "--res-ext", str(rx),
                         "--require-resistance"]) == 1


class TestRthreshRendering:
    """M2: magic wants an integer; a float is refused outright."""
    @pytest.mark.parametrize("bad", [None, "abc", float("nan"), float("inf"), -1])
    def test_rthresh_garbage_is_a_clean_valueerror(self, bad):
        # Never a TypeError, never a silently-mangled threshold.
        with pytest.raises(ValueError):
            mod.build_extraction_tcl(
                "b", "/o.spice", mod.MagicResimExtractOptions(rthresh=bad))

    @pytest.mark.parametrize("good,want", [
        (0, "0"), (0.0, "0"), (10, "10"), ("0", "0"),
        ("infinite", "infinite"), ("INFINITE", "infinite"),
    ])
    def test_rthresh_accepted_forms(self, good, want):
        tcl = mod.build_extraction_tcl(
            "b", "/o.spice", mod.MagicResimExtractOptions(rthresh=good))
        assert f"ext2spice rthresh {want}" in tcl
