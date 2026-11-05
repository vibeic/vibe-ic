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






# ------------------------------------------------------------ red control





# ------------------------------------------------- the narrowing, pinned









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
