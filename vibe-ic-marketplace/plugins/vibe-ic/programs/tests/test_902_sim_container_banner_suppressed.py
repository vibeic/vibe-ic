"""#902 follow-on — the sim path must not carry the container login banner.

#902 moved iverilog/vvp dispatch INTO the pinned container. That made
`design_one_shot_runner._docker_exec_raw` the hot path for SIMULATION, and
that path did not pass the image's own quiet knob.

The vibeic-eda image is entered through a LOGIN shell whose profile prints
two lines to STDOUT ahead of the command output:

    [INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin:...
    [INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12/...

MEASURED end-to-end on a converged cell (spm x sky130A, plugin-under-test vs
origin/main, same pinned image, three runs incl. a base-vs-base control), the
ONLY artefact whose CONTENT the change was responsible for was the sim
transcript:

    phase2/stage1/sim_full_stack/oracle_run/oracle.log
        origin/main : 4 lines, first line `ORACLE_TB_DONE pass=28/28`
        with #902   : 6 lines, first TWO lines the banner

`phase3_one_shot_runner` already passes `-e IIC_OSIC_TOOLS_QUIET=1` on its own
docker execs, and `test_container_banner_suppressed_at_source.py` states the
doctrine: suppress at SOURCE, because that needs no consumer to remember to
filter. This test extends the SAME contract to the sim path.

chip-AGNOSTIC: pure container I/O hygiene. Setting the variable changes no
tool behaviour, only whether the profile echoes.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as dosr  # noqa: E402

_QUIET = "IIC_OSIC_TOOLS_QUIET=1"


class _Recorder:
    """Capture the argv the PROGRAM hands subprocess.run, and answer it."""

    def __init__(self, stdout="OK"):
        self.argv = None
        self._stdout = stdout

    def __call__(self, argv, **kw):
        self.argv = argv
        outer = self

        class _CP:
            returncode = 0
            stdout = outer._stdout
            stderr = ""
        return _CP()


def test_sim_docker_exec_passes_the_images_quiet_knob(monkeypatch):
    """THE #902 FOLLOW-ON ASSERTION. Fails against the program without the
    knob (the banner then reaches the sim transcript), passes with it."""
    rec = _Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    dosr._docker_exec_raw("c_probe", "iverilog -V", timeout=30)

    argv = rec.argv
    assert argv is not None, "the program never invoked subprocess.run"
    # Ask the PROGRAM what it built - do not rebuild the rule here.
    assert "-e" in argv, "no -e passed to docker exec: %r" % (argv,)
    assert _QUIET in argv, (
        "docker exec argv does not carry the image quiet knob %s: %r"
        % (_QUIET, argv))
    # the knob must be an ENV FLAG (before the container), not a stray token
    assert argv[argv.index(_QUIET) - 1] == "-e"
    assert argv.index(_QUIET) < argv.index("c_probe"), (
        "quiet knob must precede the container name: %r" % (argv,))


def test_guard_docker_exec_still_dispatches_unchanged(monkeypatch):
    """PAIRED GUARD - must PASS ON BOTH SIDES, so the assertion above cannot
    be satisfied by breaking dispatch. The command still reaches the named
    container through a login shell, and rc/stdout still pass through."""
    rec = _Recorder(stdout="BANNERLESS")
    monkeypatch.setattr(subprocess, "run", rec)
    rc, out, err = dosr._docker_exec_raw("c_probe", "iverilog -V", timeout=30)

    argv = rec.argv
    assert argv[0] == "docker" and argv[1] == "exec"
    assert "c_probe" in argv
    # login shell preserved (the tools PATH depends on the profile)
    assert argv[-2] == "-lc" and argv[-3] == "bash"
    assert argv[argv.index("c_probe") + 1] == "bash"
    assert "iverilog -V" in argv[-1]
    assert (rc, out, err) == (0, "BANNERLESS", "")
