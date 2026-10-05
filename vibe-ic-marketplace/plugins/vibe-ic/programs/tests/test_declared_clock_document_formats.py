"""Supported plain-text inputs must reach the PDK-keyed clock consumer."""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import declared_clock_period as dcp
import clock_target_provenance as ctp
import l19_constraint_token_emit as l19
import phase1_doc_one_shot_runner as phase1


DOCUMENT = """# Timing constraints

| Std-cell library | period (ns) |
|---|---|
| logic_slow | 24 |
| logic_fast | 10 |
"""


def write_doc(project, name, text=DOCUMENT):
    doc = project / "input" / "docs" / name
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text)
    return doc


@pytest.mark.parametrize("suffix", [".md", ".txt", ".MD", ".TXT"])
def test_supported_plain_document_reaches_pdk_bound_clock(tmp_path, suffix):
    doc = write_doc(tmp_path, "L9_constraints" + suffix)
    # The front door accepts identical bytes in all these forms.
    assert phase1.extract_one(doc) == DOCUMENT
    report = ctp.resolve(tmp_path, pdk="logic_slow")
    assert report["period_ns"] == 24.0
    assert report["tier"] == "declared_pdk_table"
    assert report["cite"].startswith(str(doc) + ":")
    record = l19._clock_target_record(tmp_path, {"pdk_target": "logic_slow"})
    assert record["pdk"] == "logic_slow"
    assert record["pdk_source"] == "declared_pdk_table_match"


def test_conflicting_mixed_document_formats_are_refused(tmp_path):
    write_doc(tmp_path, "L9_original.md")
    write_doc(tmp_path, "L9_other.txt", DOCUMENT.replace("| 24 |", "| 31 |"))
    report = dcp.declared_period_ns(dcp.docs_in(tmp_path / "input/docs"), ["logic_slow"])
    assert report["period_ns"] is None
    assert report["ambiguous"] is True
    assert {row["period_ns"] for row in report["matches"]} == {24.0, 31.0}


def test_identical_mixed_documents_agree_without_hiding_either_source(tmp_path):
    write_doc(tmp_path, "L9_original.md")
    write_doc(tmp_path, "L9_copy.txt")
    report = dcp.declared_period_ns(dcp.docs_in(tmp_path / "input/docs"), ["logic_slow"])
    assert report["period_ns"] == 24.0
    assert report["ambiguous"] is False
    assert {Path(row["source"]).suffix for row in report["matches"]} == {".md", ".txt"}


def test_text_rows_remain_scoped_to_the_selected_technology(tmp_path):
    write_doc(tmp_path, "L9_constraints.txt")
    docs = dcp.docs_in(tmp_path / "input/docs")
    assert dcp.declared_period_ns(docs, ["logic_slow"])["period_ns"] == 24.0
    assert dcp.declared_period_ns(docs, ["logic_fast"])["period_ns"] == 10.0
    missing = dcp.declared_period_ns(docs, ["other_library"])
    assert missing["period_ns"] is None
    assert missing["rows_seen"] == 2
    assert missing["matches"] == []


def test_non_constraint_text_does_not_override_declared_clock(tmp_path):
    write_doc(tmp_path, "L9_constraints.txt")
    write_doc(tmp_path, "L2_background.txt", DOCUMENT.replace("| 24 |", "| 3 |"))
    write_doc(tmp_path, "L9_binary.pdf", DOCUMENT.replace("| 24 |", "| 4 |"))
    (tmp_path / "input/docs/L9_directory.txt").mkdir()
    report = dcp.declared_period_ns(dcp.docs_in(tmp_path / "input/docs"), ["logic_slow"])
    assert report["period_ns"] == 24.0
    assert report["ambiguous"] is False
    assert report["source"].endswith("L9_constraints.txt")
