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


def test_gap_table_is_now_empty():
    # 11/12/13/29 from #430; 28 added by #437(d).
    # v1.3.94 — the commercial-PDK campaign CLOSED 22 (SPEF via OpenRCX v2
    # -lef_rc), 11 (Fault ATPG 96%), 12 (post-DFT opt_clean), 29 (iverilog SDF
    # sim), 30 (ngspice correlation), 13 (LEC via read_liberty
    # -ignore_miss_func) with real OSS tools → they gate normally.
    # v1.3.99 — the LAST gap (5, formal proof) closed via formal_property_run
    # (real SymbiYosys with the built-in ABC engines: abc pdr unbounded safety
    # + abc bmc3 disclosed-bound functional BMC — no external SMT solver).
    # The table is EMPTY: every canonical step now gates on a real OSS engine.
    assert F._PLATFORM_CAPABILITY_GAPS == {}


def test_missing_gap_step_converts_to_skipped_with_named_flag(tmp_path,
                                                              monkeypatch):
    # The conversion MECHANISM stays pinned (a future genuine gap must still
    # surface as a disclosed SKIPPED-CONDITION, never a silent MISSING) via a
    # synthetic entry — the real table is empty since v1.3.99.
    monkeypatch.setitem(F._PLATFORM_CAPABILITY_GAPS, 99, "cap:test_synthetic")
    r = F.check_step(tmp_path, _step(99), waivers={})
    assert r.status == "SKIPPED-CONDITION", r.status
    joined = " ".join(r.reasons)
    assert "cap:test_synthetic" in joined, joined
    assert "MISSING" in joined  # the conversion is disclosed, not silent


def test_formal_step_no_longer_masked(tmp_path):
    # v1.3.99 — step 5 left the gap table: an absent formal proof now reports
    # the honest natural MISSING (the runner's formal_not_run.json sentinel
    # separately promotes an honest self-skip via #608 when it exists).
    r = F.check_step(tmp_path, _step(5), waivers={})
    assert r.status == "MISSING", r.status


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
