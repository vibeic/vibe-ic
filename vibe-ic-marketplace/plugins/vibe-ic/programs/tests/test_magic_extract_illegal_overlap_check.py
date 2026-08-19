#!/usr/bin/env python3
"""Tests for magic_extract_illegal_overlap_check.py — the extractor's error channel.

WHAT THIS PINS
==============
Before this gate the plugin validated the extraction TCL it EMITTED and never
read what magic sent BACK: a repo-wide `grep -rEil 'illegal.{0,3}overlap'` over
`vibe-ic-marketplace/plugins/vibe-ic/` returned 0 files. An extraction that hit
geometry magic could not resolve still emitted a netlist, and netgen's `match`
over that netlist reached a clean sign-off report.

The two traps, each with its own test:
  1. A MISSING feedback file must FAIL, not read as zero. `count_occurences`
     over a file that is not there returns 0, and 0 passes a threshold of 0 —
     "I could not look" and "I looked and it was clean" become the same word.
  2. The count is taken TWICE, from the raw bytes and from the parsed
     structure, and a disagreement is itself a FAILURE.

THE FIXTURE IS REAL, AND HERE IS THE RUN THAT MADE IT
=====================================================
`_REAL_FEEDBACK` below is not authored prose. It is the verbatim content of the
file `feedback save` wrote during a real magic hierarchical extraction, run in
this repo's own container image (magic 8.3.681) over a layout built to contain
an unresolvable overlap, in magic's bundled generic academic (lambda-scaled,
node-free) technology. The recipe, reproducible with nothing but magic::

    load ca -silent
    box 0 0 4 4
    paint ndiff
    save ca
    load cb -silent
    box 100 100 106 108
    paint ndiff
    save cb
    load t1 -silent
    box 0 0 4 4
    paint pdiff
    getcell ca
    save t1
    load t2 -silent
    box 100 100 106 108
    paint pdiff
    getcell cb
    save t2
    load t1 -silent
    extract all
    load t2 -silent
    extract all
    feedback save feedback.txt

    $ magic -dnull -noconsole -rcfile /dev/null -T scmos mk.tcl
    ...
    Extracting t1 into t1.ext:
    t1: 1 error
    Total of 1 error (check feedback entries).
    Extracting t2 into t2.ext:
    t2: 1 error
    Total of 1 error (check feedback entries).

Two facts that recipe also established, and that the gate's documentation
depends on:
  * `feedback save` over an EMPTY feedback list writes a 0-byte file. An empty
    feedback file is magic's real clean output and must PASS at 0 — which is
    exactly why an ABSENT one must not.
  * THREE disjoint unresolvable overlaps between ONE parent/child pair produced
    ONE feedback entry. The count is therefore a FLOOR on the number of
    overlaps, never the total, and the gate says so.

`test_magic_itself_still_writes_this_grammar` re-runs that recipe when magic is
on PATH, so the parser is checked against the tool rather than against a
transcription of it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent
_PROG = _HERE.parent / "magic_extract_illegal_overlap_check.py"

_spec = importlib.util.spec_from_file_location(
    "magic_extract_illegal_overlap_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
#: VERBATIM output of `feedback save` from the run documented above.
_REAL_FEEDBACK = (
    'box 0 0 4 4\n'
    'feedback add "Illegal overlap between ndiffusion and pdiffusion '
    '(types do not connect)" medium\n'
    'box 100 100 106 108\n'
    'feedback add "Illegal overlap between ndiffusion and pdiffusion '
    '(types do not connect)" medium\n'
)

#: A feedback entry that is NOT an illegal overlap — magic's feedback list
#: carries every complaint, and this gate must not gate on the others.
_OTHER_FEEDBACK = 'box 10 20 30 40\nfeedback add "Some other complaint" pale\n'


def _project(tmp_path: Path, feedback: str | None,
             extracted: bool = True) -> Path:
    """A project tree shaped like Step 22's declared output directory."""
    proj = tmp_path / "proj"
    ext = proj / mod.EXTRACTED_DIR
    if extracted:
        ext.mkdir(parents=True, exist_ok=True)
        (ext / "parasitic.spef").write_text("*SPEF \"IEEE 1481-1999\"\n")
    else:
        proj.mkdir(parents=True, exist_ok=True)
    if feedback is not None:
        ext.mkdir(parents=True, exist_ok=True)
        (ext / "feedback.txt").write_text(feedback)
    return proj


