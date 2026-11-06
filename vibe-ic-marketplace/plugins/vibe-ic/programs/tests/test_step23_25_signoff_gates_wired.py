#!/usr/bin/env python3
"""Steps 23 / 25 — the sign-off gates the flow DECLARED that nothing ran.

THE DEFECT, in two layers.

(1) NOT WIRED. `flow/phase1_phase2_phase3.yaml` declares four checkers across
    the two post-route sign-off steps — `sta_report_check`,
    `post_route_signoff_corner_check`, `sta_corner_record_completeness_check`
    (step 23) and `em_report_check` (step 25). No runner ever invoked any of
    them. The phase-3 orchestrators never load the flow yaml, and the only
    `flow_compliance_check` call in the runner chain is `design_one_shot_runner`
    at `--phase 2 --strict-structural`, whose verdict is filtered to `r.id ==
    'P0'` and never reaches stage3. The plugin's own
    `flow_gate_enforcement_audit` classified them AUDIT_ONLY.

(2) THE PRODUCER DROPPED ITS OUTPUT FLAG. `sta_report_check` and
    `em_report_check` rebuilt argv as `main([sys.argv[1], "--mode", <mode>])`,
    discarding the `--json <path>` the flow declares. Measured on the real
    completed run `campaign_pr427/spm/converge_ihp-sg13g2`:

        $ sta_report_check . --mode phase3/stage3/sta \
              --json reports/phase3/sta/post_route_summary.json
        rc=0        # and no file written

    `reports/phase3/sta/post_route_summary.json` is step 23's own
    `required_outputs` entry and this wrapper is its ONLY declared producer
    anywhere in the plugin, so a declared sign-off output had no producer at
    all. The same held for step 10's `pre_pnr_summary.json`.

    The dropped flag also hid an output-path COLLISION: step 25 declared its
    audit output at `reports/phase3/em.json`, which is where the PRODUCER
    (`step_canonicalize_artefacts` → `_emit_ir_em_reports`) writes the
    measurement the runner reads back as EM evidence. Honouring the flag
    without moving the path would have destroyed the measurement.

WHAT THIS COSTS — measured over the 14 published phase-3 run-roots under
`benchmark-data/ic` BEFORE wiring anything, the same corpus and evidence bar
#306 used:

    sta_report_check                      FAILs  9/14
    sta_corner_record_completeness_check  FAILs  6/14
    em_report_check                       FAILs  6/14
    post_route_signoff_corner_check       FAILs  2/14

Those are real findings. The sharpest: `sha256/clean_run_v1422_20260715`, a run
published as CLEAN, reports `setup worst-slack -1.710 ns at the sign-off
(max-RC) corner is VIOLATED` — verbatim the #147 defect step 23's gate comment
was written about, sitting in the corpus undetected because the gate that
detects it had no caller. On the real completed run all four return rc 0.

DIRECTION-1 GUARDS (`test_d1_*`) assert the behaviour that must NOT change and
hold on the pre-fix tree as well: the bare `<wrapper> <project>` call shape, the
NOT_APPLICABLE self-skips that make unconditional wiring safe, and the producer's
`reports/phase3/em.json` measurement staying untouched.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(_PROGRAMS))

# Padding to clear eda_report_audit's MIN_REPORT_BYTES anti-fabrication floor.
_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB

_STA_RPT = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\n"
    "WNS = 0.15 ns\nTNS = 0.0 ns\n"
    "slack (MET)\nsetup check: PASS\nhold check: PASS\n"
    "data arrival time: 2.34 ns\n" + _PAD
)

_EM_RPT = (
    "OpenROAD Electromigration Analysis\n"
    "EM lifetime: 10 years worst-case\n"
    "Javg = 2.5 mA/um  current density\n"
    "Jpeak = 8.1 mA/um  peak current\n"
    "RMS current: 3.2 mA/um\n" + _PAD
)

# The #147 shape: nominal-clean, sign-off corner violated.


#: CZT2-16 — THE INNER BOUND IS GONE, and the reasoning that justified it is
#: what removed it. It read: "every gate driven here is a pure report reader
#: that returns in well under a second (measured over the whole published
#: corpus: 70 invocations, none slower than a few hundred ms), so a small bound
#: is honest." A bound chosen because the work is short is a bound that only
#: ever fires when the HOST is slow, which is not a fact about the gate.
#: `_run_declared_signoff_gate` now supervises the child's own forward progress
#: and takes no `timeout` at all, so there is no argument left to pass.
#:
#: The concern the constant also served -- staying BELOW CI's `--timeout=180`
#: harness bound (#542), so a wedged test fails as one test instead of killing
#: the whole subset -- is unaffected: the harness bound is the harness's, and a
#: genuinely wedged gate is now stopped by the supervisor as a STALL, which is
#: a finding about the child rather than a number about the host.

#: The verdicts `phase3_one_shot_runner.main` treats as a releasing run.


def _run(prog: str, *args: str) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(_PROGRAMS / prog), *args],
                          capture_output=True, text=True)


def _project(tmp: Path) -> Path:
    """A minimal but tool-authentic post-route project."""
    sta = tmp / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(_STA_RPT)
    # The architectural residual reader consumes a declared post-route SPEF
    # report. A fixture claiming complete sign-off must supply that input;
    # missing-input behavior is tested separately and remains BLOCKED.
    (sta / "sta_spef_based.rpt").write_text(
        "STA_BASIS: POST_ROUTE_SPEF\n" + _STA_RPT)
    rpt = tmp / "reports" / "phase3"
    rpt.mkdir(parents=True)
    (rpt / "em.rpt").write_text(_EM_RPT)
    # A DECLARED DELIVERY ROUTE. The sixth declared sign-off gate
    # (`tapeout_precheck`, wired 2026-09-04) reads it to decide whether a
    # tape-out precheck applies at all, and a project with NO route is left
    # NOT_DETERMINED on purpose — 0.5ic failing is when a chip most needs that
    # step. The IP terminal keeps this a STA/EM fixture: no die, so no die to
    # check.
    st = tmp / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    (st / "NO_TEMPLATE.txt").write_text(
        "# submission_template_ingest: no template record\n"
        "STATUS: ABSENT — this fixture delivers an IP, not a die.\n")
    return tmp


# ===========================================================================
# (2) The producer honours the output flag the flow declares
# ===========================================================================






# ===========================================================================
# The DECLARATIONS the wrappers are driven by
# ===========================================================================
def _flow_invocations(program: str):
    """Every `<program> ...` command string declared in the flow yaml."""
    return re.findall(rf'"({re.escape(program)} [^"]*)"',
                      _FLOW.read_text(errors="replace"))


@pytest.mark.parametrize("program", ["sta_report_check", "em_report_check"])
def test_flow_declares_a_real_report_mode(program):
    """A `--mode` that is not an eda_report_audit choice is an argparse error
    (rc 2), which `flow_compliance_check` reads as VACUOUS_PASS — i.e. a
    broken declaration would buy PASS credit. Pin every declaration to a real
    mode so it cannot drift back."""
    import eda_report_audit  # noqa: WPS433
    valid = set(eda_report_audit.MODE_MAP)
    invocations = _flow_invocations(program)
    assert invocations, f"{program} is no longer declared in the flow"
    for cmd in invocations:
        toks = cmd.split()
        assert "--mode" in toks, cmd
        mode = toks[toks.index("--mode") + 1]
        assert mode in valid, (
            f"flow declares `--mode {mode}` for {program}; valid modes are "
            f"{sorted(valid)}")


def test_step25_audit_json_does_not_clobber_the_em_measurement():
    """`reports/phase3/em.json` is the PRODUCER's file — the measurement
    (`verdict: MEASURED`, max_segment_current_A) that phase3_one_shot_runner
    reads back as step 25's evidence. The audit verdict must go elsewhere or
    the checker destroys what it audits."""
    for cmd in _flow_invocations("em_report_check"):
        toks = cmd.split()
        assert "--json" in toks, cmd
        target = toks[toks.index("--json") + 1]
        assert target != "reports/phase3/em.json", (
            "step 25's audit would overwrite the EM measurement it audits")


# ===========================================================================
# (1) The gates are WIRED — a runner invokes them, so they can block
# ===========================================================================




















# ===========================================================================
# DIRECTION-1 GUARDS — must hold on the pre-fix tree too
# ===========================================================================


def test_d1_signoff_corner_check_self_skips_without_a_multicorner_report(tmp_path):
    """Why wiring it UNCONDITIONALLY is safe even though the yaml declares it
    under `condition_files_exist: [sta_spef_multicorner.rpt]`: on the
    condition's false branch the checker self-reports NOT_APPLICABLE and exits
    0, which is exactly what the unrun conditional gate produced."""
    proj = _project(tmp_path)
    r = _run("post_route_signoff_corner_check.py", str(proj))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT_APPLICABLE" in r.stdout


def test_d1_corner_record_check_self_skips_with_no_declared_corner(tmp_path):
    """Pre-phase3 and analog runs declare no sign-off corner; that must stay a
    rc 0 self-skip, not a FAIL invented out of an absent declaration."""
    r = _run("sta_corner_record_completeness_check.py", str(_project(tmp_path)))
    assert r.returncode == 0, r.stdout + r.stderr
