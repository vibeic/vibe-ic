#!/usr/bin/env python3
"""ORGANIC #642 ROUND-2 — CVDP-gate name-conformance is ADVISORY (WARN), never
a hard-BLOCK.

Field-agent reopen (round-2): the v1.0.39 fix removed the id-derived
over-block (146→0) but a RESIDUAL false-block path survived — the gate treated
the prompt's SAVE-FILENAME stem `rtl/<X>.sv` (and any prose name hint) as the
required harness top. But the CVDP harness's cocotb TOPLEVEL is fixed by the
HIDDEN test harness from the module DECLARATION name, which is NOT reliably the
filename stem (field measured 7/302 correct answers with filename-stem !=
module-name == harness TOPLEVEL == scorer PASS, yet hard-blocked and dropped
from the scoring set, e.g. cont_adder_0006: file `rtl/cont_adder_top.sv`,
module `continuous_adder`).

§4.05 asymmetry: a false-BLOCK discards a PASSING answer irreversibly, whereas
a genuine module mismatch is emitted-and-WARNed and the SCORER ELAB_ERRORs it
anyway (identical final outcome). So the gate cannot prove the harness TOPLEVEL
and must NOT hard-block on name-conformance — it surfaces an advisory WARN and
ALWAYS emits; the scorer is the sole arbiter.

ACCEPTANCE (the field-agent's exact reproduction): a prompt that says
`Modify the existing `bar_core`` + saves to `rtl/foo_top.sv`, completion
`module bar_core` → emitted=1 (was BLOCKED/emitted=0), verdict PASS + advisory
WARN.

NO-LEAK: a genuine module mismatch is still SURFACED (advisory WARN, not
silent) and emitted — the scorer arbitrates (a wrong TOPLEVEL ELAB_ERRORs).

chip-AGNOSTIC: pure id-string / prompt-prose structure; no chip/vendor/SKU
literal.
"""
import importlib
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "benchmark"))
import cvdp_gate as G  # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402
importlib.reload(G)

_V = "```verilog\n"


def _run(tmp_path, recs, extra=None):
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


# ── ACCEPTANCE: filename-stem != module name → emitted (advisory) ───────────
@NEEDS_SIM
def test_filename_vs_module_name_emits_with_warn(tmp_path):
    """The field-agent's exact repro: save-file `rtl/foo_top.sv`, module
    `bar_core`. v1.0.40 BLOCKED (emitted=0); round-2 → PASS + WARN, emitted."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_zzz_0001",
        "completion": _V + "module bar_core(input a, output y);\n"
                           "  assign y = ~a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_zzz_0001":
            "Modify the existing `bar_core` RTL.\nConsider the following "
            "content for the file rtl/foo_top.sv:\n```\nmodule bar_core("
            "input a, output y); endmodule\n```\nYour response will be saved "
            "directly to: rtl/foo_top.sv\n"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_zzz_0001" in passed          # emitted=1
    assert recs[0].get("filename_conformance") is None  # never hard-blocked
    assert any("module-name-conformance" in n
               for n in recs[0].get("notes", []))     # advisory, not silent


# ── the 7-case pattern: module name == harness top, filename differs ────────
@NEEDS_SIM
def test_correct_module_name_with_different_filename_emits(tmp_path):
    """cont_adder_0006 class: file `rtl/cont_adder_top.sv`, the harness top is
    the module `continuous_adder` (which the completion declares). It must be
    emitted — the filename stem is not the TOPLEVEL."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_cont_adder_0006",
        "completion": _V + "module continuous_adder(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_cont_adder_0006":
            "Modify the existing `continuous_adder` RTL code.\nConsider the "
            "following content for the file rtl/cont_adder_top.sv:\n"}))
    assert recs[0]["verdict"] == "PASS"
    assert "cvdp_copilot_cont_adder_0006" in passed


# ── NO-LEAK: a genuine mismatch is still surfaced (advisory) + emitted ──────
@NEEDS_SIM
def test_noleak_genuine_mismatch_surfaced_and_emitted(tmp_path):
    """A completion whose module disagrees with every prompt name hint is NOT
    silently passed: it carries an advisory WARN (so a reviewer/scorer sees the
    potential TOPLEVEL mismatch) AND is emitted so the scorer arbitrates (a
    real wrong TOPLEVEL ELAB_ERRORs → counted fail, same as a block)."""
    recs, passed = _run(tmp_path, [{
        "id": "cvdp_copilot_bus_arbiter_0001",
        "completion": _V + "module totally_unrelated(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_bus_arbiter_0001":
            "Implement and save to rtl/cvdp_copilot_bus_arbiter.sv"}))
    assert recs[0]["verdict"] == "PASS"          # emitted, not blocked
    assert "cvdp_copilot_bus_arbiter_0001" in passed
    notes = recs[0].get("notes", [])
    assert any("module-name-conformance" in n for n in notes)  # not silent


# ── never a hard-block: filename_conformance is never set on a name mismatch ─
@NEEDS_SIM
def test_name_conformance_never_hard_blocks(tmp_path):
    recs, _ = _run(tmp_path, [{
        "id": "cvdp_copilot_foo_0099",
        "completion": _V + "module wrong_name(input a, output b);\n"
                           "  assign b = a;\nendmodule\n```\n"}],
        extra=_prompts(tmp_path, {
            "cvdp_copilot_foo_0099": "### Module Name:\n`expected_top`\n"}))
    assert recs[0]["verdict"] != "BLOCKED"
    assert recs[0].get("filename_conformance") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