def _run(project: Path, *extra: str) -> tuple[int, dict]:
    out_json = project / "report.json"
    rc = mod.main([str(project), "--json", str(out_json), *extra])
    return rc, json.loads(out_json.read_text())


def _rules(payload: dict) -> list[str]:
    return [f["rule"] for f in payload["findings"]]


# --------------------------------------------------------------------------- #
# ACCEPT #1 — a fixture extraction with illegal overlaps must fail the gate
# --------------------------------------------------------------------------- #
def test_real_extraction_with_illegal_overlaps_fails(tmp_path):
    proj = _project(tmp_path, _REAL_FEEDBACK)
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert payload["verdict"] == "FAIL"
    assert "ILLEGAL_OVERLAP_NONZERO" in _rules(payload)
    assert payload["metrics"]["illegal_overlap_count"] == 2
    # both readings independently, and they agree
    assert payload["metrics"]["illegal_overlap_string_count"] == 2
    assert payload["metrics"]["illegal_overlap_parsed_count"] == 2
    # the parsed reading recovered geometry the string reading cannot see
    assert payload["illegal_overlaps"][0]["bbox"] == [0, 0, 4, 4]
    assert payload["illegal_overlaps"][1]["bbox"] == [100, 100, 106, 108]
    assert payload["illegal_overlaps"][0]["types"] == ["ndiffusion",
                                                       "pdiffusion"]


def test_one_illegal_overlap_is_already_over_threshold(tmp_path):
    single = _REAL_FEEDBACK.split("box 100")[0]
    proj = _project(tmp_path, single)
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert payload["metrics"]["illegal_overlap_count"] == 1


# --------------------------------------------------------------------------- #
# ACCEPT #2 — delete the feedback file and it fails too, with a DIFFERENT message
# --------------------------------------------------------------------------- #
def test_absent_feedback_fails_with_a_different_rule_than_a_violation(tmp_path):
    """TRAP 1. Absence is not zero, and it does not borrow the other verdict."""
    dirty = _project(tmp_path, _REAL_FEEDBACK)
    rc_dirty, dirty_payload = _run(dirty)

    absent = _project(tmp_path / "b", None)
    rc_absent, absent_payload = _run(absent)

    assert rc_dirty == rc_absent == mod.RC_FAIL
    assert _rules(dirty_payload) == ["ILLEGAL_OVERLAP_NONZERO"]
    assert _rules(absent_payload) == ["EXTRACTION_FEEDBACK_ABSENT"]
    # DIFFERENT message, not just a different rule id
    assert (dirty_payload["findings"][0]["message"]
            != absent_payload["findings"][0]["message"])
    assert "ABSENCE IS NOT ZERO" in absent_payload["findings"][0]["message"]
    # and it never publishes a number it does not have
    assert absent_payload["metrics"]["illegal_overlap_count"] is None
    assert absent_payload["metrics"]["feedback_present"] is False


def test_deleting_the_feedback_file_flips_a_pass_to_a_fail(tmp_path):
    """The same tree, PASSing, loses only its feedback file."""
    proj = _project(tmp_path, "")          # empty file: magic's clean output
    assert _run(proj)[0] == mod.RC_PASS
    (proj / mod.EXTRACTED_DIR / "feedback.txt").unlink()
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "EXTRACTION_FEEDBACK_ABSENT" in _rules(payload)


