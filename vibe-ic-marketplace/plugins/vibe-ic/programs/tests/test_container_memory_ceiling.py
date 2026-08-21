#!/usr/bin/env python3
"""Every `docker run` this plugin issues must carry a memory ceiling.

MEASURED 2026-08-19 across a seven-machine fleet: 45 EDA containers were
running with `HostConfig.Memory == 0`. A container with no cgroup limit does
not share the host's memory — it IS the host's memory — and `ulimit -v` inside
our image is `unlimited`, so a tool never gets an allocation failure it could
report. On two of those machines a yosys took the whole box: the kernel's OOM
report shows two siblings at 54 GB apiece, then 109 GB for the survivor once
its twin was killed and the room freed. What actually died was chrome and Xorg
— the desktop session — because the OOM killer picks by oom_score_adj, not by
who caused the pressure.

Proven on the shipped image before any of this was written:

    --memory 512m   -> killed at 448 MiB, host `available` unchanged
    no --memory     -> the identical allocation reached 4096 MiB and exited 0

so the ceiling is what makes the difference, not the allocator.

The load-bearing test in this file is `test_no_docker_run_escapes_the_ceiling`.
The others check the arithmetic; that one checks that the arithmetic is
actually reachable from every place a container is created, which is the half
that decays — a new `docker run` added six months from now inherits nothing
unless something refuses it.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
sys.path.insert(0, str(_PROGRAMS))

import _docker_memory as dm  # noqa: E402

_GIB = 1024 ** 3


# ── the ceiling itself ──────────────────────────────────────────────────────

def test_the_default_is_a_fraction_of_physical_memory():
    total = dm.physical_memory_bytes()
    assert total and total > 0, "this platform reports no physical memory"
    flags = dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY_FRACTION": "25"})
    assert flags[0] == "--memory"
    assert int(flags[1]) == total * 25 // 100


def test_memory_swap_is_always_pinned_to_memory():
    """`--memory` alone still lets the container reach the host's swap, which
    is the half of the incident that froze the machine before it crashed."""
    for env in ({}, {"VIBEIC_DOCKER_MEMORY": "48g"},
                {"VIBEIC_DOCKER_MEMORY_FRACTION": "10"}):
        flags = dm.docker_memory_flags(env)
        assert flags[0::2] == ["--memory", "--memory-swap"], env
        assert flags[1] == flags[3], env


def test_a_derived_ceiling_is_a_plain_byte_count():
    """`docker run --memory 1.34974e+11` is a hard error, not a big number.

    The shell version of this ceiling shipped with `awk '{print $2 * 1024}'`,
    which printed 134973464576 on one host and `1.34974e+11` on five others —
    awk switches to OFMT above an implementation-dependent magnitude — and all
    five silently ran unbounded. Nothing here goes through a number formatter.
    """
    flags = dm.docker_memory_flags({})
    assert re.fullmatch(r"[0-9]+", flags[1]), flags


def test_an_explicit_ceiling_is_passed_through_verbatim():
    assert dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": "48g"}) == \
        ["--memory", "48g", "--memory-swap", "48g"]


def test_opting_out_emits_no_flag_at_all():
    """`--memory 0` is rejected by docker; opting out must emit nothing."""
    for value in ("0", "unlimited", "none", "OFF", " 0 "):
        assert dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": value}) == [], value


def test_a_nonsense_fraction_falls_back_to_the_default_not_to_nothing():
    """A typo must not silently disable the ceiling."""
    for bad in ("", "0", "101", "seventy", "-5", "3.5"):
        flags = dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY_FRACTION": bad})
        assert flags, bad
        assert int(flags[1]) == dm.physical_memory_bytes() * dm.DEFAULT_FRACTION // 100


def test_the_ceiling_never_drops_below_the_floor_or_above_the_host(monkeypatch):
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: 1 * _GIB)
    # a 1 GiB host: the floor would exceed it, so the host total wins
    assert int(dm.docker_memory_flags({})[1]) == 1 * _GIB
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: 64 * _GIB)
    assert int(dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY_FRACTION": "1"})[1]) \
        == dm.FLOOR_BYTES


# ── the CLI the shell installer reads ───────────────────────────────────────

def _cli(*args, env=None):
    import os
    e = dict(os.environ)
    e.pop("VIBEIC_DOCKER_MEMORY", None)
    e.pop("VIBEIC_DOCKER_MEMORY_FRACTION", None)
    e.update(env or {})
    return subprocess.run([sys.executable, str(_PROGRAMS / "_docker_memory.py"), *args],
                          capture_output=True, text=True, timeout=60, env=e, check=False)


def test_the_cli_prints_the_flags_one_per_line():
    r = _cli("--flags")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split()
    assert lines[0::2] == ["--memory", "--memory-swap"]
    assert lines[1] == lines[3]


def test_the_cli_says_nothing_when_opted_out():
    r = _cli("--flags", env={"VIBEIC_DOCKER_MEMORY": "0"})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_the_cli_refuses_rather_than_printing_nothing_when_it_cannot_tell():
    """"Cannot compute a ceiling" must be a refusal, not silence.

    Silence is indistinguishable from a deliberate opt-out at the shell, so a
    caller would create the unbounded container this all exists to prevent —
    and report success while doing it.
    """
    shim = ("import os, sys; "
            f"sys.path.insert(0, {str(_PROGRAMS)!r}); "
            "import _docker_memory as m; m.physical_memory_bytes = lambda: None; "
            "sys.exit(m._main(['--flags']))")
    r = subprocess.run([sys.executable, "-c", shim], capture_output=True,
                       text=True, timeout=60, check=False)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "VIBEIC_DOCKER_MEMORY" in r.stdout


# ── the guard that has to survive future edits ──────────────────────────────

_RUN_ARGV = re.compile(r'\[\s*(?:"docker"|docker_bin)\s*,\s*"run"')


def test_no_docker_run_escapes_the_ceiling():
    """Every container-creating argv in programs/ splices the flags in.

    Stated as a total rule with no allowlist on purpose. Some of these runs are
    one-line probes that could never grow to 100 GB, but "this one is small" is
    the judgement that has to be re-made correctly every time a call site is
    edited, and it is cheaper to make the rule unconditional than to maintain
    the exceptions.
    """
    escaped = []
    for path in sorted(_PROGRAMS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in _RUN_ARGV.finditer(src):
            window = src[m.start():m.start() + 400]
            if "docker_memory_flags" not in window:
                line = src[:m.start()].count("\n") + 1
                escaped.append(f"{path.name}:{line}")
    assert escaped == [], (
        "these `docker run` sites create a container with no memory ceiling; "
        "splice `*_dmem.docker_memory_flags()` in after the run verb: "
        f"{escaped}")


def test_the_ceiling_is_reachable_from_every_program_that_uses_it():
    """A spliced call that cannot import the helper is a NameError at runtime,
    on a path that only executes when real hardware work starts."""
    users = [p for p in sorted(_PROGRAMS.glob("*.py"))
             if "docker_memory_flags" in p.read_text(encoding="utf-8")]
    assert len(users) >= 8, f"expected the wiring across the plugin, found {users}"
    for path in users:
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(_PROGRAMS)!r}); "
             f"import {path.stem}"],
            capture_output=True, text=True, timeout=120, check=False)
        assert r.returncode == 0, f"{path.name} does not import: {r.stderr[-600:]}"


# ── behavioural: the argv a real driver hands docker ────────────────────────

def test_mpw_precheck_argv_carries_the_ceiling(tmp_path):
    import mpw_precheck_driver as mpw
    for d in ("src", "input", "pdk", "run"):
        (tmp_path / d).mkdir()
    argv = mpw.build_docker_command(
        image="img:1", input_directory=tmp_path / "input",
        pdk_root=tmp_path / "pdk", pdk_path=tmp_path / "pdk",
        precheck_src=tmp_path / "src", rundir=tmp_path / "run",
        checks=["license"])
    assert argv[:2] == ["docker", "run"]
    assert "--memory" in argv and "--memory-swap" in argv
    assert argv[argv.index("--memory") + 1] == argv[argv.index("--memory-swap") + 1]


def test_caravel_harden_argv_carries_the_ceiling(tmp_path):
    import caravel_wrapper_harden_driver as cw
    argv = cw.build_harden_command(project_dir=tmp_path, design="user_project_wrapper",
                                   image="img:1", pdk_root=str(tmp_path), tag="t")
    assert "--memory" in argv
    # and the image is still the last thing before the entrypoint args
    assert argv.index("--memory") < argv.index("img:1")


def test_the_installer_script_refuses_without_the_helper(tmp_path):
    """tools/vibeic-eda/restart-eda.sh must not fall back to unbounded when the
    helper it reads the ceiling from is absent."""
    script = _REPO / "tools" / "vibeic-eda" / "restart-eda.sh"
    if not script.is_file():
        pytest.skip(f"{script} not in this checkout")
    body = script.read_text(encoding="utf-8")
    assert "_docker_memory.py" in body, (
        "the installer computes its own ceiling instead of reading the shared "
        "one; the two will drift")
    assert re.search(r'die "missing \$\{?_MEMTOOL', body) or "die \"missing ${_MEMTOOL}" in body, (
        "a missing helper must be a refusal, not an unbounded container")
    assert "MEMFLAGS" in body and 'RUN+=( "${MEMFLAGS[@]}" )' in body, (
        "the flags are computed but never reach the `docker run` argv")
