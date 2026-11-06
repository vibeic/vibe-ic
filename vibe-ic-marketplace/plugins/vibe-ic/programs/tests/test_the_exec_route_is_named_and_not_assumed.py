"""The Phase-3 runner must reach its tools when there is no docker client.

WHAT THIS FILE PINS, AND WHY IT EXISTS.  Every Phase-3 step reaches its tool
through `docker exec <$EDA_CONTAINER> bash -lc ...` into a container the runner
never starts.  That is correct beside the image and unreachable INSIDE it:
there is no `docker` binary in there.  MEASURED 2026-09-06, subservient through
the canonical front door (`vibe_ic_one_shot_runner.py --pdk gf180mcuD`) inside
ghcr.io/vibeic/vibeic-eda 0.3.46 — phase1 PASS, phase2 PASS_WITH_WAIVERS, and
Phase 3 died at its first act:

    FAIL synth rc=127 COMMAND_NOT_FOUND: [Errno 2] ... 'docker'

with `yosys` at /foss/tools/bin/yosys in that same process.  Every other
Phase-3 FAIL/BLOCKED in that run descended from it.

THE MUTATIONS EACH TEST IS REQUIRED TO KILL, named here because a control that
cannot fail is not a control:

  * Deleting the LOCAL branch of `_exec_argv` (back to the unconditional
    ["docker", "exec", ...]) must fail `test_local_route_when_no_docker_client`
    and `test_a_command_actually_runs_without_a_docker_client`.
  * Deleting the CONTAINER branch — i.e. always running locally — must fail
    `test_container_route_is_byte_identical_when_docker_exists`, which is the
    guarantee that no host beside a container changes behaviour.
  * Restoring the FIRST, WRONG predicate `not os.environ.get("EDA_CONTAINER")
    and shutil.which("docker") is None` must fail
    `test_a_default_container_name_is_not_an_operator_choice`.  That predicate
    was measured DEAD before it shipped: `phase3_one_shot_runner`'s own
    `--container` defaults to "vibeic-eda" and `main()` exports it
    unconditionally, so `$EDA_CONTAINER` is always set by the time a step runs.
  * Making the local route silent (dropping the stderr announcement or the
    `exec_route` ledger field) must fail `test_the_route_is_announced` and
    `test_the_ledger_records_which_route_ran`.
"""

import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

P3 = importlib.import_module("phase3_one_shot_runner")


import _container_exec as _CEX
import _eda_pin as _PIN


@pytest.fixture
def route(monkeypatch):
    """Drive the ONE predicate, both ways, with the cache reset each time.

    AND STAGE WHAT THE NAMED CONTAINER HOLDS (vibe-ic#2100).  `_exec_argv`'s
    container branch builds its argv through `_container_exec.docker_exec_argv`,
    which asks `_eda_pin.container_attach_refusal` whether the container running
    under that NAME holds the pinned bytes, and RAISES `ContainerImageMismatch`
    when it provably does not.  That question is answered by the real docker
    daemon on the machine the test happens to run on.

    MEASURED 2026-09-07 on 8HD-4, both env arms, on pristine main: a container
    literally named `vibeic-eda` — another lane's, holding
    `sha256:06537f7e…` (0.3.46) — was running on the host, so
    `test_container_route_is_byte_identical_when_docker_exists` raised
    CONTAINER_IMAGE_MISMATCH instead of comparing an argv.  The test was
    reporting a fact about `docker ps`, and it would equally have reported
    green-for-the-wrong-reason on a host where nothing was called that.

    `pin_state` therefore STATES what the container holds, by default MATCH —
    "this run's container is the pinned one" — which is the premise every argv
    assertion in this file already relies on and none of them used to say.
    Passing MISMATCH drives the other direction; the guard's own contract is
    pinned by `test_the_container_route_refuses_a_container_holding_other_bytes`
    below, so staging MATCH here removes no coverage.
    """
    def _set(docker_path, eda_container, pin_state=("MATCH", "")):
        monkeypatch.setattr(P3, "_LOCAL_EXEC_MODE", None, raising=False)
        real_which = shutil.which
        monkeypatch.setattr(
            P3.shutil, "which",
            lambda n, *a, **k: (docker_path if n == "docker"
                                else real_which(n, *a, **k)))
        if eda_container is None:
            monkeypatch.delenv("EDA_CONTAINER", raising=False)
        else:
            monkeypatch.setenv("EDA_CONTAINER", eda_container)
    yield _set
    P3._LOCAL_EXEC_MODE = None


def test_local_route_when_no_docker_client(route):
    route(docker_path=None, eda_container=None)
    assert P3._exec_argv("vibeic-eda", "true") == ["bash", "-lc", "true"]
    assert P3._local_exec_mode() is True


