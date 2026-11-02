#!/usr/bin/env python3
"""Ruling #82(5): the Phase-1 expert input frame carries the design documents.

THE DEFECT, MEASURED ON THE ADC D1 CASE. `input_text_report` walked `input/**`
in one sorted pass and stopped at `_INPUT_TEXT_CAP` (200,000 characters). Two
authority JSON files and `analog_flow.json` sort before `docs/` and hold
197,480 bytes, so the stored frame had five members, none from `input/docs`,
`truncated: true` and an empty skip list: the IC-expert answer was authored
without the six design documents, and the files after the stop were not
named anywhere.

The frame now reads the design documents (the D1 design-input population,
`ai_signed_judgement.DESIGN_INPUT_GLOBS`) first and whole; the rest of
`input/` shares what they leave of the budget in sorted order, and every
readable file left out is skipped BY NAME (`FRAME_BUDGET`) and listed in the
`truncation` record.

chip-AGNOSTIC: every fixture is synthetic and the budget is shrunk so the
shapes stay small.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ai_signed_judgement as J  # noqa: E402
import phase1_expert_parse_track as T  # noqa: E402

CAP = 1000


@pytest.fixture(autouse=True)
def small_budget(monkeypatch):
    monkeypatch.setattr(T, "_INPUT_TEXT_CAP", CAP)


def _tree(tmp_path: Path, files: dict, name: str = "proj") -> Path:
    d = tmp_path / name
    for rel, content in files.items():
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        else:
            f.write_text(content)
    return d


def _adc_shaped(tmp_path: Path) -> Path:
    """Authority and answer JSON that sort before `docs/` and alone spend the
    budget — the ADC shape at 1/200 scale."""
    return _tree(tmp_path, {
        "input/a_requirement_authority.json": json.dumps({"requirement": "A" * 700}),
        "input/authority_sources/answers.json": json.dumps({"answer": "B" * 700}),
        "input/docs/L1_DATASHEET.md": "# datasheet\nDOC_MARKER_ONE reference 1.0 V\n",
        "input/docs/L9_CONSTRAINTS.md": "# constraints\nDOC_MARKER_TWO die 1300 um\n",
        "input/step_0_5ic_answers.json": json.dumps({"answers": {"x": "C" * 50}}),
    })


def _binding(project: Path) -> str:
    report = T.input_text_report(project)
    return T._pack.phase1_frame(report["text"], report["source_frame"])[1]


def test_design_documents_that_used_to_be_dropped_are_in_the_frame(tmp_path):
    d = _adc_shaped(tmp_path)
    r = T.input_text_report(d)
    members = r["source_frame"]["members"]
    assert r["design_documents"] == ["docs/L1_DATASHEET.md", "docs/L9_CONSTRAINTS.md"]
    assert [m["path"] for m in members[:2]] == r["design_documents"]
    assert all(m["complete"] for m in members[:2])
    assert "DOC_MARKER_ONE" in r["text"] and "DOC_MARKER_TWO" in r["text"]
    # Context follows in sorted order and is what the budget cuts.
    assert [m["path"] for m in members[2:]] == [
        "a_requirement_authority.json", "authority_sources/answers.json"]
    assert r["truncated"] is True


def test_mutation_without_the_design_tier_drops_the_documents_again(tmp_path, monkeypatch):
    """NEGATIVE CONTROL. Take the design tier away and the plain sorted walk
    spends the budget on authority JSON again: the documents leave the frame
    (now at least by name, as FRAME_BUDGET skips)."""
    d = _adc_shaped(tmp_path)
    monkeypatch.setattr(T, "_design_document_files", lambda project: set())
    r = T.input_text_report(d)
    assert "DOC_MARKER_ONE" not in r["text"]
    budget = {s["path"] for s in r["files_skipped"] if s["reason"] == T.SKIP_FRAME_BUDGET}
    assert {"docs/L1_DATASHEET.md", "docs/L9_CONSTRAINTS.md"} <= budget


def test_the_binding_now_covers_the_design_documents(tmp_path, monkeypatch):
    """input_frame_sha256 changes whenever frame content changes. On this shape
    a same-length edit of a design document used to leave it unchanged,
    because the document was never in the frame."""
    d = _adc_shaped(tmp_path)
    doc = d / "input/docs/L1_DATASHEET.md"
    before = _binding(d)
    assert _binding(d) == before, "the frame must be deterministic"
    doc.write_text(doc.read_text().replace("1.0 V", "1.2 V"))
    assert _binding(d) != before
    monkeypatch.setattr(T, "_design_document_files", lambda project: set())
    unbound = _binding(d)
    doc.write_text(doc.read_text().replace("1.2 V", "1.0 V"))
    assert _binding(d) == unbound, "control: without the design tier the edit is invisible"


def test_truncation_names_what_was_cut_and_what_was_left_out(tmp_path):
    d = _adc_shaped(tmp_path)
    r = T.input_text_report(d)
    t = r["truncation"]
    assert t["budget_chars"] == CAP
    assert t["design_document_chars"] == len(
        (d / "input/docs/L1_DATASHEET.md").read_text() + "\n"
        + (d / "input/docs/L9_CONSTRAINTS.md").read_text())
    assert [c["path"] for c in t["cut"]] == ["authority_sources/answers.json"]
    assert 0 <= t["cut"][0]["included_chars"] < t["cut"][0]["chars"]
    assert t["left_out"] == ["step_0_5ic_answers.json"]
    skip = next(s for s in r["files_skipped"] if s["path"] == "step_0_5ic_answers.json")
    assert skip["reason"] == T.SKIP_FRAME_BUDGET
    assert skip["bytes"] == (d / "input/step_0_5ic_answers.json").stat().st_size
    assert r["source_frame"]["truncation"] == t
    assert r["source_frame"]["design_documents"] == r["design_documents"]


def test_no_file_under_input_is_silently_dropped(tmp_path):
    """Every file is read or skipped with a reason, exactly once — including the
    files after the budget, which the old walk never visited."""
    files = {f"input/ctx_{i:02d}.json": json.dumps({"v": "x" * 300}) for i in range(8)}
    files.update({"input/docs/spec.md": "spec", "input/zz.pdf": b"%PDF",
                  "input/oracle/answer.txt": "secret", "input/zz_tail.md": "tail"})
    d = _tree(tmp_path, files)
    r = T.input_text_report(d)
    accounted = r["files_read"] + [s["path"] for s in r["files_skipped"]]
    on_disk = sorted(str(p.relative_to(d / "input"))
                     for p in (d / "input").rglob("*") if p.is_file())
    assert sorted(accounted) == on_disk
    reasons = {s["path"]: s["reason"] for s in r["files_skipped"]}
    assert reasons["zz.pdf"] == T.SKIP_UNSUPPORTED_FORMAT
    assert reasons["oracle/answer.txt"] == T.SKIP_ORACLE_PATH
    assert reasons["zz_tail.md"] == T.SKIP_FRAME_BUDGET
    assert r["truncation"]["left_out"] == sorted(
        p for p, why in reasons.items() if why == T.SKIP_FRAME_BUDGET)


def test_a_design_document_larger_than_the_budget_is_never_cut(tmp_path):
    big = "x" * (CAP + 10)
    d = _tree(tmp_path, {"input/docs/big.md": big, "input/context.md": "ctx"})
    r = T.input_text_report(d)
    first = r["source_frame"]["members"][0]
    assert first["path"] == "docs/big.md" and first["complete"] is True
    assert first["text"] == big and r["chars"] == len(big)
    assert r["truncated"] is True
    assert r["truncation"]["cut"] == [] and r["truncation"]["left_out"] == ["context.md"]
    alone = T.input_text_report(_tree(tmp_path, {"input/docs/big.md": big}, "alone"))
    assert alone["truncated"] is False and alone["truncation"] is None
    assert alone["chars"] == len(big)


def test_a_frame_that_fits_reports_no_truncation(tmp_path):
    d = _tree(tmp_path, {"input/authority.json": json.dumps({"a": 1}),
                         "input/docs/L1.md": "prose"})
    r = T.input_text_report(d)
    assert r["truncated"] is False and r["truncation"] is None
    assert not [s for s in r["files_skipped"] if s["reason"] == T.SKIP_FRAME_BUDGET]
    assert r["files_read"] == ["docs/L1.md", "authority.json"]


def test_order_is_design_documents_then_context_each_sorted(tmp_path):
    d = _tree(tmp_path, {
        "input/aaa.json": "{}", "input/owner_request.md": "owner",
        "input/zzz.md": "z", "input/design_input.txt": "di",
        "input/docs/sub/deep.md": "deep", "input/phase1_prompt.md": "prompt",
        "input/phase1_structured.yaml": "ic_name: x",
    })
    r = T.input_text_report(d)
    assert r["files_read"] == [
        "design_input.txt", "docs/sub/deep.md", "phase1_prompt.md",
        "phase1_structured.yaml", "aaa.json", "owner_request.md", "zzz.md"]
    assert r["design_documents"] == r["files_read"][:4]
    assert T.input_text_report(d) == r


def test_the_skip_account_keeps_plain_sorted_order(tmp_path):
    """Reading the design documents first must not reorder the skip list: it
    is part of the binding, and reordering alone is not a content change."""
    d = _tree(tmp_path, {"input/aa.pdf": b"%PDF", "input/docs/a.pdf": b"%PDF",
                         "input/docs/b.md": "doc", "input/zz.bin": b"\0"})
    r = T.input_text_report(d)
    assert [s["path"] for s in r["files_skipped"]] == ["aa.pdf", "docs/a.pdf", "zz.bin"]


def test_the_design_tier_is_the_d1_judgement_population(tmp_path, monkeypatch):
    """One population, one owner: a path D1's judgement adds to its design
    input moves into the frame's design tier with no change here."""
    d = _tree(tmp_path, {"input/a_context.json": "{}", "input/extra_spec.md": "extra",
                         "input/docs/L1.md": "doc"})
    assert T.input_text_report(d)["design_documents"] == ["docs/L1.md"]
    monkeypatch.setattr(J, "DESIGN_INPUT_GLOBS",
                        J.DESIGN_INPUT_GLOBS + ("input/extra_spec.md",))
    r = T.input_text_report(d)
    assert r["design_documents"] == ["docs/L1.md", "extra_spec.md"]
    assert r["files_read"] == ["docs/L1.md", "extra_spec.md", "a_context.json"]


def test_the_track_record_and_the_agent_handoff_carry_the_truncation(tmp_path):
    d = _adc_shaped(tmp_path)
    rep = T.evaluate(d)
    ri = rep["retrieval_input"]
    assert ri["design_documents"] == ["docs/L1_DATASHEET.md", "docs/L9_CONSTRAINTS.md"]
    assert ri["truncation"]["left_out"] == ["step_0_5ic_answers.json"]
    r = T.input_text_report(d)
    h = T.ai_subtrack(d, r["text"], tmp_path / "pack",
                      source_frame=r["source_frame"])["handoff"]
    assert h["source_frame"]["truncation"] == r["truncation"]
    reading = (tmp_path / "pack" / h["read_design_input_from"]).read_text()
    assert reading.index("DOC_MARKER_ONE") < reading.index("A" * 700)
