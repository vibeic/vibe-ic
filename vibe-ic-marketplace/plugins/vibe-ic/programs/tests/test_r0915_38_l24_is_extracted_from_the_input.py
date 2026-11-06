"""R-0915-38: phase 1 EXTRACTS L24 from the input's own sign-off statements.

MEASURED 2026-09-15 (lane icspm3) on `spm` x gf180mcuD. R-0915-36 left L24
APPLICABLE because the design's input genuinely carries its subject -- 24
word-bounded hits across five of nine documents -- and the layer was still a
skeleton, so `l24_signoff_evidence_backed_check` kept blocking and P0 stopped
at 1. The layer was the gap, not the gate.

Phase 1 now reads those same documents and fills L24 with what they STATE::

    DRC      clean          input/docs/L1_product_metadata.md:46
    LVS      clean          input/docs/L1_product_metadata.md:46
    antenna  percent_clean  input/docs/L7_verification_plan.md:82
    STA      met            input/docs/L1_product_metadata.md:46
    IR_drop / EM / tapeout_precheck  -- searched, not stated

REQUIREMENTS, NEVER STATUSES. L24's `*_status` fields are phase-3 OUTCOMES,
and this gate treats any `*_status` / `status` / `verdict` / `result` key at
any depth as a CLAIM needing an in-project evidence path. Phase 1 runs before
DRC exists, so filling them would publish a certificate for a check that has
not run -- turning the layer from inert to FAILING. The requirement rows
therefore carry none of those key names, and the outcome fields stay null.

THE CLAUSE RULE IS THE LOAD-BEARING PART, and it is a bug this file caught: an
input line reading "DRC clean, LVS clean, STA met" states THREE requirements,
and the first implementation scanned the whole line and handed the first match
to all three -- STA came back `clean`, which the input never says. The clause
runs from a check's own token to the next check's token.

chip-AGNOSTIC: synthetic projects in tmp_path; no design, PDK or vendor name.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import l24_signoff_requirements_extract as X  # noqa: E402
import phase1_post_process as P  # noqa: E402
import _path_layout as PL  # noqa: E402


def _project(tmp_path, **docs):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        stem, _, suffix = name.rpartition("_")
        (d / f"{stem}.{suffix}").write_text(text, encoding="utf-8")
    return tmp_path


def _rows(project):
    out = X.extract_signoff_requirements(project)
    return {r["check"]: r for r in out["signoff_requirements"]}


def _emit_l24(project):
    doc = P.emit_l_doc_skeleton("L24", "unknown", project_dir=project)
    doc.pop("evidence", None)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L24_SIGNOFF.json").write_text(json.dumps(doc, indent=1))
    return doc


def _report(project, rel, payload):
    p = project / "reports" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))
    return p


# ── the extractor reads what the input states ────────────────────────────

def test_a_stated_requirement_is_extracted_with_its_citation(tmp_path):
    proj = _project(tmp_path, spec_md=(
        "# Plan\n\nThe part must sign off with DRC clean on the target PDK.\n"))
    row = _rows(proj)["DRC"]
    assert row["stated"] is True
    assert row["requirement"] == "clean"
    assert row["citation"]["document"] == "input/docs/spec.md"
    assert row["citation"]["line"] == 3
    assert "DRC" in row["citation"]["text"]


def test_one_line_stating_three_checks_gives_three_requirements(tmp_path):
    """THE REGRESSION CONTROL. Scanning the whole line made STA `clean`."""
    proj = _project(tmp_path, spec_md=(
        "Must sign off: DRC clean, LVS clean, STA met.\n"))
    rows = _rows(proj)
    assert rows["DRC"]["requirement"] == "clean"
    assert rows["LVS"]["requirement"] == "clean"
    assert rows["STA"]["requirement"] == "met", (
        "the clause must stop at the next check's token")


def test_a_check_the_input_never_mentions_is_searched_not_invented(tmp_path):
    proj = _project(tmp_path, spec_md="DRC clean is required.\n")
    row = _rows(proj)["EM"]
    assert row["stated"] is False
    assert row["requirement"] is None
    assert row["citation"] is None
    assert row["searched"]["documents"] == ["input/docs/spec.md"]
    assert row["searched"]["spellings"], "must say what it looked for"


def test_a_check_named_without_a_requirement_word_keeps_it_null(tmp_path):
    """The extractor does not guess what "DRC" alone was supposed to demand."""
    proj = _project(tmp_path, spec_md="Section 4 discusses DRC.\n")
    row = _rows(proj)["DRC"]
    assert row["stated"] is True
    assert row["requirement"] is None
    assert row["citation"]["line"] == 1


def test_a_corner_named_inside_the_clause_is_attributed(tmp_path):
    proj = _project(tmp_path, spec_md="STA met at SS and FF corners.\n")
    assert _rows(proj)["STA"]["corners"] == ["FF", "SS"]


def test_a_threshold_stated_in_the_clause_is_captured(tmp_path):
    proj = _project(tmp_path, spec_md="IR drop must stay under 50 mV.\n")
    row = _rows(proj)["IR_drop"]
    assert row["stated"] is True
    assert row["threshold"] == {"value": 50.0, "unit": "mV"}


def test_lvs_engines_are_aggregated_from_the_input_citations(tmp_path):
    proj = _project(tmp_path,
                    plan_md="| LVS | 100% clean(magic + netgen) |\n",
                    constraints_md="- ✅ LVS clean(magic + netgen)\n")
    row = _rows(proj)["LVS"]
    assert row["engines"] == ["magic", "netgen"], row
    assert row["requirement"] == "clean"
    assert row["all_citations"] == [
        {"document": "input/docs/constraints.md", "line": 1},
        {"document": "input/docs/plan.md", "line": 1}]


def test_gds_xor_zero_difference_is_a_typed_input_requirement(tmp_path):
    proj = _project(tmp_path, plan_md=(
        "| GDS XOR(magic vs klayout) | 0 difference |\n"))
    rows = _rows(proj)
    row = rows.get("GDS_XOR")
    assert row is not None, rows
    assert row["stated"] is True
    assert row["requirement"] == "zero_difference", row
    assert row["threshold"] == {"value": 0.0, "unit": "difference"}
    assert row["engines"] == ["klayout", "magic"]
    assert row["citation"] == {
        "document": "input/docs/plan.md", "line": 1,
        "text": "| GDS XOR(magic vs klayout) | 0 difference |",
        "clause": "GDS XOR(magic vs klayout) | 0 difference |"}
    assert X.report_tokens_for("GDS_XOR") == ("gds_xor",)


def test_the_normal_emitter_extracts_a_gds_xor_only_input(tmp_path):
    proj = _project(tmp_path, plan_md=(
        "GDS XOR(magic vs klayout) requires 0 differences.\n"))
    doc = _emit_l24(proj)
    assert doc["extraction_status"] == "EXTRACTED", doc
    assert doc["applicability"] == "APPLICABLE"
    rows = {r["check"]: r for r in doc["fields"]["signoff_requirements"]}
    assert rows["GDS_XOR"]["threshold"] == {"value": 0.0, "unit": "difference"}
    for key in ("drc_status", "lvs_status", "sta_status", "ir_drop_status",
                "antenna_status"):
        assert doc["fields"][key] is None
    assert doc["fields"]["tapeout_gates"] == []
    for row in rows.values():
        assert not {"status", "verdict", "result"}.intersection(row)


def test_engine_and_difference_associations_stop_at_the_next_check(tmp_path):
    proj = _project(tmp_path, plan_md=(
        "DRC clean (Magic + KLayout), LVS clean (Magic + Netgen), "
        "GDS XOR(Magic vs KLayout) 0 difference.\n"))
    rows = _rows(proj)
    assert rows["LVS"]["engines"] == ["magic", "netgen"], rows
    assert rows["DRC"]["engines"] == ["klayout", "magic"]
    assert rows["LVS"]["threshold"] is None
    assert rows["DRC"]["threshold"] is None
    assert rows["GDS_XOR"]["engines"] == ["klayout", "magic"]
    assert rows["GDS_XOR"]["requirement"] == "zero_difference"


@pytest.mark.parametrize("text", [
    "DRC clean (Magic + KLayout), LVS clean (Magic + Netgen).\n",
    "The logic XOR gate has 0 differences in its truth table.\n",
    "The gdshader XOR operation is discussed here.\n",
    "GDS XOR(Magic vs KLayout) is not required to have 0 differences.\n",
    "No GDS XOR(Magic vs KLayout) requirement: 0 differences is an example.\n",
])
def test_missing_or_denied_gds_xor_is_not_a_requirement(tmp_path, text):
    rows = _rows(_project(tmp_path, plan_md=text))
    row = rows.get("GDS_XOR")
    assert row is not None, rows
    assert row["stated"] is False, row
    assert row["requirement"] is None
    assert row["threshold"] is None
    assert row["citation"] is None
    assert row["searched"]["documents"] == ["input/docs/plan.md"]


@pytest.mark.parametrize("text,threshold,requirement", [
    ("GDS XOR(Magic vs KLayout) is discussed.\n", None, None),
    ("GDS XOR(Magic vs KLayout) requires 5 differences.\n",
     {"value": 5.0, "unit": "difference"}, None),
    ("GDS XOR(Magic vs KLayout) requires zero differences.\n",
     {"value": 0.0, "unit": "difference"}, "zero_difference"),
    ("LVS is not required; GDS XOR(Magic vs KLayout) requires 0 differences.\n",
     {"value": 0.0, "unit": "difference"}, "zero_difference"),
])
def test_gds_xor_does_not_invent_a_zero_threshold(tmp_path, text, threshold,
                                               requirement):
    rows = _rows(_project(tmp_path, plan_md=text))
    row = rows.get("GDS_XOR")
    assert row is not None, rows
    assert row["stated"] is True
    assert row["threshold"] == threshold, row
    assert row["requirement"] == requirement, row


@pytest.mark.parametrize("decoy", [
    "The state machine holds status bits.\n",
    "Installation notes follow.\n",
    "A constant is stated in the table.\n",
])
def test_the_batch4_decoys_stay_decoys(tmp_path, decoy):
    """Word-bounded throughout: `STA` must not fire inside state/stated/
    installation here either."""
    proj = _project(tmp_path, spec_md=decoy)
    assert _rows(proj)["STA"]["stated"] is False, decoy


# ── the extractor refuses rather than guessing ───────────────────────────

def test_no_project_extracts_nothing():
    assert X.extract_signoff_requirements(None) is None


def test_no_input_document_extracts_nothing(tmp_path):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    assert X.extract_signoff_requirements(tmp_path) is None


def test_a_binary_only_corpus_extracts_nothing(tmp_path):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / "layout.gds").write_bytes(b"\x00\x01")
    assert X.extract_signoff_requirements(tmp_path) is None


# ── the emitted layer ────────────────────────────────────────────────────

def test_the_layer_is_EXTRACTED_and_asserts_no_status(tmp_path):
    proj = _project(tmp_path, spec_md="Sign-off: DRC clean, LVS clean.\n")
    doc = _emit_l24(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "EXTRACTED"
    f = doc["fields"]
    for key in ("drc_status", "lvs_status", "sta_status", "ir_drop_status",
                "antenna_status"):
        assert f[key] is None, f"{key} must stay a phase-3 outcome"
    assert f["tapeout_gates"] == []
    assert [r["check"] for r in f["signoff_requirements"] if r["stated"]] == [
        "DRC", "LVS"]


def test_an_input_with_no_signoff_statement_stays_unknown(tmp_path):
    """Silence is not a source-bound declaration that sign-off is absent."""
    proj = _project(tmp_path, spec_md="It multiplies two numbers.\n")
    doc = _emit_l24(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "EXTRACTED"
    assert not any(row["stated"]
                   for row in doc["fields"]["signoff_requirements"])
    assert "applicability_evidence" not in doc


def test_explicit_source_bound_signoff_refusal_is_declared_absent(tmp_path):
    proj = _project(
        tmp_path,
        spec_md="Tape-out and sign-off are not applicable to this model.\n")
    doc = _emit_l24(proj)
    assert doc["applicability"] == "NOT_APPLICABLE"
    assert doc["extraction_status"] == "DECLARED_ABSENT_FROM_INPUT"
    assert doc["rationale"].strip(), "the stub must say WHY"
    assert doc["applicability_evidence"]["literal"].startswith("Tape-out")

    # AND THE CONTROL: strip the rationale back out and the same layer FAILS,
    # which is what R-0915-36 shipped and the roster hid.
    path = proj / "phase1" / "generated_docs" / "L24_SIGNOFF.json"
    doc.pop("rationale")
    path.write_text(json.dumps(doc, indent=1))


def test_qualified_signoff_prefix_cannot_hide_mandatory_tapeout(tmp_path):
    proj = _project(tmp_path, spec_md=(
        "Sign-off is not required before RTL generation, but is mandatory "
        "before tape-out.\n"))
    doc = _emit_l24(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert "applicability_evidence" not in doc


def test_activity_scoped_signoff_refusal_stays_applicable(tmp_path):
    proj = _project(
        tmp_path,
        spec_md="Sign-off is not required for this RTL simulation.\n")
    doc = _emit_l24(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert "applicability_evidence" not in doc


def test_structured_self_tapeout_die_is_applicable_even_without_doc_keywords(
        tmp_path):
    proj = _project(tmp_path, spec_md="An eight-bit counter.\n")
    decl = proj / "input" / "submission_template" / "tapeout_declaration.json"
    decl.parent.mkdir(parents=True)
    decl.write_text(json.dumps({
        "schema": "vibe-ic/tapeout_declaration/1",
        "answers": {"deliverable": "DIE"},
        "answer_provenance": {
            "deliverable": {"answered_by": "owner", "citation": "fixture"},
        },
    }))
    doc = _emit_l24(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "EXTRACTED"
    assert not any(row["stated"]
                   for row in doc["fields"]["signoff_requirements"])


def test_malformed_tapeout_declaration_does_not_authorize_absence(tmp_path):
    proj = _project(tmp_path, spec_md="An eight-bit counter.\n")
    decl = proj / "input" / "submission_template" / "tapeout_declaration.json"
    decl.parent.mkdir(parents=True)
    decl.write_text('{"answers":{"deliverable":42}}')
    doc = _emit_l24(proj)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "EXTRACTED"
    assert not any(row["stated"]
                   for row in doc["fields"]["signoff_requirements"])


# ── the gate judges the run against the requirements ─────────────────────

def _phase3_ran(proj):
    """Mark the run as having reached the phase that MEASURES sign-off."""
    netlist = proj / "phase2/stage2/synth/netlist_yosys.v"
    netlist.parent.mkdir(parents=True, exist_ok=True)
    netlist.write_text("module chip; endmodule\n")
    _report(proj, "orchestrator/phase3_one_shot.json", {
        "verdict": "PASS",
        "phase2_synth": PL.phase2_synth_input_identity(proj),
        "phase3_inputs": PL.phase3_signoff_input_identity(proj),
    })
    return proj


def _proj_requiring_drc(tmp_path):
    proj = _project(tmp_path, spec_md="Sign-off requires DRC clean.\n")
    _emit_l24(proj)
    return _phase3_ran(proj)


# ── the deadlock, and the control that holds it shut ─────────────────────
