#!/usr/bin/env python3
"""DFT_FCC / 11-d7 — a disclosed capability-gap skip on a SIGN-OFF-BAR step
must reach the Overall verdict.

MEASURED on the reference run (spm × ihp-sg13g2, host 192.168.1.120,
~/campaign_pr427/spm/converge_ihp-sg13g2): step 11 (DFT insertion / ATPG
sign-off coverage) resolves to SKIPPED-CONDITION with all three of its
declared outputs absent, and the verdict line never mentions it. In the
verdict path `SKIPPED-CONDITION` appeared at exactly ONE place — subtracted
from `total_required` — so it could not make a run non-green. That run is FAIL
only because of an unrelated P0 structural gate; with P0 clean it landed on
PASS_WITH_WAIVERS with the DFT sign-off gap invisible.

Meanwhile the module ALREADY enumerates step 11 in
`_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`, and the
PASS_WITH_OPEN_SOURCE_CONSTRAINTS tier built for exactly this scenario
(explicit deferral list + review_required=true) never fired, because it only
runs on an already-FAIL verdict and step 11 was in neither the failing nor the
missing bucket.

These tests drive the real CLI over a synthetic flow definition (--flow-def),
so they exercise the actual verdict composition rather than a helper.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "flow_compliance_check.py"
sys.path.insert(0, str(PROGRAMS))
import flow_compliance_check as fcc  # noqa: E402

_TABLE = fcc._OPEN_SOURCE_CONTAINER_BLOCKED_STEPS

# A minimal stage-3 flow: the two PASS_WITH_OPEN_SOURCE_CONSTRAINTS
# prerequisites (steps 6 and 36) plus one step under test. Everything is
# stage3 so `--stage 3` also switches the P0 structural umbrella off, keeping
# the fixture about the verdict composition and nothing else.
_FLOW_TMPL = """\
steps:
  - id: 6
    name: "FPGA early prototype + verification report audit"
    stage: stage3
    gate:
      all_of:
        - files_exist: ["fpga/ok6.txt"]
  - id: 36
    name: "FPGA final sign-off"
    stage: stage3
    gate:
      all_of:
        - files_exist: ["fpga/ok36.txt"]
  - id: {sid}
    name: "step under test"
    stage: stage3
    required_outputs:
      - "phase2/stage2/dft/coverage.json"
    gate:
      all_of:
        - files_exist: ["phase2/stage2/dft/coverage.json"]
