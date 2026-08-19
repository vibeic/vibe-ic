"""The placer's own legality verdict must not be demoted to a warning.

`check_placement` RETURNS the violation count. The installed binary says so in
its own body (`info body check_placement`):

    "Returns the violation count. Without `-no_abort` a non-zero count raises
     DPL-33 instead of returning, so an illegal placement can never be mistaken
     for a legal one by a caller that ignores the result."

The runner asked for that verdict at four sites OUTSIDE the legalization ladder
-- after spare insertion, in the ECO repair, and twice in the ship-time repair
-- and every one of them was the caller that sentence warns about: `catch` the
DPL-33 abort, `puts` the exception TEXT as a WARN, continue. The count never
left the call, and `placement_legality_check` -- the gate NAMED for placement
legality -- read neither the count nor the warning.

MEASURED, on a project already in the corpus, from its own PnR log:

    [WARNING DPL-0006] Site aligned check failed (1).
    [ERROR DPL-0033] detailed placement checks failed during check placement.
    SPARE_CHECK_PLACEMENT_WARN: DPL-0033

and `placement_legality_check` on that same project: `verdict: PASS`.

MEASURED, on a fixture that is one real placed DEF with ONE instance moved onto
its neighbour's site and nothing else changed, run through real OpenROAD:

    pre-fix  emitter -> [ERROR DPL-0033] ... / SPARE_CHECK_PLACEMENT_WARN: DPL-0033
    post-fix emitter -> [WARNING DPL-0040] ... 2 violation(s) returned to caller.
                        SPARE_CHECK_PLACEMENT_VIOLATIONS 2
    gate before -> PASS (rc=0)      gate after -> FAIL (rc=1), quoting 2

What changed is what is RECORDED, not what aborts: the `catch` stays, the flow
still continues past a violation, and the number is now in the log in a form the
gate refuses on.

POSITIVE: a run whose placer returned 0, and a run that records no placer
verdict at all, must both stay green -- the fix must not manufacture a failure.

NEGATIVE no-leak -- each of these must FAIL:
  - a token-clean `placed.def` plus a non-zero `*_CHECK_PLACEMENT_VIOLATIONS`;
  - the same via a legacy log that carries only the bare `*_CHECK_PLACEMENT_WARN`
    (a run from a runner that predates the count);
  - a clean site earlier in the log not cancelling a dirty site later;
  - a count of NOT_DETERMINED, which is reached only through a call that THREW
    and therefore means "not clean, size unknown" -- never zero.

A site is asked more than once (the ship-time loop asks once per pass), so the
verdict keys on its LAST reading -- the state it left behind. A loop that went
3 -> 0 converged and is not called illegal; the 3 is DISCLOSED rather than
scored or dropped, because a run that had to converge is not a run that never
objected.

chip-AGNOSTIC: the runner's own marker grammar and standard OpenROAD commands.
No chip, PDK, library, vendor or design literal in the fix or in this test.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import placement_legality_check as P  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

_TCLSH = shutil.which("tclsh")
_needs_tcl = pytest.mark.skipif(_TCLSH is None, reason="tclsh not installed")


# --------------------------------------------------------------- fixtures ---

def _placed_def(n: int = 6) -> str:
    """A DEF whose every component carries the placement STATUS TOKEN -- i.e.
    one every DEF-level check calls fully legal. An overlapping instance
    carries this token too, which is the whole point."""
    out = ["VERSION 5.8 ;", "DESIGN top ;", "COMPONENTS %d ;" % n]
    out += ["  - U_%d CELL_A + PLACED ( %d 0 ) N ;" % (i, i * 100)
            for i in range(n)]
    out += ["END COMPONENTS", "END DESIGN"]
    return "\n".join(out) + "\n"


def _mk(tmp_path, log_lines=None, n: int = 6):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "placed.def").write_text(_placed_def(n))
    if log_lines is not None:
        (pnr / "openroad.log").write_text("\n".join(log_lines) + "\n")
    return tmp_path


def _run(tmp_path):
    verdict, rc, findings, summary = P.inspect(tmp_path)
    return verdict, rc, {f["rule"] for f in findings}, summary


def _msg(tmp_path, rule):
    _v, _rc, findings, _s = P.inspect(tmp_path)
    return next(f["message"] for f in findings if f["rule"] == rule)


# ================================================================ THE GATE ===
# ------------------------------------------------------------ POSITIVE ------

def test_a_measured_zero_count_stays_green(tmp_path):
    """The converged shape must be untouched."""
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SPARE_CHECK_PLACEMENT_PASS"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "PLACER_REPORTED_ZERO_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"SPARE": "0"}
    assert summary["check_placement_violations"] == 0


def test_no_placer_verdict_at_all_does_not_manufacture_a_failure(tmp_path):
    """A run that records nothing is not thereby illegal. The absence is
    stated; it is not scored either way."""
    _mk(tmp_path, log_lines=None)
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "LEGALIZER_VERDICT_ABSENT" in rules
    assert summary["check_placement_sites"] == {}
    assert summary["check_placement_violations"] is None


def test_every_site_clean_across_several_sites_stays_green(tmp_path):
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0",
                   "ECO_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SHIP_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 0"])
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {
        "ECO": "0", "SHIP": "0", "SHIP_CVG": "0", "SPARE": "0"}


# ------------------------------------------------------ NEGATIVE no-leak ----

def test_a_nonzero_count_fails_a_token_clean_placed_def(tmp_path):
    """THE case: every component carries `+ PLACED`, and the placer counted 2
    violations. The DEF checks are right about the file they read and cannot
    see this."""
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 2",
                   "SPARE_CHECK_PLACEMENT_WARN: violations=2"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert summary["unplaced"] == 0, "fixture must be token-clean"
    assert summary["placed"] == 6
    assert (verdict, rc) == ("FAIL", 1)
    assert "PLACER_REPORTED_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"SPARE": "2"}
    assert summary["check_placement_violations"] == 2


def test_the_failure_quotes_the_tools_own_count(tmp_path):
    """A verdict that does not carry the number is not the tool's verdict."""
    _mk(tmp_path, ["ECO_CHECK_PLACEMENT_VIOLATIONS 40"])
    m = _msg(tmp_path, "PLACER_REPORTED_VIOLATIONS")
    assert "ECO=40" in m


