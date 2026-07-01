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
