"""The EDA image is resolved lazily, only on the docker path, never at import.

Several programs resolved the vibeic-eda image identity (through `_eda_pin` /
`_eda_image.resolve` / `p0_tool_frontend_check.default_image`) at IMPORT time,
or eagerly before they knew whether they needed docker. Inside the image (no
docker client) or on any host without docker they then raised
`ImageNotResolvable` although the tool was on PATH and no container was needed:
`import fault_atpg_run` (a module constant), `import
landing_pytest_runtime_preflight` (a module constant), and
`flow_step_output_content_check._rtl_errors` (an eager `default_image()` before
the front end knew whether any tool had to run in docker). Every program that
imports `fault_atpg_run` inherited the first one.

The rule these tests pin, both directions:
  * importing a program resolves nothing and starts no docker;
  * a tool on PATH resolves nothing;
  * a docker-path call resolves AT CALL TIME (a changed answer is followed,
    nothing is remembered);
  * a declared image is used as is;
  * docker needed and nothing resolvable -> the named `ImageNotResolvable`
    refusal, never a guess.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _eda_pin  # noqa: E402

# The programs that resolved at import (directly or through `fault_atpg_run`),
# plus the two whose check resolved eagerly. MEASURED on main 91835f91c inside
# vibeic-eda 0.3.79 with no docker: each of the first eleven raised
# ImageNotResolvable on import.
IMPORTED_WITHOUT_A_RESOLVE = [
    "fault_atpg_run",
    "fault_scan_chain_insert",
    "transition_fault_atpg_run",
    "path_delay_fault_atpg_run",
    "sdd_atpg_run",
    "p0_tool_frontend_check",
    # tools/ci, outside `programs/` (lane rfimg2): `IMAGE = image_reference()`
    # at module level made `import hermetic_candidate_runner` raise
    # ImageNotResolvable with no docker, for every importer of its grammar.
]

#: tools/ci modules the child may import (the repo's CI runner lives there).
TOOLS_CI = PROGRAMS.parents[3] / "tools" / "ci"

# Run in a child with NO docker on PATH, every resolver poisoned, and every
# docker subprocess recorded. The child prints what it saw.
_CHILD = r"""
import json, os, subprocess, sys
sys.path.insert(0, {programs!r})
sys.path.append({tools_ci!r})
seen = []
import _eda_pin, _eda_image
def _poison(name):
    def _f(*a, **k):
        seen.append(name)
        raise _eda_pin.ImageNotResolvable(["poisoned by the import test: " + name])
    return _f
_eda_pin.resolved_image_digest = _poison("_eda_pin.resolved_image_digest")
_eda_image.resolve = _poison("_eda_image.resolve")
_eda_image.judged_image = _poison("_eda_image.judged_image")
_real_popen = subprocess.Popen
class _Rec(_real_popen):
    def __init__(self, args, *a, **k):
        head = args[0] if isinstance(args, (list, tuple)) and args else str(args)
        if os.path.basename(str(head).split()[0] if head else "") == "docker":
            seen.append("docker subprocess: %r" % (args,))
        super().__init__(args, *a, **k)
subprocess.Popen = _Rec
err = None
try:
    __import__({module!r})
except BaseException as exc:
    err = "%s: %s" % (type(exc).__name__, exc)
