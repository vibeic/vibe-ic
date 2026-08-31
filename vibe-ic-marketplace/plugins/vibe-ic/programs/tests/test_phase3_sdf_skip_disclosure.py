#!/usr/bin/env python3
"""Step 29 — the skip-marker must disclose what ACTUALLY happened.

Defect (HIGH, dimension 6 (skip discipline)), second half: whenever
`phase3/stage3/sim_postlayout/results.log` was absent, the runner wrote ONE
canned `sdf_sim_skipped.json`:

    verdict:        SKIPPED-CONDITION
    capability_flag: cap:sdf_annotated_gatelevel_sim
    reason:          "... the open-tool runner emits the SDF but does not
                      drive a back-annotated sim (#437d) ..."

That reason has been FALSE since v1.3.94 — the runner DOES call
`sdf_gate_sim.run()` — and `flow_compliance_check._PLATFORM_CAPABILITY_GAPS` is
literally empty with the comment "29 SDF -> iverilog $sdf_annotate gate sim".
Because the marker carried a `capability_flag` plus a `skips_required_output`
naming both step-29 outputs, `_declared_sibling_self_skip_for_missing` promoted
the step from MISSING to SKIPPED-CONDITION — so a compile failure, an aborted
simulator or a missing routed netlist all came out looking like a disclosed
platform gap.

`_sdf_sim_skip_disclosure` now derives (capability_flag, reason) from what
`sdf_gate_sim.run()` actually returned. Only an observed missing simulator
toolchain keeps a flag; every input/producer failure gets flag=None, which the
#675-strict promoter refuses, so the step stays MISSING (red).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402
import flow_compliance_check as fcc  # noqa: E402

_STEP29_OUTPUTS = [
    "phase3/stage3/sim_postlayout/results.log",
    "phase3/stage3/sim_postlayout/pass.flag",
]
_STALE_FALSE_CLAIM = "does not"


def _sdf(tmp_path: Path, present: bool = True) -> Path:
    p = tmp_path / "spm.sdf"
    if present:
        p.write_text("(DELAYFILE (SDFVERSION \"3.0\"))\n")
    return p


def _marker(tmp_path: Path, flag, reason) -> Path:
    """Write the payload the runner writes, in the same shape."""
    d = tmp_path / "phase3/stage3/sim_postlayout"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "verdict": "SKIPPED-CONDITION" if flag else "ERROR",
        "reason": reason,
    }
    if flag:
        payload["capability_flag"] = flag
        payload["skips_required_output"] = list(_STEP29_OUTPUTS)
    (d / "sdf_sim_skipped.json").write_text(json.dumps(payload, indent=2))
    return d / "sdf_sim_skipped.json"


# ── discriminators: these FAIL on the pre-fix program ──────────────────────

@pytest.mark.parametrize("sim_result", [
    {"verdict": "ERROR", "reason": "compile failed"},
    {"verdict": "ERROR", "reason": "sim invoke: docker gone"},
    {"verdict": "ERROR", "reason": "sdf_gate_sim raised: boom"},
    {"verdict": "NOT_APPLICABLE", "reason": "no netlist"},
    {"verdict": "NOT_APPLICABLE", "reason": "no sdf"},
    {"verdict": "FAIL", "reason": ""},
])
def test_real_failures_get_no_capability_flag(tmp_path, sim_result):
    flag, reason = p3._sdf_sim_skip_disclosure(sim_result, _sdf(tmp_path))
    assert flag is None, f"{sim_result} was laundered as cap-gap {flag}"
    assert _STALE_FALSE_CLAIM not in reason or "NOT a disclosed" in reason


def test_never_invoked_without_an_sdf_is_not_a_capability_gap(tmp_path):
    flag, reason = p3._sdf_sim_skip_disclosure(None, _sdf(tmp_path, present=False))
    assert flag is None
    assert "no SDF was emitted" in reason


def test_sdf_present_but_producer_never_ran_is_a_runner_defect(tmp_path):
    flag, reason = p3._sdf_sim_skip_disclosure(None, _sdf(tmp_path))
    assert flag is None
    assert "runner defect" in reason


def test_the_genuine_missing_tool_gap_keeps_a_named_flag(tmp_path):
    flag, reason = p3._sdf_sim_skip_disclosure(
        {"verdict": "NOT_APPLICABLE", "reason": "no simulator"},
        _sdf(tmp_path))
    assert flag == "cap:sdf_gatelevel_simulator_toolchain"
    assert len(reason) > 60, "a cap-gap disclosure must name the gap"


def test_the_stale_false_capability_flag_is_gone():
    """`cap:sdf_annotated_gatelevel_sim` claimed the platform cannot drive a
    back-annotated sim. It can (v1.3.94+), so no code path may emit it."""
    for res in (None,
                {"verdict": "ERROR", "reason": "compile failed"},
            {"verdict": "NOT_APPLICABLE", "reason": "no simulator"},
            {"verdict": "ERROR", "reason": "no pdk lib"},
                {"verdict": "NOT_APPLICABLE", "reason": "no sdf"}):
        flag, reason = p3._sdf_sim_skip_disclosure(res, Path("/nonexistent.sdf"))
        assert flag != "cap:sdf_annotated_gatelevel_sim"
        assert "does not drive a back-annotated sim" not in reason


def test_no_code_path_hardcodes_the_retired_capability_flag():
    """Belt-and-braces on the WRITER, not just the helper: comment prose may
    still discuss `cap:sdf_annotated_gatelevel_sim` (this commit explains why it
    was retired), but no executable line may emit it."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "cap:sdf_annotated_gatelevel_sim" not in code
    assert "back-annotated sim (#437d)" not in code


