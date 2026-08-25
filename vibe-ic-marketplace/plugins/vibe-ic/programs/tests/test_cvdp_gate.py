"""ORGANIC #528 — cvdp_gate.py: the SOLE EMIT PATH for CVDP copilot
authoring (drafts JSONL → gated responses JSONL).

POSITIVE: a buggy completion (syntax error / icarus-unsupported whole-array
assignment) is BLOCKED — it never reaches the responses JSONL; the corrected
draft gates in. Hygiene `--fix` is ENFORCED in-gate (the v0.1.25 lesson).

NEGATIVE no-leak: a legitimate multi-file completion instantiating the
problem's CONTEXT module (→ icarus `Unknown module type` at elaboration)
must NOT be blocked; a doc/SVA-prose completion is tolerated.

chip-AGNOSTIC: synthetic drafts only; no dataset access.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

#: The guard's definition lives in `_sim_tools` so it exists ONCE rather
#: than once per file — eight copies of `shutil.which("yosys")` is the
#: drift shape this repo removes from registries one at a time. Same
#: semantics: skip only on genuine absence, and name the missing tool.
#: See that module for the measured 38-test / 8-file cluster.
from _sim_tools import (  # noqa: E402
    MISSING as _MISSING_SIM, NEEDS_SIM as _NEEDS_SIM)

#: Derived from the shared set rather than probed a second time. This
#: file already guarded 18 OTHER tests on `_HAS_IVERILOG and _HAS_YOSYS`
#: — the both-tools rule was always this file's intent; the 13 fixed
#: here were simply left on the older iverilog-only marker.
_HAS_IVERILOG = "iverilog" not in _MISSING_SIM
_HAS_YOSYS = "yosys" not in _MISSING_SIM

GOOD = """Here is the fix:

```verilog
module ok(input clk, input rst, output reg q);
  always @(posedge clk) begin
    if (rst) q <= 1'b0;
    else q <= ~q;
  end
endmodule
```
"""

SYNTAX_BUG = """```verilog
module bad(input clk, output reg q)   // missing semicolon
  always @(posedge clk q <= ~q;
endmodule
```
"""

WHOLE_ARRAY = """```verilog
module arr(input clk, output reg [7:0] q);
  reg [7:0] mem [0:3];
  reg [7:0] src [0:3];
  always @(posedge clk) begin
    mem <= src;   // whole-array assignment — icarus-unsupported
    q <= mem[0];
  end
endmodule
```
"""

CONTEXT_INST = """```verilog
module top(input clk, input rst, output done);
  // ctx_engine lives in the problem's CONTEXT files, not in this draft
  ctx_engine u_eng(.clk(clk), .rst(rst), .done(done));
endmodule
```
"""

DOC_ONLY = "The bug is in the handshake: ready must be deasserted while busy."


def _write_batch(tmp_path, recs):
    b = tmp_path / "drafts.jsonl"
    b.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return b


def _read_jsonl(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def test_559_required_module_names_from_prompt():
    assert G.required_module_names_from_prompt(
        "Implement the design and save it to rtl/foo_bar.sv.") == {"foo_bar"}
    assert G.required_module_names_from_prompt(
        "Write your answer in a file named adder.v") == {"adder"}
    # no filename request → empty (check never fires)
    assert G.required_module_names_from_prompt(
        "Design a 4-bit counter.") == set()


@_NEEDS_SIM
def test_559_filename_module_mismatch_is_advisory_with_prompts(tmp_path):
    # ORGANIC #642 round-2 — a filename hint (`rtl/foo.sv`) is NOT the harness
    # TOPLEVEL (cocotb sets it from the module DECLARATION name). A
    # filename-vs-module mismatch is ADVISORY (WARN + emit), never a hard-BLOCK:
    # the completion is emitted and the scorer arbitrates.
    batch = _write_batch(tmp_path, [
        {"id": "p1", "completion": "```verilog\nmodule bar(input a, "
                                   "output b);\nassign b=a;\nendmodule\n```\n"}])
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text(json.dumps(
        {"id": "p1", "prompt": "Save your module to rtl/foo.sv"}) + "\n")
    out = tmp_path / "out.jsonl"
    rep = tmp_path / "rep.json"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(rep), "--prompts", str(prompts)])
    assert rc == 0
    assert len(_read_jsonl(out)) == 1            # emitted (not discarded)
    e = _json.loads(rep.read_text())["records"][0]
    assert e["verdict"] == "PASS"
    assert "filename_conformance" not in e        # never hard-blocked
    assert any("module-name-conformance" in n     # advisory, not silent
               for n in e.get("notes", []))


@_NEEDS_SIM
def test_559_matching_module_passes_and_no_prompts_unchanged(tmp_path):
    good = ("```verilog\nmodule foo(input a, output b);\n"
            "assign b=a;\nendmodule\n```\n")
    batch = _write_batch(tmp_path, [{"id": "p1", "completion": good}])
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text(json.dumps(
        {"id": "p1", "prompt": "Save your module to rtl/foo.sv"}) + "\n")
    out = tmp_path / "out.jsonl"
    # module foo matches required foo → PASS
    assert G.main(["--batch", str(batch), "--out", str(out),
                   "--prompts", str(prompts)]) == 0
    assert len(_read_jsonl(out)) == 1
    # WITHOUT --prompts: behaviour identical (no conformance check)
    out2 = tmp_path / "out2.jsonl"
    batch2 = _write_batch(tmp_path, [
        {"id": "p2", "completion": "```verilog\nmodule bar(input a, "
                                   "output b);\nassign b=a;\nendmodule\n```\n"}])
    assert G.main(["--batch", str(batch2), "--out", str(out2), "--without-spec-guards"]) == 0
    assert len(_read_jsonl(out2)) == 1


def test_extract_code_kinds():
    code, kind = G.extract_code(GOOD)
    assert kind == "fenced" and "module ok" in code
    code, kind = G.extract_code("module bare(input a, output b);\n"
                                "assign b=a;\nendmodule\n")
    assert kind == "bare" and "module bare" in code
    code, kind = G.extract_code(DOC_ONLY)
    assert kind == "doc_only" and code is None


@_NEEDS_SIM
def test_buggy_completions_blocked_good_gated_in(tmp_path):
    batch = _write_batch(tmp_path, [
        {"id": "p_good", "completion": GOOD},
        {"id": "p_syntax", "completion": SYNTAX_BUG},
        {"id": "p_array", "completion": WHOLE_ARRAY},
    ])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1                       # ≥1 blocked
    ids = [r["id"] for r in _read_jsonl(out)]
    assert "p_good" in ids
    assert "p_syntax" not in ids and "p_array" not in ids
    rep = json.loads((tmp_path / "rep.json").read_text())
    verd = {e["id"]: e["verdict"] for e in rep["records"]}
    assert verd["p_syntax"] == "BLOCKED"
    assert verd["p_array"] == "BLOCKED"
    assert verd["p_good"] == "PASS"


@_NEEDS_SIM
def test_negative_context_module_instantiation_not_blocked(tmp_path):
    # NEGATIVE no-leak (#528): Unknown module type from the problem's
    # context files is a LEGAL copilot shape — must gate in.
    batch = _write_batch(tmp_path, [{"id": "p_ctx", "completion": CONTEXT_INST}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_ctx"]


@_NEEDS_SIM
def test_doc_only_completion_tolerated(tmp_path):
    batch = _write_batch(tmp_path, [{"id": "p_doc", "completion": DOC_ONLY}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_doc"]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["records"][0]["verdict"] == "PASS_DOC_ONLY"


@_NEEDS_SIM
def test_hygiene_fix_is_enforced_in_gate(tmp_path):
    # a draft with a reset-less power-up register: rtl_hygiene_lint --fix
    # must run INSIDE the gate (the gated-in completion may differ from the
    # draft). We assert the gate runs the tool and the record still gates
    # in; the exact fix content is the lint program's own contract.
    rtl = ("```verilog\n"
           "module pup(input clk, output reg q);\n"
           "  always @(posedge clk) q <= ~q;\n"
           "endmodule\n```\n")
    batch = _write_batch(tmp_path, [{"id": "p_pup", "completion": rtl}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    recs = _read_jsonl(out)
    assert recs and recs[0]["id"] == "p_pup"
    # the emitted completion is still compilable verilog
    code, kind = G.extract_code(recs[0]["completion"])
    assert kind in ("fenced", "bare") and "module pup" in code


def test_gate_refuses_without_iverilog(tmp_path, monkeypatch):
    # the gate must REFUSE (exit 2), never emit ungated responses, when it
    # cannot enforce.
    monkeypatch.setattr(G.shutil, "which", lambda *_: None)
    batch = _write_batch(tmp_path, [{"id": "x", "completion": GOOD}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 2
    assert not out.is_file()


def test_bad_jsonl_is_input_error(tmp_path):
    b = tmp_path / "bad.jsonl"
    b.write_text("{not json}\n")
    rc = G.main(["--batch", str(b), "--out", str(tmp_path / "o.jsonl"), "--without-spec-guards"])
    assert rc == 2


# ── adversarial-review regressions (v0.3.26 pre-push round) ────────────────

TEXT_THEN_BROKEN = """```text
Here is my analysis of the problem.
```

