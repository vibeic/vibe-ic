#!/usr/bin/env python3
"""A disclosed capability gap must be one the PLATFORM declares, not one the
marker invents.

Deferred tail of the 29/d7 SDF work (bucket `signoff_adj`, deferred item 8).
That change fixed the step-29 PRODUCER: `phase3_one_shot_runner` no longer
stamps `capability_flag: cap:sdf_annotated_gatelevel_sim` onto every
no-results.log path, because the runner HAS driven a back-annotated sim since
v1.3.94 and `_PLATFORM_CAPABILITY_GAPS` records step 29's gap as CLOSED. The
GENERIC vector it explicitly left open was the gate side: the #675-strict
promoter asked only that `capability_flag` be a NON-EMPTY STRING, so the
disclosure was self-certifying — any value at all was believed.

MEASURED on the completed spm x ihp-sg13g2 run
(~/campaign_pr427/spm/converge_ihp-sg13g2, plugin @ origin/main v1.7.61):

    >>> fcc._declared_sibling_self_skip_for_missing(proj, STEP29_OUTPUTS)
    'phase3/stage3/sim_postlayout/sdf_sim_skipped.json: owns this output
     (skips_required_output) and self-reports verdict=SKIPPED-CONDITION
     [cap:sdf_annotated_gatelevel_sim] (...)'

That run's step 29 therefore reported SKIPPED-CONDITION — a disclosed platform
gap — on the strength of a flag the platform had already retired. Same call on
this tree returns None: the step keeps its real MISSING status. Steps 12 and 30
in the same project carry REGISTERED flags and are unchanged.

FIX: `flow_compliance_check._DECLARED_CAPABILITY_GAP_FLAGS` — the declaration
side of the contract. A marker may defer only under a flag named there.

DIRECTION OF THE GUARD: it asserts the claimed flag IS ON the declared list.
The tempting alternative — a denylist of known-retired flags — passes for every
name nobody has thought of yet, which is the hole itself.

COST, stated plainly: this turns things RED, not green. Any project whose only
excuse for an absent sign-off artefact is an unregistered capability flag now
reports MISSING (strict rc 1) where it used to report SKIPPED-CONDITION. On the
measured reference run that is exactly one step (29).

SCOPE OF THE MEASUREMENT: the reference run is pure DIGITAL standard-cell, so
it exercised no analog (A1-A9) or mixed-signal (M1-M4) step. Those tracks are
covered by CODE-READING, not by that run: `skips_required_output` is emitted
by exactly three modules (`design_one_shot_runner`, `phase3_one_shot_runner`
and this gate's own tests) and no `analog_*` / `mixed_signal_*` producer writes
a `capability_flag` at all, so the strict promoter has no A/M marker to accept
or refuse and their verdicts cannot move. The synthetic fixtures below stand in
for whatever an A/M producer might emit in future.

chip-AGNOSTIC: synthetic markers + a one-step synthetic flow def.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as fcc  # noqa: E402

# The retired flag the reference run's marker still carries. Retired in
# v1.7.37; `test_phase3_sdf_skip_disclosure` forbids any producer from
# emitting it, and no producer does — yet the gate honoured it.
_RETIRED = "cap:sdf_annotated_gatelevel_sim"
# A flag no producer has ever emitted: the "next marker" vector.
_FORGED = "cap:invented_by_the_marker"
# A flag the platform DOES declare open.
_REGISTERED = "cap:post_dft_scan_optimization"

_STEP12_OUT = "phase2/stage2/synth/post_dft_netlist.v"
_STEP29_OUTS = ["phase3/stage3/sim_postlayout/results.log",
                "phase3/stage3/sim_postlayout/pass.flag"]


def _marker(proj: Path, rel_dir: str, flag, outs, name="x_not_run.json") -> Path:
    d = proj / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    payload = {"verdict": "SKIPPED-CONDITION",
               "reason": "synthetic marker",
               "skips_required_output": outs}
    if flag is not None:
        payload["capability_flag"] = flag
    p = d / name
    p.write_text(json.dumps(payload, indent=2))
    return p


# ===========================================================================
# the defect: an undeclared flag used to defer a real MISSING
# ===========================================================================
@pytest.mark.parametrize("flag", [_RETIRED, _FORGED])
def test_undeclared_capability_flag_does_not_defer_an_absent_output(
        tmp_path, flag):
    _marker(tmp_path, "phase3/stage3/sim_postlayout", flag, _STEP29_OUTS,
            name="sdf_sim_skipped.json")
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, list(_STEP29_OUTS)) is None


@pytest.mark.parametrize("flag", [_RETIRED, _FORGED])
def test_step_with_an_undeclared_flag_marker_stays_missing(tmp_path, flag):
    """The OBSERVABLE property, end to end through `check_step`: the step keeps
    its real status. A neutral step id (999) is used so the result cannot come
    from the #430 hard-coded capability-gap step-id table."""
    _marker(tmp_path, "phase2/stage2/synth", flag, _STEP12_OUT,
            name="post_dft_not_run.json")
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": [_STEP12_OUT]}
    res = fcc.check_step(tmp_path, step, waivers={})
    assert res.status == "MISSING", (res.status, res.reasons)
    assert res.self_skip_disclosed is False


