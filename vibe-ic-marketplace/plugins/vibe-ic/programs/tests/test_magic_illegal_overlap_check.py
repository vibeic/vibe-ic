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

import magic_illegal_overlap_check as M  # noqa: E402
import step_metrics as SM  # noqa: E402

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
RUNNER = PROGRAMS / "phase3_one_shot_runner.py"
PA_EXTRACT = PROGRAMS / "lvs_power_aware_extract_tcl.py"

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
             extraction: bool = True) -> Path:
    """A project root with an extraction, and optionally a feedback dump.

    `feedback=None` means the dump is ABSENT; `feedback=""` means it exists and
    is EMPTY, which is what `feedback save` writes for zero areas. Those two are
    the whole point of trap (1) and the fixture keeps them distinguishable.
    """
    proj = tmp_path / "proj"
    ext = proj / M.EXTRACTED_REL
    ext.mkdir(parents=True)
    if extraction:
        (ext / "ext2spice_top.tcl").write_text("extract all\next2spice lvs\n")
        (ext / "ext2spice.log").write_text("MAGIC_EXT2SPICE_DONE top.sp\n")
        (ext / "top_extracted.sp").write_text(".subckt top a b\n.ends\n")
    if feedback is not None:
        (ext / M.FEEDBACK_NAMES[0]).write_text(feedback)
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
def test_an_extraction_with_illegal_overlaps_fails_the_gate(tmp_path):
    proj = _project(tmp_path, feedback=MAGIC_DUMP_TWO_OVERLAPS)
    r = M.check(proj)
    assert r["passed"] is False and r["skipped"] is False
    assert "MAGIC_ILLEGAL_OVERLAP" in _rules(r)
    assert r["counts"]["gate_count"] == 2
    assert M._ve.exit_code(r["passed"], r["skipped"]) == M._ve.RC_FAIL


def test_absent_feedback_is_not_a_measured_zero(tmp_path):
    """THE trap-(1) test. An extraction ran; its error channel is not there.

    This is the one that dies against a mutant which reads a missing file as 0,
    and it is the reason the gate cannot be satisfied by looking away.
    """
    proj = _project(tmp_path, feedback=None)
    r = M.check(proj)
    assert r["passed"] is False, "a channel that was never dumped is not clean"
    assert r["skipped"] is False, "an extraction ran; this is not vacuous"
    assert "EXTRACTION_FEEDBACK_ABSENT" in _rules(r)
    assert M._ve.exit_code(r["passed"], r["skipped"]) == M._ve.RC_FAIL


def test_the_two_failures_carry_different_rules_and_different_reasons(tmp_path):
    """Both FAIL, and a reader can tell WHICH failure it is looking at."""
    dirty = M.check(_project(tmp_path / "a",
                             feedback=MAGIC_DUMP_TWO_OVERLAPS))
    absent = M.check(_project(tmp_path / "b", feedback=None))
    assert dirty["passed"] is False and absent["passed"] is False
    assert _rules(dirty)[0] != _rules(absent)[0]
    assert dirty["reason"] != absent["reason"]
    assert "NOT DETERMINED" in absent["reason"]
    assert "NOT DETERMINED" not in dirty["reason"]


def test_an_empty_dump_after_a_real_extraction_is_a_measured_zero(tmp_path):
    """`feedback save` writes 0 bytes for zero areas — that IS the measurement."""
    proj = _project(tmp_path, feedback="")
    r = M.check(proj)
    assert r["passed"] is True and r["skipped"] is False
    assert r["counts"]["gate_count"] == 0
    assert r["counts"]["determined"] is True
    assert M._ve.exit_code(r["passed"], r["skipped"]) == M._ve.RC_PASS


def test_no_extraction_at_all_is_disclosed_vacuous_and_says_it_is_not_a_pass(
        tmp_path):
    proj = _project(tmp_path, feedback=None, extraction=False)
    r = M.check(proj)
    assert r["skipped"] is True
    assert r["summary"]["reason"] == "no_extraction_in_scope"
    assert "NOT" in r["reason"] and "clean" in r["reason"]
    assert M._ve.exit_code(r["passed"], r["skipped"]) == M._ve.RC_VACUOUS
    cp = _run(proj, "--no-metrics")
    assert cp.returncode == M._ve.RC_VACUOUS
    assert M._ve.VACUOUS_STDOUT_SENTINEL in (cp.stdout + cp.stderr)


def test_a_published_lvs_verdict_is_itself_extraction_evidence(tmp_path):
    """The one way rc 2 could be manufactured, closed.

    Delete the extraction directory and the gate would have "nothing to be
    about" — a disclosed vacuous pass — while `reports/phase3/lvs.rpt` still
    certifies a unique match. The implication runs one way: an LVS report means
    a netlist was compared, that netlist came from an extraction, and that
    extraction had a feedback channel.
    """
    for rel in M.LVS_VERDICT_RELS:
        proj = tmp_path / rel.replace("/", "_")
        (proj / "reports/phase3").mkdir(parents=True)
        (proj / rel).write_text("Final result: Circuits match uniquely.\n")
        assert not (proj / M.EXTRACTED_REL).exists()
        r = M.check(proj)
        assert r["skipped"] is False, f"{rel} must defeat the vacuous route"
        assert r["passed"] is False
        assert "EXTRACTION_FEEDBACK_ABSENT" in _rules(r)
        assert rel in r["extraction_evidence"]


