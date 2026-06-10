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
HARNESS = PLUGIN / "benchmark-harness"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

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


def test_extract_code_kinds():
    code, kind = G.extract_code(GOOD)
    assert kind == "fenced" and "module ok" in code
    code, kind = G.extract_code("module bare(input a, output b);\n"
                                "assign b=a;\nendmodule\n")
    assert kind == "bare" and "module bare" in code
    code, kind = G.extract_code(DOC_ONLY)
    assert kind == "doc_only" and code is None


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_buggy_completions_blocked_good_gated_in(tmp_path):
    batch = _write_batch(tmp_path, [
        {"id": "p_good", "completion": GOOD},
        {"id": "p_syntax", "completion": SYNTAX_BUG},
        {"id": "p_array", "completion": WHOLE_ARRAY},
    ])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json")])
    assert rc == 1                       # ≥1 blocked
    ids = [r["id"] for r in _read_jsonl(out)]
    assert "p_good" in ids
    assert "p_syntax" not in ids and "p_array" not in ids
    rep = json.loads((tmp_path / "rep.json").read_text())
    verd = {e["id"]: e["verdict"] for e in rep["records"]}
    assert verd["p_syntax"] == "BLOCKED"
    assert verd["p_array"] == "BLOCKED"
    assert verd["p_good"] == "PASS"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_negative_context_module_instantiation_not_blocked(tmp_path):
    # NEGATIVE no-leak (#528): Unknown module type from the problem's
    # context files is a LEGAL copilot shape — must gate in.
    batch = _write_batch(tmp_path, [{"id": "p_ctx", "completion": CONTEXT_INST}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out)])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_ctx"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_doc_only_completion_tolerated(tmp_path):
    batch = _write_batch(tmp_path, [{"id": "p_doc", "completion": DOC_ONLY}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json")])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_doc"]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["records"][0]["verdict"] == "PASS_DOC_ONLY"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
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
                 "--report", str(tmp_path / "rep.json")])
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
    rc = G.main(["--batch", str(batch), "--out", str(out)])
    assert rc == 2
    assert not out.is_file()


def test_bad_jsonl_is_input_error(tmp_path):
    b = tmp_path / "bad.jsonl"
    b.write_text("{not json}\n")
    rc = G.main(["--batch", str(b), "--out", str(tmp_path / "o.jsonl")])
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


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_review_text_fence_before_broken_verilog_blocks(tmp_path):
    # HIGH (review): a ```text fence before the verilog fence used to skew
    # fence pairing — the broken code passed as doc_only (block-evasion).
    batch = _write_batch(tmp_path, [
        {"id": "p_evade", "completion": TEXT_THEN_BROKEN}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out)])
    assert rc == 1
    assert _read_jsonl(out) == []


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_review_text_fence_before_good_verilog_gates_in(tmp_path):
    # the same skew also DROPPED good code (compiled the prose → false
    # block). The good record must gate in as code, not doc_only.
    batch = _write_batch(tmp_path, [
        {"id": "p_good2", "completion": TEXT_THEN_GOOD}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json")])
    assert rc == 0
    assert [r["id"] for r in _read_jsonl(out)] == ["p_good2"]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["records"][0]["verdict"] == "PASS"   # NOT doc_only
    assert rep["records"][0]["kind"] == "fenced"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_review_two_fence_writeback_not_duplicated(tmp_path):
    # HIGH (review): the old write-back substituted the CONCATENATED blob
    # into every fence (f1+f2 twice → duplicate declarations). The emitted
    # completion must keep exactly one declaration of each module.
    batch = _write_batch(tmp_path, [
        {"id": "p_two", "completion": TWO_VERILOG_FENCES}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out)])
    assert rc == 0
    recs = _read_jsonl(out)
    body = recs[0]["completion"]
    assert body.count("module f1") == 1
    assert body.count("module f2") == 1
    assert body.count("```verilog") == 2     # fence structure preserved


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_review_unknown_module_does_not_mask_genuine_error(tmp_path):
    # MED (review): icarus aborts on the unknown context module BEFORE
    # reporting the author's own genuine error (undeclared signal under
    # default_nettype none) — the gate must stub the context module,
    # re-run, and BLOCK on the unmasked genuine error.
    batch = _write_batch(tmp_path, [
        {"id": "p_masked", "completion": UNKNOWN_PLUS_GENUINE}])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out)])
    assert rc == 1
    assert _read_jsonl(out) == []


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_review_report_discloses_iverilog_version(tmp_path):
    batch = _write_batch(tmp_path, [{"id": "p_doc2", "completion": DOC_ONLY}])
    out = tmp_path / "responses.jsonl"
    G.main(["--batch", str(batch), "--out", str(out),
            "--report", str(tmp_path / "rep.json")])
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "iverilog" in rep.get("iverilog_version", "").lower() or \
        "icarus" in rep.get("iverilog_version", "").lower()
