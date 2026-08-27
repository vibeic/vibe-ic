#!/usr/bin/env python3
"""Step 32: the audit must not describe a repair that was never applied.

v1.7.64 made Step 32 fail-close — a HARD non-timing sign-off failure (IR drop,
PERC, PV, EM, SI) forces ``repair_needed=True`` so the step can no longer certify
"no repair needed" over a failed power-integrity domain. That fix DELIBERATELY
leaves ``timing_repair_needed=False``; its own docstring says the timing-repair
TCL never fires and therefore "never fabricates a repaired ``repair_log.json``".

So in exactly that state ``changes`` is empty and ``re_verified`` is false BY
DESIGN — and ``postroute_timing_repair_audit`` reported both unconditionally:

    ERROR EMPTY_CHANGES   repair_log.json 'changes' array is missing or empty
    ERROR NOT_REVERIFIED  repair applied but re_verified is false
                          — must re-run sign-off

Nothing was applied. Both probes are STRUCTURAL ("is the array populated?",
"is the flag set?") and both are ADJACENT to the question the audit exists to
answer: did the repair loop do the right thing? Reported this way they assert an
repair that never happened and send the reader to re-run sign-off STA — the one
action that cannot clear the step, because timing is not what failed. The
measured cost was a full convergence round taking "re-run sign-off STA after
the repair" as its next action on a design carrying +6.28 ns of setup margin.

WHAT THIS CHANGE IS NOT: it is not a relaxation. The repair is still required, the
design is still failing, the finding is still an ERROR, ``pass`` is still
False and Step 32 still goes red. ``test_still_red_*`` below is the guard on
that, and it is written to pass in BOTH directions — before the fix and after
— so a future edit that tightens this branch until the step goes green fails
here rather than shipping.

chip-AGNOSTIC: canonical record paths and keys only; no design, PDK, vendor or
process token anywhere in this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import postroute_timing_repair_audit as ELA  # noqa: E402
import postroute_timing_repair_decision as ETD  # noqa: E402

_STATUS_GEN = _PROGRAMS_DIR / "postroute_timing_repair_status_gen.py"
_LOOP_AUDIT = _PROGRAMS_DIR / "postroute_timing_repair_audit.py"

_CLEAN_MCORNER_STANCE = {
    "multi_process_corner": True,
    "report": "reports/phase3/sta_mcorner_ocv.rpt",
    "violated_corners": [],
    "setup_worst_slack_ns": 6.28,
    "hold_worst_slack_ns": 0.12,
}


def _run(prog: Path, project: Path):
    proc = subprocess.run([sys.executable, str(prog), str(project)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _nontiming_project(tmp_path: Path) -> Path:
    """A project whose TIMING is clean at every corner but whose IR-drop and
    PERC sign-off both hard-FAIL — driven through the REAL producers, so the
    records under audit are the ones the flow actually writes, not fixtures
    hand-shaped to match the assertion."""
    (tmp_path / "phase3/stage3/sta").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage3/postroute_timing_repair").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/phase2/gates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage3/sta/post_route_timing.rpt").write_text(
        "worst slack MET\ntns 0.00\nwns 6.28\n")
    (tmp_path / "reports/phase3/mcorner_ocv_stance.json").write_text(
        json.dumps(_CLEAN_MCORNER_STANCE))
    (tmp_path / "reports/phase3/ir_drop.json").write_text(json.dumps(
        {"tool": "openroad-psm", "worst_ir_pct_vdd": 15.056,
         "budget_pct_vdd": 10.0, "verdict": "FAIL"}))
    (tmp_path / "reports/phase2/gates/perc_signoff.json").write_text(
        json.dumps({"program": "perc_signoff_check", "verdict": "FAIL"}))
    rc, out = _run(_STATUS_GEN, tmp_path)
    assert rc == 0, out
    # The decision record is written by the runner's
    # `step_canonicalize_artefacts` from `postroute_timing_repair_decision.decide(...)`,
    # not by postroute_timing_repair_status_gen. Produce it the same way, through the REAL
    # decision function, so the record under audit is the one the flow writes.
    decision = ETD.decide(tmp_path / "reports/phase3/mcorner_ocv_stance.json",
                          True, project=tmp_path)
    # `action` is stamped by the runner, not by `decide`, under the runner's own
    # condition (phase3_one_shot_runner: `if not
    # _repair_decision["timing_repair_needed"]: ... = "repair_required_non_timing"`).
    # Reproduced verbatim rather than hard-coded, so a change to that condition
    # upstream shows up here instead of being masked by a constant.
    if not decision["timing_repair_needed"]:
        decision["action"] = "repair_required_non_timing"
    (tmp_path / "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json").write_text(
        json.dumps(decision))
    return tmp_path


def _codes(findings) -> list:
    return [f.category for f in findings]


# ===========================================================================
# FORWARD — fails against the byte-identical pre-fix file, passes after
# ===========================================================================
def test_nontiming_block_is_named_not_described_as_an_applied_repair(tmp_path):
    proj = _nontiming_project(tmp_path)

    # Precondition: this really is the v1.7.64 fail-close state, taken from the
    # producers' own records rather than assumed.
    decision = json.loads(
        (proj / "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json").read_text())
    assert decision["timing_repair_needed"] is False
    assert decision["repair_needed"] is True
    assert decision["action"] == "repair_required_non_timing"

    findings, stats = ELA.audit(proj)
    codes = _codes(findings)

    assert "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF" in codes, (
        "the audit must name the domains that actually block this step")
    assert "NOT_REVERIFIED" not in codes, (
        "no repair was applied, so 'repair applied but re_verified is false' is a "
        "false statement about this run")
    assert "EMPTY_CHANGES" not in codes, (
        "'changes' is empty by design here — v1.7.64 forbids the timing "
        "repair from firing at all")

    msg = " ".join(f.message for f in findings)
    assert "ir_drop" in msg and "perc_signoff" in msg, (
        "the blocking domains must be named, so the next action is derivable "
        "from the finding alone")
    assert set(stats.get("nontiming_block_domains") or []) == {
        "ir_drop", "perc_signoff"}


# ===========================================================================
# REVERSE 1 — the anti-greening guard. Passes in BOTH directions.
# ===========================================================================
def test_still_red_the_step_does_not_go_green(tmp_path):
    """The whole point of the fix is that the DIAGNOSIS changes and the
    VERDICT does not. If a future edit narrows this branch until the errors
    reach zero — the exact 'tighten the filter until the count hits zero'
    failure this repo has already paid for once — this test is what stops it."""
    proj = _nontiming_project(tmp_path)

    findings, _ = ELA.audit(proj)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert errors, "a blocked, unfixed sign-off failure must still be an ERROR"

    rc, out = _run(_LOOP_AUDIT, proj)
    assert rc != 0, (
        "Step 32 must stay RED while IR drop and PERC are failing:\n" + out)
    payload = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert payload["summary"]["pass"] is False
    assert payload["summary"]["errors_count"] >= 1


# ===========================================================================
# REVERSE 2 — a genuine unapplied/unverified TIMING repair is untouched
# ===========================================================================
def test_real_timing_repair_still_reports_empty_changes_and_not_reverified(
        tmp_path):
    """No non-timing block => every pre-existing finding fires exactly as
    before. This is the case the new branch must never swallow."""
    (tmp_path / "phase3/stage3/postroute_timing_repair").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json").write_text(
        json.dumps({"repair_needed": True, "timing_repair_needed": True,
                    "action": "repair_required_timing", "nontiming_failures": [],
                    "setup_worst_slack_ns": -0.42}))
    (tmp_path / "phase3/stage3/postroute_timing_repair/repair_log.json").write_text(json.dumps(
        {"verdict": "REPAIR_REQUIRED", "timing_repair_needed": True,
         "changes": [], "re_verified": False}))

    codes = _codes(ELA.audit(tmp_path)[0])
    assert "EMPTY_CHANGES" in codes
    assert "NOT_REVERIFIED" in codes
    assert "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF" not in codes


# ===========================================================================
# REVERSE 3 — fail-open: a record that DOES NOT SAY SO is unchanged
# ===========================================================================
@pytest.mark.parametrize("decision,why", [
    ({"repair_needed": True, "nontiming_failures": [{"domain": "ir_drop"}]},
     "no `timing_repair_needed` and no action: a record that says nothing must "
     "not be read as saying 'no timing repair was needed'"),
    ({"repair_needed": True, "timing_repair_needed": None, "action": None,
      "nontiming_failures": [{"domain": "ir_drop"}]},
     "an explicitly NULL timing_repair_needed is still not a False"),
    ({"repair_needed": True, "timing_repair_needed": True, "action": None,
      "nontiming_failures": [{"domain": "ir_drop"}]},
     "a TIMING repair that also has a non-timing failure beside it is a real "
     "unapplied timing repair and must keep its findings"),
    ({"repair_needed": True, "timing_repair_needed": False, "action":
      "repair_required_non_timing", "nontiming_failures": []},
     "the action alone, with NO domain to name, cannot produce an actionable "
     "finding — so it must not displace the ones that exist"),
])
def test_fail_open_records_are_byte_identical_to_before(
        tmp_path, decision, why):
    (tmp_path / "phase3/stage3/postroute_timing_repair").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json").write_text(
        json.dumps(decision))
    (tmp_path / "phase3/stage3/postroute_timing_repair/repair_log.json").write_text(json.dumps(
        {"verdict": "REPAIR_REQUIRED", "changes": [], "re_verified": False}))

    codes = _codes(ELA.audit(tmp_path)[0])
    assert "EMPTY_CHANGES" in codes, why
    assert "NOT_REVERIFIED" in codes, why
    assert "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF" not in codes, why


# ===========================================================================
# REVERSE 4 — the helper is pure and does not invent domains
# ===========================================================================
def test_helper_returns_empty_for_absent_records():
    assert ELA._nontiming_block_domains({}, None) == []
    assert ELA._nontiming_block_domains({}, {}) == []
    # a malformed nontiming_failures entry contributes no domain, and a record
    # whose ONLY entries are malformed does not qualify
    assert ELA._nontiming_block_domains(
        {}, {"action": "repair_required_non_timing",
             "nontiming_failures": ["ir_drop", None, 7]}) == []


def test_helper_dedupes_domains_named_by_both_records():
    """The same domain appears in the decision AND in the log; a repeated name
    reads as two separate failures."""
    rec = {"action": "repair_required_non_timing",
           "nontiming_failures": [{"domain": "ir_drop"},
                                  {"domain": "ir_drop"},
                                  {"domain": "perc_signoff"}]}
    assert ELA._nontiming_block_domains({}, rec) == ["ir_drop",
                                                     "perc_signoff"]
