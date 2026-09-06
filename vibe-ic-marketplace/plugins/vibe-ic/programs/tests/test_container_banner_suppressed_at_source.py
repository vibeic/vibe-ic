"""The container login banner leaks onto STDOUT of every probe.

The vibeic-eda image is entered through a LOGIN shell (`docker exec … bash -lc`)
and its profile prints two lines to STDOUT ahead of the command output:

    [INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin:...
    [INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12/...

Issue #211 hardened `_registry_glob_one` against this (a candidate is accepted
only when it sits under the PDK root AND exists), which fixed the PDK-resolver
consumer. But the banner is still emitted, so every OTHER stdout consumer is
still exposed. One is still live on origin/main — the post-route SPEF-repair
capability probe reads an env var with

    rc, out, _ = _docker_exec_raw(container,
        'printf %s "${VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR:-}"')
    if rc == 0 and out.strip().lower() in ("1", "true", "yes", "on"):

With the banner prepended, `out.strip()` is the two banner lines plus the
value, so the comparison can NEVER be true and the operator's explicit opt-in
is silently ignored. Measured live against the real container:

    docker exec -e VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR=1 <c> bash -lc \
        'printf %s "${VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR:-}"'
      -> '[INFO] Final PATH variable: ...'      opt-in honoured: False

    ...same, plus -e IIC_OSIC_TOOLS_QUIET=1
      -> '1'                                     opt-in honoured: True

Fix: pass the image's OWN documented quiet knob on every `docker exec`. The
image guards both echoes on it directly
(/etc/profile.d/iic-osic-tools-setup.sh:102-103):

    [ -z "${IIC_OSIC_TOOLS_QUIET}" ] && echo "[INFO] Final PATH variable: $PATH"
    [ -z "${IIC_OSIC_TOOLS_QUIET}" ] && echo "[INFO] Final PYTHONPATH variable: ..."

Suppressing at SOURCE is strictly better than filtering at each consumer,
because it needs no consumer to remember to filter.

chip-AGNOSTIC: pure container I/O hygiene; setting the variable changes no
tool behaviour, only whether the profile echoes.

WHY THESE TESTS NOW PIN THE ROUTE EXPLICITLY.  Four of them used to read the
argv `_docker_exec_raw` builds and assert it starts `["docker", "exec"]`.  That
was true unconditionally until `phase3_one_shot_runner` learned a LOCAL exec
route (`_local_exec_mode`): with no `docker` client on PATH — which is exactly
the case when this suite runs INSIDE the vibeic-eda image — the argv is
`["bash", "-lc", …]` and there is no `-e` flag to find.  The tests were then
measuring "which route is this machine on", not "is the knob set".

So each one now DRIVES the route it means to measure, and the same property is
pinned on the OTHER route as well (`TestQuietKnobOnTheLocalRoute`): on the
container route the knob is a `docker exec -e` flag, on the local route it is
the process ENVIRONMENT the login shell inherits — which is where it has to be,
because `bash -l` sources the profile before the command runs.  Suppressing at
SOURCE is the invariant; the argv was only ever one of its two shapes.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

_QUIET = "IIC_OSIC_TOOLS_QUIET=1"


@pytest.fixture
def container_route(monkeypatch):
    """Force the CONTAINER exec route, whatever this machine has.

    Without this the suite measures the host it happens to run on: inside the
    EDA image there is no `docker` client, so `_exec_argv` returns the local
    argv and every assertion about `-e` below is asking the wrong question."""
    import shutil as _sh
    _real = _sh.which
    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", None, raising=False)
    monkeypatch.setattr(
        R.shutil, "which",
        lambda n, *a, **k: ("/usr/bin/docker" if n == "docker"
                            else _real(n, *a, **k)))
    yield
    R._LOCAL_EXEC_MODE = None


@pytest.fixture
def local_route(monkeypatch):
    """Force the LOCAL exec route (no docker client anywhere)."""
    import shutil as _sh
    _real = _sh.which
    monkeypatch.setattr(R, "_LOCAL_EXEC_MODE", None, raising=False)
    monkeypatch.setattr(
        R.shutil, "which",
        lambda n, *a, **k: (None if n == "docker" else _real(n, *a, **k)))
    yield
    R._LOCAL_EXEC_MODE = None



class _Recorder:
    """Capture the argv `subprocess.run` is handed, and answer plausibly."""

    def __init__(self, stdout=""):
        self.argv = None
        self._stdout = stdout

    def __call__(self, argv, **kw):
        self.argv = argv
        return subprocess.CompletedProcess(argv, 0, self._stdout, "")


def _quiet_is_set(argv):
    """True iff `-e IIC_OSIC_TOOLS_QUIET=1` precedes the container name."""
    assert argv[:2] == ["docker", "exec"], argv
    try:
        i = argv.index("-e")
    except ValueError:
        return False
    return argv[i + 1] == _QUIET


def test_docker_exec_raw_sets_the_quiet_knob(monkeypatch, container_route):
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "true", timeout=30)
    assert _quiet_is_set(rec.argv), rec.argv


def test_quiet_flag_precedes_the_container_name(monkeypatch, container_route):
    """`docker exec` takes options BEFORE the container; order is load-bearing."""
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "true", timeout=30)
    assert rec.argv.index(_QUIET) < rec.argv.index("cnt"), rec.argv


def test_command_is_still_passed_through_unchanged(monkeypatch, container_route):
    """NO-LEAK: suppressing the banner must not alter the command run."""
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "echo hello", timeout=30)
    assert rec.argv[-2] == "-lc"
    assert "echo hello" in rec.argv[-1]
    assert rec.argv[-3] == "bash"


def test_container_name_still_correct(monkeypatch, container_route):
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("my_container", "true", timeout=30)
    assert "my_container" in rec.argv


def test_no_other_env_is_injected(monkeypatch, container_route):
    """Exactly ONE -e is added; we do not smuggle in other variables."""
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "true", timeout=30)
    assert rec.argv.count("-e") == 1, rec.argv


def test_env_opt_in_probe_is_readable_once_the_banner_is_gone(monkeypatch):
    """The still-live consumer this fix is for.

    With a clean stdout the probe's own comparison succeeds; with the banner
    prepended it cannot. This pins the CONSUMER's contract, so a regression
    that reintroduced the banner would be caught here and not only in the
    argv-shape tests above.
    """
    banner = ("[INFO] Final PATH variable: /usr/bin\n"
              "[INFO] Final PYTHONPATH variable: /usr/lib/python3.12\n")

    def _probe_says_enabled(stdout):
        return stdout.strip().lower() in ("1", "true", "yes", "on")

    assert _probe_says_enabled("1") is True
    assert _probe_says_enabled(banner + "1") is False


class TestQuietKnobOnTheLocalRoute:
    """The SAME invariant, on the route that has no `-e` to carry it.

    `docker exec -e IIC_OSIC_TOOLS_QUIET=1` puts the knob in the child's
    environment. Running locally, the child inherits THIS process's
    environment, so the knob has to be there instead — and it has to be there
    BEFORE `bash -l` sources /etc/profile.d/iic-osic-tools-setup.sh, which is
    what prints the banner. If this class goes red, the banner is back on
    every in-image probe's stdout and #211's whole class of defect is live
    again on a route that did not exist when it was written.
    """

    def test_the_knob_is_in_the_environment(self, monkeypatch, local_route):
        monkeypatch.delenv("IIC_OSIC_TOOLS_QUIET", raising=False)
        assert R._exec_argv("cnt", "true") == ["bash", "-lc", "true"]
        assert os.environ.get("IIC_OSIC_TOOLS_QUIET") == "1"

    def test_an_operator_value_is_not_overwritten(self, monkeypatch,
                                                  local_route):
        monkeypatch.setenv("IIC_OSIC_TOOLS_QUIET", "0")
        R._exec_argv("cnt", "true")
        assert os.environ.get("IIC_OSIC_TOOLS_QUIET") == "0"

    def test_the_command_survives_the_local_route_unchanged(self, monkeypatch,
                                                            local_route):
        argv = R._exec_argv("cnt", "echo hello")
        assert argv[-2] == "-lc" and "echo hello" in argv[-1]
        assert argv[0] == "bash"

    def test_a_real_probe_reads_a_clean_stdout_locally(self, monkeypatch,
                                                       local_route):
        """END TO END, and it took a correction to make it one.

        The profile block that prints the banner is wrapped in
        `if [ -z "$FOSS_INIT_DONE" ] … export FOSS_INIT_DONE=1`, so a NESTED
        login shell skips it whatever `IIC_OSIC_TOOLS_QUIET` says. This suite
        normally runs as a child of a login shell, so without the delenv below
        the probe's stdout is clean for a reason that has nothing to do with
        the knob — MEASURED: with the `setdefault` mutated away this test
        still passed, i.e. it was not guarding what its name claims.

        Clearing FOSS_INIT_DONE puts the child in the state the block actually
        runs in, which is also the real state whenever the runner is started
        without a login shell in front of it. Then the knob is the only thing
        standing between the consumer and two lines of banner.
        """
        monkeypatch.delenv("FOSS_INIT_DONE", raising=False)
        rc, out, _err = R._docker_exec_raw(
            "cnt", 'printf %s "CZSUBDOCK_CLEAN"', timeout=60)
        assert rc == 0, (rc, out)
        assert out.strip() == "CZSUBDOCK_CLEAN", repr(out)

    def test_the_banner_really_is_there_to_suppress(self, monkeypatch,
                                                    local_route):
        """POSITIVE CONTROL for the test above: with the knob explicitly OFF
        and FOSS_INIT_DONE cleared, the banner DOES land on stdout. Without
        this, a clean stdout could mean 'suppressed' or 'never emitted here',
        and those are not the same measurement."""
        monkeypatch.delenv("FOSS_INIT_DONE", raising=False)
        monkeypatch.delenv("IIC_OSIC_TOOLS_QUIET", raising=False)
        cmd = 'printf %s "CZSUBDOCK_CLEAN"'
        argv = ["bash", "-lc", cmd]
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        if "[INFO] Final PATH variable:" not in cp.stdout:
            pytest.skip("this shell emits no startup banner — nothing for the "
                        "knob to suppress here, so the test above is "
                        "NOT_MEASURED rather than passing")
        assert cp.stdout.strip() != "CZSUBDOCK_CLEAN"
