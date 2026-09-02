"""`pad_ring_route_evidence` must recognise the deck's ACTUAL call shape.

MEASURED: the clause searched for `(?m)^\\s*detailed_route(?:\\s|$)` and never
matched, so it reported

    PADRING_CONSUMER_MISSING: live placement/route commands absent after ingest

on every chip-path run. Detailed routing was running the whole time -- 78
mentions in `openroad.log` -- because the deck wraps the call:

    if {[catch {detailed_route {*}$_vic_drc_opt} dr_err]} {

a `catch` added so a router exception is NONFATAL. A column-zero reader could
not see it. The finding was real-looking, permanent, and false.

The hard part is not matching it. It is matching it WITHOUT becoming vacuous:
the same deck contains three comments naming the command and an
`info body detailed_route` probe, and a deck that only probed and never routed
must still be reported missing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as P  # noqa: E402

DR = P._PNR_CMD_DETAILED_ROUTE
GP = P._PNR_CMD_GLOBAL_PLACEMENT


def test_the_wrapped_catch_form_the_deck_actually_emits_is_matched():
    assert DR.search("if {[catch {detailed_route {*}$_vic_drc_opt} dr_err]} {")


def test_the_bare_column_zero_form_still_matches():
    assert DR.search("detailed_route\n")
    assert DR.search("  detailed_route -foo 1\n")
    assert GP.search("global_placement -routability_driven -density 0.3\n")


def test_a_comment_naming_the_command_is_NOT_matched():
    for line in ("# detailed_route then aborts DRT-0073 and writes a DEF\n",
                 "  # detailed_route fails (open-source iic-osic-tools has it)\n",
                 "# global_placement is described here but never called\n"):
        assert not DR.search(line) and not GP.search(line), line


def test_the_info_body_PROBE_is_NOT_matched():
    """A deck that only asked whether the command exists has not routed."""
    probe = "  if {[catch {info body detailed_route} _vic_dr_body]} { set x \"\" }\n"
    assert not DR.search(probe)


def test_a_deck_that_only_probes_is_still_reported_missing():
    """The vacuity guard: the reader must still REFUSE a non-routing deck."""
    deck = ('puts "PNR_STAGE: detailed_route"\n'
            '# detailed_route is mentioned in this comment only\n'
            'if {[catch {info body detailed_route} b]} { set b "" }\n'
            'if {[string match {*-output_drc*} $b]} { puts yes }\n')
    assert not DR.search(deck), (
        "a deck that names, probes and describes detailed_route but never "
        "calls it must still be reported missing, or this clause passes what "
        "it cannot have looked at")


def test_the_stage_marker_alone_does_not_satisfy_it():
    assert not DR.search('puts "PNR_STAGE: detailed_route"\n')


def test_it_matches_the_REAL_deck_this_repo_produces():
    """Built from the runner itself, not hand-written.

    A regex tuned to a fixture that the producer does not emit is how the
    original went wrong, so the shipped deck fragment is the fixture.
    """
    real = ('puts "PNR_STAGE: detailed_route"\n'
            'utl::push_metrics_stage "detailedroute__{}"\n'
            'if {![info exists _vic_drc_opt]} {\n'
            '  set _vic_drc_opt [list]\n'
            '  if {[catch {info body detailed_route} _vic_dr_body]} '
            '{ set _vic_dr_body "" }\n'
            '}\n'
            'if {[catch {detailed_route {*}$_vic_drc_opt} dr_err]} {\n'
            '  puts "DETAILED_ROUTE_NONFATAL: $dr_err"\n'
            '}\n')
    assert DR.search(real)


#: The pattern this change replaces, quoted EXACTLY as it stood.
OLD_DETAILED_ROUTE = r"(?m)^\s*detailed_route(?:\s|$)"


def test_the_OLD_pattern_does_NOT_match_the_real_deck():
    """The control, and it does not depend on the new symbol existing.

    Reverting the source and re-running this module yields a COLLECTION ERROR
    (the new constants are gone), which proves only that they are absent. This
    test is the real red direction: it applies the superseded pattern to the
    deck fragment the runner actually emits and shows it finds nothing. If some
    future change makes the old pattern match again, this test fails and says
    the regression it was written for is no longer the regression.
    """
    import re
    real = ('if {[catch {detailed_route {*}$_vic_drc_opt} dr_err]} {\n'
            '  puts "DETAILED_ROUTE_NONFATAL: $dr_err"\n'
            '}\n')
    assert re.search(OLD_DETAILED_ROUTE, real) is None, (
        "the superseded column-zero pattern now matches the wrapped call, so "
        "the false PADRING_CONSUMER_MISSING this change fixes is no longer "
        "reachable and this test has stopped being a control")
    assert DR.search(real), "the new pattern must match what the old one missed"