def test_an_explicitly_named_absent_channel_fails(tmp_path):
    proj = _project(tmp_path, None)
    out_json = tmp_path / "r.json"
    rc = mod.main([str(proj), "--feedback", str(tmp_path / "nowhere.txt"),
                   "--json", str(out_json)])
    payload = json.loads(out_json.read_text())
    assert rc == mod.RC_FAIL
    assert _rules(payload) == ["EXTRACTION_FEEDBACK_ABSENT"]


def test_absent_feedback_never_spends_the_vacuous_exit_code(tmp_path):
    """rc 2 is credited as a VACUOUS_PASS by `flow_compliance_check`.

    Routing "the error channel was not captured" to rc 2 would turn the step
    GREEN — a cheaper false certificate than the one this gate prevents.
    """
    proj = _project(tmp_path, None)
    assert _run(proj)[0] != mod.RC_VACUOUS


# --------------------------------------------------------------------------- #
# the clean case, and what "clean" is allowed to mean
# --------------------------------------------------------------------------- #
def test_empty_feedback_file_passes_at_zero(tmp_path):
    proj = _project(tmp_path, "")
    rc, payload = _run(proj)
    assert rc == mod.RC_PASS
    assert payload["metrics"]["illegal_overlap_count"] == 0
    assert payload["metrics"]["feedback_present"] is True
    assert "EXTRACTION_FEEDBACK_CLEAN" in _rules(payload)


def test_other_feedback_entries_are_disclosed_but_not_gated(tmp_path):
    proj = _project(tmp_path, _OTHER_FEEDBACK)
    rc, payload = _run(proj)
    assert rc == mod.RC_PASS
    assert payload["metrics"]["feedback_records"] == 1
    assert payload["metrics"]["illegal_overlap_count"] == 0
    assert "EXTRACTION_FEEDBACK_OTHER_ENTRIES" in _rules(payload)


def test_an_overlap_among_other_entries_still_fails(tmp_path):
    proj = _project(tmp_path, _OTHER_FEEDBACK + _REAL_FEEDBACK)
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert payload["metrics"]["feedback_records"] == 3
    assert payload["metrics"]["illegal_overlap_count"] == 2


# --------------------------------------------------------------------------- #
# TRAP 2 — two readings, and they must agree
# --------------------------------------------------------------------------- #
def test_parsed_fewer_than_string_is_a_loud_disagreement(tmp_path):
    """A truncated write: the phrase is in the bytes, the record is not.

    Here the loss also breaks the grammar, so the file is refused as malformed
    BEFORE a parsed number is reported — a parsed reading over a file the
    grammar cannot account for is not a reading.
    """
    truncated = (_REAL_FEEDBACK
                 + "box 200 200 204 204\n"
                 + "Illegal overlap between c and d (types do not connect)\n")
    proj = _project(tmp_path, truncated)
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "EXTRACTION_FEEDBACK_MALFORMED" in _rules(payload)
    assert payload["metrics"]["illegal_overlap_string_count"] == 3
    assert payload["metrics"]["illegal_overlap_parsed_count"] is None
    assert payload["metrics"]["illegal_overlap_count"] is None


def test_parsed_more_than_string_is_a_loud_disagreement(tmp_path):
    """A reworded/case-variant message the literal string reading is blind to."""
    proj = _project(tmp_path,
                    'box 0 0 4 4\nfeedback add "ILLEGAL OVERLAP between a '
                    'and b" medium\n')
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "ILLEGAL_OVERLAP_COUNT_DISAGREEMENT" in _rules(payload)
    assert payload["metrics"]["illegal_overlap_string_count"] == 0
    assert payload["metrics"]["illegal_overlap_parsed_count"] == 1
    # the blind reading is not allowed to lower the number
    assert payload["metrics"]["illegal_overlap_count"] == 1
    msg = payload["findings"][0]["message"]
    assert "raw-string count=0" in msg and "parsed-record count=1" in msg


