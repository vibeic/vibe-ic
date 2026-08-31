#!/usr/bin/env python3
"""visited / extracted / unread are all denominated on the VISITED set.

MEASURED DEFECT
===============
The Phase-1 census reports ``visited``, ``extracted`` and ``unread``. All three
are denominated on the set the extractor CHOSE to visit, so a document that is
PRESENT under ``input/`` and never opened is in NONE of them: it cannot be
counted unread, and the census prints ``0 UNREAD`` / ``100.0%`` over it.

That is exactly how a design brief was silently dropped, and the same file is
present-and-unopened in a second benchmark IC.

SEVERITY IS A DECISION, NOT AN OVERSIGHT
========================================
Measured over the benchmark corpus, only 4 document-shaped files sit outside
``input/docs/`` at all — the brief in two ICs, and two vendor READMEs that
SHOULD never be ingested. Failing a run over a README is the wrong trade;
leaving the state invisible is what allowed the defect. So this is ADVISORY.

THE CONTENT TEST IS REQUIRED, NOT COSMETIC
==========================================
The Phase-1 front-end bridges the brief into ``input/docs/`` under a COPY, so
the ORIGINAL path is never visited even though its content was fully ingested.
A path-only check would report it forever on a flow that handles it correctly.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _path_layout as _pl  # noqa: E402
import phase1_doc_one_shot_runner as R  # noqa: E402

BRIEF = "# Brief\nThe only file stating the owner directive.\n"


def _project(tmp_path: Path, cited, bridged_copy=False) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "vendor.md").write_text("# Vendor\ntext\n")
    (tmp_path / "input" / "phase1_prompt.md").write_text(BRIEF)
    (tmp_path / "input" / "vendor_rtl").mkdir()
    (tmp_path / "input" / "vendor_rtl" / "README.md").write_text("scaffolding\n")
    if bridged_copy:
        (docs / "phase1_prompt.md").write_text(BRIEF)
        cited = cited + ["input/docs/phase1_prompt.md"]
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"source_documents": cited}))
    return tmp_path


def _paths(rows):
    return sorted(r["path"] for r in rows)


def test_a_present_document_nothing_opened_is_reported(tmp_path):
    project = _project(tmp_path, ["input/docs/vendor.md"])

    rows = R._v1_14_50_present_but_never_ingested(project)

    assert "input/phase1_prompt.md" in _paths(rows), (
        "a document present under input/ and opened by nothing appears in "
        "neither the visited, extracted nor unread census — it is invisible")


def test_a_document_ingested_under_a_bridged_copy_is_not_reported(tmp_path):
    """The content test: the original path is never visited, yet it WAS read."""
    project = _project(tmp_path, ["input/docs/vendor.md"], bridged_copy=True)

    assert "input/phase1_prompt.md" not in _paths(
        R._v1_14_50_present_but_never_ingested(project)), (
        "a path-only check cries wolf on a flow that bridges the brief under "
        "a copy and handles it correctly")


def test_a_cited_document_is_not_reported(tmp_path):
    project = _project(tmp_path, ["input/docs/vendor.md"])
    assert "input/docs/vendor.md" not in _paths(
        R._v1_14_50_present_but_never_ingested(project))


def test_every_row_carries_a_reason(tmp_path):
    project = _project(tmp_path, ["input/docs/vendor.md"])
    rows = R._v1_14_50_present_but_never_ingested(project)
    assert rows and all(r.get("reason") for r in rows)


def test_a_project_with_no_input_directory_is_a_no_op(tmp_path):
    assert R._v1_14_50_present_but_never_ingested(tmp_path) == []
