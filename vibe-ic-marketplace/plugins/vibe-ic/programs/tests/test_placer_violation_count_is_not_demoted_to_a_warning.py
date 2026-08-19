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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import placement_legality_check as P  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

_TCLSH = shutil.which("tclsh")
_needs_tcl = pytest.mark.skipif(_TCLSH is None, reason="tclsh not installed")
_OPENROAD = shutil.which("openroad")
_needs_openroad = pytest.mark.skipif(
    _OPENROAD is None, reason="openroad not on PATH (container-only tool)")


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


def test_a_legacy_bare_pass_with_no_count_is_a_measured_zero(tmp_path):
    """The other half of the archive, and it must NOT be read as unknown.

    The pre-count runner printed `<SITE>_CHECK_PLACEMENT_PASS` only from the
    `else` branch of `catch {check_placement}` -- i.e. only when the aborting
    form did not throw, which is the placer returning zero. Reading that as
    NOT_DETERMINED would redden every archived run that was actually legal.
    MEASURED: a published run's `eco/eco_repair.log` carries this bare line.
    """
    _mk(tmp_path, None)
    eco = tmp_path / "phase3" / "stage3" / "eco"
    eco.mkdir(parents=True)
    (eco / "eco_repair.log").write_text("ECO_CHECK_PLACEMENT_PASS\n")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"ECO": "0"}
    assert "PLACER_REPORTED_VIOLATIONS" not in rules


@pytest.mark.parametrize("marker,site", [
    # the ship-time signoff repair...
    ("SHIP_CP_WARN", "SHIP"),
    # ...and the post-route convergence loop. Both spelled their WARN this way
    # before the count existed, and neither spelling contains
    # `_CHECK_PLACEMENT_WARN`, so a reader that keys only on the new grammar
    # sees an archived log of either shape as "no verdict recorded".
    ("SHIP_CVG_CP_WARN", "SHIP_CVG"),
])
def test_the_runners_older_ship_time_warn_spelling_is_not_read_as_silence(
        tmp_path, marker, site):
    """An ARCHIVED log may carry the ship-time sites' PREVIOUS marker names.

    Both were printed only from inside `if {[catch {check_placement} e]}`, so
    the line exists exactly when the call THREW -- the placer refusing. Reading
    that as "this run records no placer verdict" would be a silent false
    NEGATIVE of the very shape this gate exists to refuse, so it is read like
    any other count-less WARN: NOT_DETERMINED, never zero.
    """
    _mk(tmp_path, [f"{marker}: DPL-0033 detailed placement checks failed"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "PLACER_REPORTED_VIOLATIONS" in rules
    # the SITE must survive the parse -- a verdict attributed to the wrong site
    # is not the tool's verdict either
    assert summary["check_placement_sites"] == {site: "NOT_DETERMINED"}
    assert summary["check_placement_violations"] == "NOT_DETERMINED"
    assert "DPL-0033" in _msg(tmp_path, "PLACER_REPORTED_VIOLATIONS")


def test_the_older_spelling_does_not_fire_on_a_clean_run(tmp_path):
    """The positive control for the line above: recognising the old spelling
    must not turn a run that never printed it red. MEASURED across the
    published run roots -- no log carries the old spelling, so this widening
    flips nothing today and covers only the archive."""
    _mk(tmp_path, ["SHIP_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SHIP_CVG_CHECK_PLACEMENT_VIOLATIONS 0"])
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"SHIP": "0", "SHIP_CVG": "0"}


def test_the_generated_deck_is_not_read_as_a_verdict(tmp_path):
    """`pnr/signoff_spef_repair.tcl` contains the literal marker text -- it is
    the SCRIPT that emits it. MEASURED: a published run's deck carries
    `puts "SHIP_CP_WARN: $e"` while its log carries no such line. Reading a
    deck as a result would refuse every design that merely emitted one.
    """
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0"])
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    (pnr / "signoff_spef_repair.tcl").write_text(
        'if {[catch {check_placement} e]} { puts "SHIP_CP_WARN: $e" }\n'
        'puts "SHIP_CHECK_PLACEMENT_VIOLATIONS 99"\n')
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"SPARE": "0"}


