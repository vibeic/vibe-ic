"""The designs-root resolution ladder in benchmark/score_iverilog_tb.py.

Background: the scorer used to default its host designs root to one developer's
home directory and then `mkdir(parents=True, exist_ok=True)` it — so a clean
install grew a workspace directory nobody asked for, and on any other machine
the container paths it produced were silently wrong.

The replacement is a LADDER, and the ordering is the whole point:

  1. $VIBEIC_DESIGNS_HOST_ROOT           — explicit; power users and CI.
  2. derived from the caller's project   — the normal case: every entry point
                                           already receives a design_dir, so
                                           nothing needs configuring and the
                                           thing mounted is what the user is
                                           actually working on.
  3. structured needs-a-decision status  — never a hard exit, never an invented
                                           path. The programs are
                                           non-interactive and are driven by an
                                           AI agent, which relays the choice.

The invariant every test here shares: **no directory is ever created outside a
path the caller already gave us.**
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_SCORER = _PLUGIN / "benchmark" / "score_iverilog_tb.py"


@pytest.fixture()
def mod(monkeypatch):
    monkeypatch.delenv("VIBEIC_DESIGNS_HOST_ROOT", raising=False)
    spec = importlib.util.spec_from_file_location("_score_iv", _SCORER)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_score_iv"] = m
    spec.loader.exec_module(m)
    # Never let a real `docker inspect` make these tests environment-dependent.
    monkeypatch.setattr(m, "_container_mounts", lambda c: [])
    monkeypatch.setattr(m, "_container_mount_sources", lambda c: [])
    return m


# --------------------------------------------------------------------------
# The defect itself
# --------------------------------------------------------------------------
def test_no_personal_path_constant_survives(mod):
    """The module must not carry any absolute home path as a value."""
    src = _SCORER.read_text()
    for m in re.finditer(r"/home/([A-Za-z0-9._-]+)/|/Users/([A-Za-z0-9._-]+)/", src):
        assert False, f"absolute home path still in the scorer: {m.group(0)!r}"


def test_nothing_is_created_in_home(mod, monkeypatch, tmp_path):
    """The phantom-directory regression, pinned."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VIBEIC_DESIGNS_HOST_ROOT", raising=False)

    assert mod._host_designs_root(None) is None
    built, passed = mod._verilator_run_text(
        "module m; endmodule", "d", tmp_path / "tb.v", None,
        re.compile("PASS"), "t")
    assert (built, passed) == (False, False)
    assert list(home.iterdir()) == [], \
        f"the scorer created something in HOME: {list(home.iterdir())}"


# --------------------------------------------------------------------------
# Rung 1 — explicit env
# --------------------------------------------------------------------------
def test_rung1_explicit_env_wins(mod, monkeypatch, tmp_path):
    root = tmp_path / "designs"
    root.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(root))
    assert mod._host_designs_root(proj) == root.resolve()


def test_rung1_missing_env_dir_is_not_created_and_falls_through(
        mod, monkeypatch, tmp_path):
    """A bad env value must not be conjured into existence; we fall through to
    the project rather than failing the run."""
    ghost = tmp_path / "not-there"
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(ghost))
    assert mod._host_designs_root(proj) == proj.resolve()
    assert not ghost.exists(), "a non-existent env root must never be created"


# --------------------------------------------------------------------------
# Rung 2 — derived from the caller's project (the normal case)
# --------------------------------------------------------------------------
def test_rung2_derives_root_from_project(mod, tmp_path):
    proj = tmp_path / "my_chip"
    proj.mkdir()
    assert mod._host_designs_root(proj) == proj.resolve()


def test_rung2_prefers_the_bind_mount_containing_the_project(
        mod, monkeypatch, tmp_path):
    """When the container's mount table is readable, the mount that CONTAINS the
    project wins over the project itself — host->container translation then
    stays correct for the whole tree, not just the project subdir."""
    mount = tmp_path / "workspace"
    proj = mount / "chips" / "my_chip"
    proj.mkdir(parents=True)
    monkeypatch.setattr(mod, "_container_mount_sources",
                        lambda c: [mount.resolve()])
    assert mod._host_designs_root(proj) == mount.resolve()