def test_flagless_marker_is_refused_by_the_strict_promoter(tmp_path):
    """End-to-end: the ERROR-tier marker must NOT promote step 29 out of
    MISSING, while a genuine cap-gap marker still may."""
    flag, reason = p3._sdf_sim_skip_disclosure(
        {"verdict": "ERROR", "reason": "compile failed"}, _sdf(tmp_path))
    _marker(tmp_path, flag, reason)
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, list(_STEP29_OUTPUTS)) is None

    flag2, reason2 = p3._sdf_sim_skip_disclosure(
        {"verdict": "NOT_APPLICABLE", "reason": "no simulator"},
        _sdf(tmp_path))
    _marker(tmp_path, flag2, reason2)
    hint = fcc._declared_sibling_self_skip_for_missing(
        tmp_path, list(_STEP29_OUTPUTS))
    assert hint and "cap:sdf_gatelevel_simulator_toolchain" in hint


# ── direction-1 guards: must PASS on BOTH trees ───────────────────────────

def guard_strict_promoter_still_requires_flag_and_ownership(tmp_path):
    """#675-strict ownership rules are only ADDED to, never relaxed.

    2026-07-27 (deferred item 8): the positive leg used to hand the promoter a
    made-up `cap:x`. That made the guard assert, as expected behaviour, the
    very hole the promoter had — that ANY non-empty string is a believable
    capability disclosure. Both legs now use a flag
    `flow_compliance_check._DECLARED_CAPABILITY_GAP_FLAGS` actually declares
    open, so each leg isolates exactly one refusal cause and the guard tests
    ownership rather than credulity. The rules it protects are unchanged; a
    third one (the flag must be declared) was added, never a relaxation.

    Deliberately references no new symbol, so this guard still passes against
    the pre-registry tree — the registry's own contents are asserted in
    `test_capability_gap_flag_registry.py`.
    """
    declared = "cap:sdf_gatelevel_simulator_toolchain"
    d = tmp_path / "phase3/stage3/sim_postlayout"
    d.mkdir(parents=True)
    # no capability_flag -> refused
    (d / "a.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "skips_required_output": _STEP29_OUTPUTS}))
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, list(_STEP29_OUTPUTS)) is None
    # flag but owns a DIFFERENT output -> refused
    (d / "a.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "capability_flag": declared,
        "skips_required_output": ["phase3/stage2/synth/netlist.v"]}))
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, list(_STEP29_OUTPUTS)) is None
    # both present -> promoted
    (d / "a.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "capability_flag": declared,
        "skips_required_output": _STEP29_OUTPUTS}))
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, list(_STEP29_OUTPUTS)) is not None


def guard_platform_capability_gaps_stays_empty_for_step_29():
    """The module's own doctrine: step 29 has no open platform gap. If a future
    change reopens one it must be a deliberate, reviewed edit."""
    assert 29 not in fcc._PLATFORM_CAPABILITY_GAPS


test_guard_strict_promoter_still_requires_flag_and_ownership = \
    guard_strict_promoter_still_requires_flag_and_ownership
test_guard_platform_capability_gaps_stays_empty_for_step_29 = \
    guard_platform_capability_gaps_stays_empty_for_step_29