def test_the_legacy_spelling_is_a_closed_set_not_a_wildcard(tmp_path):
    """`*_CP_WARN` as a wildcard would let any future marker from any
    subsystem redden the PLACEMENT gate. The legacy set is closed -- the two
    names the runner ever emitted from a bare `catch {check_placement}` -- so
    an unrelated marker that merely ends the same way is not a placer verdict.
    """
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0",
                   "SOME_OTHER_SUBSYSTEM_CP_WARN: unrelated"])
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"SPARE": "0"}


def test_the_closed_legacy_set_is_exactly_what_the_runner_ever_emitted():
    """...and the set is only closed while it is complete. Every
    `<X>_CP_WARN` name still present anywhere in the runner must be in it; a
    new one added without extending the set would be read as silence.
    """
    # The set itself, pinned: shrinking it must be a deliberate edit, not a
    # side effect. These are the two names `git log --all -S_CP_WARN` yields
    # over the runner's whole history, and both really are recognised.
    assert set(P._CP_LEGACY_WARN_SITES) == {"SHIP", "SHIP_CVG"}
    for site in P._CP_LEGACY_WARN_SITES:
        assert P._CP_LEGACY_WARN_RE.search(f"{site}_CP_WARN: DPL-0033")

    # ...and nothing in the runner emits a name outside it. The current runner
    # emits none at all (every site now carries the count), so this holds as a
    # guard on what comes next: a new bare `catch {check_placement}` printing
    # `<X>_CP_WARN` without extending the set would be read as silence.
    src = (Path(R.__file__)).read_text()
    emitted = set(re.findall(r'puts \\?"([A-Z0-9_]+)_CP_WARN', src))
    assert emitted <= set(P._CP_LEGACY_WARN_SITES), emitted


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


def _mk_two_logs(tmp_path, first_name, first, second_name, second):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "placed.def").write_text(_placed_def())
    (pnr / first_name).write_text("\n".join(first) + "\n")
    (pnr / second_name).write_text("\n".join(second) + "\n")
    return tmp_path


@pytest.mark.parametrize("dirty_log,clean_log", [
    # the dirty log sorts FIRST -- folding every log into one sequence would
    # let the clean one, which merely sorts last, overwrite the verdict
    ("a_dirty.log", "z_clean.log"),
    # ...and the mirror, so the test cannot pass by accident of ordering
    ("z_dirty.log", "a_clean.log"),
])
def test_a_clean_log_does_not_cancel_a_dirty_log_for_the_same_site(
        tmp_path, dirty_log, clean_log):
    """"Last reading" is only meaningful WITHIN one log file.

    The logs are walked in FILENAME order, which is not time order. A site
    read as 7 in one file and 0 in another must be illegal whichever way the
    two names happen to sort -- otherwise `a.log`=7 with `z.log`=0 passes as
    legal purely because `z` sorts last, which is a false NEGATIVE and exactly
    the failure this gate exists to refuse.
    """
    _mk_two_logs(
        tmp_path,
        dirty_log, ["SHIP_CHECK_PLACEMENT_VIOLATIONS 7",
                    "SHIP_CHECK_PLACEMENT_WARN: violations=7"],
        clean_log, ["SHIP_CHECK_PLACEMENT_VIOLATIONS 0",
                    "SHIP_CHECK_PLACEMENT_PASS"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1), (
        f"{dirty_log}=7 / {clean_log}=0 was called legal")
    assert summary["check_placement_sites"] == {"SHIP": "7"}
    assert "PLACER_REPORTED_VIOLATIONS" in rules
    assert "7" in _msg(tmp_path, "PLACER_REPORTED_VIOLATIONS")


def test_two_clean_logs_for_the_same_site_stay_green(tmp_path):
    """The positive half of the same rule: per-log tracking must not turn a
    run whose placer was clean in every log into a failure."""
    _mk_two_logs(
        tmp_path,
        "a.log", ["SHIP_CHECK_PLACEMENT_VIOLATIONS 0",
                  "SHIP_CHECK_PLACEMENT_PASS"],
        "z.log", ["SHIP_CHECK_PLACEMENT_VIOLATIONS 0",
                  "SHIP_CHECK_PLACEMENT_PASS"])
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"SHIP": "0"}
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


