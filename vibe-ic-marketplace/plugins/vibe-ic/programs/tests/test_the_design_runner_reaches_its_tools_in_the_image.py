"""CZD-35 — the THIRD exec surface.

`design_one_shot_runner` reaches its tools through `docker exec` and stages
their inputs and outputs with `docker cp`. Neither exists inside the EDA image,
so a runner ALREADY RUNNING IN that image cannot execute a single tool through
this file: the calls return 127 and every step downstream of them stays shut.
Phase 3 was taught the route first (v1.18.20); this file is the other half of
the same defect.

The route is decided by ONE predicate, `_container_exec.no_container_route()`,
shared with the two surfaces that came before. These tests drive BOTH routes
and require the container route to stay byte-identical, because "it works
in-image now" is worth nothing if it moved the host.

Tool/PDK/chip-AGNOSTIC: nothing here names a tool, a PDK or a design.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]


def _load(name):
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cex():
    m = _load("_container_exec")
    # Tolerant on purpose: on a tree WITHOUT this change the module has no
    # announce-set, and clearing it here would make every test below error on
    # the fixture instead of on the thing it actually measures.
    getattr(m, "_ANNOUNCED", set()).clear()
    return m


def _local(monkeypatch, cex, yes=True):
    """Drive the ROUTE, never assume it: hide/show the docker client."""
    monkeypatch.setattr(cex.shutil, "which",
                        lambda n: None if (yes and n == "docker") else "/usr/bin/" + n)
    getattr(cex, "_ANNOUNCED", set()).clear()


def _code_of(module_name: str, func_name: str) -> str:
    """A function's CODE, with comments AND its docstring removed.

    `ast.unparse` drops comments but KEEPS the docstring, and a docstring that
    explains why a literal must not appear CONTAINS that literal. Without this
    strip the source guards below would match their own explanation."""
    src = (PROGRAMS / module_name).read_text()
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == func_name]
    assert len(fn) == 1, (module_name, func_name, len(fn))
    body = list(fn[0].body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    assert body, "function has no code outside its docstring"
    return "\n".join(ast.unparse(n) for n in body)


# --------------------------------------------------------------------------
# The seam exists and every site goes through it
# --------------------------------------------------------------------------

def test_no_exec_or_cp_site_builds_its_own_docker_argv():
    """RED before this change: 22 literal docker argv sites, 6 exec and 12 cp.

    After it, the ONLY literals left are the two helpers' own container
    branches plus the three daemon queries that have no local meaning, and
    they are named here so a new one cannot be added silently."""
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    owners = {"_docker_cp", "_docker_exec_argv_with_deadline",
              "_container_mounts", "_container_image_id",
              "_run_stage_in_mounted_image"}
    stray = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name in owners:
            continue
        for lst in ast.walk(fn):
            if not isinstance(lst, ast.List) or not lst.elts:
                continue
            first = lst.elts[0]
            if isinstance(first, ast.Constant) and first.value == "docker":
                verb = (lst.elts[1].value
                        if len(lst.elts) > 1 and isinstance(lst.elts[1], ast.Constant)
                        else "?")
                stray.append(f"{fn.name}: docker {verb}")
    assert stray == [], stray


def test_the_route_predicate_is_not_duplicated_here():
    """One question, one definition. A second copy is how two exec surfaces
    come to disagree about which route a run took."""
    code = _code_of("design_one_shot_runner.py", "_local_exec_mode")
    # ONE alias since czimg4 landed: this file already imported
    # `_container_exec as _ce` for the guarded argv builder, so a second alias
    # for the same module was a way for two call sites to look unrelated.
    assert "_ce.local_exec_mode" in code, code
    assert "shutil.which" not in code, code
    assert "EDA_CONTAINER" not in code, code


# --------------------------------------------------------------------------
# Both routes, driven
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs,expect", [
    ({}, ["docker", "exec", "-e", "IIC_OSIC_TOOLS_QUIET=1",
          "C", "bash", "-lc", "T"]),
    ({"workdir": "/w", "quiet": False},
     ["docker", "exec", "-w", "/w", "C", "bash", "-lc", "T"]),
    ({"shell": "sh", "quiet": False, "login": False},
     ["docker", "exec", "C", "sh", "-c", "T"]),
])
def test_the_container_argv_is_byte_identical(monkeypatch, cex, kwargs, expect):
    """The three shapes this file emitted before the change, unchanged."""
    _local(monkeypatch, cex, yes=False)
    assert cex.exec_argv("C", "T", **kwargs) == expect


def test_in_the_image_the_command_runs_here(monkeypatch, cex):
    _local(monkeypatch, cex)
    argv = cex.exec_argv("C", "T")
    assert argv == ["bash", "-lc", "T"], argv
    assert "docker" not in argv


def test_a_workdir_becomes_a_cd_that_can_fail(monkeypatch, cex):
    """`-w` has no docker to interpret it. `&&` so a missing directory FAILS
    the command instead of silently running it somewhere else."""
    _local(monkeypatch, cex)
    argv = cex.exec_argv("C", "yosys", workdir="/a dir")
    assert argv[:2] == ["bash", "-lc"]
    assert argv[2] == "cd '/a dir' && yosys", argv[2]


def test_the_route_is_announced_once(monkeypatch, cex, capsys):
    _local(monkeypatch, cex)
    for _ in range(3):
        cex.local_exec_mode("design")
    err = capsys.readouterr().err
    assert err.count("EXEC ROUTE = LOCAL") == 1, err
    assert "[design]" in err


# --------------------------------------------------------------------------
# The twelve cp sites: a COPY, not a no-op and not a removal
# --------------------------------------------------------------------------

def test_staging_actually_copies_the_file(monkeypatch, cex, tmp_path):
    src = tmp_path / "rtl" / "a.v"
    src.parent.mkdir()
    src.write_text("module a; endmodule\n")
    dst_dir = tmp_path / "stage"
    _local(monkeypatch, cex)
    rc, _o, err = cex.local_copy(str(src), f"C:{dst_dir}/a.v", "C")
    assert rc == 0, err
    assert (dst_dir / "a.v").read_text() == "module a; endmodule\n"
    assert src.is_file(), "the source is the run's own input; never removed"


def test_retrieval_works_in_the_other_direction(monkeypatch, cex, tmp_path):
    """Half of these sites pull a PRODUCED file back out."""
    produced = tmp_path / "c" / "net.v"
    produced.parent.mkdir()
    produced.write_text("netlist\n")
    out = tmp_path / "host" / "net.v"
    _local(monkeypatch, cex)
    rc, _o, err = cex.local_copy(f"C:{produced}", str(out), "C")
    assert rc == 0, err
    assert out.read_text() == "netlist\n"


def test_a_file_already_in_place_is_success_not_an_error(monkeypatch, cex,
                                                        tmp_path):
    """In-image both endpoints can resolve to ONE path — the staging is
    already satisfied. `shutil.copy2` raises SameFileError there, which would
    turn a satisfied precondition into a failed step."""
    f = tmp_path / "a.v"
    f.write_text("x")
    _local(monkeypatch, cex)
    assert cex.local_copy(str(f), f"C:{f}", "C")[0] == 0


def test_only_the_declared_containers_prefix_is_stripped(cex):
    assert cex.strip_container_prefix("C:/p", "C") == "/p"
    assert cex.strip_container_prefix("/a:b/p", "C") == "/a:b/p"
    assert cex.strip_container_prefix("D:/p", "C") == "D:/p"


# --------------------------------------------------------------------------
# The route must not lose what the container route had
# --------------------------------------------------------------------------

def test_a_local_tool_still_gets_its_own_deadline():
    """The orphan this guard prevents is not a container phenomenon: a host
    `subprocess.run` timeout kills the shell and leaves the tool running."""
    d = _load("design_one_shot_runner")
    out = d._docker_exec_argv_with_deadline(["bash", "-lc", "yosys -p x"], 30)
    assert out[:2] == ["bash", "-lc"]
    assert out[2] != "yosys -p x", "the script was not given a deadline"


def test_in_the_image_every_path_is_reachable(monkeypatch, cex):
    """`_container_mounts` asks the daemon; with no client that raises and is
    swallowed into an EMPTY list, so the reachability question answered False
    for a file on the runner's own disk and the caller staged it into a
    container that does not exist."""
    d = _load("design_one_shot_runner")
    monkeypatch.setattr(d._ce, "no_container_route", lambda: True)
    d._CONTAINER_MOUNTS_CACHE.clear()
    assert d._path_in_container("/anywhere/at/all.v", "C") is True
    assert d._container_mounts("C") == []


def test_the_staging_cleanup_never_runs_on_this_filesystem():
    """`rm -rf <staging>` is correct against a container and destructive here.
    A route change must not become a delete."""
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    i = src.index("rm -rf {cont_wd}")
    window = src[max(0, i - 700):i]
    assert "if not _local_exec_mode():" in window, window[-400:]
