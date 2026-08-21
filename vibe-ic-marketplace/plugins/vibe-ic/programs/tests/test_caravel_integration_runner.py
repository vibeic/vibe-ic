"""Unit tests for `caravel_integration_runner.py`."""
import importlib
import json

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("caravel_integration_runner")


def _make_pinmap(path):
    """Minimal spm-shape pin-map at `path`."""
    path.write_text(json.dumps({
        "project_name": "spm",
        "core_module": "spm",
        "power_domains": ["vccd1", "vssd1"],
        "pin_assignments": [
            {"core_port": "clk", "caravel_pin": "wb_clk_i",
             "port_dir": "input"},
            {"core_port": "p", "caravel_pin": "io_out[35]",
             "port_dir": "output"},
        ],
    }))


def _make_core_artifacts(tmp_path):
    core_gds = tmp_path / "spm.gds"
    core_lef = tmp_path / "spm.lef"
    core_v = tmp_path / "spm.v"
    core_gds.write_bytes(b"FAKE_GDS")
    core_lef.write_text("MACRO spm\nEND spm\n")
    core_v.write_text("module spm; endmodule\n")
    return core_gds, core_lef, core_v


class TestStepA1Clone:
    def test_returns_not_run_when_target_missing(self, tmp_path):
        r = mod.step_a1_clone_template(tmp_path)
        assert r.verdict == "NOT_RUN"
        assert "git clone" in r.command_hint

    def test_pass_when_target_exists(self, tmp_path):
        (tmp_path / "caravel_user_project").mkdir()
        r = mod.step_a1_clone_template(tmp_path)
        assert r.verdict == "PASS"


class TestStepA2Install:
    def test_fail_when_source_missing(self, tmp_path):
        r = mod.step_a2_install_core(
            tmp_path, tmp_path / "x.gds", tmp_path / "x.lef",
            tmp_path / "x.v", "spm")
        assert r.verdict == "FAIL"

    def test_plan_when_sources_exist(self, tmp_path):
        gds, lef, v = _make_core_artifacts(tmp_path)
        r = mod.step_a2_install_core(tmp_path, gds, lef, v, "spm")
        assert r.verdict == "NOT_RUN"  # plan-only
        assert "cp " in r.command_hint


class TestStepA3EmitWrapper:
    def test_emits_wrapper_to_disk(self, tmp_path):
        pm = tmp_path / "pinmap.json"
        _make_pinmap(pm)
        r = mod.step_a3_emit_wrapper(tmp_path, pm)
        assert r.verdict == "PASS"
        wrapper = (tmp_path / "caravel_user_project" /
                    "verilog" / "rtl" / "user_project_wrapper.v")
        assert wrapper.exists()
        assert "module user_project_wrapper" in wrapper.read_text()

    def test_fail_when_pin_map_missing(self, tmp_path):
        r = mod.step_a3_emit_wrapper(tmp_path, tmp_path / "missing.json")
        assert r.verdict == "FAIL"


class TestStepA4EmitUserDefines:
    def test_emits_user_defines(self, tmp_path):
        pm = tmp_path / "pinmap.json"
        _make_pinmap(pm)
        r = mod.step_a4_emit_user_defines(tmp_path, pm)
        assert r.verdict == "PASS"
        ud = (tmp_path / "caravel_user_project" /
              "verilog" / "rtl" / "user_defines.v")
        assert ud.exists()
        assert "USER_CONFIG_GPIO_35_INIT" in ud.read_text()


class TestStepB:
    def test_b1_openlane_is_not_run_plan(self, tmp_path):
        # run=False (default) keeps plan-only behaviour, now delegated to the
        # harden driver; the real docker flow.tcl command hint is preserved.
        r = mod.step_b1_openlane_wrapper_pnr(tmp_path)
        assert r.verdict == "NOT_RUN"
        assert "flow.tcl" in r.command_hint

    def test_b1_live_blocked_when_prereqs_missing(self, tmp_path):
        # run=True with no OpenLane image / PDK / config available -> BLOCKED
        # (never a fabricated harden). Inject a runner that reports no image.
        def _no_image_runner(cmd, timeout=60):
            return (0, "", "")  # `docker images` returns nothing
        r = mod.step_b1_openlane_wrapper_pnr(
            tmp_path, run=True, runner=_no_image_runner)
        assert r.verdict == "BLOCKED"
        assert r.details["artifact"] is None
        assert r.details["blocked_reason"]

    def test_b3_merge_blocked_when_gds_absent(self, tmp_path):
        r = mod.step_b3_fullchip_merge(
            tmp_path, golden_gds=None, wrapper_gds=None, run=True)
        assert r.verdict == "BLOCKED"
        assert r.details["artifact"] is None

    def test_b4_xor_blocked_when_gds_absent(self, tmp_path):
        r = mod.step_b4_live_xor(
            tmp_path, assembled_gds=None, golden_gds=None, run=True,
            allow_macros=["user_proj_example"])
        assert r.verdict == "BLOCKED"

    def test_b2_pass_with_clean_metrics(self, tmp_path):
        m = tmp_path / "reports" / "openlane_wrapper" / "metrics.json"
        m.parent.mkdir(parents=True)
        m.write_text(json.dumps({
            "wns_ns": 0.5, "routing_violations": 0}))
        r = mod.step_b2_assert_wrapper_pnr_clean(tmp_path)
        assert r.verdict == "PASS"

    def test_b2_fail_with_negative_wns(self, tmp_path):
        m = tmp_path / "reports" / "openlane_wrapper" / "metrics.json"
        m.parent.mkdir(parents=True)
        m.write_text(json.dumps({
            "wns_ns": -1.5, "routing_violations": 0}))
        r = mod.step_b2_assert_wrapper_pnr_clean(tmp_path)
        assert r.verdict == "FAIL"


