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


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------------ unit

def test_skip_before_the_command_is_accepted():
    assert prrap.inspect_remedy(
        "docker run -d --init --name c ghcr.io/vibeic/vibeic-eda:0.3.16 "
        "--skip sleep infinity") is None


def test_command_before_skip_is_refused():
    why = prrap.inspect_remedy(
        "docker run -d --init --name c ghcr.io/vibeic/vibeic-eda:0.3.16 "
        "sleep infinity")
    assert why is not None
    assert "Unexpected option" in why


def test_a_line_with_no_image_is_not_this_population():
    assert prrap.inspect_remedy("docker run hello-world") is None


# -------------------------------------------------------- red control

def test_bad_ordering_in_a_printed_remedy_goes_red(tmp_path):
    """Reintroduce the defect: a refusal that prints the swallowed form."""
    (tmp_path / "gate.py").write_text(
        'def refuse():\n'
        '    print("Remedy: docker run -d --init --name c "\n'
        '          "ghcr.io/vibeic/vibeic-eda:0.3.16 bash -lc \'yosys -V\'")\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "Unexpected option" in out


def test_the_same_remedy_with_skip_first_passes(tmp_path):
    """BIDIRECTIONAL: the corrected form of the very same line must go green."""
    (tmp_path / "gate.py").write_text(
        'def refuse():\n'
        '    print("Remedy: docker run -d --init --name c "\n'
        '          "ghcr.io/vibeic/vibeic-eda:0.3.16 --skip bash -lc \'yosys -V\'")\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_a_remedy_concatenated_from_a_constant_goes_red(tmp_path):
    """MEASURED FALSE PASS, now pinned.

    This scan reported PASS on a swallowed remedy written the way a real refusal
    writes one, with the image reference kept in a constant:

        IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.16"
        print("Remedy: docker run ... " + IMAGE + " bash -lc yosys")
    """
    (tmp_path / "gate.py").write_text(
        'IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.16"\n'
        'def refuse():\n'
        '    print("Remedy: docker run -d --init --name c " + IMAGE +\n'
        '          " bash -lc yosys")\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the concatenated form was not caught:\n{out}"
    assert "Unexpected option" in out


def test_the_same_concatenated_remedy_with_skip_first_passes(tmp_path):
    """BIDIRECTIONAL, and it also proves the fold does not glue tokens that were
    never adjacent — `--skip` really is read as the token after the image."""
    (tmp_path / "gate.py").write_text(
        'IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.16"\n'
        'def refuse():\n'
        '    print("Remedy: docker run -d --init --name c " + IMAGE +\n'
        '          " --skip bash -lc yosys")\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_a_returned_remedy_is_in_the_population(tmp_path):
    (tmp_path / "gate.py").write_text(
        'def remedy():\n'
        '    return "docker run --name c vibeic-eda:latest sleep infinity"\n')
    rc, out = _run(tmp_path)
    assert rc == 1, out


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

def test_empty_population_is_not_checked(tmp_path):
    (tmp_path / "u.py").write_text("x = 1\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_a_comment_is_not_a_remedy(tmp_path):
    (tmp_path / "g.py").write_text(
        '# never print: docker run vibeic-eda:latest bash\n'
        'x = 1\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out          # no PRINTED remedy at all -> not checked


def test_unparseable_file_is_not_checked(tmp_path):
    (tmp_path / "bad.py").write_text('print("docker run" ,,,\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 0, out
