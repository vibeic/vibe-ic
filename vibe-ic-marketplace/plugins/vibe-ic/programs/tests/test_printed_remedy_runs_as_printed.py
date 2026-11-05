"""A refusal that prints "run this" must print something that runs.

WHY
===
The composed EDA image has an entry point that parses the arguments after the
image reference. `--skip` must reach it BEFORE the command or the entry point
takes the command for one of its own options:

    docker logs: [ERROR] Unexpected option "sleep"

recorded verbatim at `container_image_provenance.py:145`. The command never
runs, the exit is non-zero, and a reader following the remedy exactly concludes
the refusal is broken.

EXECUTED, NOT ASSERTED ON ITS TEXT
==================================
One case below RUNS a command through a stand-in entry point that behaves the
way the image's does, and asserts BOTH a zero exit AND a marker in the output.
A zero exit alone is the signature of an entry point that swallowed the command,
which is the failure being guarded — so the marker is the assertion that matters.
The paired negative control proves the stand-in can fail.

chip-AGNOSTIC: argument ordering and string scanning. No design or PDK literal.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "printed_remedy_runs_as_printed.py"

_spec = importlib.util.spec_from_file_location("prrap", _TOOL)
prrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prrap)




# ------------------------------------------------------------------ unit







# -------------------------------------------------------- red control











# ------------------------------------- executed, with its negative control

def _entrypoint(tmp_path):
    """A stand-in that behaves the way the image's entry point does: it parses
    what follows and refuses an unexpected option instead of running it."""
    ep = tmp_path / "entrypoint.py"
    ep.write_text(
        'import subprocess, sys\n'
        'argv = sys.argv[1:]\n'
        'if not argv or argv[0] != "--skip":\n'
        '    print(f\'[ERROR] Unexpected option "{argv[0] if argv else ""}"\')\n'
        '    raise SystemExit(1)\n'
        'raise SystemExit(subprocess.run(argv[1:]).returncode)\n')
    return ep


def test_the_printed_form_actually_runs(tmp_path):
    """Execute the remedy shape, assert BOTH rc 0 AND the marker."""
    ep = _entrypoint(tmp_path)
    cp = subprocess.run(
        [sys.executable, str(ep), "--skip", sys.executable, "-c",
         "print('VIBEIC_MARKER_OK')"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "VIBEIC_MARKER_OK" in cp.stdout, (
        "zero exit with no marker is the signature of an entry point that "
        "swallowed the command")


def test_the_swallowed_form_fails(tmp_path):
    """THE NEGATIVE CONTROL for the executed case. Without it the test above
    would pass against a stand-in that has no entry point at all."""
    ep = _entrypoint(tmp_path)
    cp = subprocess.run(
        [sys.executable, str(ep), sys.executable, "-c",
         "print('VIBEIC_MARKER_OK')"], capture_output=True, text=True)
    assert cp.returncode != 0
    assert "VIBEIC_MARKER_OK" not in cp.stdout
    assert "Unexpected option" in cp.stdout


# ------------------------------------------------------------ verdicts
