#!/usr/bin/env python3
"""ORGANIC-20260606 #470 (CRITICAL) — Step 31 PV sign-off gate was DEAD CODE.

Background
----------
The flow YAML authored Step 31's predicate block (``all_of:`` with
drc_report_check / lvs_report_check / 2x provenance_check + erc_density_check)
as a SIBLING of ``programs:`` / ``required_outputs:`` instead of nesting it
inside ``gate:`` (compare Step 32, which is correct). ``check_step`` reads
only ``step.get("gate")`` → gate was ``None`` → all four sub-gates never
executed → the most safety-critical sign-off step (DRC+LVS+ERC+Density)
degraded to "any required_output present → PASS". A run with NO DRC sign-off
report, NO ERC report, and a truncated verdict-less netgen LVS log would PASS.

This file:
  (1) FIXED-PATH end-to-end acceptance — builds a defect-artifact fixture
      shaped exactly like the issue (Step-31 outputs where drc_signoff.rpt +
      erc.rpt are ABSENT and lvs.rpt is a truncated netgen log with no
      terminal verdict) and drives the REAL check_step on it. Step 31 must
      now FAIL (it would have spuriously PASSed before the fix).
  (2) DEFENSE regression — a step node that (mistakenly) carries gate-shaped
      predicate keys directly (not nested under gate:) must have them PROMOTED
      into the gate AND surface a visible WARNING finding, so a future hand-
      slip can never again silently void a whole gate.
  (3) META-TEST — walk every step node in the live flow YAML and assert NONE
      carries a gate-shaped predicate key outside ``gate:``. Guards the YAML
      against regressing to the #470 shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import flow_compliance_check as fcc  # noqa: E402

FLOW_YAML = PROG_DIR.parent / "flow" / "phase1_phase2_phase3.yaml"

# The gate-shaped predicate keys recognised by _evaluate_gate(). These must
# only ever appear INSIDE a step's `gate:` mapping, never as a direct child of
# the step node.
GATE_PREDICATE_KEYS = {
    "all_of",
    "any_of",
    "program_exit_zero",
    "optional_program_exit_zero",
    "files_exist",
    "json_field_true",
}


def _load_flow() -> dict:
    return yaml.safe_load(FLOW_YAML.read_text())


def _step_node(flow: dict, sid):
    for s in flow.get("steps", []):
        if s.get("id") == sid:
            return s
    raise AssertionError(f"step id {sid!r} not found in flow YAML")


# ── Defect-artifact fixture (the issue's 現象) ─────────────────────────────
def _build_issue470_defect_project(root: Path) -> Path:
    """Step-31 sign-off artefacts shaped like the bug report:

      * drc_signoff.rpt  -> ABSENT (no DRC report on disk at all)
      * erc.rpt          -> ABSENT
      * lvs.rpt          -> PRESENT but a TRUNCATED netgen log with no
                            terminal verdict (this is the one required_output
                            that lets the step slip past the early
                            required_outputs MISSING exit and reach the gate).

    Synthetic / chip-AGNOSTIC: no chip/vendor/SKU names; the netgen-style log
    uses a structural shape (the tool banner + a per-cell compare header that
    gets cut off mid-run), not a real design name.
    """
    proj = root / "issue470_defect"
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)

    # Truncated netgen LVS log: it names the tool (netgen) so provenance could
    # in principle match, but the run is cut off BEFORE any
    # "Circuits match"/"matching"/verdict line — exactly the verdict-less
    # truncation called out in the issue. NO drc_signoff.rpt, NO erc.rpt.
    truncated_netgen = (
        "Netgen 1.5.262 compare run\n"
        "Reading netlist file layout.spice\n"
        "Reading netlist file schematic.spice\n"
        "Contents of circuit 1:  Circuit: 'top'\n"
        "Contents of circuit 2:  Circuit: 'top'\n"
        "Cell top:  (comparing cells, run truncated mid-pass)\n"
        # <-- log ends here: no "Circuits match", no net/device/instance
        #     mismatch summary, no terminal verdict.
    )
    (proj / "reports" / "phase3" / "lvs.rpt").write_text(truncated_netgen)

    return proj


# ── (1) FIXED-PATH end-to-end acceptance ───────────────────────────────────
def test_issue470_step31_fails_on_defect_artifact(tmp_path):
    """The acceptance criterion, executed end-to-end against the REAL gate.

    Drive the actual check_step on the defect-artifact fixture using the LIVE
    flow YAML step-31 node. Step 31 must now FAIL (DRC report absent → first
    sub-gate fails). Before the fix the gate was dead and the step PASSed.
    """
    proj = _build_issue470_defect_project(tmp_path)
    flow = _load_flow()
    step31 = _step_node(flow, 31)

    result = fcc.check_step(proj, step31, waivers={})

    # END-STATE assertion: the most safety-critical sign-off step FAILs.
    assert result.status == "FAIL", (
        f"Step 31 should FAIL on the #470 defect artefact (no DRC sign-off, "
        f"no ERC, verdict-less LVS) but got status={result.status!r} "
        f"reasons={result.reasons}"
    )
    # And the failure is the real gate firing, not an early MISSING exit:
    # the truncated lvs.rpt is the one required_output that exists, so the
    # step reached the gate and the DRC sub-gate failed.
    joined = " ".join(result.reasons).lower()
    assert "program failed" in joined or "drc" in joined, (
        f"expected a real gate-program failure reason, got {result.reasons}"
    )


def test_issue470_live_yaml_step31_gate_is_nested():
    """Structural fix verification: Step 31 now carries its predicate block
    inside `gate:` (not at the step level), matching Step 32's correct shape.
    """
    flow = _load_flow()
    step31 = _step_node(flow, 31)

    assert "gate" in step31, "Step 31 must carry a `gate:` mapping"
    assert "all_of" in step31["gate"], "Step 31 gate must be an `all_of:` block"
    # The predicate keys must NOT be present at the step (top) level anymore.
    assert GATE_PREDICATE_KEYS.isdisjoint(step31.keys()), (
        f"Step 31 still carries gate-shaped keys at the step level: "
        f"{GATE_PREDICATE_KEYS & set(step31.keys())}"
    )
    # The promoted gate still carries all five ORIGINAL sub-gates.
    #
    # This asserted `len(...) == 5`, which said "the five survived" by proxy.
    # The proxy broke the moment #488 legitimately added a sixth
    # (`pg_rail_geometry_check`) — a count cannot tell an ADDITION from a
    # LOSS, and this test exists to catch the loss. Changing 5 to 6 would just
    # re-arm the same trap for the next addition, so it now names what must
    # survive and stays silent about what else step 31 may grow.
    _cmds = " ".join(str(v) for sub in step31["gate"]["all_of"]
                     for v in sub.values())
    for _required in ("drc_report_check", "lvs_report_check",
                      "erc_density_check"):
        assert _required in _cmds, (
            f"Step 31 gate lost its {_required} sub-gate: {_cmds}")
    assert _cmds.count("provenance_check") == 2, (
        f"Step 31 gate must keep BOTH provenance checks: {_cmds}")
    assert len(step31["gate"]["all_of"]) >= 5, (
        f"Step 31 gate dropped below its five original sub-gates: {_cmds}")


# ── (2) DEFENSE regression — promotion + visible warning ───────────────────
def test_issue470_defense_promotes_stray_predicate_keys(tmp_path):
    """A hand-slip that puts the predicate block at the step level (the exact
    #470 shape, BEFORE the YAML fix) must be defended: check_step promotes the
    stray keys into the gate AND emits a WARNING finding. The dead-gate FAIL
    must therefore still fire even on the buggy step shape.
    """
    proj = _build_issue470_defect_project(tmp_path)

    # Reconstruct the BUGGY step node: predicate `all_of` at the step level,
    # NO `gate:` key — exactly what the YAML looked like before the fix.
    flow = _load_flow()
    good31 = _step_node(flow, 31)
    buggy31 = {k: v for k, v in good31.items() if k != "gate"}
    buggy31["all_of"] = good31["gate"]["all_of"]
    assert "gate" not in buggy31 and "all_of" in buggy31  # bug reproduced

    result = fcc.check_step(proj, buggy31, waivers={})

    # The promoted gate fires → step FAILs (would have spuriously PASSed if
    # the defense were absent and the gate stayed dead).
    assert result.status == "FAIL", (
        f"defense must promote the stray gate so the step FAILs; got "
        f"{result.status!r} reasons={result.reasons}"
    )
    # The authoring slip is SURFACED, not hidden.
    assert any(
        "step level" in r.lower() and "#470" in r for r in result.reasons
    ), (
        f"defense must emit a visible WARNING about the misplaced gate keys; "
        f"reasons={result.reasons}"
    )


def test_issue470_defense_does_not_fire_when_gate_is_correct(tmp_path):
    """The defense must be a no-op when the gate is correctly nested — it must
    NOT emit the #470 warning for a well-authored step. (Guards against the
    promotion path leaking into the normal case.)"""
    proj = _build_issue470_defect_project(tmp_path)
    flow = _load_flow()
    step31 = _step_node(flow, 31)  # correctly nested gate (post-fix)

    result = fcc.check_step(proj, step31, waivers={})

    assert not any("#470" in r for r in result.reasons), (
        f"defense warning must NOT fire on a correctly-nested gate; "
        f"reasons={result.reasons}"
    )


def test_issue470_defense_step_with_no_gate_and_no_predicate_is_untouched(
        tmp_path):
    """A step that legitimately has no gate and no stray predicate keys must
    behave exactly as before (presence-of-outputs PASS), not be perturbed by
    the promotion logic."""
    proj = tmp_path / "no_gate_proj"
    proj.mkdir()
    (proj / "out.txt").write_text("ok\n")
    step = {
        "id": 999,
        "name": "synthetic no-gate step",
        "stage": "stage4",
        "required_outputs": ["out.txt"],
    }
    result = fcc.check_step(proj, step, waivers={})
    assert result.status == "PASS"
    assert not any("#470" in r for r in result.reasons)


# ── (3) META-TEST — no step node carries predicate keys outside gate: ──────
def test_issue470_metatest_no_step_carries_predicate_outside_gate():
    """Walk EVERY step node in the live flow YAML and assert none carries a
    gate-shaped predicate key at the step level. This is the regression guard
    that pins the #470 shape out of the flow definition for good.
    """
    flow = _load_flow()
    steps = flow.get("steps", [])
    assert steps, "flow YAML has no steps list"

    offenders = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        stray = GATE_PREDICATE_KEYS & set(s.keys())
        if stray:
            offenders.append((s.get("id"), sorted(stray)))

    assert not offenders, (
        "step node(s) carry gate-shaped predicate keys OUTSIDE `gate:` "
        f"(the #470 dead-gate shape): {offenders}. Nest them under `gate:`."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
