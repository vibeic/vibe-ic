"""Regression for ORGANIC #642 round-2 (field-agent reopen) — the CVDP gate's
module-name conformance must match the harness's ACTUAL TOPLEVEL, which is the
prompt's stated `Module Name:` (293/302 problems), not the id stem
`cvdp_copilot_<problem>` (9/302).

THE DEFECT (round-1 v1.0.27): the gate forced the id-derived top
`cvdp_copilot_<stem>` as a HARD requirement BY DEFAULT (no --prompts), so a
completion whose top is the functional `Module Name:` was BLOCKED — false for
97% of CVDP problems and in DIRECT CONTRADICTION with the official scorer. The
field agent's counter-example: `cvdp_copilot_16qam_mapper_0001` declares
`### Module Name: qam16_mapper_interpolated`; the official
`run_benchmark.py --model local_import` (image `cvdp-sim-oss:v110`) PASSes the
`qam16_mapper_interpolated` completion (result=0, 100% pass rate) — yet the
v1.0.27 gate BLOCKed it (emitted=0 → counted as fail). Two root causes:

  (1) `required_module_names_from_prompt()` (#559) recognised ONLY an
      `rtl/<name>.sv` filename pattern, so it missed the `### Module Name:`
      declaration the 293 use → fell through to the id-derived fallback.
  (2) the id-derived fallback HARD-BLOCKed; it must be ADVISORY only because
      the id stem is not the harness top for 293/302.

THE FIX (v1.0.39):
  (1) extend `required_module_names_from_prompt()` to also recognise a
      `Module Name:` declaration (markdown `### Module Name:` /
      `**Module Name**:` / plain, with a backtick-quoted or plain identifier);
  (2) id-derived `cvdp_copilot_<stem>` mismatch → WARN note, never a hard
      BLOCK; ONLY a PROMPT-derived name (filename OR `Module Name:`) may
      hard-block.

This is a guard-CORRECTION (un-block the 293) that simultaneously STRENGTHENS
the real catch surface: the `Module Name:` extractor now lets the gate catch a
genuine wrong-named completion at gate time (prompt-derived hard-block) where
v1.0.27 could only do so via the OPTIONAL `rtl/<name>.sv` filename pattern.

chip-AGNOSTIC: pure id-string / prompt-prose structure (the CVDP harness's
universal naming scheme); no chip / vendor / SKU literal.
"""
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402
importlib.reload(G)

_V = "```verilog\n"

# The end-state tests below drive the REAL gate via `G.main`, which by DESIGN
# refuses (rc=2, writes NOTHING) when `iverilog` (#528) or `yosys` (#604) is
# absent — that refusal is the anti-false-PASS guard, not a defect. Without
# this precondition the helper below read a report the gate deliberately never
# wrote and raised a misleading FileNotFoundError instead of reporting an
# unmet environment requirement. Same idiom as the sibling cvdp_gate suites
# (test_v1_0_74_issue715 / test_v1_0_79_issue734). The `Module Name:`
# extractor tests (root cause #1) are PURE and stay unconditional.
HAVE_GATE_TOOLS = (shutil.which("iverilog") is not None
                   and shutil.which("yosys") is not None)


def _run(tmp_path, recs, extra=None):
    """Run the REAL gate (G.main) on a drafts JSONL → (report_records,
    passed_ids). End state = each record's verdict + whether it was emitted
    to the scoring responses JSONL."""
    if not HAVE_GATE_TOOLS:
        pytest.skip("iverilog/yosys not available — the gate refuses to emit "
                    "(#528/#604), so its end state cannot be observed")
    b = tmp_path / "drafts.jsonl"
    b.write_text("".join(json.dumps(r) + "\n" for r in recs))
    out = tmp_path / "responses.jsonl"
    _extra = list(extra or [])
    if not any(a in _extra for a in ("--prompts", "--dataset")):
    # These fixtures deliberately run the gate with its spec guards
    # OFF; since 2026-08-25 that must be SAID, not implied by silence.
        _extra.append("--without-spec-guards")
    G.main(["--batch", str(b), "--out", str(out),
            "--report", str(tmp_path / "rep.json")] + _extra)
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


# ── (A) root cause #1: the `Module Name:` extractor was blind ─────────────────

@pytest.mark.parametrize("prompt,expected", [
    # the field-agent's exact reproduction
    ("Design a combinational module.\n\n### Module Name:\n`foo_func`\n",
     "foo_func"),
    # the real CVDP counter-example shape (no rtl/<name>.sv line at all)
    ("### Module Name:\n`qam16_mapper_interpolated`\n",
     "qam16_mapper_interpolated"),
    ("**Module Name**: `bar_top`\n", "bar_top"),
    ("Module Name: baz\n", "baz"),
    ("### Module Name\n\n`dut_name`\n", "dut_name"),
])
def test_module_name_declaration_now_recognized(prompt, expected):
    """`required_module_names_from_prompt` must recognise a `Module Name:`
    declaration, not only the `rtl/<name>.sv` filename pattern. (The
    field-agent's acceptance probe: extractor must return {'foo_func'}.)"""
    assert expected in G.required_module_names_from_prompt(prompt)


def test_module_name_extractor_does_not_overmatch_prose():
    """No `Module Name:` adjacency → no spurious required name (must not
    over-fire and re-introduce false blocks)."""
    assert G.required_module_names_from_prompt(
        "The module has a name field in its CSR register map.") == set()
    assert G.required_module_names_from_prompt(
        "Design a 4-bit synchronous counter.") == set()


