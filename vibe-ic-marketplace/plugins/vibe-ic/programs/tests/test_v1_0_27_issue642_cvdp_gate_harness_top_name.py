"""Regression for ORGANIC #642 — module-name conformance vs the CVDP harness
TOPLEVEL.

ROUND-1 (v1.0.27) made the id-derived top name `cvdp_copilot_<stem>` a HARD
harness-top requirement BY DEFAULT (without --prompts). ROUND-2 (field-agent
reopen, v1.0.39) PROVED that premise false for 97% of CVDP problems: the
harness's cocotb TOPLEVEL is the prompt's stated functional `Module Name:`,
NOT the id stem (field-measured 293/302). v1.0.27's hard-block therefore
false-blocked correct completions and directly contradicted the official
scorer (counter-example `cvdp_copilot_16qam_mapper_0001`, top
`qam16_mapper_interpolated`, which the scorer PASSes but the gate BLOCKed).

CORRECTED behaviour (this file pins the v1.0.39 semantics):
  • PROMPT-derived name (filename `rtl/<name>.sv` OR a `Module Name:`
    declaration) is AUTHORITATIVE → a mismatch hard-BLOCKs. This catches both
    the 293/302 `Module Name:` problems and the genuine 9/302
    `rtl/cvdp_copilot_<id>.sv` problems (their stem is prompt-stated).
  • id-DERIVED `cvdp_copilot_<stem>` (used only when NO prompt-derived name is
    available, e.g. the documented --batch-dir flow without --prompts) is
    ADVISORY-only → a mismatch is a WARN note, never a hard BLOCK; the gate
    cannot prove the harness top without prompt evidence.

chip-AGNOSTIC: pure id-string / prompt-prose structure (the CVDP harness's
universal naming scheme); no chip / vendor / SKU literal.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402

_V = "```verilog\n"


def _run(tmp_path, recs, extra=None):
    """Defect-artifact fixture: write a drafts JSONL and run the REAL gate
    (G.main) → (report_records, passed_ids). End state = each record's
    verdict."""
    b = tmp_path / "drafts.jsonl"
    b.write_text("".join(json.dumps(r) + "\n" for r in recs))
    out = tmp_path / "responses.jsonl"
    G.main(["--batch", str(b), "--out", str(out),
            "--report", str(tmp_path / "rep.json")] + (extra or []))
    recs_out = json.loads((tmp_path / "rep.json").read_text())["records"]
    passed = ({json.loads(x)["id"]
               for x in out.read_text().splitlines() if x.strip()}
              if out.is_file() else set())
    return recs_out, passed


def _prompts(tmp_path, mapping):
    p = tmp_path / "prompts.jsonl"
    p.write_text("".join(json.dumps({"id": k, "prompt": v}) + "\n"
                         for k, v in mapping.items()))
    return ["--prompts", str(p)]


# ── (1) the round-2 fix: id-derived mismatch is ADVISORY, not a hard block ────

@NEEDS_SIM
def test_id_derived_mismatch_is_advisory_not_blocked(tmp_path):
    """Without --prompts (the documented --batch-dir flow), a completion whose
    top is the functional name — NOT `cvdp_copilot_<stem>` — must PASS with a
    WARN note. v1.0.27 false-BLOCKed this; the harness top is the prompt's
    Module Name for 293/302, so the id stem cannot hard-block."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_16qam_mapper_0001",
        "completion": _V + "module qam16_mapper_interpolated(input a, "
                           "output b);\n  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_16qam_mapper_0001" in passed
    assert any("module-name-conformance" in n
               for n in recs[0].get("notes", []))
    assert "filename_conformance" not in recs[0]


# ── (2) NEGATIVE no-leak: prompt-derived names still hard-block ───────────────

@NEEDS_SIM
def test_prompt_module_name_mismatch_is_advisory_NOLEAK(tmp_path):
    """ORGANIC #642 round-2 — a `Module Name:` hint is NOT guaranteed to equal
    the hidden harness TOPLEVEL, so a mismatch is ADVISORY (WARN + emit), never
    a hard-BLOCK. The completion is emitted and the scorer arbitrates; the
    potential mismatch is surfaced (not silent)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_foo_0001",
        "completion": _V + "module totally_wrong(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_foo_0001": "### Module Name:\n`expected_top`\n"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_foo_0001" in passed
    assert recs[0].get("filename_conformance") is None
    assert any("module-name-conformance" in n
               for n in recs[0].get("notes", []))


@NEEDS_SIM
def test_filename_pinned_top_is_advisory_NOLEAK(tmp_path):
    """ORGANIC #642 round-2 — a SAVE-FILENAME hint (`rtl/<X>.sv`) is NOT the
    harness TOPLEVEL (cocotb sets it from the module DECLARATION name). Field
    round-2 proved the filename-pinned hard-block false-blocked correct
    answers, so it is now ADVISORY: the completion is emitted with a WARN."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_bus_arbiter_0001":
            "Save your top to rtl/cvdp_copilot_bus_arbiter.sv"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_bus_arbiter_0001" in passed
    assert recs[0].get("filename_conformance") is None
    assert any("module-name-conformance" in n
               for n in recs[0].get("notes", []))


@NEEDS_SIM
def test_prompt_module_name_match_passes_NOLEAK(tmp_path):
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_16qam_mapper_0001",
        "completion": _V + "module qam16_mapper_interpolated(input a, "
                           "output b);\n  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_16qam_mapper_0001":
            "### Module Name:\n`qam16_mapper_interpolated`\n"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_16qam_mapper_0001" in passed


@NEEDS_SIM
def test_correct_id_stem_top_passes_NOLEAK(tmp_path):
    """A completion ALREADY declaring `cvdp_copilot_<stem>` passes (no
    mismatch at all)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module cvdp_copilot_bus_arbiter(input a, output b);"
                           "\n  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_bus_arbiter_0001" in passed


@NEEDS_SIM
def test_doc_only_stays_doc_only_NOLEAK(tmp_path):
    recs, _ = _run(tmp_path, [{
        "id": "cvdp_copilot_bar_0003",
        "completion": "The bug is in the handshake: ready must be deasserted "
                      "while busy. No RTL change to the datapath is required."}])
    assert recs[0]["verdict"] == "PASS_DOC_ONLY"


@NEEDS_SIM
def test_non_cvdp_id_imposes_no_requirement_NOLEAK(tmp_path):
    """A draft id NOT following the cvdp_copilot_ convention imposes no
    id-derived top requirement — the gate behaves exactly as before."""
    recs, passed = _run(tmp_path, [{
        "id": "my_design_42",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "my_design_42" in passed


# ── (3) helper unit: id → id-derived advisory top ─────────────────────────────

@pytest.mark.parametrize("rid,expected", [
    ("cvdp_copilot_bus_arbiter_0001", "cvdp_copilot_bus_arbiter"),
    ("cvdp_copilot_ethernet_parser_0042", "cvdp_copilot_ethernet_parser"),
    # no variant suffix → returned as-is
    ("cvdp_copilot_axis_image_border_gen", "cvdp_copilot_axis_image_border_gen"),
    # name with an embedded number, real variant stripped
    ("cvdp_copilot_axi4_lite_0007", "cvdp_copilot_axi4_lite"),
    # non-CVDP id → no requirement
    ("my_design_42", None),
    ("bus_arbiter", None),
    ("", None),
])
def test_required_top_from_id(rid, expected):
    assert G.required_top_from_id(rid) == expected


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
