"""A compliance receipt says which scope it judged — not "all" over one stage.

R-0915-147. `flow_compliance_check` stamped its receipt with `args.phase`, which
DEFAULTS to "all", and recorded the `--stage` / `--stage-id` narrowing NOWHERE. So a
stage-scoped pass published a whole-flow label over a single stage's population.

MEASURED on spm run22, READ-ONLY, on five shipped receipts:

    reports/phase1/gates/stage_phase1_compliance.json    2 steps   phase="all"
    reports/phase2/gates/stage1_compliance.json          7 steps   phase="all"
    reports/phase2/gates/stage2_compliance.json         13 steps   phase="all"
    reports/phase3/gates/stage3_compliance.json         20 steps   phase="all"
    reports/phase3/gates/stage4_compliance.json         10 steps   phase="all"

— every one stamped whole-flow, none carrying a `stage` key at all, while the flow
has 70 steps. That is how a reader comparing a stage's own stdout against its receipt
cannot tell whether the two describe the same population, which is the disagreement
this was found through (a stage1 pass printing PASS beside a receipt saying FAIL).

The receipt now carries the scope it actually judged: the phase and stage arguments
as given, the step ids in the population, the flow's own total, and whether the
population WAS the whole flow — derived against the flow size read BEFORE narrowing,
never from `args.phase`, because the argument is the thing that was already wrong.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def _flow_step_ids() -> list:
    doc = yaml.safe_load(FLOW.read_text())
    return [str(s.get("id")) for s in doc["steps"] if isinstance(s, dict)]


@pytest.fixture()
def project(tmp_path):
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text("module d(); endmodule\n")
    return tmp_path














# ── R-0915-150: a pass's own receipt, and nobody else's ─────────────────────
#
# MEASURED END TO END with icspm5's three-pass driver on a `cp -a` of spm run22
# (stage1 receipt present at 08:52:02), three sequential top-level invocations:
#
#   PLAIN MAIN f7d03cc8b                    THIS TIP
#     stage1 exits 12:58:10                   stage1 exits 13:07:58
#       its own receipt written 12:58:08        its own receipt written 13:07:57
#       overall NOT_MEASURED                   overall NOT_MEASURED
#     stage2 pass REPUBLISHES it 12:58:50     stage2 pass leaves it alone
#       overall becomes FAIL      (pass 2)    stage4 pass leaves it alone
#     stage4 pass republishes     (pass 3)    every receipt: republished = False,
#       12:59:45                               written inside its OWN pass's window
#     canonical completion audit REWRITTEN    canonical audit BYTE-IDENTICAL to the
#       by the scoped passes (md5 differs)      original; each scoped pass writes
#                                               its own .scoped-<stage>.json
#
# So a reader of main's stage1 receipt gets FAIL for a stage whose own pass said
# NOT_MEASURED, authored while a different stage was being judged. The mechanism is
# the R-0915-138 republish — mine — reaching across invocations it was never about.










def test_phase3_does_not_carry_a_scoped_audit_as_the_runs(tmp_path):
    """READER 3: `_derive_headline_verdict` copies what it finds into
    phase3_one_shot.json as `completion_audit_verdict`, and the front door reads THAT as
    the run's audit axis. A scoped document must not travel under that name."""
    import phase3_one_shot_runner as R
    import _path_layout as _pl
    audit = _pl.report_path(tmp_path, "phase23_completion_audit.json")
    audit.parent.mkdir(parents=True, exist_ok=True)

    audit.write_text(json.dumps({"verdict": "FAIL", "scope": {
        "whole_flow": True, "step_count": 70, "flow_step_total": 70}}))
    _headline, carried, _note = R._derive_headline_verdict(tmp_path, "PASS")
    assert carried == "FAIL", carried

    audit.write_text(json.dumps({"verdict": "FAIL", "scope": {
        "whole_flow": False, "step_count": 10, "flow_step_total": 70,
        "stage_id": "stage4"}}))
    headline, carried2, note = R._derive_headline_verdict(tmp_path, "PASS")
    assert carried2 is None, carried2
    assert headline == "PASS", headline
    assert "not this run's whole-flow audit" in note and "10 of 70" in note, note


def test_the_fpga_guard_requires_its_own_pass_and_its_own_population():
    """READER 4. Source-pinned because driving a burn needs the board: the guard dates the
    document against its own pass AND checks the scope is the population it asked about."""
    src = (PLUGIN / "mcp-eda/src/devices/fpga/terasic-de10lite"
           / "driver.py").read_text()
    started = src.index("_pass_started = time.time()")
    check = src.index('_scope.get("phase")) != "2"', started)
    assert started < check
    window = src[started:check + 400]
    assert "st_mtime + 1.0 < _pass_started" in window, (
        "the guard no longer dates the audit against its own pass")
    assert '_scope.get("whole_flow") is True' in window, (
        "the guard accepts a whole-flow audit as an answer about its 32 steps")












def _seeded_step2_project(tmp_path: Path) -> Path:
    """A project where step 2's outputs EXIST, so its advisory clause actually runs.

    On a bare fixture step 2 returns MISSING early and the republish never happens, so
    the pair the finding is about never forms — which is why the bare fixture hid it.
    """
    proj = tmp_path / "seeded"
    rtl = proj / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text("module d(); endmodule\n")
    for rel, body in (
            ("reports/phase1/gates/stage_phase1_compliance.json",
             {"program": "flow_compliance_check", "overall": "PASS", "steps": []}),
            ("reports/crosslayer/rewrite_equivalence.json", {"rewrites": []}),
            ("reports/crosslayer/rewrite_equivalence_check.json",
             {"program": "crosslayer_rewrite_fidelity", "verdict": "PASS"}),
            ("reports/phase2/lint/rtl_hygiene.json", {"verdict": "PASS"}),
            ("reports/phase2/lint/rom_init_lint.json", {"verdict": "PASS"})):
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(body) + "\n")
    return proj




def _moved(audit: dict) -> object:
    """`design_moved` lives in `tally_delta` — the CLASSIFICATION block — not in
    `design_input_digest`, which only carries this pass's own hash.

    Read from the wrong block my first cut returned None for every sequence, so the
    four-sequence arm passed VACUOUSLY: `None is not True` is satisfied by a key that
    does not exist. The RTL-edit arm is what exposed it, which is the whole reason a
    positive direction sits beside the negative one."""
    return ((audit.get("tally_delta") or {}).get("design_moved"))


def _classification(audit: dict) -> object:
    return ((audit.get("tally_delta") or {}).get("classification"))


#: The outcomes that are honest on an unchanged tree. DESIGN_CHANGE is not one of them.
#: NOT_COMPARABLE IS: with ONE canonical audit, the document on disk when a pass reads its
#: prior is whatever the last NESTED clause wrote during the step loop (a 2-step
#: `stage_phase1` audit), while the document the pass LEAVES is its own (70 steps,
#: whole_flow=true — measured). So a whole-flow pass compares itself against a different
#: population and correctly refuses the comparison. That is how main behaves, and refusing
#: to compare is not a claim about the design.
_HONEST_ON_UNCHANGED = {"NOT_COMPARABLE", "UNCHANGED", "MEASUREMENT_CHANGE",
                        "UNEXPLAINED_TALLY_MOVE", "NOT_ATTRIBUTABLE"}
