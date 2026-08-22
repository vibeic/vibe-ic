"""One flow-declared path, one writer.

WHY
===
MEASURED: a precheck delegated to the same checker with a reduced argument set
and wrote its result at the flow's canonical evidence path:

    the declaring step's write   811 bytes, 2 findings, sign-off scope populated
    the delegate's write         308 bytes, 1 finding, no scope keys at all

A release tier graded the second. Which writer wins is execution order, so the
same tree can grade either way.

THE GUARD THE RECORD ASKED FOR IS TESTED, NOT ASSUMED
=====================================================
"Guard the rule with a negative control asserting the historical paths are still
recognised as flow-owned, so the check cannot pass over an empty set."
`test_the_known_flow_paths_are_still_recognised_as_flow_owned` does exactly that,
and `test_an_empty_declaration_set_is_not_checked` proves the empty case refuses
rather than passes.

chip-AGNOSTIC: flow declarations and Python writes. No design or PDK literal.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "only_the_declaring_step_writes_its_output.py"
_REPO = _PROGRAMS.parents[3]

_spec = importlib.util.spec_from_file_location("otdswio", _TOOL)
otdswio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(otdswio)

_FLOW_REL = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
_PROG_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"


def _tree(tmp_path, flow_yaml, modules):
    flow = tmp_path / _FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(flow_yaml)
    progs = tmp_path / _PROG_REL
    progs.mkdir(parents=True, exist_ok=True)
    for name, body in modules.items():
        (progs / name).write_text(body)
    return tmp_path


_ONE_STEP = (
    "steps:\n"
    "  - id: 18\n"
    "    required_outputs:\n"
    "      - reports/coverage.json\n")
_TWO_STEPS = (
    "steps:\n"
    "  - id: 18\n"
    "    required_outputs:\n"
    "      - reports/coverage.json\n"
    "  - id: 19\n"
    "    required_outputs:\n"
    "      - reports/coverage.json\n")

_WRITER = ('from pathlib import Path\n'
           'def emit(project):\n'
           '    p = project / "reports" / "coverage.json"\n'
           '    p.write_text("{}")\n')


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------ red control

def test_two_writers_of_one_declared_output_go_red(tmp_path):
    """THE NEGATIVE CONTROL: the defect exactly as measured."""
    root = _tree(tmp_path, _ONE_STEP,
                 {"checker.py": _WRITER, "runner.py": _WRITER})
    rc, out = _run(root)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "reports/coverage.json" in out
    assert "checker.py" in out and "runner.py" in out
    assert "execution order" in out


def test_one_writer_passes(tmp_path):
    """BIDIRECTIONAL: remove the second writer and the same tree goes green."""
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    rc, out = _run(root)
    assert rc == 0, out


def test_the_flow_may_declare_two_producers(tmp_path):
    """When the flow itself declares two steps, this rule does not overrule it."""
    root = _tree(tmp_path, _TWO_STEPS,
                 {"checker.py": _WRITER, "runner.py": _WRITER})
    rc, out = _run(root)
    assert rc == 0, out
    assert "EXEMPT" in out


def test_a_different_basename_is_the_remedy(tmp_path):
    """A non-declaring writer must change the BASENAME, not just the directory."""
    private_dir_only = _WRITER.replace('"reports" / "coverage.json"',
                                       '"private" / "coverage.json"')
    root = _tree(tmp_path, _ONE_STEP,
                 {"checker.py": _WRITER, "runner.py": private_dir_only})
    rc, out = _run(root)
    assert rc == 1, ("a private directory alone must NOT satisfy the rule — "
                     "discovery is by recursive glob\n" + out)
    renamed = _WRITER.replace('"coverage.json"', '"coverage_private.json"')
    root2 = _tree(tmp_path / "b", _ONE_STEP,
                  {"checker.py": _WRITER, "runner.py": renamed})
    rc2, out2 = _run(root2)
    assert rc2 == 0, out2


# ------------------------------------------------------- reads are not writes

def test_a_shell_second_writer_goes_red(tmp_path):
    """MEASURED FALSE PASS: the scan was Python-only, so a shell redirection
    onto the same flow-declared path sat beside a Python writer unseen. This
    tree drives real work from tools/*.sh, so the blind spot was not
    hypothetical."""
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    (tmp_path / _PROG_REL / "runner.sh").write_text(
        '#!/bin/bash\n'
        'echo "{}" > "$PROJECT/reports/coverage.json"\n')
    rc, out = _run(root)
    assert rc == 1, f"the shell writer was not seen:\n{out}"
    assert "runner.sh" in out


def test_a_shell_read_is_not_a_writer(tmp_path):
    """BIDIRECTIONAL: reading the path from shell must not count."""
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    (tmp_path / _PROG_REL / "consumer.sh").write_text(
        '#!/bin/bash\n'
        'cat "$PROJECT/reports/coverage.json"\n')
    rc, out = _run(root)
    assert rc == 0, out


def test_a_shell_comment_is_not_a_writer(tmp_path):
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    (tmp_path / _PROG_REL / "note.sh").write_text(
        '#!/bin/bash\n'
        '# never do: echo x > reports/coverage.json\n'
        'true\n')
    rc, out = _run(root)
    assert rc == 0, out


def test_a_shutil_copy_second_writer_goes_red(tmp_path):
    """MEASURED GAP: the enumeration was write_text / write_bytes / open(w)."""
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    (tmp_path / _PROG_REL / "runner.py").write_text(
        'import shutil\n'
        'def emit(project, src):\n'
        '    dst = project / "reports" / "coverage.json"\n'
        '    shutil.copy(src, dst)\n')
    rc, out = _run(root)
    assert rc == 1, f"a shutil.copy writer was not seen:\n{out}"


def test_an_os_replace_second_writer_goes_red(tmp_path):
    """THE ONE THAT MATTERS. `os.replace` is this repository's OWN sanctioned
    atomic-write idiom (`_atomic_output.py`): a declared output is supposed to
    arrive by temp-file-then-rename so it only exists under its final name if the
    step completed. The scan could not see it, so the MORE CORRECTLY a step wrote
    its output, the more invisible it was to this gate."""
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    (tmp_path / _PROG_REL / "runner.py").write_text(
        'import os\n'
        'def emit(project, tmp):\n'
        '    dst = project / "reports" / "coverage.json"\n'
        '    os.replace(tmp, dst)\n')
    rc, out = _run(root)
    assert rc == 1, f"an os.replace writer was not seen:\n{out}"


def test_a_dest_call_to_an_undeclared_path_is_not_a_writer(tmp_path):
    """BIDIRECTIONAL: widening the enumeration must not make every copy a hit."""
    root = _tree(tmp_path, _ONE_STEP, {"checker.py": _WRITER})
    (tmp_path / _PROG_REL / "runner.py").write_text(
        'import shutil\n'
        'def emit(project, src):\n'
        '    shutil.copy(src, project / "scratch" / "other.json")\n')
    rc, out = _run(root)
    assert rc == 0, out


def test_a_read_is_not_a_writer(tmp_path):
    reader = ('from pathlib import Path\n'
              'def load(project):\n'
              '    p = project / "reports" / "coverage.json"\n'
              '    return p.read_text()\n')
    root = _tree(tmp_path, _ONE_STEP,
                 {"checker.py": _WRITER, "consumer.py": reader})
    rc, out = _run(root)
    assert rc == 0, out


def test_open_without_a_write_mode_is_not_a_writer(tmp_path):
    reader = ('from pathlib import Path\n'
              'def load(project):\n'
              '    p = project / "reports" / "coverage.json"\n'
              '    with p.open() as fh:\n'
              '        return fh.read()\n')
    root = _tree(tmp_path, _ONE_STEP,
                 {"checker.py": _WRITER, "consumer.py": reader})
    rc, out = _run(root)
    assert rc == 0, out


def test_open_with_a_write_mode_is_a_writer(tmp_path):
    writer = ('from pathlib import Path\n'
              'def emit(project):\n'
              '    p = project / "reports" / "coverage.json"\n'
              '    with p.open("w") as fh:\n'
              '        fh.write("{}")\n')
    root = _tree(tmp_path, _ONE_STEP,
                 {"checker.py": _WRITER, "runner.py": writer})
    rc, out = _run(root)
    assert rc == 1, out


# --------------------------- the guard: it cannot pass over an empty set

def test_an_empty_declaration_set_is_not_checked(tmp_path):
    root = _tree(tmp_path, "steps: []\n", {"checker.py": _WRITER})
    rc, out = _run(root)
    assert rc == 2, out
    assert "not a pass" in out.lower()


def test_no_identifiable_writer_is_not_checked(tmp_path):
    root = _tree(tmp_path, _ONE_STEP, {"unrelated.py": "x = 1\n"})
    rc, out = _run(root)
    assert rc == 2, out
    assert "not a pass" in out.lower()


def test_a_missing_flow_is_not_checked(tmp_path):
    progs = tmp_path / _PROG_REL
    progs.mkdir(parents=True)
    (progs / "checker.py").write_text(_WRITER)
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


@pytest.mark.parametrize("known", [
    "reports/phase3/antenna.rpt",
    "phase3/stage3/sta/post_route_timing.rpt",
    "reports/spare_cell_coverage.json",
])
def test_the_known_flow_paths_are_still_recognised_as_flow_owned(known):
    """THE GUARD THE RECORD ASKED FOR. If a flow rename or a schema change
    empties the declaration set, this fails instead of passing over nothing."""
    declared = otdswio.declared_outputs(_REPO / otdswio.FLOW_REL)
    assert known in declared, (
        f"{known} is no longer recognised as flow-owned — this gate's "
        f"population has silently shrunk")
    assert declared[known], "a declared path with no declaring step"


def test_the_real_flow_declares_a_substantial_population():
    declared = otdswio.declared_outputs(_REPO / otdswio.FLOW_REL)
    assert len(declared) > 100, len(declared)


# -------------------------------------------------------------- verdicts

def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out
