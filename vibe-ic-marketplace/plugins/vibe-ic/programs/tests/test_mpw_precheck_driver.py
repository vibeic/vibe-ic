"""Unit tests for `mpw_precheck_driver.py` (TAPEOUT-SIGNOFF P0#2, driver half).

The live driver runs `efabless/mpw_precheck` in Docker and feeds the produced run
directory to `mpw_precheck_result_gate`. These tests exercise the orchestration +
the parser-feed with NO live Docker image by injecting the two seams:

  * `image_resolver(image, allow_pull) -> Optional[str]`  — availability/pull.
  * `docker_runner(cmd, timeout) -> (rc, stdout, stderr)`  — the container run.

The fake docker_runner reads `--output_directory` straight out of the assembled
argv and writes a synthetic mpw_precheck run dir there — exactly as the real
container would — so the command construction AND the parser-feed are both under
test. The §4.05 core is proven by (b)+(c): an absent image and an empty output
must NEVER yield a PASS; and (d) proves a non-zero container exit that DID emit a
real failing-check log is a legitimate FAIL, not a fabricated pass and not a
spurious BLOCK.
"""
import importlib
import json

mod = importlib.import_module("mpw_precheck_driver")

_STAGE_LOG_NAME = {
    "license": "License", "makefile": "Makefile", "default": "Default",
    "documentation": "Documentation", "consistency": "Consistency",
    "gpio_defines": "GPIO-Defines", "xor": "XOR", "magic_drc": "Magic DRC",
    "klayout_feol": "KLayout FEOL", "klayout_beol": "KLayout BEOL",
    "klayout_offgrid": "KLayout Offgrid", "lvs": "LVS", "oeb": "OEB",
}

# The precheck-token -> parser-stage names for the default ladder.
_DEFAULT_STAGES = [mod._CHECK_TO_STAGE[c] for c in mod.DEFAULT_CHECKS]


def _output_dir_from_cmd(cmd):
    """Pull the value of `--output_directory` out of the assembled docker argv.

    The driver embeds the whole `python3 mpw_precheck.py …` invocation as the
    final `bash -c` string, so scan the tokens for it there."""
    from pathlib import Path
    for tok in cmd:
        if "--output_directory" in tok:
            parts = tok.split()
            i = parts.index("--output_directory")
            return Path(parts[i + 1])
    raise AssertionError("no --output_directory in docker command")