```verilog
module mux(input a, input b, input s, output y;
  assign y = s ? a : b
endmodule
```
"""

TEXT_THEN_GOOD = """```text
Explanation prose mentioning module here.
```

```verilog
module good(input a, output y);
  assign y = a;
endmodule
```
"""

TWO_VERILOG_FENCES = """First block:

```verilog
module f1(input a, output y);
  assign y = a;
endmodule
```

Second block:

```verilog
module f2(input clk, output reg q);
  always @(posedge clk) q <= ~q;
endmodule
```
"""

UNKNOWN_PLUS_GENUINE = """```verilog
`default_nettype none
module top(input wire clk, output wire q);
  ctx_engine u0(.clk(clk), .q(q));
  assign q = undeclared_sig;
endmodule
```
"""


@_NEEDS_SIM
def test_review_text_fence_before_broken_verilog_blocks(tmp_path):
    # HIGH (review): a ```text fence before the verilog fence used to skew
    # fence pairing — the broken code passed as doc_only (block-evasion).
    batch = _write_batch(tmp_path, [
        {"id": "p_evade", "completion": TEXT_THEN_BROKEN}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []


@_NEEDS_SIM
def test_review_text_fence_before_good_verilog_gates_in(tmp_path):
    # the same skew also DROPPED good code (compiled the prose → false
    # block). The good record must gate in as code, not doc_only.
    batch = _write_batch(tmp_path, [
        {"id": "p_good2", "completion": TEXT_THEN_GOOD}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_good2"]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["records"][0]["verdict"] == "PASS"   # NOT doc_only
    assert rep["records"][0]["kind"] == "fenced"


@_NEEDS_SIM
def test_review_two_fence_writeback_not_duplicated(tmp_path):
    # HIGH (review): the old write-back substituted the CONCATENATED blob
    # into every fence (f1+f2 twice → duplicate declarations). The emitted
    # completion must keep exactly one declaration of each module.
    batch = _write_batch(tmp_path, [
        {"id": "p_two", "completion": TWO_VERILOG_FENCES}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 0
    recs = _read_jsonl(out)
    body = recs[0]["completion"]
    assert body.count("module f1") == 1
    assert body.count("module f2") == 1
    # ORGANIC #626 — the emitted completion is DE-FENCED (the bytes the gate
    # compiled): no fence markers survive, so the scorer's verbatim-written
    # .sv compiles. (Was: assert two ```verilog fences retained — that was the
    # fence-marker defect that ELAB_ERRORed at scoring.)
    assert "```" not in body


@_NEEDS_SIM
def test_review_unknown_module_does_not_mask_genuine_error(tmp_path):
    # MED (review): icarus aborts on the unknown context module BEFORE
    # reporting the author's own genuine error (undeclared signal under
    # default_nettype none) — the gate must stub the context module,
    # re-run, and BLOCK on the unmasked genuine error.
    batch = _write_batch(tmp_path, [
        {"id": "p_masked", "completion": UNKNOWN_PLUS_GENUINE}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []


@_NEEDS_SIM
def test_review_report_discloses_iverilog_version(tmp_path):
    batch = _write_batch(tmp_path, [{"id": "p_doc2", "completion": DOC_ONLY}])
    out = tmp_path / "responses.jsonl"
    G.main(["--batch", str(batch), "--out", str(out),
            "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "iverilog" in rep.get("iverilog_version", "").lower() or \
        "icarus" in rep.get("iverilog_version", "").lower()


# ── #531 yosys smoke + #535 transmission integrity ─────────────────────────


IVERILOG_OK_YOSYS_EMPTY = "```verilog\n// no module at all — just a comment\n```"

PASSTHRU = """```verilog
module thin(input a, output y);
  assign y = a;
endmodule
```
"""


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_531_zero_module_blocked_by_yosys_smoke(tmp_path):
    # POSITIVE (#531): a completion iverilog ACCEPTS but yosys cannot
    # synthesize — a SYNTH-STAGE failure (async-edge sensitivity with no
    # reset-if split → PROC_DFF error), exactly the class the 13/92
    # first-round emit gate never caught. (A FRONTEND parse gap like
    # fork/join is deliberately tolerated instead — the host yosys SV
    # frontend may trail the official 0.40; see the frontend-gap note.)
    bad = ("```verilog\n"
           "module zs(input clk, input rst, input d, output reg q);\n"
           "  always @(posedge clk or posedge rst)\n"
           "    q <= d;\n"
           "endmodule\n"
           "```\n")
    batch = _write_batch(tmp_path, [{"id": "p_zs", "completion": bad}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["records"][0]["verdict"] == "BLOCKED"


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_531_negative_trivial_passthrough_not_blocked(tmp_path):
    # NEGATIVE no-leak (#531): a 0-cell pure-wire module is legal — the
    # smoke gates on stat-PRESENCE, never the cell count.
    batch = _write_batch(tmp_path, [{"id": "p_thin", "completion": PASSTHRU}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_thin"]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "yosys-smoke ok" in rep["records"][0].get("synth", "")


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_531_negative_context_instantiation_still_gates_in(tmp_path):
    # NEGATIVE no-leak (#531): context-module instantiation must survive
    # the yosys smoke via the same synthesized stubs.
    batch = _write_batch(tmp_path, [{"id": "p_ctx2", "completion": CONTEXT_INST}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_ctx2"]


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_535_batch_dir_intake_gate_does_own_json(tmp_path):
    # #535: raw-file intake — the gate does its OWN json.dumps; special
    # characters (backslash, quotes, CRLF, unicode) survive the round-trip.
    bdir = tmp_path / "drafts"
    bdir.mkdir()
    tricky = ('Fix: see "notes \\ here" — 中文註解\r\n\r\n'
              "```verilog\r\n"
              "module rt(input a, output y);\r\n"
              "  assign y = a;  // path \\\\server\\share\r\n"
              "endmodule\r\n"
              "```\r\n")
    (bdir / "p_rt.md").write_text(tricky)
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch-dir", str(bdir), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    recs = _read_jsonl(out)
    assert [r["id"] for r in recs] == ["p_rt"]
    # CRLF normalized; code still extractable from the DELIVERED record.
    # ORGANIC #626 — the fenced draft is emitted DE-FENCED, so the delivered
    # record's kind is now 'bare' (the compiled bytes), not 'fenced'. The
    # round-trip integrity guarantees under test (module survives, CRLF gone)
    # are unchanged.
    code, kind = G.extract_code(recs[0]["completion"])
    assert kind == "bare" and "module rt" in code and "\r" not in recs[0]["completion"]


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_535_roundtrip_corruption_blocked(tmp_path, monkeypatch):
    # POSITIVE (#535): simulate transport corruption — the delivered JSONL
    # parses to an EMPTY/truncated completion → the round-trip gate must
    # BLOCK with empty-after-roundtrip/mismatch and PURGE the record.
    batch = _write_batch(tmp_path, [{"id": "p_corr", "completion": GOOD}])
    out = tmp_path / "responses.jsonl"
    real_write = Path.write_text
    state = {"n": 0}

    def corrupting_write(self, text, *a, **k):
        # corrupt only the FIRST responses write (the pre-roundtrip emit)
        if self.name == "responses.jsonl" and state["n"] == 0:
            state["n"] += 1
            corrupted = json.dumps({"id": "p_corr", "completion": ""}) + "\n"
            return real_write(self, corrupted, *a, **k)
        return real_write(self, text, *a, **k)
    monkeypatch.setattr(Path, "write_text", corrupting_write)
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []          # corrupted record purged


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_review2_sibling_broken_module_not_evaded(tmp_path):
    # ADVERSARIAL-REVIEW MED (round-2): synth -auto-top used to DROP a
    # sibling root module as unused — an unsynthesizable DUT next to a
    # trivial helper evaded the smoke. Per-module synth must catch it.
    bad = ("```verilog\n"
           "module bad_synth(input clk, input rst, input d, output reg q);\n"
           "  always @(posedge clk or posedge rst)\n"
           "    q <= d;\n"
           "endmodule\n"
           "module good_trivial(input a, input b, output y);\n"
           "  assign y = a & b;\n"
           "endmodule\n"
           "```\n")
    batch = _write_batch(tmp_path, [{"id": "p_sib", "completion": bad}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_review2_frontend_gap_tolerated_not_blocked(tmp_path):
    # ADVERSARIAL-REVIEW MED (round-2): host-yosys SV-frontend gaps
    # (e.g. `parameter type` on yosys 0.33) must NOT hard-block a completion
    # the official icarus scorer accepts.
    sv = ("```verilog\n"
          "module pt #(parameter type T = logic [7:0])\n"
          "  (input T a, input T b, output T y);\n"
          "  assign y = a ^ b;\n"
          "endmodule\n"
          "```\n")
    batch = _write_batch(tmp_path, [{"id": "p_pt", "completion": sv}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    rep = json.loads((tmp_path / "rep.json").read_text())
    # depending on host yosys generation this is either a clean synth or a
    # tolerated frontend gap — NEVER a block.
    assert rc == 0, rep
    assert [r["id"] for r in _read_jsonl(out)] == ["p_pt"]


def test_review2_duplicate_ids_refused(tmp_path):
    # ADVERSARIAL-REVIEW MED/LOW (round-2): duplicate ids made the
    # round-trip purge collateral-drop the good twin and would overwrite
    # each other in local_import — the gate now REFUSES ambiguous batches.
    batch = _write_batch(tmp_path, [
        {"id": "dup", "completion": GOOD},
        {"id": "dup", "completion": PASSTHRU}])
    rc = G.main(["--batch", str(batch), "--out", str(tmp_path / "o.jsonl"), "--without-spec-guards"])
    assert rc == 2


def test_review2_missing_id_refused(tmp_path):
    batch = _write_batch(tmp_path, [{"completion": GOOD}])
    rc = G.main(["--batch", str(batch), "--out", str(tmp_path / "o.jsonl"), "--without-spec-guards"])
    assert rc == 2


def test_review2_batch_dir_stem_collision_refused(tmp_path):
    bdir = tmp_path / "drafts"
    bdir.mkdir()
    (bdir / "p1.sv").write_text("module a(input x, output y); assign y=x; endmodule\n")
    (bdir / "p1.md").write_text("doc twin")
    rc = G.main(["--batch-dir", str(bdir), "--out", str(tmp_path / "o.jsonl"), "--without-spec-guards"])
    assert rc == 2


# ── field round-2 reopen regressions (#528/#531/#535) ──────────────────────

import json as _json
from _hostpaths import require_corpus  # noqa: E402

JSON_DICT_GOOD = _json.dumps({"code": [{"rtl/foo.sv":
    "module foo(input a, output b);\n  assign b = a;\nendmodule"}]})
JSON_DICT_BROKEN = _json.dumps({"code": [{"rtl/bad.sv":
    "module bad(input a, output b)\n  assign b = a\nendmodule"}]})
JSON_DICT_SCHEMA = _json.dumps({"code": [{"docs/elevator_spec.json":
    "{\"states\": [\"IDLE\", \"MOVING\"], \"floors\": 8}"}]})
JSON_DICT_UNSYNTH = _json.dumps({"code": [{"rtl/zs.sv":
    "module zs(input clk, input rst, input d, output reg q);\n"
    "  always @(posedge clk or posedge rst)\n    q <= d;\nendmodule"}]})


def test_round2_json_dict_extraction():
    # #528 field repro: the official JSON code-dict shape must extract the
    # RTL payload, not feed raw JSON to iverilog as bare Verilog.
    code, kind = G.extract_code(JSON_DICT_GOOD)
    assert kind == "json_dict" and "module foo" in code
    # prose around the JSON (official parser is first-{ → last-})
    code, kind = G.extract_code("Answer:\n" + JSON_DICT_GOOD + "\nDone.")
    assert kind == "json_dict"
    # JSON-schema answers (no RTL files) are tolerated docs
    assert G.extract_code(JSON_DICT_SCHEMA) == (None, "doc_only")


@_NEEDS_SIM
def test_round2_json_dict_good_gates_in_broken_blocked(tmp_path):
    batch = _write_batch(tmp_path, [
        {"id": "p_jgood", "completion": JSON_DICT_GOOD},
        {"id": "p_jbad", "completion": JSON_DICT_BROKEN},
        {"id": "p_jschema", "completion": JSON_DICT_SCHEMA},
    ])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1                                  # p_jbad blocked
    ids = [r["id"] for r in _read_jsonl(out)]
    assert "p_jgood" in ids and "p_jschema" in ids
    assert "p_jbad" not in ids
    rep = _json.loads((tmp_path / "rep.json").read_text())
    verd = {e["id"]: e["verdict"] for e in rep["records"]}
    assert verd["p_jgood"] == "PASS"
    assert verd["p_jschema"] == "PASS_DOC_ONLY"
    assert verd["p_jbad"] == "BLOCKED"


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_round2_531_json_dict_reaches_yosys_smoke(tmp_path):
    # #531 reopen: the smoke must be REACHABLE for JSON-dict completions —
    # positive (good json_dict has a synth field) + negative (json_dict
    # with yosys-unsynthesizable RTL is BLOCKED by the smoke).
    batch = _write_batch(tmp_path, [
        {"id": "p_jsmoke", "completion": JSON_DICT_GOOD},
        {"id": "p_jzs", "completion": JSON_DICT_UNSYNTH},
    ])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1
    rep = _json.loads((tmp_path / "rep.json").read_text())
    verd = {e["id"]: e for e in rep["records"]}
    assert "yosys-smoke ok" in verd["p_jsmoke"].get("synth", "")
    assert verd["p_jzs"]["verdict"] == "BLOCKED"
    assert [r["id"] for r in _read_jsonl(out)] == ["p_jsmoke"]


@_NEEDS_SIM
def test_round2_535_empty_completion_blocked_not_doc_only(tmp_path):
    # #535 reopen: whitespace-only / trivially-short completions are the
    # corruption shape and must BLOCK — never PASS_DOC_ONLY.
    batch = _write_batch(tmp_path, [
        {"id": "p_blank", "completion": "   \n  "},
        {"id": "p_short", "completion": "ok."},
        {"id": "p_doc", "completion": DOC_ONLY},     # substantive doc keeps
    ])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1
    ids = [r["id"] for r in _read_jsonl(out)]
    assert ids == ["p_doc"]
    rep = _json.loads((tmp_path / "rep.json").read_text())
    verd = {e["id"]: e for e in rep["records"]}
    assert verd["p_blank"]["verdict"] == "BLOCKED"
    assert "empty" in verd["p_blank"]["compile"]
    assert verd["p_short"]["verdict"] == "BLOCKED"
    assert verd["p_doc"]["verdict"] == "PASS_DOC_ONLY"


def test_round2_real_corpus_json_dict_records_extract():
    # content-gated real-corpus pin: the 3 falsely-blocked records (+ the
    # axis example) must all extract as json_dict / doc_only — never bare.
    src = require_corpus("cvdp_open_run_v0325/final_responses_r3.jsonl")
    if not src.is_file():
        src = require_corpus("cvdp_open_run_v0325/final_responses.jsonl")
    if not src.is_file():
        pytest.skip("real corpus not on this host")
    wanted = ("elevator_control_0006", "elevator_control_0026",
              "huffman_0001", "axis_border_gen_0014")
    seen = {}
    for ln in src.read_text(errors="replace").splitlines():
        r = _json.loads(ln)
        for w in wanted:
            if w in r["id"]:
                seen[r["id"]] = G.extract_code(r["completion"])[1]
    if not seen:
        pytest.skip("target records not in the current corpus file")
    assert all(k in ("json_dict", "doc_only") for k in seen.values()), seen


# ── field round-3 reopen regression (#531) ─────────────────────────────────

COMMENT_PHANTOM_JSON = _json.dumps({"code": [{"rtl/elev.sv":
    "/* This module implements an FSM-based elevator control system\n"
    "   with request arbitration. */\n"
    "module elev_ctrl(input clk, input rst, input req, output reg busy);\n"
    "  always @(posedge clk) begin\n"
    "    if (rst) busy <= 1'b0;\n"
    "    else busy <= req;\n"
    "  end\nendmodule"}]})


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_round3_comment_prose_is_not_a_phantom_module(tmp_path):
    # the field round-3 counter-evidence: a leading block comment saying
    # "This module implements ..." used to yield phantom module name
    # 'implements' → synth -top implements → false BLOCK. The smoke must
    # synth only the REAL module.
    batch = _write_batch(tmp_path, [
        {"id": "p_phantom", "completion": COMMENT_PHANTOM_JSON}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    rep = _json.loads((tmp_path / "rep.json").read_text())
    e = rep["records"][0]
    assert e["verdict"] == "PASS"
    assert "elev_ctrl" in e.get("synth", "")
    assert "implements" not in e.get("synth", "")


def test_round3_detection_text_strips_comments_and_strings():
    assert "module implements" not in G._detection_text(
        "/* This module implements an FSM */ module real_one(input a);")
    assert "real_one" in G._detection_text(
        "/* This module implements an FSM */ module real_one(input a);")
    # a $display string mentioning a module must not be a declaration
    assert G._MODULE_RE.search(
        G._detection_text('initial $display("module fake_decl here");')) is None
    # prose-only completion mentioning "module implements" stays doc_only
    code, kind = G.extract_code(
        "The module implements a simple two-stage handshake protocol "
        "as described in the spec.")
    assert kind == "doc_only" and code is None


def test_round3_real_corpus_elevator_huffman_gate_pass(tmp_path):
    # content-gated binding pins: the 2 falsely-blocked official-PASS
    # records gate PASS; huffman_0001 does not regress.
    src = require_corpus("cvdp_open_run_v0325/final_responses_r3.jsonl")
    if not src.is_file():
        src = require_corpus("cvdp_open_run_v0325/final_responses.jsonl")
    if not src.is_file():
        pytest.skip("real corpus not on this host")
    if not (_HAS_IVERILOG and _HAS_YOSYS):
        pytest.skip("iverilog/yosys not on this host")
    import tempfile
    wanted = ("elevator_control_0006", "elevator_control_0026",
              "huffman_0001")
    recs = []
    for ln in src.read_text(errors="replace").splitlines():
        r = _json.loads(ln)
        if any(w in r["id"] for w in wanted):
            recs.append(r)
    if not recs:
        pytest.skip("target records not in the current corpus file")
    with tempfile.TemporaryDirectory() as td:
        for r in recs:
            ok, _out, entry = G.gate_record(r, Path(td))
            assert ok, (r["id"], entry)
            assert entry["verdict"] in ("PASS", "PASS_DOC_ONLY"), entry


# ── field round-4 reopen regressions (#531) ────────────────────────────────

# `.*` implicit connection defeats _stub_for (stub not derivable) — the
# exact elevator_0033/_0036 shape: compile tolerates WITHOUT stubs, so the
# synth hierarchy pass needs its own symmetric tolerance.
CTX_AT_SYNTH_JSON = _json.dumps({"code": [{"rtl/elev2.sv":
    "module elev2(input clk, input rst, input [2:0] floor,\n"
    "             output [6:0] seg);\n"
    "  // display converter lives in the problem's CONTEXT files\n"
    "  wire [2:0] floor_w = floor;\n"
    "  floor_to_seven_segment u_disp(.*);\n"
    "  reg [2:0] cur;\n"
    "  always @(posedge clk) begin\n"
    "    if (rst) cur <= 3'd0;\n"
    "    else cur <= floor;\n"
    "  end\nendmodule"}]})

LATCH_COMB_JSON = _json.dumps({"code": [{"rtl/bcd.sv":
    "module bcd(input [3:0] bin, output reg [3:0] out);\n"
    "  // always_comb that infers a latch on a path — yosys ERRORs, the\n"
    "  // official sim-only harness does not care\n"
    "  always_comb begin\n"
    "    if (bin < 4'd10) out = bin;\n"
    "  end\nendmodule"}]})


# ── host-yosys CAPABILITY probes (never a version string) ──────────────────
# The three round-4/round-5 assertions below pin the EVIDENCE STRING the gate
# must emit when it takes ONE SPECIFIC tolerance branch. Reaching that branch
# needs a yosys that (a) parses SV `.*` so the HIERARCHY pass actually runs
# and (b) raises always_comb latch inference to an `ERROR:` line. The plugin
# PINS yosys 0.40 (benchmark/cvdp_env_preflight.py REQUIRED / Dockerfile.sim);
# a host yosys older than the pin (the distro 0.9 has neither capability:
# `.*` is a frontend syntax error, and latch inference is an INFO line) can
# NEVER execute those branches, so the gate correctly reports a DIFFERENT —
# still correct — reason string there. `shutil.which("yosys")` proves
# PRESENCE, not CAPABILITY, so each mechanism assertion is preconditioned on
# a real probe of the host binary while the VERDICT assertions above it stay
# unconditional on every host.
#
# The probes carry their OWN literal patterns and never import cvdp_gate's
# regexes: a probe that asked the code under test whether it can be tested
# would fall silent exactly when that code broke. A probe that cannot get
# yosys to run at all FAILS the test instead of skipping it (#604 applied to
# the probe itself) — a skip must never rest on absent evidence.
_YOSYS_CAP: dict = {}


def _yosys_probe_blob(sv_text, top):
    import re as _re_p
    import subprocess as _sp
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        p = Path(td) / "probe.sv"
        p.write_text(sv_text)
        r = _sp.run(["yosys", "-p",
                     f"read_verilog -sv {p}; synth -top {top}; stat"],
                    # 60s, NOT 300. The pytest harness runs with --timeout=180, so a
                    # bound ABOVE the harness cap is not a longer allowance — it is a
                    # different failure mode. A hung yosys reaches 180s first and
                    # `--timeout-method=thread` kills the SESSION, losing every other
                    # result in the run, instead of failing this one test with a name.
                    # That is why `ci_harness_timeout_ceiling_check` refuses it: the
                    # ceiling is 60 = 180 // 3.
                    #
                    # Measured: batch R4 (22 PRs) failed BOTH its gates on this one
                    # line — `FAIL targeted tests +++ Timeout +++` with zero named
                    # failures, and `[FAIL] 1 inner bound(s) above the 60s ceiling`.
                    # The timeout named nothing because the session died; the hygiene
                    # gate is the only one that could say why.
                    capture_output=True, text=True, timeout=60)
    blob = (r.stdout or "") + "\n" + (r.stderr or "")
    assert _re_p.search(r"Yosys\s+[\d.]|Executing\s+\w+\s+pass|/----", blob), (
        "host yosys did not RUN for the capability probe — refusing to "
        "downgrade a mechanism assertion to a skip on no evidence:\n"
        + blob[:400])
    return blob


def _host_yosys_version():
    if "ver" not in _YOSYS_CAP:
        import subprocess as _sp
        r = _sp.run(["yosys", "-V"], capture_output=True, text=True,
                    timeout=60)
        line = ((r.stdout or "") + (r.stderr or "")).splitlines()
        _YOSYS_CAP["ver"] = line[0].strip() if line else "unknown"
    return _YOSYS_CAP["ver"]


def _yosys_errors_on_always_comb_latch():
    """Host yosys raises always_comb latch inference to an ERROR line."""
    if "latch" not in _YOSYS_CAP:
        import re as _re_p
        blob = _yosys_probe_blob(
            "module lprobe(input e, input d, output reg q);\n"
            "  always_comb begin\n    if (e) q = d;\n  end\nendmodule\n",
            "lprobe")
        _YOSYS_CAP["latch"] = any(
            _re_p.search(r"ERROR:.*[Ll]atch inferred", ln)
            for ln in blob.splitlines())
    return _YOSYS_CAP["latch"]


def _yosys_hierarchy_reaches_unknown_context():
    """Host yosys parses `.*` and reaches HIERARCHY on the unknown module."""
    if "ctx" not in _YOSYS_CAP:
        import re as _re_p
        blob = _yosys_probe_blob(
            "module cprobe(input a, output z);\n"
            "  unknown_ctx u(.*);\nendmodule\n", "cprobe")
        _YOSYS_CAP["ctx"] = bool(_re_p.search(r"referenced in module", blob))
    return _YOSYS_CAP["ctx"]


def _skip_unreachable(cap, what):
    pytest.skip(
        f"host yosys ({_host_yosys_version()}) {cap} — the synth-stage "
        f"{what} under test is UNREACHABLE on this binary; the plugin pins "
        f"yosys 0.40 (cvdp_env_preflight REQUIRED), where this assertion "
        f"runs hard. The gate VERDICT for this record was asserted above on "
        f"THIS host and held.")


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_round4_context_module_at_synth_hierarchy_tolerated(tmp_path):
    # field round-4 (elevator_0033/_0036 shape): the compile path tolerates
    # unknown context modules but the synth HIERARCHY pass used to hard-fail
    # on them — the tolerance must be SYMMETRIC.
    batch = _write_batch(tmp_path, [
        {"id": "p_ctxsynth", "completion": CTX_AT_SYNTH_JSON}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    rep = _json.loads((tmp_path / "rep.json").read_text())
    e = rep["records"][0]
    assert e["verdict"] == "PASS"
    if not _yosys_hierarchy_reaches_unknown_context():
        _skip_unreachable("cannot parse SV `.*` (frontend syntax error), so "
                          "its frontend never reaches the HIERARCHY pass",
                          "unknown-context-module tolerance")
    assert "context module" in e.get("synth", "")


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_round4_latch_strictness_is_advisory_not_block(tmp_path):
    # field round-4 (binary_to_BCD_0010 / line_buffer_0003 shape): yosys's
    # always_comb latch-inference ERROR is stricter than the official
    # sim-only harness — advisory note, never a block.
    batch = _write_batch(tmp_path, [
        {"id": "p_latch", "completion": LATCH_COMB_JSON}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 0
    rep = _json.loads((tmp_path / "rep.json").read_text())
    e = rep["records"][0]
    assert e["verdict"] == "PASS"
    if not _yosys_errors_on_always_comb_latch():
        _skip_unreachable("does not raise always_comb latch inference to an "
                          "ERROR line (it is an INFO line there, so the smoke "
                          "simply succeeds)",
                          "latch-strictness ADVISORY tolerance")
    assert "ADVISORY" in e.get("synth", "")


@pytest.mark.skipif(not (_HAS_IVERILOG and _HAS_YOSYS),
                    reason="iverilog/yosys not on this host")
def test_round4_negative_async_edge_still_blocked(tmp_path):
    # NEGATIVE no-leak: the round-4 tolerances must not swallow a genuine
    # synth-stage failure (PROC_DFF multiple-edge) — still BLOCKED.
    bad = ("```verilog\n"
           "module zs(input clk, input rst, input d, output reg q);\n"
           "  always @(posedge clk or posedge rst)\n"
           "    q <= d;\n"
           "endmodule\n```\n")
    batch = _write_batch(tmp_path, [{"id": "p_neg4", "completion": bad}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []


def test_round5_latch_info_line_must_not_mask_fatal_error(tmp_path):
    # field round-5 leak repro: "Latch inferred for signal" ALSO prints as a
    # PROC_DLATCH INFO line (plain `always @*` missing-else, no ERROR:
    # prefix). The round-4 blob-wide tolerance let that info line mask a
    # co-occurring REAL fatal ERROR (PROC_DFF multiple-edge) as PASS — the
    # tolerance must anchor on the ERROR lines themselves.
    if not (_HAS_IVERILOG and _HAS_YOSYS):
        pytest.skip("iverilog/yosys not on this host")
    mask = _json.dumps({"code": [{"rtl/mask_one.sv":
        "module mask_one(input en, input d, input a, input b, input c,\n"
        "                output reg q, output reg r);\n"
        "  // missing else -> PROC_DLATCH info line (no ERROR: prefix)\n"
        "  always @* begin\n"
        "    if (en) q = d;\n"
        "  end\n"
        "  // REAL fatal: multiple edge sensitive events (PROC_DFF)\n"
        "  always @(posedge a or posedge b) r <= c;\n"
        "endmodule"}]})
    batch = _write_batch(tmp_path, [{"id": "p_mask1", "completion": mask}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []
    rep = _json.loads((tmp_path / "rep.json").read_text())
    e = rep["records"][0]
    assert e["verdict"] == "BLOCKED"
    assert "yosys-smoke failed" in e.get("synth", "")


def test_round5_latch_error_line_still_advisory_when_sole_error_class():
    # boundary negative-of-the-negative: when the latch message IS the
    # ERROR line (always_comb shape) and no other ERROR class co-occurs,
    # the advisory tolerance must still fire (round-4 positives hold).
    # Covered end-to-end by test_round4_latch_strictness_is_advisory_not_
    # block; this pins the LINE-anchored predicate itself, no tools needed.
    import re as _re
    latch_error = _re.compile(
        r"ERROR:.*(?:No latch inferred for signal"
        r"|Latch inferred for signal)")
    pure_latch = [
        "ERROR: Latch inferred for signal `\\bcd.\\out' from always_comb "
        "process `\\bcd.$proc$bcd.sv:0$1'."]
    masked = [
        "ERROR: Multiple edge sensitive events found for this signal!"]
    assert all(latch_error.search(ln) for ln in pure_latch)
    assert not all(latch_error.search(ln) for ln in masked)


def test_round5_review_latch_error_abort_must_not_mask_later_fatal(tmp_path):
    # adversarial-review HIGH (round-5): yosys aborts at the FIRST error and
    # PROC_DLATCH runs before PROC_DFF — an always_comb latch ERROR is then
    # the ONLY ERROR line, so "all ERROR lines are latch-class" proves
    # nothing about later passes. The confirming re-run (latch keywords
    # relaxed on a smoke copy) must surface the masked multiple-edge fatal.
    if not (_HAS_IVERILOG and _HAS_YOSYS):
        pytest.skip("iverilog/yosys not on this host")
    mask = _json.dumps({"code": [{"rtl/d.sv":
        "module dut(input en, input d, input a, input b, input c,\n"
        "           output reg q, output reg r);\n"
        "  always_comb begin\n"
        "    if (en) q = d;\n"   # latch ERROR aborts PROC_DLATCH first
        "  end\n"
        "  always @(posedge a or posedge b) r <= c;\n"  # masked fatal
        "endmodule"}]})
    batch = _write_batch(tmp_path, [{"id": "p_lmask", "completion": mask}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json"), "--without-spec-guards"])
    assert rc == 1
    assert _read_jsonl(out) == []
    rep = _json.loads((tmp_path / "rep.json").read_text())
    assert rep["records"][0]["verdict"] == "BLOCKED"
    if not _yosys_errors_on_always_comb_latch():
        _skip_unreachable("does not raise always_comb latch inference to an "
                          "ERROR line, so PROC_DLATCH never aborts and the "
                          "masked PROC_DFF fatal prints on the FIRST run "
                          "(the block above proves it was not masked)",
                          "confirming re-run that un-masks it")
    assert "confirming re-run" in rep["records"][0].get("synth", "")


def test_round5_review_context_abort_must_not_mask_later_fatal(tmp_path):
    # adversarial-review MED (round-5): the hierarchy unknown-context abort
    # is the EARLIEST pass — the context tolerance must stub the missing
    # module(s) and re-run so an INDEPENDENT fatal in the same module gets
    # the chance to print; a context-only module stays tolerated.
    if not (_HAS_IVERILOG and _HAS_YOSYS):
        pytest.skip("iverilog/yosys not on this host")
    import tempfile
    code_bad = ("module dut(input clk, input rst, input a,\n"
                "           output reg q, output z);\n"
                "  unknown_ctx u(.x(a), .y(z));\n"
                "  always @(posedge clk or posedge rst or negedge a)\n"
                "    q <= a;\n"
                "endmodule")
    code_ok = ("module top1(input clk, input a, output z);\n"
               "  unknown_ctx u(.x(a), .y(z));\n"
               "  reg q;\n"
               "  always @(posedge clk) q <= a;\n"
               "endmodule")
    with tempfile.TemporaryDirectory() as td:
        ok, why = G.yosys_smoke(code_bad, Path(td), stubs_text="")
        assert not ok and "confirming re-run" in why, why
    with tempfile.TemporaryDirectory() as td:
        ok, why = G.yosys_smoke(code_ok, Path(td), stubs_text="")
        assert ok and "context module" in why, why


def test_synth_stage_block_stderr_names_the_synth_reason(tmp_path, capsys):
    # ORGANIC #539 — the per-record BLOCKED stderr one-liner used to always
    # print the compile field, so a synth-stage block read "compile clean"
    # on console; it must name the stage that actually blocked.
    if not (_HAS_IVERILOG and _HAS_YOSYS):
        pytest.skip("iverilog/yosys not on this host")
    bad = ("```verilog\n"
           "module zs3(input clk, input rst, input d, output reg q);\n"
           "  always @(posedge clk or posedge rst)\n"
           "    q <= d;\n"
           "endmodule\n```\n")
    batch = _write_batch(tmp_path, [{"id": "p_stderr", "completion": bad}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out), "--without-spec-guards"])
    assert rc == 1
    err = capsys.readouterr().err
    blocked_line = next(ln for ln in err.splitlines()
                        if ln.startswith("BLOCKED p_stderr:"))
    assert "yosys-smoke failed" in blocked_line
    assert "compile clean" not in blocked_line


def test_round4_real_corpus_four_records_gate_pass(tmp_path):
    # content-gated binding pins: the 4 round-4 falsely-blocked official-
    # PASS records gate PASS.
    src = require_corpus("cvdp_open_run_v0325/final_responses_r3.jsonl")
    if not src.is_file():
        src = require_corpus("cvdp_open_run_v0325/final_responses.jsonl")
    if not src.is_file():
        pytest.skip("real corpus not on this host")
    if not (_HAS_IVERILOG and _HAS_YOSYS):
        pytest.skip("iverilog/yosys not on this host")
    import tempfile
    wanted = ("elevator_control_0033", "elevator_control_0036",
              "binary_to_BCD_0010", "line_buffer_0003")
    recs = [r for r in
            (_json.loads(ln) for ln in
             src.read_text(errors="replace").splitlines())
            if any(w in r["id"] for w in wanted)]
    if not recs:
        pytest.skip("target records not in the current corpus file")
    with tempfile.TemporaryDirectory() as td:
        for r in recs:
            ok, _o, entry = G.gate_record(r, Path(td))
            assert ok, (r["id"], entry)
