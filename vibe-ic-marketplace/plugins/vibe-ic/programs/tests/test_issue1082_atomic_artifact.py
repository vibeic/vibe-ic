#!/usr/bin/env python3
"""vibe-ic#1082 — a declared artefact under its final name means the writer finished.

Every test here drives the real module. The load-bearing one is
`test_a_sigkilled_writer_leaves_no_file_under_the_final_name`: it forks a real
child, SIGKILLs it mid-write, and asserts on the filesystem afterwards. A
`finally` cannot cover SIGKILL — that is the whole reason the temp-then-rename
shape is needed rather than a try/except that unlinks — so the proof has to use
the signal, not a raised exception.

The control it is paired with runs the SAME child doing a DIRECT
`Path.write_text`, and asserts the truncated file IS left behind. Without that
arm the test would pass against a hypothetical filesystem that never leaves
partial writes, and would prove nothing about this module.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _atomic_artifact as A  # noqa: E402


# ── the invariant, on the happy path ────────────────────────────────────────

def test_the_final_name_holds_the_whole_content(tmp_path):
    p = tmp_path / "out" / "report.json"
    A.atomic_write_json(p, {"verdict": "PASS", "examined": 7})
    assert json.loads(p.read_text()) == {"verdict": "PASS", "examined": 7}
    assert p.parent.is_dir(), "parent directories are created"


def test_no_temp_file_survives_a_successful_write(tmp_path):
    p = tmp_path / "report.json"
    A.atomic_write_text(p, "done\n")
    leftovers = [q for q in tmp_path.iterdir() if q != p]
    assert leftovers == [], leftovers


def test_bytes_and_text_round_trip(tmp_path):
    A.atomic_write_bytes(tmp_path / "a.gds", b"HEADER\x00\x01")
    A.atomic_write_text(tmp_path / "b.rpt", "line\n")
    assert (tmp_path / "a.gds").read_bytes() == b"HEADER\x00\x01"
    assert (tmp_path / "b.rpt").read_text() == "line\n"


# ── the invariant, when the writer fails ────────────────────────────────────

def test_an_exception_mid_write_leaves_NO_file_under_the_final_name(tmp_path):
    p = tmp_path / "report.json"
    with pytest.raises(RuntimeError):
        with A.atomic_output(p) as fh:
            fh.write('{"partial": ')
            raise RuntimeError("the step died here")
    assert not p.exists(), (
        "a step that died mid-write left an artefact under its final name — "
        "which is exactly what makes `required_outputs` meaningless")
    assert list(tmp_path.iterdir()) == [], list(tmp_path.iterdir())


def test_a_failed_rewrite_leaves_THE_PREVIOUS_content_not_a_stump(tmp_path):
    """The second write is the dangerous one: a direct `write_text` truncates
    the good artefact first and then dies, so the tree ends up WORSE than if
    the step had never run."""
    p = tmp_path / "report.json"
    A.atomic_write_json(p, {"run": 1})
    with pytest.raises(RuntimeError):
        with A.atomic_output(p) as fh:
            fh.write("{")
            raise RuntimeError("died on the re-run")
    assert json.loads(p.read_text()) == {"run": 1}


def test_an_unrenderable_object_creates_no_file_at_all(tmp_path):
    """`json.dumps` raises BEFORE any file exists — the reason
    `atomic_write_json` renders to a string first rather than streaming.

    A circular structure is the shape `default=str` cannot rescue, so it is
    what reaches the raise.
    """
    p = tmp_path / "report.json"
    cyclic: dict = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError):          # "Circular reference detected"
        A.atomic_write_json(p, cyclic)
    assert not p.exists()
    assert list(tmp_path.iterdir()) == []


# ── SIGKILL: the case a `finally` cannot cover ──────────────────────────────

_CHILD = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, {progs!r})
    dest = {dest!r}
    if {atomic!r}:
        import _atomic_artifact as A
        with A.atomic_output(dest) as fh:
            fh.write('{{"partial": ')
            fh.flush()
            open({flag!r}, "w").close()
            time.sleep(30)
    else:
        from pathlib import Path
        fh = open(dest, "w")
        fh.write('{{"partial": ')
        fh.flush()
        open({flag!r}, "w").close()
        time.sleep(30)
""")


def _kill_mid_write(tmp_path, *, atomic: bool) -> Path:
    dest = tmp_path / ("atomic.json" if atomic else "direct.json")
    flag = tmp_path / ("flag_a" if atomic else "flag_d")
    src = _CHILD.format(progs=str(PROGRAMS), dest=str(dest),
                        flag=str(flag), atomic=atomic)
    proc = subprocess.Popen([sys.executable, "-c", src])
    try:
        deadline = time.time() + 30
        while not flag.exists() and time.time() < deadline:
            if proc.poll() is not None:
                raise AssertionError("child exited before it began writing")
            time.sleep(0.02)
        assert flag.exists(), "child never reached the mid-write point"
        os.kill(proc.pid, signal.SIGKILL)
    finally:
        proc.wait(timeout=30)
    assert proc.returncode == -signal.SIGKILL, proc.returncode
    return dest


def test_a_sigkilled_writer_leaves_no_file_under_the_final_name(tmp_path):
    """THE CLAIM. A `finally` does not run under SIGKILL; `os.replace` never
    happened, so the final name was never created."""
    dest = _kill_mid_write(tmp_path, atomic=True)
    assert not dest.exists(), (
        "SIGKILL mid-write left the declared artefact under its final name")


def test_CONTROL_a_direct_write_DOES_leave_a_truncated_artefact(tmp_path):
    """The paired control. Same child, same signal, `open(dest,'w')` instead.

    If this ever stops failing to leave a stump, the test above is passing for
    a reason that has nothing to do with `_atomic_artifact` and the whole file
    is measuring the filesystem instead of the module.
    """
    dest = _kill_mid_write(tmp_path, atomic=False)
    assert dest.exists(), (
        "the control did not reproduce the defect, so the atomic test above "
        "proves nothing on this filesystem")
    with pytest.raises(json.JSONDecodeError):
        json.loads(dest.read_text())


# ── leftovers ───────────────────────────────────────────────────────────────

def test_a_leftover_temp_is_never_mistaken_for_the_artefact(tmp_path):
    """It is dot-prefixed and does not carry the declared name, so neither a
    `*.json` glob nor an `exists()` on the declared path sees it."""
    dest = tmp_path / "report.json"
    tmp = A.temp_name_for(dest)
    tmp.write_text('{"partial": ')
    assert not dest.exists()
    assert list(tmp_path.glob("*.json")) == []


def test_sweep_removes_a_dead_writers_temp_and_spares_a_live_one(tmp_path):
    dead = tmp_path / f".gone.json.999999{A.TEMP_SUFFIX}"
    dead.write_text("x")
    live = A.temp_name_for(tmp_path / "mine.json")   # stamped with OUR pid
    live.write_text("y")
    removed = A.sweep_stale_temps(tmp_path)
    assert dead in removed and not dead.exists()
    assert live.exists(), "a live writer's temp must not be swept"


def test_the_temp_lives_beside_its_destination(tmp_path):
    """Cross-filesystem `os.replace` is not atomic, so the temp may not be in
    a scratch dir elsewhere."""
    dest = tmp_path / "sub" / "report.json"
    assert A.temp_name_for(dest).parent == dest.parent