def test_the_gated_count_is_the_max_of_the_two_readings(tmp_path):
    """Neither reading can lower the count on its own."""
    proj = _project(tmp_path,
                    _REAL_FEEDBACK
                    + 'box 5 5 9 9\nfeedback add "illegal overlap between e '
                      'and f" medium\n')
    rc, payload = _run(proj)
    m = payload["metrics"]
    assert rc == mod.RC_FAIL
    assert m["illegal_overlap_string_count"] == 2
    assert m["illegal_overlap_parsed_count"] == 3
    assert m["illegal_overlap_count"] == max(2, 3) == 3


def test_a_message_carrying_the_phrase_twice_disagrees(tmp_path):
    """One record, two literal occurrences — string 2 vs parsed 1."""
    proj = _project(tmp_path,
                    'box 0 0 4 4\nfeedback add "Illegal overlap between a and '
                    'b; Illegal overlap between c and d" medium\n')
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "ILLEGAL_OVERLAP_COUNT_DISAGREEMENT" in _rules(payload)
    assert payload["metrics"]["illegal_overlap_string_count"] == 2
    assert payload["metrics"]["illegal_overlap_parsed_count"] == 1


# --------------------------------------------------------------------------- #
# the channel is there but unusable
# --------------------------------------------------------------------------- #
def test_malformed_feedback_is_refused_not_counted(tmp_path):
    proj = _project(tmp_path, "this is not a magic feedback file at all\n")
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "EXTRACTION_FEEDBACK_MALFORMED" in _rules(payload)


def test_feedback_add_without_a_box_is_malformed(tmp_path):
    proj = _project(tmp_path, 'feedback add "Illegal overlap between a and b"\n')
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "EXTRACTION_FEEDBACK_MALFORMED" in _rules(payload)


def test_unreadable_feedback_fails(tmp_path):
    proj = _project(tmp_path, "")
    (proj / mod.EXTRACTED_DIR / "feedback.txt").write_bytes(b"\xff\xfe\x00bad")
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "EXTRACTION_FEEDBACK_UNREADABLE" in _rules(payload)


# --------------------------------------------------------------------------- #
# nothing was extracted at all
# --------------------------------------------------------------------------- #
def test_no_extraction_in_scope_is_a_disclosed_vacuous_rc2(tmp_path):
    proj = _project(tmp_path, None, extracted=False)
    rc, payload = _run(proj)
    assert rc == mod.RC_VACUOUS
    assert payload["verdict"] == "VACUOUS"
    assert _rules(payload) == ["NO_EXTRACTION_IN_SCOPE"]
    assert "NOTHING IS CLAIMED" in payload["findings"][0]["message"]


def test_extraction_output_of_any_kind_is_enough_to_demand_the_channel(tmp_path):
    """Not just `*.spef`: a netlist-only extraction is still an extraction."""
    proj = tmp_path / "p"
    ext = proj / mod.EXTRACTED_DIR
    ext.mkdir(parents=True)
    (ext / "top.spice").write_text(".subckt top a b\n.ends\n")
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "EXTRACTION_FEEDBACK_ABSENT" in _rules(payload)


def test_more_than_one_feedback_file_in_scope_is_disclosed(tmp_path):
    """Reading one of several and naming only that one cannot be checked."""
    proj = _project(tmp_path, "")
    ext = proj / mod.EXTRACTED_DIR
    (ext / "magic_extract_feedback.txt").write_text(_OTHER_FEEDBACK)
    rc, payload = _run(proj)
    assert rc == mod.RC_PASS
    assert "MULTIPLE_FEEDBACK_CANDIDATES" in _rules(payload)
    assert len(payload["feedback_candidates_found"]) == 2
    # and the one it read is named
    assert payload["feedback_file"] in payload["feedback_candidates_found"]


def test_a_project_dir_that_is_not_a_directory_never_passes(tmp_path):
    missing = tmp_path / "no-such-project"
    assert mod.main([str(missing)]) == mod.RC_FAIL


