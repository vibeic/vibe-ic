"""Unit tests for `hold_corner_coverage_check.py`."""
import importlib

mod = importlib.import_module("hold_corner_coverage_check")


_FF_TCL = """\
# hold analysis at the fast corner
read_liberty gf180mcu_fd_sc_mcu7t5v0__ff_1p10v_m40c.lib
read_verilog design.v
read_sdc design.sdc
report_checks -path_delay min -slack_max 0
report_worst_slack -min
"""

_SS_TCL = """\
# hold analysis reading the WRONG (slow) corner
read_liberty gf180mcu_fd_sc_mcu7t5v0__ss_0p90v_125c.lib
report_checks -path_delay min -slack_max 0
"""

_NO_HOLD_TCL = """\
read_liberty gf180mcu_fd_sc_mcu7t5v0__ff_1p10v_m40c.lib
report_checks -path_delay max -slack_max 0
report_worst_slack -max
"""

_MCMM_FF_VIEW = """\
set_operating_conditions -analysis_type single ff_1p10v_m40c
report_checks -path_delay min
"""


class TestEvaluatePass:
    def test_ff_liberty_passes(self):
        verdict, rc, report = mod.evaluate(_FF_TCL)
        assert verdict == "PASS"
        assert rc == 0
        assert report["hold_feed_corners"] == ["FF"]

    def test_mcmm_ff_operating_condition_passes(self):
        verdict, rc, report = mod.evaluate(_MCMM_FF_VIEW)
        assert verdict == "PASS"
        assert "FF" in report["hold_feed_corners"]


class TestEvaluateFailHonest:
    def test_ss_liberty_fails(self):
        verdict, rc, report = mod.evaluate(_SS_TCL)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "HOLD_NOT_AT_FF"
        assert "SS" in report["hold_feed_corners"]

    def test_no_hold_analysis_fails(self):
        # setup-only flow: there is no min-path / hold analysis at all
        verdict, rc, report = mod.evaluate(_NO_HOLD_TCL)
        assert verdict == "FAIL"
        assert report["reason"] == "NO_HOLD_ANALYSIS"

    def test_none_input_fails(self):
        verdict, rc, report = mod.evaluate(None)
        assert verdict == "FAIL"
        assert report["reason"] == "INPUT_MISSING"

    def test_empty_input_fails(self):
        verdict, rc, report = mod.evaluate("   \n  ")
        assert verdict == "FAIL"
        assert report["reason"] == "INPUT_EMPTY"

    def test_hold_run_but_no_feed_corner_fails(self):
        # a hold analysis runs but no Liberty/OC corner is identifiable
        txt = "report_checks -path_delay min -slack_max 0\n"
        verdict, rc, report = mod.evaluate(txt)
        assert verdict == "FAIL"
        assert report["reason"] == "NO_FEED_CORNER"


class TestCli:
    def test_cli_ff_pass(self, tmp_path):
        import json
        f = tmp_path / "hold.tcl"
        f.write_text(_FF_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(f), "--json", str(out)])
        assert rc == 0
        assert json.loads(out.read_text())["verdict"] == "PASS"

    def test_cli_ss_fail(self, tmp_path):
        import json
        f = tmp_path / "hold.tcl"
        f.write_text(_SS_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(f), "--json", str(out)])
        assert rc == 1
        assert json.loads(out.read_text())["reason"] == "HOLD_NOT_AT_FF"

    def test_cli_missing_file_fails(self, tmp_path):
        import json
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path / "nope.tcl"), "--json", str(out)])
        assert rc == 1
        assert json.loads(out.read_text())["verdict"] == "FAIL"


# ═════════════════════════════════════════════════════════════════════════
# Added when this gate was first WIRED (Step 23, unconditional).
# ═════════════════════════════════════════════════════════════════════════

# The flow's own emitter writes the sign-off corner liberty and then
# interpolates one `read_liberty` per HARD-MACRO liberty into the SAME hold
# script, narrowing multi-corner macro libs to the TYPICAL ones on purpose.
# The first version of this gate demanded that EVERY designator classify FF,
# so every macro-bearing design was failed `HOLD_NOT_AT_FF ['FF','TT']` for a
# hold sign-off that was in fact at FF. The corpus hid it: the only two runs
# that retained the script belong to a macro-free design.
_HOLD_TCL_WITH_MACRO = """\
read_liberty /pdk/lib/stdcells__ff_n40C_1v95.lib
read_liberty /proj/input/pdk_local/sram_1rw_64x32/lib/sram_1rw_64x32_tt_1p80V_25C.lib
read_verilog top_pnr.v
link_design top
read_sdc constraint.sdc
puts $_f "=== HOLD corner: process=FF liberty=/pdk/lib/stdcells__ff_n40C_1v95.lib ==="
report_worst_slack -min
report_checks -path_delay min
"""


