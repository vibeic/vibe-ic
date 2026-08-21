"""#643 — a scored simulation that timed out was abandoned, not killed.

`subprocess.run(timeout=N)` kills its DIRECT CHILD. When `vvp` on PATH is a shim

    #!/usr/bin/env bash
    exec docker exec -w "$PWD" <container> /foss/tools/bin/vvp "$@"

the direct child is the docker CLIENT, and `docker exec` has no
kill-on-disconnect: the client dies and the simulation runs forever. Four were
found at 99.9 % CPU on `.114` roughly four hours after the run that started them
had already written its RESULT.

WHY IT IS A MEASUREMENT DEFECT AND NOT HOUSEKEEPING: `sim_timeout` is a scored
verdict, so the leak feeds itself — a hung TB steals a core, the next design is
scored on a smaller machine, a design near the bound now exceeds it and is
scored `sim_timeout`, which leaks another core. The designs scored last were
measured under conditions the ones scored first never saw, and a re-score starts
with the previous run's leaks still burning.

MEASURED END-TO-END in a live container (`a13r2-eda`), one hanging TB, one 8 s
bound, the same shim, run twice:

    before   TimeoutExpired   11.0 s   1 vvp still at 99.9 % CPU 3 s later
    after    TimeoutExpired    6.1 s   0

Both raise, which is why nothing noticed: the exception is identical and the
verdict is identical. The only thing that differs is what is still running.

WHY THE EXISTING GATE COULD NOT SEE IT: `container_exec_deadline_check.py` was
written for exactly this defect, and its population is "an argv literal that
STARTS a `docker exec`". These call sites say `vvp`. The containerization lives
in PATH, not in the argv — invisible to any static scan, which is why the fix
has to ask, at run time, what `vvp` actually is.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_SCORER = _REPO / "vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_iverilog_tb.py"

_spec = importlib.util.spec_from_file_location("score_iverilog_tb", _SCORER)
S = importlib.util.module_from_spec(_spec)
sys.modules["score_iverilog_tb"] = S
try:
    _spec.loader.exec_module(S)
except SystemExit:
    pass


def _shim(tmp_path, body: str):
    p = tmp_path / "vvp"
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")
    p.chmod(0o755)
    return p


# ── what is `vvp`, really ──────────────────────────────────────────────────
def test_it_reads_the_container_out_of_the_shim_found_in_the_field(tmp_path):
    """The exact shape on `.114`. The shim is written by the benchmark host, not
    by this repo, so the only honest way to know the route is to read the file
    actually on PATH."""
    p = _shim(tmp_path, 'exec docker exec -w "$PWD" vibeic-eda-edge1 '
                        '/foss/tools/bin/vvp "$@"')
    assert S._vvp_route_of(p) == ("vibeic-eda-edge1", "/foss/tools/bin/vvp")


def test_flags_are_not_mistaken_for_the_container_name(tmp_path):
    """LOAD-BEARING. `-w`/`-u`/`-e` CONSUME the next token; `-i`/`-t` do not.
    Taking the first non-flag token without that distinction names `/work` (the
    value of `-w`) as the container, and every run then fails to launch — which
    would look like a scorer regression, not like this fix."""
    p = _shim(tmp_path, 'exec docker exec -it -u root --workdir /work '
                        '-e FOO=1 mycontainer /foss/tools/bin/vvp "$@"')
    assert S._vvp_route_of(p) == ("mycontainer", "/foss/tools/bin/vvp")


def test_a_real_binary_is_not_a_shim():
    """THE ACCEPT CASE, and the one that decides whether this can ship: on a host
    with a real iverilog the bound was always correct, and must keep behaving
    exactly as before."""
    import shutil
    real = shutil.which("vvp")
    if not real:
        return
    if pathlib.Path(real).read_bytes()[:2] == b"#!":
        return                      # this host is itself shimmed; nothing to assert
    assert S._vvp_route_of(real) is None


def test_a_script_that_does_not_route_into_a_container_is_not_a_shim(tmp_path):
    p = _shim(tmp_path, 'exec /usr/local/bin/vvp.real "$@"')
    assert S._vvp_route_of(p) is None


def test_no_vvp_on_path_is_not_a_crash():
    assert S._vvp_route_of(None) is None
    assert S._vvp_route_of(str(pathlib.Path("/nonexistent/vvp"))) is None


# ── where the bound lands ──────────────────────────────────────────────────
def _capture_argv(monkeypatch, rc=0):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        return subprocess.CompletedProcess(argv, rc, "", "")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    return seen


def test_the_container_route_bounds_the_tool_not_the_client(monkeypatch):
    """The whole issue in one assertion: `timeout` must be in front of the tool
    INSIDE the container. GNU `timeout` signals the process GROUP, so a tool that
    spawns children is torn down whole."""
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: True)
    seen = _capture_argv(monkeypatch)
    S._bounded_vvp("bin", timeout=30, cwd="/w", route=("ct", "/foss/tools/bin/vvp"))
    argv = seen["argv"]
    assert argv[:5] == ["docker", "exec", "-w", "/w", "ct"]
    i = argv.index("timeout")
    assert argv[i:i + 3] == ["timeout", "--kill-after=5", "25"]
    assert i < argv.index("/foss/tools/bin/vvp"), "the bound is behind the tool"


def test_the_inner_deadline_fires_before_the_host_one(monkeypatch):
    """Firing 5 s early means the container side is already dead when the host
    would have given up — otherwise the host raises first and we are back to
    abandoning the work."""
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: True)
    seen = _capture_argv(monkeypatch)
    # 60 and not 120: `_capture_argv` monkeypatches `S.subprocess.run`, so this
    # call launches nothing and the measured worst case is a dict write. 120 was
    # over `ci_harness_timeout_ceiling_check`'s per-call ceiling (harness // 3 =
    # 60 s) and sat on that gate's advisory list. The 5 s head start is what the
    # test is about, and it is the same claim at any scale.
    S._bounded_vvp("bin", timeout=60, cwd="/w", route=("ct", "vvp"))
    argv, kw = seen["argv"], seen["kw"]
    assert argv[argv.index("timeout") + 2] == "55"
    assert kw["timeout"] == 60, "the host bound stays as the backstop"


def test_a_short_bound_does_not_become_a_nonpositive_one(monkeypatch):
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: True)
    seen = _capture_argv(monkeypatch)
    S._bounded_vvp("bin", timeout=3, cwd="/w", route=("ct", "vvp"))
    assert seen["argv"][seen["argv"].index("timeout") + 2] == "1"


def test_no_shell_is_interposed(monkeypatch):
    """LOAD-BEARING, and the reason this does not reuse
    `_docker_watchdog.wrap_with_container_timeout`: that helper runs through
    `bash -lc`, and this container's login profile PRINTS
    (`[INFO] Final PATH variable: …`) — measured, it is what broke the first
    version of the end-to-end probe. This call's stdout is the exact text
    `pass_regex`/`fail_regex` are matched against, so a banner in there is a
    SCORING hazard. The remote path arrives from the shim already absolute, so
    no login profile is needed to resolve it."""
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: True)
    seen = _capture_argv(monkeypatch)
    S._bounded_vvp("bin", timeout=30, cwd="/w", route=("ct", "/foss/tools/bin/vvp"))
    for tok in seen["argv"]:
        assert tok not in ("bash", "sh", "-lc", "-c"), tok


def test_a_container_without_timeout_still_runs(monkeypatch):
    """Degradation must be to the OLD behaviour, never to a hard failure — a
    container missing `timeout` would otherwise turn every simulation into an
    error and every design into a FAIL."""
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: False)
    seen = _capture_argv(monkeypatch)
    S._bounded_vvp("bin", timeout=30, cwd="/w", route=("ct", "vvp"))
    assert "timeout" not in seen["argv"]
    assert seen["argv"][-2:] == ["vvp", "bin"]


def test_the_host_route_is_the_plain_call_it_always_was(monkeypatch):
    seen = _capture_argv(monkeypatch)
    S._bounded_vvp("bin", timeout=30, cwd="/w", route=None)
    # route=None means "already resolved, no container" only when the resolver
    # agrees; force that so the test does not depend on this host's PATH.
    monkeypatch.setattr(S, "_resolve_vvp_route", lambda: None)
    S._bounded_vvp("bin", timeout=30, cwd="/w")
    assert seen["argv"] == ["vvp", "bin"]
    assert seen["kw"]["cwd"] == "/w" and seen["kw"]["timeout"] == 30


# ── the verdict every call site already handles must not change ────────────
def test_the_container_deadline_is_reported_as_a_timeout(monkeypatch):
    """Seven call sites catch `subprocess.TimeoutExpired` and each attaches its
    own meaning to it (`sim_timeout`, "stub hangs the TB ⇒ inconclusive", "keep
    FAIL"). GNU `timeout` reports through rc 124 — returning that as an ordinary
    result would silently convert every timeout into a rc-124 FAIL and rewrite
    verdicts this fix has no business touching."""
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: True)
    for rc in (124, 137):
        _capture_argv(monkeypatch, rc=rc)
        try:
            S._bounded_vvp("bin", timeout=30, cwd="/w", route=("ct", "vvp"))
        except subprocess.TimeoutExpired as e:
            assert e.timeout == 30
        else:
            raise AssertionError(f"rc {rc} did not surface as a timeout")


def test_an_ordinary_nonzero_rc_is_still_an_ordinary_result(monkeypatch):
    """A simulation that ran and failed is NOT a timeout. Over-claiming here
    would convert real FAILs into `sim_timeout`, which is the same class of
    error as the leak, pointed the other way."""
    monkeypatch.setattr(S, "_container_has_timeout", lambda c: True)
    seen = _capture_argv(monkeypatch, rc=1)
    r = S._bounded_vvp("bin", timeout=30, cwd="/w", route=("ct", "vvp"))
    assert r.returncode == 1 and seen["argv"]


# ── the anti-regression that makes it stick ────────────────────────────────
def test_no_bounded_vvp_call_bypasses_the_helper():
    """Seven call sites had this defect independently. A new one added later
    would reintroduce it invisibly — both routes raise the same exception and
    record the same verdict, so the only observable difference is a process
    nobody is looking at."""
    src = _SCORER.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert '["vvp", binp]' not in body, \
        "a bounded vvp call is going straight to subprocess.run again"
    assert body.count("_bounded_vvp(binp,") >= 7
