"""The host mount root is MEASURED from the container, never read off a name.

THE DEFECT
==========
Three shipped programs derived "which host directory does the container see as
its designs root?" by searching the host path for one developer's design-tree
directory NAME::

    host_root = Path(str(project).split(NAME)[0]) / NAME      # two analog drivers
    if NAME in str(h): ... Path.home() / NAME                 # the yosys flattener

On any machine whose design tree is called something else the test is False and
the code falls through to a different root. MEASURED on a live container with a
tree named nothing like NAME: the old derivation emitted
``/foss/designs/phase2/.../run.sp`` for a file whose real container path is
``/foss/designs/quiet_adc/phase2/.../run.sp`` — ``docker exec test -f`` says
rc=1 for the first and rc=0 for the second. A wrong answer that renders exactly
like a right one.

Renaming NAME to some other directory would leave the same defect wearing
different clothes, so these tests do not merely ban a token:

  * TOKEN guard   — the private name must not survive in any shipped code
    string literal (docstrings and comments are prose and are excluded; the
    name is assembled from fragments here so this file does not carry it).
  * SHAPE guard   — each site's mount root must be a call into the shared
    designs-root ladder. An AST assertion, so ANY re-derivation from a string
    (a new name, a split, an `in` test) fails it, not just the old token.
  * BEHAVIOUR     — with a stubbed / faked mount table, each site must produce
    the container path the mount table implies, and must REFUSE when no mount
    covers the path rather than emit a plausible-looking default.

SCOPE THIS FILE DOES NOT COVER (stated, not silently excluded): the token guard
reads Python sources only. Shell and JSON sources under the plugin are outside
it; the one live shell occurrence is a GitHub repository slug, not a filesystem
path.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[1]
_PLUGIN = _HERE.parents[2]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _designs_root as dr                      # noqa: E402
import analog_real_corner_sweep as ARS          # noqa: E402
import analog_mc_yield_run as MCY               # noqa: E402
import shipped_path_portability_check as SPC    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# Assembled, never spelled: this guard must not be the thing that reintroduces
# the name it exists to keep out, and must not match itself.
_PRIVATE_DIR_NAME = "AI" + "_IC_" + "design"

_SITES = {
    "analog_real_corner_sweep.py": _PROGRAMS / "analog_real_corner_sweep.py",
    "analog_mc_yield_run.py": _PROGRAMS / "analog_mc_yield_run.py",
}


# ---------------------------------------------------------------------------
# TOKEN guard — the sweep
# ---------------------------------------------------------------------------
def _shipped_python_sources():
    for sub in ("programs", "benchmark", "mcp-eda/src", "skills"):
        base = _PLUGIN / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(_PLUGIN)
            parts = rel.parts
            if "__pycache__" in parts or "tests" in parts or "test" in parts:
                continue
            yield rel, p


def test_the_population_this_guard_scans_is_not_empty():
    """A PASS with no denominator cannot be told apart from a PASS that read
    nothing."""
    n = sum(1 for _ in _shipped_python_sources())
    assert n > 200, f"shipped-python census collapsed to {n} files"


def test_no_shipped_code_literal_names_a_private_design_directory():
    """R-TOKEN: the private directory name must not appear in executable code.

    Prose (docstrings, comments) is excluded on purpose — a placeholder there is
    documentation. A code STRING is a value, and a value that names one
    machine's directory cannot be correct on another's.
    """
    offenders = []
    for rel, p in _shipped_python_sources():
        text = p.read_text(errors="replace")
        if _PRIVATE_DIR_NAME not in text:
            continue
        for s in SPC._py_code_strings(text):
            if _PRIVATE_DIR_NAME in s:
                offenders.append(f"{rel}: {s[:120]!r}")
    assert offenders == [], (
        "a private design-directory name is back in shipped executable code:\n"
        + "\n".join(offenders))


# ---------------------------------------------------------------------------
# SHAPE guard — the mount root must come from the shared ladder
# ---------------------------------------------------------------------------
def _calls_in(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            yield n


def _call_dotted_name(call):
    f = call.func
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


@pytest.mark.parametrize("name", sorted(_SITES))
def test_site_imports_the_shared_designs_root_ladder(name):
    """No site may grow its own answer to a question the plugin answers once."""
    tree = ast.parse(_SITES[name].read_text())
    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names
    }
    assert "_designs_root" in imported, (
        f"{name} must consume the shared designs-root ladder, not re-derive it")


@pytest.mark.parametrize("name", ["analog_real_corner_sweep.py",
                                  "analog_mc_yield_run.py"])
def test_host_root_is_assigned_from_the_ladder_not_from_a_string(name):
    """Every `host_root = ...` in these drivers must be a ladder call.

    This is the assertion that survives a RENAME: any derivation from a string
    literal — a new directory name, a `.split()`, an `in str(path)` test — is
    not a call to `_dr.resolve_host_root`, so it fails here.
    """
    tree = ast.parse(_SITES[name].read_text())
    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "host_root"
                       for t in n.targets)]
    assert assigns, f"{name}: no host_root assignment found at all"
    for a in assigns:
        assert isinstance(a.value, ast.Call), (
            f"{name}:{a.lineno} host_root is derived from an expression, not "
            f"measured: {ast.dump(a.value)[:160]}")
        assert _call_dotted_name(a.value) == "_dr.resolve_host_root", (
            f"{name}:{a.lineno} host_root must come from the designs-root "
            f"ladder, got {_call_dotted_name(a.value)!r}")




# ---------------------------------------------------------------------------
# BEHAVIOUR — the analog drivers
# ---------------------------------------------------------------------------
def _stub_docker_miss(monkeypatch):
    """`docker exec test -e <host path>` fails: the container does NOT expose
    the host's absolute path, i.e. the legacy /foss/designs-style mount."""
    monkeypatch.setattr(
        ARS, "_docker",
        lambda c, cmd, **kw: types.SimpleNamespace(
            returncode=1, stdout="", stderr=""))