def _write_run(rundir, passed, failed=(), summary=None):
    """Write a synthetic mpw_precheck run dir mirroring the real log conventions
    ({{...CHECK PASSED}} / {{...CHECK FAILED}} + a `N Check(s) Failed` summary)."""
    logs = rundir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    lines = []
    for k in passed:
        lines.append(f"{{{{SUCCESS}}}} {_STAGE_LOG_NAME[k]} Check Passed")
    for k in failed:
        lines.append(f"{{{{FAIL}}}} {_STAGE_LOG_NAME[k]} Check Failed")
    if summary == "PASS":
        lines.append("{{SUCCESS}} All Checks Passed!")
    elif summary == "FAIL":
        n = len(list(failed)) or 1
        lines.append(f"{{{{FAILURE}}}} {n} Check(s) Failed")
    (logs / "precheck.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prepare_project(tmp_path):
    """A minimal on-disk Caravel-shaped project: an mpw_precheck.py stub + a PDK
    variant dir, so the driver's input-validation passes without a live tree."""
    proj = tmp_path / "caravel_user_project"
    (proj / "dependencies" / "mpw_precheck").mkdir(parents=True)
    (proj / "dependencies" / "mpw_precheck" / "mpw_precheck.py").write_text(
        "# stub\n", encoding="utf-8")
    pdk_root = tmp_path / "pdks"
    (pdk_root / "sky130A").mkdir(parents=True)
    return proj, pdk_root


# --------------------------------------------------------------------------- #
# (a) POSITIVE — image present + a completed all-pass run dir → PASS.
# --------------------------------------------------------------------------- #
class TestPositiveDriveToPass:
    def test_all_pass_run_parses_to_pass(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)

        def fake_resolver(image, allow_pull):
            return image  # image available

        def fake_runner(cmd, timeout):
            out = _output_dir_from_cmd(cmd)
            _write_run(out, passed=_DEFAULT_STAGES, summary="PASS")
            return 0, "All Checks Passed!\n", ""

        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root,
            image_resolver=fake_resolver, docker_runner=fake_runner)

        assert rep.overall_verdict == "PASS"
        assert rep.ran is True
        assert rep.docker_returncode == 0
        assert rep.gate_report["overall_verdict"] == "PASS"
        assert rep.blocked_reason == ""
        # The command actually mounts the precheck source at /opt/mpw_precheck.
        assert any(mod._CONTAINER_PRECHECK_MOUNT in tok for tok in rep.command)
        assert mod.ATTRIBUTION in rep.as_dict()["emitted_by"]

    def test_cli_returns_zero_on_pass(self, tmp_path, monkeypatch):
        proj, pdk_root = _prepare_project(tmp_path)

        def fake_runner(cmd, timeout):
            out = _output_dir_from_cmd(cmd)
            _write_run(out, passed=_DEFAULT_STAGES, summary="PASS")
            return 0, "", ""

        # Patch the module-level seams the CLI path uses.
        monkeypatch.setattr(mod, "default_image_resolver",
                            lambda image, allow_pull: image)
        monkeypatch.setattr(mod, "default_docker_runner", fake_runner)
        rc = mod.main([
            "--input-directory", str(proj),
            "--pdk-root", str(pdk_root),
            "--rundir", str(proj / "precheck_results" / "run_cli"),
        ])
        assert rc == 0


# --------------------------------------------------------------------------- #
# (b) §4.05 NEGATIVE — image missing → BLOCKED, never PASS, container never run.
# --------------------------------------------------------------------------- #
class TestImageMissingIsBlocked:
    def test_absent_image_blocks(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)
        ran_flag = {"called": False}

        def fake_resolver(image, allow_pull):
            return None  # image not available / unpullable

        def fake_runner(cmd, timeout):  # must NEVER be called
            ran_flag["called"] = True
            return 0, "", ""

        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root,
            image_resolver=fake_resolver, docker_runner=fake_runner)

        assert rep.overall_verdict == "BLOCKED"
        assert rep.overall_verdict != "PASS"
        assert rep.ran is False
        assert ran_flag["called"] is False          # never invoked the container
        assert "not available" in rep.blocked_reason

    def test_missing_pdk_blocks(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)

        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root, pdk_variant="does_not_exist",
            image_resolver=lambda image, allow_pull: image,
            docker_runner=lambda cmd, timeout: (0, "", ""))
        assert rep.overall_verdict == "BLOCKED"
        assert "PDK" in rep.blocked_reason

    def test_missing_precheck_src_blocks(self, tmp_path):
        proj = tmp_path / "bare_project"
        proj.mkdir()
        pdk_root = tmp_path / "pdks"
        (pdk_root / "sky130A").mkdir(parents=True)
        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root,
            image_resolver=lambda image, allow_pull: image,
            docker_runner=lambda cmd, timeout: (0, "", ""))
        assert rep.overall_verdict == "BLOCKED"
        assert "mpw_precheck.py" in rep.blocked_reason