def test_a_legacy_bare_warn_with_no_count_still_fails(tmp_path):
    """The shape ALREADY IN THE CORPUS: a runner that predates the count wrote
    only the exception text. That is still the placer refusing, and the count
    is reported as NOT DETERMINED rather than guessed as zero."""
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_WARN: DPL-0033"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "PLACER_REPORTED_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"SPARE": "NOT_DETERMINED"}
    assert summary["check_placement_violations"] == "NOT_DETERMINED"
    assert "DPL-0033" in _msg(tmp_path, "PLACER_REPORTED_VIOLATIONS")


def test_not_determined_is_never_reported_as_zero(tmp_path):
    _mk(tmp_path, ["SHIP_CHECK_PLACEMENT_VIOLATIONS NOT_DETERMINED"])
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert summary["check_placement_sites"]["SHIP"] == "NOT_DETERMINED"
    assert summary["check_placement_violations"] != 0


def test_a_clean_site_does_not_cancel_a_dirty_one(tmp_path):
    """Legalization is not a best-of. If the placer ever counted a violation,
    the design carried it."""
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SPARE_CHECK_PLACEMENT_PASS",
                   "ECO_CHECK_PLACEMENT_VIOLATIONS 7"])
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert summary["check_placement_sites"] == {"ECO": "7", "SPARE": "0"}


def test_an_earlier_clean_reading_at_the_same_site_does_not_win(tmp_path):
    """The ship loop asks the same site once per pass. The last word is not the
    first word."""
    _mk(tmp_path, ["SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SHIP_CVG_CHECK_PLACEMENT_PASS",
                   "SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 3"])
    _v, rc, _rules, summary = _run(tmp_path)
    assert rc == 1 and summary["check_placement_sites"]["SHIP_CVG"] == "3"


# ------------------------------------------- converged, and still disclosed --

