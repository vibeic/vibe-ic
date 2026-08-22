#!/usr/bin/env python3
"""A head-to-head corpus must be identified by what a document DECLARES, not by
what it is called — and this program's own reports are not subjects it may judge.

MEASURED ON THIS REPOSITORY, origin/main a00f53f20 (v1.11.66), before the fix.
`corpus_records` was `corpus.glob("**/*head_to_head*.json")`, a guess about
filenames, and it was wrong in both directions at the same time:

  --corpus ppa-crosslayer  ->  "0 head-to-head record(s) found", rc 2
      while 15 committed `vibeic.ppa.comparison.v2` records sit in
      `ppa-crosslayer/records/h2h_A.json` .. `h2h_O.json`. Judged one at a time
      they are 12 PASS, 1 REFUSED (`BASELINE_TUNED_BY_US` on the record behind
      the lane's headline number) and 2 UNDETERMINED. The corpus verdict was
      byte-identical to a corpus that holds nothing.

  --corpus ppa-e2e         ->  4 files matched, 2 of them `*_report.json`
      artefacts THIS checker wrote. A report carries no `arms`, so the gate
      answered `TOO_FEW_ARMS ... got 0` — a REFUSAL, its most severe verdict,
      aimed at its own output. Half that corpus verdict was the gate marking
      its own paper.

Both halves are asserted here, and so are the two ways the repair could itself
become a hole: a file that is unreadable must not be quietly dropped, and a real
record that has genuinely lost its `arms` must still be refused rather than
mistaken for a report.
"""
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_pphth_corpus", PROGRAMS / "ppa_head_to_head_check.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def _minimal_record(schema="vibeic.ppa.comparison.v2"):
    """Only what IDENTIFIES a record. It need not be a good one — the point of
    every assertion below is which files enter the population, not what verdict
    they then earn."""
    return {"schema": schema,
            "arms": [{"flow": "a", "role": "baseline"},
                     {"flow": "b", "role": "subject"}]}


def test_a_record_under_any_filename_is_in_the_corpus(tmp_path):
    """RED WITHOUT THE FIX: the name glob never matches `h2h_A.json`, so this
    found 0 and the corpus reported an empty population it had not searched."""
    _write(tmp_path / "records" / "h2h_A.json", _minimal_record())
    found = C.corpus_records(tmp_path)
    assert [p.name for p in found] == ["h2h_A.json"]


def test_this_programs_own_report_is_not_a_subject(tmp_path):
    """RED WITHOUT THE FIX: the report's filename matched, it has no `arms`, and
    the gate refused it TOO_FEW_ARMS."""
    _write(tmp_path / "head_to_head.json", _minimal_record())
    _write(tmp_path / "head_to_head_report.json",
           {"record": "/somewhere/head_to_head.json",
            "declared_schema": "vibeic.ppa.comparison.v2",
            "ok": False,
            "refusal": {"code": "SCOPE_SENTINEL", "message": "..."}})
    found = C.corpus_records(tmp_path)
    assert [p.name for p in found] == ["head_to_head.json"], (
        "the report about a record is not a second record")


def test_dropping_the_report_never_drops_the_record_it_is_about(tmp_path):
    """The paired half of the test above: excluding reports must not be able to
    shrink the population of real records. Without this, 'exclude reports' could
    be widened until it excluded everything and both tests would still pass."""
    _write(tmp_path / "head_to_head.json", _minimal_record())
    _write(tmp_path / "head_to_head_report.json",
           {"record": "x", "ok": True})
    _write(tmp_path / "records" / "h2h_B.json", _minimal_record())
    _write(tmp_path / "records" / "h2h_B_report.json",
           {"record": "y", "ok": False, "refusal": {"code": "C", "message": "m"}})
    assert sorted(p.name for p in C.corpus_records(tmp_path)) == [
        "h2h_B.json", "head_to_head.json"]


def test_a_record_that_lost_its_arms_is_still_refused_not_mistaken_for_a_report(tmp_path):
    """The repair must not become a way to disappear. A document that DECLARES
    the comparison schema is a record however defective it is, and it earns its
    refusal from `evaluate` rather than being filtered out of the population."""
    _write(tmp_path / "records" / "h2h_C.json",
           {"schema": "vibeic.ppa.comparison.v2", "record": "self", "ok": True})
    found = C.corpus_records(tmp_path)
    assert [p.name for p in found] == ["h2h_C.json"]
    rc, report = C.evaluate(found[0])
    assert rc == C.RC_REFUSED
    assert report["refusal"]["code"] == "TOO_FEW_ARMS"


def test_an_unreadable_file_that_was_named_a_record_is_not_silently_dropped(tmp_path):
    """UNREADABLE IS NOT ABSENT. A file that claims by its name to be a record
    and cannot be parsed stays in the population so the gate says so out loud."""
    p = tmp_path / "head_to_head_truncated.json"
    p.write_text('{"schema": "vibeic.ppa.comparison.v2", "arms": [',
                 encoding="utf-8")
    found = C.corpus_records(tmp_path)
    assert [x.name for x in found] == ["head_to_head_truncated.json"]
    rc, _ = C.evaluate(found[0])
    assert rc != C.RC_OK, "an unparseable record must never reach a reader as a pass"


def test_a_neighbouring_document_is_not_conscripted_as_a_record(tmp_path):
    """The other direction: identification by declaration must not sweep in
    every JSON file in the corpus. A contract is not a comparison."""
    _write(tmp_path / "records" / "contract.json",
           {"schema": "vibeic.ppa.contract.v1", "run_label": "b000"})
    _write(tmp_path / "records" / "records_flat.json",
           [{"schema": "vibeic.ppa.metric.v1", "metric": "area.die.um2"}])
    assert C.corpus_records(tmp_path) == []


def test_a_pre_schema_record_keeps_the_filename_it_only_ever_had(tmp_path):
    """`record_schema()` reads a missing declaration as v1 because records
    predate the field. Those have nothing BUT their name, so the name is still
    honoured — together with the `arms` a head-to-head is defined by."""
    _write(tmp_path / "old_head_to_head.json",
           {"arms": [{"flow": "a", "role": "baseline"},
                     {"flow": "b", "role": "subject"}]})
    assert [p.name for p in C.corpus_records(tmp_path)] == [
        "old_head_to_head.json"]