class TestMacroLibrariesAreNotTheSignoffCorner:
    def test_typ_macro_liberty_does_not_fail_an_ff_hold_run(self):
        verdict, rc, report = mod.evaluate(_HOLD_TCL_WITH_MACRO)
        assert verdict == "PASS", report
        assert rc == 0

    def test_a_declared_hold_view_outranks_other_libraries(self):
        _v, _rc, report = mod.evaluate(_HOLD_TCL_WITH_MACRO)
        assert report["corner_basis"] == "declared_hold_view"
        assert report["judged_corners"] == ["FF"]

    def test_no_fast_corner_anywhere_is_still_a_fail(self):
        """The repair must not silence the defect: strip the FF liberty and
        only slow/typical libraries feed the hold analysis."""
        txt = _HOLD_TCL_WITH_MACRO.replace("__ff_n40C_1v95", "__ss_100C_1v60") \
                                  .replace("process=FF", "process=SS")
        verdict, rc, report = mod.evaluate(txt)
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "HOLD_NOT_AT_FF"


class TestDeclaredStance:
    """The DURABLE record: `hold_process_corner` in mcorner_ocv_stance.json.
    It survives when the Tcl is pruned from a published run, and it is what
    the run actually decided."""

    def test_ff_stance_passes(self):
        verdict, rc, report = mod.evaluate_stance(
            {"setup_process_corner": "SS", "hold_process_corner": "FF",
             "multi_process_corner": True})
        assert (verdict, rc) == ("PASS", 0)

    def test_tt_stance_fails(self):
        """The runner falls back to TT when the PDK has no fast liberty. A
        hold role assigned to TT under-reports hold violations, and no wired
        gate asked whether that assignment was legitimate."""
        verdict, rc, report = mod.evaluate_stance(
            {"setup_process_corner": "TT", "hold_process_corner": "TT",
             "multi_process_corner": False, "report": None})
        assert (verdict, rc) == ("FAIL", 1)
        assert report["reason"] == "HOLD_NOT_AT_FF"

    def test_no_declared_corner_is_not_checked(self):
        verdict, rc, report = mod.evaluate_stance(
            {"setup_process_corner": None, "hold_process_corner": None})
        assert rc == 2
        assert report["reason"] == "NO_DECLARED_HOLD_CORNER"

    def test_unreadable_stance_is_not_checked(self):
        verdict, rc, report = mod.evaluate_stance(None)
        assert rc == 2


class TestProjectDirectoryMode:
    """rc=2 is what lets the gate be wired UNCONDITIONALLY: gating a corner
    gate on the corner artefact is how an unreported corner became
    indistinguishable from a met one."""

    def test_project_without_any_hold_record_is_not_checked(self, tmp_path):
        rc = mod.main([str(tmp_path)])
        assert rc == 2

    def test_a_bad_stance_fails_even_beside_a_good_tcl(self, tmp_path):
        """WORST wins in BOTH directions. The declared field is the defective
        one here and the script is clean; the run is still FAILed, because the
        stance is what the run signed off with."""
        import json
        (tmp_path / "reports/phase3").mkdir(parents=True)
        (tmp_path / "reports/phase3/mcorner_ocv_stance.json").write_text(
            json.dumps({"hold_process_corner": "TT",
                        "multi_process_corner": False, "report": None}))
        (tmp_path / "phase3/stage3/sta").mkdir(parents=True)
        (tmp_path / "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl").write_text(
            _FF_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path), "--json", str(out)])
        assert rc == 1
        rep = json.loads(out.read_text())
        assert rep["deciding_source"] == "stance"
        assert rep["reason"] == "HOLD_NOT_AT_FF"
        assert rep["contradiction"] is True
        assert {s["source"]: s["verdict"] for s in rep["sources"]} == {
            "stance": "FAIL", "tcl": "PASS"}

    def test_project_falls_back_to_the_hold_tcl(self, tmp_path):
        import json
        (tmp_path / "phase3/stage3/sta").mkdir(parents=True)
        (tmp_path / "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl").write_text(
            _FF_TCL)
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path), "--json", str(out)])
        assert rc == 0
        assert json.loads(out.read_text())["verdict"] == "PASS"


