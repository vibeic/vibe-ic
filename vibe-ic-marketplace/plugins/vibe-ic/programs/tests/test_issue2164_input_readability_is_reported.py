#!/usr/bin/env python3
"""Regression for #2164 (1 of 3) — an unreadable design input is a named
NOT_MEASURED at the point of use, never an empty query.

THE DEFECT, MEASURED ON THE PUBLISHED CORPUS. `input_text` returned a string
and nothing else. A project whose entire design input is a PDF returned `""` —
byte-identical to a project with no `input/` tree at all, and to one whose
files are genuinely empty. That empty string was then handed to
`ic_expert_db_query.query` as a retrieval QUERY and to the AI sub-track as a
PROMPT, and every consumer read what came back as a measurement. FOURTEEN
published corpus projects are in that state today, every one of them
classified, across five registered classes — ten `digital_arithmetic_primitive`
plus one each of `serial_peripheral_protocol`, `digital_cmd_driven`,
`pure_analog` and `processor_cpu`. All fourteen hold exactly one `.pdf`.

AND THE COUNT IS WHY THE CENSUS EXISTS. That figure was carried by hand as
"12 across five classes" through two commit messages of the lane that found it.
It was 14. A population nobody can re-derive with one command is a population
that drifts, so `--input-readability` prints it per project and the corpus
figure is a loop, not a memory.

FIVE STATES, because four of them used to be the same empty string:
  READ / NO_INPUT_TREE / NO_FILES_AT_ALL / UNREADABLE_FORMAT / READ_AND_EMPTY
and the one distinction the whole change turns on is the last against the
fourth: "I read it and it was empty" is a fact about the DESIGN and may be
reported as a zero; "I could not open it" is a fact about the READER and may
not.

chip-AGNOSTIC: every fixture is synthetic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T  # noqa: E402


def _project(tmp_path: Path, files: dict, name: str = "proj") -> Path:
    d = tmp_path / name
    for rel, content in files.items():
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        else:
            f.write_text(content)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── 1. the five states are all reachable and all distinct ─────────────────

def test_a_readable_input_is_READ(tmp_path):
    d = _project(tmp_path, {"input/docs/L1.md": "# a design\nwith prose.\n"})
    r = T.input_text_report(d)
    assert r["status"] == T.INPUT_READ
    assert r["chars"] > 0 and r["files_read"] == ["docs/L1.md"]
    assert T.input_readability_disposition(r)["retrieval_input"] == "MEASURED"


def test_no_input_tree_is_its_own_state(tmp_path):
    d = tmp_path / "bare"
    d.mkdir()
    r = T.input_text_report(d)
    assert r["status"] == T.INPUT_NO_TREE and r["chars"] == 0
    assert T.input_readability_disposition(r)["retrieval_input"] == "NOT_MEASURED"


def test_an_input_tree_with_no_files_is_its_own_state(tmp_path):
    d = tmp_path / "empty"
    (d / "input" / "docs").mkdir(parents=True)
    r = T.input_text_report(d)
    assert r["status"] == T.INPUT_NO_FILES and r["chars"] == 0


def test_a_pdf_only_input_is_UNREADABLE_FORMAT_and_says_the_format(tmp_path):
    """THE MEASURED CASE, reduced to its shape. The reason must NAME the
    format: a reader told "the query was empty" repairs nothing, and a reader
    told "the spec is a .pdf and I open seven text formats" repairs it."""
    d = _project(tmp_path, {"input/docs/spec.pdf": b"%PDF-1.4 binary"})
    r = T.input_text_report(d)
    assert r["status"] == T.INPUT_UNREADABLE_FORMAT and r["chars"] == 0
    assert r["unsupported_suffixes"] == {".pdf": 1}
    assert r["files_skipped"][0]["reason"] == T.SKIP_UNSUPPORTED_FORMAT
    assert r["files_skipped"][0]["bytes"] == len(b"%PDF-1.4 binary")
    disp = T.input_readability_disposition(r)
    assert disp["retrieval_input"] == "NOT_MEASURED"
    assert ".pdf" in disp["reason"]
    for ext in T._INPUT_TEXT_EXTS:
        assert ext in disp["reason"], "the reason must list what it CAN open"


def test_read_and_empty_is_the_ONE_zero_that_is_about_the_design(tmp_path):
    """THE DISTINCTION THE WHOLE CHANGE TURNS ON, asserted against its
    neighbour rather than alone. Both produce 0 characters; only one of them is
    a measurement, and a consumer that spells them the same way credits an
    unread design as an empty one."""
    readable_but_empty = _project(tmp_path, {"input/docs/L1.md": ""}, "a")
    unreadable = _project(tmp_path, {"input/docs/spec.pdf": b"%PDF"}, "b")
    ra = T.input_text_report(readable_but_empty)
    ub = T.input_text_report(unreadable)
    assert ra["chars"] == ub["chars"] == 0
    assert ra["status"] == T.INPUT_READ_AND_EMPTY
    assert ub["status"] == T.INPUT_UNREADABLE_FORMAT
    assert T.input_readability_disposition(ra)["retrieval_input"] == "MEASURED_EMPTY"
    assert T.input_readability_disposition(ub)["retrieval_input"] == "NOT_MEASURED"


def test_the_oracle_exclusion_is_recorded_as_a_skip_not_as_a_failure(tmp_path):
    """§4.05's own exclusion must appear in the account. A file the reader
    refused ON PURPOSE and a file it could not open are both "not read", and a
    record that cannot tell them apart makes the deliberate one look broken."""
    d = _project(tmp_path, {"input/docs/L1.md": "prose",
                            "input/output/golden.md": "the answer"})
    r = T.input_text_report(d)
    reasons = {s["reason"] for s in r["files_skipped"]}
    assert T.SKIP_ORACLE_PATH in reasons, r["files_skipped"]
    assert "the answer" not in r["text"]
    assert r["status"] == T.INPUT_READ


# ── 2. the text itself is unchanged ───────────────────────────────────────

def test_input_text_returns_exactly_what_it_always_returned(tmp_path):
    """The refactor must not move a single character: every caller that only
    wants the string keeps getting the same string."""
    d = _project(tmp_path, {"input/docs/a.md": "alpha\n",
                            "input/docs/b.txt": "beta\n",
                            "input/notes.rst": "gamma\n"})
    r = T.input_text_report(d)
    assert T.input_text(d) == r["text"]
    # sorted rglob order: docs/a.md, docs/b.txt, notes.rst
    assert r["text"] == "alpha\n\nbeta\n\ngamma\n"
    assert r["files_read"] == ["docs/a.md", "docs/b.txt", "notes.rst"]


def test_truncation_is_reported_rather_than_silent(tmp_path):
    # Context, not a design document: ruling #82(5) never cuts input/docs
    # (test_expert_frame_reads_design_documents_first.py).
    big = "x" * (T._INPUT_TEXT_CAP + 10)
    d = _project(tmp_path, {"input/big.md": big})
    r = T.input_text_report(d)
    assert r["truncated"] is True
    assert r["chars"] == T._INPUT_TEXT_CAP


# ── 3. the point of USE — the track says NOT_MEASURED, loudly ─────────────

def test_the_track_reports_an_unreadable_input_by_rule_name(tmp_path):
    d = _project(tmp_path, {"input/docs/spec.pdf": b"%PDF-1.4"})
    rep = T.evaluate(d)
    fired = [f for f in rep["findings"]
             if f["rule"] == T.RULE_INPUT_NOT_READABLE]
    assert fired, "an unreadable design input produced no finding at all"
    assert fired[0]["about"] == "track", (
        "this is about the READER; counting it against the design would make "
        "an unopened spec look like a deficient chip")
    assert ".pdf" in fired[0]["message"]
    assert rep["retrieval_input"]["retrieval_input"] == "NOT_MEASURED"
    assert rep["track_health"]["input_text_status"] == T.INPUT_UNREADABLE_FORMAT


def test_the_track_is_silent_when_the_input_IS_readable(tmp_path):
    """The other direction. A finding that fires on every run is not a
    finding."""
    d = _project(tmp_path, {"input/docs/L1.md": "a serial peripheral design.\n"})
    rep = T.evaluate(d)
    assert not [f for f in rep["findings"]
                if f["rule"] == T.RULE_INPUT_NOT_READABLE]
    assert rep["retrieval_input"]["retrieval_input"] == "MEASURED"


def test_mutation_treating_an_unreadable_input_as_empty_loses_the_finding(
        tmp_path, monkeypatch):
    """THE NEGATIVE CONTROL. Put the reader back the way it was — a zero with
    no state attached — and the track goes quiet on a design input it cannot
    open, which is exactly the pre-#2164 behaviour."""
    d = _project(tmp_path, {"input/docs/spec.pdf": b"%PDF-1.4"})
    real = T.input_text_report

    def flattened(project):
        r = real(project)
        r["status"] = T.INPUT_READ_AND_EMPTY   # the old undifferentiated zero
        return r

    monkeypatch.setattr(T, "input_text_report", flattened)
    rep = T.evaluate(d)
    assert not [f for f in rep["findings"]
                if f["rule"] == T.RULE_INPUT_NOT_READABLE], (
        "the mutation did not reproduce the defect, so the positive assertion "
        "above proves nothing about the new state")


# ── 4. the census a corpus loop needs ─────────────────────────────────────

def test_the_census_flag_prints_a_line_and_exits_zero_both_ways(tmp_path, capsys):
    """Exit 0 either way ON PURPOSE: an unreadable input is a fact to report,
    and a census that exits non-zero on the thing it exists to count cannot be
    run in a loop over a corpus."""
    bad = _project(tmp_path, {"input/docs/spec.pdf": b"%PDF"}, "bad")
    good = _project(tmp_path, {"input/docs/L1.md": "prose"}, "good")
    assert T.main([str(bad), "--input-readability"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("NOT_MEASURED\t") and "UNREADABLE_FORMAT" in out
    assert '".pdf": 1' in out and "reason:" in out
    assert T.main([str(good), "--input-readability"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("MEASURED\t") and "READ" in out


def test_the_census_writes_no_report_file(tmp_path):
    """It must be cheap enough to run over a whole corpus, which means it does
    not do the track's work and does not leave the track's artefacts behind."""
    d = _project(tmp_path, {"input/docs/spec.pdf": b"%PDF"})
    assert T.main([str(d), "--input-readability"]) == 0
    assert not (d / "reports").exists()