def test_a_loop_that_converged_is_not_called_illegal(tmp_path):
    """The ship-time loop asks its site once per pass. A first pass with 3
    violations and a last pass with 0 is a loop that CONVERGED; the state that
    site left behind is legal, and calling it illegal would be a false alarm
    about a placement the placer itself signed off."""
    _mk(tmp_path, ["SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 3",
                   "SHIP_CVG_CHECK_PLACEMENT_WARN: violations=3",
                   "SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SHIP_CVG_CHECK_PLACEMENT_PASS"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"SHIP_CVG": "0"}
    assert "PLACER_REPORTED_VIOLATIONS" not in rules


def test_a_recovered_violation_is_disclosed_not_dropped(tmp_path):
    """Not scored is not the same as not recorded. A run that had to converge
    must not read like a run that never objected."""
    _mk(tmp_path, ["SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 3",
                   "SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 0"])
    _v, rc, rules, summary = _run(tmp_path)
    assert rc == 0
    assert "PLACER_VIOLATIONS_RECOVERED" in rules
    assert summary["check_placement_recovered"] == {"SHIP_CVG": "3"}
    assert "3" in _msg(tmp_path, "PLACER_VIOLATIONS_RECOVERED")


def test_a_run_that_never_objected_discloses_nothing(tmp_path):
    """The disclosure must discriminate: no recovery finding on a clean run."""
    _mk(tmp_path, ["SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SHIP_CVG_CHECK_PLACEMENT_PASS"])
    _v, rc, rules, summary = _run(tmp_path)
    assert rc == 0
    assert "PLACER_VIOLATIONS_RECOVERED" not in rules
    assert summary["check_placement_recovered"] == {}


def test_the_count_is_found_in_any_pnr_log(tmp_path):
    """The runner writes more than one log under pnr/."""
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0"])
    (tmp_path / "phase3" / "stage3" / "pnr" / "eco.log").write_text(
        "ECO_CHECK_PLACEMENT_VIOLATIONS 1\n")
    _v, rc, rules, _s = _run(tmp_path)
    assert rc == 1 and "PLACER_REPORTED_VIOLATIONS" in rules


def test_the_ladder_verdict_is_still_read(tmp_path):
    """The pre-existing `*_LEGALIZE_FAILED` reading must not regress."""
    _mk(tmp_path, ["INITIAL_DPL_LEGALIZE_OK disp=default",
                   "POST_HOLD_LEGALIZE_FAILED"])
    _v, rc, rules, _s = _run(tmp_path)
    assert rc == 1 and "LEGALIZER_REPORTED_FAILURE" in rules


def test_the_def_checks_are_kept_and_still_catch_their_own_failure(tmp_path):
    """KEEP the DEF checks -- they catch a different failure. An UNPLACED
    instance must still FAIL even when the placer counted zero violations."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "placed.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 2 ;\n"
        "  - U_0 CELL_A + PLACED ( 0 0 ) N ;\n"
        "  - U_1 CELL_A + UNPLACED ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    (pnr / "openroad.log").write_text("SPARE_CHECK_PLACEMENT_VIOLATIONS 0\n")
    verdict, rc, rules, _s = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "UNPLACED_INSTANCES" in rules


def test_cli_exit_code_and_json_carry_the_count(tmp_path):
    """The gate is wired by exit code, and the JSON is the artefact of record."""
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 2"])
    out = tmp_path / "plc.json"
    assert P.main([str(tmp_path), "--json", str(out)]) == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert data["check_placement_sites"] == {"SPARE": "2"}
    assert data["check_placement_violations"] == 2


# =============================================================== THE RUNNER ===

_SITES = {
    "SPARE": lambda: R._build_spare_postfix_tcl(
        {"instances": [{"name": "u0", "cell": "C", "llx": 0, "lly": 0}],
         "out_dir": "/o"}),
    "ECO": lambda: R._build_eco_repair_tcl(
        top="t", tech_lef_c="/a.tlef", cell_lef_c="/b.lef",
        liberty_c="/c.lib", pnr_dir_c="/pnr", eco_dir_c="/eco",
        metal_prefix="met"),
    "SHIP": lambda: R._ship_signoff_spef_repair_tcl(
        top="t", tech_lef_c="/a.tlef", cell_lef_c="/b.lef",
        ss_liberty_c="/ss.lib", pnr_dir_c="/pnr", max_captable_c="/cap",
        metal_prefix="met", thread_count=8, filler_masters=[]),
    "SHIP_CVG": lambda: R._ship_postroute_convergence_tcl("/cap", "/pnr"),
}


@pytest.mark.parametrize("site", sorted(_SITES))
def test_every_call_site_emits_the_measured_count(site):
    """Every site that asks the placer for its verdict must record the number.
    A site that only prints the exception text has swallowed it."""
    tcl = _SITES[site]()
    assert f"{site}_CHECK_PLACEMENT_VIOLATIONS" in tcl, (
        f"{site} asks check_placement but records no violation count")
    assert "check_placement -no_abort" in tcl, (
        f"{site} does not use the form that RETURNS the count")


@pytest.mark.parametrize("site", sorted(_SITES))
def test_no_call_site_swallows_the_exception_text_alone(site):
    """The pre-fix shape -- `catch` the abort, print `$err`, carry on with the
    number gone -- must be absent from every site."""
    tcl = _SITES[site]()
    for swallow in (f'puts "{site}_CHECK_PLACEMENT_WARN: $_cp_err"',
                    f'puts "{site}_CP_WARN: $e"'):
        assert swallow not in tcl, f"{site} still swallows: {swallow}"


@_needs_tcl
@pytest.mark.parametrize("stub,expect_count,expect_verdict", [
    # a modern OpenROAD, legal placement
    ("proc check_placement {args} { return 0 }", "0", "PASS"),
    # a modern OpenROAD, 40 violations returned through -no_abort
    ('proc check_placement {args} { if {[lsearch $args -no_abort] >= 0} '
     '{ return 40 } ; error "DPL-0033" }', "40", "WARN"),
    # an OpenROAD with no -no_abort flag, legal placement
    ("proc check_placement {} { return }", "0", "PASS"),
    # an OpenROAD with no -no_abort flag, ILLEGAL placement: the aborting form
    # tells us THAT it is non-zero and never how large. NOT DETERMINED beats a
    # guess, and beats zero.
    ('proc check_placement {} { error "DPL-0033 checks failed" }',
     "NOT_DETERMINED", "WARN"),
])
def test_the_emitted_tcl_measures_the_count_on_every_openroad_shape(
        tmp_path, stub, expect_count, expect_verdict):
    src = stub + "\n" + R._build_check_placement_measured_tcl("TEST", "_t")
    f = tmp_path / "cp.tcl"
    f.write_text(src)
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert f"TEST_CHECK_PLACEMENT_VIOLATIONS {expect_count}" in r.stdout, \
        r.stdout
    assert f"TEST_CHECK_PLACEMENT_{expect_verdict}" in r.stdout, r.stdout


@_needs_tcl
def test_a_violation_does_not_abort_the_flow(tmp_path):
    """The `catch` stays. This change makes the count RECORDED, not fatal to
    PnR -- a step that aborts writes no DEF for anything downstream to judge."""
    src = ('proc check_placement {args} { error "DPL-0033" }\n'
           + R._build_check_placement_measured_tcl("TEST", "_t")
           + 'puts "REACHED_THE_NEXT_STEP"\n')
    f = tmp_path / "cont.tcl"
    f.write_text(src)
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert "REACHED_THE_NEXT_STEP" in r.stdout


# ------------------------------------------------------- end-to-end chain ---

@_needs_tcl
def test_the_runners_own_output_is_what_the_gate_refuses_on(tmp_path):
    """The two halves must actually meet: run the runner's OWN emitted Tcl
    against a stub placer that counts 2 violations, write what it printed into
    the PnR log, and hand it to the gate unedited."""
    src = ('proc check_placement {args} { if {[lsearch $args -no_abort] >= 0} '
           '{ return 2 } ; error "DPL-0033" }\n'
           + R._build_check_placement_measured_tcl("SPARE", "_sp"))
    f = tmp_path / "emit.tcl"
    f.write_text(src)
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr

    proj = tmp_path / "proj"
    _mk(proj, log_lines=r.stdout.strip().splitlines())
    verdict, rc, rules, summary = _run(proj)
    assert (verdict, rc) == ("FAIL", 1)
    assert "PLACER_REPORTED_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"SPARE": "2"}
