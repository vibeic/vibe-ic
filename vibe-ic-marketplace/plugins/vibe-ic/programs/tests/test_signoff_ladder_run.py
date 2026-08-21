"""Unit tests for `signoff_ladder_run.py` (release-gate wired)."""
import importlib
import json

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("signoff_ladder_run")


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# A genuine netgen unique-match transcript.
_LVS_MATCH = """\
Netlists match uniquely.
Final result: Circuits match uniquely.
"""

# A power-pin-only mismatch — the universal sky130 OSS artifact. The only
# failing rows are power/tie nets (note the space before `|`, the shape the
# power-row detector keys on); no signal-net evidence.
_LVS_POWER_PIN_ONLY = """\
Top level cell failed pin matching.
Cell pin lists for design and design do not match.
  VPWR |(no matching pin)
  VGND |(no matching pin)
  VPB  |(no matching pin)
  VNB  |(no matching pin)
"""

# A real signal-net mismatch (top-level `(no pin, node is …)` rows).
_LVS_SIGNAL = """\
Top level cell failed pin matching.
(no pin, node is o_data[7])                 |o_wdata[7]
(no pin, node is o_data[6])                 |o_wdata[6]
Final result: Top level cell failed pin matching.
"""

# A full-rigor sign-off STA report.
_STA_FULL = """\
Startpoint: reg_a
Endpoint: reg_b
   0.42   slack (MET)
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
Recovery/Removal checks:
   reg_rst recovery  0.31   slack (MET)
   reg_rst removal   0.12   slack (MET)
Min Pulse Width checks:
   clk min_pulse_width  1.80  slack (MET)
"""

# An optimistic STA report (setup/hold MET only — no OCV / recovery / MPW).
_STA_OPTIMISTIC = """\
Startpoint: reg_a
Endpoint: reg_b
   0.42   slack (MET)
"""

_RAM_NO_WRAPPER = """\
module myram(input clk, input we, input [3:0] addr,
             input [7:0] din, output reg [7:0] dout);
    reg [7:0] mem [0:15];
    always @(posedge clk) begin
        if (we) mem[addr] <= din;
        dout <= mem[addr];
    end
endmodule
"""

_RAMLESS = """\
module g(input a, output y);
    assign y = ~a;
endmodule
"""

_EM_JMAX = {"layers": {"met1": {"kind": "routing", "thickness_um": 0.35,
                                "width_um": 0.14, "jmax_mA_per_um": 2.8}}}
_EM_HEADER = "Node0 Layer,Node0 X,Node0 Y,Node1 Layer,Node1 X,Node1 Y,Current\n"


def _em_csv(current_a):
    return _EM_HEADER + f"met1,0,0,met1,1,0,{current_a}\n"


