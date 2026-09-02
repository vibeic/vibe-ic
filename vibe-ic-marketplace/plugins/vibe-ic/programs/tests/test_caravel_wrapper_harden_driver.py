"""Unit tests for `caravel_wrapper_harden_driver.py`.

Exercise the harden -> full-chip merge -> live XOR orchestration + the XOR-feed
wiring WITHOUT a live EDA image, by injecting runner callables. Pin the §4.05
honesty invariants:

  * plan mode (run=False)                     -> NOT_RUN (+ real command hint)
  * live harden with missing image/PDK/config -> BLOCKED, never a fake GDS
  * live harden that produces a GDS           -> PASS with the artifact path
  * live harden that produces NO GDS          -> FAIL (e.g. a DRT routing wall)
  * merge/XOR with a missing input GDS        -> BLOCKED (no fabricated output)
  * synthetic hardened wrapper + golden       -> the XOR gate actually RUNS
  * a NOT_RUN / failed harden short-circuits  -> BLOCKED, XOR NEVER attempted
"""
import importlib
import json

import pytest

mod = importlib.import_module("caravel_wrapper_harden_driver")


# ---------------------------------------------------------------------------
# helpers / injected runners
# ---------------------------------------------------------------------------
def _pdk(tmp_path):
    p = tmp_path / "pdk"
    (p / "sky130A").mkdir(parents=True)
    return str(p)


def _project(tmp_path, design="user_project_wrapper"):
    proj = tmp_path / "caravel_user_project"
    (proj / "openlane" / design).mkdir(parents=True)
    (proj / "openlane" / design / "config.json").write_text(
        json.dumps({"DESIGN_NAME": design, "DIE_AREA": [0, 0, 2920, 3520]}))
    return proj


def _image_runner(present=True, image=mod.OPENLANE_IMAGE_DEFAULT):
    """A runner that answers `docker images` only."""
    def runner(cmd, timeout=60):
        if isinstance(cmd, list) and "images" in cmd:
            return (0, (image + "\n") if present else "", "")
        return (0, "", "")
    return runner


def _harden_runner(proj, design="user_project_wrapper", produce_gds=True,
                   image_present=True):
    """A runner that answers `docker images` AND simulates the OpenLane harden
    (optionally dropping a hardened GDS at the OpenLane-1 results path)."""
    def runner(cmd, timeout=3600):
        if isinstance(cmd, list) and "images" in cmd:
            return (0, (mod.OPENLANE_IMAGE_DEFAULT + "\n")
                    if image_present else "", "")
        if produce_gds:
            gdir = (proj / "openlane" / design / "runs" / "harden" /
                    "results" / "final" / "gds")
            gdir.mkdir(parents=True, exist_ok=True)
            (gdir / f"{design}.gds").write_bytes(b"FAKE_HARDENED_GDS")
        return (0, "OpenLane flow.tcl completed", "")
    return runner


# ---------------------------------------------------------------------------
# docker_image_available
# ---------------------------------------------------------------------------
class TestImageAvailable:
    def test_present(self):
        assert mod.docker_image_available(
            mod.OPENLANE_IMAGE_DEFAULT, runner=_image_runner(True)) is True

    def test_absent(self):
        assert mod.docker_image_available(
            mod.OPENLANE_IMAGE_DEFAULT, runner=_image_runner(False)) is False

    def test_docker_missing_is_false(self):
        def boom(cmd, timeout=60):
            return (127, "", "docker: not found")
        assert mod.docker_image_available("x", runner=boom) is False