# ═════════════════════════════════════════════════════════════════════════
# A DECLARED FIELD DOES NOT OUTRANK THE EVIDENCE IT CLAIMS TO SUMMARISE.
#
# `_discover` used to return the FIRST source it found and the stance was
# first, so a hold script that CONTRADICTED the declared field was never
# opened. Reproduced verbatim below: rc=0 PASS on the project directory,
# rc=1 FAIL on the identical Tcl. Two published roots
# (sha256/clean_run_v1422_20260715, …v1427…) carry BOTH artefacts.
# ═════════════════════════════════════════════════════════════════════════

_STANCE_SAYS_FF = {"hold_process_corner": "FF", "setup_process_corner": "SS",
                   "multi_process_corner": True,
                   "report": "phase3/stage3/sta/mcorner_ocv.rpt"}

_TCL_SAYS_SS = """\
# === HOLD corner: process=SS liberty=/pdk/lib/stdcells__ss_100C_1v60.lib ===
read_liberty /pdk/lib/stdcells__ss_100C_1v60.lib
read_verilog netlist.v
link_design top
report_checks -path_delay min -digits 4
"""

_TCL_SAYS_FF = _TCL_SAYS_SS.replace("__ss_100C_1v60", "__ff_n40C_1v95") \
                           .replace("process=SS", "process=FF")


def _project(tmp_path, *, stance=None, tcl=None):
    import json
    if stance is not None:
        (tmp_path / "reports/phase3").mkdir(parents=True, exist_ok=True)
        (tmp_path / "reports/phase3/mcorner_ocv_stance.json").write_text(
            json.dumps(stance))
    if tcl is not None:
        (tmp_path / "phase3/stage3/sta").mkdir(parents=True, exist_ok=True)
        (tmp_path / "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl").write_text(
            tcl)
    return tmp_path


class TestTheStanceCannotOutrankTheScript:

    def test_the_tcl_is_still_judged_when_a_stance_exists(self, tmp_path):
        """THE DEFECT. Pre-fix this returned rc=0 PASS on the strength of the
        declared `hold_process_corner: "FF"` while the only liberty the hold
        script reads is `…__ss_…` and its own banner says `process=SS`."""
        proj = _project(tmp_path, stance=_STANCE_SAYS_FF, tcl=_TCL_SAYS_SS)
        verdict, rc, rep = mod.judge_project(proj)
        assert (verdict, rc) == ("FAIL", 1), rep
        assert rep["deciding_source"] == "tcl"
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_the_same_tcl_alone_reaches_the_same_verdict(self, tmp_path):
        """The two readings that disagreed pre-fix now agree — which is the
        only way to know the project mode is reading the script at all."""
        direct_v, direct_rc, _ = mod.evaluate(_TCL_SAYS_SS)
        proj = _project(tmp_path, stance=_STANCE_SAYS_FF, tcl=_TCL_SAYS_SS)
        proj_v, proj_rc, _ = mod.judge_project(proj)
        assert (direct_v, direct_rc) == (proj_v, proj_rc) == ("FAIL", 1)

    def test_the_contradiction_is_published_not_just_the_winner(self, tmp_path):
        proj = _project(tmp_path, stance=_STANCE_SAYS_FF, tcl=_TCL_SAYS_SS)
        _v, _rc, rep = mod.judge_project(proj)
        assert rep["contradiction"] is True
        assert {s["source"]: s["verdict"] for s in rep["sources"]} == {
            "stance": "PASS", "tcl": "FAIL"}
        assert "CONTRADICTION" in rep["message"]

    def test_an_honest_stance_and_tcl_pair_still_PASSES(self, tmp_path):
        """NEGATIVE CONTROL — the repair must not redden agreeing evidence.
        This is the shape of the only 2 published roots that carry both."""
        proj = _project(tmp_path, stance=_STANCE_SAYS_FF, tcl=_TCL_SAYS_FF)
        verdict, rc, rep = mod.judge_project(proj)
        assert (verdict, rc) == ("PASS", 0), rep
        assert "contradiction" not in rep
        assert [s["verdict"] for s in rep["sources"]] == ["PASS", "PASS"]

    def test_a_stance_that_declares_nothing_cannot_mask_a_passing_tcl(
            self, tmp_path):
        """`FAIL > PASS > NOT CHECKED` is "worst of the verdicts REACHED".
        A stance with no `hold_process_corner` reached none, so it must not
        drag a real PASS down to rc=2 — that would discard evidence in the
        other direction, which is the same defect mirrored."""
        proj = _project(tmp_path, stance={"setup_process_corner": "SS"},
                        tcl=_TCL_SAYS_FF)
        verdict, rc, rep = mod.judge_project(proj)
        assert (verdict, rc) == ("PASS", 0), rep
        assert rep["deciding_source"] == "tcl"

    def test_a_stance_that_declares_nothing_cannot_mask_a_failing_tcl(
            self, tmp_path):
        proj = _project(tmp_path, stance={"setup_process_corner": "SS"},
                        tcl=_TCL_SAYS_SS)
        verdict, rc, _rep = mod.judge_project(proj)
        assert (verdict, rc) == ("FAIL", 1)

    def test_discover_returns_every_source_not_the_first(self, tmp_path):
        proj = _project(tmp_path, stance=_STANCE_SAYS_FF, tcl=_TCL_SAYS_SS)
        assert [k for k, _p in mod._discover(proj)] == ["stance", "tcl"]

    def test_neither_source_is_still_rc2(self, tmp_path):
        verdict, rc, rep = mod.judge_project(tmp_path)
        assert (verdict, rc) == ("NOT CHECKED", 2)
        assert rep["reason"] == "NO_HOLD_SIGNOFF_ARTEFACT"
        assert rep["sources"] == []

    def test_the_cli_surfaces_the_worst_verdict_end_to_end(self, tmp_path,
                                                           capsys):
        """Through `main`, not the helper: a wiring defect in the CLI branch
        must not hide behind a green unit test of `judge_project`."""
        import json
        proj = _project(tmp_path, stance=_STANCE_SAYS_FF, tcl=_TCL_SAYS_SS)
        out = tmp_path / "r.json"
        rc = mod.main([str(proj), "--json", str(out)])
        assert rc == 1
        printed = capsys.readouterr().out
        assert "source[stance] PASS" in printed
        assert "source[tcl] FAIL" in printed
        assert "CONTRADICTION" in printed
        assert json.loads(out.read_text())["contradiction"] is True