def test_undeclared_flag_makes_the_whole_gate_exit_nonzero(tmp_path):
    """Wired BLOCKING: the refusal reaches the program's exit code. rc 1 here
    against rc 0 for the byte-identical project whose marker names a REGISTERED
    flag — so the two legs differ only in the claim being checked."""
    flow_def = tmp_path / "mini_flow.yaml"
    flow_def.write_text(
        "steps:\n"
        "  - id: 999\n"
        "    name: \"Post-DFT optimization\"\n"
        "    stage: stage2\n"
        f"    required_outputs: [\"{_STEP12_OUT}\"]\n")

    forged_proj = tmp_path / "forged"
    _marker(forged_proj, "phase2/stage2/synth", _FORGED, _STEP12_OUT,
            name="post_dft_not_run.json")
    rc_forged = fcc.main([str(forged_proj), "--flow-def", str(flow_def),
                          "--strict"])

    ok_proj = tmp_path / "declared"
    _marker(ok_proj, "phase2/stage2/synth", _REGISTERED, _STEP12_OUT,
            name="post_dft_not_run.json")
    rc_ok = fcc.main([str(ok_proj), "--flow-def", str(flow_def), "--strict"])

    assert (rc_forged, rc_ok) == (1, 0)


def test_a_registered_flag_is_matched_exactly_not_by_prefix(tmp_path):
    """`cap:cdc` is registered; `cap:cdc_forged` must not ride on it, and a
    registered flag must not be reachable by appending to a shorter one."""
    for near_miss in ("cap:cdc_forged", "cap:cdc.x", "cap", "cap:"):
        _marker(tmp_path, "phase2/stage2/synth", near_miss, _STEP12_OUT,
                name="post_dft_not_run.json")
        assert fcc._declared_sibling_self_skip_for_missing(
            tmp_path, [_STEP12_OUT]) is None, near_miss


# ===========================================================================
# the registry must not silently go stale
# ===========================================================================
def test_every_capability_flag_a_producer_emits_is_registered():
    """Completeness aid for the registry.

    Scans the plugin's non-test program sources for `"cap:..."` STRING
    LITERALS and requires each to be declared. Its purpose is to stop the
    registry silently going stale and false-REDding a legitimate new gap: a
    producer minting a flag must also register it, which is the deliberate,
    reviewed edit the whole design is for.

    WHAT THIS SCAN CANNOT SEE, stated so nobody mistakes a green run here for
    proof: a flag assembled at runtime (f-string, `"cap:" + name`, a value read
    from JSON) is invisible to it. Today every emitter uses a plain literal —
    `transition_coverage_check.py` is the one place that handles flags
    generically, and it only PROPAGATES a flag another producer wrote. The
    BEHAVIOURAL contract does not depend on this scan: an unregistered flag,
    however it was built, is refused at runtime by the tests above.

    Full-line comments are stripped first, so PROSE about a flag (this repo
    discusses the retired one at length) is not miscounted as an emission.
    """
    lit = re.compile(r'"(cap:[A-Za-z0-9_.-]+)"')
    emitted: dict = {}
    for py in sorted(PROGRAMS.glob("*.py")):
        code = "\n".join(ln for ln in py.read_text(errors="replace").splitlines()
                         if not ln.lstrip().startswith("#"))
        for m in lit.finditer(code):
            emitted.setdefault(m.group(1), set()).add(py.name)
    # The retired flag must not have come back, and every live one must be
    # declared. `_RETIRED` is named in prose in this repo but must not appear
    # as a producer literal.
    assert _RETIRED not in emitted, f"retired flag re-emitted by {emitted.get(_RETIRED)}"
    unregistered = {f: sorted(src) for f, src in emitted.items()
                    if f not in fcc._DECLARED_CAPABILITY_GAP_FLAGS}
    assert not unregistered, (
        "producer(s) emit capability flags that flow_compliance_check does not "
        "declare open — register them (a reviewed edit) or stop emitting them: "
        + json.dumps(unregistered, indent=2))


