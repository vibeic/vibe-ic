"""v0.2.67 substance-not-existence sign-off gate regressions.

Pins the #437 fix (ORGANIC-20260606-existence-only-signoff-gates,
CRITICAL). The audited rot, per sub-item:

  (a) tapeout checklist marked DRC satisfied via an EXISTS check — it
      read the clean detailed-router DRC while the KLayout SIGNOFF DRC
      beside it carried 204k violations it never counted;
  (b) foundry-handoff audit PASSed packs whose members self-report
      cell_count=-1 / pdk=unknown and carry TODO/TBD markers;
  (c) multi-corner STA claimed with an EMPTY per_corner dir, or with
      byte-identical single-corner copies;
  (d) post-layout-sim PASS flag self-disclosed "no SDF re-sim run"
      (escalation pinned in test_post_layout_sim_check.py; the cap-gap
      channel in test_v0_2_63_platform_capability_gaps.py — here we pin
      the RUNNER source no longer fabricates pass.flag);
  (e) waiver parser ignored the `rationale` field, displaying valid
      waivers as "(no reason)" / WAIVED:0;
  (f) orchestrator said PASS_WITH_WAIVERS while its own completion audit
      and final summary said FAIL — contradictory verdict surfaces.

chip-AGNOSTIC: synthetic fixtures + source-shape pins only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gdsii  # noqa: E402
import _si_signoff_fixture  # noqa: E402

# 2026-07-27 (review follow-up): the tape-out GDS slot credits ONLY the flow's
# declared stream-out artefact (phase3/stage4/gds/*.gds), and only when it
# carries real GDSII substance. This file's subject is not the GDS slot; it
# just needs that slot satisfied, so its tape-out artefact is now a real
# minimal GDSII stream at the declared path rather than a text placeholder.

from _source_pin import func_src

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eda_report_audit as ERA       # noqa: E402
import flow_compliance_check as F    # noqa: E402
import signoff_audit as SA           # noqa: E402
import phase3_one_shot_runner as P3  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


# ── (a) tapeout DRC gates on the COUNT of the SIGNOFF report ───────────────

def _tapeout_base(tmp_path):
    (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
    _gdsii.write_gdsii(tmp_path / "phase3/stage4/gds/chip_top.gds")
    (tmp_path / "synth_netlist.v").write_text("module chip_top(); endmodule")
    (tmp_path / "timing_final.rpt").write_text("timing report")
    # 2026-07-27: tapeout mode gained a fifth LVS pillar. This fixture is
    # about the DRC slot's substance rule; it needs a genuine LVS match so
    # the DRC assertions are not masked by a missing-LVS FAIL.
    (tmp_path / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/phase3/lvs.rpt").write_text(
        "Netlists match uniquely.\nFinal result: Circuits match uniquely.\n")
    # 2026-07-28: tape-out mode gained an SI (crosstalk-delay) blocking
    # condition. This fixture is about the DRC slot, so it carries a PROVED
    # SI verdict — without one every case here would collapse onto the
    # SI refusal and stop discriminating what it exists to pin.
    _si_signoff_fixture.write_proved_si_report(tmp_path)


def test_tapeout_drc_fails_on_nonzero_signoff_count(tmp_path):
    _tapeout_base(tmp_path)
    # the observed failing shape: clean router DRC + violation-laden
    # KLayout signoff DRC in the SAME project — the signoff one must win
    (tmp_path / "drc_router.rpt").write_text(
        "detailed_route\nTotal violations: 0\n")
    (tmp_path / "drc_signoff.rpt").write_text(
        "<report-database>\n" + "<item>x</item>\n" * 7
        + "</report-database>\n")
    SA._LENIENT = False
    result = SA._check_tapeout(tmp_path)
    assert result.passed is False
    viol = [f for f in result.findings
            if f.rule == "TAPEOUT_DRC_VIOLATIONS"]
    assert viol and "7" in viol[0].message
    assert "signoff" in viol[0].file


def test_tapeout_drc_unparseable_count_refuses_pass(tmp_path):
    _tapeout_base(tmp_path)
    (tmp_path / "drc_final.rpt").write_text("looks like a report\n")
    result = SA._check_tapeout(tmp_path)
    assert any(f.rule == "TAPEOUT_DRC_UNPARSED" and f.severity == "ERROR"
               for f in result.findings)


def test_tapeout_drc_clean_parsed_count_passes(tmp_path):
    _tapeout_base(tmp_path)
    (tmp_path / "drc_signoff.rpt").write_text(
        "<report-database>\n</report-database>\n")
    SA._LENIENT = False
    result = SA._check_tapeout(tmp_path)
    assert any(f.rule == "TAPEOUT_DRC_CLEAN" for f in result.findings)
    assert result.passed is True


# ── (c) multi-corner STA substance in eda_report_audit ─────────────────────

def _sta_base(tmp_path):
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(
        "Startpoint: a\nEndpoint: b\nPath Type: max\n"
        "slack (MET)\nwns 0.00\ntns 0.00\nsetup hold\n"
        "OpenSTA report_checks\n")
    return sta


def test_sta_empty_per_corner_dir_fails(tmp_path):
    sta = _sta_base(tmp_path)
    (sta / "per_corner").mkdir()
    result = ERA._check_sta(tmp_path)
    assert result.passed is False
    assert any(f.rule == "STA_PER_CORNER_EMPTY" for f in result.findings)


def test_sta_identical_corner_copies_fail(tmp_path):
    sta = _sta_base(tmp_path)
    pc = sta / "per_corner"
    pc.mkdir()
    body = (sta / "post_route_timing.rpt").read_text()
    for c in ("SS", "TT", "FF"):
        (pc / f"sta_{c}.rpt").write_text(body)  # byte-identical copies
    result = ERA._check_sta(tmp_path)
    assert result.passed is False
    assert any(f.rule == "STA_CORNERS_NOT_DISTINCT" for f in result.findings)
    assert result.summary["corner_reports_distinct"] == 1


def test_sta_single_corner_report_fails_the_claim(tmp_path):
    sta = _sta_base(tmp_path)
    pc = sta / "per_corner"
    pc.mkdir()
    (pc / "sta_TT.rpt").write_text("slack (MET)\nPath Type: max\n")
    result = ERA._check_sta(tmp_path)
    assert any(f.rule == "STA_CORNERS_NOT_DISTINCT" for f in result.findings)


def test_sta_two_distinct_corners_pass(tmp_path):
    sta = _sta_base(tmp_path)
    pc = sta / "per_corner"
    pc.mkdir()
    (pc / "sta_SS.rpt").write_text(
        "Startpoint: a\nPath Type: max\nslack (MET) 1.2\nOpenSTA\n")
    (pc / "sta_FF.rpt").write_text(
        "Startpoint: a\nPath Type: max\nslack (MET) 3.4\nOpenSTA\n")
    result = ERA._check_sta(tmp_path)
    assert result.summary["multi_corner_claim_not_broken"] is True


def test_sta_no_per_corner_dir_is_no_claim(tmp_path):
    _sta_base(tmp_path)
    result = ERA._check_sta(tmp_path)
    assert result.summary["corner_dirs_found"] == 0
    assert result.summary["multi_corner_claim_not_broken"] is True


# ── (d) runner source no longer fabricates sim_postlayout/pass.flag ───────

def test_runner_emits_skip_selfreport_not_pass_flag():
    i = _P3_SRC.index("Step 29: SDF emit")  # v2.3 renumber
    # v1.3.94 — widened: the REAL SDF-annotated gate sim (sdf_gate_sim.run) now
    # runs FIRST; the honest skip self-report is the FALLBACK when no results.log
    # is produced (never a fabricated pass.flag).
    # v1.3.99 — widened again: the DT2 path-delay-fault producer now sits
    # between the SDF sim and the #437 fallback note.
    # v1.4.5 — widened again: the DT3 (SDD) + Step-27 (MCF) producers land in
    # the same span (the marker is now ~7.85k chars from the Step-29 anchor).
    # #146 — widened again: the DT1 transition-coverage producer now sits in the
    # same span (DT1/DT2 phase3 parity), pushing the marker to ~10.2k chars.
    window = _P3_SRC[i:i + 11500]
    assert "sdf_gate_sim" in window          # the real SDF sim runs
    assert 'sim_pl_out / "pass.flag"' not in window
    assert "sdf_sim_skipped.json" in window  # fallback skip note still present
    assert "SKIPPED-CONDITION" in window
    assert "#437" in window


def test_runner_no_single_corner_standin_in_multicorner_sta():
    window = func_src(_P3_SRC, "_emit_multi_corner_sta")
    # the old fallback copied the single-corner TT report verbatim
    assert "rpt.write_text(single_rpt.read_text())" not in window
    assert "unsubstantiated multi-corner claim" in window


def test_capability_gap_covers_step_28():
    # v1.3.94 — Step 29 (SDF-annotated gate sim) was CLOSED this campaign
    # (iverilog $sdf_annotate real sim), so it is no longer a cap-gap; Step 28
    # (PERC) is enforced, never a gap. 13 LEC was CLOSED (Yosys equiv,
    # ignore-miss-func). v1.3.99 — 5 (formal) closed too: the table is EMPTY.
    assert 29 not in F._PLATFORM_CAPABILITY_GAPS
    assert 28 not in F._PLATFORM_CAPABILITY_GAPS
    assert F._PLATFORM_CAPABILITY_GAPS == {}


# ── (e) waiver parser honours the `rationale` field ────────────────────────

def test_waiver_rationale_field_is_normalized_to_reason(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": 24,
            "rationale": "IR-drop tool unavailable on this PDK; "
                         "documented in ticket VIBE-1.",
            "ticket": "VIBE-1",
            "approver": "user",
            "review_required": True,
        }]
    }))
    waivers = F._load_waivers(tmp_path)
    assert 24 in waivers
    assert waivers[24].get("reason", "").startswith("IR-drop tool")


def test_waiver_explicit_reason_still_wins(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": 25, "reason": "explicit reason text wins",
            "rationale": "ignored when reason present",
            "ticket": "VIBE-2", "approver": "user",
            "review_required": True,
        }]
    }))
    waivers = F._load_waivers(tmp_path)
    assert waivers[25]["reason"] == "explicit reason text wins"


# ── (f) orchestrator headline derives from the completion audit ────────────

def _audit(tmp_path, verdict):
    p = tmp_path / "reports" / "audit"
    p.mkdir(parents=True, exist_ok=True)
    (p / "phase23_completion_audit.json").write_text(
        json.dumps({"verdict": verdict}))


def test_headline_downgrades_to_completion_audit_fail(tmp_path):
    _audit(tmp_path, "FAIL")
    headline, audit_v, note = P3._derive_headline_verdict(
        tmp_path, "PASS_WITH_WAIVERS")
    assert headline == "FAIL" and audit_v == "FAIL"
    assert "#437f" in note


def test_headline_takes_weaker_tier_not_stronger(tmp_path):
    # audit PASS must never UPGRADE an own-steps FAIL
    _audit(tmp_path, "PASS")
    headline, _, _ = P3._derive_headline_verdict(tmp_path, "FAIL")
    assert headline == "FAIL"


def test_headline_without_audit_keeps_steps_verdict(tmp_path):
    headline, audit_v, note = P3._derive_headline_verdict(
        tmp_path, "PASS_WITH_WAIVERS")
    assert headline == "PASS_WITH_WAIVERS" and audit_v is None
    assert "absent" in note