def test_rung2_ignores_unrelated_mounts(mod, monkeypatch, tmp_path):
    other = tmp_path / "somewhere_else"
    other.mkdir()
    proj = tmp_path / "my_chip"
    proj.mkdir()
    monkeypatch.setattr(mod, "_container_mount_sources",
                        lambda c: [other.resolve()])
    assert mod._host_designs_root(proj) == proj.resolve()


def test_rung2_translation_uses_the_derived_root(mod, tmp_path):
    proj = tmp_path / "my_chip"
    (proj / "rtl").mkdir(parents=True)
    assert mod._to_container(str(proj / "rtl" / "top.v"), proj) == \
        "/foss/designs/rtl/top.v"


def test_rung2_translation_uses_actual_mount_destination(mod, monkeypatch,
                                                          tmp_path):
    """The Source and Destination from docker inspect are one mapping.

    Rewriting a discovered host Source to the historical /foss/designs default
    produced paths that did not exist when the live container used a different
    destination.
    """
    mount = tmp_path / "workspace"
    proj = mount / "chips" / "my_chip"
    rtl = proj / "rtl" / "top.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module top; endmodule\n")
    pairs = [(mount.resolve(), "/workspace-live")]
    monkeypatch.setattr(mod, "_container_mounts", lambda c: pairs)
    monkeypatch.setattr(mod, "_container_mount_sources",
                        lambda c: [src for src, _dst in pairs])

    assert mod._to_container(str(rtl), proj) == \
        "/workspace-live/chips/my_chip/rtl/top.v"


def test_rung2_nested_mount_uses_longest_source_prefix(mod, monkeypatch,
                                                        tmp_path):
    outer = tmp_path / "workspace"
    inner = outer / "runs"
    proj = inner / "chip"
    rtl = proj / "top.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module top; endmodule\n")
    pairs = [(outer.resolve(), "/outer"), (inner.resolve(), "/active-runs")]
    monkeypatch.setattr(mod, "_container_mounts", lambda c: pairs)
    monkeypatch.setattr(mod, "_container_mount_sources",
                        lambda c: [src for src, _dst in pairs])

    assert mod._to_container(str(rtl), proj) == "/active-runs/chip/top.v"


def test_rung2_explicit_container_destination_still_wins(mod, monkeypatch,
                                                          tmp_path):
    root = tmp_path / "workspace"
    proj = root / "chip"
    proj.mkdir(parents=True)
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(root))
    monkeypatch.setenv("VIBEIC_DESIGNS_CONT_ROOT", "/ci/designs")
    monkeypatch.setattr(mod, "_container_mounts",
                        lambda c: [(root.resolve(), "/live-but-overridden")])

    assert mod._to_container(str(proj / "top.v"), proj) == "/ci/designs/chip/top.v"


# --------------------------------------------------------------------------
# Rung 3 — structured decision request, never a hard exit
# --------------------------------------------------------------------------
def test_rung3_returns_none_not_an_invented_path(mod):
    assert mod._host_designs_root(None) is None


def test_rung3_status_is_structured_and_actionable(mod):
    st = mod._designs_root_undecided("no project given.")
    assert st["needs_user_decision"] is True
    assert st["error_code"] == "DESIGNS_ROOT_UNRESOLVED"
    assert st["verdict"] == "SKIP"
    ids = {o["id"] for o in st["options"]}
    assert ids == {"derive_from_project", "explicit_env"}
    # the human-readable half must name the env var and both routes
    assert "VIBEIC_DESIGNS_HOST_ROOT" in st["reason"]
    assert "project" in st["reason"].lower()


def test_rung3_does_not_exit_the_process(mod):
    """A hard exit would be terrible UX for a first-time user AND would kill the
    surrounding scoring run. It must be a returned VALUE."""
    r = mod._verilator_compile_run("d", "/tmp/x.v", Path("/tmp/tb.v"), None,
                                   re.compile("PASS"), None)
    assert isinstance(r, dict)
    assert r.get("needs_user_decision") is True


def test_rung3_message_promises_no_directory_creation(mod):
    assert "never adds directories" in mod._DESIGNS_ROOT_HELP
