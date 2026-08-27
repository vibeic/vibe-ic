"""v1.3.47 — phase3 GLUE for the progress-stall watchdog.

The general supervision primitive lives in `_watchdog.py` (tested end-to-end in
tests/test_watchdog.py). This file covers ONLY the docker/EDA-specific glue that
phase3 injects into it:
  • `_container_cpu_seconds` — the in-container CPU probe (marker-matched `ps`).
  • `_docker_exec` DISPATCH — marker=None → simple raw wall-clock; marker set →
    the watchdog path (`_watchdog.run_supervised`).
  • `_pnr_hard_ceiling_s` — the retired size ESTIMATE repurposed as a HIGH
    backstop ceiling that can never wall-clock-kill a live job.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import _watchdog as W  # noqa: E402


# ── _container_cpu_seconds parsing (marker-matched CPU sum) ───────────────────

def test_container_cpu_seconds_sums_cputimes_for_marker(monkeypatch):
    # 4-column rows (pid ppid cpu args) — shared tree-aware probe contract.
    marker = "/foss/designs/proj/pnr.tcl"
    ps_out = (
        "50 1    0 ps -eo pid=,ppid=,cputimes=,args=\n"
        "10 11 123 openroad -no_init -exit /foss/designs/proj/pnr.tcl\n"
        "11 1    4 bash -lc openroad -no_init -exit /foss/designs/proj/pnr.tcl | tee x\n"
        "12 1   99 klayout -b -r /foss/other/deck.lydrc\n"
    )
    monkeypatch.setattr(R, "_docker_exec_raw",
                        lambda c, cmd, timeout=15: (0, ps_out, ""))
    # 123 (openroad) + 4 (its bash wrapper) = 127; the klayout line is excluded.
    assert R._container_cpu_seconds("c", marker) == 127.0


def test_container_cpu_seconds_counts_descendants(monkeypatch):
    # The two-kill lesson: yosys runs ABC in a child `yosys-abc` whose argv
    # does not carry the marker — the tree closure must count it.
    marker = "/proj/synth/netlist.v"
    ps_out = (
        "100 1    5 yosys -p write_verilog /proj/synth/netlist.v\n"
        "200 100 3600 /foss/tools/yosys/bin/yosys-abc -s\n"
        "300 1   99 klayout -b -r /other/deck\n"
    )
    monkeypatch.setattr(R, "_docker_exec_raw",
                        lambda c, cmd, timeout=15: (0, ps_out, ""))
    assert R._container_cpu_seconds("c", marker) == 3605.0


def test_container_cpu_seconds_none_without_marker():
    assert R._container_cpu_seconds("c", None) is None


def test_container_cpu_seconds_fallback_to_cputime_hms(monkeypatch):
    marker = "netlist.spice"
    calls = {"n": 0}

    def fake_exec(c, cmd, timeout=15):
        calls["n"] += 1
        if "cputimes=" in cmd:
            return (1, "", "")          # cputimes unsupported → empty
        return (0, "7 1 00:02:00 netgen -batch lvs netlist.spice top\n", "")

    monkeypatch.setattr(R, "_docker_exec_raw", fake_exec)
    assert R._container_cpu_seconds("c", marker) == 120.0
    assert calls["n"] == 2, "must fall back to the cputime format"


def test_container_cpu_seconds_none_when_marker_absent(monkeypatch):
    monkeypatch.setattr(
        R, "_docker_exec_raw",
        lambda c, cmd, timeout=15: (0, "123 openroad -exit /other.tcl\n", ""))
    assert R._container_cpu_seconds("c", "/not/present.tcl") is None


def test_parse_cputime_hms():
    assert R._parse_cputime_hms("01:02:03") == 3723
    assert R._parse_cputime_hms("1-00:00:00") == 86400
    assert R._parse_cputime_hms("05:30") == 330
    assert R._parse_cputime_hms("junk") is None
    assert R._parse_cputime_hms("") is None


# ── _docker_exec DISPATCH: raw (short) vs watchdog (long, marker) ─────────────

def test_docker_exec_no_marker_uses_raw(monkeypatch):
    """A plain call (no marker) routes to _docker_exec_raw — the simple bounded
    wall-clock path — untouched, so the ~40 short call sites are unchanged."""
    seen = {}

    def fake_raw(container, cmd, timeout=1800):
        seen["raw"] = (container, timeout)
        return (0, "raw-out", "")

    monkeypatch.setattr(R, "_docker_exec_raw", fake_raw)
    # If it wrongly took the watchdog path this would call run_supervised.
    monkeypatch.setattr(W, "run_supervised",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not supervise a marker-less call")))
    rc, out, err = R._docker_exec("cont", "command -v openroad", timeout=10)
    assert (rc, out) == (0, "raw-out")
    assert seen["raw"] == ("cont", 10)


def test_docker_exec_with_marker_uses_watchdog(monkeypatch):
    """A call WITH a marker routes to _watchdog.run_supervised, and the stall /
    ceiling return codes propagate as (rc, out, err)."""
    captured = {}

    def fake_supervised(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return W.SupervisedResult(W.RC_STALLED, "part-out", "part-err\nWATCHDOG_STALLED",
                                  "stalled", 12.0)

    monkeypatch.setattr(W, "run_supervised", fake_supervised)
    rc, out, err = R._docker_exec(
        "cont", "openroad -exit /p/pnr.tcl", marker="/p/pnr.tcl",
        log_path=Path("/p/openroad.log"), stall_grace_s=1800)
    assert rc == W.RC_STALLED
    assert out == "part-out"
    assert "WATCHDOG_STALLED" in err
    # the injected callbacks + windows were threaded through
    assert captured["kw"]["stall_grace_s"] == 1800
    assert captured["kw"]["log_path"] == Path("/p/openroad.log")
    assert callable(captured["kw"]["cpu_probe"])
    assert callable(captured["kw"]["kill"])
    # cmd was wrapped with the container-side ceiling backstop `timeout`
    assert "timeout --kill-after=5" in captured["cmd"][-1]


def test_docker_exec_watchdog_cpu_probe_reads_container(monkeypatch):
    """The injected cpu_probe delegates to _container_cpu_seconds(container,
    marker) — the transport glue, not the general module.

    THE DOUBLE IS CHECKED AGAINST THE REAL SIGNATURE BEFORE IT REPLACES IT.
    `_container_cpu_seconds` gained a `pidfile=` parameter when the reap became
    identity-anchored, and `_cpu_probe` passes it by keyword. A stand-in that
    does not accept it does not make this test measure the glue less — it makes
    the glue raise TypeError inside the closure, so the test fails for the
    stand-in's shape rather than for anything about the transport. Binding the
    parameter names first turns the next such drift into a named refusal here
    instead of a TypeError in the code under test.
    """
    _real_params = set(inspect.signature(R._container_cpu_seconds).parameters)

    def _cpu_double(container, marker, timeout=15, pidfile=None):
        return 42.0 if marker == "/p/x.tcl" else None

    assert set(inspect.signature(_cpu_double).parameters) >= _real_params, (
        "the cpu-probe stand-in no longer accepts every parameter the real "
        "_container_cpu_seconds takes: missing "
        f"{sorted(_real_params - set(inspect.signature(_cpu_double).parameters))}")
    monkeypatch.setattr(R, "_container_cpu_seconds", _cpu_double)
    grabbed = {}

    def fake_supervised(cmd, **kw):
        grabbed["cpu"] = kw["cpu_probe"](object())
        return W.SupervisedResult(0, "", "", "natural", 1.0)

    monkeypatch.setattr(W, "run_supervised", fake_supervised)
    R._docker_exec("cont", "tool /p/x.tcl", marker="/p/x.tcl")
    assert grabbed["cpu"] == 42.0


# ── hard-ceiling repurpose: NEVER a wall-clock kill budget ────────────────────

def test_pnr_hard_ceiling_is_high_floor_and_never_below_estimate():
    assert R._pnr_hard_ceiling_s(0) == R._WATCHDOG_HARD_CEILING_S
    assert R._pnr_hard_ceiling_s(50_000) >= R._WATCHDOG_HARD_CEILING_S
    for cells in (0, 5_000, 31_790, 200_000, 5_000_000, -5):
        assert R._pnr_hard_ceiling_s(cells) >= R._pnr_timeout_s(cells)
        assert R._pnr_hard_ceiling_s(cells) >= R._WATCHDOG_HARD_CEILING_S
    prev = 0
    for cells in (0, 10_000, 100_000, 1_000_000, 10_000_000):
        v = R._pnr_hard_ceiling_s(cells)
        assert v >= prev
        prev = v


def test_old_estimate_retained_for_ceiling_input_only():
    """`_pnr_timeout_s` arithmetic is UNCHANGED (still a valid ceiling input);
    it is simply no longer wired to a killing timeout=."""
    assert R._pnr_timeout_s(0) == R._PNR_TIMEOUT_DEFAULT_S
    assert R._pnr_timeout_s(10_000_000) == R._PNR_TIMEOUT_CAP_S


def test_phase3_constants_bind_shared_module():
    assert R._RC_STALLED == W.RC_STALLED == 199
    assert R._WATCHDOG_STALL_GRACE_S == W.DEFAULT_STALL_GRACE_S == 1800
    assert R._WATCHDOG_HARD_CEILING_S == W.DEFAULT_HARD_CEILING_S == 86_400