class TestStepC:
    def test_c1_is_external_docker_plan(self, tmp_path):
        r = mod.step_c1_run_precheck(tmp_path)
        assert r.verdict == "NOT_RUN"
        assert "mpw_precheck" in r.command_hint

    def test_c2_cleanup_runs_inline(self, tmp_path):
        proj = tmp_path / "caravel_user_project"
        proj.mkdir()
        (proj / "README.md").write_text("# Caravel User Project\n")
        pm = tmp_path / "pinmap.json"
        _make_pinmap(pm)
        r = mod.step_c2_cleanup(tmp_path, "spm", pm)
        assert r.verdict in ("PASS", "CLEAN_FIXED")

    def test_c4_at_2_of_7_floor_auto_waiver(self, tmp_path):
        r = mod.step_c4_emit_waivers_if_at_floor(
            tmp_path, precheck_fail_set=["Consistency", "XOR"],
            project_name="spm")
        assert r.verdict == "PASS"
        assert "next_step" in r.details

    def test_c4_off_floor_human_triage_required(self, tmp_path):
        r = mod.step_c4_emit_waivers_if_at_floor(
            tmp_path,
            precheck_fail_set=["License", "XOR"],  # different from floor
            project_name="spm")
        assert r.verdict == "FAIL"
        # Human-triage requirement appears in the STEP NAME
        assert "human triage" in r.name.lower()
        assert "investigate" in r.notes.lower()

    def test_c4_no_fail_set_supplied_is_not_run(self, tmp_path):
        r = mod.step_c4_emit_waivers_if_at_floor(
            tmp_path, precheck_fail_set=None, project_name="spm")
        assert r.verdict == "NOT_RUN"


class TestOverallVerdict:
    def test_all_pass(self):
        steps = [mod.PhaseStepResult("A1", "A", "x", "PASS")]
        assert mod.overall_verdict(steps) == "PASS"

    def test_any_fail(self):
        steps = [mod.PhaseStepResult("A1", "A", "x", "PASS"),
                  mod.PhaseStepResult("C4", "C", "y", "FAIL")]
        assert mod.overall_verdict(steps) == "FAIL"

    def test_any_not_run_yields_partial(self):
        steps = [mod.PhaseStepResult("A1", "A", "x", "PASS"),
                  mod.PhaseStepResult("B1", "B", "y", "NOT_RUN")]
        assert mod.overall_verdict(steps) == "PARTIAL_PLAN_READY"

    def test_blocked_is_honest_non_pass(self):
        # A BLOCKED live step (missing image / PDK / golden GDS) must never be
        # promoted to PASS -- it rolls up to BLOCKED (§4.05).
        steps = [mod.PhaseStepResult("A1", "A", "x", "PASS"),
                  mod.PhaseStepResult("B1", "B", "y", "BLOCKED")]
        assert mod.overall_verdict(steps) == "BLOCKED"


class TestPlanIntegration:
    def test_full_plan_emits_12_steps(self, tmp_path):
        gds, lef, v = _make_core_artifacts(tmp_path)
        pm = tmp_path / "pm.json"
        _make_pinmap(pm)
        rep = mod.plan_integration(
            tmp_path, "spm", gds, lef, v, pm)
        # 10 legacy steps + B3 (full-chip merge) + B4 (live XOR) = 12
        assert len(rep.steps) == 12
        # Phase A inline steps should be PASS (we wrote pinmap + artifacts)
        a_steps = [s for s in rep.steps if s.phase == "A"]
        # A1 (clone) and A2 (install) are NOT_RUN; A3/A4 should be PASS
        assert any(s.step_id == "A3" and s.verdict == "PASS"
                   for s in a_steps)
        assert any(s.step_id == "A4" and s.verdict == "PASS"
                   for s in a_steps)

    def test_plan_includes_merge_and_xor_steps(self, tmp_path):
        gds, lef, v = _make_core_artifacts(tmp_path)
        pm = tmp_path / "pm.json"
        _make_pinmap(pm)
        rep = mod.plan_integration(tmp_path, "spm", gds, lef, v, pm)
        ids = {s.step_id for s in rep.steps}
        assert "B3" in ids and "B4" in ids
        # In plan (non-live) mode with no golden GDS, the live B-steps are
        # NOT_RUN, so the overall rolls up to a partial plan (never a fake PASS).
        b3 = next(s for s in rep.steps if s.step_id == "B3")
        b4 = next(s for s in rep.steps if s.step_id == "B4")
        assert b3.verdict == "NOT_RUN"
        assert b4.verdict == "NOT_RUN"
        assert rep.overall_verdict == "PARTIAL_PLAN_READY"

    def test_attribution(self, tmp_path):
        gds, lef, v = _make_core_artifacts(tmp_path)
        pm = tmp_path / "pm.json"
        _make_pinmap(pm)
        rep = mod.plan_integration(tmp_path, "x", gds, lef, v, pm)
        assert rep.as_dict()["emitted_by"] == \
            f"caravel_integration_runner v{shipped_plugin_version()}"

    def test_known_floor_constant(self):
        # The 2/7 hard-macro floor must be Consistency + XOR (spm pilot empirical)
        assert mod.KNOWN_2_OF_7_FLOOR == frozenset({"Consistency", "XOR"})
