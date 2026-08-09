#!/usr/bin/env python3
"""#902 — a PINNED image must be the image that SIMULATES.

`vibe_ic_one_shot_runner --require-image ghcr.io/vibeic/vibeic-eda:<tag>`
verifies the container's image identity at launch and HALTS the run on any
non-PASS verdict. That pin was then thrown away at the one place it matters
most: `design_one_shot_runner._iverilog_exec_container` short-circuited to the
HOST the moment `shutil.which("iverilog")` found anything, so the sim ran on
whatever Icarus the machine happened to carry.

Measured on the fleet, SAME pin, same cell:

    host iverilog 11.0  -> sim ran on host 11.0
    host iverilog 12.0  -> sim ran on host 12.0
    no host iverilog    -> sim ran in the image, 14.0

Three simulator frontends for one cell, selected by which machine the job
landed on, and invisible because the pin check PASSED. The frontends are not
interchangeable: measured on 8HD-7 (host 11.0) against the pinned 0.2.78 image
(14.0), an identical two-file SystemVerilog source set where the importing
module is compiled before the package it imports gives

    host 11.0     -> rc=2, "syntax error" / "I give up."
    image 14.0    -> rc=0, .vvp produced

so the machine, not the design, decided the verdict.

The fix is a PREDICATE change: dispatch into the container whenever the
container carries iverilog. The host is the fallback — true host mode (no
container / no iverilog in it), or a container that cannot SEE the run tree
(no bind-mount covers it), where dispatching would turn a runnable sim into a
bogus "cannot open file" defect.

chip/tool-AGNOSTIC: pure host/container tool-locality plumbing over whatever
argv it is handed — no chip / PDK / vendor literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402

#: Simulation bound handed to `_sim_run_or_reuse` below. Every test patches
#: both launchers, so nothing is ever started; a value inside
#: `ci_harness_timeout_ceiling_check`'s per-call ceiling needs no exemption.
_T_PATCHED = 60


def _mixed_host_and_container(monkeypatch, *, mounted: bool = True):
    """The #902 shape: the host HAS iverilog AND the pinned container has it.

    `mounted` controls whether a bind-mount covers the run tree.
    """
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container",
                        lambda p, c: mounted)


# --------------------------------------------------------------------------
# The predicate: a pinned container that carries iverilog WINS over the host.
# --------------------------------------------------------------------------
def test_pinned_container_wins_over_a_host_that_also_has_iverilog(monkeypatch):
    """THE regression. Pre-fix this returned False — the host's Icarus ran
    the sim and the pinned image was decorative."""
    _mixed_host_and_container(monkeypatch)
    assert dosr._iverilog_exec_container(
        "c_pinned", Path("/home/u/proj/run")) is True


def test_predicate_without_a_run_dir_still_prefers_the_container(monkeypatch):
    """No locality information supplied -> still container-first, so no
    caller can silently fall back to the host by omitting the path."""
    _mixed_host_and_container(monkeypatch)
    assert dosr._iverilog_exec_container("c_pinned") is True


def test_host_iverilog_version_is_never_consulted(monkeypatch):
    """Mutation guard: the decision must not read the HOST tool at all when
    the container carries iverilog. A re-introduced `shutil.which` veto —
    in any spelling — trips this."""
    def _boom(_t):
        pytest.fail("the host tool must not veto a pinned container")
    monkeypatch.setattr("shutil.which", _boom)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True)
    assert dosr._iverilog_exec_container(
        "c_pinned", Path("/home/u/proj/run")) is True


# --------------------------------------------------------------------------
# The host fallback is still reachable — and only where it must be.
# --------------------------------------------------------------------------
def test_true_host_mode_unchanged(monkeypatch):
    """No container supplied -> host, exactly as before."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: pytest.fail(
                            "must not probe an empty container"))
    assert dosr._iverilog_exec_container("", Path("/home/u/proj/run")) is False


