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


# ── #531 yosys smoke + #535 transmission integrity ─────────────────────────

_HAS_YOSYS = shutil.which("yosys") is not None

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
                 "--report", str(tmp_path / "rep.json")])
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
                 "--report", str(tmp_path / "rep.json")])
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
    rc = G.main(["--batch", str(batch), "--out", str(out)])
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
                 "--report", str(tmp_path / "rep.json")])
    assert rc == 0
    recs = _read_jsonl(out)
    assert [r["id"] for r in recs] == ["p_rt"]
    # CRLF normalized; code still extractable from the DELIVERED record
    code, kind = G.extract_code(recs[0]["completion"])
    assert kind == "fenced" and "module rt" in code and "\r" not in recs[0]["completion"]


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
    rc = G.main(["--batch", str(batch), "--out", str(out)])
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
    rc = G.main(["--batch", str(batch), "--out", str(out)])
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
                 "--report", str(tmp_path / "rep.json")])
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
    rc = G.main(["--batch", str(batch), "--out", str(tmp_path / "o.jsonl")])
    assert rc == 2


def test_review2_missing_id_refused(tmp_path):
    batch = _write_batch(tmp_path, [{"completion": GOOD}])
    rc = G.main(["--batch", str(batch), "--out", str(tmp_path / "o.jsonl")])
    assert rc == 2


def test_review2_batch_dir_stem_collision_refused(tmp_path):
    bdir = tmp_path / "drafts"
    bdir.mkdir()
    (bdir / "p1.sv").write_text("module a(input x, output y); assign y=x; endmodule\n")
    (bdir / "p1.md").write_text("doc twin")
    rc = G.main(["--batch-dir", str(bdir), "--out", str(tmp_path / "o.jsonl")])
    assert rc == 2


# ── field round-2 reopen regressions (#528/#531/#535) ──────────────────────

import json as _json

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


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_round2_json_dict_good_gates_in_broken_blocked(tmp_path):
    batch = _write_batch(tmp_path, [
        {"id": "p_jgood", "completion": JSON_DICT_GOOD},
        {"id": "p_jbad", "completion": JSON_DICT_BROKEN},
        {"id": "p_jschema", "completion": JSON_DICT_SCHEMA},
    ])
    out = tmp_path / "responses.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out),
                 "--report", str(tmp_path / "rep.json")])
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
                 "--report", str(tmp_path / "rep.json")])
    assert rc == 1
    rep = _json.loads((tmp_path / "rep.json").read_text())
    verd = {e["id"]: e for e in rep["records"]}
    assert "yosys-smoke ok" in verd["p_jsmoke"].get("synth", "")
    assert verd["p_jzs"]["verdict"] == "BLOCKED"
    assert [r["id"] for r in _read_jsonl(out)] == ["p_jsmoke"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
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
                 "--report", str(tmp_path / "rep.json")])
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
    src = Path("/home/reyerchu/AI_IC_design/cvdp_open_run_v0325"
               "/final_responses_r3.jsonl")
    if not src.is_file():
        src = Path("/home/reyerchu/AI_IC_design/cvdp_open_run_v0325"
                   "/final_responses.jsonl")
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
