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
import hashlib
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
    em = {"tool": "psm", "segments_analysed": 4,
          "max_segment_current_A": float(peak), "verdict": "MEASURED"}
    if with_csv:
        (proj / "reports" / "phase3" / "em_segments.csv").write_text(
            CSV.format(peak=peak))
        # The two PSM edges sit on one real, same-net DEF special wire.
        # This is the width authority; the Jmax table's default is not.
        dp = proj / "phase3" / "stage3" / "pnr" / "routed.def"
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text("UNITS DISTANCE MICRONS 1000 ;\nSPECIALNETS 1 ;\n"
                      "- PWRNET + USE POWER + ROUTED mA 140 + SHAPE STRIPE "
                      "( 0 0 ) ( 2000 0 ) ;\nEND SPECIALNETS\n")
        em.update({"power_nets": ["PWRNET"],
                   "subject_def": "phase3/stage3/pnr/routed.def",
                   "subject_def_sha256": hashlib.sha256(dp.read_bytes()).hexdigest()})
    (proj / "reports" / "phase3" / "em.json").write_text(json.dumps(em))
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
    # R-0915-85 — `INCOMPLETE:` here is the GATE PROGRAM's own refusal token,
    # not a step status: this gate is one of the ~450 checkers whose stdout
    # `flow_compliance_check` reads, and that vocabulary is not this batch's.
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
    # R-0915-85 — `INCOMPLETE:` here is the GATE PROGRAM's own refusal token,
    # not a step status: this gate is one of the ~450 checkers whose stdout
    # `flow_compliance_check` reads, and that vocabulary is not this batch's.
    assert any(l.lstrip().startswith("INCOMPLETE")
               for l in r.stdout.splitlines())
    assert "read 0 peak-current figure(s)" in r.stdout




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




def _reason_taxonomy():
    import _flow_reason_taxonomy as T
    return T




# ── the gate publishes its OWN reason class (#1978 producer duty) ──────────
