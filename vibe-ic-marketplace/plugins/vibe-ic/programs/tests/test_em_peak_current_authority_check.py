#!/usr/bin/env python3
"""Tests for em_peak_current_authority_check.py — the EM peak current must
reach a COMPARISON, or the step must name the authority it lacks.

WHAT EACH TEST IS FOR, so a later reader can tell a decision test from a
plumbing test:

  * ``test_peak_over_supply_current_fails`` and
    ``test_peak_under_supply_current_does_not_fail`` are the DECISION. They are
    the pair the mutant arm targets: neuter the comparison and the first dies.
  * ``test_no_jmax_refuses_and_names_it`` is the REFUSAL — a physically possible
    current is not an EM pass, and the gate must say so rather than print PASS.
  * ``test_incomplete_sentinel_survives_the_flow_tail_cut`` is the one that a
    reviewer would otherwise have to take on trust: the consumer keeps only the
    LAST 300 characters of stdout, so a disclosure printed anywhere else is not
    a disclosure. A first draft of this gate failed exactly here.
  * ``test_jmax_present_screens_and_names_the_threshold`` proves the wiring to
    ``em_current_density_check`` is real, and that a PASS states what it
    compared against.

Fixtures are SYNTHETIC and carry no process, foundry or chip token: a made-up
net name, round numbers, and a Jmax table whose layer names are generic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PROG = _HERE.parent / "em_peak_current_authority_check.py"
sys.path.insert(0, str(_HERE.parent))

#: A report in the shape the flow's own emitter writes: the runner's summary
#: line, the tool's own stdout lines, and the IR block that declares the
#: authority (total power and supply voltage for the analysed net).
RPT = """\
tool: power-grid analyser, electromigration mode
EM lifetime screen: power-grid segment current density

segments_analysed: 4
max segment current: {peak} A
current density (Jpeak, derived): {peak} A per segment width

