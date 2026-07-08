"""tests/test_docker_watchdog.py — the SHARED docker glue that routes a long
in-container tool run through the general `_watchdog` primitive (v1.3.48).

Covers the docker-specific pieces INJECTED into the general supervisor:
  • parse_cputime_hms          — ps cputime token → seconds.
  • container_cpu_seconds      — marker-matched CPU sum via an injected raw exec
                                 (cputimes fast-path + cputime hms fallback +
                                 None when unavailable).
  • run_docker_supervised      — builds the ceiling `timeout` wrap + host/
                                 container argv, threads cpu_probe/kill into
                                 run_supervised, propagates (rc,out,err); the
                                 kill callback pkills the marker via the raw exec.
No real docker: the raw exec and run_supervised are injected fakes.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _docker_watchdog as DW  # noqa: E402
import _watchdog as W  # noqa: E402


def test_parse_cputime_hms():
    assert DW.parse_cputime_hms("01:02:03") == 3723
    assert DW.parse_cputime_hms("1-00:00:00") == 86400
    assert DW.parse_cputime_hms("05:30") == 330
    assert DW.parse_cputime_hms("junk") is None
    assert DW.parse_cputime_hms("") is None


def test_container_cpu_seconds_sums_marker_matches():
    marker = "/foss/x/pnr.tcl"
    ps = ("123 openroad -exit /foss/x/pnr.tcl\n"
          "  4 bash -lc openroad -exit /foss/x/pnr.tcl\n"
          " 99 klayout -b -r /other/deck\n")

    def raw(c, cmd, timeout=15):
        return (0, ps, "") if "cputimes=" in cmd else (1, "", "")

    assert DW.container_cpu_seconds("c", marker, raw) == 127.0


def test_container_cpu_seconds_none_without_marker():
    assert DW.container_cpu_seconds("c", None, lambda *a, **k: (0, "", "")) is None


def test_container_cpu_seconds_none_when_no_match():
    def raw(c, cmd, timeout=15):
        return (0, "1 openroad -exit /other.tcl\n", "")
    assert DW.container_cpu_seconds("c", "/not/here.tcl", raw) is None


def test_container_cpu_seconds_hms_fallback():
    def raw(c, cmd, timeout=15):
        if "cputimes=" in cmd:
            return (1, "", "")     # unsupported → empty
        return (0, "00:02:00 netgen -batch lvs netlist.spice top\n", "")
    assert DW.container_cpu_seconds("c", "netlist.spice", raw) == 120.0


def test_run_docker_supervised_threads_callbacks_and_wraps(monkeypatch):
    captured = {}

    def fake_supervised(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return W.SupervisedResult(0, "out", "err", "natural", 1.0)

    monkeypatch.setattr(W, "run_supervised", fake_supervised)
    raw_calls = []

    def raw(c, cmd, timeout=15):
        raw_calls.append(cmd)
        return (0, "", "")

    rc, out, err = DW.run_docker_supervised(
        "cont", "sta -no_init -exit /p/x.tcl", "/p/x.tcl",
        docker_exec_raw=raw, stall_grace_s=1800)
    assert (rc, out, err) == (0, "out", "err")
    # container argv + ceiling timeout wrap
    assert captured["cmd"][:3] == ["docker", "exec", "cont"]
    assert "timeout --kill-after=5" in captured["cmd"][-1]
    assert captured["kw"]["stall_grace_s"] == 1800
    assert callable(captured["kw"]["cpu_probe"])
    assert callable(captured["kw"]["kill"])
    # cpu_probe delegates to the injected raw exec (ps)
    captured["kw"]["cpu_probe"](object())
    assert any("cputime" in c for c in raw_calls)
    # kill callback pkills the marker via the raw exec
    class _P:
        def kill(self):
            self.killed = True
    p = _P()
    captured["kw"]["kill"](p, "stalled")
    assert any("pkill" in c and "/p/x.tcl" in c for c in raw_calls)


def test_run_docker_supervised_host_argv(monkeypatch):
    captured = {}

    def fake_supervised(cmd, **kw):
        captured["cmd"] = cmd
        return W.SupervisedResult(0, "", "", "natural", 0.0)

    monkeypatch.setattr(W, "run_supervised", fake_supervised)
    DW.run_docker_supervised("host", "magic x.tcl", "x.tcl",
                             docker_exec_raw=lambda *a, **k: (0, "", ""))
    assert captured["cmd"][0] == "bash"       # host → no docker exec prefix


def test_run_docker_supervised_propagates_stall(monkeypatch):
    monkeypatch.setattr(
        W, "run_supervised",
        lambda cmd, **kw: W.SupervisedResult(
            W.RC_STALLED, "partial", "WATCHDOG_STALLED", "stalled", 9.0))
    rc, out, err = DW.run_docker_supervised(
        "c", "yosys -s x.ys", "x.ys", docker_exec_raw=lambda *a, **k: (0, "", ""))
    assert rc == W.RC_STALLED
    assert "WATCHDOG_STALLED" in err