# ---------------------------------------------------------------------------
# preflight + build command
# ---------------------------------------------------------------------------
class TestPreflight:
    """`preflight_harden` reads `PDK_ROOT` from the host, so these tests set it.

    `_resolve_pdk_root` is `pdk_root or os.environ.get("PDK_ROOT") or None`.
    The runtime this suite ships in exports `PDK_ROOT=/foss/pdks` with a
    `sky130A` under it, so the "nothing supplied" case silently became "a
    perfectly good PDK was supplied by the environment" and the missing-PDK
    line was never appended — MEASURED: the list came back as image + project
    dir only, and `"PDK" in joined` was False. On a bare host with no
    `PDK_ROOT` the identical code is green. That is a test reading the host as
    if it were a constant, in both directions: it would also stay green if the
    PDK branch were deleted, on any host that exports one.

    Deleting the `"PDK" in joined` assertion would shrink the population to
    exactly exclude the only red. The class owns the variable instead, and
    each of the four states `preflight_harden` distinguishes is driven below.
    """

    @pytest.fixture(autouse=True)
    def _own_the_pdk_root(self, monkeypatch):
        monkeypatch.delenv("PDK_ROOT", raising=False)

    def test_all_present_is_clean(self, tmp_path):
        proj = _project(tmp_path)
        missing = mod.preflight_harden(
            proj, "user_project_wrapper", mod.OPENLANE_IMAGE_DEFAULT,
            _pdk(tmp_path), runner=_image_runner(True))
        assert missing == []

    def test_missing_image_pdk_config_all_reported(self, tmp_path):
        missing = mod.preflight_harden(
            tmp_path / "nope", "user_project_wrapper",
            mod.OPENLANE_IMAGE_DEFAULT, None, runner=_image_runner(False))
        joined = " ".join(missing)
        assert "image not available" in joined
        assert "PDK" in joined
        assert "project dir absent" in joined or "config absent" in joined

    def test_an_environment_pdk_root_answers_when_none_is_passed(self, tmp_path,
                                                                monkeypatch):
        """The other half of `_resolve_pdk_root`: the env supplies it, and a
        supplied-and-valid PDK must NOT be reported missing."""
        monkeypatch.setenv("PDK_ROOT", str(_pdk(tmp_path)))
        missing = mod.preflight_harden(
            tmp_path / "nope", "user_project_wrapper",
            mod.OPENLANE_IMAGE_DEFAULT, None, runner=_image_runner(False))
        assert not any("PDK" in m for m in missing), missing

    def test_a_pdk_root_without_the_sub_pdk_is_reported(self, tmp_path,
                                                       monkeypatch):
        """THE POLE THE HOST WAS HIDING. A directory that exists but holds no
        sky130A is a DIFFERENT missing prerequisite from none at all, and the
        message has to say which."""
        empty = tmp_path / "pdks-empty"
        empty.mkdir()
        monkeypatch.setenv("PDK_ROOT", str(empty))
        joined = " ".join(mod.preflight_harden(
            tmp_path / "nope", "user_project_wrapper",
            mod.OPENLANE_IMAGE_DEFAULT, None, runner=_image_runner(False)))
        assert "PDK_ROOT has no sky130A sub-PDK" in joined, joined

    def test_a_pdk_root_that_is_not_a_directory_is_reported(self, tmp_path,
                                                           monkeypatch):
        f = tmp_path / "not-a-dir"
        f.write_text("")
        monkeypatch.setenv("PDK_ROOT", str(f))
        joined = " ".join(mod.preflight_harden(
            tmp_path / "nope", "user_project_wrapper",
            mod.OPENLANE_IMAGE_DEFAULT, None, runner=_image_runner(False)))
        assert "PDK_ROOT is not a directory" in joined, joined

    def test_build_command_has_flow_tcl_and_mounts(self, tmp_path):
        proj = _project(tmp_path)
        argv = mod.build_harden_command(
            proj, "user_project_wrapper", mod.OPENLANE_IMAGE_DEFAULT,
            _pdk(tmp_path))
        assert "flow.tcl" in argv
        assert mod.OPENLANE_IMAGE_DEFAULT in argv
        assert any("/pdk" in a for a in argv)
        assert any("user_project_wrapper" in a for a in argv)


