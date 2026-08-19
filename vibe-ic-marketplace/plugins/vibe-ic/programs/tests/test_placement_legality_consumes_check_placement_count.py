"""The placer's own legality verdict must not be demoted to a warning.

WHAT THE TOOL ITSELF SAYS. From `info body check_placement` on the installed
binary (OpenROAD 26Q3-1472-g42cadea9df):

    # Returns the violation count. Without -no_abort a non-zero count raises
    # DPL-33 instead of returning, so an illegal placement can never be
    # mistaken for a legal one by a caller that ignores the result.
    return [dpl::check_placement_cmd $verbose $file_name $no_abort]

WHAT THE RUNNER DID WITH IT. Four FINAL call sites — after spare insertion,
after ECO repair, and twice in the ship-convergence loop — each wrapped the
call in `catch` and printed the caught value as a warning:

    if {[catch {check_placement} e]} { puts "SHIP_CP_WARN: $e" }

The catch was there for a real reason (an inherited mis-alignment must not
abort PnR) and it achieved that. It also threw the count away: `$e` is the
string "DPL-0033", the WARN line is read by no gate, and the process exits 0.

WHAT THE GATE DID WITH IT. `placement_legality_check` asserted the DEF STATUS
FIELD — COMPONENTS > 0, declared == parsed, every instance PLACED/FIXED/COVER,
and a density only when derivable. None of that can see an overlap: an
overlapping instance still carries `+ PLACED ( x y ) N`.

MEASURED, verbatim, in the pinned image. A four-instance design on a
purpose-built two-layer LEF, with U1 shifted so it overlaps U0:

  check_placement -no_abort   ->  [WARNING DPL-0005] Overlap check failed (1).
                                   U1 (cellA) overlaps U0 (cellA)
                                  [WARNING DPL-0011] Padding check failed (1).
                                  [WARNING DPL-0040] detailed placement checks
                                   failed during check placement: 2
                                   violation(s) returned to caller.
                                  returns 2
  check_placement             ->  same two warnings, then
                                  [ERROR DPL-0033] detailed placement checks
                                   failed during check placement.
                                  throws; the catch prints the WARN; rc 0

On the same design with U1 legal, both forms are silent and the return is 0 —
so the count is a clean discriminator, not a proxy.

POSITIVE (must not manufacture a failure): a clean count, and a run that
records no count at all, both stay PASS.

NEGATIVE no-leak — each of these must FAIL:
  - a token-clean placed.def plus `CHECK_PLACEMENT_VIOLATIONS <scope> <n>`;
  - the same run under the LEGACY swallow shape (`*_CHECK_PLACEMENT_WARN` /
    `SHIP_CP_WARN` / `SHIP_CVG_CP_WARN`), because a discarded count is an
    unknown placement, not a legal one;
  - `CHECK_PLACEMENT_NOT_DETERMINED`, because "the call did not answer" is
    not an answer.

And the runner must stop producing the swallow shape at its final sites.

chip-AGNOSTIC: the tool's own diagnostic IDs and flag, the runner's own marker
grammar, and a LEF/DEF fixture written for this test. No chip, PDK, library,
vendor or design literal.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import placement_legality_check as P  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures — the DEF fed to the real tool, and the real tool's real output.
# --------------------------------------------------------------------------

def _placed_def(overlapping: bool) -> str:
    """The exact COMPONENTS section fed to `check_placement`.

    Every instance carries the placement STATUS TOKEN in BOTH variants — that
    is the whole point: the token is written regardless of legality, so the
    pre-existing status checks report the two DEFs as identically clean.
    """
    xs = [0, 1380, 2760, 4140]
    if overlapping:
        xs[1] = 460  # U1 now sits inside U0's 0..1380 footprint
    recs = ["  - U%d cellA + PLACED ( %d 0 ) N ;" % (i, x)
            for i, x in enumerate(xs)]
    return "\n".join(
        ["VERSION 5.8 ;", "DESIGN top ;", "COMPONENTS %d ;" % len(recs)]
        + recs + ["END COMPONENTS", "END DESIGN"]) + "\n"


# Verbatim tail of the OpenROAD run on the overlapping DEF, under the shape
# the runner emits AFTER the fix.
_LOG_VIOLATIONS = """\
[INFO ODB-0131]     Created 4 components and 8 component-terminals.
[WARNING DPL-0005] Overlap check failed (1).
 U1 (cellA) overlaps U0 (cellA)