# ─────────────────────────────────────────────────────────────────────────────
# A DECLARED CORNER IS THE CLAIM; A CORNER IN A LIBERTY FILENAME IS NOT
#
# The emitter writes its hold banner as
#     === HOLD corner: process=FF liberty=<path> ===
# and the module docstring names that banner as RULE 2's primary evidence. It
# could not be read: `=` was absent from `_PROC_RE`'s delimiter class, so
# `process=FF` yielded NOTHING and the only corner the line produced came from
# the Liberty FILENAME beside it. On the usual naming conventions the two agree
# and the gate looks correct. The tests below are the two directions in which
# they DISAGREE — one produces a false FAIL, the other a false PASS — plus the
# two cases that must be untouched.
#
# BIDIRECTIONAL NEGATIVE CONTROL — measured against the byte-identical pre-fix
# module (`git show e3aa9b12:…/hold_corner_coverage_check.py`, md5
# d0390374c2f89145e3c227ceb4367e8d), same test file, `5 failed, 31 passed`:
#
#   FAILED  …declared_ff_is_read_when_the_liberty_filename_has_no_corner_token
#           the false FAIL: rc=1 NO_FEED_CORNER on a banner reading process=FF
#   FAILED  …a_declared_slow_corner_is_not_masked_by_a_fast_liberty_filename
#           the false PASS: rc=0 HOLD_AT_FF on a banner reading process=SS
#   FAILED  …the_delimiter_class_reads_an_equals_assignment      (root cause)
#   FAILED  …a_declared_slow_corner_alone_still_fails
#           pre-fix this reached FAIL, but via NO_FEED_CORNER — right verdict,
#           wrong reason, and the reason is what a reader acts on
#   FAILED  …an_assignment_to_a_non_corner_word_is_not_a_corner  (helper absent)
#
#   passed  …reverse_declared_ff_with_a_matching_filename_still_passes
#   passed  …a_view_line_without_an_assignment_is_unchanged
#
# The last two are the REVERSE cases and they must pass on BOTH sides. They are
# what stops this fix from being "narrow the rule until the bad case stops
# firing": the common shape (declaration and filename agreeing at FF) and the
# space-delimited MCMM shape are pinned unchanged.
# ─────────────────────────────────────────────────────────────────────────────

_LIB_WITH_TOKEN = "/pdk/lib/acme_sc__ff_n40C_1v95.lib"
_LIB_NO_TOKEN = "/pdk/lib/acme_sc_core_lib.lib"


