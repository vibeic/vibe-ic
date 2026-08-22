#!/usr/bin/env python3
"""A redirected orchestrator log reported the phases in the wrong ORDER.

Python block-buffers stdout when it is not a tty. The orchestrator's phase
banners therefore sat in a buffer until exit, while the child runners — which
inherit the same fd — wrote through it as they went. Under the redirect every
real run uses (`> run.log 2>&1`) the file recorded ALL child output first and
ALL banners last.

MEASURED (sha256 x sky130A, run1.log): `=== PHASE 2 ===` was followed
immediately by the `DONE` banner with zero phase-2 output between them, which
reads as "phase 2 died instantly". Phase 2 had run its full 3-iteration ECO loop
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

#: Bound for BOTH launches below. NOT a round number picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed.
#: The landed values were 120 (the redirect probe) and 180 (the import probe).
#: MEASURED here: the redirect probe is a five-line parent around two
#: `print()`-only children and runs 0.06 s; the import probe imports one
#: orchestrator module and runs 0.16 s. 60 s is ~370x the slower of the two.
_PROBE_TIMEOUT_S = 60


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
    with log.open("w") as fh:
        subprocess.run([sys.executable, str(parent)], stdout=fh,
                       stderr=subprocess.STDOUT, timeout=_PROBE_TIMEOUT_S)
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
        with log.open("w") as fh:
            subprocess.run([sys.executable, str(probe)], stdout=fh,
                           stderr=subprocess.STDOUT, timeout=_PROBE_TIMEOUT_S)
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