def test_the_eco_repairs_verdict_is_read_where_the_runner_writes_it(tmp_path):
    """The ECO site writes to `phase3/stage3/eco`, not to `pnr/`.

    `_build_eco_repair_tcl`'s output is run into `eco_dir()/eco_repair.log`
    (`_path_layout.eco_dir`), so a gate that walked only `pnr/` would have the
    ECO site emitting a count nothing ever opened -- the same demotion one
    directory over.
    """
    _mk(tmp_path, ["SPARE_CHECK_PLACEMENT_VIOLATIONS 0"])
    eco = tmp_path / "phase3" / "stage3" / "eco"
    eco.mkdir(parents=True)
    (eco / "eco_repair.log").write_text(
        "ECO_CHECK_PLACEMENT_VIOLATIONS 3\n"
        "ECO_CHECK_PLACEMENT_WARN: violations=3\n")
    _v, rc, rules, summary = _run(tmp_path)
    assert rc == 1 and "PLACER_REPORTED_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"ECO": "3", "SPARE": "0"}
    assert "3" in _msg(tmp_path, "PLACER_REPORTED_VIOLATIONS")


def test_the_log_roots_are_the_ones_the_runner_actually_writes_to():
    """Pin the roots to the layout module, so a directory rename cannot make
    this gate quietly stop reading a site."""
    import _path_layout as L
    proj = Path("/nonexistent-project")
    roots = {str(proj.joinpath(*parts)) for parts in P._LOG_ROOTS}
    assert str(L.pnr_dir(proj)) in roots
    assert str(L.eco_dir(proj)) in roots


def test_two_roots_do_not_merge_same_named_logs(tmp_path):
    """`pnr/x.log` and `eco/x.log` are different files and must stay different
    sequences -- otherwise a clean reading in one would cancel a dirty reading
    in the other by pretending they are one chronological log."""
    _mk(tmp_path, None)
    (tmp_path / "phase3" / "stage3" / "pnr" / "x.log").write_text(
        "ECO_CHECK_PLACEMENT_VIOLATIONS 5\n")
    eco = tmp_path / "phase3" / "stage3" / "eco"
    eco.mkdir(parents=True)
    (eco / "x.log").write_text("ECO_CHECK_PLACEMENT_VIOLATIONS 0\n")
    _v, rc, rules, summary = _run(tmp_path)
    assert rc == 1 and "PLACER_REPORTED_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"ECO": "5"}


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
    # an OpenROAD that TAKES -no_abort but returns nothing (check_placement did
    # not always return the count). Taking the flag is not the same as getting
    # a number back, and the difference is a false ALARM, not a false pass: a
    # LEGAL placement here must still read 0. Before the fallback covered this
    # shape it read NOT_DETERMINED and reddened every design on such a build.
    ("proc check_placement {args} { return }", "0", "PASS"),
    # ...and the same build with an ILLEGAL placement: the flagged form still
    # returns nothing, the bare form aborts, and the size stays unknown.
    ('proc check_placement {args} { if {[lsearch $args -no_abort] >= 0} '
     '{ return } ; error "DPL-0033" }', "NOT_DETERMINED", "WARN"),
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