class TestPerTierChecks:
    def test_drc_pass(self, tmp_path):
        _write_json(tmp_path / "reports/drc/full_deck.json", {"violations": 0})
        assert mod.check_tier_1_drc(tmp_path).verdict == "PASS"

    def test_drc_fail(self, tmp_path):
        _write_json(tmp_path / "reports/drc/full_deck.json",
                    {"violations": 1780})
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "FAIL"
        assert r.details["violations"] == 1780

    def test_drc_not_run(self, tmp_path):
        assert mod.check_tier_1_drc(tmp_path).verdict == "NOT_RUN"

    def test_pdn_pass(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/pdn.json", {"specialnets": 2})
        assert mod.check_tier_2_pdn(tmp_path).verdict == "PASS"

    def test_pdn_fail_zero_specialnets(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/pdn.json", {"specialnets": 0})
        assert mod.check_tier_2_pdn(tmp_path).verdict == "FAIL"

    def test_ir_pass_under_budget(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/ir_drop.json", {"worst_ir_uv": 20.0})
        assert mod.check_tier_2_ir(tmp_path, budget_uv=35.0).verdict == "PASS"

    def test_ir_fail_over_budget(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/ir_drop.json", {"worst_ir_uv": 50.0})
        assert mod.check_tier_2_ir(tmp_path, budget_uv=35.0).verdict == "FAIL"

    def test_antenna_both_clean(self, tmp_path):
        _write_json(tmp_path / "reports/antenna/magic.json", {"violations": 0})
        _write_json(tmp_path / "reports/antenna/klayout.json", {"violations": 0})
        assert mod.check_tier_3_antenna(tmp_path).verdict == "PASS"

    def test_antenna_one_violator(self, tmp_path):
        _write_json(tmp_path / "reports/antenna/magic.json", {"violations": 5})
        _write_json(tmp_path / "reports/antenna/klayout.json", {"violations": 0})
        assert mod.check_tier_3_antenna(tmp_path).verdict == "FAIL"

    def test_lvs_device_pass(self, tmp_path):
        _write_json(tmp_path / "reports/lvs/device_class.json",
                    {"device_class_match": True, "layout": 261,
                     "schematic": 261})
        assert mod.check_tier_4_lvs_device(tmp_path).verdict == "PASS"

    def test_lvs_net_waived_triage(self, tmp_path):
        _write_json(tmp_path / "reports/lvs/net_level.json",
                    {"verdict": "WAIVED",
                     "rationale": "blackbox-macro open-source gap"})
        assert mod.check_tier_4_5_lvs_net(tmp_path).verdict == "WAIVED"

    def test_latchup_pass(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/tapcell_density.json",
                    {"tapcells_per_mm2": 384})
        assert mod.check_tier_5_latchup(tmp_path).verdict == "PASS"

    def test_latchup_fail_zero(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/tapcell_density.json",
                    {"tapcells_per_mm2": 0})
        assert mod.check_tier_5_latchup(tmp_path).verdict == "FAIL"


class TestEMDensityTier:
    """The EM tier is the REAL J-vs-Jmax gate, not the decap-count proxy."""

    def test_absent_report_not_run(self, tmp_path):
        r = mod.check_tier_2_em(tmp_path)
        assert r.verdict == "NOT_RUN"

    def test_present_report_no_jmax_skips_not_run(self, tmp_path):
        # Report present but NO Jmax reference → honest SKIP, never the old
        # decap proxy, never a fabricated PASS.
        _write(tmp_path / "reports/phase3/em_segments.csv", _em_csv(1e-4))
        r = mod.check_tier_2_em(tmp_path)
        assert r.verdict == "NOT_RUN"
        assert r.details["em_verdict"] == "SKIPPED"

    def test_under_jmax_pass(self, tmp_path):
        _write(tmp_path / "reports/phase3/em_segments.csv", _em_csv(1e-4))
        _write_json(tmp_path / "reports/phase3/em_jmax.json", _EM_JMAX)
        r = mod.check_tier_2_em(tmp_path)
        assert r.verdict == "PASS"

    def test_over_jmax_fail(self, tmp_path):
        _write(tmp_path / "reports/phase3/em_segments.csv", _em_csv(5e-4))
        _write_json(tmp_path / "reports/phase3/em_jmax.json", _EM_JMAX)
        r = mod.check_tier_2_em(tmp_path)
        assert r.verdict == "FAIL"


class TestLVSTapeoutTier:
    def test_genuine_match_pass(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        assert mod.check_tier_lvs_tapeout(tmp_path).verdict == "PASS"

    def test_power_pin_only_is_waived_pending_not_pass(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_POWER_PIN_ONLY)
        r = mod.check_tier_lvs_tapeout(tmp_path)
        assert r.verdict == "WAIVED_PENDING"
        assert r.verdict != "PASS"

    def test_signal_net_mismatch_fail(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_SIGNAL)
        assert mod.check_tier_lvs_tapeout(tmp_path).verdict == "FAIL"

    def test_absent_report_not_run(self, tmp_path):
        assert mod.check_tier_lvs_tapeout(tmp_path).verdict == "NOT_RUN"


class TestSTARigorTier:
    def test_full_rigor_pass(self, tmp_path):
        _write(tmp_path / "phase3/stage3/pnr/post_route_timing.rpt", _STA_FULL)
        assert mod.check_tier_sta_rigor(tmp_path).verdict == "PASS"

    def test_optimistic_fail(self, tmp_path):
        _write(tmp_path / "phase3/stage3/pnr/post_route_timing.rpt",
               _STA_OPTIMISTIC)
        assert mod.check_tier_sta_rigor(tmp_path).verdict == "FAIL"

    def test_absent_not_run(self, tmp_path):
        assert mod.check_tier_sta_rigor(tmp_path).verdict == "NOT_RUN"


class TestMBISTTier:
    def test_ram_without_wrapper_fail(self, tmp_path):
        r = mod.check_tier_mbist(tmp_path, sources=[("ram.v", _RAM_NO_WRAPPER)])
        assert r.verdict == "FAIL"

    def test_ramless_is_na(self, tmp_path):
        r = mod.check_tier_mbist(tmp_path, sources=[("g.v", _RAMLESS)])
        assert r.verdict == "N/A"

    def test_no_sources_not_run(self, tmp_path):
        assert mod.check_tier_mbist(tmp_path, sources=[]).verdict == "NOT_RUN"


class TestAggregateVerdict:
    def test_all_pass_no_waivers(self):
        assert mod.aggregate_verdict(
            [mod.TierResult("T1", "DRC", "PASS")]) == "PASS"

    def test_any_fail(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T5", "Latchup", "FAIL")]
        assert mod.aggregate_verdict(tiers) == "FAIL"

    def test_waived_promotes_to_pass_with_waivers(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T4.5", "LVS net", "WAIVED")]
        assert mod.aggregate_verdict(tiers) == "PASS_WITH_WAIVERS"

    # ----- absent evidence must NOT release (the #520 core) -----
    def test_absent_evidence_does_not_release(self):
        # A release-gating tier nobody ran is NOT a pass. This is the branch
        # that used to hand an all-NOT_RUN design a PASS_WITH_WAIVERS.
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T3_ESD", "ESD/pad-ring", "NOT_RUN")]
        v = mod.aggregate_verdict(tiers)
        assert v == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert v not in mod.RELEASING_VERDICTS

    def test_nothing_checked_at_all_does_not_release(self):
        # The reported shape: every tier honestly NOT_RUN, nothing verified.
        tiers = [mod.TierResult(f"T{i}", f"tier {i}", "NOT_RUN")
                 for i in range(18)]
        v = mod.aggregate_verdict(tiers)
        assert v == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert v not in mod.RELEASING_VERDICTS

    def test_reviewed_waiver_and_absent_evidence_are_distinct(self):
        # Constraint the fix must not collapse: a REVIEWED, documented waiver
        # is a decision somebody owns and still releases; an unrun tier is
        # nobody deciding anything and does not. Same ladder, same PASS
        # neighbour, opposite release outcome.
        waived = [mod.TierResult("T1", "DRC", "PASS"),
                  mod.TierResult("T_XOR", "Layout XOR", "WAIVED")]
        unrun = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T_XOR", "Layout XOR", "NOT_RUN")]
        assert mod.aggregate_verdict(waived) == "PASS_WITH_WAIVERS"
        assert mod.aggregate_verdict(waived) in mod.RELEASING_VERDICTS
        assert mod.aggregate_verdict(unrun) == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert mod.aggregate_verdict(unrun) not in mod.RELEASING_VERDICTS
        assert mod.aggregate_verdict(waived) != mod.aggregate_verdict(unrun)

    def test_fail_dominates_absent_evidence(self):
        tiers = [mod.TierResult("T1", "DRC", "FAIL"),
                 mod.TierResult("T3_ESD", "ESD", "NOT_RUN")]
        assert mod.aggregate_verdict(tiers) == "FAIL"

    def test_waived_pending_dominates_absent_evidence(self):
        tiers = [mod.TierResult("T4.5", "LVS tapeout", "WAIVED_PENDING"),
                 mod.TierResult("T3_ESD", "ESD", "NOT_RUN")]
        assert mod.aggregate_verdict(tiers) == "NOT_RELEASED"

    def test_absent_evidence_dominates_warn(self):
        # Both block, but "nothing was checked" is the more actionable label
        # and must not be masked by a softer WARN.
        tiers = [mod.TierResult("T2", "PDN", "WARN"),
                 mod.TierResult("T3_ESD", "ESD", "NOT_RUN")]
        assert mod.aggregate_verdict(tiers) == mod.NOT_RELEASED_EVIDENCE_ABSENT

    def test_absent_evidence_dominates_a_reviewed_waiver(self):
        # A waiver on one tier cannot buy a release for a tier nobody ran.
        tiers = [mod.TierResult("T_XOR", "Layout XOR", "WAIVED"),
                 mod.TierResult("T3_ESD", "ESD", "NOT_RUN")]
        v = mod.aggregate_verdict(tiers)
        assert v == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert v not in mod.RELEASING_VERDICTS

    # ----- advisory tiers: absence is not missing sign-off evidence -----
    def test_advisory_tier_absence_never_blocks(self):
        # An advisory row (the DRC heatmap picture) is not sign-off evidence,
        # so its absence alone must not withhold a release — otherwise the fix
        # would block every design forever on a missing visualisation.
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T1.5", "DRC heatmap", "NOT_RUN",
                                release_gating=False)]
        assert mod.aggregate_verdict(tiers) == "PASS"
        assert mod.evidence_absent_tiers(tiers) == []

    def test_advisory_tier_fail_still_blocks(self):
        # Advisory means "absence does not block", NOT "this tier cannot
        # block" — a real FAIL on one still stops the release.
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T1.5", "DRC heatmap", "FAIL",
                                release_gating=False)]
        assert mod.aggregate_verdict(tiers) == "FAIL"

    def test_tiers_are_release_gating_by_default(self):
        # A tier author must opt OUT of gating explicitly; forgetting the flag
        # must fail safe (blocking), never silently release.
        assert mod.TierResult("Tx", "new tier", "NOT_RUN").release_gating is True

    def test_warn_overrides_pass(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T2", "PDN", "WARN")]
        assert mod.aggregate_verdict(tiers) == "WARN"

    def test_waived_pending_is_not_released(self):
        # §4.05: a POWER_PIN_ONLY waiver blocks release (NOT_RELEASED).
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T4.5", "LVS tapeout", "WAIVED_PENDING")]
        v = mod.aggregate_verdict(tiers)
        assert v == "NOT_RELEASED"
        assert v not in mod.RELEASING_VERDICTS

    def test_incomplete_is_not_released(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("Tx", "precheck", "INCOMPLETE")]
        assert mod.aggregate_verdict(tiers) == "NOT_RELEASED"

    def test_na_is_neutral(self):
        # A RAM-less MBIST N/A tier never demotes an otherwise-clean PASS.
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T_MBIST", "MBIST", "N/A")]
        assert mod.aggregate_verdict(tiers) == "PASS"

    def test_fail_dominates_waived_pending(self):
        tiers = [mod.TierResult("T1", "DRC", "FAIL"),
                 mod.TierResult("T4.5", "LVS tapeout", "WAIVED_PENDING")]
        assert mod.aggregate_verdict(tiers) == "FAIL"


class TestReleasedRespectsMode:
    """`triage`'s own docstring says "Nothing here claims a tapeout" — so the
    diagnostic ladder must never print a release flag that contradicts it."""

    def test_triage_never_releases_however_clean_the_verdict(self):
        for verdict in mod.RELEASING_VERDICTS:
            assert mod.is_released(verdict, "triage") is False

    def test_tapeout_releases_on_a_releasing_verdict(self):
        for verdict in mod.RELEASING_VERDICTS:
            assert mod.is_released(verdict, "tapeout") is True

    def test_no_mode_releases_a_blocking_verdict(self):
        for verdict in ("FAIL", "WARN", "NOT_RELEASED",
                        mod.NOT_RELEASED_EVIDENCE_ABSENT):
            for mode in ("triage", "tapeout"):
                assert mod.is_released(verdict, mode) is False

    def test_triage_report_says_why_it_is_not_releasing(self, tmp_path):
        rep = mod.run_ladder(tmp_path, mode="triage")
        assert rep.as_dict()["released"] is False
        assert "triage" in rep.release_note()


class TestRunLadder:
    def test_triage_ladder_returns_10_tiers(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        assert rep.mode == "triage"
        assert len(rep.tiers) == 10

    def test_attribution(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        assert rep.as_dict()["emitted_by"] == (
            f"signoff_ladder_run v{shipped_plugin_version()} (release-gate-wired)")

    def test_tapeout_adds_release_tiers(self, tmp_path):
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        ids = [t.tier_id for t in rep.tiers]
        assert "T4.5_LVS_TAPEOUT" in ids
        assert "T4.5_LVS_NET" not in ids          # triage tier is swapped out
        assert "T_STA_RIGOR" in ids
        assert "T_MBIST" in ids
        assert "T2_EM" in ids

    # ----- the §4.05 negative: POWER_PIN_ONLY no longer releases -----
    def test_power_pin_only_does_not_release_at_tapeout(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_POWER_PIN_ONLY)
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        lvs = [t for t in rep.tiers if t.tier_id == "T4.5_LVS_TAPEOUT"][0]
        assert lvs.verdict == "WAIVED_PENDING"
        assert rep.overall_verdict == "NOT_RELEASED"
        assert rep.overall_verdict not in mod.RELEASING_VERDICTS
        assert rep.as_dict()["released"] is False

    def test_power_pin_only_still_shown_as_a_waiver_in_triage(self, tmp_path):
        # Contrast: the triage tier still SHOWS the reasoned waiver (only the
        # tapeout tier refuses to credit it) — but triage NEVER releases, so
        # the diagnostic ladder cannot be read as a tapeout claim.
        _write_json(tmp_path / "reports/lvs/net_level.json",
                    {"verdict": "WAIVED", "rationale": "OSS blackbox-macro gap"})
        rep = mod.run_ladder(tmp_path, mode="triage")
        lvs = [t for t in rep.tiers if t.tier_id == "T4.5_LVS_NET"][0]
        assert lvs.verdict == "WAIVED"
        assert rep.as_dict()["released"] is False

    def test_genuine_lvs_match_alone_does_not_release(self, tmp_path):
        # A genuine LVS match is one tier out of eighteen. With DRC, PDN, IR,
        # EM, antenna, ESD, latch-up, STA rigor, dynamic IR, metal density,
        # aging, thermal, DFT and post-layout LEC all unrun, the ladder has
        # nothing to release on — §4.05.
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        lvs = [t for t in rep.tiers if t.tier_id == "T4.5_LVS_TAPEOUT"][0]
        assert lvs.verdict == "PASS"
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert rep.as_dict()["released"] is False

    def test_signal_net_mismatch_fails_release(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_SIGNAL)
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        assert rep.overall_verdict == "FAIL"


class TestDynamicIRTier:
    """Transient (di/dt) IR-drop — distinct from the static ir_drop tier."""

    def test_absent_report_not_run(self, tmp_path):
        assert mod.check_tier_dynamic_ir(tmp_path).verdict == "NOT_RUN"

    def test_under_budget_pass(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/dynamic_ir.json",
                    {"max_dynamic_drop_mv": 90.0, "vdd_v": 1.8})
        # budget = 10% * 1.8 V * 1000 = 180 mV; 90 < 180.
        assert mod.check_tier_dynamic_ir(tmp_path).verdict == "PASS"

    def test_over_budget_fail(self, tmp_path):
        # §4.05 negative: a transient droop over budget FAILs (does not pass).
        _write_json(tmp_path / "reports/phase3/dynamic_ir.json",
                    {"max_dynamic_drop_mv": 250.0, "vdd_v": 1.8})
        assert mod.check_tier_dynamic_ir(tmp_path).verdict == "FAIL"

    def test_static_ir_drop_json_is_not_read_as_dynamic(self, tmp_path):
        # The STATIC ir_drop.json must NOT masquerade as a dynamic sign-off.
        _write_json(tmp_path / "reports/phase3/ir_drop.json",
                    {"worst_ir_uv": 20.0, "budget_uv": 90000.0})
        assert mod.check_tier_dynamic_ir(tmp_path).verdict == "NOT_RUN"


class TestMetalDensityTier:
    """Per-layer metal density — distinct axis from row/core-util density."""

    def test_absent_report_not_run(self, tmp_path):
        assert mod.check_tier_metal_density(tmp_path).verdict == "NOT_RUN"

    def test_within_window_pass(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/metal_density.json",
                    {"layers": {"met1": 0.42, "met2": 0.55, "met3": 0.48}})
        assert mod.check_tier_metal_density(tmp_path).verdict == "PASS"

    def test_below_window_fail(self, tmp_path):
        # §4.05 negative: a layer below the CMP min-density window FAILs.
        _write_json(tmp_path / "reports/phase3/metal_density.json",
                    {"layers": {"met1": 0.12, "met2": 0.55}})
        r = mod.check_tier_metal_density(tmp_path)
        assert r.verdict == "FAIL"
        assert "met1" in r.notes

    def test_row_util_density_json_is_not_read(self, tmp_path):
        # reports/density.json is ROW/core utilization — NOT per-layer metal
        # density. Reading it here would gate on the wrong axis.
        _write_json(tmp_path / "reports/density.json",
                    {"row_utilization_pct": 99.0})
        assert mod.check_tier_metal_density(tmp_path).verdict == "NOT_RUN"


class TestAgingSTATier:
    def test_absent_report_not_run(self, tmp_path):
        # The open PDK ships no foundry aging Liberty → honest NOT_RUN.
        assert mod.check_tier_aging_sta(tmp_path).verdict == "NOT_RUN"

    def test_aged_slack_met_pass(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/aging_sta.json",
                    {"worst_slack_ns": 0.15, "is_aging": True,
                     "aging_corner": "ss_aging_10yr late=1.10"})
        assert mod.check_tier_aging_sta(tmp_path).verdict == "PASS"

    def test_aged_slack_violated_fail(self, tmp_path):
        # §4.05 negative: negative slack under the aging corner FAILs.
        _write_json(tmp_path / "reports/phase3/aging_sta.json",
                    {"worst_slack_ns": -0.20, "aging_corner": "ss_nbti_eol"})
        assert mod.check_tier_aging_sta(tmp_path).verdict == "FAIL"

    def test_no_aging_evidence_skips_not_run(self, tmp_path):
        # A fresh report mislabeled aging has no aging evidence → SKIP (NOT_RUN),
        # never a false aging pass.
        _write_json(tmp_path / "reports/phase3/aging_sta.json",
                    {"worst_slack_ns": 0.15})
        assert mod.check_tier_aging_sta(tmp_path).verdict == "NOT_RUN"


class TestThermalTier:
    def test_absent_power_not_run(self, tmp_path):
        assert mod.check_tier_thermal(tmp_path).verdict == "NOT_RUN"

    def test_within_limit_pass(self, tmp_path):
        _write(tmp_path / "reports/phase3/power.rpt",
               "Total Power = 0.05 W\nleakage dynamic internal\n")
        _write_json(tmp_path / "floorplan.json", {"die_area_mm2": 1.0})
        assert mod.check_tier_thermal(tmp_path).verdict == "PASS"

    def test_over_limit_fail(self, tmp_path):
        # §4.05 negative: 5 W over 1 mm² = 5 W/mm² >= 1.0 limit → FAIL.
        _write(tmp_path / "reports/phase3/power.rpt",
               "Total Power = 5.0 W\nleakage dynamic internal\n")
        _write_json(tmp_path / "floorplan.json", {"die_area_mm2": 1.0})
        assert mod.check_tier_thermal(tmp_path).verdict == "FAIL"

    def test_power_present_but_no_die_area_skips_not_run(self, tmp_path):
        _write(tmp_path / "reports/phase3/power.rpt", "Total Power = 0.05 W\n")
        assert mod.check_tier_thermal(tmp_path).verdict == "NOT_RUN"


class TestDFTSignoffTier:
    def _pass_coverage(self, tmp_path):
        _write_json(tmp_path / "reports/phase2/dft/coverage.json",
                    {"coverage_pct": 99.0, "target_pct": 98.0,
                     "transition": {"engine_limited": True,
                                    "reason": "OSS ATPG has no at-speed engine"}})
        _write_json(tmp_path / "reports/phase2/dft/bsdl_plan.json",
                    {"verdict": "N_A", "padded": False})
        # The at-speed mechanism plan. `fault_atpg_run.run_transition_atpg` —
        # the only producer of the transition block this fixture stands in for
        # — writes it on every engine-limited run before it emits the record,
        # so a fixture without it was describing a state the flow does not
        # produce. `dft_signoff_check` now requires the document the
        # ENGINE_LIMITED tier calls "documented"; this is the artefact, not a
        # relaxation of the check.
        plan = tmp_path / "phase2/stage2/dft/transition_atpg_plan.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(
            "# At-speed (launch-off-capture) transition ATPG plan\n\n"
            "Mechanism, clocking, capture window and the engine limitation "
            "this tier is accepted on.\n" + ("detail line\n" * 20))

    def test_absent_evidence_not_run(self, tmp_path):
        assert mod.check_tier_dft_signoff(tmp_path).verdict == "NOT_RUN"

    def test_full_dft_signoff_pass(self, tmp_path):
        self._pass_coverage(tmp_path)
        assert mod.check_tier_dft_signoff(tmp_path).verdict == "PASS"

    def test_low_stuck_at_fail(self, tmp_path):
        # §4.05 negative: stuck-at 50% < 95% foundry floor → FAIL.
        _write_json(tmp_path / "reports/phase2/dft/coverage.json",
                    {"coverage_pct": 50.0, "target_pct": 98.0})
        assert mod.check_tier_dft_signoff(tmp_path).verdict == "FAIL"


class TestLECPostTier:
    def test_absent_not_run(self, tmp_path):
        assert mod.check_tier_lec_post(tmp_path).verdict == "NOT_RUN"

    def test_proven_equivalent_pass(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/lec_post_layout.json",
                    {"verdict": "PROVEN_EQUIVALENT", "total_points": 128,
                     "proven_points": 128, "unproven_points": 0,
                     "non_equivalent_points": 0, "equivalent": True})
        assert mod.check_tier_lec_post(tmp_path).verdict == "PASS"

    def test_unproven_fail(self, tmp_path):
        # §4.05 negative: a bounded/aborted non-proof is NOT a clean pass.
        _write_json(tmp_path / "reports/phase3/lec_post_layout.json",
                    {"verdict": "UNPROVEN", "total_points": 128,
                     "proven_points": 120, "unproven_points": 8,
                     "equivalent": False})
        assert mod.check_tier_lec_post(tmp_path).verdict == "FAIL"

    def test_non_equivalent_fail(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/lec_post_layout.json",
                    {"verdict": "NON_EQUIVALENT", "total_points": 128,
                     "non_equivalent_points": 4, "equivalent": False})
        assert mod.check_tier_lec_post(tmp_path).verdict == "FAIL"


class TestNewSignoffTiersInLadder:
    def test_tapeout_adds_the_six_new_tiers(self, tmp_path):
        ids = [t.tier_id for t in mod.run_ladder(tmp_path, mode="tapeout").tiers]
        for tid in ("T_DYN_IR", "T_METAL_DENSITY", "T_AGING_STA", "T_THERMAL",
                    "T_DFT_SIGNOFF", "T_LEC_POST"):
            assert tid in ids

    def test_triage_omits_the_six_new_tiers(self, tmp_path):
        ids = [t.tier_id for t in mod.run_ladder(tmp_path).tiers]
        for tid in ("T_DYN_IR", "T_METAL_DENSITY", "T_AGING_STA", "T_THERMAL",
                    "T_DFT_SIGNOFF", "T_LEC_POST"):
            assert tid not in ids

    def test_dynamic_ir_over_budget_blocks_release(self, tmp_path):
        # §4.05 end-to-end: an otherwise-releasing tapeout (genuine LVS match)
        # is BLOCKED by a dynamic-IR droop over budget.
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        _write_json(tmp_path / "reports/phase3/dynamic_ir.json",
                    {"max_dynamic_drop_mv": 300.0, "vdd_v": 1.8})
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        dyn = [t for t in rep.tiers if t.tier_id == "T_DYN_IR"][0]
        assert dyn.verdict == "FAIL"
        assert rep.overall_verdict == "FAIL"
        assert rep.as_dict()["released"] is False

    def test_dynamic_ir_under_budget_clears_its_own_tier(self, tmp_path):
        # The tier itself PASSes — but two clean tiers out of eighteen still
        # do not release the ladder (the other sixteen were never run).
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        _write_json(tmp_path / "reports/phase3/dynamic_ir.json",
                    {"max_dynamic_drop_mv": 50.0, "vdd_v": 1.8})
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        dyn = [t for t in rep.tiers if t.tier_id == "T_DYN_IR"][0]
        assert dyn.verdict == "PASS"
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert rep.as_dict()["released"] is False

    def test_metal_density_below_window_blocks_release(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        _write_json(tmp_path / "reports/phase3/metal_density.json",
                    {"layers": {"met1": 0.10}})
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        assert rep.overall_verdict == "FAIL"
        assert rep.as_dict()["released"] is False


class TestReportToMarkdown:
    def test_includes_overall_verdict(self, tmp_path):
        md = mod.report_to_markdown(mod.run_ladder(tmp_path))
        assert "Overall verdict" in md
        assert mod.NOT_RELEASED_EVIDENCE_ABSENT in md

    def test_markdown_release_flag_matches_the_report(self, tmp_path):
        # The printed flag is the SAME computation as the JSON's, so the two
        # emit sites can never disagree about whether the design released.
        # Exercised on a project where the raw verdict and the mode-guarded
        # flag DISAGREE (a fully-evidenced triage run reads PASS but does not
        # release) — on an empty project they coincide and prove nothing.
        d = _build_fully_signed_off(tmp_path)
        _write_json(d / "reports/lvs/net_level.json", {"verdict": "PASS"})
        for mode, expect_released in (("triage", False), ("tapeout", True)):
            rep = mod.run_ladder(d, mode=mode, caravel=False)
            assert rep.overall_verdict in mod.RELEASING_VERDICTS
            assert rep.as_dict()["released"] is expect_released
            assert f"(released={expect_released})" in mod.report_to_markdown(rep)

    def test_markdown_names_the_unrun_gating_tiers(self, tmp_path):
        md = mod.report_to_markdown(mod.run_ladder(tmp_path, mode="tapeout"))
        assert "produced no evidence" in md
        assert "T3_ESD" in md

    def test_doctrine_quote(self, tmp_path):
        md = mod.report_to_markdown(mod.run_ladder(tmp_path))
        assert "doctrine" in md.lower()

    def test_mode_line_present(self, tmp_path):
        md = mod.report_to_markdown(mod.run_ladder(tmp_path, mode="tapeout"))
        assert "Mode: tapeout" in md


# ---------------------------------------------------------------------------
# OLD-tier real-artifact discovery (the dead-legacy-path fix). Each old tier
# now reads the REAL runner artifact (reports/phase3/...) instead of a dead
# legacy path no program writes; §4.05: this can only surface a masked FAIL or
# correct a false-FAIL, NEVER fabricate a pass — an absent artifact still
# NOT_RUNs.
# ---------------------------------------------------------------------------

# A KLayout XML sign-off DRC report (the shape the runner re-stages into
# reports/phase3/drc_signoff.rpt). Empty <items> = clean; N <item> = N viols.
_DRC_KLAYOUT_CLEAN = """\
# Sign-off DRC report (ORGANIC-20260531 Step 31 alias).
# Tool: klayout
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <categories>
  <category><name>li.1</name><description>li.1 : min width : violation</description></category>
 </categories>
 <items>
 </items>
</report-database>
"""


def _drc_klayout_with(n_items):
    items = "\n".join("  <item><category>'li.1'</category></item>"
                      for _ in range(n_items))
    return ("# Tool: klayout\n<?xml version=\"1.0\"?>\n<report-database>\n"
            " <categories>\n  <category><name>li.1</name>"
            "<description>violation</description></category>\n </categories>\n"
            f" <items>\n{items}\n </items>\n</report-database>\n")


# A plain-text OpenROAD/Magic DRC projection carrying an explicit count.
def _drc_text(n):
    return (f"# Tool: openroad\nopenroad / drt-pass: detailed_route invoked\n"
            f"violation report: {n}\n"
            f"DRC clean: {'YES' if n == 0 else 'NO'}\n")


# The runner's real reports/phase3/antenna.json shapes.
_ANTENNA_FAIL = {"tool": "openroad", "net_violations": 14, "pin_violations": 0,
                 "clean": False, "routing_incomplete": False, "verdict": "FAIL"}
_ANTENNA_INCOMPLETE = {"tool": "openroad", "net_violations": None,
                       "pin_violations": None, "clean": True,
                       "routing_incomplete": True, "verdict": "FAIL"}
_ANTENNA_CLEAN = {"tool": "openroad", "net_violations": 0, "pin_violations": 0,
                  "clean": True, "routing_incomplete": False, "verdict": "PASS"}

# The runner's real reports/phase3/ir_drop.json shape (worst 271 µV, own budget
# 90 mV = 5% of 1.8 V). The OLD 35 µV default false-FAILed this real static IR.
_IR_REAL = {"tool": "openroad-psm", "worst_ir_uv": 271.0,
            "budget_uv": 90000.0, "verdict": "PASS"}

_DEF_WITH_SN = """\
VERSION 5.8 ;
DESIGN top ;
SPECIALNETS 2 ;
    - VDD ( a VPWR ) ( b VPWR )
    - VSS ( a VGND ) ( b VGND )
END SPECIALNETS
END DESIGN
"""

_DEF_NO_SN = """\
VERSION 5.8 ;
DESIGN top ;
COMPONENTS 3 ;
END COMPONENTS
END DESIGN
"""


class TestDRCRealDiscovery:
    def test_phase3_klayout_clean_pass(self, tmp_path):
        _write(tmp_path / "reports/phase3/drc_signoff.rpt", _DRC_KLAYOUT_CLEAN)
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "PASS"
        assert r.details["violations"] == 0

    def test_phase3_klayout_violations_fail(self, tmp_path):
        _write(tmp_path / "reports/phase3/drc_signoff.rpt",
               _drc_klayout_with(87))
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "FAIL"
        assert r.details["violations"] == 87

    def test_phase3_text_report_count_fail(self, tmp_path):
        # A router-level violation is still a real defect and keeps its FAIL.
        # FAIL is not waivable; downgrading it would have made it deferrable.
        _write(tmp_path / "reports/phase3/drc_signoff.rpt", _drc_text(5))
        assert mod.check_tier_1_drc(tmp_path).verdict == "FAIL"

    def test_router_projection_clean_is_not_a_signoff_pass(self, tmp_path):
        """`_drc_text` IS the router's own detailed-route projection —
        `# Tool: openroad`, `drt-pass: detailed_route invoked`. This tier is
        named "Full DRC (KLayout/Magic)" and is release-gating; it used to
        return PASS from that log. The router cannot certify physical
        verification, so its CLEAN is NOT_RUN — the state the governed
        waivers.json channel exists for. Its FAIL is unchanged (above): router
        evidence can withhold credit, never grant it, and never remove a
        failure."""
        _write(tmp_path / "reports/phase3/drc_signoff.rpt", _drc_text(0))
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "NOT_RUN", r
        assert r.details["producer"] == "openroad"

    def test_non_router_plain_text_clean_still_passes(self, tmp_path):
        """The plain-text dialect itself is untouched — only the ROUTER as a
        producer is refused."""
        _write(tmp_path / "reports/phase3/drc_signoff.rpt",
               "Magic 8.3.678\ndrc count\ntotal violations: 0\n")
        assert mod.check_tier_1_drc(tmp_path).verdict == "PASS"

    def test_legacy_json_still_read(self, tmp_path):
        # Back-compat: the legacy full_deck.json is still a fallback.
        _write_json(tmp_path / "reports/drc/full_deck.json", {"violations": 3})
        assert mod.check_tier_1_drc(tmp_path).verdict == "FAIL"

    def test_absent_not_run(self, tmp_path):
        # §4.05: genuinely absent → honest NOT_RUN, never a fabricated pass.
        assert mod.check_tier_1_drc(tmp_path).verdict == "NOT_RUN"

    def test_phase3_preferred_over_legacy(self, tmp_path):
        # A clean phase3 report wins over a dirty legacy json (the runner's
        # canonical artifact is authoritative).
        _write(tmp_path / "reports/phase3/drc_signoff.rpt", _DRC_KLAYOUT_CLEAN)
        _write_json(tmp_path / "reports/drc/full_deck.json",
                    {"violations": 999})
        r = mod.check_tier_1_drc(tmp_path)
        assert r.verdict == "PASS"
        assert "phase3" in r.artifact_path


class TestAntennaRealDiscovery:
    def test_real_report_violations_surfaces_masked_fail(self, tmp_path):
        # THE headline fix: the dead legacy path hid a real antenna FAIL.
        _write_json(tmp_path / "reports/phase3/antenna.json", _ANTENNA_FAIL)
        r = mod.check_tier_3_antenna(tmp_path)
        assert r.verdict == "FAIL"
        assert r.details["net_violations"] == 14

    def test_routing_incomplete_is_fail(self, tmp_path):
        # An 'antenna clean' claim on an UNROUTED design is vacuous → FAIL.
        _write_json(tmp_path / "reports/phase3/antenna.json",
                    _ANTENNA_INCOMPLETE)
        r = mod.check_tier_3_antenna(tmp_path)
        assert r.verdict == "FAIL"
        assert r.details["routing_incomplete"] is True

    def test_clean_report_pass(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/antenna.json", _ANTENNA_CLEAN)
        assert mod.check_tier_3_antenna(tmp_path).verdict == "PASS"

    def test_absent_not_run(self, tmp_path):
        assert mod.check_tier_3_antenna(tmp_path).verdict == "NOT_RUN"

    def test_legacy_pair_still_read(self, tmp_path):
        _write_json(tmp_path / "reports/antenna/magic.json", {"violations": 0})
        _write_json(tmp_path / "reports/antenna/klayout.json",
                    {"violations": 0})
        assert mod.check_tier_3_antenna(tmp_path).verdict == "PASS"

    def test_real_fail_blocks_ladder(self, tmp_path):
        # End-to-end: the surfaced antenna FAIL makes the whole ladder FAIL
        # (previously the masked NOT_RUN let it release-with-waivers).
        _write_json(tmp_path / "reports/phase3/antenna.json", _ANTENNA_FAIL)
        rep = mod.run_ladder(tmp_path)
        assert rep.overall_verdict == "FAIL"
        assert rep.as_dict()["released"] is False


class TestIRRealBudget:
    def test_real_report_uses_own_budget_pass(self, tmp_path):
        # §4.05 no-false-FAIL: 271 µV static IR is FAR under the real 90 mV
        # budget; the OLD 35 µV default would have wrongly FAILed it.
        _write_json(tmp_path / "reports/phase3/ir_drop.json", _IR_REAL)
        r = mod.check_tier_2_ir(tmp_path)
        assert r.verdict == "PASS"
        assert r.details["budget_source"] == "report budget_uv"
        assert r.details["budget_uv"] == 90000.0

    def test_over_report_budget_fail(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/ir_drop.json",
                    {"worst_ir_uv": 120000.0, "budget_uv": 90000.0})
        assert mod.check_tier_2_ir(tmp_path).verdict == "FAIL"

    def test_pct_of_vdd_default_when_no_budget(self, tmp_path):
        # No budget in report → 5%-of-Vdd default (1.8 V → 90 mV); 271 < 90 mV.
        _write_json(tmp_path / "reports/phase3/ir_drop.json",
                    {"worst_ir_uv": 271.0, "vdd_v": 1.8})
        r = mod.check_tier_2_ir(tmp_path)
        assert r.verdict == "PASS"
        assert "default" in r.details["budget_source"]

    def test_absent_not_run(self, tmp_path):
        assert mod.check_tier_2_ir(tmp_path).verdict == "NOT_RUN"

    def test_explicit_caller_budget_wins(self, tmp_path):
        _write_json(tmp_path / "reports/phase3/ir_drop.json",
                    {"worst_ir_uv": 50.0, "budget_uv": 90000.0})
        # caller's tight 35 µV budget overrides the report budget → FAIL.
        assert mod.check_tier_2_ir(tmp_path, budget_uv=35.0).verdict == "FAIL"


class TestPDNRealDEF:
    def _pnr(self, tmp_path):
        return tmp_path / "phase3" / "stage3" / "pnr"

    def test_def_specialnets_pass(self, tmp_path):
        _write(self._pnr(tmp_path) / "routed.def", _DEF_WITH_SN)
        r = mod.check_tier_2_pdn(tmp_path)
        assert r.verdict == "PASS"
        assert r.details["specialnets"] == 2
        assert r.details["source"] == "DEF SPECIALNETS"

    def test_no_specialnets_but_pdn_straps_pass(self, tmp_path):
        # subservient/caravel-class: 0 DEF SPECIALNETS but PDN delivered via
        # straps/followpins → PASS (never false-FAILed).
        pnr = self._pnr(tmp_path)
        _write(pnr / "routed.def", _DEF_NO_SN)
        _write(pnr / "pnr.tcl", "add_pdn_stripe -layer met1\npdngen\n")
        r = mod.check_tier_2_pdn(tmp_path)
        assert r.verdict == "PASS"
        assert r.details["source"] == "PDN-strap TCL"

    def test_no_specialnets_no_straps_fail(self, tmp_path):
        # A routed DEF with neither SPECIALNETS nor strap evidence = real
        # missing-PDN defect (§4.05: never fabricated).
        _write(self._pnr(tmp_path) / "routed.def", _DEF_NO_SN)
        assert mod.check_tier_2_pdn(tmp_path).verdict == "FAIL"

    def test_no_def_legacy_json_pass(self, tmp_path):
        _write_json(tmp_path / "reports/pnr/pdn.json", {"specialnets": 4})
        r = mod.check_tier_2_pdn(tmp_path)
        assert r.verdict == "PASS"
        assert r.details["source"] == "legacy pdn.json"

    def test_no_def_no_legacy_not_run(self, tmp_path):
        assert mod.check_tier_2_pdn(tmp_path).verdict == "NOT_RUN"


class TestEMJmaxPDKFallback:
    _TLEF = ("LAYER met1 ;\n  TYPE ROUTING ;\n  THICKNESS 0.35 ;\n"
             "  WIDTH 0.14 ;\n  DCCURRENTDENSITY AVERAGE 2.8 ;\nEND met1\n")

    def _pdk_root(self, tmp_path):
        tlef = (tmp_path / "pdks" / "sky130A" / "libs.ref" /
                "sky130_fd_sc_hd" / "techlef" / "sky130_fd_sc_hd__nom.tlef")
        _write(tlef, self._TLEF)
        return tmp_path / "pdks"

    def test_pdk_root_resolves_tech_lef(self, tmp_path, monkeypatch):
        root = self._pdk_root(tmp_path)
        monkeypatch.setenv("PDK_ROOT", str(root))
        monkeypatch.setenv("PDK", "sky130A")
        proj = tmp_path / "proj"
        # EM segment CSV present, but NO jmax/tech-lef inside the project.
        _write(proj / "reports/phase3/em_segments.csv", _em_csv(1e-4))
        j, t = mod._discover_jmax_ref(proj)
        assert j is None and t is not None
        assert t.name == "sky130_fd_sc_hd__nom.tlef"
        # The EM tier now gives a REAL verdict instead of SKIP.
        r = mod.check_tier_2_em(proj)
        assert r.verdict == "PASS"
        assert r.details["em_verdict"] == "PASS"

    def test_no_pdk_root_keeps_honest_skip(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PDK_ROOT", raising=False)
        monkeypatch.delenv("PDK", raising=False)
        proj = tmp_path / "proj"
        _write(proj / "reports/phase3/em_segments.csv", _em_csv(1e-4))
        j, t = mod._discover_jmax_ref(proj)
        assert (j, t) == (None, None)
        r = mod.check_tier_2_em(proj)
        assert r.verdict == "NOT_RUN"
        assert r.details["em_verdict"] == "SKIPPED"

    def test_unresolvable_pdk_root_is_skip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PDK_ROOT", str(tmp_path / "does_not_exist"))
        assert mod._resolve_pdk_tech_lef() is None


class TestSignoffDiscoveryNoFabrication:
    """§4.05 blanket negative: on a project with NO artifacts, every OLD tier
    is NOT_RUN — discovery never fabricates a pass out of thin air."""

    def test_all_old_tiers_not_run_on_empty(self, tmp_path):
        for fn in (mod.check_tier_1_drc, mod.check_tier_2_pdn,
                   mod.check_tier_2_ir, mod.check_tier_3_antenna,
                   mod.check_tier_3_esd, mod.check_tier_4_lvs_device,
                   mod.check_tier_5_latchup):
            r = fn(tmp_path)
            assert r.verdict == "NOT_RUN", f"{fn.__name__} -> {r.verdict}"


# ---------------------------------------------------------------------------
# The #520 positive control. Making absent evidence non-releasing is only a fix
# if a design whose evidence is COMPLETE still releases — otherwise the ladder
# is not stricter, it is broken. These build a synthetic project that satisfies
# every release-gating tier and prove the release still happens, then remove
# exactly one piece of evidence and prove it stops.
#
# chip-AGNOSTIC: every artifact here is a conventional report NAME carrying
# generic numbers; no design, vendor, SKU or PDK literal appears.
# ---------------------------------------------------------------------------
_DRC_CLEAN_XML = (
    "# Tool: klayout\n<?xml version=\"1.0\"?>\n<report-database>\n"
    " <categories>\n  <category><name>li.1</name>"
    "<description>violation</description></category>\n </categories>\n"
    " <items>\n </items>\n</report-database>\n")

# A routed DEF carrying BOTH the PDN evidence (SPECIALNETS) and the die area
# the thermal screen divides total power by.
_DEF_SIGNED_OFF = """\
VERSION 5.8 ;
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 1000000 1000000 ) ;
SPECIALNETS 2 ;
    - VDD ( a VPWR )
    - VSS ( a VGND )
END SPECIALNETS
END DESIGN
"""

_PRECHECK_STAGE_LOG_NAME = {
    "license": "License", "makefile": "Makefile", "default": "Default",
    "documentation": "Documentation", "consistency": "Consistency",
    "gpio_defines": "GPIO-Defines", "xor": "XOR", "magic_drc": "Magic DRC",
    "klayout_feol": "KLayout FEOL", "klayout_beol": "KLayout BEOL",
    "klayout_offgrid": "KLayout Offgrid", "lvs": "LVS", "oeb": "OEB",
}

# The blackbox macro whose XOR residual is EXPLICITLY allow-listed. A generic
# placeholder name — the waiver mechanism keys on the allow-list, never on any
# particular macro's identity.
_ALLOWLISTED_MACRO = "blackbox_macro_a"


def _build_fully_signed_off(root):
    """A project with REAL evidence for every release-gating tapeout tier."""
    d = root / "signed_off"
    _write(d / "reports/phase3/drc_signoff.rpt", _DRC_CLEAN_XML)          # T1
    _write_json(d / "reports/drc/geographic_heatmap.json", {"bins": []})  # T1.5
    _write(d / "phase3/stage3/pnr/routed.def", _DEF_SIGNED_OFF)      # T2_PDN
    _write_json(d / "reports/phase3/ir_drop.json", _IR_REAL)         # T2_IR
    _write(d / "reports/phase3/em_segments.csv", _em_csv(1e-4))      # T2_EM
    _write_json(d / "reports/phase3/em_jmax.json", _EM_JMAX)
    _write_json(d / "reports/phase3/antenna.json", _ANTENNA_CLEAN)   # T3_ANTENNA
    _write_json(d / "reports/phase3/esd_padring.json",
                {"clean": True, "verdict": "PASS"})                  # T3_ESD
    _write_json(d / "reports/phase3/device_class.json",
                {"device_class_match": True, "devices_layout": 261,
                 "devices_source": 261})                             # T4_LVS_DEV
    _write(d / "reports/phase3/lvs.rpt", _LVS_MATCH)                 # T4.5 LVS
    _write_json(d / "reports/phase3/tapcell_density.json",
                {"tapcells_per_mm2": 4200, "tapcells": 4200,
                 "area_mm2": 1.0})                                   # T5_LATCHUP
    _write(d / "reports/phase3/sta_signoff.rpt", _STA_FULL)          # T_STA_RIGOR
    _write(d / "rtl/top.v", _RAMLESS)                         # T_MBIST -> N/A
    _write_json(d / "reports/phase3/dynamic_ir.json",
                {"max_dynamic_drop_mv": 50.0, "vdd_v": 1.8})         # T_DYN_IR
    _write_json(d / "reports/phase3/metal_density.json",
                {"layers": {"met1": 0.42, "met2": 0.55}})     # T_METAL_DENSITY
    _write_json(d / "reports/phase3/aging_sta.json",
                {"worst_slack_ns": 0.15, "is_aging": True,
                 "aging_corner": "ss_aging_10yr late=1.10"})         # T_AGING_STA
    _write(d / "reports/phase3/power.rpt",
           "Total Power = 0.05 W\nleakage dynamic internal\n")       # T_THERMAL
    _write_json(d / "reports/phase2/dft/coverage.json",
                {"coverage_pct": 99.0, "target_pct": 98.0,
                 "transition": {"engine_limited": True,
                                "reason": "OSS ATPG has no at-speed engine"}})
    _write_json(d / "reports/phase2/dft/bsdl_plan.json",
                {"verdict": "N_A", "padded": False})            # T_DFT_SIGNOFF
    # The at-speed mechanism plan the ENGINE_LIMITED tier calls "documented".
    # Added here for the same reason it was added to `TestDFTSignoffTier`'s
    # builder: `fault_atpg_run.run_transition_atpg` writes it on every
    # engine-limited run BEFORE it emits the coverage record, so a fixture
    # that ships the record without the plan describes a state the flow does
    # not produce. Without it this "fully signed off" project is not fully
    # signed off and the ladder correctly refuses to release — which is what
    # six tests in this file measured when `dft_signoff_check` stopped taking
    # the free-text `reason` string as the documentation.
    _write(d / "phase2/stage2/dft/transition_atpg_plan.md",
           "# At-speed (launch-off-capture) transition ATPG plan\n\n"
           "Mechanism, clocking, capture window and the engine limitation "
           "this tier is accepted on.\n" + ("detail line\n" * 20))
    _write_json(d / "reports/phase3/lec_post_layout.json",
                {"verdict": "PROVEN_EQUIVALENT", "total_points": 128,
                 "proven_points": 128, "unproven_points": 0,
                 "non_equivalent_points": 0, "equivalent": True})    # T_LEC_POST
    return d


def _add_shuttle_documented_waiver(d):
    """Shuttle tiers with an all-pass precheck and an XOR residual lying
    ENTIRELY inside an explicitly allow-listed blackbox macro — i.e. a real,
    reviewed, documented waiver rather than an unrun check."""
    import mpw_precheck_result_gate as mpg
    lines = [f"{{{{SUCCESS}}}} {_PRECHECK_STAGE_LOG_NAME[k]} Check Passed"
             for k in mpg.DEFAULT_REQUIRED]
    lines.append("{{SUCCESS}} All Checks Passed!")
    _write(d / "reports/mpw_precheck/logs/precheck.log",
           "\n".join(lines) + "\n")
    _write_json(d / "reports/xor/xor_report.json",
                {"tool": "klayout-xor", "top": "user_project_wrapper",
                 "layout_under_test": "assembled.gds",
                 "golden_reference": "golden.gds", "dbu": 0.001,
                 "total_residual_count": 3, "total_residual_area_um2": 1.25,
                 "layers": [{"layer": "met1", "residual_count": 3,
                             "residual_area_um2": 1.25,
                             "by_cell": [{"cell": _ALLOWLISTED_MACRO,
                                          "count": 3, "area_um2": 1.25}]}]})
    _write_json(d / "reports/xor_allow_macros.json", [_ALLOWLISTED_MACRO])
    return d


class TestFullyEvidencedLadderStillReleases:
    """The ladder must still work when it is GIVEN something to work with."""

    def test_every_gating_tier_has_evidence(self, tmp_path):
        # Guards the fixture itself: if a tier stopped being satisfiable, the
        # release tests below would silently stop proving anything.
        rep = mod.run_ladder(_build_fully_signed_off(tmp_path),
                             mode="tapeout", caravel=False)
        unrun = [t.tier_id for t in mod.evidence_absent_tiers(rep.tiers)]
        assert unrun == [], f"fixture no longer covers: {unrun}"

    def test_complete_evidence_releases(self, tmp_path):
        rep = mod.run_ladder(_build_fully_signed_off(tmp_path),
                             mode="tapeout", caravel=False)
        assert rep.overall_verdict == "PASS"
        assert rep.as_dict()["released"] is True
        assert rep.as_dict()["release_blockers"] == []

    def test_missing_advisory_artifact_still_releases(self, tmp_path):
        # Removing the DIAGNOSTIC heatmap must NOT cost the release — a
        # missing picture is not missing sign-off evidence.
        d = _build_fully_signed_off(tmp_path)
        (d / "reports/drc/geographic_heatmap.json").unlink()
        rep = mod.run_ladder(d, mode="tapeout", caravel=False)
        heat = [t for t in rep.tiers if t.tier_id == "T1.5"][0]
        assert heat.verdict == "NOT_RUN"
        assert rep.overall_verdict == "PASS"
        assert rep.as_dict()["released"] is True

    def test_removing_one_gating_tier_stops_the_release(self, tmp_path):
        # The single-variable proof: same project, one sign-off report
        # deleted, release withheld and the responsible tier named.
        d = _build_fully_signed_off(tmp_path)
        (d / "reports/phase3/esd_padring.json").unlink()
        rep = mod.run_ladder(d, mode="tapeout", caravel=False)
        assert rep.overall_verdict == mod.NOT_RELEASED_EVIDENCE_ABSENT
        assert rep.as_dict()["released"] is False
        assert rep.as_dict()["evidence_absent_tiers"] == ["T3_ESD"]

    def test_documented_waiver_releases(self, tmp_path):
        # Constraint the fix must not break: a REVIEWED waiver still releases.
        d = _add_shuttle_documented_waiver(_build_fully_signed_off(tmp_path))
        rep = mod.run_ladder(d, mode="tapeout")
        xor = [t for t in rep.tiers if t.tier_id == "T_XOR"][0]
        assert xor.verdict == "WAIVED"
        assert rep.overall_verdict == "PASS_WITH_WAIVERS"
        assert rep.as_dict()["released"] is True

    def test_triage_does_not_release_a_fully_evidenced_design(self, tmp_path):
        # Isolates the MODE guard from the evidence rule: the triage ladder is
        # fully evidenced AND reaches a releasing verdict, and still does not
        # release, because triage is diagnostic by definition.
        d = _build_fully_signed_off(tmp_path)
        _write_json(d / "reports/lvs/net_level.json",
                    {"verdict": "PASS", "rationale": "genuine match"})
        rep = mod.run_ladder(d, mode="triage")
        assert mod.evidence_absent_tiers(rep.tiers) == []
        assert rep.overall_verdict in mod.RELEASING_VERDICTS
        assert rep.as_dict()["released"] is False


class TestStrictExitCodeMatchesReleasedFlag:
    """`--strict` is the actionable form of `released`; a run that prints
    released=False must not exit 0 under --strict."""

    def _cli(self, argv):
        import sys
        old = sys.argv
        sys.argv = ["signoff_ladder_run.py"] + argv
        try:
            return mod._cli()
        finally:
            sys.argv = old

    def test_strict_fails_when_evidence_is_absent(self, tmp_path, capsys):
        rc = self._cli([str(tmp_path), "--mode", "tapeout", "--strict"])
        capsys.readouterr()
        assert rc == 1

    def test_strict_passes_on_a_fully_evidenced_tapeout(self, tmp_path, capsys):
        d = _build_fully_signed_off(tmp_path)
        rc = self._cli([str(d), "--mode", "tapeout", "--no-caravel",
                        "--strict"])
        capsys.readouterr()
        assert rc == 0

    def test_strict_fails_in_triage_because_triage_never_releases(
            self, tmp_path, capsys):
        d = _build_fully_signed_off(tmp_path)
        _write_json(d / "reports/lvs/net_level.json", {"verdict": "PASS"})
        rc = self._cli([str(d), "--mode", "triage", "--strict"])
        capsys.readouterr()
        assert rc == 1

    def test_strict_exit_code_agrees_with_the_json_released_flag(
            self, tmp_path, capsys):
        # Both polarities, on the SAME project: the releasing tapeout run and
        # the non-releasing triage run must each have rc match `released`.
        d = _build_fully_signed_off(tmp_path)
        _write_json(d / "reports/lvs/net_level.json", {"verdict": "PASS"})
        for mode in ("tapeout", "triage"):
            out = tmp_path / f"ladder_{mode}.json"
            rc = self._cli([str(d), "--mode", mode, "--no-caravel",
                            "--strict", "--out-json", str(out)])
            capsys.readouterr()
            assert (rc == 0) is json.loads(out.read_text())["released"], mode