# ---------------------------------------------------------------------------
# run_harden — the live wrapper PnR
# ---------------------------------------------------------------------------
class TestRunHarden:
    def test_plan_mode_is_not_run_with_flow_tcl_hint(self, tmp_path):
        proj = _project(tmp_path)
        r = mod.run_harden(proj, "user_project_wrapper",
                           pdk_root=_pdk(tmp_path),
                           run=False, runner=_image_runner(True))
        assert r.verdict == "NOT_RUN"
        assert "flow.tcl" in r.command_hint
        assert r.artifact is None

    def test_live_blocked_when_prereqs_missing(self, tmp_path):
        # no PDK, no config, no image -> BLOCKED, never a fabricated GDS
        r = mod.run_harden(tmp_path / "nope", "user_project_wrapper",
                           pdk_root=None, run=True,
                           runner=_image_runner(False))
        assert r.verdict == "BLOCKED"
        assert r.artifact is None
        assert r.blocked_reason

    def test_live_pass_when_gds_produced(self, tmp_path):
        proj = _project(tmp_path)
        r = mod.run_harden(
            proj, "user_project_wrapper", pdk_root=_pdk(tmp_path), run=True,
            runner=_harden_runner(proj, produce_gds=True))
        assert r.verdict == "PASS"
        assert r.artifact and r.artifact.endswith("user_project_wrapper.gds")

    def test_live_fail_when_no_gds_produced(self, tmp_path):
        # e.g. a real DRT-0302 multi-bterm power-net routing wall: OpenLane
        # runs but emits no final GDS -> honest FAIL, not a fabricated PASS.
        proj = _project(tmp_path)
        r = mod.run_harden(
            proj, "user_project_wrapper", pdk_root=_pdk(tmp_path), run=True,
            runner=_harden_runner(proj, produce_gds=False))
        assert r.verdict == "FAIL"
        assert r.artifact is None
        assert "no hardened GDS" in r.details.get("note", "")

    def test_stale_prior_run_gds_does_not_fabricate_pass(self, tmp_path):
        # §4.05 regression: a PDK-version-guard abort produces NOTHING for this
        # run (rc!=0, no tagged GDS) but an OLD run left a GDS under a DIFFERENT
        # tag. The tag-scoped search must NOT pick up that stale GDS -> FAIL,
        # never a PASS off a layout this invocation never produced.
        proj = _project(tmp_path)
        stale = (proj / "openlane" / "user_project_wrapper" / "runs" /
                 "26_05_29_00_39" / "results" / "final" / "gds")
        stale.mkdir(parents=True)
        (stale / "user_project_wrapper.gds").write_bytes(b"STALE_PRIOR_RUN")

        def aborting_runner(cmd, timeout=3600):
            if isinstance(cmd, list) and "images" in cmd:
                return (0, mod.OPENLANE_IMAGE_DEFAULT + "\n", "")
            # simulate flow.tcl aborting at the open_pdks version guard: rc!=0,
            # writes no GDS under the requested tag.
            return (255, "", "open_pdks version mismatch; OpenLane will quit")

        r = mod.run_harden(
            proj, "user_project_wrapper", pdk_root=_pdk(tmp_path), run=True,
            runner=aborting_runner)
        assert r.verdict == "FAIL"
        assert r.artifact is None

    def test_produced_gds_but_nonzero_rc_is_not_a_clean_pass(self, tmp_path):
        # §4.05 regression: the run's OWN tagged GDS exists but the flow exited
        # non-zero (e.g. the end-of-flow KLayout XOR signoff quit_on_xor_error on
        # a blackbox macro). That is NOT a clean PASS.
        proj = _project(tmp_path)

        def gds_then_fail_runner(cmd, timeout=3600):
            if isinstance(cmd, list) and "images" in cmd:
                return (0, mod.OPENLANE_IMAGE_DEFAULT + "\n", "")
            gdir = (proj / "openlane" / "user_project_wrapper" / "runs" /
                    "harden" / "results" / "final" / "gds")
            gdir.mkdir(parents=True, exist_ok=True)
            (gdir / "user_project_wrapper.gds").write_bytes(b"ROUTED_GDS")
            return (1, "[ERROR]: There are XOR differences", "quit_on_xor_error")

        r = mod.run_harden(
            proj, "user_project_wrapper", pdk_root=_pdk(tmp_path), run=True,
            runner=gds_then_fail_runner)
        assert r.verdict == "FAIL"
        assert r.artifact is None
        assert r.details.get("produced_gds_but_flow_failed")