def test_container_without_iverilog_falls_back_to_host(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    assert dosr._iverilog_exec_container(
        "c_no_tool", Path("/home/u/proj/run")) is False


def test_unmounted_run_tree_stays_on_the_host(monkeypatch):
    """A container that cannot SEE the project must not be handed the sim —
    it would fail on 'cannot open file' and be read as a design defect. The
    host, which can actually run it, keeps the job."""
    _mixed_host_and_container(monkeypatch, mounted=False)
    assert dosr._iverilog_exec_container(
        "c_pinned", Path("/elsewhere/proj/run")) is False


def test_container_only_host_dispatches_even_when_unmounted(monkeypatch):
    """Pre-#902 behaviour for a host with NO iverilog is preserved verbatim:
    the container is the only place the sim can run, mounted or not."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: False)
    assert dosr._iverilog_exec_container(
        "c_pinned", Path("/elsewhere/proj/run")) is True


def test_absent_on_both_sides_is_false(monkeypatch):
    """Honesty preserved: nothing to run -> False, and `_iverilog_available`
    then WAIVEs without claiming a sim verdict."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    assert dosr._iverilog_exec_container("c", Path("/home/u/proj/run")) is False
    assert dosr._iverilog_available("c") is False


# --------------------------------------------------------------------------
# End of the wire: the STAGE really goes into the container, path-translated.
# --------------------------------------------------------------------------
def test_stage_dispatches_into_the_pinned_container_on_a_host_with_iverilog(
        monkeypatch):
    """The whole point: on a host that USED to run the sim itself, the argv
    now goes into the pinned container with every project path translated."""
    _mixed_host_and_container(monkeypatch)
    monkeypatch.setattr(
        dosr, "_to_container_path",
        lambda p, c: p[len("/host"):] if str(p).startswith("/host") else p)
    monkeypatch.setattr(dosr, "_run", lambda *a, **k: pytest.fail(
        "a pinned container must not be bypassed for the host"))
    seen = {}

    def _fake_docker_exec(container, cmd, timeout=600, **k):
        seen["container"] = container
        seen["cmd"] = cmd
        return 0, "CONTAINER_OK", ""

    monkeypatch.setattr(dosr, "_docker_exec", _fake_docker_exec)
    argv = ["iverilog", "-g2012", "-DDUT_TOP_NAME=chip_top",
            "-o", "/host/p/run/x.vvp", "/host/p/sim/tb.v", "/host/p/rtl/dut.v"]
    rc, out, _err = dosr._run_iverilog_stage(
        argv, Path("/host/p/run"), "c_pinned", 120)

    assert (rc, out) == (0, "CONTAINER_OK")
    assert seen["container"] == "c_pinned"
    cmd = seen["cmd"]
    assert "cd /p/run &&" in cmd
    assert "export PATH=%s/bin:$PATH" % dosr.TOOLS_IN_CONTAINER in cmd
    assert "/p/run/x.vvp" in cmd and "/p/sim/tb.v" in cmd and "/p/rtl/dut.v" in cmd
    assert "/host/" not in cmd            # no untranslated host path leaks
    assert "-DDUT_TOP_NAME=chip_top" in cmd and "-g2012" in cmd


def test_stage_falls_back_to_host_verbatim_when_tree_is_unmounted(monkeypatch):
    """The safety valve at the wire: argv handed to `_run` unchanged."""
    _mixed_host_and_container(monkeypatch, mounted=False)
    monkeypatch.setattr(dosr, "_docker_exec", lambda *a, **k: pytest.fail(
        "an unreadable container must not be handed the sim"))
    seen = {}

    def _fake_run(argv, cwd=None, timeout=600, env=None):
        seen["argv"] = list(argv)
        seen["cwd"] = cwd
        return 0, "HOST_OK", ""

    monkeypatch.setattr(dosr, "_run", _fake_run)
    argv = ["iverilog", "-g2012", "-o", "/elsewhere/run/x.vvp",
            "/elsewhere/sim/tb.v"]
    rc, out, _err = dosr._run_iverilog_stage(
        argv, Path("/elsewhere/run"), "c_pinned", 120)
    assert (rc, out) == (0, "HOST_OK")
    assert seen["argv"] == argv
    assert str(seen["cwd"]) == "/elsewhere/run"


# --------------------------------------------------------------------------
# Lock-step: compile and vvp must land on the SAME side.
# --------------------------------------------------------------------------
def test_compile_and_vvp_land_on_the_same_side(monkeypatch):
    """A container-built `.vvp` handed to a host `vvp` (or vice versa) is a
    version mismatch. Both stages are decided from the same `run_dir`, so the
    two calls must agree — asserted by running them back to back."""
    _mixed_host_and_container(monkeypatch)
    monkeypatch.setattr(dosr, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(dosr, "_run", lambda *a, **k: pytest.fail(
        "neither stage may fall to the host here"))
    sides = []

    def _fake_docker_exec(container, cmd, timeout=600, **k):
        sides.append(cmd)
        return 0, "OK", ""

    monkeypatch.setattr(dosr, "_docker_exec", _fake_docker_exec)
    run = Path("/home/u/proj/run")
    dosr._run_iverilog_stage(
        ["iverilog", "-o", "/home/u/proj/run/x.vvp", "/home/u/proj/sim/tb.v"],
        run, "c_pinned", 120)
    dosr._sim_run_or_reuse("iverilog_g2012", run / "x.vvp", 0, "", "",
                           run, timeout=_T_PATCHED, container="c_pinned")
    assert len(sides) == 2, "both stages must have been dispatched"
    assert "iverilog" in sides[0]
    assert "vvp" in sides[1] and "/home/u/proj/run/x.vvp" in sides[1]


def test_verilator_escape_reuse_is_untouched(monkeypatch):
    """The #703 reuse path never runs vvp on either side — unchanged."""
    monkeypatch.setattr(dosr, "_run", lambda *a, **k: pytest.fail("no vvp"))
    monkeypatch.setattr(dosr, "_docker_exec",
                        lambda *a, **k: pytest.fail("no dispatch"))
    rc, out, _err = dosr._sim_run_or_reuse(
        "verilator_sva", Path("/home/u/proj/run/none.vvp"), 0, "RAN", "",
        Path("/home/u/proj/run"), timeout=_T_PATCHED, container="c_pinned")
    assert (rc, out) == (0, "RAN")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
