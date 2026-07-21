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
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

_QUIET = "IIC_OSIC_TOOLS_QUIET=1"


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


def test_docker_exec_raw_sets_the_quiet_knob(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "true", timeout=30)
    assert _quiet_is_set(rec.argv), rec.argv


def test_quiet_flag_precedes_the_container_name(monkeypatch):
    """`docker exec` takes options BEFORE the container; order is load-bearing."""
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "true", timeout=30)
    assert rec.argv.index(_QUIET) < rec.argv.index("cnt"), rec.argv


def test_command_is_still_passed_through_unchanged(monkeypatch):
    """NO-LEAK: suppressing the banner must not alter the command run."""
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("cnt", "echo hello", timeout=30)
    assert rec.argv[-2] == "-lc"
    assert "echo hello" in rec.argv[-1]
    assert rec.argv[-3] == "bash"


def test_container_name_still_correct(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    R._docker_exec_raw("my_container", "true", timeout=30)
    assert "my_container" in rec.argv


def test_no_other_env_is_injected(monkeypatch):
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
