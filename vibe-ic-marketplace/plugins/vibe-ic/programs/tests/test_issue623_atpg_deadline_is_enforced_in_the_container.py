"""#623 — a client-side timeout killed the docker CLIENT, not the ATPG engine.

`fault_atpg_run._run_docker` started the engine with `docker run --rm` under a
client-side `subprocess.run(..., timeout=)`. That bounds the docker CLIENT: on
expiry Python killed the client and the container carried on, because the engine
is not a child of the client and no signal crosses the boundary. Two harms
followed from that one fact:

  1. THE COMPLETED MEASUREMENT WAS DISCARDED. The engine kept running, finished,
     wrote `coverage.yml` into the mounted project — 331 s and 312 s after the
     caller had already recorded "no measurement", both carrying a
     byte-identical `ratio: 9.16633307933807e-1` — and nothing looked again.
     `--rm` then removed the evidence that it had ever run.
  2. THE CONTAINER WAS NEVER REAPED. It self-removes only when the engine
     finishes on its own; one was recorded still burning a core after the flow
     had ended. `--rm` makes it look self-cleaning, which is why this stayed
     invisible.

Both are fixed by the primitive this repo already landed for the same defect in
`docker exec` (`_container_exec`): coreutils `timeout`, running INSIDE the
container as the engine's own parent, can signal it.

THE DEADLINE IS `budget + flush grace`, on purpose. Killing an engine minutes
from finishing because a size-independent constant expired discards work the run
exists to produce. The grace is a CAP on flush time, not an estimate of how long
ATPG needs — #581 declined to invent the latter and that stands.

MEASURED AGAINST A REAL CONTAINER, all three directions:

    pre-fix path   client TimeoutExpired at 5.0s, 1 container still running
    fixed path     rc 124 at 5.5s, 0 containers still running
    the grace      budget 4s + grace 10s, engine needs 9s -> rc 0 at 9.5s
                   (it was allowed to finish; the measurement is not discarded)

A NOTE ON THE PROBE, because it nearly inverted the result. The first survivor
count used `docker ps --format "{{.Command}}"`, which TRUNCATES the command, so
the mark at the end was cut off and the pre-fix path read as 0 survivors — while
the reap step immediately after found one. `docker inspect -f {{.Config.Cmd}}`
gives the full command; the corrected probe is what the numbers above come from.

WHAT THIS DOES NOT DO, stated: it does not harvest a `coverage.yml` that a
PREVIOUS run left behind. It removes the reason one gets stranded. #623's
`--publish-existing-coverage` and the size-independent budget (#623 §3) are the
remaining halves and are not touched here.
"""
from __future__ import annotations

import importlib
import shlex
import subprocess

F = importlib.import_module("fault_atpg_run")
CE = importlib.import_module("_container_exec")


class _Rec:
    """Capture the argv and the client-side timeout `_run_docker` would use."""

    def __init__(self, rc=0, out="", err="", raise_timeout=False):
        self.rc, self.out, self.err = rc, out, err
        self.raise_timeout = raise_timeout
        self.argv = None
        self.timeout = None

    def __call__(self, argv, **kw):
        self.argv = argv
        self.timeout = kw.get("timeout")
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(argv, self.timeout or 0)
        return subprocess.CompletedProcess(argv, self.rc, self.out, self.err)


def _drive(monkeypatch, tmp_path, rec, **kw):
    monkeypatch.setattr(F.subprocess, "run", rec)
    return F._run_docker(tmp_path, ["fault", "atpg"], **kw)


# ── the deadline is inside the container ────────────────────────────────────
def test_the_engine_runs_under_a_container_side_deadline(monkeypatch, tmp_path):
    """LOAD-BEARING. Without this the deadline exists only in the caller's
    belief: the client dies and the engine does not.

    Driven at SMALL numbers on purpose: a test that hands a launcher
    `timeout=1800` carries an 1800-second bound the 180s harness can outlive,
    which kills the session instead of the test. The production-sized
    arithmetic is asserted on `atpg_container_deadline`, which blocks on
    nothing."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=10, flush_grace_s=20)
    shell = rec.argv[-1]
    assert shell.startswith(f"timeout -k {CE.DEFAULT_KILL_GRACE_S} 30 bash -c "), shell


def test_the_kill_escalation_comes_from_the_shared_constant(monkeypatch, tmp_path):
    """`-k` escalates to SIGKILL for an engine that ignores SIGTERM while
    writing. Sourced from `_container_exec` so the two deadline paths cannot
    drift into different escalation policies."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=60, flush_grace_s=0)
    assert f"-k {CE.DEFAULT_KILL_GRACE_S} " in rec.argv[-1]