def test_filename_extractor_still_works():
    """#559 filename path is preserved alongside the new `Module Name:`
    path."""
    assert G.required_module_names_from_prompt(
        "Save it to rtl/foo_bar.sv.") == {"foo_bar"}


# ── (B) THE FIX: id-derived mismatch is ADVISORY (PASS + WARN), not BLOCK ──────

@NEEDS_SIM
def test_id_derived_mismatch_passes_with_warn_no_prompts(tmp_path):
    """The documented --batch-dir flow (no --prompts): a completion declaring
    the functional top — NOT `cvdp_copilot_<stem>` — must PASS (emitted) with
    an advisory WARN note. v1.0.27 false-BLOCKed this and contradicted the
    scorer for 97% of problems."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_16qam_mapper_0001",
        "completion": _V + "module qam16_mapper_interpolated(input a, "
                           "output b);\n  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_16qam_mapper_0001" in passed
    assert any("module-name-conformance" in n
               for n in recs[0].get("notes", []))
    # advisory → no hard-block field recorded
    assert "filename_conformance" not in recs[0]


@NEEDS_SIM
def test_id_derived_advisory_note_is_clearly_advisory(tmp_path):
    """The WARN must SAY it is advisory (the id stem is not the harness top
    for ~97%) so a reader is not misled into thinking it is a real failure."""
    recs, _ = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}])
    note = " ".join(recs[0].get("notes", []))
    assert "advisory" in note


# ── (C) STRENGTHEN + NO-LEAK: prompt-derived names still hard-block ───────────

@NEEDS_SIM
def test_module_name_mismatch_is_advisory_not_block(tmp_path):
    """ORGANIC #642 round-2 — a name hint mismatch is ADVISORY (WARN + emit),
    NOT a hard-BLOCK. Even a `Module Name:` hint is not guaranteed to equal the
    hidden harness TOPLEVEL (field round-2: 7/302 correct answers were
    false-blocked this way), so the gate must emit and let the scorer arbitrate.
    Prompt hints `expected_top`; completion declares `wrong_top` → PASS + WARN,
    emitted (the scorer ELAB_ERRORs it if it's a real mismatch — same outcome
    as blocking, but a PASSING answer is never discarded)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_foo_0007",
        "completion": _V + "module wrong_top(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_foo_0007": "### Module Name:\n`expected_top`\n"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_foo_0007" in passed
    # the potential mismatch is surfaced advisory (NOT silent), never blocked
    assert recs[0].get("filename_conformance") is None
    assert any("module-name-conformance" in n and "expected_top" in n
               for n in recs[0].get("notes", []))


@NEEDS_SIM
def test_module_name_match_passes(tmp_path):
    """NO-LEAK: the correctly-named completion for the same prompt PASSes
    (the corrected gate is not a blanket block)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_foo_0007",
        "completion": _V + "module expected_top(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_foo_0007": "### Module Name:\n`expected_top`\n"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_foo_0007" in passed


@NEEDS_SIM
def test_filename_pinned_top_is_advisory_not_block(tmp_path):
    """ORGANIC #642 round-2 — a SAVE-FILENAME hint (`rtl/<X>.sv`) is NOT the
    harness TOPLEVEL (the cocotb harness sets TOPLEVEL from the module
    DECLARATION name, often != the filename stem). Field round-2 proved the
    filename-pinned hard-block false-blocked correct answers, so it is now
    ADVISORY too: the completion is emitted with a WARN, and the scorer
    arbitrates. A genuine mismatch is still surfaced (advisory, not silent)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module bus_arbiter(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_bus_arbiter_0001":
            "Implement and save to rtl/cvdp_copilot_bus_arbiter.sv"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_bus_arbiter_0001" in passed
    assert recs[0].get("filename_conformance") is None
    # the potential mismatch is surfaced advisory (NOT silent)
    assert any("module-name-conformance" in n
               and "cvdp_copilot_bus_arbiter" in n
               for n in recs[0].get("notes", []))


@NEEDS_SIM
def test_prompts_advisory_flag_still_passes(tmp_path):
    """ORGANIC #642 round-2 — `--prompts-advisory` is retained for compat and
    still yields PASS + WARN (conformance is now always advisory regardless of
    the flag)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_foo_0008",
        "completion": _V + "module wrong_top(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_foo_0008": "### Module Name:\n`expected_top`\n"})
        + ["--prompts-advisory"])
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_foo_0008" in passed
    assert any("module-name-conformance" in n
               for n in recs[0].get("notes", []))


@NEEDS_SIM
def test_non_cvdp_id_no_requirement(tmp_path):
    """NO-LEAK: a draft id NOT following the cvdp_copilot_ convention imposes
    no id-derived requirement (gate behaves as before)."""
    recs, passed = _run(tmp_path, [{
        "id": "my_design_42",
        "completion": _V + "module whatever(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}])
    assert recs[0]["verdict"] == "PASS"
    assert "my_design_42" in passed
    assert recs[0].get("notes", []) == [] or not any(
        "module-name-conformance" in n for n in recs[0].get("notes", []))


@NEEDS_SIM
def test_doc_only_unaffected(tmp_path):
    """NO-LEAK: a doc-only completion stays doc_only (no module-name path
    fires)."""
    recs, _ = _run(tmp_path, [{
        "id": "cvdp_copilot_bar_0009",
        "completion": "The fix is to deassert ready while busy is high. No "
                      "datapath RTL change is needed for this problem."}])
    assert recs[0]["verdict"] == "PASS_DOC_ONLY"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
