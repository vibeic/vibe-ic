"""The hold corner is decided by the Liberty the script READS, not by the
corner token its FILENAME spells or its banner asserts.

Bidirectional negative control for the repair in
`hold_corner_coverage_check.py`:

  FORWARD (F*)  — these FAIL against the byte-identical pre-fix file and pass
                  after. Two of them are TIGHTENINGS: F5/F6 turn a pre-fix
                  PASS into a FAIL, which is what proves the repair catches a
                  real defect rather than merely relabelling one.
  REVERSE (R*)  — these pass BEFORE and must STILL pass AFTER, and every one of
                  them is written against the PRE-FIX call signature so that
                  claim is literally checkable. They are the control against
                  "narrow the reader until the count is zero": every
                  pre-existing route to a verdict — the filename token, the
                  MCMM operating-condition line, the hard-macro extra liberty,
                  the honest FAIL tiers, the stance mode and the worst-of
                  project arbitration — is pinned here.

WHY NOT pytest's `tmp_path`: its directory name embeds the TEST NAME, and a
test named `..._ff_...` puts a live `_ff_` corner token into every Liberty path
built under it — `_corners_in()` returns `['FF']` for a bare pytest tmp_path.
That silently decides the very thing under test. Every temp root here is built
under a name this file controls and is ASSERTED corner-token-free before use.

Chip-AGNOSTIC: every Liberty is synthesised from generic Liberty syntax. No
PDK, vendor, SKU, process node or part number appears.
"""
import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

mod = importlib.import_module("hold_corner_coverage_check")

#: A root whose every path component is corner-token-free by construction
#: (pid is digits only). Asserted, not assumed, in the `libdir` fixture.
_ROOT = Path(tempfile.gettempdir()) / f"vibeic_holdlib_{os.getpid()}"
_SEQ = [0]


@pytest.fixture
def libdir():
    _SEQ[0] += 1
    d = _ROOT / f"d{_SEQ[0]}"
    d.mkdir(parents=True)
    assert mod._corners_in(str(d / "probe.lib")) == [], (
        f"the temp root {d} itself carries a corner token — every Liberty "
        f"path built under it would be pre-decided and these tests would be "
        f"measuring the directory name instead of the Liberty")
    yield d
    shutil.rmtree(_ROOT, ignore_errors=True)


# ───────────────────────────── fixtures ──────────────────────────────────
def _lib(d: Path, name: str, oc: str, default: bool = True) -> str:
    """A minimal Liberty declaring `operating_conditions (<oc>)`."""
    body = [
        f"library ({name}) {{",
        "  delay_model : table_lookup;",
        "  time_unit : \"1ns\";",
        "  nom_process : 1.0;",
        f"  operating_conditions ({oc}) {{",
        "    process : 1.0;",
        "    temperature : 25.0;",
        "    voltage : 1.8;",
        "  }",
    ]
    if default:
        body.append(f"  default_operating_conditions : {oc};")
    body.append("  cell (SOMECELL) { area : 1.0; }")
    body.append("}")
    p = d / f"{name}.lib"
    p.write_text("\n".join(body) + "\n")
    return str(p)


def _hold_tcl(lib_path: str, banner_corner: str = None) -> str:
    lines = [f"read_liberty {lib_path}", "read_verilog design.v"]
    if banner_corner:
        lines.append(
            f'puts $_f "=== HOLD corner: process={banner_corner} '
            f'liberty={lib_path}, SPEF=design.spef ==="')
    lines += ["report_worst_slack -min",
              "report_checks -path_delay min -group_path_count 3"]
    return "\n".join(lines) + "\n"