def test_a_project_with_neither_an_extraction_nor_an_lvs_verdict_is_vacuous(
        tmp_path):
    """The evidence rule must still leave a genuine no-run case rc 2.

    Without this, "evidence" could creep until every empty directory FAILs and
    the gate stops distinguishing "nothing ran" from "something ran and hid".
    """
    proj = tmp_path / "empty"
    (proj / "reports/phase3").mkdir(parents=True)
    (proj / "reports/phase3/drc_signoff.rpt").write_text("0 total errors\n")
    r = M.check(proj)
    assert r["skipped"] is True
    assert r["extraction_evidence"] == []


# --------------------------------------------------------------------------- #
# trap (2) — two counts, and a disagreement is loud
# --------------------------------------------------------------------------- #
def test_the_two_counts_disagree_loudly_and_the_larger_decides(tmp_path):
    """A marker the structural view cannot see must not read as clean.

    The structural arm is a SUBSET of the raw text, so it can only ever
    undercount. A gate reading it alone would report 0 over this file.
    """
    proj = _project(
        tmp_path,
        feedback="Illegal overlap between nwell and pdiff "
                 "(types do not connect)\n")
    r = M.check(proj)
    assert r["counts"]["string_count"] == 1
    assert r["counts"]["structural_count"] == 0
    assert r["counts"]["record_count"] == 0
    assert "FEEDBACK_COUNT_DISAGREEMENT" in _rules(r)
    assert r["counts"]["gate_count"] == 1, "the LARGER count decides"
    assert r["passed"] is False


def test_a_clean_pass_over_a_partly_unparsed_dump_says_so(tmp_path):
    proj = _project(tmp_path,
                    feedback='box 0 0 5 5\nfeedback add "ordinary" pale\n'
                             '<<< garbage from a crashed dump\n')
    r = M.check(proj)
    assert r["passed"] is True
    assert "FEEDBACK_PARTIALLY_UNPARSED" in _rules(r)


def test_the_parser_reads_magics_real_save_format(tmp_path):
    records, defects = M.parse_feedback(MAGIC_DUMP_TWO_OVERLAPS)
    assert len(records) == 3 and defects == []
    assert [r.box for r in records] == [(0, 0, 10, 10), (20, 20, 35, 40),
                                        (100, 100, 110, 110)]
    assert all(r.style == "pale" for r in records)
    assert sum(M.MARKER in r.message for r in records) == 2


def test_a_feedback_add_with_no_box_is_recorded_as_a_structural_defect():
    _, defects = M.parse_feedback(
        'feedback add "Illegal overlap between a and b" pale\n')
    assert any("no bounding box" in d for d in defects)


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
    cp = subprocess.run(["magic", "-dnull", "-noconsole", "-rcfile",
                         "/dev/null", "mk.tcl"], capture_output=True,
                        text=True, check=False, cwd=tmp_path, timeout=180)
    assert "Wrong number of arguments" not in (cp.stdout + cp.stderr), \
        f"magic rejected the feedback commands: {(cp.stdout + cp.stderr)[-400:]}"
    assert clean.is_file(), "feedback save must CREATE the file for 0 areas"
    assert clean.read_text() == "", "0 areas => an empty file, i.e. a real zero"
    assert dirty.is_file()
    records, defects = M.parse_feedback(dirty.read_text())
    assert defects == [], f"parser rejected real magic output: {defects}"
    assert sum(M.MARKER in r.message for r in records) == 2
    assert M.count_marker(dirty.read_text()) == 2


# --------------------------------------------------------------------------- #
# the metric — null is not zero
# --------------------------------------------------------------------------- #
def test_a_not_determined_count_publishes_null_never_zero(tmp_path):
    proj = _project(tmp_path, feedback=None)
    r = M.check(proj)
    m = r["metrics"]
    key = "31__drv__magic_illegal_overlap__violation_count"
    assert m[key] is None, "an unmeasured count must never render as 0"
    assert m["31__drv__magic_illegal_overlap__determined"] is False


def test_the_metric_goes_through_the_repo_channel_and_declares_a_direction(
        tmp_path):
    proj = _project(tmp_path, feedback=MAGIC_DUMP_TWO_OVERLAPS)
    cp = _run(proj, "--json", str(tmp_path / "r.json"))
    assert cp.returncode == M._ve.RC_FAIL
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
def _recipe(text: str) -> str:
    i = text.index('_MAGIC_EXT2SPICE_TCL = """\\\n') if \
        '_MAGIC_EXT2SPICE_TCL = """\\\n' in text else \
        text.index('_DEFAULT_BASE_TCL = """\\\n')
    return text[i:text.index('"""', i + 40)]


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


def test_both_recipe_copies_stay_identical():
    """The two copies are pinned identical by contract; drift breaks the CLI."""
    import phase3_one_shot_runner as R
    import lvs_power_aware_extract_tcl as E
    assert R._MAGIC_EXT2SPICE_TCL == E._DEFAULT_BASE_TCL


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
    helper = src[src.index("def _run_illegal_overlap_gate("):]
    assert "magic_illegal_overlap_check.py" in helper[:1600]
    assert "subprocess.run(" in helper[:1600]


def test_the_gate_declares_the_enforcement_it_is_wired_for():
    """`ENFORCEMENT: blocking` must OPEN a line — a mention in prose is not one."""
    lines = M.__doc__.splitlines()
    assert any(l.startswith("ENFORCEMENT: blocking") for l in lines)


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


def test_the_threshold_is_zero_and_one_overlap_is_enough(tmp_path):
    assert M.THRESHOLD == 0
    proj = _project(
        tmp_path,
        feedback='box 1 1 2 2\nfeedback add "Illegal overlap between a and b '
                 '(types do not connect)" pale\n')
    r = M.check(proj)
    assert r["counts"]["gate_count"] == 1 and r["passed"] is False
