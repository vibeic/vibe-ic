"""ORGANIC #715 round-2 — multi-file completeness must NOT over-fire on a
prompt `input.context`-provided context module (field-agent reopen of v1.0.77).

ROUND-1 (#715, v1.0.74) blocked a completion that instantiates a prompt-REQUIRED
module no emitted file defines. But it conflated a context module the prompt's
`input.context` ALREADY PROVIDES (the harness compiles it alongside the author's
file) with a dropped AUTHOR file. The reopen repro: `gf_multiplier_0013` has
`input.context` = {rtl/gf_multiplier.sv}; the author correctly writes a top
`gf_mac` instantiating that context module — yet round-1 BLOCKed it as
"multi-file INCOMPLETE: instantiates prompt-required module(s) ['gf_multiplier']".
5 scorer-PASSing problems (elevator_control_0009/0033/0036, gf_multiplier_0013,
scrambler_0018) were false-blocked (302: 301/302 → 296/302).

ROUND-2 FIX: exclude `input.context`-provided module stems (context_modules)
from the block set; the gate loads them per-id via `_load_context_modules` from
the prompts/dataset `input.context`.

§4.05 NO-LEAK (load-bearing): a context-provided module is NEVER blocked
(negative); an author-defined module that is required, instantiated, undefined,
AND not context-provided (ping_pong's dual_port_memory) STILL blocks (positive).
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS.parent / "benchmark"))
import cvdp_gate as G  # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402

# the gf_multiplier_0013 shape from the reopen: author writes top `gf_mac`,
# instantiates the context-provided `gf_multiplier`.
_GF_TOP = ("module gf_mac(input clk, input [7:0] a, input [7:0] b,\n"
           "             output [7:0] y);\n"
           "  gf_multiplier u_mul (.a(a), .b(b), .y(y));\n"
           "endmodule\n")
_GF_PROMPT = ("Implement a multiply-accumulate `gf_mac`. Module Name: gf_mac. "
              "It instantiates gf_multiplier (provided in rtl/gf_multiplier.sv).")


def test_context_module_names_stem_parse():
    ctx = G.context_module_names({"rtl/gf_multiplier.sv": "...",
                                  "verif/tb_gf.sv": "...",
                                  "docs/spec.md": "..."})
    # only RTL-extension files name a module; docs/spec.md is excluded
    assert ctx == {"gf_multiplier", "tb_gf"}
    # list form also accepted
    assert G.context_module_names(["rtl/foo.v"]) == {"foo"}
    assert G.context_module_names(None) == set()


def test_noleak_context_provided_module_not_blocked():
    """§4.05 NEGATIVE: gf_multiplier is provided by input.context → NOT blocked
    (the round-2 over-fire fix)."""
    ctx = G.context_module_names({"rtl/gf_multiplier.sv": "module gf_multiplier; endmodule"})
    comp = json.dumps({"code": [{"rtl/gf_mac.sv": _GF_TOP}]})
    block, warn = G.multifile_incompleteness(comp, _GF_PROMPT,
                                             context_modules=ctx)
    assert block == [], block
    # also not nagged as a warn (it is a known context module)
    assert "gf_multiplier" not in warn


def test_positive_author_dropped_file_still_blocks():
    """§4.05 POSITIVE: ping_pong's dual_port_memory is author-defined, required,
    instantiated, undefined, and NOT context-provided → STILL blocks."""
    top = ("module ping_pong_buffer(input clk);\n"
           "  dual_port_memory u_m (.clk(clk));\nendmodule\n")
    comp = json.dumps({"code": [{"rtl/ping_pong_buffer.sv": top}]})
    prompt = ("Save it to rtl/ping_pong_buffer.sv and a file named "
              "dual_port_memory.sv. Module Name: ping_pong_buffer")
    block, _ = G.multifile_incompleteness(comp, prompt, context_modules=set())
    assert block == ["dual_port_memory"]
    # an UNRELATED context module does not rescue a genuinely-dropped author file
    block2, _ = G.multifile_incompleteness(comp, prompt,
                                           context_modules={"unrelated_ctx"})
    assert block2 == ["dual_port_memory"]


def test_load_context_modules_from_dataset(tmp_path):
    """`_load_context_modules` reads input.context (dict) per id (the reopen's
    `d['input']['context'].keys()` shape)."""
    ds = tmp_path / "prompts.jsonl"
    ds.write_text(
        json.dumps({"id": "cvdp_copilot_gf_multiplier_0013",
                    "input": {"context": {"rtl/gf_multiplier.sv": "...",
                                          "docs/spec.md": "..."}}}) + "\n"
        + json.dumps({"id": "no_ctx", "input": {"prompt": "hi"}}) + "\n")
    cm = G._load_context_modules(str(ds))
    # docs/spec.md is not an RTL file → only the RTL context module is recorded
    assert cm["cvdp_copilot_gf_multiplier_0013"] == {"gf_multiplier"}
    assert "no_ctx" not in cm  # empty context → not recorded


@NEEDS_SIM
def test_end_state_gate_does_not_block_context_module(tmp_path):
    """END-STATE via the real gate: a completion instantiating a context-provided
    module is NOT blocked (rc=0) when --prompts carries its input.context."""
    import shutil
    import subprocess
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not available")
    rid = "cvdp_copilot_gf_multiplier_0013"
    drafts = tmp_path / "drafts.jsonl"
    prompts = tmp_path / "prompts.jsonl"
    out = tmp_path / "out.jsonl"
    report = tmp_path / "report.json"
    comp = json.dumps({"code": [{"rtl/gf_mac.sv": _GF_TOP}]})
    drafts.write_text(json.dumps({"id": rid, "completion": comp}) + "\n")
    prompts.write_text(json.dumps({
        "id": rid, "prompt": _GF_PROMPT,
        "input": {"context": {"rtl/gf_multiplier.sv":
                              "module gf_multiplier(input [7:0] a, input [7:0] b,"
                              " output [7:0] y); assign y=a; endmodule"}}}) + "\n")
    gate = _PROGRAMS.parent / "benchmark" / "cvdp_gate.py"
    cp = subprocess.run(
        [sys.executable, str(gate), "--batch", str(drafts), "--out", str(out),
         "--prompts", str(prompts), "--report", str(report)],
        capture_output=True, text=True)
    # END-STATE: the gate does NOT BLOCK the context-module completion → it is
    # written to the gated-out responses (returncode 0 = every record gated in).
    assert cp.returncode == 0, (
        f"context-module completion was wrongly BLOCKED (rc={cp.returncode}): "
        f"{cp.stdout[-600:]}{cp.stderr[-600:]}")
    rep = json.loads(report.read_text())
    recs = rep if isinstance(rep, list) else rep.get("records", [])
    note_blob = " ".join(n for e in recs for n in e.get("notes", []))
    assert "INCOMPLETE" not in note_blob, (
        f"context module was wrongly flagged INCOMPLETE: {note_blob}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