def test_the_registry_is_not_a_rubber_stamp():
    """It must actually be a finite named list — an empty or wildcard-ish
    registry would make the guard vacuous."""
    reg = fcc._DECLARED_CAPABILITY_GAP_FLAGS
    assert isinstance(reg, frozenset) and reg
    assert all(isinstance(f, str) and f.startswith("cap:") and len(f) > 4
               for f in reg)
    assert not fcc._is_declared_capability_gap("")
    assert not fcc._is_declared_capability_gap("cap:" + "z" * 40)


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change (pass on BOTH trees)
# ===========================================================================
def test_guard_a_declared_flag_with_ownership_still_defers(tmp_path):
    """The mechanism the #675-strict promoter exists for is untouched."""
    _marker(tmp_path, "phase2/stage2/synth", _REGISTERED, _STEP12_OUT,
            name="post_dft_not_run.json")
    hint = fcc._declared_sibling_self_skip_for_missing(tmp_path, [_STEP12_OUT])
    assert hint and _REGISTERED in hint

    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": [_STEP12_OUT]}
    res = fcc.check_step(tmp_path, step, waivers={})
    assert res.status == "SKIPPED-CONDITION", (res.status, res.reasons)
    assert res.self_skip_disclosed is True


def test_guard_no_flag_at_all_is_still_refused(tmp_path):
    _marker(tmp_path, "phase2/stage2/synth", None, _STEP12_OUT,
            name="post_dft_not_run.json")
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, [_STEP12_OUT]) is None


def test_guard_declared_flag_owning_a_different_output_is_still_refused(
        tmp_path):
    """Ownership is still checked independently of the flag: a REGISTERED flag
    on a marker naming someone else's output must not mask this step."""
    _marker(tmp_path, "phase2/stage2/synth", _REGISTERED,
            "phase2/stage2/synth/netlist.v", name="post_dft_not_run.json")
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, [_STEP12_OUT]) is None


def test_guard_declared_flag_with_a_broad_glob_claim_is_still_refused(tmp_path):
    """Exact-match ownership is unchanged: a registered flag does not buy a
    wildcard `skips_required_output` any masking power."""
    _marker(tmp_path, "reports/phase3", _REGISTERED, "reports/phase3/*",
            name="forged.json")
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, ["reports/phase3/drc_signoff.rpt"]) is None


def test_guard_declared_flag_with_a_non_skip_verdict_is_still_refused(tmp_path):
    d = tmp_path / "phase2/stage2/synth"
    d.mkdir(parents=True)
    (d / "post_dft_not_run.json").write_text(json.dumps({
        "verdict": "FAIL", "capability_flag": _REGISTERED,
        "skips_required_output": _STEP12_OUT}))
    assert fcc._declared_sibling_self_skip_for_missing(
        tmp_path, [_STEP12_OUT]) is None


def test_guard_loose_files_exist_variant_is_untouched(tmp_path):
    """The registry gates the STRICT early-MISSING promoter only. The loose
    `files_exist`-path variant never looked at `capability_flag` (a second
    sub-gate backstops it there) and must keep working unchanged."""
    d = tmp_path / "phase2/stage1/formal"
    d.mkdir(parents=True)
    (d / "formal_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "reason": "no proof harness authored"}))
    hint = fcc._sibling_self_skip_for_missing(
        tmp_path, ["phase2/stage1/formal/results.json"])
    assert hint and "formal_not_run.json" in hint


def test_guard_platform_capability_gaps_table_is_untouched():
    """`_PLATFORM_CAPABILITY_GAPS` (the #430 step-id table) is a DIFFERENT
    mechanism and is deliberately left empty by this change. The literal form
    of the deferred guard — "refuse any flag for a step id this table says has
    no open gap" — would, with the table empty, refuse EVERY marker and delete
    the #675 promoter outright; that is why the declaration is keyed on the
    FLAG instead."""
    assert fcc._PLATFORM_CAPABILITY_GAPS == {}
