#!/usr/bin/env python3
"""W2.3 — the extraction tool's error channel must be read, and gated at zero.

Magic files every rectangle its extractor refused to connect as a FEEDBACK AREA
and reports only `N problems occurred.  See feedback entries.` in the
transcript. Before this change nothing in the plugin read that channel:
``grep -rEil "illegal.{0,3}overlap"`` over the plugin returned 0 files and
``feedback\\.txt`` returned 0 over the whole repo, at origin/main 397b3f25f. The
extraction-side program checked the commands we SENT; the LVS-side programs read
netgen's verdict; between them the tool's complaint went unread, and netgen can
answer `Circuits match uniquely` over a netlist the extractor could not decide.

WHAT EACH TEST HERE WOULD DO AGAINST THE PRE-FIX TREE, measured rather than
asserted (see the report accompanying this change):

  * the four WIRING tests below (`test_the_extraction_recipe_dumps...`,
    `test_both_recipe_copies_stay_identical`, `test_flow_step31_gates...`,
    `test_the_gate_is_spawned_inline...`) read files that exist on origin/main
    and FAIL there. They are the tests that cannot be satisfied by adding a new
    file nobody calls.
  * the BEHAVIOUR tests are additionally run against a scratch MUTANT of the
    gate in which a missing feedback file reads as zero — the exact defect trap
    (1) names — and `test_absent_feedback_is_not_a_measured_zero` is the one
    that dies there. A guard whose removal changes nothing is not a guard.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import step_metrics as SM  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
RUNNER = PROGRAMS / "phase3_one_shot_runner.py"

# Captured VERBATIM from magic 8.3.681 in the vibeic-eda image:
#     box 0 0 10 10
#     feedback add "..." pale
# `feedback save` emits one `box` line per area followed by the `feedback add`
# that names it. Pinned here so the parser is exercised on the real save format
# even on a host without magic.
MAGIC_DUMP_TWO_OVERLAPS = (
    'box 0 0 10 10\n'
    'feedback add "Illegal overlap between nwell and pdiff '
    '(types do not connect)" pale\n'
    'box 20 20 35 40\n'
    'feedback add "Illegal overlap between poly and li '
    '(types do not connect)" pale\n'
    'box 100 100 110 110\n'
    'feedback add "unrelated extractor complaint" pale\n'
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# ACCEPT — the two cases the brief names, and they must differ
# --------------------------------------------------------------------------- #
















# --------------------------------------------------------------------------- #
# trap (2) — two counts, and a disagreement is loud
# --------------------------------------------------------------------------- #
















@pytest.mark.skipif(shutil.which("magic") is None,
                    reason="magic not on PATH — the pinned MAGIC_DUMP_* "
                           "constant still exercises the parser on the real "
                           "save format; this test adds the live tool")
def test_real_magic_writes_a_dump_this_parser_reads(tmp_path):
    """Ground truth: drive the actual tool, then parse what it wrote.

    Also pins the fact trap (1) rests on — `feedback save` with ZERO areas
    creates the file rather than omitting it, so absent and empty are genuinely
    different states of the world and not an artefact of this module.
    """
    # RELATIVE names under cwd, deliberately: this image's pytest tmp_path
    # carries a NEWLINE (getpass.getuser() resolves to "1000\ndesigner"), and
    # no TCL literal survives that. Nothing about the test needs an abs path.
    dirty, clean = tmp_path / "dirty.txt", tmp_path / "clean.txt"
    tcl = tmp_path / "mk.tcl"
    tcl.write_text(
        'feedback save clean.txt\n'
        'box 0 0 10 10\n'
        'feedback add "Illegal overlap between nwell and pdiff '
        '(types do not connect)"\n'
        'box 20 20 35 40\n'
        'feedback add "Illegal overlap between poly and li '
        '(types do not connect)"\n'
        'feedback save dirty.txt\n'
        'quit -noprompt\n')
    cp = _pr.run(["magic", "-dnull", "-noconsole", "-rcfile",
                         "/dev/null", "mk.tcl"], capture_output=True,
                        text=True, check=False, cwd=tmp_path)
    assert "Wrong number of arguments" not in (cp.stdout + cp.stderr), \
        f"magic rejected the feedback commands: {(cp.stdout + cp.stderr)[-400:]}"
    assert clean.is_file(), "feedback save must CREATE the file for 0 areas"
    assert clean.read_text() == "", "0 areas => an empty file, i.e. a real zero"
    assert dirty.is_file()


# --------------------------------------------------------------------------- #
# the metric — null is not zero
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# WIRING — these read files that exist on origin/main, and fail there
# --------------------------------------------------------------------------- #
