#!/usr/bin/env python3
"""#902 — a pinned image that is VERIFIED and then not USED for simulation.

The defect
----------
`design_one_shot_runner._iverilog_exec_container()` returned False whenever the
HOST carried any iverilog:

    if _shutil.which("iverilog"):
        return False

so `--require-image <ref>` was checked at launch, reported satisfied, and the
simulation then ran whatever iverilog the machine happened to have. MEASURED on
one fleet: three different Icarus frontends for the SAME cell (two host
versions and the container's), selected by which host the job landed on, with
the pin reported satisfied on every one of them. Host and container even report
different line numbers for the same error, so a diagnosis taken on one host
does not transfer to another.

Why it hid: the pin check answers "is the image present and correct", which is
a different question from "did the tools come from it", and nothing asked the
second one. This is proxy-instead-of-property, one layer below "the image is on
the host" != "the container was built from it".

The fix has TWO halves and this file tests both AGAINST THE PROGRAM — every
assertion reads a value the program produced (its dispatch target, its written
record), never a rule recomputed here:

  1. PREDICATE — the container is preferred whenever it has iverilog and can
     SEE the run tree; the host is the fallback.
  2. PROVENANCE — `_record_sim_toolchain` writes WHICH simulator actually ran,
     measured from the side it ran on, so a residual host fallback is recorded
     as DIVERGED instead of being silent.

MUTATION CONTROL. The tests named `test_902_*` fail against the unfixed
program. The tests named `test_902_guard_*` are the PAIRED GUARD: they pass on
BOTH sides, so a future change cannot satisfy the controls by breaking true
host mode, by breaking the container-only dispatch that is already in
production, or by making the honest no-sim WAIVE stop firing.

chip/PDK/tool-AGNOSTIC: pure host/container tool-locality and attribution.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402

#: Simulation bound handed to the stage helpers below. Every one of these tests
#: monkeypatches both launchers, so nothing is really spawned; the value is kept
#: inside `ci_harness_timeout_ceiling_check`'s per-call ceiling so it needs no
#: exemption.
_T = 60

#: The record filename comes FROM THE PROGRAM. The literal is only the
#: fallback for the UNFIXED program, which has no such constant and writes no
#: record at all — without it the paired guards below could not be collected on
#: that side, and a guard you cannot run on both sides proves nothing.
_REC = getattr(dosr, "SIM_TOOLCHAIN_RECORD", "sim_toolchain.json")


def _stub_image_probe(monkeypatch, **fields):
    """Keep the image-identity lookup off real docker in tests where it is not
    the subject. `raising=False` so this is a no-op against the unfixed
    program, which has no such helper — that is what lets the paired guards run
    unchanged on both sides."""
    rec = {"declared_image_ref": None, "declared_image_id": None,
           "require_image": None, "declared_image_source": None}
    rec.update(fields)
    monkeypatch.setattr(dosr, "_declared_container_image",
                        lambda _project, _container: dict(rec), raising=False)


@pytest.fixture(autouse=True)
def _clear_record_memo():
    """The recorder memoises per (run_dir, container, tool, locality); clear it
    so tests cannot alias each other. `getattr` because this fixture must also
    be harmless against the UNFIXED program, where the memo does not exist —
    otherwise the paired guards below could not run on both sides."""
    getattr(dosr, "_SIM_TOOLCHAIN_SEEN", {}).clear()
    yield
    getattr(dosr, "_SIM_TOOLCHAIN_SEEN", {}).clear()


def _capture_launchers(monkeypatch, *, docker_out="CONTAINER_OK",
                       host_out="HOST_OK"):
    """Replace both execution launchers with recorders and return the log.

    The log is a list of ("docker"|"host", payload) in call order, so a test can
    read WHERE the program sent the work instead of asserting on a locally
    recomputed rule."""
    log = []

    def _fake_docker_exec(container, cmd, timeout=600, **_k):
        log.append(("docker", cmd))
        return 0, docker_out, ""

    def _fake_run(argv, cwd=None, timeout=600, env=None):
        log.append(("host", list(argv)))
        return 0, host_out, ""

    monkeypatch.setattr(dosr, "_docker_exec", _fake_docker_exec)
    monkeypatch.setattr(dosr, "_run", _fake_run)
    return log


def _stage_calls(log):
    """Only the STAGE dispatches — the identity probe the recorder fires is
    attribution traffic, not the simulation, and must not be mistaken for it."""
    out = []
    for where, payload in log:
        text = payload if isinstance(payload, str) else " ".join(payload)
        if "__VIBEIC_TOOL_PATH__" in text:
            continue
        out.append((where, payload))
    return out


# ==========================================================================
# HALF 1 — PREDICATE: the pinned container is where the sim runs
# ==========================================================================
def test_902_container_wins_when_host_also_has_iverilog(monkeypatch):
    """THE defect, at the predicate. Host has iverilog AND the pinned container
    has iverilog -> the sim belongs in the container. The unfixed program
    answers False here purely because the host has a binary."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True)
    assert dosr._iverilog_exec_container("pinned_container") is True