# ====================================================== THE PLANTED OVERLAP ===
# Everything above drives the chain with a stub placer. This section drives it
# with the REAL one: a hand-written generic LEF and a DEF whose only difference
# from a legal placement is that ONE instance sits on its neighbour's site.
#
# MEASURED in the pinned image (OpenROAD 26Q3-1535-g543c33894f):
#
#   legal      -> check_placement -no_abort returns 0
#   overlapped -> [WARNING DPL-0005] Overlap check failed (1).
#                 [WARNING DPL-0011] Padding check failed (1).
#                 [WARNING DPL-0040] detailed placement checks failed during
#                                    check placement: 2 violation(s) returned
#                                    to caller.
#                 check_placement -no_abort returns 2
#   overlapped, WITHOUT -no_abort ->
#                 [ERROR DPL-0033] detailed placement checks failed during
#                                  check placement.
#
# which is the tool's own sentence made concrete: without `-no_abort` a non-zero
# count raises DPL-33 instead of returning. The pre-fix emitter caught that
# abort and printed `SPARE_CHECK_PLACEMENT_WARN: DPL-0033` -- the 2 never left
# the call, and the gate passed the design.
#
# chip-AGNOSTIC: the LEF below is written here, in this file, out of generic
# names. It is not a PDK, a library or a vendor artefact.

_ACCEPT_LEF = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MANUFACTURINGGRID 0.005 ;
LAYER metal1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.5 ;
  WIDTH 0.2 ;
  SPACING 0.2 ;
END metal1
SITE unitsite
  CLASS CORE ;
  SIZE 1.0 BY 10.0 ;
END unitsite
MACRO CELLA
  CLASS CORE ;
  ORIGIN 0 0 ;
  FOREIGN CELLA 0 0 ;
  SIZE 2.0 BY 10.0 ;
  SITE unitsite ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 0.4 4.8 0.6 5.2 ;
    END
  END A
  PIN Y
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal1 ;
        RECT 1.4 4.8 1.6 5.2 ;
    END
  END Y
END CELLA
END LIBRARY
"""

_ACCEPT_DEF_HEAD = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 40000 ) ;
ROW ROW_0 unitsite 0 0 N DO 100 BY 1 STEP 1000 0 ;
ROW ROW_1 unitsite 0 10000 FS DO 100 BY 1 STEP 1000 0 ;
"""


def _accept_def(u1_x: int) -> str:
    """A DEF that is legal at u1_x=4000 and has u1 sitting on u0 at u1_x=1000.

    `u0` occupies x 0..2000 (the macro is two sites wide), so 1000 puts u1
    half on top of it. Nothing else differs between the two files, and EVERY
    component carries `+ PLACED` in both -- which is the point: the status
    token cannot tell them apart.
    """
    rows = [("u0", 0, 0, "N"), ("u1", u1_x, 0, "N"), ("u2", 10000, 0, "N"),
            ("u3", 0, 10000, "FS"), ("u4", 6000, 10000, "FS")]
    body = ["COMPONENTS %d ;" % len(rows)]
    body += ["  - %s CELLA + PLACED ( %d %d ) %s ;" % r for r in rows]
    body += ["END COMPONENTS", "END DESIGN"]
    return _ACCEPT_DEF_HEAD + "\n".join(body) + "\n"


_LEGAL_X, _OVERLAP_X = 4000, 1000


def _openroad_on(def_text: str, verdict_tcl: str):
    """Run `verdict_tcl` in real OpenROAD over the given DEF; return stdout.

    `tempfile.mkdtemp` rather than pytest's `tmp_path`: in this image the
    pytest base temp path contains a newline, which OpenROAD's own argument
    handling does not survive.
    """
    work = Path(tempfile.mkdtemp(prefix="cp_accept_"))
    (work / "tech.lef").write_text(_ACCEPT_LEF)
    (work / "in.def").write_text(def_text)
    (work / "run.tcl").write_text(
        "read_lef tech.lef\nread_def in.def\n" + verdict_tcl)
    res = subprocess.run([_OPENROAD, "-no_init", "-exit", "run.tcl"],
                         cwd=str(work), capture_output=True, text=True,
                         timeout=300)
    return work, res.stdout + res.stderr