# --------------------------------------------------------------------------- #
# the metric
# --------------------------------------------------------------------------- #
def test_metric_is_published_under_the_step_and_is_schema_conformant(tmp_path):
    proj = _project(tmp_path, _REAL_FEEDBACK)
    _run(proj)
    metrics_file = proj / "reports" / "metrics" / "22.json"
    assert metrics_file.is_file()
    doc = json.loads(metrics_file.read_text())
    assert doc["22__magic__illegal_overlap__count"] == 2
    assert doc["22__magic__illegal_overlap__string_count"] == 2
    assert doc["22__magic__illegal_overlap__parsed_count"] == 2
    assert doc["22__magic__feedback__present"] is True
    # upstream's metric name survives verbatim as the key's tail
    assert any(k.endswith("magic__illegal_overlap__count") for k in doc)

    sm_spec = importlib.util.spec_from_file_location(
        "step_metrics", _HERE.parent / "step_metrics.py")
    sm = importlib.util.module_from_spec(sm_spec)
    sm_spec.loader.exec_module(sm)
    assert sm.conformance_defects(proj) == []


def test_an_undetermined_count_is_published_as_null_not_zero(tmp_path):
    """The metric must not launder "could not look" into "looked, saw none"."""
    proj = _project(tmp_path, None)
    _run(proj)
    doc = json.loads((proj / "reports" / "metrics" / "22.json").read_text())
    assert doc["22__magic__illegal_overlap__count"] is None
    assert doc["22__magic__feedback__present"] is False


# --------------------------------------------------------------------------- #
# parser unit tests
# --------------------------------------------------------------------------- #
def test_parser_accepts_the_style_token_being_absent(tmp_path):
    """Measured: magic omits the style when the entry carries polygon points."""
    records, defects = mod.parse_feedback(
        'box 0 0 200 200\nfeedback add "poly message with polygon"\n')
    assert defects == []
    assert records[0]["style"] is None
    assert records[0]["message"] == "poly message with polygon"


def test_parser_unescapes_quoted_messages(tmp_path):
    """Measured: magic writes `msg with \\"quotes\\" inside`."""
    records, defects = mod.parse_feedback(
        'box 0 0 200 200\nfeedback add "msg with \\"quotes\\" inside" pale\n')
    assert defects == []
    assert records[0]["message"] == 'msg with "quotes" inside'


def test_parser_reports_a_box_with_no_entry(tmp_path):
    _, defects = mod.parse_feedback("box 0 0 4 4\n")
    assert defects and "ends mid-entry" in defects[0]


def test_count_literal_is_case_sensitive_on_purpose(tmp_path):
    assert mod.count_literal("ILLEGAL OVERLAP") == 0
    assert mod.count_literal("Illegal overlap x Illegal overlap") == 2


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #
def test_gate_is_wired_between_extraction_and_lvs():
    """The gate must run on the extraction step, ahead of the LVS step.

    A checker that exists and nothing invokes is the shape this repo has a
    register for. Read as text rather than as YAML so the assertion does not
    depend on a YAML dependency being installed.
    """
    flow = (_PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()

    def _step_offset(step_id: str) -> int:
        m = re.search(rf"^  - id: {re.escape(step_id)}\s*$", flow, re.M)
        assert m, f"step {step_id} not found in the flow definition"
        return m.start()

    # A GATE CLAUSE, not a mention. Naming the program in the step's `programs:`
    # list documents it; only a `program_exit_zero` clause makes its exit status
    # decide the step. MEASURED: an earlier version of this assertion checked
    # only that the NAME APPEARS in the flow, and it passed in the revert copy
    # with the gate clause deleted and only the `programs:` mention left.
    clause = re.search(
        r'^\s*- program_exit_zero: "magic_extract_illegal_overlap_check\b[^"]*"$',
        flow, re.M)
    assert clause, ("the gate is not wired as a `program_exit_zero` clause; a "
                    "mention in `programs:` does not make an exit status "
                    "decide anything")
    gate_at = clause.start()
    # inside step 22 (extraction): after step 22's header, before the next step
    assert _step_offset("22") < gate_at < _step_offset("DT2")
    # and therefore ahead of step 31, which is where LVS is signed off
    assert gate_at < _step_offset("31")
    assert gate_at < flow.index('- program_exit_zero: "lvs_report_check')


def test_the_gate_declares_its_enforcement_intent():
    """`flow_gate_enforcement_audit` fails an in-flow gate that declares none."""
    doc = _PROG.read_text()
    assert re.search(r"^ENFORCEMENT:[ \t]*(blocking|advisory)\b", doc, re.M)


# NDA (no foundry name, process node, SKU or chip codename in a repo artefact)
# is NOT re-implemented here. The repo already owns that question in
# `nda_diff_scan_check` / `nda_tracked_tree_scan` / `source_chip_agnostic_check`,
# and a second hand-rolled pattern list would be a weaker copy that drifts from
# the real one — and, measured, one that matches its own regex source.


# --------------------------------------------------------------------------- #
# provenance — check the parser against the TOOL, not against a transcription
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("magic") is None,
                    reason="magic is not on PATH; the grammar this parser "
                           "accepts was measured from magic 8.3.681 and is "
                           "pinned by _REAL_FEEDBACK above")