[WARNING DPL-0011] Padding check failed (1).
 U1
[WARNING DPL-0040] detailed placement checks failed during check placement: \
2 violation(s) returned to caller.
CHECK_PLACEMENT_VIOLATIONS SPARE 2
"""

# Verbatim tail of the same run under the shape the runner emitted BEFORE the
# fix: DPL-33 raised, caught, printed as a warning, process exits 0.
_LOG_SWALLOWED = """\
[INFO ODB-0131]     Created 4 components and 8 component-terminals.
[WARNING DPL-0005] Overlap check failed (1).
 U1 (cellA) overlaps U0 (cellA)
[WARNING DPL-0011] Padding check failed (1).
 U1
[ERROR DPL-0033] detailed placement checks failed during check placement.
SPARE_CHECK_PLACEMENT_WARN: DPL-0033
"""

# Verbatim tail of the run on the legal DEF.
_LOG_CLEAN = """\
[INFO ODB-0131]     Created 4 components and 8 component-terminals.
CHECK_PLACEMENT_CLEAN SPARE 0
SPARE_CHECK_PLACEMENT_PASS
"""

# The escalation loop legitimately catches DPL-33 on a rung and retries the
# next one, so DPL-33 lines occur in fully converged runs.
_LOG_ESCALATION_THEN_OK = """\
[WARNING DPL-0006] Site aligned check failed (3).
[ERROR DPL-0033] detailed placement checks failed during check placement.
INITIAL_DPL_LEGALIZE_OK disp=2
CHECK_PLACEMENT_CLEAN SPARE 0
"""


def _mk(tmp_path, log_text=None, *, overlapping=True, sub="pnr",
        log_name="openroad.log"):
    d = tmp_path / "phase3" / "stage3" / sub
    d.mkdir(parents=True, exist_ok=True)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "placed.def").write_text(_placed_def(overlapping))
    if log_text is not None:
        (d / log_name).write_text(log_text)
    return tmp_path


def _run(tmp_path):
    verdict, rc, findings, summary = P.inspect(tmp_path)
    return verdict, rc, {f["rule"] for f in findings}, findings, summary


def _msg(findings, rule):
    return next(f["message"] for f in findings if f["rule"] == rule)


# --------------------------------------------------------------------------
# The fixture itself must be the hard case: token-clean and illegal.
# --------------------------------------------------------------------------

def test_the_overlapping_fixture_is_token_clean(tmp_path):
    """If the DEF checks could already see this, the new reading would be
    redundant and the test would prove nothing."""
    _mk(tmp_path, None, overlapping=True)
    _v, _rc, rules, _f, summary = _run(tmp_path)
    assert summary["unplaced"] == 0
    assert summary["placed"] == 4
    assert "ALL_PLACED" in rules
    assert "UNPLACED_INSTANCES" not in rules


# ------------------------------------------------------------- POSITIVE ----

def test_a_clean_count_passes(tmp_path):
    _mk(tmp_path, _LOG_CLEAN, overlapping=False)
    verdict, rc, rules, _f, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "CHECK_PLACEMENT_CLEAN" in rules
    assert summary["check_placement_clean"][0]["scope"] == "SPARE"


def test_no_count_at_all_is_stated_not_scored(tmp_path):
    """A run that records no final count is not thereby illegal."""
    _mk(tmp_path, "nothing relevant here\n", overlapping=False)
    verdict, rc, rules, _f, _s = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "CHECK_PLACEMENT_VERDICT_ABSENT" in rules


def test_an_escalation_rungs_dpl33_is_not_a_final_verdict(tmp_path):
    """The legalizer catches DPL-33 per rung and retries; a converged run
    contains DPL-33 lines and must stay green."""
    _mk(tmp_path, _LOG_ESCALATION_THEN_OK, overlapping=False)
    verdict, rc, rules, _f, _s = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0), (
        "a bare DPL-33 line must not be scored — only the final-site markers")
    assert "CHECK_PLACEMENT_CLEAN" in rules


# ------------------------------------------------------ NEGATIVE no-leak ---

def test_a_nonzero_count_fails_a_token_clean_placed_def(tmp_path):
    _mk(tmp_path, _LOG_VIOLATIONS, overlapping=True)
    verdict, rc, rules, findings, summary = _run(tmp_path)
    assert summary["unplaced"] == 0, "fixture must stay token-clean"
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_VIOLATIONS" in rules
    v = summary["check_placement_violations"][0]
    assert (v["scope"], v["count"]) == ("SPARE", 2)
    # The tool's own number must be quoted, not paraphrased.
    m = _msg(findings, "CHECK_PLACEMENT_VIOLATIONS")
    assert "2 violation(s)" in m
    assert "DPL-0040" in m and "Overlap check failed (1)" in m


def test_the_legacy_swallow_shape_fails_and_recovers_the_count(tmp_path):
    """A caught DPL-33 is a non-zero count that was discarded. The gate must
    refuse on it and must reconstruct the number from the tool's own lines."""
    _mk(tmp_path, _LOG_SWALLOWED, overlapping=True)
    verdict, rc, rules, findings, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_DEMOTED_TO_WARNING" in rules
    m = _msg(findings, "CHECK_PLACEMENT_DEMOTED_TO_WARNING")
    assert "SPARE_CHECK_PLACEMENT_WARN" in m
    # 1 overlap + 1 padding == the 2 the -no_abort form returns for this DEF.
    assert "count for this call is 2" in m
    assert summary["check_placement_demoted"][0]["marker"] == (
        "SPARE_CHECK_PLACEMENT_WARN")


