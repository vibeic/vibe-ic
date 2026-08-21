"""ORGANIC #734 [P2] — cvdp_gate `--prompts` from the documented local_export
flow carries NO `input.context`, so the #715 round-2 context-module protection
is silently inactive and a completion that instantiates a harness-supplied
CONTEXT module (e.g. `gf_multiplier`) is FALSE-BLOCKED (proven 5/5 on
gf_multiplier_0013 / elevator_control / scrambler).

ROOT CAUSE: `context_module_names()` got an empty set because the local_export
prompts JSONL ({id, prompt, system, user}) has no `input.context` key; the gate
then hard-BLOCKED every instantiated-undefined prompt-required module without
being able to tell a dropped author file from a context module.

FIX (chip-AGNOSTIC):
  * new `--dataset` arg → the gate UNIONS `input.context` from the original CVDP
    dataset JSONL (which carries it) with anything in `--prompts`, RE-ENABLING the
    #715 exclusion in the documented flow.
  * `_load_context_available()` → the ids that actually CARRY an `input.context`
    key. When context is UNAVAILABLE for an id (neither source supplies it), the
    multi-file hard-BLOCK degrades to an advisory WARN ("context protection
    INACTIVE") instead of silently false-blocking (§4.05: a false-BLOCK discards
    a PASSING answer irreversibly; a genuine dropped file is WARNed and the
    scorer ELAB-fails it anyway → same outcome).

§4.05 NO-LEAK is the load-bearing half:
  - NEGATIVE (no context): the context-module completion is NOT hard-blocked.
  - POSITIVE re-enable (--dataset carries it): exclusion fires, still not blocked.
  - POSITIVE retain (context KNOWN-EMPTY): a genuinely-dropped author file still
    hard-blocks — the protection is degraded ONLY when context is truly unknown.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "benchmark"))
import cvdp_gate as G  # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402

_RID = "cvdp_copilot_gf_multiplier_0013"
# author writes the top `gf_mac` and CORRECTLY instantiates the context-provided
# `gf_multiplier` (it must NOT be re-emitted) — a single-file completion.
_GF_TOP = ("module gf_mac(input clk, input [7:0] a, input [7:0] b,\n"
           "             output reg [7:0] y);\n"
           "  gf_multiplier u_mul (.a(a), .b(b), .y(y));\n"
           "endmodule\n")
_GF_PROMPT = ("Implement a multiply-accumulate `gf_mac`. Module Name: gf_mac. "
              "It instantiates gf_multiplier (provided in rtl/gf_multiplier.sv).")
_COMP = json.dumps({"code": [{"rtl/gf_mac.sv": _GF_TOP}]})


# ── unit: context-availability key-presence parse (no iverilog) ──────────────
def test_load_context_available_key_presence(tmp_path):
    p = tmp_path / "src.jsonl"
    p.write_text(
        json.dumps({"id": "a", "prompt": "x"}) + "\n"                       # no context key
        + json.dumps({"id": "b", "input": {"context": {}}}) + "\n"          # known-empty
        + json.dumps({"id": "c", "input": {"context": {"rtl/m.sv": "..."}}}) + "\n"
        + json.dumps({"id": "d", "context": {"rtl/n.sv": "..."}}) + "\n"    # top-level
        + json.dumps({"id": "e", "input": {"context": None}}) + "\n")       # explicit null = UNKNOWN
    avail = G._load_context_available(str(p))
    # 'a' (local_export shape) and 'e' (context:null) are NOT available; an
    # explicit null must mirror _load_context_modules' truthiness so a null-
    # context record is not mis-read as known-empty and false-blocked (#734 adv-review).
    assert avail == {"b", "c", "d"}
    assert G._load_context_modules(str(p)) == {"c": {"m"}, "d": {"n"}}  # loaders agree (no 'e')


def test_load_context_modules_union_from_dataset(tmp_path):
    # the dataset (not the prompts) carries input.context — the stems must load.
    ds = tmp_path / "dataset.jsonl"
    ds.write_text(json.dumps(
        {"id": _RID, "input": {"context": {"rtl/gf_multiplier.sv": "module gf_multiplier; endmodule"}}}) + "\n")
    cm = G._load_context_modules(str(ds))
    assert cm.get(_RID) == {"gf_multiplier"}
    assert _RID in G._load_context_available(str(ds))


# ── end-state via the real program (iverilog-gated) ──────────────────────────
def _have_iverilog():
    return shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def _run(tmp_path, prompts_line, dataset_line=None):
    drafts = tmp_path / "drafts.jsonl"
    prompts = tmp_path / "prompts.jsonl"
    out = tmp_path / "out.jsonl"
    report = tmp_path / "report.json"
    drafts.write_text(json.dumps({"id": _RID, "completion": _COMP}) + "\n")
    prompts.write_text(prompts_line + "\n")
    argv = ["--batch", str(drafts), "--out", str(out),
            "--prompts", str(prompts), "--report", str(report)]
    if dataset_line is not None:
        ds = tmp_path / "dataset.jsonl"
        ds.write_text(dataset_line + "\n")
        argv += ["--dataset", str(ds)]
    rc = G.main(argv)
    rep = json.loads(report.read_text())
    recs = rep if isinstance(rep, list) else rep.get("records", [])
    notes = " ".join(n for e in recs for n in e.get("notes", []))
    return rc, notes


@pytest.mark.skipif(not _have_iverilog(), reason="iverilog/vvp not available")
@NEEDS_SIM
def test_negative_no_context_downgrades_to_warn_not_block(tmp_path):
    """#734 END-STATE: local_export-shape prompts (NO input.context) → the
    context-module completion is NOT hard-blocked; a loud INACTIVE WARN fires
    instead of a silent false-block."""
    rc, notes = _run(tmp_path, json.dumps({"id": _RID, "prompt": _GF_PROMPT,
                                            "system": "s", "user": "u"}))
    assert rc == 0, "context-module completion must NOT be false-blocked w/o context"
    assert "#734" in notes and "INACTIVE" in notes
    assert "multi-file INCOMPLETE (#715)" not in notes  # the hard-block did NOT fire


@pytest.mark.skipif(not _have_iverilog(), reason="iverilog/vvp not available")
@NEEDS_SIM
def test_positive_dataset_reenables_exclusion(tmp_path):
    """With --dataset carrying input.context{gf_multiplier}, the #715 exclusion
    fires properly — gf_multiplier is a known context module, not blocked, and
    NOT via the INACTIVE-degrade path."""
    # The context stub must declare the ports the completion instantiates
    # (.a/.b/.y) — as the REAL CVDP context module does. The context-fed yosys
    # smoke (PR #122/#130) now genuinely elaborates the design WITH the context
    # module, so a bare portless `module gf_multiplier; endmodule` (which the old,
    # non-context-fed gate never synthesized) would fail on a real port mismatch —
    # a correct catch, not the #734 false-block this test guards against.
    rc, notes = _run(
        tmp_path,
        json.dumps({"id": _RID, "prompt": _GF_PROMPT}),
        dataset_line=json.dumps({"id": _RID, "input": {"context": {
            "rtl/gf_multiplier.sv": "module gf_multiplier(input [7:0] a, input [7:0] b, "
                                    "output [7:0] y); assign y = a & b; endmodule"}}}))
    assert rc == 0
    assert "multi-file INCOMPLETE (#715)" not in notes
    assert "INACTIVE" not in notes  # excluded properly, not degraded


@pytest.mark.skipif(not _have_iverilog(), reason="iverilog/vvp not available")
@NEEDS_SIM
def test_positive_known_context_still_hard_blocks_dropped_file(tmp_path):
    """Protection RETAINED: when input.context is KNOWN (here empty — gf_multiplier
    is therefore NOT context-provided), the instantiated-undefined prompt-required
    module is a genuinely-dropped author file → hard-BLOCK (rc=1)."""
    rc, notes = _run(
        tmp_path,
        json.dumps({"id": _RID, "prompt": _GF_PROMPT}),
        dataset_line=json.dumps({"id": _RID, "input": {"context": {}}}))
    assert rc == 1, "a dropped author file must still hard-block when context is KNOWN"
    assert "multi-file INCOMPLETE (#715)" in notes
    assert "INACTIVE" not in notes


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
