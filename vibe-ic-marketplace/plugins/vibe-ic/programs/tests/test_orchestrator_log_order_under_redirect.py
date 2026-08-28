#!/usr/bin/env python3
"""A redirected orchestrator log reported the phases in the wrong ORDER.

Python block-buffers stdout when it is not a tty. The orchestrator's phase
banners therefore sat in a buffer until exit, while the child runners — which
inherit the same fd — wrote through it as they went. Under the redirect every
real run uses (`> run.log 2>&1`) the file recorded ALL child output first and
ALL banners last.

MEASURED (sha256 x sky130A, run1.log): `=== PHASE 2 ===` was followed
immediately by the `DONE` banner with zero phase-2 output between them, which
reads as "phase 2 died instantly". Phase 2 had run its full 3-iteration RTL repair/retry loop
at lines 109-131 — ABOVE its own banner. Every phase attribution made from that
log was off by one, on every cell, every run.

These tests are BEHAVIOURAL: they redirect a real parent/child pair to a file
and assert the resulting ORDER. A source grep for `reconfigure` would pass
against a call placed somewhere it never runs, and would fail against any other
correct fix (`-u`, `PYTHONUNBUFFERED`, per-print flush) — it would be testing
this implementation rather than the property.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]

# The two runners that print progress AND spawn a child which inherits stdout.
# The others capture their children's output, so nothing interleaves.
ORCHESTRATORS = ("vibe_ic_one_shot_runner.py", "design_one_shot_runner.py")

sys.path.insert(0, str(PROGRAMS))
import _watchdog  # noqa: E402


def _redirected_to_a_file(cmd) -> str:
    """Run `cmd` with BOTH streams on one non-tty regular file, and return what
    that file received — under progress supervision, with no wall-clock bound.

    The redirect is the SUBJECT here: block buffering is what a child does when
    its stdout is not a tty, and `run_host_supervised` captures into an OS temp
    FILE, so the child sees exactly the stream shape `> run.log 2>&1` gives it.
    `merge_stderr=True` sends stderr down the same descriptor, which is what
    makes the recorded ORDER meaningful — separately captured streams re-order
    under Python's own buffering and the assertion would be about the harness.

    The bound this replaces was 60 s, justified by "the redirect probe runs
    0.06 s, so 60 s is ~370x". A multiple of a measured runtime is still a
    reading of one host: exceed it on a loaded box and the recorded result is
    not "the machine was busy" but the orchestrator failing. Nothing here bounds
    runtime now — only the absence of forward progress, which is the property
    "hung" actually means."""
    res = _watchdog.run_host_supervised(cmd, merge_stderr=True)
    return res.out


def _redirected_order(tmp_path: Path, preamble: str) -> list[str]:
    """Run a parent that prints around an inherited-stdout child, redirected to
    a FILE (not a tty), and return the recorded lines."""
    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent(f"""
        import subprocess, sys
        {preamble}
        print("=== PHASE 1 ===")
        subprocess.run([sys.executable, "-c", "print('child-1')"])
        print("=== PHASE 2 ===")
        subprocess.run([sys.executable, "-c", "print('child-2')"])
        print("=== DONE ===")
    """))
    log = tmp_path / "run.log"
    log.write_text(_redirected_to_a_file([sys.executable, str(parent)]))
    return log.read_text().splitlines()


def test_block_buffering_really_does_reorder_a_redirected_log(tmp_path):
    """The control. Without the fix the reordering is real, not theoretical —
    if this ever stops holding, the test below is passing for a reason that has
    nothing to do with the fix."""
    lines = _redirected_order(tmp_path, preamble="")
    assert lines.index("child-1") < lines.index("=== PHASE 1 ==="), (
        f"expected the un-fixed shape, got {lines!r}")


def test_line_buffering_restores_the_true_order(tmp_path):
    """The property: a banner precedes the output of the phase it announces."""
    lines = _redirected_order(
        tmp_path,
        preamble="sys.stdout.reconfigure(line_buffering=True)")
    assert lines == ["=== PHASE 1 ===", "child-1",
                     "=== PHASE 2 ===", "child-2",
                     "=== DONE ==="], lines


def test_each_orchestrator_line_buffers_its_own_stream(tmp_path):
    """Applied where it was measured: importing the module and calling its
    entry hook must leave stdout line-buffered. Checked by BEHAVIOUR (the flag
    the interpreter reports) rather than by the presence of a call."""
    for prog in ORCHESTRATORS:
        probe = tmp_path / f"probe_{prog}"
        probe.write_text(textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(PROGRAMS)!r})
            import {Path(prog).stem} as m
            m._line_buffer_own_stream()
            print("line_buffering=%s" % sys.stdout.line_buffering)
        """))
        log = tmp_path / f"out_{prog}.log"
        log.write_text(_redirected_to_a_file([sys.executable, str(probe)]))
        out = log.read_text()
        assert "line_buffering=True" in out, f"{prog}: {out[-400:]}"


def test_the_hook_runs_before_the_first_banner(tmp_path):
    """A correctly-written helper called too late fixes nothing. It must be the
    FIRST statement of `main`, ahead of every print the run makes."""
    import ast
    for prog in ORCHESTRATORS:
        tree = ast.parse((PROGRAMS / prog).read_text())
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        body = [n for n in main.body
                if not (isinstance(n, ast.Expr)
                        and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str))]
        first = body[0]
        assert (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Call)
                and getattr(first.value.func, "id", "")
                == "_line_buffer_own_stream"), (
            f"{prog}: main() starts with {ast.dump(first)[:120]}")