# ---------------------------------------------------------------------------
# merge — full-chip assembly
# ---------------------------------------------------------------------------
class TestMerge:
    def test_merge_script_is_valid_python_with_copy_tree(self):
        s = mod.build_merge_script(
            "base.gds", "wrap.gds", "out.gds", "caravel",
            "user_project_wrapper")
        compile(s, "<merge>", "exec")
        assert "copy_tree" in s
        assert "caravel" in s
        assert "user_project_wrapper" in s

    def test_merge_plan_is_not_run(self, tmp_path):
        base = tmp_path / "golden.gds"; base.write_bytes(b"G")
        wrap = tmp_path / "wrap.gds"; wrap.write_bytes(b"W")
        r = mod.run_merge(base, wrap, tmp_path / "out.gds", "caravel",
                          "user_project_wrapper", run=False)
        assert r.verdict == "NOT_RUN"

    def test_merge_blocked_when_input_absent(self, tmp_path):
        r = mod.run_merge(tmp_path / "no_base.gds", tmp_path / "no_wrap.gds",
                          tmp_path / "out.gds", "caravel",
                          "user_project_wrapper", run=True)
        assert r.verdict == "BLOCKED"
        assert r.artifact is None

    def test_merge_pass_when_out_written(self, tmp_path):
        base = tmp_path / "golden.gds"; base.write_bytes(b"G")
        wrap = tmp_path / "wrap.gds"; wrap.write_bytes(b"W")
        out = tmp_path / "out" / "assembled.gds"

        def klayout(cmd, timeout=1800):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"ASSEMBLED")
            return (0, "MERGE_WRITTEN", "")

        r = mod.run_merge(base, wrap, out, "caravel", "user_project_wrapper",
                          run=True, klayout_runner=klayout)
        assert r.verdict == "PASS"
        assert r.artifact == str(out)


# ---------------------------------------------------------------------------
# run_xor — the XOR-feed wiring (synthetic hardened wrapper + golden)
# ---------------------------------------------------------------------------
def _zero_delta(top="caravel"):
    return {"tool": "klayout-xor", "top": top,
            "total_residual_count": 0, "total_residual_area_um2": 0.0,
            "layers": []}


def _residual_outside(top="caravel"):
    return {"tool": "klayout-xor", "top": top,
            "total_residual_count": 2, "total_residual_area_um2": 0.4,
            "layers": [{"layer": "met2", "residual_count": 2,
                        "residual_area_um2": 0.4,
                        "by_cell": [{"cell": mod.xlc.OUTSIDE_SENTINEL,
                                     "count": 2, "area_um2": 0.4}]}]}


class TestRunXor:
    def test_xor_blocked_when_gds_absent(self, tmp_path):
        r = mod.run_xor(tmp_path / "no_asm.gds", tmp_path / "no_gold.gds",
                        "caravel", run=True)
        assert r.verdict == "BLOCKED"

    def test_xor_plan_is_not_run(self, tmp_path):
        asm = tmp_path / "asm.gds"; asm.write_bytes(b"A")
        gold = tmp_path / "gold.gds"; gold.write_bytes(b"G")
        r = mod.run_xor(asm, gold, "caravel", run=False)
        assert r.verdict == "NOT_RUN"
        assert "klayout" in r.command_hint

    def test_xor_runs_and_passes_on_zero_delta(self, tmp_path):
        asm = tmp_path / "asm.gds"; asm.write_bytes(b"A")
        gold = tmp_path / "gold.gds"; gold.write_bytes(b"G")
        report = tmp_path / "xr.json"

        def klayout(cmd, timeout=1800):
            report.write_text(json.dumps(_zero_delta()))
            return (0, "XOR_REPORT_WRITTEN", "")

        r = mod.run_xor(asm, gold, "caravel", allow_macros=["user_proj_example"],
                        report_out=report, run=True, klayout_runner=klayout)
        assert r.verdict == "PASS"
        assert r.details["xor"]["verdict"] == "PASS"

    def test_xor_fails_on_outside_residual(self, tmp_path):
        asm = tmp_path / "asm.gds"; asm.write_bytes(b"A")
        gold = tmp_path / "gold.gds"; gold.write_bytes(b"G")
        report = tmp_path / "xr.json"

        def klayout(cmd, timeout=1800):
            report.write_text(json.dumps(_residual_outside()))
            return (0, "XOR_REPORT_WRITTEN", "")

        r = mod.run_xor(asm, gold, "caravel", allow_macros=["user_proj_example"],
                        report_out=report, run=True, klayout_runner=klayout)
        assert r.verdict == "FAIL"

    def test_xor_blocked_when_klayout_writes_no_report(self, tmp_path):
        # INCOMPLETE (absent report) is mapped to BLOCKED -- never a fake PASS.
        asm = tmp_path / "asm.gds"; asm.write_bytes(b"A")
        gold = tmp_path / "gold.gds"; gold.write_bytes(b"G")

        def klayout(cmd, timeout=1800):
            return (1, "", "klayout crashed")

        r = mod.run_xor(asm, gold, "caravel", report_out=tmp_path / "xr.json",
                        run=True, klayout_runner=klayout)
        assert r.verdict == "BLOCKED"


