#!/usr/bin/env python3
"""Regression for #834 — `agent_report_sha256_attestation_check` returned rc 0
for `VACUOUS_PASS`, and its umbrella keys the vacuous tier on rc 2.

THE TWO HALVES THAT DISAGREED
=============================
`flow_compliance_check` registers this gate in `_STRUCTURAL_RTL_GATES`. The
driver for that tuple, `_run_structural_rtl_gates`, reads the gate's EXIT CODE
and nothing else:

    rc 0 -> a PASS gate record  (counted by `_p0_passed_count`)
    rc 1 -> FAIL
    rc 2 -> a SKIP record, `skip_kind: input-missing`

The gate computed the verdict `VACUOUS_PASS`, printed it, and returned 0. So
"there was no report file" and "there were no canonical artefacts on disk"
both arrived at the umbrella as an ordinary executed PASS — the same record a
project gets when every SOF / GDS / netlist on disk is attested and every hash
matches.

MEASURED BEFORE THE FIX, through the real umbrella on a project holding one
trivial RTL file and a `reports/final_summary.md` with no hashes:

    {"name": "agent_report_sha256_attestation_check",
     "verdict": "PASS", "evidence": {"exit_code": 0}}

AFTER: verdict `SKIP`, `exit_code 2`, `skip_kind input-missing` — out of the
executed-PASS numerator, which is the point.

WHAT IS AND IS NOT ASSERTED HERE
================================
The two rc-2 cases are the fix. The rc-0 and rc-1 cases are CONTROLS and pass
identically before and after: a change that moved a real PASS or a real FAIL
would be a different bug, not this one. The stdout-sentinel test is a
no-regression pin — the second (weaker) channel `_stdout_signals_vacuous`
reads must survive, because `_check_program_exit_zero` on the per-step path
still uses it.

chip-AGNOSTIC: generic synthetic fixtures; no vendor / SKU / IC literal.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _vacuous_exit as _vx  # noqa: E402
import flow_compliance_check as F  # noqa: E402

_GATE = _PROGRAMS / "agent_report_sha256_attestation_check.py"
_GATE_NAME = "agent_report_sha256_attestation_check"

#: Bound for the launch in `_run_gate`, and it is NOT a round number picked by
#: feel. `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest
#: harness bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any one blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed.
_GATE_TIMEOUT_S = 60


def _run_gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_GATE), str(project)],
                          capture_output=True, text=True,
                          timeout=_GATE_TIMEOUT_S)


def _report(project: Path, body: str) -> None:
    (project / "reports").mkdir(parents=True, exist_ok=True)
    (project / "reports" / "final_summary.md").write_text(body,
                                                          encoding="utf-8")


def _artefact(project: Path, rel: str, body: bytes) -> str:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# The fix: both VACUOUS branches must reach the umbrella's vacuous channel.
# ---------------------------------------------------------------------------
def test_no_report_file_exits_with_the_vacuous_rc(tmp_path):
    """No canonical report anywhere — the gate opened nothing."""
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_gate(proj)
    assert r.returncode == _vx.RC_VACUOUS, (
        f"a gate that examined nothing must exit {_vx.RC_VACUOUS}, not "
        f"{r.returncode} — the umbrella reads the exit code and credits "
        f"rc 0 as an executed PASS. stdout={r.stdout!r}")


def test_no_canonical_artefacts_exits_with_the_vacuous_rc(tmp_path):
    """A report exists, but the project has produced no artefact to attest."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _report(proj, "# summary\n\nNo canonical artefacts yet.\n")
    r = _run_gate(proj)
    assert r.returncode == _vx.RC_VACUOUS, (
        f"pre-output project: examined nothing, must exit "
        f"{_vx.RC_VACUOUS}, got {r.returncode}. stdout={r.stdout!r}")


def test_the_vacuous_rc_is_the_one_the_umbrella_reads():
    """Pins the two sides of the contract to ONE constant, not to a literal.

    The defect was two literals in two files drifting apart. Reading the
    consumer's own convention constant is what stops a third one appearing.
    """
    assert _vx.RC_VACUOUS == 2
    assert _GATE_NAME in F._STRUCTURAL_RTL_GATES


# ---------------------------------------------------------------------------
# CONTROLS — these pass identically before and after the fix.
# ---------------------------------------------------------------------------
def test_attested_artefact_still_exits_zero(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    h = _artefact(proj, "phase2/stage2/synth/netlist.v",
                  b"module top(); endmodule\n")
    _report(proj, f"# summary\n\n| netlist | `sha256:{h}` |\n")
    r = _run_gate(proj)
    assert r.returncode == 0, (
        f"a real, fully-attested artefact set is a real PASS. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}")


def test_unattested_artefact_still_exits_one(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _artefact(proj, "phase2/stage2/synth/netlist.v",
              b"module top(); endmodule\n")
    _report(proj, "# summary\n\n| netlist | `sha256:"
                  + "0" * 64 + "` |\n")
    r = _run_gate(proj)
    assert r.returncode == 1, (
        f"an artefact on disk whose hash is not declared is a real FAIL. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}")


def test_stdout_vacuous_sentinel_channel_is_preserved(tmp_path):
    """The weaker channel must survive the fix, not be traded for the rc.

    `_check_program_exit_zero` (the per-step path) reads this line; the token
    is matched at LINE START, which is why `[VACUOUS_PASS]` would not do.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_gate(proj)
    assert F._stdout_signals_vacuous(r.stdout), (
        f"the line-start VACUOUS_PASS sentinel must still be emitted; "
        f"stdout={r.stdout!r}")


# ---------------------------------------------------------------------------
# The consequence, measured through the REAL umbrella (not re-derived).
# ---------------------------------------------------------------------------
def test_umbrella_no_longer_records_an_executed_pass_for_a_vacuous_run(
        tmp_path):
    """Drives `_run_structural_rtl_gates` and reads the gate's own record.

    This is the assertion the issue is about: the gate's conclusion has to
    arrive at the machine that publishes the X-of-Y figure, not merely be
    printed. Before the fix this record read
    `verdict=PASS, exit_code=0` on a project with no artefacts at all.
    """
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\n"
        "endmodule\n")
    _report(proj, "# summary\n\nNo canonical artefacts yet.\n")

    records = []
    F._run_structural_rtl_gates(proj, records_out=records)
    rec = next(r for r in records if r["name"] == _GATE_NAME)

    assert rec["verdict"] != "PASS", (
        "a gate that examined nothing must not hold a PASS record — that is "
        f"what puts it in the executed-PASS numerator. record={rec}")
    assert rec["verdict"] == "SKIP", rec
    assert rec["evidence"].get("exit_code") == _vx.RC_VACUOUS, rec
    assert rec["evidence"].get("skip_kind") == "input-missing", rec
    # And it must NOT be misread as the caller's own invocation defect: the
    # gate DID return a verdict about the design.
    assert rec["verdict"] != "NOT_INVOCABLE", rec