def test_every_legacy_swallow_marker_name_is_caught(tmp_path):
    """The four final sites used three different marker spellings."""
    for marker in ("SPARE_CHECK_PLACEMENT_WARN", "ECO_CHECK_PLACEMENT_WARN",
                   "SHIP_CP_WARN", "SHIP_CVG_CP_WARN"):
        d = tmp_path / marker
        _mk(d, "[ERROR DPL-0033] detailed placement checks failed during "
               "check placement.\n" + marker + ": DPL-0033\n",
            overlapping=True)
        verdict, rc, rules, _f, _s = _run(d)
        assert (verdict, rc) == ("FAIL", 1), marker
        assert "CHECK_PLACEMENT_DEMOTED_TO_WARNING" in rules, marker


def test_not_determined_is_not_a_pass(tmp_path):
    _mk(tmp_path, "CHECK_PLACEMENT_NOT_DETERMINED ECO DPL-103\n",
        overlapping=False)
    verdict, rc, rules, findings, _s = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_NOT_DETERMINED" in rules
    assert "DPL-103" in _msg(findings, "CHECK_PLACEMENT_NOT_DETERMINED")


def test_the_eco_sites_log_is_read_too(tmp_path):
    """The ECO deck tees its log into phase3/stage3/eco/, so a scan pinned to
    pnr/ alone would never see that site's verdict."""
    _mk(tmp_path, "CHECK_PLACEMENT_VIOLATIONS ECO 7\n", overlapping=True,
        sub="eco", log_name="eco_repair.log")
    verdict, rc, rules, _f, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_VIOLATIONS" in rules
    assert summary["check_placement_violations"][0]["count"] == 7


def test_the_def_checks_are_kept_not_replaced(tmp_path):
    """The two readings catch different failures; neither substitutes for the
    other. A clean placer verdict must not rescue an UNPLACED instance."""
    t = _mk(tmp_path, _LOG_CLEAN, overlapping=False)
    d = t / "phase3" / "stage3" / "pnr" / "placed.def"
    d.write_text(d.read_text().replace("- U2 cellA + PLACED ( 2760 0 ) N ;",
                                       "- U2 cellA + UNPLACED ;"))
    verdict, rc, rules, _f, _s = _run(t)
    assert (verdict, rc) == ("FAIL", 1)
    assert "UNPLACED_INSTANCES" in rules
    assert "CHECK_PLACEMENT_CLEAN" in rules