# ---------------------------------------------------------------------------
# harden_merge_xor — full orchestration + §4.05 short-circuit
# ---------------------------------------------------------------------------
class TestOrchestration:
    def test_synthetic_hardened_wrapper_drives_a_real_xor_pass(self, tmp_path):
        # A synthetic hardened wrapper + a golden reference; the injected
        # klayout runner writes the merged GDS then a zero-delta XOR report.
        proj = _project(tmp_path)
        golden = tmp_path / "golden_caravel.gds"; golden.write_bytes(b"GOLD")
        hardened = tmp_path / "hardened_wrapper.gds"; hardened.write_bytes(b"HW")
        assembled = tmp_path / "gds" / "caravel_assembled.gds"

        def klayout(cmd, timeout=1800):
            s = cmd if isinstance(cmd, str) else " ".join(cmd)
            if "_merge_fullchip.py" in s:
                assembled.parent.mkdir(parents=True, exist_ok=True)
                assembled.write_bytes(b"ASSEMBLED")
            elif "_xor_fullchip.py" in s:
                (assembled.parent / "xor_report.json").write_text(
                    json.dumps(_zero_delta()))
            return (0, "ok", "")

        rep = mod.harden_merge_xor(
            proj, "user_project_wrapper", golden, assembled, "caravel",
            "user_project_wrapper", allow_macros=["user_proj_example"],
            run=True, klayout_runner=klayout, hardened_gds=hardened)
        assert rep["overall_verdict"] == "PASS"
        step_names = [s["step"] for s in rep["steps"]]
        assert step_names == ["harden", "merge", "xor"]

    def test_failed_harden_short_circuits_no_xor(self, tmp_path):
        # A live harden that cannot run (no image/PDK/config). The whole chain
        # must be BLOCKED and the XOR must NEVER be attempted -- proven by a
        # klayout runner that raises if it is ever called.
        def klayout_must_not_run(cmd, timeout=1800):
            raise AssertionError("XOR/merge must NOT run after a failed harden")

        rep = mod.harden_merge_xor(
            tmp_path / "nope", "user_project_wrapper",
            tmp_path / "golden.gds", tmp_path / "out.gds", "caravel",
            "user_project_wrapper", run=True,
            harden_runner=_image_runner(False),
            klayout_runner=klayout_must_not_run)
        assert rep["overall_verdict"] == "BLOCKED"
        step_names = [s["step"] for s in rep["steps"]]
        assert step_names == ["harden"]           # merge + xor never attempted
        assert "no fabricated pass" in rep["note"]

    def test_verdict_exit_codes(self):
        assert mod.verdict_exit_code("PASS") == 0
        assert mod.verdict_exit_code("PASS_WITH_WAIVER") == 0
        assert mod.verdict_exit_code("FAIL") == 1
        assert mod.verdict_exit_code("BLOCKED") == 2
        assert mod.verdict_exit_code("NOT_RUN") == 2


# ---------------------------------------------------------------------------
# stage_gl — wire the harden gl netlist into the precheck input (GOAL A)
# ---------------------------------------------------------------------------
def _write_gl(proj, design, tag, primary=True, nl=True, text="module m; endmodule\n"):
    """Drop OpenLane-1 gl netlist(s) at runs/<tag>/results/final/verilog/gl/."""
    gl = (proj / "openlane" / design / "runs" / tag /
          "results" / "final" / "verilog" / "gl")
    gl.mkdir(parents=True, exist_ok=True)
    if primary:
        (gl / f"{design}.v").write_text(text)
    if nl:
        (gl / f"{design}.nl.v").write_text(text)
    return gl


