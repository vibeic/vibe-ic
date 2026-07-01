"""Unit tests for `signoff_ladder_run.py` (release-gate wired)."""
import importlib
import json

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

    def test_not_run_promotes_to_pass_with_waivers(self):
        tiers = [mod.TierResult("T1", "DRC", "PASS"),
                 mod.TierResult("T1.5", "DRC heatmap", "NOT_RUN")]
        assert mod.aggregate_verdict(tiers) == "PASS_WITH_WAIVERS"

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


class TestRunLadder:
    def test_triage_ladder_returns_10_tiers(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        assert rep.mode == "triage"
        assert len(rep.tiers) == 10

    def test_attribution(self, tmp_path):
        rep = mod.run_ladder(tmp_path)
        assert "v0.1.51" in rep.as_dict()["emitted_by"]

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

    def test_power_pin_only_still_releases_in_triage_with_waiver(self, tmp_path):
        # Contrast: the triage tier still SHOWS the reasoned waiver and the
        # diagnostic ladder releases-with-waivers — only tapeout tightens.
        _write_json(tmp_path / "reports/lvs/net_level.json",
                    {"verdict": "WAIVED", "rationale": "OSS blackbox-macro gap"})
        rep = mod.run_ladder(tmp_path, mode="triage")
        assert rep.overall_verdict == "PASS_WITH_WAIVERS"
        assert rep.as_dict()["released"] is True

    def test_genuine_match_releases_at_tapeout(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        assert rep.overall_verdict in mod.RELEASING_VERDICTS
        assert rep.as_dict()["released"] is True

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

    def test_dynamic_ir_under_budget_releases(self, tmp_path):
        _write(tmp_path / "reports/phase3/lvs.rpt", _LVS_MATCH)
        _write_json(tmp_path / "reports/phase3/dynamic_ir.json",
                    {"max_dynamic_drop_mv": 50.0, "vdd_v": 1.8})
        rep = mod.run_ladder(tmp_path, mode="tapeout")
        assert rep.overall_verdict in mod.RELEASING_VERDICTS
        assert rep.as_dict()["released"] is True

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
        assert "PASS_WITH_WAIVERS" in md

    def test_doctrine_quote(self, tmp_path):
        md = mod.report_to_markdown(mod.run_ladder(tmp_path))
        assert "doctrine" in md.lower()

    def test_mode_line_present(self, tmp_path):
        md = mod.report_to_markdown(mod.run_ladder(tmp_path, mode="tapeout"))
        assert "Mode: tapeout" in md