def test_902_stage_dispatches_into_container_when_host_also_has_iverilog(
        monkeypatch, tmp_path):
    """The same defect end-to-end through the program's own stage dispatcher:
    with a container supplied and BOTH sides carrying iverilog, the compile must
    reach `_docker_exec`, not the host `_run`. Asserted on the program's real
    dispatch target."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True)
    monkeypatch.setattr(dosr, "_to_container_path", lambda p, c: str(p))
    _stub_image_probe(monkeypatch)
    log = _capture_launchers(monkeypatch)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    argv = ["iverilog", "-g2012", "-o", str(run_dir / "x.vvp"),
            str(tmp_path / "tb.v")]
    rc, out, _err = dosr._run_iverilog_stage(argv, run_dir, "pinned_container",
                                             timeout=_T)

    stages = _stage_calls(log)
    assert [w for w, _ in stages] == ["docker"], (
        "the pinned container was verified and then not used: %r" % (stages,))
    assert (rc, out) == (0, "CONTAINER_OK")


def test_902_host_fallback_when_container_cannot_see_the_run_tree(
        monkeypatch, tmp_path):
    """A container that has iverilog but no bind mount covering the run tree
    cannot run the sim (`_to_container_path` would hand it an untranslated,
    non-existent path). The program must fall back to the host rather than
    dispatch into a container that cannot see the files."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: False)
    _stub_image_probe(monkeypatch)
    log = _capture_launchers(monkeypatch)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dosr._run_iverilog_stage(["iverilog", "-o", str(run_dir / "x.vvp")],
                             run_dir, "unmounted_container", timeout=_T)

    assert [w for w, _ in _stage_calls(log)] == ["host"]