class TestFindGlNetlists:
    def test_finds_primary_first_then_siblings(self, tmp_path):
        proj = _project(tmp_path)
        _write_gl(proj, "user_project_wrapper", "harden")
        found = mod.find_hardened_gl_netlists(proj, "user_project_wrapper")
        assert [p.name for p in found][0] == "user_project_wrapper.v"
        assert "user_project_wrapper.nl.v" in [p.name for p in found]

    def test_none_when_no_gl(self, tmp_path):
        proj = _project(tmp_path)
        assert mod.find_hardened_gl_netlists(proj, "user_project_wrapper") == []

    def test_tag_scoped_ignores_other_runs(self, tmp_path):
        proj = _project(tmp_path)
        _write_gl(proj, "user_project_wrapper", "OTHER_RUN")
        # A tag with no gl netlist must find nothing even though OTHER_RUN has one.
        assert mod.find_hardened_gl_netlists(
            proj, "user_project_wrapper", tag="harden") == []


class TestStageGl:
    def test_stages_produced_netlists_into_verilog_gl(self, tmp_path):
        proj = _project(tmp_path)
        _write_gl(proj, "user_project_wrapper", "harden")
        r = mod.run_stage_gl(proj, "user_project_wrapper")
        assert r.verdict == "PASS"
        dst = proj / "verilog" / "gl" / "user_project_wrapper.v"
        assert dst.is_file()                      # the precheck user netlist
        assert (proj / "verilog" / "gl" / "user_project_wrapper.nl.v").is_file()
        assert r.artifact == str(dst)

    def test_no_produced_netlist_is_blocked_and_writes_nothing(self, tmp_path):
        # §4.05: a harden that produced no gl netlist -> BLOCKED, and NOTHING is
        # written into verilog/gl (never a fabricated/empty netlist), so the
        # precheck Consistency/LVS still FAIL honestly.
        proj = _project(tmp_path)
        r = mod.run_stage_gl(proj, "user_project_wrapper")
        assert r.verdict == "BLOCKED"
        assert not (proj / "verilog" / "gl" / "user_project_wrapper.v").exists()
        assert r.blocked_reason

    def test_tag_scoped_stage_does_not_fabricate_from_stale_run(self, tmp_path):
        # §4.05 regression: an OLD run left a gl netlist under a DIFFERENT tag;
        # a tag-scoped stage of the CURRENT (empty) run must stage nothing.
        proj = _project(tmp_path)
        _write_gl(proj, "user_project_wrapper", "26_05_29_00_35")
        r = mod.run_stage_gl(proj, "user_project_wrapper", tag="harden")
        assert r.verdict == "BLOCKED"
        assert not (proj / "verilog" / "gl" / "user_project_wrapper.v").exists()

    def test_harden_success_path_auto_stages_when_enabled(self, tmp_path):
        # run_harden(stage_gl=True) on a clean PASS stages the gl netlist and
        # records it under details["gl_staged"], without changing the verdict.
        proj = _project(tmp_path)

        def runner(cmd, timeout=3600):
            if isinstance(cmd, list) and "images" in cmd:
                return (0, mod.OPENLANE_IMAGE_DEFAULT + "\n", "")
            gdir = (proj / "openlane" / "user_project_wrapper" / "runs" /
                    "harden" / "results" / "final" / "gds")
            gdir.mkdir(parents=True, exist_ok=True)
            (gdir / "user_project_wrapper.gds").write_bytes(b"GDS")
            _write_gl(proj, "user_project_wrapper", "harden")
            return (0, "flow.tcl completed", "")

        r = mod.run_harden(proj, "user_project_wrapper",
                           pdk_root=_pdk(tmp_path), run=True, runner=runner,
                           stage_gl=True)
        assert r.verdict == "PASS"
        staged = r.details.get("gl_staged", {})
        assert staged.get("verdict") == "PASS"
        assert (proj / "verilog" / "gl" / "user_project_wrapper.v").is_file()

    def test_harden_failure_stages_nothing(self, tmp_path):
        # A harden that produced NO GDS must not stage a netlist even if
        # stage_gl=True (the FAIL path never reaches the stage call).
        proj = _project(tmp_path)
        r = mod.run_harden(
            proj, "user_project_wrapper", pdk_root=_pdk(tmp_path), run=True,
            runner=_harden_runner(proj, produce_gds=False), stage_gl=True)
        assert r.verdict == "FAIL"
        assert not (proj / "verilog" / "gl" / "user_project_wrapper.v").exists()