# ═════════════════════════════ FORWARD ═══════════════════════════════════
class TestForwardTokenlessLibertyIsClassifiable:
    """Pre-fix these answer NO_FEED_CORNER — "no Liberty / operating condition
    corner could be identified feeding it" — while holding the Liberty's path
    on the very line being read."""

    def test_F1_banner_and_tokenless_fast_liberty_passes(self, libdir):
        lib = _lib(libdir, "corelib_bestcase", "fast")
        verdict, rc, rep = mod.evaluate(_hold_tcl(lib, "FF"), base=libdir)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["reason"] == "HOLD_AT_FF"
        assert rep["judged_corners"] == ["FF"]
        # and it is CONTENT-backed, not banner-backed
        assert rep["liberty_declared_corners"] == [
            {"liberty": lib, "declared_corners": ["FF"]}]

    def test_F2_tokenless_fast_liberty_with_no_banner_at_all_passes(
            self, libdir):
        lib = _lib(libdir, "corelib_bestcase", "fast")
        verdict, rc, rep = mod.evaluate(_hold_tcl(lib), base=libdir)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["reason"] == "HOLD_AT_FF"

    def test_F3_tokenless_slow_liberty_fails_for_the_RIGHT_reason(
            self, libdir):
        """Pre-fix this is FAIL/NO_FEED_CORNER (blind). It must become
        FAIL/HOLD_NOT_AT_FF — the same rc, a truthful reason."""
        lib = _lib(libdir, "corelib_worstcase", "slow")
        verdict, rc, rep = mod.evaluate(_hold_tcl(lib), base=libdir)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_F4_banner_keyvalue_spelling_alone_is_readable(self):
        """No Liberty to open at all — this is purely the `=` that was missing
        from the delimiter class, so the emitter's own documented rule-2
        banner becomes visible to the rule that documents itself as reading
        it."""
        tcl = ('puts $_f "=== HOLD corner: process=FF liberty=corelib.lib ==="\n'
               "report_checks -path_delay min\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["corner_basis"] == "declared_hold_view"
        assert rep["judged_corners"] == ["FF"]

    def test_F5_no_default_oc_pointer_still_read_from_the_group(self, libdir):
        lib = _lib(libdir, "corelib_bestcase", "fast", default=False)
        verdict, rc, _ = mod.evaluate(_hold_tcl(lib), base=libdir)
        assert (verdict, rc) == ("PASS", 0)


class TestForwardContentBeatsTheLabel:
    """The TIGHTENING half. Pre-fix both of these are rc=0 PASS on a filename
    or a banner that the Liberty itself contradicts."""

    def test_F6_filename_says_ff_but_liberty_declares_slow_now_FAILS(
            self, libdir):
        lib = _lib(libdir, "corelib_ff_1p10v_m40c", "slow")
        verdict, rc, rep = mod.evaluate(_hold_tcl(lib), base=libdir)
        assert (verdict, rc) == ("FAIL", 1), (
            "a Liberty named _ff_ that declares operating_conditions (slow) "
            "must be judged on what it declares")
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_F7_banner_says_FF_but_liberty_declares_slow_now_FAILS(
            self, libdir):
        """F6 with a BANNER — and the banner is what changes the reason.

        F6 above carries no competing claim, so the Liberty's content decides
        and the corner IS measured, at a non-fast one: `HOLD_NOT_AT_FF`.

        Here the same Liberty is named on a line that also asserts
        `process=FF`. Two corner claims on one line that disagree is the
        module's third state, not its second — see its own docstring:

            measured-clean   -> PASS
            measured-defect  -> FAIL   HOLD_NOT_AT_FF
            NOT measured     -> FAIL   HOLD_CORNER_CONTRADICTION

        This assertion said `HOLD_NOT_AT_FF` and had done since before
        `72a72850` ("the hold banner's label is the CLAIM and its Liberty is
        the EVIDENCE — arbitrate them, do not union them") introduced the
        arbitration. That commit made this case FAIL, the test was updated to
        expect the FAIL, and the REASON was left on the pre-arbitration value.

        `hold_corner_measured` is asserted alongside the reason string on
        purpose: it is the claim that actually separates the two states, and a
        future rename of the reason code must not be able to satisfy this test
        while the semantics move.
        """
        lib = _lib(libdir, "corelib_ff_1p10v_m40c", "slow")
        verdict, rc, rep = mod.evaluate(_hold_tcl(lib, "FF"), base=libdir)
        assert (verdict, rc) == ("FAIL", 1), (
            "a banner asserting process=FF does not outrank the Liberty it "
            "names on the same line")
        assert rep["reason"] == "HOLD_CORNER_CONTRADICTION"
        assert rep["hold_corner_measured"] is False, (
            "a line that contradicts itself about its corner was not measured "
            "at any corner; reporting it as measured is the union this "
            "arbitration replaced")

    def test_F8_filename_says_ss_but_liberty_declares_fast_now_PASSES(
            self, libdir):
        """The mirror of F6 — the repair must move verdicts in BOTH
        directions, or it is a one-way filter."""
        lib = _lib(libdir, "corelib_ss_0p90v_125c", "fast")
        verdict, rc, rep = mod.evaluate(_hold_tcl(lib), base=libdir)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["reason"] == "HOLD_AT_FF"


class TestForwardProjectMode:
    def test_F9_project_dir_end_to_end(self, libdir):
        sta = libdir / "phase3" / "stage3" / "sta"
        sta.mkdir(parents=True)
        lib = _lib(libdir, "corelib_bestcase", "fast")
        (sta / "sta_mcorner_ocv_hold.tcl").write_text(_hold_tcl(lib, "FF"))
        rep_dir = libdir / "reports" / "phase3"
        rep_dir.mkdir(parents=True)
        (rep_dir / "mcorner_ocv_stance.json").write_text(
            json.dumps({"hold_process_corner": "FF"}))
        verdict, rc, rep = mod.judge_project(libdir)
        assert (verdict, rc) == ("PASS", 0)
        assert not rep.get("contradiction"), (
            "the stance and the script now agree; pre-fix the script was "
            "blind and manufactured a CONTRADICTION")
        assert {s["verdict"] for s in rep["sources"]} == {"PASS"}


# ═════════════════════════════ REVERSE ═══════════════════════════════════
# Every test below calls the PRE-FIX signature (`evaluate(text)` /
# `evaluate_stance` / `judge_project`) so that "passes before AND after" is a
# claim that can actually be executed against the pre-fix file.
class TestReverseFilenameRouteSurvives:
    def test_R1_filename_ff_token_with_no_openable_file_still_passes(self):
        tcl = ("read_liberty /nonexistent/corelib__ff_1p10v_m40c.lib\n"
               "report_checks -path_delay min\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["reason"] == "HOLD_AT_FF"

    def test_R2_filename_ss_token_with_no_openable_file_still_fails(self):
        tcl = ("read_liberty /nonexistent/corelib__ss_0p90v_125c.lib\n"
               "report_checks -path_delay min\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_R3_mcmm_set_operating_conditions_line_still_passes(self):
        tcl = ("set_operating_conditions -analysis_type single ff_1p10v_m40c\n"
               "report_checks -path_delay min\n")
        verdict, rc, _ = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)

    def test_R4_hard_macro_extra_liberty_still_disclosed_not_failed(self):
        """The documented macro-narrowing case: an FF sign-off liberty plus a
        TT hard-macro liberty is a PASS with TT disclosed."""
        tcl = ("read_liberty corelib__ff_1p10v_m40c.lib\n"
               "read_liberty macro__tt_1p00v_25c.lib\n"
               "report_checks -path_delay min\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["extra_library_corners"] == ["TT"]

    def test_R5_relative_liberty_is_not_opened_when_there_is_no_base(
            self, libdir):
        """A caller with no directory context keeps exactly the pre-existing
        text-token behaviour, even when a contradicting Liberty of that name
        exists in the cwd-ish neighbourhood."""
        _lib(libdir, "corelib_ff_1p10v_m40c", "slow")
        tcl = ("read_liberty corelib_ff_1p10v_m40c.lib\n"
               "report_checks -path_delay min\n")
        verdict, rc, _ = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)


class TestReverseFailSafeNeverFailOpen:
    """Absolute paths, no `base` — so these run identically on both files."""

    def test_R6_unparseable_liberty_falls_back_to_filename_token(self, libdir):
        p = libdir / "corelib__ss_0p90v_125c.lib"
        p.write_text("this is not a liberty file at all\n")
        tcl = f"read_liberty {p}\nreport_checks -path_delay min\n"
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "HOLD_NOT_AT_FF"
        assert "liberty_declared_corners" not in rep

    def test_R7_liberty_with_unclassifiable_oc_name_falls_back(self, libdir):
        lib = _lib(libdir, "corelib__ff_1p10v_m40c", "bestcase_corner_7")
        tcl = f"read_liberty {lib}\nreport_checks -path_delay min\n"
        verdict, rc, _ = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0), (
            "an unclassifiable operating_conditions name must contribute "
            "NOTHING and leave the filename token deciding — fail-safe, "
            "never fail-open")

    def test_R8_directory_named_dot_lib_does_not_crash(self, libdir):
        d = libdir / "corelib__ff_1p10v_m40c.lib"
        d.mkdir()
        tcl = f"read_liberty {d}\nreport_checks -path_delay min\n"
        verdict, rc, _ = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)