# The emitter shape this fix REMOVES, kept here verbatim as the control. It is
# what `origin/main` put at each of the four sites.
_PREFIX_EMITTER = (
    "if {[catch {check_placement} _cp_err]} {\n"
    "  puts \"SPARE_CHECK_PLACEMENT_WARN: $_cp_err\"\n"
    "} else {\n"
    "  puts \"SPARE_CHECK_PLACEMENT_PASS\"\n"
    "}\n")

# ...and the GATE that emitter was paired with. Every rule the pre-fix gate
# could FAIL on, enumerated from `origin/main`'s own source. The pre-fix gate
# is exactly this set: parse `placed.def`, refuse an UNPLACED token, refuse a
# `*_LEGALIZE_FAILED` marker, refuse a derivable density outside (0, 100].
# Asserting that NONE of them fires on the planted overlap is the same
# statement as "today's gate PASSES this design", and unlike loading the old
# source out of git it stays true as the gate grows — a future check that
# starts refusing this fixture for a DIFFERENT reason is a change to the
# control, and this assertion is where it surfaces.
_PRE_FIX_FAIL_RULES = frozenset({
    "PLACED_DEF_MISSING", "PLACED_DEF_EMPTY", "PLACED_DEF_UNPARSEABLE",
    "NO_COMPONENTS_SECTION", "EMPTY_COMPONENTS", "COMPONENT_COUNT_MISMATCH",
    "UNPLACED_INSTANCES", "LEGALIZER_REPORTED_FAILURE",
    "DENSITY_NONPOSITIVE", "DENSITY_OVER_100",
})


def _pre_fix_verdict(project: Path):
    """What the pre-fix gate would have returned for this project.

    It ran the SAME DEF/ladder/density readings this gate still runs and had
    no other predicate, so its verdict is FAIL iff one of those rules fires.
    """
    _v, _rc, findings, _s = P.inspect(project)
    fired = sorted({f["rule"] for f in findings
                    if f["severity"] == "FAIL"} & _PRE_FIX_FAIL_RULES)
    return ("FAIL" if fired else "PASS"), fired


def _gate_on(log_text: str, def_text: str):
    proj = Path(tempfile.mkdtemp(prefix="cp_gate_"))
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "placed.def").write_text(def_text)
    (pnr / "openroad.log").write_text(log_text)
    return proj, _run(proj)


@_needs_openroad
def test_the_real_placer_counts_the_planted_overlap():
    """The fixture has to actually be illegal, and legal without the move --
    otherwise everything below is testing a log, not a placement."""
    _w, dirty = _openroad_on(_accept_def(_OVERLAP_X),
                             'puts "N: [check_placement -no_abort]"\n')
    _w, clean = _openroad_on(_accept_def(_LEGAL_X),
                             'puts "N: [check_placement -no_abort]"\n')
    assert "Overlap check failed" in dirty, dirty
    assert "N: 0" in clean, clean
    n = int(next(l for l in dirty.splitlines()
                 if l.startswith("N: ")).split()[1])
    assert n > 0, dirty


@_needs_openroad
def test_the_prefix_emitter_loses_the_real_count():
    """THE DEMOTION, from the real tool: the abort is caught, the exception
    text is printed, and the number the placer computed is gone."""
    _w, out = _openroad_on(_accept_def(_OVERLAP_X), _PREFIX_EMITTER)
    assert "DPL-0033" in out, out
    assert "SPARE_CHECK_PLACEMENT_WARN" in out, out
    assert "CHECK_PLACEMENT_VIOLATIONS" not in out, out


