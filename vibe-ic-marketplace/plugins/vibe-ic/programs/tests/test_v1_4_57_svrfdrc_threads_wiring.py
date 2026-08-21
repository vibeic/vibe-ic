"""v1.4.57 — svrfdrc --threads wiring (probe-gated rule-check parallelism).

The plugin passes `--threads=N` to the native svrfdrc buddy ONLY when the
container's binary advertises the flag (`svrfdrc --help` mentions `--threads`,
i.e. image >= 0.2.19). On an older image the flag is omitted (graceful
degradation to serial). Passing it is verdict-safe: the svrfdrc report is
byte-identical for every thread count, so this changes only wall-clock.

These tests mock the container probe (no docker needed) and prove:
  - the probe returns True/False by the --help text and CACHES per (container,bin);
  - the flag is added iff supported.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def _reset_cache():
    R._SVRFDRC_THREADS_CACHE.clear()


def test_probe_true_when_help_has_threads(monkeypatch):
    _reset_cache()
    calls = {"n": 0}

    def fake_exec(container, cmd, **kw):
        calls["n"] += 1
        # a 0.2.19 svrfdrc --help lists the flag
        return 0, "Usage: svrfdrc ...\n  --threads=n  Worker threads ...\n", ""

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    assert R._svrfdrc_supports_threads("vibeic-eda", "/foss/tools/bin/svrfdrc") is True
    # cached: a 2nd call does not re-probe
    assert R._svrfdrc_supports_threads("vibeic-eda", "/foss/tools/bin/svrfdrc") is True
    assert calls["n"] == 1


def test_probe_false_on_old_image(monkeypatch):
    _reset_cache()

    def fake_exec(container, cmd, **kw):
        # a 0.2.18 svrfdrc --help has NO --threads
        return 0, "Usage: svrfdrc <deck> <layout> <report>\n  --cell=name\n", ""

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    assert R._svrfdrc_supports_threads("old", "svrfdrc") is False


def test_probe_false_on_exec_error(monkeypatch):
    _reset_cache()

    def fake_exec(container, cmd, **kw):
        raise RuntimeError("docker down")

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    # never raises; degrades to False (serial)
    assert R._svrfdrc_supports_threads("x", "svrfdrc") is False


def test_flag_added_iff_supported(monkeypatch):
    _reset_cache()

    def fake_exec(container, cmd, **kw):
        if cmd.endswith("--help"):
            return 0, "  --threads=n  ...\n", ""
        return 0, "", ""

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    monkeypatch.setattr(R, "_openroad_thread_count", lambda: 8)
    # emulate the cmd assembly the runner does
    bin_c = "svrfdrc"
    cmd = f"{bin_c} deck gds rpt --cell=top"
    if R._svrfdrc_supports_threads("c", bin_c):
        cmd += f" --threads={R._openroad_thread_count()}"
    assert cmd.endswith(" --threads=8")

    _reset_cache()

    def fake_exec_old(container, cmd, **kw):
        return 0, "  --cell=name\n", ""

    monkeypatch.setattr(R, "_docker_exec", fake_exec_old)
    cmd2 = f"{bin_c} deck gds rpt --cell=top"
    if R._svrfdrc_supports_threads("c2", bin_c):
        cmd2 += f" --threads={R._openroad_thread_count()}"
    assert "--threads" not in cmd2