def test_the_command_is_quoted_not_concatenated(monkeypatch, tmp_path):
    """The engine command now sits inside another `bash -c`, so an unquoted
    `&&` or `;` would be executed by the OUTER shell instead of the engine's —
    changing what runs rather than merely how it is bounded."""
    rec = _Rec()
    monkeypatch.setattr(F.subprocess, "run", rec)
    F._run_docker(tmp_path, ["fault atpg && echo pwned"], timeout=10,
                  flush_grace_s=0)
    shell = rec.argv[-1]
    inner = shell.split("bash -c ", 1)[1]
    assert inner.startswith(("'", '"')), shell
    assert "&& echo pwned" in shlex.split(shell)[-1]


# ── the grace is a real extension, and it is bounded ────────────────────────
def test_the_grace_extends_the_deadline(monkeypatch, tmp_path):
    """The measured overshoots were 331 s and 312 s against an 1800 s budget.
    An engine cut off at the budget loses a measurement it was about to write."""
    assert F.atpg_container_deadline(1800, 600) == 2400
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=10, flush_grace_s=20)
    assert " 30 bash -c " in rec.argv[-1], "the argv does not carry the sum"


def test_the_default_grace_is_the_declared_constant(monkeypatch, tmp_path):
    assert (F.atpg_container_deadline(1800)
            == 1800 + F.ATPG_FLUSH_GRACE_S)
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=7)
    assert f" {7 + F.ATPG_FLUSH_GRACE_S} bash -c " in rec.argv[-1]


def test_a_zero_grace_is_honoured(monkeypatch, tmp_path):
    """A caller that wants the budget enforced exactly must be able to say so;
    a grace that cannot be switched off is a hidden budget increase."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=45, flush_grace_s=0)
    assert " 45 bash -c " in rec.argv[-1]


def test_the_deadline_is_never_zero_or_negative(monkeypatch, tmp_path):
    """`timeout 0` means NO deadline in coreutils — the one value that must
    never be produced by arithmetic here."""
    assert F.atpg_container_deadline(0, -5) == 1
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=0, flush_grace_s=-5)
    assert " 1 bash -c " in rec.argv[-1]


# ── the client-side wait is a backstop, and says so ─────────────────────────
def test_the_client_wait_is_strictly_larger_than_the_container_deadline(
        monkeypatch, tmp_path):
    """If it were not, the client would fire first and orphan the engine again
    — the defect, restored by an off-by-one."""
    rec = _Rec()
    _drive(monkeypatch, tmp_path, rec, timeout=10, flush_grace_s=20)
    assert rec.timeout == 30 + CE.CLIENT_GRACE_S
    assert rec.timeout > 30


def test_the_backstop_firing_names_what_it_means(monkeypatch, tmp_path):
    """A merely-slow engine can no longer reach this branch, so reaching it is
    information: the CONTAINER is unresponsive, not the tool. "docker command
    timed out" pointed at the tool and sent the reader to the wrong place."""
    _force_container_route(monkeypatch)
    rc, _out, err = _drive(monkeypatch, tmp_path, _Rec(raise_timeout=True),
                           timeout=10, flush_grace_s=5)
    assert rc == 124
    assert "container" in err and "unresponsive" in err
    assert "docker command timed out" not in err


def test_the_local_backstop_does_not_blame_a_container(monkeypatch, tmp_path):
    """Same event, other route, and the wording must NOT be copied across: on
    the local route there IS no container, so "the container is unresponsive"
    would send the reader to look at something that was never started. Both
    messages have to name the deadline that did not fire; only one of them may
    name a container."""
    _force_local_route(monkeypatch)
    rc, _out, err = _drive(monkeypatch, tmp_path, _Rec(raise_timeout=True),
                           timeout=10, flush_grace_s=5)
    assert rc == 124
    assert "local backstop" in err, err
    assert "container" not in err, err


