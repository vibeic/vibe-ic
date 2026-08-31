#!/usr/bin/env python3
"""The design brief was unreadable whenever input/docs/ was already populated.

MEASURED DEFECT
===============
`phase1_one_shot_runner._run_docs_mode` bridged the Phase-1 front-end into
`input/docs/` only under ``if not _has_real_doc(docs_dir)`` — stated policy
"a real document always wins".

That is right for the DIALOGUE artefact `phase1_structured.yaml`, which
restates the same design. It is wrong for `input/phase1_prompt.md`, which is
the only input carrying what the vendor documents cannot: parameter overrides,
the PDK target, tie-off decisions, the intended implementation path, the
verification oracle.

Measured on a staged-vendor-docs IC: **0 of 28** emitted L docs cited the
prompt, and the coverage gate still reported ``0 UNREAD`` / ``100.0%`` — its
denominator is the set the extractor CHOSE to visit, and a file that is never
opened cannot be counted unread. The value the brief stated never reached
Phase 2, so synthesis built the vendor default and aborted.

The same file is present-and-unopened in a second benchmark IC (ibex), so this
is not one project's accident.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase1_one_shot_runner as P  # noqa: E402


def _project(tmp_path: Path) -> Path:
    """A project shaped like every staged-vendor-docs IC: real docs AND a brief."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "vendor_theory.md").write_text("# Theory\nA real vendor document.\n")
    (tmp_path / "input" / "phase1_prompt.md").write_text(
        "# Brief\nOnly this file states the owner directive.\n")
    return tmp_path


def test_prompt_is_bridged_when_docs_dir_already_holds_real_documents(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    # The delegated docs runner is not under test; stub it so the bridge is
    # the only thing this exercises.
    monkeypatch.setattr(P._phase1_doc, "main", lambda: 0, raising=False)

    P._run_docs_mode(project, "UNIT_IC")

    bridged = project / "input" / "docs" / "phase1_prompt.md"
    assert bridged.is_file(), (
        "input/phase1_prompt.md was NOT bridged into a populated input/docs/, "
        "so nothing in Phase 1 can ever read the design brief")
    assert "owner directive" in bridged.read_text()


def test_the_real_vendor_document_is_never_overwritten(tmp_path, monkeypatch):
    project = _project(tmp_path)
    before = (project / "input" / "docs" / "vendor_theory.md").read_text()
    monkeypatch.setattr(P._phase1_doc, "main", lambda: 0, raising=False)

    P._run_docs_mode(project, "UNIT_IC")

    assert (project / "input" / "docs" / "vendor_theory.md").read_text() == before


def test_an_existing_docs_entry_of_the_same_name_wins(tmp_path, monkeypatch):
    """The bridge must never clobber a document the project already ships."""
    project = _project(tmp_path)
    existing = project / "input" / "docs" / "phase1_prompt.md"
    existing.write_text("# Already here\n")
    monkeypatch.setattr(P._phase1_doc, "main", lambda: 0, raising=False)

    P._run_docs_mode(project, "UNIT_IC")

    assert existing.read_text() == "# Already here\n"
