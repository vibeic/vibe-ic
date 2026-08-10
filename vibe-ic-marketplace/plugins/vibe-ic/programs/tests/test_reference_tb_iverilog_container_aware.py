#!/usr/bin/env python3
"""The reference-TB / full-stack sim gate must be CONTAINER-AWARE.

Repro (subservient x sky130A, 8HD-4): the runner ran on the HOST and
dispatched EDA tools into `--container` (a 0.2.28 iic-osic-tools). iverilog
lived ONLY in the container (/foss/tools/bin/iverilog — our Icarus fork);
the host had none. The Step-4 connectivity/full-stack sim gate probed the
HOST (`shutil.which("iverilog")`), found nothing, and either skipped the sim
emitting `iverilog_available: false` or hard-FAILed "by construction" — a
"check that lies": it reported a sim verdict without ever running the sim.
Even past the probe, the compile+run were executed on the HOST with a bare
`iverilog`/`vvp` argv, so a container-only iverilog still never ran.

The fix: availability AND execution are container-aware. Prefer the
container; fall back to the host only when the host actually has iverilog.
Honesty preserved: iverilog absent in BOTH -> availability False -> the
deterministic no-sim WAIVE still fires.

chip/tool-AGNOSTIC: no chip / PDK / vendor literal — pure host/container
tool-locality plumbing over whatever argv it is handed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402

#: The simulation bound handed to `_sim_run_or_reuse` in the tests below.
#:
#: Every one of those tests monkeypatches `dosr._run` AND `dosr._docker_exec`
#: — several of them to a `pytest.fail` that asserts the launcher is not
#: reached at all — so no process is started and the measured worst case at
#: those call sites is a dictionary write. The value used to be 120, which is
#: over `ci_harness_timeout_ceiling_check`'s per-call ceiling (the harness bound
#: // 3 = 60 s) and therefore sat on that gate's advisory list of bounds it
#: cannot resolve. A number inside the ceiling needs no exemption.
_T_PATCHED = 60


# --------------------------------------------------------------------------
# _iverilog_available — container-first availability
# --------------------------------------------------------------------------
def test_available_when_only_container_has_iverilog(monkeypatch):
    """The exact repro shape: host has NO iverilog, container DOES."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    assert dosr._iverilog_available("rv_subservient_926009") is True


def test_available_in_true_host_mode_unchanged(monkeypatch):
    """No container supplied + host has iverilog -> available (host mode)."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: pytest.fail(
                            "must not probe container in host mode"))
    assert dosr._iverilog_available("") is True


def test_unavailable_when_both_missing_keeps_honesty(monkeypatch):
    """Absent in BOTH -> False, so the honest no-sim WAIVE still fires."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    assert dosr._iverilog_available("some_container") is False


def test_container_absent_but_host_present_is_available(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    assert dosr._iverilog_available("c") is True


# --------------------------------------------------------------------------
# _iverilog_exec_container — WHERE compile+run execute
# --------------------------------------------------------------------------
def test_exec_prefers_container_even_when_host_has_iverilog(monkeypatch):
    """#902 — this assertion USED TO READ `is False`: whenever the host carried
    any iverilog the sim ran there, so a run that pinned an image verified it
    and then simulated with the machine's own simulator. MEASURED across a
    fleet: three different Icarus frontends for the SAME cell, chosen by which
    host the job landed on, with the pin reported satisfied every time.

    The contract is now the same container-first order `_iverilog_available`
    already uses, so availability and execution cannot disagree about where the
    simulator is. The host fallbacks that remain (no iverilog in the container,
    or the container cannot see the run tree) are covered below and are
    RECORDED rather than silent."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: True)
    assert dosr._iverilog_exec_container("c") is True


def test_exec_in_container_when_only_container_has_iverilog(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    assert dosr._iverilog_exec_container("cont") is True


def test_exec_neither_side_is_host_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda c, t: False)
    assert dosr._iverilog_exec_container("cont") is False
    assert dosr._iverilog_exec_container("") is False


# --------------------------------------------------------------------------
# _run_iverilog_stage — dispatch + path translation
# --------------------------------------------------------------------------
def test_stage_runs_on_host_unchanged(monkeypatch):
    """True host mode: the argv is handed to _run verbatim with cwd=run_dir;
    _docker_exec is never touched (behaviour unchanged)."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    monkeypatch.setattr(dosr, "_docker_exec",
                        lambda *a, **k: pytest.fail("host mode must not dispatch"))
    seen = {}

    def _fake_run(argv, cwd=None, timeout=600, env=None):
        seen["argv"] = list(argv)
        seen["cwd"] = cwd
        return 0, "HOST_OK", ""

    monkeypatch.setattr(dosr, "_run", _fake_run)
    argv = ["iverilog", "-g2012", "-o", "/w/p/run/x.vvp", "/w/p/sim/tb.v"]
    rc, out, err = dosr._run_iverilog_stage(argv, Path("/w/p/run"), "", 120)
    assert (rc, out) == (0, "HOST_OK")
    assert seen["argv"] == argv          # verbatim, no docker wrapping
    assert str(seen["cwd"]) == "/w/p/run"