def _banner_tcl(process: str, liberty: str) -> str:
    """The emitter's own hold script shape: a Liberty read, the `=== HOLD
    corner: process=<X> liberty=<path> ===` banner, and the min report."""
    return (
        f"read_liberty {liberty}\n"
        f'puts $_f "=== HOLD corner: process={process} liberty={liberty}, '
        f'SPEF=x.spef ==="\n'
        f"report_checks -path_delay min -digits 3\n"
    )


class TestDeclaredCornerOutranksTheLibertyFilename:

    def test_declared_ff_is_read_when_the_liberty_filename_has_no_corner_token(
            self):
        """FALSE FAIL. A PDK whose Liberty filenames carry no corner
        designator is an ordinary naming convention, not a defect. The banner
        says `process=FF`; the gate reported `NO_FEED_CORNER` — "no corner
        could be identified" — while quoting that very line back in
        `hold_feed_lines`."""
        verdict, rc, rep = mod.evaluate(_banner_tcl("FF", _LIB_NO_TOKEN))
        assert (verdict, rc) == ("PASS", 0)
        assert rep["reason"] == "HOLD_AT_FF"
        assert rep["judged_corners"] == ["FF"]
        assert rep["view_line_assigned_corners"] == ["FF"]

    def test_a_declared_slow_corner_is_not_masked_by_a_fast_liberty_filename(
            self):
        """FALSE PASS — the defect this gate exists to catch. The script
        declares `process=SS`, which under-reports hold violations. Reading the
        union of the line let `_ff_` in the filename supply an FF the
        declaration never claimed, and the gate returned PASS/`HOLD_AT_FF`
        under basis `declared_hold_view` — i.e. asserting it had judged the
        declaration it could not read."""
        verdict, rc, rep = mod.evaluate(_banner_tcl("SS", _LIB_WITH_TOKEN))
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "HOLD_NOT_AT_FF"
        assert rep["judged_corners"] == ["SS"]
        assert rep["view_line_assigned_corners"] == ["SS"]
        # The filename's corner is DISCLOSED, never silently dropped.
        assert rep["view_line_incidental_corners"] == ["FF"]

    def test_reverse_declared_ff_with_a_matching_filename_still_passes(self):
        """REVERSE CASE. The overwhelmingly common shape — declaration and
        filename AGREE at FF — must be untouched. A fix that reached the two
        cases above by narrowing what counts as evidence would break this
        one."""
        verdict, rc, rep = mod.evaluate(_banner_tcl("FF", _LIB_WITH_TOKEN))
        assert (verdict, rc) == ("PASS", 0)
        assert rep["reason"] == "HOLD_AT_FF"
        assert rep["judged_corners"] == ["FF"]

    def test_a_declared_slow_corner_alone_still_fails(self):
        """REVERSE CASE. Already correct before the fix; must stay correct.
        Pins that the new assignment path did not become a way to PASS."""
        verdict, rc, rep = mod.evaluate(_banner_tcl("SS", _LIB_NO_TOKEN))
        assert (verdict, rc) == ("FAIL", 1)
        assert rep["reason"] == "HOLD_NOT_AT_FF"

    def test_a_view_line_without_an_assignment_is_unchanged(self):
        """REVERSE CASE. `set_hold_view -corner ff_view` names its corner
        space-delimited, with no `=`. Such lines have always resolved through
        the union rule and must continue to — the fix adds a stronger reading
        where one exists, it does not remove the fallback."""
        tcl = ("read_liberty /pdk/lib/acme_sc__ff_n40C_1v95.lib\n"
               "set_hold_view -corner ff_view\n"
               "report_checks -path_delay min\n")
        verdict, rc, rep = mod.evaluate(tcl)
        assert (verdict, rc) == ("PASS", 0)
        assert rep["corner_basis"] == "declared_hold_view"
        assert "view_line_assigned_corners" not in rep

    def test_the_delimiter_class_reads_an_equals_assignment(self):
        """The one-character root cause, pinned directly so a future edit to
        `_PROC_RE` cannot silently re-open it."""
        assert mod._corners_in("process=FF") == ["FF"]
        assert mod._corners_in("corner=ss,") == ["SS"]
        # and the pre-existing delimiters keep working
        assert mod._corners_in("process FF") == ["FF"]
        assert mod._corners_in("lib__tt_025C.lib") == ["TT"]

    def test_an_assignment_to_a_non_corner_word_is_not_a_corner(self):
        """`_CORNER_ASSIGN_RE` must not fire on assignments whose value merely
        STARTS with a corner designator."""
        assert mod._assigned_corners_in("process=ffast_model") == []
        assert mod._assigned_corners_in("corner=ssub") == []
        assert mod._assigned_corners_in("mode=functional") == []