########## IR report #################
Net              : PWRNET
Total power      : {power} W
Supply voltage   : {volt} V
Worstcase IR drop: 3.75e-04 V
######################################
########## EM analysis ###############
Net                : PWRNET
Maximum current    : {peak} A
Average current    : 7.03e-06 A
######################################
"""

CSV = ("Node0 Layer,Node0 X location,Node0 Y location,"
       "Node1 Layer,Node1 X location,Node1 Y location,Current\n"
       "mA,0,0,mA,1,0,{peak}\n"
       "mA,1,0,mA,2,0,1.0e-06\n")

#: Generic routing layer with a DC current-density limit. `mA` is a LAYER NAME
#: here, chosen so no real metal stack is implied.
JMAX = {"layers": {"mA": {"kind": "routing", "thickness_um": 0.35,
                          "width_um": 0.14, "jmax_mA_per_um": 2.8}}}


def _project(tmp_path: Path, peak: str, power: str = "1.34e-03",
             volt: str = "1.80e+00", with_csv: bool = False,
             with_jmax: bool = False) -> Path:
    proj = tmp_path / "run"
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "em.rpt").write_text(
        RPT.format(peak=peak, power=power, volt=volt))
    (proj / "reports" / "phase3" / "em.json").write_text(json.dumps(
        {"tool": "psm", "segments_analysed": 4,
         "max_segment_current_A": float(peak), "verdict": "MEASURED"}))
    if with_csv:
        (proj / "reports" / "phase3" / "em_segments.csv").write_text(
            CSV.format(peak=peak))
    if with_jmax:
        (proj / "reports" / "phase3" / "em_jmax.json").write_text(
            json.dumps(JMAX))
    return proj


def _run(proj: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(proj), *[str(a) for a in args]],
        capture_output=True, text=True)


# ── the DECISION ───────────────────────────────────────────────────────────
def test_peak_over_supply_current_fails(tmp_path):
    """5.0 A on a net supplied with 7.44e-04 A is a contradiction inside one
    artefact. This is the ledger's ART-EM-CURRENT-DENSITY mutation, in
    miniature."""
    proj = _project(tmp_path, peak="5.0")
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "EM_PEAK_CURRENT_EXCEEDS_SUPPLY" in r.stdout
    # The finding must NAME both sides. A finding that states only the offence
    # is the same shape of unfalsifiable output this gate was written against.
    assert "5.0000e+00" in r.stdout
    assert "7.4444e-04" in r.stdout


def test_peak_under_supply_current_does_not_fail(tmp_path):
    """The published corpus's own ratio. Nothing may go RED here.

    rc 2, not 0, since vibe-ic#1017: this project has no Jmax authority, so the
    gate reaches INCOMPLETE and INCOMPLETE is now the disclosed-skip tier. What
    this test guards is unchanged and is the thing that matters — the supply
    screen does not fire — and it is asserted directly rather than through the
    exit code.

    The half of the control that keeps this gate from being a BLANKET refusal
    is `test_jmax_present_screens_and_names_the_threshold`, which still earns a
    real rc 0.
    """
    proj = _project(tmp_path, peak="1.963e-04")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "EM_PEAK_CURRENT_EXCEEDS_SUPPLY" not in r.stdout


def test_the_bound_is_one_not_a_guardband(tmp_path):
    """Just under and just over 1.0 must land on opposite sides. If someone
    later introduces a margin here, this dies — which is the point: the limit
    is conservation of charge and there is nothing in it to tune."""
    # supplied current = 1.0e-03 / 1.0 = 1.0e-03 A
    #
    # Just UNDER is rc 2, not 0 (vibe-ic#1017): neither project carries a Jmax
    # authority, so passing the supply screen still leaves the gate INCOMPLETE.
    # The two sides remain opposite — 2 is "I did not finish", 1 is "I looked
    # and it was wrong" — and only one of them is a verdict.
    assert _run(_project(tmp_path / "a", peak="9.99e-04", power="1.0e-03",
                         volt="1.0")).returncode == 2
    assert _run(_project(tmp_path / "b", peak="1.01e-03", power="1.0e-03",
                         volt="1.0")).returncode == 1


# ── the REFUSAL ────────────────────────────────────────────────────────────
def test_no_jmax_refuses_and_names_it(tmp_path):
    """A current that is physically possible is not an EM pass. With no Jmax
    authority the gate must REFUSE and name what it lacks — never print PASS,
    and (vibe-ic#1017) never EXIT like one either."""
    proj = _project(tmp_path, peak="1.963e-04")
    r = _run(proj)
    assert r.returncode == 2
    assert "[PASS]" not in r.stdout
    assert any(l.lstrip().startswith("INCOMPLETE")
               for l in r.stdout.splitlines())
    assert "Jmax" in r.stdout
    # A PASS must say how much it looked at; so must a refusal.
    assert "of 4 segment(s) screened against Jmax" in r.stdout


def test_empty_project_refuses_and_discloses(tmp_path):
    """Zero denominator: the gate must REFUSE, and refusing means rc 2.

    This docstring used to read "it may exit 0 only if it SAYS so" — and that
    is NOT the house rule, which is why `test_matrix_d2_falsifiable` was red on
    main for five merges (vibe-ic#1017). `gate_zero_denominator_refuses_check`
    says REFUSE. Saying so in stdout while exiting 0 does not reach the
    consumer: this gate is a BLOCKING `program_exit_zero` clause at step 25,
    and `program_exit_zero` reads the EXIT CODE, not the prose. An empty tree
    used to pass it.
    """
    proj = tmp_path / "empty"
    (proj / "reports").mkdir(parents=True)
    r = _run(proj)
    assert r.returncode == 2
    assert "[PASS]" not in r.stdout
    assert any(l.lstrip().startswith("INCOMPLETE")
               for l in r.stdout.splitlines())
    assert "read 0 peak-current figure(s)" in r.stdout


def test_incomplete_sentinel_survives_the_flow_tail_cut(tmp_path):
    """THE DISCLOSURE CHANNEL, not the disclosure.

    `flow_compliance_check.output_snippet` keeps only the last
    `_OUTPUT_SNIPPET_CHARS` characters of stdout. A sentinel printed at the head
    of a long paragraph is deleted before any tier is decided — measured, that
    is what a first draft of this gate did. Asserted against the consumer's own
    functions so it cannot drift.
    """
    import flow_compliance_check as fcc
    proj = _project(tmp_path, peak="1.963e-04")
    r = _run(proj)
    snippet = fcc.output_snippet(r.stdout, r.stderr)
    assert fcc._stdout_signals_token(snippet, fcc._INCOMPLETE_STDOUT_TOKEN)


# ── the WIRING to the real EM screen ───────────────────────────────────────
def test_jmax_present_screens_and_names_the_threshold(tmp_path):
    """With a Jmax reference the delegated screen runs and the PASS states what
    it compared against. A PASS that names no threshold is indistinguishable
    from one that never looked."""
    proj = _project(tmp_path, peak="1.0e-06", with_csv=True, with_jmax=True)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("[PASS]"), r.stdout
    assert "Compared against Jmax from" in r.stdout
    assert "em_jmax.json" in r.stdout
    assert "worst utilization" in r.stdout
    assert "2 of 2 segment(s) screened against Jmax" in r.stdout


def test_jmax_offender_fails(tmp_path):
    """The delegated screen's FAIL is carried, not swallowed. 1.0e-03 A through
    a 0.14 um wide layer limited to 2.8e-03 A/um is over the margined limit."""
    proj = _project(tmp_path, peak="1.0e-03", power="1.0e+00", volt="1.0",
                    with_csv=True, with_jmax=True)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "EM_CURRENT_DENSITY_OVER_JMAX" in r.stdout
    # …and NOT because of the supply screen: 1.0e-03 A against a net supplied
    # with 1.0 A is physically fine, so this red is attributable to Jmax alone.
    assert "EM_PEAK_CURRENT_EXCEEDS_SUPPLY" not in r.stdout


def test_json_report_is_written_and_carries_both_tiers(tmp_path):
    proj = _project(tmp_path, peak="1.963e-04")
    out = tmp_path / "out.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 2          # INCOMPLETE tier, vibe-ic#1017
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "INCOMPLETE"
    assert doc["supply_current_screen"]["screened"] is True
    assert doc["supply_current_screen"]["limit_ratio"] == 1.0
    assert doc["jmax_screen"]["verdict"] == "SKIPPED"
    assert "Jmax" in doc["missing_authority"]


def test_not_a_directory_is_an_argument_error(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2


# ── the TIER AS THE CONSUMER SEES IT (vibe-ic#1017) ────────────────────────
def _flow_disposition(fcc, project, cmd, *, slot="program_exit_zero"):
    """What the flow does with this command: the wrapper's snippet, the class
    it published, and the tier the STEP reaches through the slot the canonical
    flow wires this gate in.  Read through the consumer's own functions so it
    cannot drift from them."""
    ok, out = fcc._check_program_exit_zero(project, cmd)
    cls = (out.split("reason_class=", 1)[1].split(";", 1)[0].strip()
           if "reason_class=" in out else None)
    step = {"id": "probe", "name": "one clause",
            "gate": {"all_of": [{slot: cmd}]}}
    return ok, out, cls, fcc.check_step(project, step, {}).status


def test_the_refusal_reaches_the_flow_as_not_a_pass(tmp_path):
    """The exit code only matters because of what `flow_compliance_check` does
    with it, so assert it THERE and not just here.

    This is the whole of vibe-ic#1017. Both of this campaign's step-25/step-33
    gates printed a refusal and returned 0, and `program_exit_zero` — a
    BLOCKING clause — reads the exit code, not the prose. An empty tree passed.
    `test_matrix_d2_falsifiable::test_d2_gate_has_a_reachable_fail` said so on
    main for five merges and was merged past each time.

    WHAT THIS ASSERTION USED TO ASK, AND WHY IT WAS THE WRONG QUESTION. It
    required the snippet to be `__VACUOUS_HINT__` — "the input-missing skip
    convention, explicitly NOT a clean result". At the time that marker was the
    only tier between PASS and FAIL, so pinning the MARKER was the only way to
    spell the PROPERTY. `#1978`/`#1980` added the reason taxonomy and the two
    came apart: rc 2 is now classified, and only a SKIP_ELIGIBLE class
    (DESIGN_DECLARED_NA / CAPABILITY_ABSENT / EXTERNAL) keeps the skip marker.
    This gate's own stdout has printed the line-start sentinel `INCOMPLETE:`
    since it was written — the gate has always said it was NOT screened — and
    the old wrapper DELETED that sentence and substituted the skip marker. The
    property the assertion meant ("not a clean result") holds more strongly
    than before; the marker it was spelled with no longer does. So it is the
    QUESTION that is rewritten here, not the behaviour.

    MEASURED, on the same empty tree (tree ca330272d): the step tier is
    INCOMPLETE, and it is VACUOUS_PASS only if the class is relabelled
    skip-eligible — which is the relabel `test_the_tier_is_not_bought_by_a_
    relabel` below exists to redden.
    """
    import flow_compliance_check as fcc

    empty = tmp_path / "empty"
    (empty / "reports").mkdir(parents=True)
    ok, out, cls, tier = _flow_disposition(
        fcc, empty, "em_peak_current_authority_check .")
    assert ok, out            # rc 2 is still not a FAIL ...
    assert not out.startswith(fcc._VACUOUS_HINT_PREFIX), out  # ... nor a skip
    # ... and it is not a PASS either, which is what #1017 was about.
    assert cls not in _reason_taxonomy().SKIP_ELIGIBLE, out
    assert tier == "INCOMPLETE", (tier, out)
    # the gate's OWN sentence now survives into the flow's snippet, which is
    # what the substituted marker used to delete.
    assert "NOT screened" in out, out

    real = _project(tmp_path / "real", peak="1.0e-06", with_csv=True, with_jmax=True)
    ok2, out2, cls2, tier2 = _flow_disposition(
        fcc, real, "em_peak_current_authority_check .")
    assert ok2, out2
    assert not out2.startswith(fcc._VACUOUS_HINT_PREFIX), out2
    assert cls2 is None and tier2 == "PASS", (cls2, tier2, out2)


def _reason_taxonomy():
    import _flow_reason_taxonomy as T
    return T


def test_the_tier_is_not_bought_by_a_relabel(tmp_path):
    """THE ASSERTION THAT REDDENS IF THE CLASSIFICATION MOVES AGAIN.

    The cheapest way to make the assertion above go green again is to teach
    this gate to publish `reason_class: CAPABILITY_ABSENT` (or to widen
    SKIP_ELIGIBLE), which returns it to the skip tier without measuring one
    more ampere. A denominator of zero is not a missing capability. This pins
    the CONSEQUENCE of that relabel — the step certifies — so the trade is
    visible in a diff instead of only in a tier nobody re-reads."""
    import flow_compliance_check as fcc
    T = _reason_taxonomy()

    empty = tmp_path / "empty"
    (empty / "reports").mkdir(parents=True)
    cmd = "em_peak_current_authority_check ."

    _, _, cls, tier = _flow_disposition(fcc, empty, cmd)
    # ZERO_DENOMINATOR since the counted-zero recogniser was corrected: this
    # gate READ an EM report and found no segments, so "the program errored"
    # was never true of it. The TIER is unchanged at INCOMPLETE, which is what
    # makes that correction a correction and not a route back to the skip
    # tier — see `test_issue1978_reason_taxonomy::
    # test_the_reclassification_greens_nothing`.
    assert cls == T.ZERO_DENOMINATOR, (cls, tier)
    assert cls not in T.SKIP_ELIGIBLE and tier == "INCOMPLETE", (cls, tier)

    orig = T.infer_nonverdict_reason
    try:
        T.infer_nonverdict_reason = lambda **kw: T.CAPABILITY_ABSENT
        fcc._reason_taxonomy.infer_nonverdict_reason = T.infer_nonverdict_reason
        _, out_r, _, tier_r = _flow_disposition(fcc, empty, cmd)
    finally:
        T.infer_nonverdict_reason = orig
        fcc._reason_taxonomy.infer_nonverdict_reason = orig
    assert out_r.startswith(fcc._VACUOUS_HINT_PREFIX), out_r
    assert tier_r == "VACUOUS_PASS", (
        "the two dispositions must remain DISTINGUISHABLE at the step tier; "
        "if this stops being true the assertion above has stopped measuring "
        f"anything: {tier_r}")


# ── the gate publishes its OWN reason class (#1978 producer duty) ──────────
def _em_report(tmp_path, project):
    """Run through the FLOW's own command form -- the one that names `--json`,
    because a class published into a report nobody reads is not published."""
    import flow_compliance_check as fcc
    cmd = ("em_peak_current_authority_check . "
           "--json reports/phase3/em_current_authority.json")
    ok, out = fcc._check_program_exit_zero(project, cmd)
    report = fcc._command_json_report(project, cmd)
    step = {"id": "probe", "name": "one clause",
            "gate": {"all_of": [{"program_exit_zero": cmd}]}}
    return ok, out, report, fcc.check_step(project, step, {}).status


def test_a_zero_denominator_is_declared_by_the_gate_not_inferred(tmp_path):
    """`_flow_reason_taxonomy`'s docstring: "Producers should publish an
    explicit ``reason_class`` whenever possible. The inference helper exists
    for legacy programs." This gate was a legacy program. It read 0
    peak-current figures and 0 supply authorities and left the flow to guess,
    and the fail-closed guess is EXECUTION_ERROR -- "the gate blew up", which
    it did not.

    Asserted through `report_reason_class`, the function the consumer uses, so
    the field name cannot drift out from under the publication."""
    import _flow_reason_taxonomy as T

    empty = tmp_path / "empty"
    (empty / "reports" / "phase3").mkdir(parents=True)
    ok, out, report, tier = _em_report(tmp_path, empty)
    assert ok, out
    assert report is not None and report["verdict"] == "INCOMPLETE", report
    assert T.report_reason_class(report) == T.ZERO_DENOMINATOR, report
    # the flow consumed what was published, not what it guessed
    assert "reason_class=ZERO_DENOMINATOR" in out, out


def test_the_instance_reason_survives_the_class(tmp_path):
    """A class is not a reason. `em_report_absent` says what happened on THIS
    run; ZERO_DENOMINATOR says which kind of non-verdict it is. Publishing the
    second must not consume the first -- a reader needs the class to know the
    program did not crash and the reason to know where to go next."""
    empty = tmp_path / "empty"
    (empty / "reports" / "phase3").mkdir(parents=True)
    _, _, report, _ = _em_report(tmp_path, empty)
    assert report["missing_authority_reason"] == "em_report_absent", report
    assert report["jmax_screen"]["skip_reason"] == "em_report_absent", report
    assert report["reason_class"] == "ZERO_DENOMINATOR", report


def test_publishing_the_class_changes_no_step_verdict(tmp_path):
    """THE CONTROL THAT MATTERS. ZERO_DENOMINATOR is not skip-eligible, so this
    publication cannot buy a green anywhere: the empty tree stays INCOMPLETE
    and a real comparison stays PASS. If either of these ever moves, the class
    being published has stopped being the honest one."""
    empty = tmp_path / "empty"
    (empty / "reports" / "phase3").mkdir(parents=True)
    assert _em_report(tmp_path, empty)[3] == "INCOMPLETE"

    real = _project(tmp_path / "real", peak="1.0e-06",
                    with_csv=True, with_jmax=True)
    ok, out, report, tier = _em_report(tmp_path, real)
    assert ok and tier == "PASS", (tier, out)
    # ...and a gate that DECIDED publishes no non-verdict class at all.
    assert "reason_class" not in report, report


def test_a_partial_read_is_not_declared_a_zero_denominator(tmp_path):
    """SCOPE. The INCOMPLETE tier is also reachable with peak currents in hand
    and no Jmax authority. That is a different state -- something WAS read --
    and this gate does not claim to know its class, so it publishes none and
    lets the fail-closed inference stand. Guards the publication from being
    widened into "every INCOMPLETE is a zero denominator"."""
    partial = _project(tmp_path / "partial", peak="1.0e-06")
    _, _, report, _ = _em_report(tmp_path, partial)
    assert report["verdict"] == "INCOMPLETE", report
    assert report["peak_currents_read"], report
    assert "reason_class" not in report, report