# ── WHICH ROUTE ARE WE MEASURING? ───────────────────────────────────────────
# `fault_atpg_run._run_docker` gained a LOCAL route: with no `docker` client on
# PATH there is no route to any container, so it runs the engine on this
# filesystem instead of returning 127 for every ATPG call (measured in-image:
# `scan_chain.json` recorded `"exit": 127, "docker binary not found in PATH"`
# and Step 11 disclosed-skipped). Inside the EDA image — where this suite runs —
# that means the DEFAULT route is now local, and a test that asserts a docker
# argv without saying so is measuring WHICH HOST IT IS ON, not the property it
# names. Each test below now drives the route it means to measure.
def _force_container_route(monkeypatch):
    import shutil as _sh
    _real = _sh.which
    monkeypatch.setattr(F._CE.shutil, "which",
                        lambda n, *a, **k: ("/usr/bin/docker" if n == "docker"
                                            else _real(n, *a, **k)))


def _force_local_route(monkeypatch):
    import shutil as _sh
    _real = _sh.which
    monkeypatch.setattr(F._CE.shutil, "which",
                        lambda n, *a, **k: (None if n == "docker"
                                            else _real(n, *a, **k)))
    monkeypatch.setattr(F, "_LOCAL_ATPG_ROUTE_ANNOUNCED", True, raising=False)


def test_a_missing_docker_still_says_so(monkeypatch, tmp_path):
    """A client that IS on PATH and then vanishes is still reported."""
    _force_container_route(monkeypatch)

    def boom(*_a, **_k):
        raise FileNotFoundError()
    monkeypatch.setattr(F.subprocess, "run", boom)
    rc, _o, err = F._run_docker(tmp_path, ["x"], timeout=5)
    assert rc == 127 and "docker binary not found" in err


def test_no_client_at_all_runs_locally_and_says_which_route(monkeypatch,
                                                            tmp_path):
    """The OTHER half of the same question. With no client there is nothing to
    report as missing — there is a route to take — so the honest outcome is a
    local run, and 127 then means the TOOL is absent, not the container."""
    _force_local_route(monkeypatch)
    rec = _Rec()
    monkeypatch.setattr(F.subprocess, "run", rec)
    F._run_docker(tmp_path, ["x"], timeout=5)
    assert rec.argv[0] == "bash" and "docker" not in rec.argv, rec.argv


# ── the ordinary paths are unchanged ────────────────────────────────────────
def test_a_successful_run_is_passed_through(monkeypatch, tmp_path):
    rc, out, err = _drive(monkeypatch, tmp_path,
                          _Rec(rc=0, out="coverage 91.7", err=""), timeout=30)
    assert (rc, out, err) == (0, "coverage 91.7", "")


def test_an_expired_container_deadline_arrives_as_an_ordinary_rc(
        monkeypatch, tmp_path):
    """coreutils `timeout` returns 124, so expiry is a return code existing
    `returncode != 0` handling already routes — not an exception thrown past
    callers that never expected one."""
    rc, _o, _e = _drive(monkeypatch, tmp_path, _Rec(rc=124), timeout=30)
    assert rc == 124


def test_the_pdk_mount_is_still_wired(monkeypatch, tmp_path):
    """CONTAINER route: the PDK is reached by a bind mount."""
    _force_container_route(monkeypatch)
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    rec = _Rec()
    monkeypatch.setattr(F.subprocess, "run", rec)
    F._run_docker(tmp_path, ["x"], timeout=5, pdk_dir=pdk)
    assert f"{pdk}:/pdk" in rec.argv


def test_the_pdk_is_reached_without_a_mount_on_the_local_route(monkeypatch,
                                                               tmp_path):
    """LOCAL route: there is no mount to wire, so the SAME files must be
    reached by rewriting `/pdk` to where they actually are. Mounting and
    rewriting are the two shapes of one requirement — the engine sees the
    PDK — and this is the half the mount test cannot cover."""
    _force_local_route(monkeypatch)
    pdk = tmp_path / "foundry_kit"
    pdk.mkdir()
    rec = _Rec()
    monkeypatch.setattr(F.subprocess, "run", rec)
    F._run_docker(tmp_path, ["x", "--lib", "/pdk/cells.lib"], timeout=5,
                  pdk_dir=pdk)
    shell = rec.argv[-1]
    assert f"{pdk}/cells.lib" in shell, shell
    assert " /pdk/" not in shell, shell


def test_an_image_without_timeout_degrades_loudly(monkeypatch, tmp_path):
    """127 from the shell is `command not found`. The caller learns the
    deadline could NOT be enforced instead of running unbounded behind a
    deadline that exists only in its belief."""
    rc, _o, _e = _drive(monkeypatch, tmp_path,
                        _Rec(rc=CE.TIMEOUT_UNAVAILABLE_RC), timeout=30)
    assert rc == CE.TIMEOUT_UNAVAILABLE_RC