@_needs_openroad
def test_todays_gate_passes_the_planted_overlap_and_this_one_fails_it():
    """The acceptance A/B, end to end and with nothing hand-written in the
    middle: the runner's OWN emitter runs in real OpenROAD over the planted
    overlap, its stdout becomes the PnR log unedited, and the gate refuses --
    quoting the count the placer returned."""
    def_text = _accept_def(_OVERLAP_X)
    _w, out = _openroad_on(
        def_text, R._build_check_placement_measured_tcl("SPARE", "_sp"))
    count = next(l.split()[1] for l in out.splitlines()
                 if l.startswith("SPARE_CHECK_PLACEMENT_VIOLATIONS"))
    assert count.isdigit() and int(count) > 0, out

    proj, (verdict, rc, rules, summary) = _gate_on(out, def_text)
    assert summary["unplaced"] == 0, "the DEF is token-clean, as it must be"

    # A. TODAY'S GATE. Not one of the rules it could refuse on fires: the DEF
    #    parses, every component carries `+ PLACED`, there is no
    #    `*_LEGALIZE_FAILED` marker and no derivable density. It PASSES a
    #    design the placer just counted violations in.
    pre_v, pre_fired = _pre_fix_verdict(proj)
    assert (pre_v, pre_fired) == ("PASS", []), (
        "the acceptance fixture must be one TODAY'S gate passes -- otherwise "
        "the A/B is measuring some other failure")

    # B. THIS GATE. Same project, same log, and it refuses -- quoting the
    #    number the placer returned.
    assert (verdict, rc) == ("FAIL", 1)
    assert "PLACER_REPORTED_VIOLATIONS" in rules
    assert summary["check_placement_sites"] == {"SPARE": count}
    assert count in _msg(proj, "PLACER_REPORTED_VIOLATIONS")

    # ... and the same overlap, seen only through the pre-fix emitter, is what
    # today's gate was handed. The count is absent from that log entirely, and
    # today's gate passes that one too.
    _w2, old_log = _openroad_on(def_text, _PREFIX_EMITTER)
    assert "CHECK_PLACEMENT_VIOLATIONS" not in old_log
    proj2, (v2, rc2, rules2, _s2) = _gate_on(old_log, def_text)
    assert _pre_fix_verdict(proj2) == ("PASS", [])
    assert (v2, rc2) == ("FAIL", 1), (
        "the legacy WARN spelling must still be refused, as NOT_DETERMINED")
    assert "PLACER_REPORTED_VIOLATIONS" in rules2


def test_the_pre_fix_control_list_is_not_stale():
    """The control is only a control while it names rules the gate really has.

    Every name in `_PRE_FIX_FAIL_RULES` must still be a rule this program can
    emit; if one is renamed away the control silently stops refusing anything
    and the A/B above degrades to "PASS because I looked for nothing".
    """
    src = (Path(P.__file__)).read_text()
    missing = sorted(r for r in _PRE_FIX_FAIL_RULES
                     if '"%s"' % r not in src)
    assert missing == [], missing


@_needs_openroad
def test_the_same_fixture_without_the_overlap_stays_green():
    """The negative control that keeps the fix from being 'always FAIL': move
    the one instance back onto its own site and nothing else, and the real
    placer returns 0 and the gate passes."""
    def_text = _accept_def(_LEGAL_X)
    _w, out = _openroad_on(
        def_text, R._build_check_placement_measured_tcl("SPARE", "_sp"))
    assert "SPARE_CHECK_PLACEMENT_VIOLATIONS 0" in out, out
    proj, (verdict, rc, rules, summary) = _gate_on(out, def_text)
    assert _pre_fix_verdict(proj) == ("PASS", []), (
        "today's gate passes the legal fixture too -- the A/B turns on the "
        "overlap and on nothing else")
    assert (verdict, rc) == ("PASS", 0)
    assert summary["check_placement_sites"] == {"SPARE": "0"}
    assert "PLACER_REPORTED_VIOLATIONS" not in rules