print("@@" + json.dumps({{"seen": seen, "err": err}}))
"""


def _import_without_docker(module: str, tmp_path: Path) -> dict:
    empty = tmp_path / "no-docker-bin"
    empty.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("VIBEIC_EDA_IMAGE")}
    env["PATH"] = str(empty)            # no docker client can be found
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run(
        [sys.executable, "-c", _CHILD.format(programs=str(PROGRAMS),
                                            tools_ci=str(TOOLS_CI),
                                            module=module)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=300)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("@@")]
    assert lines, f"{module}: child printed no verdict (rc={r.returncode}): {r.stderr[-1500:]}"
    return json.loads(lines[-1][2:])


@pytest.mark.parametrize("module", IMPORTED_WITHOUT_A_RESOLVE)
def test_the_module_imports_with_no_docker_and_resolves_nothing(module, tmp_path):
    got = _import_without_docker(module, tmp_path)
    assert got["err"] is None, f"{module} does not import without docker: {got['err']}"
    assert got["seen"] == [], f"{module} resolved or ran docker at import: {got['seen']}"


# ── the static half: no module-level call into a resolver, anywhere ─────────

_RESOLVER_MODULES = {"_eda_pin": "_docker", "_eda_image": "_run"}


def _resolving_functions() -> dict[str, set[str]]:
    """Per resolver module, the functions that ASK something: call its docker /
    registry runner (`_eda_pin._docker`, `_eda_image._run`), a subprocess, or
    such a function in the other module -- to a fixpoint. Pure ones (e.g.
    `_eda_pin.default_container_name`, which reads an env var) are not in it.
    Derived from the source, so a new resolver is covered without an edit."""
    trees = {m: ast.parse((PROGRAMS / f"{m}.py").read_text(encoding="utf-8"))
             for m in _RESOLVER_MODULES}
    alias_of = {}  # (module, alias) -> other resolver module
    for m, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in _RESOLVER_MODULES:
                        alias_of[(m, a.asname or a.name)] = a.name
    funcs = {m: {n.name: n for n in t.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
             for m, t in trees.items()}
    resolving = {m: set() for m in trees}
    changed = True
    while changed:
        changed = False
        for m, fns in funcs.items():
            for name, fn in fns.items():
                if name in resolving[m]:
                    continue
                for n in ast.walk(fn):
                    if not isinstance(n, ast.Call):
                        continue
                    f = n.func
                    hit = (
                        (isinstance(f, ast.Name) and
                         (f.id == _RESOLVER_MODULES[m] or f.id in resolving[m]))
                        or (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                            and (f.value.id == "subprocess" or
                                 f.attr in resolving.get(alias_of.get((m, f.value.id)), ()))))
                    if hit:
                        resolving[m].add(name)
                        changed = True
                        break
    return resolving


def _module_level_resolver_calls(tree: ast.Module,
                                 resolving: dict[str, set[str]] | None = None
                                 ) -> list[tuple[int, str]]:
    """Calls into a resolving function of `_eda_pin` / `_eda_image`, or into a
    local function that makes one, evaluated when the module is IMPORTED:
    statements at module or class level, default arguments and decorators.
    Function bodies run later, and the `if __name__ == "__main__":` block runs
    only as a script; neither is import-time."""
    resolving = _resolving_functions() if resolving is None else resolving
    aliases: dict[str, str] = {}   # alias -> resolver module
    direct: set[str] = set()       # `from _eda_pin import resolved_image_digest`
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in _RESOLVER_MODULES:
                    aliases[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module in _RESOLVER_MODULES:
            for a in node.names:
                if a.name in resolving[node.module]:
                    direct.add(a.asname or a.name)

    def calls_resolver(node) -> list[tuple[int, str]]:
        hits = []
        for n in ast.walk(node):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                    and f.attr in resolving.get(aliases.get(f.value.id), ()):
                hits.append((n.lineno, f"{f.value.id}.{f.attr}"))
            elif isinstance(f, ast.Name) and (f.id in direct or f.id in local):
                hits.append((n.lineno, f.id))
        return hits

    # Local functions whose body resolves (one level of indirection is the
    # shape every offender had: `X = _resolve_docker_image()`), to a fixpoint.
    functions = {n.name: n for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    local: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, fn in functions.items():
            if name not in local and any(calls_resolver(s) for s in fn.body):
                local.add(name)
                changed = True

    out: list[tuple[int, str]] = []

    def visit(body):
        for st in body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in [*st.decorator_list, *st.args.defaults,
                          *[x for x in st.args.kw_defaults if x]]:
                    out.extend(calls_resolver(d))
            elif isinstance(st, ast.ClassDef):
                for d in st.decorator_list:
                    out.extend(calls_resolver(d))
                visit(st.body)
            else:
                visit_stmt(st)

    def visit_stmt(st):
        # compound statements (if/try/with/for) at import level: their headers
        # run at import and their bodies are visited as import-level bodies
        if isinstance(st, ast.If) and isinstance(st.test, ast.Compare) \
                and isinstance(st.test.left, ast.Name) and st.test.left.id == "__name__":
            return
        if isinstance(st, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("test", "iter", "items"):
                v = getattr(st, field, None)
                if isinstance(v, list):
                    for item in v:
                        out.extend(calls_resolver(item))
                elif v is not None:
                    out.extend(calls_resolver(v))
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(st, field, []) or [])
            for h in getattr(st, "handlers", []) or []:
                visit(h.body)
        else:
            out.extend(calls_resolver(st))

    visit(tree.body)
    return out


def test_no_program_resolves_the_image_at_import():
    resolving = _resolving_functions()
    assert "resolved_image_digest" in resolving["_eda_pin"]
    assert "image_reference" in resolving["_eda_pin"]
    assert "resolve" in resolving["_eda_image"]
    assert "default_container_name" not in resolving["_eda_pin"]
    offenders = []
    for path in sorted(PROGRAMS.glob("*.py")):
        if path.stem in _RESOLVER_MODULES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        offenders += [f"{path.name}:{ln} {what}()"
                      for ln, what in _module_level_resolver_calls(tree, resolving)]
    assert offenders == [], ("import-time image resolves (resolve only on the "
                             "docker path, at call time):\n  " + "\n  ".join(offenders))


def test_the_static_finder_sees_the_shape_that_was_shipped():
    """Calibration of the finder above against the exact shape it replaced,
    and against the lazy shape that replaced it."""
    shipped = ast.parse(
        "import _eda_image as _img\n"
        "def _resolve_docker_image():\n    return _img.resolve()\n"
        "DOCKER_IMAGE = _resolve_docker_image()\n")
    assert [w for _, w in _module_level_resolver_calls(shipped)] == ["_resolve_docker_image"]
    direct = ast.parse("import _eda_pin as _pin\nRUNNER_IMAGE = _pin.image_reference()\n")
    assert [w for _, w in _module_level_resolver_calls(direct)] == ["_pin.image_reference"]
    default_arg = ast.parse("import _eda_pin as _pin\ndef f(i=_pin.image_reference()):\n    return i\n")
    assert _module_level_resolver_calls(default_arg)
    lazy = ast.parse(
        "import _eda_image as _img\n"
        "def docker_image():\n    return _img.resolve()\n"
        "def __getattr__(name):\n"
        "    if name == 'DOCKER_IMAGE':\n        return docker_image()\n"
        "    raise AttributeError(name)\n")
    assert _module_level_resolver_calls(lazy) == []
    pure = ast.parse("import _eda_pin as _pin\nNAME = _pin.default_container_name()\n"
                     "if __name__ == '__main__':\n    _pin.image_reference()\n")
    assert _module_level_resolver_calls(pure) == []


# ── fault_atpg_run: the container route resolves when it runs ───────────────

def test_the_atpg_container_route_resolves_at_call_time(monkeypatch, tmp_path):
    import _container_exec as CE
    import fault_atpg_run as F
    answers = iter(["ghcr.io/example/first@sha256:" + "1" * 64,
                    "ghcr.io/example/second@sha256:" + "2" * 64])
    monkeypatch.setattr(F._img, "resolve", lambda *a, **k: next(answers))
    monkeypatch.setattr(CE.shutil, "which",
                        lambda n, *a, **k: "/usr/bin/docker" if n == "docker" else None)
    first = F.atpg_engine_identity()["image"]
    second = F.atpg_engine_identity()["image"]
    assert first.startswith("ghcr.io/example/first@")
    assert second.startswith("ghcr.io/example/second@"), "the image was remembered, not resolved"
    assert "DOCKER_IMAGE" not in vars(F), "a module constant stores the image again"


def test_the_atpg_local_route_resolves_nothing(monkeypatch, tmp_path):
    import _container_exec as CE
    import fault_atpg_run as F

    def _refuse(*a, **k):
        raise AssertionError("the local route resolved an image")
    monkeypatch.setattr(F._img, "resolve", _refuse)
    monkeypatch.setattr(CE.shutil, "which", lambda n, *a, **k: None)
    idy = F.atpg_engine_identity()
    assert idy["exec_route"] == "local" and idy["image"] is None


def test_the_atpg_container_route_refuses_by_name_when_nothing_resolves(monkeypatch):
    import _container_exec as CE
    import fault_atpg_run as F

    def _none(*a, **k):
        raise _eda_pin.ImageNotResolvable(["this host: docker unusable"])
    monkeypatch.setattr(F._img, "resolve", _none)
    monkeypatch.setattr(CE.shutil, "which",
                        lambda n, *a, **k: "/usr/bin/docker" if n == "docker" else None)
    with pytest.raises(_eda_pin.ImageNotResolvable):
        F.atpg_engine_identity()


def test_the_sat_probe_on_the_local_route_resolves_nothing(monkeypatch, tmp_path):
    import _container_exec as CE
    import transition_fault_atpg_run as T

    def _refuse(*a, **k):
        raise AssertionError("the local-route SAT probe resolved an image")
    monkeypatch.setattr(T._far, "docker_image", _refuse)
    monkeypatch.setattr(CE.shutil, "which", lambda n, *a, **k: None)
    monkeypatch.setattr(T, "_SAT_SOLVER_PROBE_CACHE", {})
    monkeypatch.setenv("VIBEIC_ATPG_SAT_SOLVER", "kissat")
    monkeypatch.setattr(T, "_run_in_docker",
                        lambda *a, **k: (0, "model found: FAIL!", ""))
    assert T._detect_sat_solver(tmp_path, None, 30) == "kissat"


# ── p0 front end / step-output content check ────────────────────────────────

def _rtl_project(tmp_path: Path) -> Path:
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.sv").write_text("module top(input logic a); endmodule\n")
    return tmp_path


def _front_end(monkeypatch, *, on_path: bool, docker: bool, default):
    import p0_tool_frontend_check as P
    resolved = []

    def _default_image():
        resolved.append(1)
        return default()
    monkeypatch.setattr(P, "default_image", _default_image)
    monkeypatch.setattr(
        P.shutil, "which",
        lambda n, *a, **k: ("/usr/bin/docker" if (n == "docker" and docker) else
                            (f"/bin/{n}" if on_path and n in ("yosys", "verilator") else None)))
    images = []

    def _fake(tool, args, project, image):
        images.append(image)
        return subprocess.CompletedProcess([], 0, "", "")
    monkeypatch.setattr(P, "_invoke", _fake)
    return P, resolved, images


def test_a_tool_on_path_resolves_no_image(monkeypatch, tmp_path):
    P, resolved, images = _front_end(
        monkeypatch, on_path=True, docker=False,
        default=lambda: pytest.fail("a tool on PATH resolved an image"))
    result = P.check(_rtl_project(tmp_path))
    assert result["passed"], result
    assert resolved == [] and images == [None, None]
    assert result["tools"]["Yosys.JsonHeader"]["execution"] == "host"


def test_the_docker_path_resolves_at_call_time(monkeypatch, tmp_path):
    P, resolved, images = _front_end(
        monkeypatch, on_path=False, docker=True,
        default=lambda: "ghcr.io/example/resolved@sha256:" + "3" * 64)
    result = P.check(_rtl_project(tmp_path))
    assert resolved, "the docker path did not resolve"
    assert images == ["ghcr.io/example/resolved@sha256:" + "3" * 64] * 2
    assert result["tools"]["Verilator.Lint"]["execution"] == images[0]


def test_a_declared_image_is_used_as_is(monkeypatch, tmp_path):
    P, resolved, images = _front_end(
        monkeypatch, on_path=False, docker=True,
        default=lambda: pytest.fail("a declared image was re-resolved"))
    P.check(_rtl_project(tmp_path), "declared/image:1")
    assert resolved == [] and images == ["declared/image:1"] * 2


def test_docker_needed_and_nothing_resolvable_is_refused_by_name(monkeypatch, tmp_path):
    def _none():
        raise _eda_pin.ImageNotResolvable(["this host: docker unusable"])
    P, _resolved, images = _front_end(monkeypatch, on_path=False, docker=True,
                                      default=_none)
    result = P.check(_rtl_project(tmp_path))
    assert not result["passed"]
    assert images == [], "a tool ran with no image"
    assert any("IMAGE_NOT_RESOLVABLE" in f for f in result["findings"]), result


# ── landing preflight: the remedy names the image when it is read ───────────


# ── fmeda: the injection backend asks for an image only as its first choice ──

def test_an_unresolvable_image_leaves_the_host_injection_leg_open(monkeypatch):
    """`resolve_injection_backend` is container-first. With no docker (inside
    the image) the image cannot even be resolved; that used to escape as
    ImageNotResolvable and crash the program although host iverilog/vvp was
    there to run the injection."""
    import fmeda_fault_injection_coverage as fi

    def _none():
        raise _eda_pin.ImageNotResolvable(["this host: docker unusable"])
    monkeypatch.setattr(fi, "_local_docker_image", _none)
    monkeypatch.setattr(fi, "_host_iverilog", lambda: True)
    assert fi.resolve_injection_backend()[:2] == (fi.BACKEND_HOST, None)
    monkeypatch.setattr(fi, "_host_iverilog", lambda: False)
    backend, img, reason = fi.resolve_injection_backend()
    assert (backend, img) == (fi.BACKEND_NONE, None)
    assert "IMAGE_NOT_RESOLVABLE" in reason, reason
    # a declared image is used as is, and nothing is resolved for it
    assert fi.resolve_injection_backend("declared/image:1")[:2] == (
        fi.BACKEND_DOCKER, "declared/image:1")


# ── image_reference names a reference THIS HOST HOLDS (lane migf14) ──────────
# Every fleet host configures VIBEIC_EDA_IMAGE_REPO as the fleet mirror while
# holding the bytes under another name; composing `<configured repo>@<digest>`
# named an image no host holds, and `docker run` of it would pull from the
# mirror. The model below is the daemon; it refuses any pull or registry ask.

_D = "sha256:" + "6d" * 32
_MIRROR = "mirror.invalid:5000/vibeic-eda"


def _host_holding(monkeypatch, *names):
    asked = []

    def _docker(*argv, timeout=None):
        asked.append(argv)
        if argv[:1] in (("pull",), ("manifest",)) or "pull" in argv:
            pytest.fail(f"image_reference reached the registry: {argv}")
        if argv[:2] == ("image", "ls"):
            return 0, "".join(f"{n}@{_D}\n" for n in names), ""
        pytest.fail(f"a daemon question this model does not describe: {argv}")
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)
    monkeypatch.setenv(_eda_pin.IMAGE_REPO_ENV, _MIRROR)
    monkeypatch.setattr(_eda_pin, "_docker", _docker)
    monkeypatch.setattr(_eda_pin, "resolved_image_digest",
                        lambda env=None, *, allow_pull=False: _D)
    return asked


def test_a_configured_mirror_the_host_does_not_hold_is_never_named(monkeypatch):
    asked = _host_holding(monkeypatch, _eda_pin.IMAGE_REPO_DEFAULT)
    got = _eda_pin.image_reference()
    assert got == f"{_eda_pin.IMAGE_REPO_DEFAULT}@{_D}", got
    assert not got.startswith(_MIRROR), "the configured repo was composed, not held"
    assert asked and all(a[:2] == ("image", "ls") for a in asked)


def test_the_configured_name_is_preferred_when_it_is_held(monkeypatch):
    _host_holding(monkeypatch, _eda_pin.IMAGE_REPO_DEFAULT, _MIRROR)
    assert _eda_pin.image_reference() == f"{_MIRROR}@{_D}"


def test_a_digest_no_local_name_carries_is_refused_by_name(monkeypatch):
    _host_holding(monkeypatch)                     # holds nothing
    with pytest.raises(_eda_pin.ImageNotHeld) as exc:
        _eda_pin.image_reference()
    assert isinstance(exc.value, _eda_pin.ImageNotResolvable)
    assert _eda_pin.IMAGE_NOT_PRESENT in str(exc.value)


def test_librelane_runs_the_held_reference_or_refuses(monkeypatch):
    import librelane_contract as LL
    from _stated_eda_image import mock_docker_route
    # This case models the host Docker daemon, not the enclosing LOCAL image.
    mock_docker_route(monkeypatch)
    monkeypatch.delenv("VIBEIC_LIBRELANE_IMAGE", raising=False)
    _host_holding(monkeypatch, _eda_pin.IMAGE_REPO_DEFAULT)
    assert LL.resolve_image(None) == f"{_eda_pin.IMAGE_REPO_DEFAULT}@{_D}"
    _host_holding(monkeypatch)
    with pytest.raises(LL.Refusal) as exc:
        LL.resolve_image(None)
    assert _eda_pin.IMAGE_NOT_PRESENT in str(exc.value)