# --------------------------------------------------------------------------- #
# (c) §4.05 NEGATIVE — container ran but produced NOTHING → BLOCKED, never PASS.
# --------------------------------------------------------------------------- #
class TestEmptyOutputIsBlocked:
    def test_empty_output_blocks(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)

        def fake_runner(cmd, timeout):
            # Simulate an orchestration failure: non-zero exit, NO run dir written.
            return 1, "", "some docker/tool error\n"

        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root,
            image_resolver=lambda image, allow_pull: image,
            docker_runner=fake_runner)
        assert rep.overall_verdict == "BLOCKED"
        assert rep.overall_verdict != "PASS"
        assert rep.docker_returncode == 1
        # The parser's SKIPPED_CONDITION is surfaced for transparency.
        assert rep.gate_report is not None
        assert rep.gate_report["overall_verdict"] == "SKIPPED_CONDITION"


# --------------------------------------------------------------------------- #
# (d) HONESTY — non-zero exit WITH a real failing-check log → FAIL (not BLOCK,
#     not a fabricated pass). This is the discriminating case for §4.05.
# --------------------------------------------------------------------------- #
class TestRealFailIsFailNotBlock:
    def test_nonzero_exit_with_fail_log_is_fail(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)
        passed = [s for s in _DEFAULT_STAGES if s not in ("consistency", "xor")]

        def fake_runner(cmd, timeout):
            out = _output_dir_from_cmd(cmd)
            _write_run(out, passed=passed, failed=["consistency", "xor"],
                       summary="FAIL")
            return 1, "", ""   # mpw_precheck exits non-zero on a check failure

        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root,
            image_resolver=lambda image, allow_pull: image,
            docker_runner=fake_runner)
        assert rep.overall_verdict == "FAIL"
        assert rep.ran is True
        assert rep.docker_returncode == 1
        assert set(rep.gate_report["failed_checks"]) == {"consistency", "xor"}

    def test_partial_run_is_incomplete(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)

        def fake_runner(cmd, timeout):
            out = _output_dir_from_cmd(cmd)
            # Only the first three checks logged a verdict; the rest never ran.
            _write_run(out, passed=_DEFAULT_STAGES[:3], summary=None)
            return 0, "", ""

        rep = mod.drive(
            input_directory=proj, pdk_root=pdk_root,
            image_resolver=lambda image, allow_pull: image,
            docker_runner=fake_runner)
        assert rep.overall_verdict == "INCOMPLETE"
        assert rep.overall_verdict != "PASS"


# --------------------------------------------------------------------------- #
# Command-shape + required-set mapping.
# --------------------------------------------------------------------------- #
class TestCommandShape:
    def test_required_stages_mapping(self):
        stages, dropped = mod._required_stages(list(mod.DEFAULT_CHECKS))
        assert stages == _DEFAULT_STAGES
        assert dropped == []

    def test_command_carries_checks_and_mounts(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)
        rundir = proj / "precheck_results" / "run1"
        cmd = mod.build_docker_command(
            "efabless/mpw_precheck:latest", proj, pdk_root,
            pdk_root / "sky130A", proj / "dependencies" / "mpw_precheck",
            rundir, list(mod.DEFAULT_CHECKS))
        joined = " ".join(cmd)
        assert "mpw_precheck.py" in joined
        assert "--input_directory" in joined
        assert "--pdk_path" in joined
        assert "--output_directory" in joined
        for c in mod.DEFAULT_CHECKS:
            assert c in joined

    def test_out_json_written(self, tmp_path):
        proj, pdk_root = _prepare_project(tmp_path)
        outp = tmp_path / "verdict.json"

        def fake_runner(cmd, timeout):
            out = _output_dir_from_cmd(cmd)
            _write_run(out, passed=_DEFAULT_STAGES, summary="PASS")
            return 0, "", ""

        import mpw_precheck_driver as m
        # Drive directly then serialize (mirrors main()'s --out-json branch).
        rep = m.drive(input_directory=proj, pdk_root=pdk_root,
                      image_resolver=lambda image, allow_pull: image,
                      docker_runner=fake_runner)
        outp.write_text(json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
        loaded = json.loads(outp.read_text())
        assert loaded["overall_verdict"] == "PASS"
        assert loaded["emitted_by"].startswith("mpw_precheck_driver")
