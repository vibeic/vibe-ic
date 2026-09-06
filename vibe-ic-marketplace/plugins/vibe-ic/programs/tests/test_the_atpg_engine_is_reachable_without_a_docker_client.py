"""The ATPG engine must be reachable when there is no docker client either.

WHY THIS FILE EXISTS.  `phase3_one_shot_runner` learned a LOCAL exec route, and
the in-image run then reached PnR — but Step 11 still recorded, in its own
`reports/phase2/dft/scan_chain.json`:

    "exit": 127,
    "log_tail": "\\ndocker binary not found in PATH",
    "error": "`fault chain` produced no scan netlist"

because `fault_atpg_run._run_docker` enters a container the OTHER way: `docker
run` of a fresh sibling container rather than `docker exec` into a named one.
MEASURED consequence: the in-image run routed the PRE-SCAN netlist while the
same tree run host-side routed the SCAN netlist, so the two disagreed about
which Phase-3 steps even opened (22 names vs 25).

THE IMAGE IT STARTS IS THE IMAGE IT IS ALREADY IN.
`docker image inspect ghcr.io/vibeic/vibeic-eda@sha256:06537f7e… --format
'{{.Id}}'` is `sha256:891063f1473b9c0ae8b0b6dfc442511df059a78e75972928e454181d588dc9be`
— exactly the digest a host-side run records as this tool's provenance. So the
local route runs the SAME build; it is not a substitution.

MUTATIONS THESE TESTS MUST KILL:
  * Deleting the local branch of `_run_docker` fails
    `test_the_local_route_is_taken_when_there_is_no_client`.
  * Deleting the CONTAINER branch fails
    `test_the_container_route_is_byte_identical_when_a_client_exists`.
  * Dropping `_localise_mounted_paths` (running the /work-absolute command as
    written) fails `test_the_mounted_paths_are_rewritten_to_this_filesystem`.
  * Widening the mount-prefix match to a bare `str.replace` fails
    `test_a_token_that_merely_contains_the_mount_name_is_untouched`.
  * Dropping the deadline on the local route fails
    `test_the_deadline_survives_on_both_routes`.
  * Re-introducing a second copy of the route predicate in either program
    fails `test_one_definition_of_the_route_question`.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _container_exec as CE          # noqa: E402
import fault_atpg_run as F            # noqa: E402


class _Recorder:
    def __init__(self, rc=0, out="", err=""):
        self.argv = None
        self._r = (rc, out, err)

    def __call__(self, argv, **kw):
        self.argv = argv
        rc, out, err = self._r
        return subprocess.CompletedProcess(argv, rc, out, err)


@pytest.fixture
def route(monkeypatch):
    """Drive the ONE predicate, both ways."""
    def _set(docker_path):
        real = CE.shutil.which
        monkeypatch.setattr(
            CE.shutil, "which",
            lambda n, *a, **k: (docker_path if n == "docker"
                                else real(n, *a, **k)))
        monkeypatch.setattr(F, "_LOCAL_ATPG_ROUTE_ANNOUNCED", False,
                            raising=False)
    yield _set
    F._LOCAL_ATPG_ROUTE_ANNOUNCED = False


def test_the_predicate_answers_the_route_question():
    real = CE.shutil.which
    try:
        CE.shutil.which = lambda n, *a, **k: None if n == "docker" else real(n)
        assert CE.no_container_route() is True
        CE.shutil.which = lambda n, *a, **k: "/usr/bin/docker" if n == "docker" else real(n)
        assert CE.no_container_route() is False
    finally:
        CE.shutil.which = real


def test_the_container_route_is_byte_identical_when_a_client_exists(
        route, monkeypatch, tmp_path):
    """THE HOST-SIDE CONTROL."""
    route("/usr/bin/docker")
    rec = _Recorder()
    monkeypatch.setattr(F.subprocess, "run", rec)
    F._run_docker(tmp_path, ["fault", "chain", "/work/net.v"], timeout=60)
    argv = rec.argv
    assert argv[:3] == ["docker", "run", "--rm"], argv
    assert "-v" in argv and f"{tmp_path}:/work" in argv
    assert F.DOCKER_IMAGE in argv
    # the command still speaks the CONTAINER's paths, untouched
    assert "/work/net.v" in argv[-1]
    assert str(tmp_path) not in argv[-1]


def test_the_local_route_is_taken_when_there_is_no_client(
        route, monkeypatch, tmp_path):
    route(None)
    rec = _Recorder()
    monkeypatch.setattr(F.subprocess, "run", rec)
    F._run_docker(tmp_path, ["fault", "chain", "/work/net.v"], timeout=60)
    argv = rec.argv
    assert argv[0] == "bash", argv
    assert "docker" not in argv
    assert F.DOCKER_IMAGE not in argv


def test_the_mounted_paths_are_rewritten_to_this_filesystem(
        route, monkeypatch, tmp_path):
    """A command written against /work must name the REAL files locally."""
    route(None)
    rec = _Recorder()
    monkeypatch.setattr(F.subprocess, "run", rec)
    # deliberately NOT named "pdk": a real rewrite must be visible without the
    # destination happening to spell the mount point back again (the first
    # version of this test asserted `"/pdk/" not in shell` and failed on a
    # CORRECT rewrite into a directory called `pdk`).
    pdk = tmp_path / "foundry_kit"
    pdk.mkdir()
    F._run_docker(tmp_path, ["fault", "chain", "-o", "/work/out/scan.v",
                             "/work/net.v", "--lib", "/pdk/cells.lib"],
                  timeout=60, pdk_dir=pdk)
    shell = rec.argv[-1]
    assert f"{tmp_path}/out/scan.v" in shell, shell
    assert f"{tmp_path}/net.v" in shell, shell
    assert f"{pdk}/cells.lib" in shell, shell
    # no container-absolute argument survives (they all follow a space here)
    assert " /work/" not in shell, shell
    assert " /pdk/" not in shell, shell


def test_a_token_that_merely_contains_the_mount_name_is_untouched():
    """A bare `replace` would corrupt a design called `network`."""
    out = F._localise_mounted_paths(
        "echo network /opt/workspace /workflow /work/real",
        Path("/p/proj"), None)
    assert "network" in out
    assert "/opt/workspace" in out
    assert "/workflow" in out
    assert "/p/proj/real" in out


def test_pdk_is_only_rewritten_when_one_was_mounted():
    out = F._localise_mounted_paths("--lib /pdk/x.lib", Path("/p/proj"), None)
    assert out == "--lib /pdk/x.lib"


def test_the_deadline_survives_on_both_routes(route, monkeypatch, tmp_path):
    """The engine keeps a deadline it is the child of, on either route."""
    seen = {}
    for client, key in (("/usr/bin/docker", "container"), (None, "local")):
        route(client)
        rec = _Recorder()
        monkeypatch.setattr(F.subprocess, "run", rec)
        F._run_docker(tmp_path, ["fault", "chain"], timeout=60)
        seen[key] = rec.argv[-1]
    for key, shell in seen.items():
        assert re.search(r"timeout -k \d+ \d+ bash -c", shell), (key, shell)


def test_the_route_is_announced_once(route, monkeypatch, tmp_path, capsys):
    route(None)
    monkeypatch.setattr(F.subprocess, "run", _Recorder())
    F._run_docker(tmp_path, ["fault", "chain"], timeout=60)
    err = capsys.readouterr().err
    assert "EXEC ROUTE = LOCAL" in err, err
    F._run_docker(tmp_path, ["fault", "chain"], timeout=60)
    assert "EXEC ROUTE = LOCAL" not in capsys.readouterr().err


def test_the_container_route_announces_nothing(route, monkeypatch, tmp_path,
                                               capsys):
    route("/usr/bin/docker")
    monkeypatch.setattr(F.subprocess, "run", _Recorder())
    F._run_docker(tmp_path, ["fault", "chain"], timeout=60)
    assert "EXEC ROUTE" not in capsys.readouterr().err


def test_one_definition_of_the_route_question():
    """Two programs enter a container two different ways; ONE predicate.

    A second copy is how they would come to disagree about which route a run
    took — which is exactly the state this pair of fixes was measured in."""
    for name in ("phase3_one_shot_runner.py", "fault_atpg_run.py"):
        src = (PROGRAMS / name).read_text()
        assert 'which("docker")' not in src, (
            f"{name} defines its own route predicate; the ONE definition is "
            f"_container_exec.no_container_route")
        assert "no_container_route()" in src, name
    assert (PROGRAMS / "_container_exec.py").read_text().count(
        'shutil.which("docker")') == 1


class TestTheRecordSaysWhatActuallyRan:
    """A fix that makes a step RUN must not make its record LIE.

    `scan_chain.json` records the coverage number's provenance as
    `image: DOCKER_IMAGE`. Two things are true on the local route and neither
    was accounted for: no image is started at all, and `DOCKER_IMAGE` is
    resolved by asking a registry that is UNREACHABLE from inside the image —
    MEASURED, in the aborted first RUN C:

        _eda_image: registry unreachable and no local ghcr.io/vibeic/vibeic-eda
        image; falling back to hpretl/iic-osic-tools:latest, which does NOT
        carry the forked tools.

    So the naive fix would have stamped every in-image scan netlist with an
    image that was never run and is the wrong image. I killed that run rather
    than publish its record.

    MUTATIONS THESE MUST KILL:
      * `"image": _fatpg.DOCKER_IMAGE` restored at the consumer fails
        `test_the_consumer_records_the_route_not_a_name`.
      * `atpg_engine_identity` returning `DOCKER_IMAGE` on the local route
        fails `test_the_local_route_records_no_image`.
      * Dropping `image` from the local dict fails
        `test_the_image_key_is_present_on_both_routes`.
    """

    def test_the_local_route_records_no_image(self, route):
        route(None)
        idy = F.atpg_engine_identity()
        assert idy["exec_route"] == "local"
        assert idy["image"] is None, idy
        assert "engine_path" in idy
        assert "no docker client" in idy["image_note"]

    def test_the_container_route_records_the_image(self, route):
        route("/usr/bin/docker")
        idy = F.atpg_engine_identity()
        assert idy["exec_route"] == "container"
        assert idy["image"] == F.DOCKER_IMAGE

    def test_the_image_key_is_present_on_both_routes(self, route):
        """An existing consumer reading `image` must never KeyError."""
        for client in ("/usr/bin/docker", None):
            route(client)
            assert "image" in F.atpg_engine_identity()

    def test_the_consumer_records_the_route_not_a_name(self):
        """The record writer must go through the identity, not the constant."""
        src = (PROGRAMS / "fault_scan_chain_insert.py").read_text()
        assert '"image": _fatpg.DOCKER_IMAGE' not in src
        assert "_fatpg.atpg_engine_identity()" in src

    def test_the_announcement_does_not_name_the_resolved_image(self):
        """In-image `DOCKER_IMAGE` is a registry fallback; printing it puts a
        wrong image in the transcript."""
        # over the PARSED body, not the characters: the comment above the
        # print explains why the constant is not named, and a text search
        # cannot tell an explanation from a use (the same trap as
        # `out.splitlines()[-25:]` surviving in prose elsewhere in this tree).
        import ast
        src = (PROGRAMS / "fault_atpg_run.py").read_text()
        fn = [n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef)
              and n.name == "_announce_local_atpg_route"]
        assert len(fn) == 1
        body = ast.unparse(fn[0])
        assert "DOCKER_IMAGE" not in body, body