class TestReverseHonestFailTiersUnmoved:
    def test_R9_no_hold_analysis_still_fails(self):
        tcl = ("read_liberty corelib__ff_1p10v_m40c.lib\n"
               "report_checks -path_delay max\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "NO_HOLD_ANALYSIS"

    def test_R10_empty_artefact_still_fails(self):
        verdict, rc, rep = mod.evaluate("   \n")
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "INPUT_EMPTY"

    def test_R11_missing_artefact_still_fails(self):
        verdict, rc, rep = mod.evaluate(None)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "INPUT_MISSING"

    def test_R12_no_corner_anywhere_still_NO_FEED_CORNER(self):
        """The blind tier must NOT be deleted — it is still the right verdict
        when there genuinely is nothing to read."""
        tcl = ("read_liberty /nonexistent/corelib_bestcase.lib\n"
               "report_checks -path_delay min\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "NO_FEED_CORNER"


class TestReverseStanceAndArbitrationUnmoved:
    def test_R13_stance_ff_still_passes(self):
        verdict, rc, _ = mod.evaluate_stance({"hold_process_corner": "FF"})
        assert (verdict, rc) == ("PASS", 0)

    def test_R14_stance_ss_still_fails(self):
        verdict, rc, rep = mod.evaluate_stance({"hold_process_corner": "SS"})
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_R15_stance_ff_beside_a_slow_script_still_FAILS_worst_of(
            self, libdir):
        """The load-bearing arbitration: a declared field does not outrank the
        evidence it claims to summarise. This is exactly the false PASS the
        previous repair removed and it must STAY removed. The script is failed
        on its FILENAME token here, so this runs identically on both files."""
        sta = libdir / "phase3" / "stage3" / "sta"
        sta.mkdir(parents=True)
        tcl = ("read_liberty /nonexistent/corelib__ss_0p90v_125c.lib\n"
               "report_checks -path_delay min\n")
        (sta / "sta_mcorner_ocv_hold.tcl").write_text(tcl)
        rep_dir = libdir / "reports" / "phase3"
        rep_dir.mkdir(parents=True)
        (rep_dir / "mcorner_ocv_stance.json").write_text(
            json.dumps({"hold_process_corner": "FF"}))
        verdict, rc, rep = mod.judge_project(libdir)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["contradiction"] is True

    def test_R16_no_artefact_at_all_still_disclosed_skip(self, libdir):
        verdict, rc, rep = mod.judge_project(libdir)
        assert (verdict, rc) == ("NOT CHECKED", 2)
        assert rep["reason"] == "NO_HOLD_SIGNOFF_ARTEFACT"


class TestReverseWiderDelimiterDoesNotInventCorners:
    """The `=`/bracket delimiters must not manufacture a corner out of
    ordinary Tcl."""

    def test_R17_ordinary_tcl_still_has_no_corner(self):
        tcl = ("set_units -time 1ns -capacitance 1pF\n"
               "set_propagated_clock [all_clocks]\n"
               "set_timing_derate -early 0.95 -late 1.05\n"
               "report_checks -path_delay min -fields {slew capacitance}\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "NO_FEED_CORNER"
        assert rep["hold_feed_corners"] == []
