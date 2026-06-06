"""v0.2.63 platform-capability-gap regressions.

Pins the #430 fix (ORGANIC-20260606-runner-missing-canonical-steps),
suggested-fix option (b): canonical Steps 11/12/13/29 (DFT scan insertion +
ATPG, post-DFT optimization, LEC, post-layout SPICE correlation) are not
implemented by the open-tool runner chain, so three independent full-chain
clean-room digital runs all ended FAIL(strict) on the SAME fixed MISSING
set regardless of design quality. `flow_compliance_check` now carries a
DOCUMENTED `_PLATFORM_CAPABILITY_GAPS` profile: a would-be-MISSING verdict
on a listed step converts to SKIPPED-CONDITION whose reason NAMES the
capability flag — never a silent MISSING — while a step that produces
evidence keeps its natural PASS/FAIL (implementing a step removes its
entry; the flag is the tracking anchor). Step 18 is NOT listed (the
runner emits its spare-cell/ECO evidence chain since v0.2.60).

chip-AGNOSTIC: synthetic step dicts in tmp projects only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F  # noqa: E402


def _step(sid, name="step", outputs=None):
    return {"id": sid, "name": name, "stage": "stage3",
            "required_outputs": outputs or
            [f"reports/never_emitted_{sid}.rpt"]}


def test_gap_table_names_the_gap_steps_with_flags():
    # 11/12/13/29 from #430; 28 added by #437(d) — the runner emits the
    # SDF but never runs an SDF-annotated gate-level re-sim.
    assert set(F._PLATFORM_CAPABILITY_GAPS) == {5, 11, 12, 13, 29, 30}  # v2.3 renumber
    for sid, flag in F._PLATFORM_CAPABILITY_GAPS.items():
        assert flag.startswith("cap:"), (sid, flag)


def test_missing_gap_step_converts_to_skipped_with_named_flag(tmp_path):
    for sid in (5, 11, 12, 13, 29, 30):
        r = F.check_step(tmp_path, _step(sid), waivers={})
        assert r.status == "SKIPPED-CONDITION", (sid, r.status)
        joined = " ".join(r.reasons)
        assert F._PLATFORM_CAPABILITY_GAPS[sid] in joined, (sid, joined)
        assert "MISSING" in joined  # the conversion is disclosed, not silent


def test_step_with_evidence_keeps_natural_verdict(tmp_path):
    # a listed step that DOES produce evidence must gate normally —
    # implementing the capability later must not be masked by the profile
    out = tmp_path / "reports" / "dft_scan.rpt"
    out.parent.mkdir(parents=True)
    out.write_text("scan chains: 4\n")
    r = F.check_step(tmp_path, _step(11, outputs=["reports/dft_scan.rpt"]),
                     waivers={})
    assert r.status == "PASS", r


def test_unlisted_step_still_reports_missing(tmp_path):
    # step 18 (and any other unlisted id) keeps the honest MISSING
    r = F.check_step(tmp_path, _step(18), waivers={})
    assert r.status == "MISSING", r.status


def test_env_unavailable_waiver_still_wins_over_gap(tmp_path):
    # an explicit ENV_UNAVAILABLE waiver outranks the capability profile
    # (waiver promotion runs first) — order pinned so audits see WAIVED
    waivers = {11: {"_env_unavailable": True, "reason": "no scan tool on host",
                    "approver": "review-board"}}
    r = F.check_step(tmp_path, _step(11), waivers=waivers)
    assert r.status == "WAIVED", r.status
