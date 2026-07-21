#!/usr/bin/env python3
"""Regression: an INCONCLUSIVE step-13 LEC must NOT be recorded as a bare PASS
in the flow_compliance matrix.

#208 correctly stopped calling equiv_induct non-convergence a false
LEC_NOT_EQUIVALENT and re-classed it INCONCLUSIVE. But `lec_equivalence_check`
then returned **0** on that path, reasoning that INCONCLUSIVE must not be a hard
FAIL that cascade-marks downstream steps MISSING (true), and that
`result.passed` staying False in the JSON body kept it "a visible non-PASS"
(false).

It was not visible. Step 13's gate in flow/phase1_phase2_phase3.yaml is

    program_exit_zero: "lec_equivalence_check . --json reports/lec_equivalence_check.json"

and `flow_compliance_check._check_program_exit_zero` maps rc==0 -> passed=True
with NO downgrade tier attached. Only rc==2 (VACUOUS_PASS) and rc==3 + the
`PASS_WITH_WAIVERS` stdout sentinel (WAIVED-DEFERRED) are demoted. So an
INCONCLUSIVE LEC was booked as a BARE PASS: the authoritative compliance table
asserted "RTL == post-DFT netlist: PASS" about a netlist that nothing had proven
equivalent. That is strictly worse than the visible FAIL it replaced, and is the
exact false-clean lec_equivalence_check's own docstring exists to prevent.

Fix: INCONCLUSIVE exits 3 and prints the `PASS_WITH_WAIVERS` sentinel as its
LAST and SHORT line, so flow_compliance promotes step 13 to WAIVED-DEFERRED --
visible, excluded from a strict PASS headline, and still not a cascading FAIL.
Same idiom already used by cpu_functional_oracle_waiver_check.

chip-AGNOSTIC: pure verdict-shape fixtures; no chip/PDK/vendor literal.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as fcc  # noqa: E402

_CHECKER = _PROGRAMS / "lec_equivalence_check.py"

# The ibex #208 signature: a COMPLETED miter, points left unproven, and
# critically ZERO counterexamples -- equiv_induct simply did not converge.
INCONCLUSIVE_NONCONVERGENCE = (
    '{"verdict":"INCONCLUSIVE","equivalent":false,"proven_points":6350,'
    '"unproven_points":7259,"non_equivalent_points":0,"compared_points":13609}')
# A frontend parse-abort / wall-clock kill: nothing was decided at all.
INCONCLUSIVE_PARSE_ABORT = (
    '{"verdict":"INCONCLUSIVE","equivalent":false,"proven_points":0,'
    '"unproven_points":0,"non_equivalent_points":0,"compared_points":0}')
# A REAL non-equivalence, witnessed by a counterexample.
REAL_MISMATCH = (
    '{"verdict":"INCONCLUSIVE","equivalent":false,"proven_points":6350,'
    '"unproven_points":7259,"non_equivalent_points":1,"compared_points":13609}')
# An ordinary FAIL with no non-convergence evidence.
PLAIN_FAIL = (
    '{"verdict":"FAIL","equivalent":false,"proven_points":6350,'
    '"unproven_points":7259,"non_equivalent_points":0,"compared_points":13609}')
CLEAN_PASS = (
    '{"verdict":"PASS","equivalent":true,"proven_points":13609,'
    '"unproven_points":0,"non_equivalent_points":0,"compared_points":13609}')


def _run(tmp_path, lec_json_body):
    """Run the checker exactly as the step-13 gate does, and resolve the tier
    the way flow_compliance_check itself resolves it -- including the real
    stdout[-300:] truncation window, which a sentinel must survive."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "lec.json").write_text(lec_json_body)
    proc = subprocess.run([sys.executable, str(_CHECKER), str(tmp_path)],
                          capture_output=True, text=True)
    snippet = (proc.stdout[-300:] + "\n" + proc.stderr[-300:]).strip()
    if proc.returncode == 0:
        tier = "PASS"
    elif proc.returncode == 2:
        tier = "VACUOUS_PASS"
    elif (proc.returncode == fcc._WAIVER_EXIT_CODE
          and fcc._stdout_signals_waiver(snippet)):
        tier = "WAIVED-DEFERRED"
    else:
        tier = "FAIL"
    return proc.returncode, tier


@pytest.mark.parametrize("body,label", [
    (INCONCLUSIVE_NONCONVERGENCE, "equiv_induct non-convergence"),
    (INCONCLUSIVE_PARSE_ABORT, "frontend parse-abort / budget kill"),
])
def test_inconclusive_is_waived_deferred_never_a_bare_pass(tmp_path, body,
                                                           label):
    """The whole point: INCONCLUSIVE must never read as PASS to the gate."""
    rc, tier = _run(tmp_path, body)
    assert tier != "PASS", (
        f"{label}: INCONCLUSIVE was booked as a BARE PASS -- the compliance "
        f"matrix would assert RTL==netlist equivalence that nothing proved")
    assert rc == fcc._WAIVER_EXIT_CODE, f"{label}: want rc=3, got rc={rc}"
    assert tier == "WAIVED-DEFERRED", f"{label}: got tier={tier}"


def test_sentinel_survives_the_300_char_truncation_window(tmp_path):
    """The sentinel must be the LAST and a SHORT line.

    flow_compliance reads only stdout[-300:] and requires the token at
    line-START. A long single-line sentinel gets sliced mid-string, the prefix
    falls outside the window, and the gate silently degrades to a bare FAIL.
    This asserts the property directly rather than trusting line ordering.
    """
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "lec.json").write_text(INCONCLUSIVE_NONCONVERGENCE)
    proc = subprocess.run([sys.executable, str(_CHECKER), str(tmp_path)],
                          capture_output=True, text=True)
    window = proc.stdout[-300:]
    assert fcc._stdout_signals_waiver(window), (
        "PASS_WITH_WAIVERS sentinel did not survive the trailing-300-char "
        f"window flow_compliance actually inspects; window was:\n{window!r}")


@pytest.mark.parametrize("body,label", [
    (REAL_MISMATCH, "a recorded counterexample"),
    (PLAIN_FAIL, "a plain FAIL verdict"),
])
def test_real_non_equivalence_still_hard_fails(tmp_path, body, label):
    """NO-LEAK: the waiver tier must never launder a genuine mismatch."""
    rc, tier = _run(tmp_path, body)
    assert rc == 1, f"{label}: want rc=1 (hard FAIL), got rc={rc}"
    assert tier == "FAIL", f"{label}: got tier={tier}"


def test_clean_pass_still_passes(tmp_path):
    """A genuinely proven-equivalent design is unaffected."""
    rc, tier = _run(tmp_path, CLEAN_PASS)
    assert rc == 0
    assert tier == "PASS"