"""

# The runner-emitted disclosed-skip marker, in the exact shape the #675 strict
# promotion requires (self-skip verdict + non-empty capability_flag +
# skips_required_output naming this step's absent canonical output).
_SKIP_NOTE = {
    "verdict": "SKIPPED-CONDITION",
    "capability_flag": "cap:atpg_signoff_coverage",
    "skips_required_output": "phase2/stage2/dft/coverage.json",
    "reason": "OSS Fault ATPG could not measure sign-off stuck-at coverage",
}


def _mk(tmp_path: Path, sid, *, prereqs=True, flow_tmpl: str = _FLOW_TMPL):
    proj = tmp_path / "proj"
    dft = proj / "phase2/stage2/dft"
    dft.mkdir(parents=True)
    (proj / "fpga").mkdir(parents=True)
    if prereqs:
        (proj / "fpga/ok6.txt").write_text("")
        (proj / "fpga/ok36.txt").write_text("")
    (dft / "dft_atpg_not_run.json").write_text(json.dumps(_SKIP_NOTE))
    flow = tmp_path / "flow.yaml"
    flow.write_text(flow_tmpl.format(sid=sid))
    return proj, flow


def _run(proj: Path, flow: Path, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), str(proj), "--flow-def", str(flow),
         "--stage", "3", *extra],
        capture_output=True, text=True)


def _overall(out: str) -> str:
    for line in out.splitlines():
        if line.startswith("Overall:"):
            return line.split()[1]
    raise AssertionError(f"no Overall line in:\n{out}")


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------
def test_signoff_bar_self_skip_is_not_a_clean_pass(tmp_path):
    """Step 11 is listed in `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`. A
    SKIPPED-CONDITION on it must not leave the run reported as a bare PASS."""
    proj, flow = _mk(tmp_path, 11)
    r = _run(proj, flow)
    assert "SKIPPED-CONDITION" in r.stdout, r.stdout
    assert _overall(r.stdout) == "PASS_WITH_OPEN_SOURCE_CONSTRAINTS", r.stdout
    # named, with the review flag the tier exists to carry
    assert "Step 11" in r.stdout
    assert "DEFERRED" in r.stdout


def test_signoff_bar_self_skip_stays_in_the_required_denominator(tmp_path):
    """It used to be subtracted from `total_required`, so the X/Y
    executed-PASS metric hid the unmet requirement in Y as well as in X
    (2/2, not 2/3)."""
    proj, flow = _mk(tmp_path, 11)
    r = _run(proj, flow)
    assert "(2/3 executed PASS" in r.stdout, r.stdout


def test_deferral_is_recorded_in_the_audit_json(tmp_path):
    proj, flow = _mk(tmp_path, 11)
    r = _run(proj, flow)
    assert r.returncode == 0, r.stdout + r.stderr
    audit = json.loads(
        (proj / "reports/audit/phase23_completion_audit.json").read_text())
    assert audit["verdict"] == "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"
    skipped = audit["open_source_blocked_self_skipped_steps"]
    assert [e["step_id"] for e in skipped] == [11]
    assert skipped[0]["review_required"] is True
    assert any(d["step_id"] == 11 and d["review_required"] is True
               for d in audit["open_source_constraints_deferrals"])


#: The table's DIGITAL step ids — the population this arm is keyed on, DERIVED
#: from the table instead of re-typed beside it.
#:
#: It was `[5, 11, 12, 13]`, hand-written. MEASURED on live main 7903c1972305
#: (2026-09-03, pinned image sha256:66c33ff2..., host load 24.0):
#:
#:     FAILED test_every_oss_blocked_signoff_step_is_covered[5]
#:
#: `2a9d21368d` (#1974, "close formal property authoring gap") DELIBERATELY
#: removed key 5 — "Formal verification harness (SymbiYosys IS in container)"
#: — from `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`, because SymbiYosys is in the
#: image and the entry was a false open-source reprieve. Only the `[5]` cell
#: was red; 11, 12 and 13 still pass. Putting 5 back would REOPEN the reprieve
#: #1974 closed, and this arm's own docstring already said the bucket is keyed
#: on the EXISTING table — so it now reads the table.
#:
#: The analog/mixed entries are string ids on a different track and the DFT
#: -shaped fixture below cannot express them; the digital ids are exactly the
#: ones it can, and `test_the_derived_oss_population_is_not_vacuous` refuses a
#: derivation that has silently emptied or started dropping numeric keys.
_OSS_BLOCKED_DIGITAL_STEPS = sorted(k for k in _TABLE if isinstance(k, int))


def test_the_derived_oss_population_is_not_vacuous():
    """A parametrize derived from a table is a green with no cases in it the
    day the derivation breaks. Both halves are checked: the population is
    non-empty, and it drops no numeric key the table carries."""
    assert _OSS_BLOCKED_DIGITAL_STEPS, (
        "the OSS-blocked digital population is EMPTY, so "
        "test_every_oss_blocked_signoff_step_is_covered runs zero cases and "
        "passes vacuously")
    numeric = {k for k in _TABLE if not isinstance(k, str)}
    assert set(_OSS_BLOCKED_DIGITAL_STEPS) == numeric, (
        f"the derivation dropped numeric table keys: "
        f"{sorted(numeric - set(_OSS_BLOCKED_DIGITAL_STEPS), key=str)}")


@pytest.mark.parametrize("sid", _OSS_BLOCKED_DIGITAL_STEPS)
def test_every_oss_blocked_signoff_step_is_covered(tmp_path, sid):
    """The bucket is keyed on the EXISTING table, so it must behave the same
    for the table's other sign-off entries — no per-step special-casing."""
    assert sid in _TABLE, f"fixture stale: step {sid} left the OSS-blocked table"
    proj, flow = _mk(tmp_path, sid)
    r = _run(proj, flow)
    assert _overall(r.stdout) == "PASS_WITH_OPEN_SOURCE_CONSTRAINTS", r.stdout


