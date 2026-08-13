"""ORGANIC #715 — CVDP sole-emit gate must enforce multi-file completeness.

DEFECT (CVDP 100% campaign): when a problem's design instantiates submodules,
the hidden harness compiles ALL rtl/*.sv the file layout implies. A completion
that emits only the top file passes the single-file emit gate (the submodule is
tolerated as an unknown CONTEXT module) but ELAB-fails at scoring 'Unknown module
type: <submodule>'. ping_pong_buffer_0001 false-failed when its second file
(dual_port_memory.sv) was dropped; emitting both as a JSON code-dict passed.

FIX (chip-AGNOSTIC): cvdp_gate parses the authored top for INSTANTIATED module
names; a module that is INSTANTIATED, NOT defined in any emitted file, AND in the
PROMPT's required-deliverable set is a definite dropped file → BLOCK. An
instantiated-undefined module NOT in the required set MAY be a harness context
module → advisory WARN only.

§4.05 NO-LEAK: never false-BLOCK a legitimate context-module instantiation — only
a PROMPT-required dropped module blocks; SV keywords / gate primitives are not
mistaken for instantiations.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
import cvdp_gate as G  # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402

_TOP = ("module ping_pong_buffer(input clk);\n"
        "  dual_port_memory u_m (.clk(clk));\n"
        "endmodule\n")
_PROMPT = ("Implement the design. Save it to rtl/ping_pong_buffer.sv and a file "
           "named dual_port_memory.sv. Module Name: ping_pong_buffer")


def test_acceptance_instantiation_parse(tmp_path):
    """驗收 (verbatim shape): instantiated module names are extracted from the
    top — the gate's structural signal."""
    insts = G.instantiated_module_names(_TOP)
    assert "dual_port_memory" in insts


def test_end_state_dropped_required_submodule_blocks():
    """END-STATE: a completion that instantiates a PROMPT-required submodule but
    omits its file is INCOMPLETE → BLOCK list carries it."""
    comp = json.dumps({"code": [{"rtl/ping_pong_buffer.sv": _TOP}]})
    block, warn = G.multifile_incompleteness(comp, _PROMPT)
    assert block == ["dual_port_memory"], (block, warn)


def test_both_files_emitted_passes():
    """Emitting BOTH required files reconciles — no block, no warn."""
    comp = json.dumps({"code": [
        {"rtl/ping_pong_buffer.sv": _TOP},
        {"rtl/dual_port_memory.sv": "module dual_port_memory(input clk);\nendmodule\n"},
    ]})
    block, warn = G.multifile_incompleteness(comp, _PROMPT)
    assert block == [] and warn == []


def test_noleak_context_module_not_blocked():
    """§4.05: an instantiated-undefined module NOT in the prompt-required set is
    a possible context module → advisory WARN, NEVER a hard BLOCK."""
    top = ("module top(input clk);\n  some_ctx_lib u (.clk(clk));\nendmodule\n")
    comp = json.dumps({"code": [{"rtl/top.sv": top}]})
    block, warn = G.multifile_incompleteness(comp, "Module Name: top")
    assert block == []
    assert warn == ["some_ctx_lib"]


def test_noleak_keywords_not_instantiations():
    """§4.05: SV keywords / gate primitives matching `<word> <word> (` are not
    mistaken for module instantiations."""
    code = ("module top(input a, b, output o);\n"
            "  and g1 (o, a, b);\n"
            "  if (a) begin end\n"
            "endmodule\n")
    insts = G.instantiated_module_names(code)
    assert "and" not in insts and "if" not in insts


def test_noleak_no_prompt_no_block():
    """Without a prompt (no --prompts), the required set is empty so NOTHING
    hard-blocks (the instantiated-undefined module is advisory WARN only)."""
    comp = json.dumps({"code": [{"rtl/ping_pong_buffer.sv": _TOP}]})
    block, warn = G.multifile_incompleteness(comp, "")
    assert block == []
    assert "dual_port_memory" in warn


@NEEDS_SIM
def test_end_state_gate_blocks_dropped_file(tmp_path):
    """END-STATE via the real program: cvdp_gate.main() on a draft that drops a
    prompt-required submodule file returns rc=1 (BLOCKED) and the report carries
    the #715 incomplete note — proving the gate no longer ships it to a scoring
    ELAB Unknown-module-type fail."""
    import shutil
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not available")
    drafts = tmp_path / "drafts.jsonl"
    prompts = tmp_path / "prompts.jsonl"
    out = tmp_path / "out.jsonl"
    report = tmp_path / "report.json"
    rid = "cvdp_copilot_ping_pong_buffer_0001"
    comp = json.dumps({"code": [{"rtl/ping_pong_buffer.sv": _TOP}]})
    drafts.write_text(json.dumps({"id": rid, "completion": comp}) + "\n")
    # ORGANIC #734 — carry input.context (known-empty: dual_port_memory is NOT a
    # context module) so the gate KNOWS this is a genuinely-dropped author file
    # and hard-blocks. Without an input.context key the gate now degrades to an
    # advisory WARN (it cannot prove dropped-author vs harness-context), so this
    # round-1 hard-block assertion is exercised in its context-AVAILABLE form.
    prompts.write_text(json.dumps(
        {"id": rid, "prompt": _PROMPT, "input": {"context": {}}}) + "\n")
    rc = G.main(["--batch", str(drafts), "--out", str(out),
                 "--prompts", str(prompts), "--report", str(report)])
    assert rc == 1, "the dropped-file draft must be BLOCKED (rc=1)"
    rep = json.loads(report.read_text())
    recs = rep if isinstance(rep, list) else rep.get("records", [])
    note_blob = " ".join(
        n for e in recs for n in e.get("notes", []))
    assert "#715" in note_blob and "dual_port_memory" in note_blob


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