def test_magic_itself_still_writes_this_grammar(tmp_path):
    """Re-run the documented recipe and parse whatever magic actually writes."""
    fb = tmp_path / "feedback.txt"
    script = tmp_path / "mk.tcl"
    # RELATIVE filenames, driven from cwd=tmp_path. The script is Tcl, and an
    # absolute pytest tmp path is not guaranteed to be one Tcl word: measured
    # in this image, `pytest`'s basetemp is named after the login account and
    # that account's name contains a NEWLINE, so an interpolated absolute path
    # made magic report `invalid command name "<second line>"` and write no
    # feedback file at all — a tool that ran, said nothing about it on stdout,
    # and would have been read as "clean".
    script.write_text(
        "load ca -silent\nbox 0 0 4 4\npaint ndiff\nsave ca\n"
        "load t1 -silent\nbox 0 0 4 4\npaint pdiff\ngetcell ca\nsave t1\n"
        "load t1 -silent\nextract all\n"
        "feedback save feedback.txt\nquit -noprompt\n")
    try:
        cp = subprocess.run(
            ["magic", "-dnull", "-noconsole", "-rcfile", os.devnull,
             "-T", "scmos", script.name],
            cwd=tmp_path, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"magic could not be driven here: {exc}")

    # magic must have SAID it hit the error; if it did not, this build or
    # technology does not reproduce the recipe and there is nothing to check.
    said_error = "error" in (cp.stdout + cp.stderr).lower()
    if not said_error:
        pytest.skip("this magic build/technology reported no extraction error "
                    f"for the recipe; stdout tail: {cp.stdout[-400:]!r}")
    # It DID say so — then the file must be there. A tool that reported an
    # error and left no error channel behind is the defect, not a skip.
    assert fb.is_file() and fb.read_text().strip(), (
        f"magic reported an extraction error and wrote no feedback file; "
        f"stdout tail: {cp.stdout[-400:]!r} stderr tail: {cp.stderr[-400:]!r}")

    text = fb.read_text()
    records, defects = mod.parse_feedback(text)
    assert defects == [], f"parser cannot account for magic's own output: {text!r}"
    assert records, f"magic wrote entries this parser produced none from: {text!r}"
    overlaps = mod.illegal_overlap_records(records)
    assert overlaps, f"expected an illegal overlap, magic wrote: {text!r}"
    assert mod.count_literal(text) == len(overlaps)

    proj = _project(tmp_path, text)
    rc, payload = _run(proj)
    assert rc == mod.RC_FAIL
    assert "ILLEGAL_OVERLAP_NONZERO" in _rules(payload)
