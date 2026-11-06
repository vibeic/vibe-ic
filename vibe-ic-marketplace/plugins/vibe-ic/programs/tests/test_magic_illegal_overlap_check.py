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
def _project(tmp_path: Path, *, feedback: str = None,
             extraction: bool = True, transcript: str = None) -> Path:
    """A project root with an extraction, and optionally a feedback dump.

    `feedback=None` means the dump is ABSENT; `feedback=""` means it exists and
    is EMPTY, which is what `feedback save` writes for zero areas. Those two are
    the whole point of trap (1) and the fixture keeps them distinguishable.
    """
    proj = tmp_path / "proj"
    return proj


def _run(proj: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "magic_illegal_overlap_check.py"),
         str(proj), *extra],
        capture_output=True, text=True, check=False)


def _rules(report: dict) -> list:
    return [f["rule"] for f in report["findings"]]


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


def test_the_metric_goes_through_the_repo_channel_and_declares_a_direction(
        tmp_path):
    proj = _project(tmp_path, feedback=MAGIC_DUMP_TWO_OVERLAPS)
    cp = _run(proj, "--json", str(tmp_path / "r.json"))
    metrics = json.loads((proj / "reports/metrics/31.json").read_text())
    key = "31__drv__magic_illegal_overlap__violation_count"
    assert metrics[key] == 2
    assert SM.direction_for(key) == "lower", \
        "a rise in this count must grade as `worse`, not `undeclared`"
    assert SM.key_defect(key) is None
    assert SM.conformance_defects(proj) == []


# --------------------------------------------------------------------------- #
# WIRING — these read files that exist on origin/main, and fail there
# --------------------------------------------------------------------------- #


def test_the_extraction_recipe_dumps_the_feedback_channel():
    """A channel that is never dumped cannot be read. FAILS on origin/main."""
    import phase3_one_shot_runner as R
    tcl = R._MAGIC_EXT2SPICE_TCL
    assert "feedback save $env(FEEDBACK_OUT)" in tcl, \
        "the recipe must dump magic's feedback areas, or the gate has no input"
    assert tcl.index("extract all") < tcl.index("feedback save"), \
        "the dump must follow the extract that generates the areas"
    assert tcl.index("feedback save") < tcl.index("quit"), \
        "the dump must precede quit"
    runner = RUNNER.read_text()
    assert "FEEDBACK_OUT={_to_container_path(str(feedback_out), container)}" \
        in runner, "the recipe's env var must be exported by the invocation"




def test_flow_step31_gates_illegal_overlap_before_lvs():
    """The clause exists AND sits before both LVS clauses. FAILS on main."""
    import yaml
    doc = yaml.safe_load(FLOW.read_text())
    step = next(s for s in doc["steps"] if s["id"] == 31)
    clauses = [c["program_exit_zero"] for c in step["gate"]["all_of"]
               if "program_exit_zero" in c]
    idx = {name: i for i, c in enumerate(clauses)
           for name in [c.split()[0]] }
    assert "magic_illegal_overlap_check" in idx, \
        "step 31 must declare the illegal-overlap gate"
    assert idx["magic_illegal_overlap_check"] < idx["lvs_report_check"]
    assert idx["magic_illegal_overlap_check"] < idx["lvs_signoff_guard"]




def test_the_gate_is_spawned_inline_and_blocks_before_netgen():
    """Not merely declared: the runner spawns it and stops on its status.

    Asserted on the SOURCE ORDER inside `_run_extraction_lvs`, because "between
    extraction and LVS" is a claim about position, not just presence.
    FAILS on origin/main.
    """
    src = RUNNER.read_text()
    body = src[src.index("def _run_extraction_lvs("):]
    body = body[:body.index("\ndef ", 10)]
    assert "_run_illegal_overlap_gate(" in body
    assert "if _mio_rc != 0:" in body, "the exit status must reach a decision"
    assert body.index("magic -dnull") < body.index("_run_illegal_overlap_gate("), \
        "the gate must run AFTER the extraction"
    gate_at = body.index("_run_illegal_overlap_gate(")
    # Anchor on the two places netgen is actually INVOKED, not on the word:
    # `netgen_setup` is a parameter in this function's own signature, and an
    # ordering test that matched it would pass on any arrangement whatsoever.
    for invocation in ("_try_power_aware_lvs(", 'netgen -batch lvs'):
        assert gate_at < body.index(invocation), (
            f"the gate must run BEFORE {invocation!r} — a compare over an "
            f"undecided netlist is not evidence about the design")
    import ast
    function = next(node for node in ast.parse(src).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_run_illegal_overlap_gate")
    helper = ast.get_source_segment(src, function)
    assert "magic_illegal_overlap_check.py" in helper
    assert "subprocess.run(" in helper
    assert "_verify_runtime_command(cmd)" in helper
    assert "timeout=_ILLEGAL_OVERLAP_GATE_TIMEOUT" in helper




def test_the_runner_helper_fails_closed_on_a_dirty_extraction(tmp_path):
    import phase3_one_shot_runner as R
    proj = _project(tmp_path, feedback=MAGIC_DUMP_TWO_OVERLAPS)
    rc, detail = R._run_illegal_overlap_gate(
        proj, proj / "reports/phase3/magic_illegal_overlap.json")
    assert rc == 1, "a dirty extraction must not clear the inline gate"
    assert "MAGIC_ILLEGAL_OVERLAP" in detail
    rc2, _ = R._run_illegal_overlap_gate(
        _project(tmp_path / "b", feedback=""),
        tmp_path / "b" / "out.json")
    assert rc2 == 0, "a measured-clean extraction must pass through"