def _tree(tmp_path):
    """A design tree whose name has nothing to do with any private one."""
    mount = tmp_path / "photon_lab_workspace"
    proj = mount / "quiet_adc"
    sp = proj / "phase2" / "analog" / "ldo" / "sizing_loop" / "run.sp"
    sp.parent.mkdir(parents=True)
    sp.write_text("* deck\n")
    return mount, proj, sp


def test_analog_driver_uses_the_mount_destination_for_an_unrelated_tree(
        monkeypatch, tmp_path):
    mount, proj, sp = _tree(tmp_path)
    pairs = [(mount.resolve(), "/foss/designs")]
    monkeypatch.setattr(dr, "container_mounts", lambda c: pairs)
    _stub_docker_miss(monkeypatch)
    ARS._CONTAINER_PATH_CACHE.clear()

    root = dr.resolve_host_root(proj, "c")
    assert root.basis == dr.BASIS_MOUNT
    assert root.host_root == mount.resolve()
    assert ARS._container_path("c", root, sp) == \
        "/foss/designs/quiet_adc/phase2/analog/ldo/sizing_loop/run.sp"


def test_analog_driver_honours_a_non_default_mount_destination(
        monkeypatch, tmp_path):
    """Source and Destination are ONE mapping: a tree mounted somewhere other
    than the historical default must not be rewritten to the default."""
    mount, proj, sp = _tree(tmp_path)
    pairs = [(mount.resolve(), "/workspace-live")]
    monkeypatch.setattr(dr, "container_mounts", lambda c: pairs)
    _stub_docker_miss(monkeypatch)
    ARS._CONTAINER_PATH_CACHE.clear()

    root = dr.resolve_host_root(proj, "c")
    assert ARS._container_path("c", root, sp) == \
        "/workspace-live/quiet_adc/phase2/analog/ldo/sizing_loop/run.sp"


def test_analog_driver_still_works_for_a_tree_under_the_old_magic_name(
        monkeypatch, tmp_path):
    """The CONTROL. The case that happened to work before must still work."""
    mount = tmp_path / _PRIVATE_DIR_NAME
    proj = mount / "quiet_adc"
    sp = proj / "phase2" / "analog" / "ldo" / "sizing_loop" / "run.sp"
    sp.parent.mkdir(parents=True)
    sp.write_text("* deck\n")
    pairs = [(mount.resolve(), "/foss/designs")]
    monkeypatch.setattr(dr, "container_mounts", lambda c: pairs)
    _stub_docker_miss(monkeypatch)
    ARS._CONTAINER_PATH_CACHE.clear()

    root = dr.resolve_host_root(proj, "c")
    assert root.host_root == mount.resolve()
    assert ARS._container_path("c", root, sp) == \
        "/foss/designs/quiet_adc/phase2/analog/ldo/sizing_loop/run.sp"


def test_analog_driver_refuses_when_no_mount_covers_the_path(
        monkeypatch, tmp_path):
    """An unanswerable question gets 'I cannot tell', never a default."""
    mount, proj, sp = _tree(tmp_path)
    monkeypatch.setattr(dr, "container_mounts", lambda c: [])
    _stub_docker_miss(monkeypatch)
    ARS._CONTAINER_PATH_CACHE.clear()

    root = dr.resolve_host_root(proj, "c")
    assert root.basis == dr.BASIS_PROJECT_FALLBACK
    assert root.mount_root_is_measured is False
    with pytest.raises(dr.MountRootUnresolved) as ei:
        ARS._container_path("c", root, sp)
    st = ei.value.status
    assert st["error_code"] == "DESIGNS_ROOT_UNRESOLVED"
    assert st["needs_user_decision"] is True
    assert dr.HOST_ROOT_ENV in st["reason"]


def test_analog_driver_reports_the_refusal_instead_of_raising(
        monkeypatch, tmp_path):
    """`run_block` is an entry point: the refusal must be a VERDICT."""
    _mount, proj, _sp = _tree(tmp_path)
    monkeypatch.setattr(
        ARS, "_run_block",
        lambda *a, **k: (_ for _ in ()).throw(
            dr.MountRootUnresolved(dr.unresolved_status("probe", "c"))))
    assert ARS.run_block(proj, "ldo", "c", "sky130", "auto") == 2


def test_mc_yield_reports_a_structured_skip_instead_of_raising(
        monkeypatch, tmp_path):
    _mount, proj, _sp = _tree(tmp_path)
    monkeypatch.setattr(
        MCY, "_run_block",
        lambda *a, **k: (_ for _ in ()).throw(
            dr.MountRootUnresolved(dr.unresolved_status("probe", "c"))))
    out = MCY.run_block(proj, "ldo", "c", "sky130", 3)
    assert out["verdict"] == "SKIP"
    assert out["rc"] == 2
    assert out["mc_runs"] == 0
    assert out["error_code"] == "DESIGNS_ROOT_UNRESOLVED"
    assert out["needs_user_decision"] is True
    assert {o["id"] for o in out["options"]} == {"derive_from_project",
                                                 "explicit_env"}


# ---------------------------------------------------------------------------
# BEHAVIOUR — the yosys flattener, driven as a real process over a fake docker
# ---------------------------------------------------------------------------
