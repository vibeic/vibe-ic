"""Regression for ORGANIC #642 — cvdp_gate compiles without the official
harness top-module flag (`-s cvdp_copilot_<problem>`), so a completion whose
top module is named differently passes the gate but ELAB-fails at scoring with
"cannot find top".

現象 (round-1 v1.0.0/v1.0.23 CVDP nonagentic no_commercial, 302): the official
cocotb harness elaborates each completion with
`iverilog -o sim.vvp -s cvdp_copilot_<problem> ... rtl/cvdp_copilot_<problem>.sv`,
i.e. it FORCES the top module to be `cvdp_copilot_<problem>`. cvdp_gate's own
compile gate did NOT replicate that top selection (the #559 module-name check
was gated behind an OPTIONAL --prompts arg the documented --batch-dir flow does
not pass). So a completion declaring its top under the short/functional prose
name (e.g. `module bus_arbiter`) compiled clean at the gate (verdict PASS) but
the harness's `-s cvdp_copilot_bus_arbiter` could not find that top → exit 1 →
ELAB_ERROR at scoring. All 9 ELAB_ERROR problems declared a top WITHOUT the
`cvdp_copilot_` prefix; the gate marked every one PASS. Same gate-compile !=
scorer-compile class as the fence-emit gap #626.

Fix: derive the harness-required top name `cvdp_copilot_<stem>` from the draft
id (strip a trailing `_NNNN` variant suffix) and enforce the #559 module-name
conformance BY DEFAULT (no --prompts needed) — a completion whose top is not
named `cvdp_copilot_<stem>` is BLOCKED at the gate instead of shipped to ELAB.

NEGATIVE no-leak: (a) a completion ALREADY declaring the correct
`cvdp_copilot_<stem>` top passes unchanged; (b) a multi-module completion that
declares the correct top (even as a sub-module) passes; (c) a doc_only
completion stays doc_only; (d) a NON-CVDP id (no `cvdp_copilot_` prefix)
imposes no id-derived requirement (gate behaves as before); (e) --prompts-
advisory WARNs instead of blocking.

chip-AGNOSTIC: pure id-string structure (the CVDP harness's universal naming
scheme); no chip / vendor / SKU literal.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

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


# ── (1) the fix: a wrong-named top is BLOCKED (no --prompts) ──────────────────

def test_wrong_top_name_blocked_by_default(tmp_path):
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "BLOCKED"
    assert "cvdp_copilot_bus_arbiter_0001" not in passed
    assert "cvdp_copilot_bus_arbiter" in recs[0].get("filename_conformance", "")


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

def test_correct_top_name_passes_NOLEAK(tmp_path):
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module cvdp_copilot_bus_arbiter(input a, output b);"
                           "\n  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_bus_arbiter_0001" in passed


def test_multi_module_with_correct_top_passes_NOLEAK(tmp_path):
    """The harness `-s` can select a declared module even if it is not the
    syntactic last module — so a completion that DECLARES the required top
    (alongside helpers) passes."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_foo_0002",
        "completion": _V + "module helper(input x, output y); assign y=x; "
                           "endmodule\nmodule cvdp_copilot_foo(input a, "
                           "output b); helper h(a,b); endmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"


def test_doc_only_stays_doc_only_NOLEAK(tmp_path):
    recs, _ = _run(tmp_path, [{
        "id": "cvdp_copilot_bar_0003",
        "completion": "The bug is in the handshake: ready must be deasserted "
                      "while busy. No RTL change to the datapath is required."}])
    assert recs[0]["verdict"] == "PASS_DOC_ONLY"


def test_non_cvdp_id_imposes_no_requirement_NOLEAK(tmp_path):
    """A draft id NOT following the cvdp_copilot_ convention imposes no
    id-derived top requirement — the gate behaves exactly as before."""
    recs, passed = _run(tmp_path, [{
        "id": "my_design_42",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "my_design_42" in passed


def test_advisory_mode_warns_not_blocks_NOLEAK(tmp_path):
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=["--prompts-advisory"])
    assert recs[0]["verdict"] == "PASS"
    assert any("filename-module-mismatch" in n
               for n in recs[0].get("notes", []))


# ── (3) helper unit: id → required harness top ───────────────────────────────

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