def test_cli_exit_code_and_json_carry_the_count(tmp_path):
    _mk(tmp_path, _LOG_VIOLATIONS, overlapping=True)
    out = tmp_path / "plc.json"
    rc = P.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert data["check_placement_violations"][0]["count"] == 2


# --------------------------------------------------------------------------
# The runner side: the four FINAL sites must stop swallowing the count.
# --------------------------------------------------------------------------

_SPARE_PLAN = {
    "count": 1,
    "instances": [{"name": "spare_inv_0", "cell": "CELL_INV", "type":
                   "inverter", "llx": 10, "lly": 10}],
}


def _spare_tcl():
    return R._build_spare_postfix_tcl(_SPARE_PLAN, tie_lo_cell="CELL_TIE",
                                      tie_lo_pin="LO")


def _eco_tcl():
    return R._build_eco_repair_tcl(
        top="chip_top", tech_lef_c="/c/tech.lef", cell_lef_c="/c/cells.lef",
        liberty_c="/c/cells.lib", pnr_dir_c="/c/p/phase3/stage3/pnr",
        eco_dir_c="/c/p/phase3/stage3/eco", metal_prefix="met")


def _ship_cvg_tcl():
    return R._ship_postroute_convergence_tcl("/c/cap", "/c/p/phase3/stage3/pnr")


def _ship_tcl():
    return R._ship_signoff_spef_repair_tcl(
        top="chip_top", tech_lef_c="/c/tech.lef", cell_lef_c="/c/cells.lef",
        ss_liberty_c="/c/ss.lib", pnr_dir_c="/c/p/phase3/stage3/pnr",
        max_captable_c="/c/cap", metal_prefix="met", thread_count=1)


_SITES = [("SPARE", _spare_tcl), ("ECO", _eco_tcl),
          ("SHIP_CVG", _ship_cvg_tcl), ("SHIP", _ship_tcl)]


def test_every_final_site_asks_for_the_count():
    for scope, build in _SITES:
        tcl = build()
        assert "check_placement -no_abort" in tcl, scope
        assert "CHECK_PLACEMENT_VIOLATIONS %s" % scope in tcl, scope
        assert "CHECK_PLACEMENT_CLEAN %s" % scope in tcl, scope


def test_no_final_site_demotes_the_verdict_to_a_warning():
    for scope, build in _SITES:
        tcl = build()
        for legacy in ("CHECK_PLACEMENT_WARN", "CP_WARN: "):
            assert legacy not in tcl, "%s still emits %s" % (scope, legacy)


def test_the_flow_still_does_not_abort_on_an_inherited_misalignment():
    """`-no_abort` is what replaces the catch, and it is the reason the catch
    can go: the call returns instead of raising, so PnR keeps running."""
    for scope, build in _SITES:
        tcl = build()
        i = tcl.index("check_placement -no_abort")
        # The only `catch` around it guards the *call*, not the verdict: a
        # non-zero count reaches the elseif, never the catch body.
        window = tcl[i - 200:i + 400]
        assert "CHECK_PLACEMENT_NOT_DETERMINED %s" % scope in window, scope


def test_the_escalation_loop_keeps_its_own_catch():
    """The per-rung catch is correct and must not be collateral damage: the
    loop retries the next displacement rung on a throw."""
    tcl = R._build_escalating_legalize_tcl("INITIAL_DPL", "_i")
    assert "catch {check_placement}" in tcl
    assert "INITIAL_DPL_LEGALIZE_FAILED" in tcl


def test_the_marker_grammar_is_shared_by_runner_and_gate():
    """One spelling, two readers — a drift here is silent."""
    assert R._CP_VIOLATIONS_MARKER == "CHECK_PLACEMENT_VIOLATIONS"
    assert R._CP_CLEAN_MARKER == "CHECK_PLACEMENT_CLEAN"
    assert R._CP_NOT_DETERMINED_MARKER == "CHECK_PLACEMENT_NOT_DETERMINED"
    for marker in (R._CP_VIOLATIONS_MARKER, R._CP_CLEAN_MARKER,
                   R._CP_NOT_DETERMINED_MARKER):
        assert marker in P.__doc__ or any(
            marker in r.pattern for r in
            (P._CP_VIOLATIONS_RE, P._CP_CLEAN_RE, P._CP_NOT_DETERMINED_RE))
