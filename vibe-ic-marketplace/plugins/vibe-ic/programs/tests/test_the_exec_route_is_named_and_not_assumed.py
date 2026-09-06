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


@pytest.fixture
def route(monkeypatch):
    """Drive the ONE predicate, both ways, with the cache reset each time."""
    def _set(docker_path, eda_container):
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


def test_a_command_actually_runs_without_a_docker_client(route):
    """End to end through `_docker_exec_raw`: with no client, a command that
    exists on THIS filesystem runs and returns its own output."""
    route(docker_path=None, eda_container="vibeic-eda")
    rc, out, err = P3._docker_exec_raw("vibeic-eda",
                                       "echo THE_TOOL_RAN", timeout=60)
    assert rc == 0, (rc, out, err)
    assert "THE_TOOL_RAN" in out


def test_a_missing_tool_names_the_tool_and_the_route(route):
    """127 must not be ambiguous between 'no container' and 'no tool'."""
    route(docker_path=None, eda_container="vibeic-eda")
    rc, _out, err = P3._docker_exec_raw(
        "vibeic-eda", "czsubdock_no_such_tool_anywhere --version", timeout=60)
    assert rc == 127, rc
    assert "czsubdock_no_such_tool_anywhere" in err
    assert "LOCAL_EXEC" in err
    assert "vibeic-eda" in err


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


def test_both_exec_entry_points_share_one_seam():
    """`_docker_exec_raw` and the supervised branch of `_docker_exec` must
    both go through `_exec_argv`, or they will disagree about where a tool
    runs the first time one of them is edited."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert src.count("full = _exec_argv(container, _wrapped)") == 2, (
        "both exec entry points must build their argv through the one seam")
    # Neither of them may rebuild the argv itself: a second copy is how the
    # two came to disagree about `-e IIC_OSIC_TOOLS_QUIET=1` before the seam
    # existed. The ONE literal `docker exec` argv in a *tool-running* path is
    # inside `_exec_argv`; the remaining ones are short helpers that read a
    # file or a mount table, not the two supervised entry points.
    body = src.split("def _exec_argv(")[1].split("\ndef ")[0]
    assert body.count('"docker", "exec",') == 1