# ---------------------------------------------------------------------------
# DIRECTION-1 GUARDS — what must NOT change
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sid", [27, 30])
def test_ordinary_step_self_skip_stays_cost_free(tmp_path, sid):
    """Most SKIPPED-CONDITION steps in a real run (22 of them on the
    reference run) are legitimately inapplicable. Steps NOT in
    `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` must keep their current cost-free
    behaviour — this is the blanket-policy change the fix deliberately does
    NOT make."""
    assert sid not in _TABLE, (
        f"fixture stale: step {sid} joined the OSS-blocked table; pick another")
    proj, flow = _mk(tmp_path, sid)
    r = _run(proj, flow)
    assert "SKIPPED-CONDITION" in r.stdout, r.stdout
    assert _overall(r.stdout) == "PASS", r.stdout
    assert "(2/2 executed PASS" in r.stdout, r.stdout


_FLOW_CONDITION_NA = """\
steps:
  - id: 6
    name: "FPGA early prototype + verification report audit"
    stage: stage3
    gate:
      all_of:
        - files_exist: ["fpga/ok6.txt"]
  - id: 36
    name: "FPGA final sign-off"
    stage: stage3
    gate:
      all_of:
        - files_exist: ["fpga/ok36.txt"]
  - id: {sid}
    name: "step under test"
    stage: stage3
    condition:
      files_exist: ["phase1/analog/analog_block_list.json"]
    required_outputs:
      - "phase2/stage2/dft/coverage.json"
    gate:
      all_of:
        - files_exist: ["phase2/stage2/dft/coverage.json"]
"""


@pytest.mark.parametrize("sid", [11, 12, 13])
def test_inapplicable_signoff_step_stays_cost_free(tmp_path, sid):
    """DIRECTION-1 GUARD — the one that nearly went wrong.

    Keying ONLY on `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` over-reaches: that
    table also lists A3-A9 and M1-M4, and on the pure-digital reference run
    those resolve to SKIPPED-CONDITION for reasons that are NOT deferred
    sign-off — "analog track skipped via --skip-analog" and "condition not
    met" (no analog block list on a digital chip). Measured: keying on the
    table alone flagged 13 steps as deferred sign-off where only 3 were.

    A step whose applicability CONDITION is unmet is genuinely inapplicable
    and must keep costing nothing.
    """
    assert sid in _TABLE
    proj, flow = _mk(tmp_path, sid, flow_tmpl=_FLOW_CONDITION_NA)
    r = _run(proj, flow)
    assert "SKIPPED-CONDITION" in r.stdout, r.stdout
    assert _overall(r.stdout) == "PASS", r.stdout
    assert "SIGN-OFF step(s) SELF-SKIPPED" not in r.stdout, r.stdout


def test_clean_run_with_no_skip_is_still_plain_pass(tmp_path):
    """DIRECTION-1 GUARD — nothing changes for a run with no self-skip."""
    proj, flow = _mk(tmp_path, 11)
    (proj / "phase2/stage2/dft/coverage.json").write_text('{"coverage_pct": 99}')
    r = _run(proj, flow)
    assert _overall(r.stdout) == "PASS", r.stdout
    assert r.returncode == 0


def test_promotion_still_exits_zero_so_ci_gating_is_unchanged(tmp_path):
    """DIRECTION-1 GUARD — PASS_WITH_OPEN_SOURCE_CONSTRAINTS is a recognised
    tier that exits 0. Routing the skip through it must not start failing CI
    for projects that were passing."""
    proj, flow = _mk(tmp_path, 11)
    r = _run(proj, flow)
    assert r.returncode == 0, r.stdout + r.stderr


def test_lenient_mode_tolerates_the_skip_exactly_like_missing(tmp_path):
    """DIRECTION-1 GUARD — the bucket is wired into the STRICT `ok` only,
    alongside `missing`, which lenient mode already tolerates."""
    proj, flow = _mk(tmp_path, 11)
    r = _run(proj, flow, "--lenient")
    assert _overall(r.stdout) == "PASS", r.stdout


def test_prerequisite_guard_still_holds(tmp_path):
    """DIRECTION-1 GUARD — the tier's own precondition (the chip is
    engineering-complete: steps 6 and 36 PASS) must still gate the promotion,
    so this never upgrades a structurally incomplete run.

    NOTE the consequence, which is deliberate and REDDER: when the
    prerequisites are not met the promotion cannot fire, and an unmet
    sign-off bar can no longer be reported as a green PASS either — the run
    is FAIL, and the skip is named on the verdict line."""
    proj, flow = _mk(tmp_path, 11, prereqs=False)
    r = _run(proj, flow)
    assert _overall(r.stdout) == "FAIL", r.stdout
    assert r.returncode == 1
    assert "SIGN-OFF step(s) SELF-SKIPPED" in r.stdout, r.stdout