def test_container_route_is_byte_identical_when_docker_exists(route):
    """THE HOST-SIDE CONTROL.  A machine with a docker client must assemble
    exactly the argv it always did, `-e IIC_OSIC_TOOLS_QUIET=1` included."""
    route(docker_path="/usr/bin/docker", eda_container=None)
    assert P3._exec_argv("vibeic-eda", "true") == [
        "docker", "exec", "-e", "IIC_OSIC_TOOLS_QUIET=1",
        "vibeic-eda", "bash", "-lc", "true"]
    assert P3._local_exec_mode() is False
    # and with an operator-named container, still the container route
    route(docker_path="/usr/bin/docker", eda_container="some_other_name")
    assert P3._exec_argv("some_other_name", "true")[:2] == ["docker", "exec"]




def test_an_unreadable_container_digest_is_not_a_refusal(route):
    """"I could not read it" is not "I read it and it was wrong"."""
    route(docker_path="/usr/bin/docker", eda_container=None,
          pin_state=("UNREADABLE", "CONTAINER_ABSENT: vibeic-eda"))
    assert P3._exec_argv("vibeic-eda", "true")[:2] == ["docker", "exec"]


def test_a_default_container_name_is_not_an_operator_choice(route):
    """`$EDA_CONTAINER` set + no docker client  ->  STILL the local route.

    The runner exports its own `--container` DEFAULT into the environment, so
    a predicate that reads "nobody named a container" reads a value the runner
    wrote to itself.  With no client there is no route to that container and
    no second toolchain to choose between."""
    route(docker_path=None, eda_container="vibeic-eda")
    assert P3._local_exec_mode() is True
    assert P3._exec_argv("vibeic-eda", "true") == ["bash", "-lc", "true"]


def test_the_route_is_announced(route, capsys):
    """DEGRADE LOUDLY: a transcript must say which route the run took."""
    route(docker_path=None, eda_container="vibeic-eda")
    assert P3._local_exec_mode() is True
    err = capsys.readouterr().err
    assert "EXEC ROUTE = LOCAL" in err
    assert "vibeic-eda" in err          # names the container it did NOT enter
    # announced ONCE, not per call
    P3._local_exec_mode()
    assert capsys.readouterr().err == ""


def test_the_container_route_announces_nothing(route, capsys):
    route(docker_path="/usr/bin/docker", eda_container=None)
    assert P3._local_exec_mode() is False
    assert "EXEC ROUTE" not in capsys.readouterr().err


@pytest.fixture
def launched(monkeypatch):
    """Record the argv `_docker_exec_raw` actually launched, and still launch it.

    vibe-ic#2100.  The two end-to-end tests below used to assert only on the
    OUTPUT, and an output does not say where it came from.  MEASURED on this
    branch while driving the M1 mutation arm (delete the LOCAL branch of
    `_exec_argv`) on 8HD-4: both stayed GREEN.  With the branch gone the seam
    built a container argv, `subprocess.run` reached the real Docker CLI —
    `shutil.which` is substituted but `execvp` is not — and a container
    genuinely named `vibeic-eda` on that host echoed the string back.  The
    tests passed while the tool had run in exactly the place they exist to
    prove it does not.

    So the argv is recorded and asserted, and the command is still really run:
    "it produced the right output" and "it ran where we said" are two claims
    and this file needs both.
    """
    seen = []
    real_run = P3.subprocess.run

    def _record(argv, *a, **k):
        seen.append(list(argv))
        return real_run(argv, *a, **k)

    monkeypatch.setattr(P3.subprocess, "run", _record)
    return seen


def test_a_command_actually_runs_without_a_docker_client(route, launched):
    """End to end through `_docker_exec_raw`: with no client, a command that
    exists on THIS filesystem runs and returns its own output — and it ran
    HERE, not in a container that happened to be reachable."""
    route(docker_path=None, eda_container="vibeic-eda")
    rc, out, err = P3._docker_exec_raw("vibeic-eda",
                                       "echo THE_TOOL_RAN", timeout=60)
    assert rc == 0, (rc, out, err)
    assert "THE_TOOL_RAN" in out
    assert launched and launched[-1][:2] == ["bash", "-lc"], launched


def test_a_missing_tool_names_the_tool_and_the_route(route, launched):
    """127 must not be ambiguous between 'no container' and 'no tool'."""
    route(docker_path=None, eda_container="vibeic-eda")
    rc, _out, err = P3._docker_exec_raw(
        "vibeic-eda", "czsubdock_no_such_tool_anywhere --version", timeout=60)
    assert rc == 127, rc
    assert "czsubdock_no_such_tool_anywhere" in err
    assert "LOCAL_EXEC" in err
    assert "vibeic-eda" in err
    assert launched and launched[-1][:2] == ["bash", "-lc"], launched


def test_annotation_is_a_no_op_on_the_container_route(route):
    route(docker_path="/usr/bin/docker", eda_container=None)
    assert P3._annotate_local_exec(127, "boom") == "boom"