# ==========================================================================
# HALF 2 — PROVENANCE: what actually ran is written down
# ==========================================================================
def test_902_host_fallback_is_recorded_as_diverged(monkeypatch, tmp_path):
    """The residual host fallback must not be silent. The record names the
    declared container, the reason, and the toolchain that really ran."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True)
    _stub_image_probe(monkeypatch, declared_image_ref="declared:ref")
    _capture_launchers(
        monkeypatch,
        host_out="__VIBEIC_TOOL_PATH__/usr/bin/iverilog\n"
                 "__VIBEIC_TOOL_VERSION__HOST_SIMULATOR_BANNER\n")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dosr._run_iverilog_stage(["iverilog", "-o", str(run_dir / "x.vvp")],
                             run_dir, "declared_container", timeout=_T)

    doc = json.loads((run_dir / _REC).read_text())
    rec = doc["records"][0]
    assert rec["verdict"] == "DIVERGED"
    assert rec["sim_toolchain_matches_declared_image"] is False
    assert rec["execution_locality"] == "host"
    assert rec["container"] == "declared_container"
    assert rec["host_fallback_reason"]
    # the version is MEASURED from the side that ran, not assumed
    assert rec["tool_version"] == "HOST_SIMULATOR_BANNER"
    assert doc["any_divergence"] is True


def test_902_container_execution_is_recorded_as_match(monkeypatch, tmp_path):
    """Ran in the declared container -> MATCH, with the container's own
    simulator banner recorded (not the host's)."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True)
    monkeypatch.setattr(dosr, "_to_container_path", lambda p, c: str(p))
    _stub_image_probe(monkeypatch, declared_image_ref="declared:ref",
                      declared_image_id="sha256:deadbeef",
                      require_image="declared:ref",
                      declared_image_source="test")
    _capture_launchers(
        monkeypatch,
        docker_out="__VIBEIC_TOOL_PATH__/foss/tools/bin/iverilog\n"
                   "__VIBEIC_TOOL_VERSION__CONTAINER_SIMULATOR_BANNER\n")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dosr._run_iverilog_stage(["iverilog", "-o", str(run_dir / "x.vvp")],
                             run_dir, "declared_container", timeout=_T)

    rec = json.loads((run_dir / _REC).read_text())["records"][0]
    assert rec["verdict"] == "MATCH"
    assert rec["sim_toolchain_matches_declared_image"] is True
    assert rec["execution_locality"] == "container"
    assert rec["tool_path"] == "/foss/tools/bin/iverilog"
    assert rec["tool_version"] == "CONTAINER_SIMULATOR_BANNER"
    assert rec["require_image"] == "declared:ref"


def test_902_no_container_is_unpinned_not_match(monkeypatch, tmp_path):
    """True host mode has nothing to match. Saying so is NOT the same as
    reporting a match — that conflation is the failure being fixed."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    _capture_launchers(monkeypatch)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dosr._run_iverilog_stage(["iverilog", "-o", str(run_dir / "x.vvp")],
                             run_dir, "", timeout=_T)

    rec = json.loads((run_dir / _REC).read_text())["records"][0]
    assert rec["verdict"] == "UNPINNED"
    assert rec["sim_toolchain_matches_declared_image"] is None


def test_902_compile_and_run_tools_are_both_recorded(monkeypatch, tmp_path):
    """A compile and its vvp run share a run_dir. Both must survive: an
    aggregate that keeps only the last one would claim the run used one tool."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    _stub_image_probe(monkeypatch)
    _capture_launchers(monkeypatch)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vvp = run_dir / "x.vvp"
    dosr._run_iverilog_stage(["iverilog", "-o", str(vvp)], run_dir,
                             "declared_container", timeout=_T)
    dosr._sim_run_or_reuse("iverilog_g2012", vvp, 0, "", "", run_dir,
                           timeout=_T, container="declared_container")

    doc = json.loads((run_dir / _REC).read_text())
    tools = sorted(r["tool"] for r in doc["records"])
    assert tools == ["iverilog", "vvp"]
    assert doc["verdicts"]["DIVERGED"] == 2


def test_902_aggregate_lands_under_reports_of_the_owning_project(
        monkeypatch, tmp_path):
    """The run-level aggregate belongs where the rest of the run's provenance
    is. The project root is derived from the layout, and the divergence flag is
    the single field a reader/gate can look at."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    _stub_image_probe(monkeypatch)
    _capture_launchers(monkeypatch)

    project = tmp_path / "proj"
    run_dir = project / "phase2" / "stage1" / "sim" / "generic_full_stack_run"
    run_dir.mkdir(parents=True)
    dosr._run_iverilog_stage(["iverilog", "-o", str(run_dir / "x.vvp")],
                             run_dir, "declared_container", timeout=_T)

    agg = json.loads((project / "reports" / _REC).read_text())
    assert agg["any_divergence"] is True
    assert agg["records"][0]["project"] == str(project)


def test_902_version_probe_reads_a_banner_written_to_stderr(monkeypatch,
                                                            tmp_path):
    """MEASURED: `iverilog -V` prints its banner on STDOUT while `vvp -V`
    prints the SAME banner on STDERR. A probe that read only stdout recorded
    the runtime half of the very same toolchain as unknown.

    This runs the program's OWN probe script in a real shell against a real
    stderr-only executable — the script text and the parser both come from the
    program, so nothing here re-implements the rule."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "p902stderrtool"
    fake.write_text("#!/bin/sh\necho 'STDERR_ONLY_BANNER' >&2\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ.get("PATH", "")))

    def _real_shell(argv, cwd=None, timeout=600, _env=None, **_k):
        # execute the PROGRAM's script; `-c` instead of `-lc` only so a login
        # profile cannot rewrite PATH out from under the test.
        cp = subprocess.run(["bash", "-c", argv[-1]], capture_output=True,
                            text=True, timeout=_T, env=env)
        return cp.returncode, cp.stdout, cp.stderr

    monkeypatch.setattr(dosr, "_run", _real_shell)
    path, version = dosr._probe_tool_identity("p902stderrtool", "", False)
    assert path == str(fake)
    assert version == "STDERR_ONLY_BANNER"


# ==========================================================================
# PAIRED GUARD — must pass on BOTH the unfixed and the fixed program.
# A future change cannot satisfy the controls above by breaking these.
# ==========================================================================
def test_902_guard_true_host_mode_still_runs_on_the_host(monkeypatch, tmp_path):
    """No container supplied -> the argv goes to the host launcher verbatim and
    nothing is dispatched. Host mode must survive the fix."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    log = _capture_launchers(monkeypatch)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    argv = ["iverilog", "-g2012", "-o", str(run_dir / "x.vvp")]
    rc, out, _err = dosr._run_iverilog_stage(argv, run_dir, "", timeout=_T)

    assert _stage_calls(log) == [("host", argv)]
    assert (rc, out) == (0, "HOST_OK")


def test_902_guard_container_only_iverilog_still_dispatches(monkeypatch,
                                                            tmp_path):
    """The canonical containerised config (no host iverilog) is already in
    production. It must keep dispatching into the container, with every
    absolute path translated and the tools PATH exported."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True)
    monkeypatch.setattr(
        dosr, "_to_container_path",
        lambda p, c: str(p)[len("/work"):] if str(p).startswith("/work")
        else str(p))
    _stub_image_probe(monkeypatch)
    log = _capture_launchers(monkeypatch)

    rc, out, _err = dosr._run_iverilog_stage(
        ["iverilog", "-g2012", "-DDUT_TOP_NAME=chip_top",
         "-o", "/work/p/run/x.vvp", "/work/p/sim/tb.v"],
        Path("/work/p/run"), "cont", timeout=_T)

    stages = _stage_calls(log)
    assert [w for w, _ in stages] == ["docker"]
    cmd = stages[0][1]
    assert "cd /p/run &&" in cmd
    assert "export PATH=%s/bin:$PATH" % dosr.TOOLS_IN_CONTAINER in cmd
    assert "/p/run/x.vvp" in cmd and "/p/sim/tb.v" in cmd
    assert "/work/" not in cmd
    assert "-DDUT_TOP_NAME=chip_top" in cmd
    assert (rc, out) == (0, "CONTAINER_OK")


def test_902_guard_no_iverilog_anywhere_stays_unavailable(monkeypatch):
    """Absent on BOTH sides -> unavailable, so the deterministic no-sim WAIVE
    still fires. The fix must not manufacture availability."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    assert dosr._iverilog_available("some_container") is False
    assert dosr._iverilog_exec_container("some_container") is False


def test_902_guard_verilator_escape_still_never_runs_vvp(monkeypatch):
    """The verilator SV-escape already ran its native binary; its captured
    result must still be reused rather than re-run on either side."""
    monkeypatch.setattr(dosr, "_run",
                        lambda *a, **k: pytest.fail("must not run vvp"))
    monkeypatch.setattr(dosr, "_docker_exec",
                        lambda *a, **k: pytest.fail("must not dispatch"))
    rc, out, _err = dosr._sim_run_or_reuse(
        "verilator_sva", Path("/p/run/none.vvp"), 0, "RAN_IN_ESCAPE", "",
        Path("/p/run"), timeout=_T, container="cont")
    assert (rc, out) == (0, "RAN_IN_ESCAPE")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
