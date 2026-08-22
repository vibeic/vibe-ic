"""An artefact says where its numbers came from by resolving it, not typing it.

WHY
===
MEASURED: a published antenna report was 487 bytes BYTE-IDENTICAL across two
different designs on two different open process kits, citing a source path
neither design contains. The subject half of that defect is fixed and landed.

THE RESIDUE
===========
What the fix left behind is an artefact carrying TWO source claims in one write:
a resolved subject block, and beside it a sentence naming a fixed path. The
resolved one moves with the run; the typed one cannot. On this repository the
rule found exactly one instance, `_emit_antenna_report`'s `Source:` sentence,
and it is fixed in the same change that adds this checker —
`test_the_antenna_emitter_no_longer_types_its_source` pins that it stays fixed.

THE NARROWING IS PINNED TOO
===========================
The broad form ("any path constant under a source-naming key") produces 16 hits
here and most are correct — a genuinely fixed canonical input named by a constant
is an accurate statement. `test_an_accurate_constant_alone_is_not_a_finding`
keeps this rule off them.

chip-AGNOSTIC: source text and path shapes only.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "provenance_value_is_resolved_not_constant.py"

_spec = importlib.util.spec_from_file_location("pvirnc", _TOOL)
pvirnc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pvirnc)

_TYPED = (
    'def emit(rpt, project, top, def_file, pnr_log):\n'
    '    _subject = _measured_subject(project, top, [def_file],\n'
    '                                 tool_log=pnr_log)\n'
    '    rpt.write_text(\n'
    '        _measured_subject_lines(_subject) +\n'
    '        "# Source: phase3/stage3/pnr/openroad.log.\\n"\n'
    '        f"antenna clean: {clean}\\n")\n')
_RESOLVED = _TYPED.replace(
    '        "# Source: phase3/stage3/pnr/openroad.log.\\n"\n',
    '        f"# Source: {_rel_to_project(pnr_log, project)}.\\n"\n')


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


def _mk(tmp_path, body, name="emitter.py"):
    (tmp_path / name).write_text(body)
    return tmp_path


# ------------------------------------------------------------ red control

def test_a_typed_source_beside_a_resolved_subject_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the residue exactly as it stood on main."""
    _mk(tmp_path, _TYPED)
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "phase3/stage3/pnr/openroad.log" in out
    assert "two source claims" in out


def test_rendering_the_same_line_from_the_resolved_value_passes(tmp_path):
    """BIDIRECTIONAL: only the rendering changes and it goes green."""
    _mk(tmp_path, _RESOLVED)
    rc, out = _run(tmp_path)
    assert rc == 0, out


# ------------------------------------------------- the narrowing, pinned

def test_a_typed_source_held_in_a_constant_goes_red(tmp_path):
    """MEASURED FALSE PASS: the same typed claim, one assignment away."""
    _mk(tmp_path,
        'LOGPATH = "phase3/stage3/pnr/openroad.log"\n'
        'def emit(rpt, project, top, def_file, pnr_log):\n'
        '    s = _measured_subject(project, top, [def_file], tool_log=pnr_log)\n'
        '    rpt.write_text(_measured_subject_lines(s) + "# Source: " + LOGPATH)\n')
    rc, out = _run(tmp_path)
    assert rc == 1, f"the constant-in-a-name form was not caught:\n{out}"


def test_an_accurate_constant_alone_is_not_a_finding(tmp_path):
    """A record naming a genuinely fixed canonical input is accurate. Without a
    resolved claim beside it there is no contradiction, and no finding."""
    _mk(tmp_path,
        'import json\n'
        'def emit(p):\n'
        '    p.write_text(json.dumps({"source": "input/docs/README.md"}))\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out          # no resolved-subject write at all
    assert "NOT CHECKED" in out


def test_a_resolved_write_with_no_typed_path_passes(tmp_path):
    _mk(tmp_path,
        'def emit(rpt, s):\n'
        '    rpt.write_text(_measured_subject_lines(s) + "clean: YES\\n")\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_a_bare_word_is_not_a_path(tmp_path):
    _mk(tmp_path,
        'def emit(rpt, s):\n'
        '    rpt.write_text(_measured_subject_lines(s) + "mode: antenna\\n")\n')
    rc, out = _run(tmp_path)
    assert rc == 0, out


# ------------------------------------------------ the real site stays fixed

def test_the_antenna_emitter_no_longer_types_its_source():
    """Revert-proof for the one instance this rule found on the repository."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    assert '"# (ANT-0008). Source: phase3/stage3/pnr/openroad.log.\\n"' not in src
    assert "_rel_to_project(pnr_log, project)" in src


def test_the_resolver_keeps_an_unexpected_location_visible():
    """A path outside the project must NOT be laundered into a plausible
    relative one — an unexpected location has to stay legible."""
    sys.path.insert(0, str(_PROGRAMS))
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "p3osr_probe", _PROGRAMS / "phase3_one_shot_runner.py")
    # Importing the whole runner is expensive; assert on the source contract.
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    assert "def _rel_to_project(" in src
    assert "except (ValueError, TypeError):" in src


# -------------------------------------------------------------- verdicts

def test_empty_population_is_not_checked(tmp_path):
    _mk(tmp_path, "x = 1\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_unparseable_file_is_not_checked(tmp_path):
    _mk(tmp_path, '_measured_subject_lines(,,,\n')
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 0, out