def test_annotation_is_a_no_op_for_every_other_rc(route):
    route(docker_path=None, eda_container=None)
    assert P3._annotate_local_exec(0, "") == ""
    assert P3._annotate_local_exec(1, "real failure") == "real failure"


def test_the_ledger_records_which_route_ran(route, tmp_path, monkeypatch):
    """A provenance row that names a container the run never entered is a
    false record.  `exec_route` must be present and must say `local`."""
    import json
    route(docker_path=None, eda_container="vibeic-eda")
    monkeypatch.setattr(P3, "_PROV_SINK", str(tmp_path), raising=False)
    P3._log_invocation("yosys -V", 0, 12, marker=None, container="vibeic-eda")
    rows = [json.loads(l) for l in
            (tmp_path / "provenance.jsonl").read_text().splitlines() if l]
    inv = [r for r in rows if r.get("record") == "invocation"]
    assert inv, rows
    assert inv[-1]["exec_route"] == "local"


def test_the_ledger_says_container_when_a_container_ran(route, tmp_path,
                                                        monkeypatch):
    import json
    route(docker_path="/usr/bin/docker", eda_container="vibeic-eda")
    monkeypatch.setattr(P3, "_PROV_SINK", str(tmp_path), raising=False)
    P3._log_invocation("yosys -V", 0, 12, marker=None, container="vibeic-eda")
    rows = [json.loads(l) for l in
            (tmp_path / "provenance.jsonl").read_text().splitlines() if l]
    inv = [r for r in rows if r.get("record") == "invocation"]
    assert inv and inv[-1]["exec_route"] == "container"


def test_both_exec_entry_points_share_one_seam(route, monkeypatch):
    """`_docker_exec_raw` and the supervised branch of `_docker_exec` must take
    their ROUTE from the one predicate, or they will disagree about where a
    tool runs the first time one of them is edited.

    THE MECHANISM MOVED AND THE PROPERTY DID NOT (vibe-ic#2100).  This test
    used to read the source text and require the literal
    `full = _exec_argv(container, _wrapped)` to appear EXACTLY TWICE — correct
    while both entry points assembled their own argv here.  v1.18.28 removed
    the private supervised dispatch from this file: the supervised branch now
    calls `_docker_watchdog.run_docker_supervised`, hands it
    `docker_exec_raw=_docker_exec_raw` for the probes, and passes the ROUTE it
    decided as the container argument (`"" if _local_exec_mode() else
    container` — `""` is that module's documented NATIVE mode).  So the string
    appears ONCE and the file was red on every host, in both env arms, saying
    `assert 1 == 2` about a delegation that had made the seam narrower rather
    than wider.

    A count of a source literal is a claim about MECHANISM.  What both entry
    points are actually required to share is the ROUTE DECISION, so that is
    what is driven here — both of them, both ways — instead of counted.
    """
    seen = {}

    def _fake_supervised(container, cmd, marker, **kw):
        seen["container"] = container
        seen["docker_exec_raw"] = kw.get("docker_exec_raw")
        return 0, "", ""

    monkeypatch.setattr(P3._dwd, "run_docker_supervised", _fake_supervised)

    # LOCAL: the raw entry point emits the local argv, and the supervised
    # branch hands the watchdog its native mode rather than a container name.
    route(docker_path=None, eda_container="vibeic-eda")
    assert P3._exec_argv("vibeic-eda", "true") == ["bash", "-lc", "true"]
    P3._docker_exec("vibeic-eda", "true", marker="m")
    assert seen["container"] == "", seen
    assert seen["docker_exec_raw"] is P3._docker_exec_raw, (
        "the supervised branch must probe through THIS file's raw exec, or the "
        "two can disagree about where a probe runs")

    # CONTAINER: both name the same container.
    seen.clear()
    route(docker_path="/usr/bin/docker", eda_container=None)
    assert P3._exec_argv("vibeic-eda", "true")[:2] == ["docker", "exec"]
    P3._docker_exec("vibeic-eda", "true", marker="m")
    assert seen["container"] == "vibeic-eda", seen


def test_the_seam_builds_no_docker_exec_argv_of_its_own():
    """Exactly one place in the repo spells a `docker exec` argv.

    Unchanged in substance from what this file has always asserted, and split
    out from the route property above because it is a fact about the SOURCE and
    that one is a fact about a RUN.  A second copy of the argv is how the two
    entry points came to disagree about `-e IIC_OSIC_TOOLS_QUIET=1` before the
    seam existed; the constructor also carries the attach check that keeps a run
    from addressing a container holding other bytes, so building the argv by
    hand here would bypass a guard as well as duplicate a shape.
    """
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    body = src.split("def _exec_argv(")[1].split("\ndef ")[0]
    assert body.count('"docker", "exec",') == 0, (
        "the seam spells a `docker exec` argv itself again; it must build it "
        "through _container_exec.docker_exec_argv")
    assert "docker_exec_argv(" in body, (
        "the seam must build its container argv through the ONE guarded "
        "constructor, not by hand")