def test_stage_dispatches_into_container_with_translated_paths(monkeypatch):
    """Container-only iverilog: the stage is dispatched via _docker_exec,
    every project path is translated host->container, the tools PATH is put
    on, and the cwd is the translated run_dir. _run is never used."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    # #902 — dispatch also requires the container to SEE the tree. Stubbed
    # here (raising=False: a no-op against the pre-#902 program) so this test
    # keeps asserting exactly what it always asserted, on both sides.
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True,
                        raising=False)
    # deterministic host->container mount translation: strip a /work prefix.
    monkeypatch.setattr(
        dosr, "_to_container_path",
        lambda p, c: p[len("/work"):] if str(p).startswith("/work") else p)
    monkeypatch.setattr(dosr, "_run",
                        lambda *a, **k: pytest.fail("container mode must not use host _run"))
    seen = {}

    def _fake_docker_exec(container, cmd, timeout=600, **k):
        seen["container"] = container
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        return 0, "CONTAINER_OK", ""

    monkeypatch.setattr(dosr, "_docker_exec", _fake_docker_exec)
    argv = ["iverilog", "-g2012", "-DDUT_TOP_NAME=chip_top",
            "-o", "/work/p/run/x.vvp", "/work/p/sim/tb.v", "/work/p/rtl/dut.v"]
    rc, out, err = dosr._run_iverilog_stage(
        argv, Path("/work/p/run"), "rv_subservient_926009", 120)

    assert (rc, out) == (0, "CONTAINER_OK")
    assert seen["container"] == "rv_subservient_926009"
    cmd = seen["cmd"]
    # cwd translated + tools PATH exported so the fork's iverilog is found.
    assert "cd /p/run &&" in cmd
    assert "export PATH=%s/bin:$PATH" % dosr.TOOLS_IN_CONTAINER in cmd
    # every project path translated; NO host /work/ prefix leaks in.
    assert "/p/run/x.vvp" in cmd
    assert "/p/sim/tb.v" in cmd
    assert "/p/rtl/dut.v" in cmd
    assert "/work/" not in cmd
    # non-path tokens (tool name, flags, -D defines) pass through untouched.
    assert "iverilog" in cmd and "-g2012" in cmd
    assert "-DDUT_TOP_NAME=chip_top" in cmd


def test_stage_runs_vvp_in_container_too(monkeypatch):
    """The vvp RUN follows the same host/container decision as the compile,
    so a container-compiled image is run where it exists."""
    monkeypatch.setattr("shutil.which", lambda _t: None)
    monkeypatch.setattr(dosr, "_tool_in_container",
                        lambda c, t: t == "iverilog")
    monkeypatch.setattr(dosr, "_path_in_container", lambda p, c: True,
                        raising=False)
    monkeypatch.setattr(dosr, "_to_container_path", lambda p, c: p)
    calls = {}

    def _fake_docker_exec(container, cmd, timeout=600, **k):
        calls["cmd"] = cmd
        return 0, "VVP_OK", ""

    monkeypatch.setattr(dosr, "_docker_exec", _fake_docker_exec)
    monkeypatch.setattr(dosr, "_run",
                        lambda *a, **k: pytest.fail("host _run must not be used"))
    rc, out, err = dosr._sim_run_or_reuse(
        "iverilog_g2012", Path("/p/run/x.vvp"), 0, "", "",
        Path("/p/run"), timeout=_T_PATCHED, container="cont")
    assert (rc, out) == (0, "VVP_OK")
    assert "vvp" in calls["cmd"] and "/p/run/x.vvp" in calls["cmd"]


def test_sim_run_or_reuse_host_default_is_backward_compatible(monkeypatch):
    """No container arg -> host vvp run, exactly as before the fix."""
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/iverilog")
    seen = {}

    def _fake_run(argv, cwd=None, timeout=600, env=None):
        seen["argv"] = list(argv)
        return 0, "ok", ""

    monkeypatch.setattr(dosr, "_run", _fake_run)
    monkeypatch.setattr(dosr, "_docker_exec",
                        lambda *a, **k: pytest.fail("host default must not dispatch"))
    dosr._sim_run_or_reuse("iverilog_g2012", Path("/p/run/x.vvp"),
                           0, "", "", Path("/p/run"), timeout=_T_PATCHED)
    assert seen["argv"] == ["vvp", "/p/run/x.vvp"]


def test_verilator_sva_reuse_never_runs_vvp(monkeypatch):
    """The #703 verilator-escape reuse path is unaffected: it returns the
    captured result and never dispatches a vvp run on either side."""
    monkeypatch.setattr(dosr, "_run",
                        lambda *a, **k: pytest.fail("must not run vvp"))
    monkeypatch.setattr(dosr, "_docker_exec",
                        lambda *a, **k: pytest.fail("must not dispatch"))
    rc, out, err = dosr._sim_run_or_reuse(
        "verilator_sva", Path("/p/run/none.vvp"), 0, "RAN_IN_ESCAPE", "",
        Path("/p/run"), timeout=_T_PATCHED, container="cont")
    assert (rc, out) == (0, "RAN_IN_ESCAPE")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
