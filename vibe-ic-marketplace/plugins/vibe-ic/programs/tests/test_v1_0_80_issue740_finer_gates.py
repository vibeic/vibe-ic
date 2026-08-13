#!/usr/bin/env python3
"""ORGANIC #740 [P2, chip-AGNOSTIC] — four FINER deterministic-gate coverage
gaps (G2 / G3 / G4 / G5). Each on a DISJOINT file.

  G4 (PRIMARY, the 驗收) — rtl_hygiene_lint.py multidriven-register rule: WARN
      when the SAME reg is driven from >1 always block in a racing / different
      clocking domain (the `verilator -Wall` MULTIDRIVEN class, made
      plugin-native). FIREs on the acceptance shape (one reset-clear block + one
      UNCONDITIONAL datapath block, same clock) and on DIFFERENT clock domains;
      does NOT false-fire on a single always block, on a reset-COMPLEMENTARY
      same-clock split, or on disjoint bit-slice writers.

  G3 — latency_conformance_check.py per-output latency: a SECOND output whose
      latency has no event->output handshake to MEASURE gets its intended
      per-output latency INFERRED from the declared intermediate pipeline
      registers feeding it (registered-chain depth). ADVISORY (never changes the
      exit code); the existing single event->output MEASURE path is unchanged.

  G5 — cvdp_gate.py EMBEDDED iface-check scoping: route the embedded
      iface_conformance_v2 advisory through the EXTRACTED RTL + the record's full
      context RTL, so a prompt-named port whose OWNING module is a
      harness-supplied / instantiated sub-module is SATISFIED — the same
      owning-module scoping the STANDALONE gate gets via `--context`.
      Advisory-only (no false-block); the alignment is the fix.

  G2 — clause_smoke_tb.py (NEW): auto-derive minimal directed stimulus from a
      prompt's relational functional clauses (faster/slower/equal, greater/less)
      for code-completion prompts with NO golden rows and no authored TB. Runs
      iverilog (shutil.which-guarded; degrade-not-block if absent);
      advisory/NOT-APPLICABLE when no clause is confidently derivable. Clause
      extraction + stimulus derivation are PURE functions, unit-testable WITHOUT
      iverilog.

chip-AGNOSTIC: pure SV structure / prompt prose / RTL port parse. No chip /
vendor / SKU literal (enforced by programs/source_chip_agnostic_check.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
BENCHMARK = PLUGIN / "benchmark"
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(BENCHMARK))

import rtl_hygiene_lint as HY            # noqa: E402
import latency_conformance_check as LAT  # noqa: E402
import clause_smoke_tb as CS             # noqa: E402
import iface_conformance_v2 as IF        # noqa: E402
from _sim_tools import NEEDS_SIM  # noqa: E402

HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


# ───────────────────────────── G4: multidriven lint ─────────────────────────
G4_PROG = PROGRAMS / "rtl_hygiene_lint.py"


def _lint_warn(tmp_path, rtl: str):
    p = tmp_path / "d.sv"
    p.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(G4_PROG), "--severity", "WARN", str(p)],
        capture_output=True, text=True, timeout=60)


def test_g4_acceptance_multidriven_warn(tmp_path):
    """驗收 END-STATE (the issue's only 驗收): rtl_hygiene_lint WARNs that `mem0`
    is driven from two always blocks (multidriven)."""
    rtl = ("module m(input clk,rst,output reg [3:0] mem0); "
           "always @(posedge clk) if(rst) mem0<=0; "
           "always @(posedge clk) mem0<=mem0+1; endmodule\n")
    r = _lint_warn(tmp_path, rtl)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "multidriven-register" in r.stdout
    assert "mem0" in r.stdout
    assert "multidriven" in r.stdout.lower()


def test_g4_fire_different_clock_domains(tmp_path):
    """A reg driven from two DIFFERENT clock domains is the genuine verilator
    MULTIDRIVEN — fires WARN."""
    rtl = ("module m(input clk_a, input clk_b, output reg q);\n"
           "  always @(posedge clk_a) q<=1'b1;\n"
           "  always @(posedge clk_b) q<=1'b0;\nendmodule\n")
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    assert any(f.symbol == "q" and "DIFFERENT clocking" in f.message for f in fs)
    assert all(f.severity == "WARN" for f in fs)


def test_g4_noleak_single_always_block(tmp_path):
    """A reg written in ONE always block (incl. the `if(rst) x<=0; else x<=d;`
    in-block reset+datapath idiom) is NEVER multidriven."""
    rtl = ("module m(input clk, input rst, output reg [3:0] cnt);\n"
           "  always @(posedge clk) if(rst) cnt<=0; else cnt<=cnt+1;\n"
           "endmodule\n")
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    assert [f for f in fs if f.rule == "multidriven-register"] == []


def test_g4_noleak_reset_complementary_same_clock_pair(tmp_path):
    """A SAME-clock reset-COMPLEMENTARY split (`if(rst)` in one block, `if(!rst)`
    in another) never both-fires on one edge → legal → no WARN."""
    rtl = ("module m(input clk, input rst, output reg [3:0] cnt);\n"
           "  always @(posedge clk) if(rst) cnt<=0;\n"
           "  always @(posedge clk) if(!rst) cnt<=cnt+1;\nendmodule\n")
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    assert [f for f in fs if f.rule == "multidriven-register"] == []


def test_g4_noleak_disjoint_bit_slices(tmp_path):
    """Two blocks writing DISJOINT bit-slices of a reg are distinct drivers of
    distinct bits — not a multidriven race."""
    rtl = ("module m(input clk, output reg [3:0] q);\n"
           "  always @(posedge clk) q[1:0]<=2'b01;\n"
           "  always @(posedge clk) q[3:2]<=2'b10;\nendmodule\n")
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    assert [f for f in fs if f.rule == "multidriven-register"] == []


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not on PATH")
def test_g4_acceptance_rtl_actually_compiles_and_is_genuinely_multidriven(tmp_path):
    """Cross-check: the acceptance RTL really DOES compile (so the WARN is about
    a real, compilable, multidriven shape — not a parse artefact)."""
    p = tmp_path / "md.sv"
    p.write_text("module m(input clk,rst,output reg [3:0] mem0); "
                 "always @(posedge clk) if(rst) mem0<=0; "
                 "always @(posedge clk) mem0<=mem0+1; endmodule\n")
    rc = subprocess.run(["iverilog", "-g2012", "-t", "null", str(p)],
                        capture_output=True, text=True, timeout=60).returncode
    assert rc == 0


# ───────────────────────── G3: per-output latency inference ─────────────────
def test_g3_infer_pipeline_depth_pure():
    """A second output fed through an N-stage register chain has inferred
    per-output latency N (PURE — no iverilog)."""
    rtl = ("module m(input clk, input start, input a, output reg done, "
           "output reg out2);\n  reg s1, s2;\n"
           "  always @(posedge clk) begin\n"
           "    s1 <= a; s2 <= s1; out2 <= s2; done <= start;\n"
           "  end\nendmodule\n")
    lat, reason = LAT.infer_output_latency_from_registers(rtl, "m", "out2")
    assert lat == 3, reason
    lat2, _ = LAT.infer_output_latency_from_registers(rtl, "m", "done")
    assert lat2 == 1


def test_g3_ambiguous_branch_depths_advisory():
    """Different chain depths feeding one output → ambiguous → None (advisory)."""
    rtl = ("module m(input clk, input a, output reg y);\n  reg p, q;\n"
           "  always @(posedge clk) begin p<=a; q<=p; end\n"
           "  always @(posedge clk) y <= a;\n"
           "  always @(posedge clk) y <= q;\nendmodule\n")
    lat, reason = LAT.infer_output_latency_from_registers(rtl, "m", "y")
    assert lat is None
    assert "ambiguous" in reason.lower()


def test_g3_comb_output_not_inferred_advisory():
    """A purely combinational output is not a registered chain → advisory None."""
    rtl = "module m(input a, output y); assign y = a; endmodule\n"
    lat, reason = LAT.infer_output_latency_from_registers(rtl, "m", "y")
    assert lat is None
    assert "registered" in reason.lower()


def test_g3_feedback_is_advisory_not_crash():
    """A register feedback loop is reported advisory (not inferred), never a
    crash / runaway."""
    rtl = ("module m(input clk, output reg y); "
           "always @(posedge clk) y <= y; endmodule\n")
    lat, reason = LAT.infer_output_latency_from_registers(rtl, "m", "y")
    assert lat is None and reason


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not on PATH")
def test_g3_cli_second_output_is_advisory_does_not_change_rc(tmp_path):
    """The existing single event->output MEASURE path is unchanged; the second
    output is reported advisory and never alters the exit code."""
    rtl = ("module m(input clk, input rst_n, input start, input [7:0] a, "
           "output reg done, output reg out2);\n  reg s1, s2;\n"
           "  always @(posedge clk) begin\n"
           "    if (!rst_n) begin s1<=0; s2<=0; out2<=0; done<=0; end\n"
           "    else begin s1<=a[0]; s2<=s1; out2<=s2; done<=start; end\n"
           "  end\nendmodule\n")
    p = tmp_path / "g3.sv"
    p.write_text(rtl)
    jp = tmp_path / "rep.json"
    # WITHOUT --second-output: pure existing path (regression guard).
    r0 = subprocess.run(
        [sys.executable, str(PROGRAMS / "latency_conformance_check.py"),
         "--rtl", str(p), "--top", "m", "--event", "start", "--output", "done",
         "--expect", "1"], capture_output=True, text=True, timeout=60)
    assert r0.returncode == 0, (r0.stdout, r0.stderr)
    assert "latency-conformance ok" in r0.stdout
    # WITH --second-output: same primary verdict + an ADVISORY note; rc unchanged.
    r1 = subprocess.run(
        [sys.executable, str(PROGRAMS / "latency_conformance_check.py"),
         "--rtl", str(p), "--top", "m", "--event", "start", "--output", "done",
         "--expect", "1", "--second-output", "out2", "--expect-second", "3",
         "--json", str(jp)], capture_output=True, text=True, timeout=60)
    assert r1.returncode == 0, (r1.stdout, r1.stderr)
    assert "latency-conformance ok" in r1.stdout
    assert "SECOND-OUTPUT-LATENCY (advisory)" in r1.stdout
    rep = json.loads(jp.read_text())
    assert rep["second_output"]["inferred_latency"] == 3
    assert rep["second_output"]["matches_spec"] is True


# ─────────────────────── G5: embedded iface-check scoping ───────────────────
def test_g5_embedded_context_loader(tmp_path):
    """_load_context_rtl returns the FULL RTL content of a record's
    input.context (not just module-name stems)."""
    import cvdp_gate as G
    ds = tmp_path / "ds.jsonl"
    rec = {"id": "cvdp_copilot_dma_engine_0001",
           "input": {"context": {
               "rtl/fifo_ctrl.sv":
               "module fifo_ctrl(input clk, output [3:0] wr_ptr); endmodule",
               "docs/spec.md": "ignore this non-rtl entry"}}}
    ds.write_text(json.dumps(rec) + "\n")
    out = G._load_context_rtl(str(ds))
    assert "cvdp_copilot_dma_engine_0001" in out
    texts = out["cvdp_copilot_dma_engine_0001"]
    assert any("fifo_ctrl" in t for t in texts)
    # the docs/spec.md (non-RTL suffix) is NOT returned
    assert not any("ignore this" in t for t in texts)


def test_g5_context_satisfies_prompt_named_submodule_port():
    """ALIGNMENT: a prompt-named port that lives on a harness-supplied CONTEXT
    sub-module false-fires MISSING-PORT WITHOUT context, but is SATISFIED when
    the context RTL is passed (what the embedded gate now does)."""
    prompt = ("The submodule fifo_ctrl exposes `wr_ptr` as an output. "
              "Implement the top dma_engine.")
    comp = ("module dma_engine(input clk, output done); "
            "fifo_ctrl u(.wr_ptr()); endmodule")
    ctx = "module fifo_ctrl(input clk, output [3:0] wr_ptr); endmodule"
    # WITHOUT context → false MISSING-PORT (the old embedded behaviour)
    f0 = IF.check_conformance("cvdp_copilot_dma_engine_0001", prompt, comp)
    assert any(x.kind == "MISSING-PORT" and "wr_ptr" in x.message for x in f0)
    # WITH context → satisfied (the aligned embedded behaviour)
    f1 = IF.check_conformance("cvdp_copilot_dma_engine_0001", prompt, comp, [ctx])
    assert not any(x.kind == "MISSING-PORT" and "wr_ptr" in x.message for x in f1)


@NEEDS_SIM
def test_g5_embedded_call_passes_extracted_code_and_context(tmp_path, monkeypatch):
    """END-STATE: the embedded iface-check inside cvdp_gate routes through the
    extracted RTL + the record's context RTL — proven by capturing the args the
    embedded check_conformance receives. The MISSING-PORT for a context-owned
    submodule port no longer surfaces in the notes."""
    import cvdp_gate as G

    # A multi-file JSON-dict completion: top dma_engine + the prompt names a
    # context submodule's port. context RTL declares the port.
    prompt = ("The submodule fifo_ctrl exposes `wr_ptr` as an output. "
              "Implement the top dma_engine.")
    completion = json.dumps({
        "rtl/dma_engine.sv":
            "module dma_engine(input clk, output done); "
            "fifo_ctrl u(.wr_ptr()); endmodule"})
    rid = "cvdp_copilot_dma_engine_0001"

    prompts_f = tmp_path / "prompts.jsonl"
    prompts_f.write_text(json.dumps({"id": rid, "prompt": prompt}) + "\n")
    dataset_f = tmp_path / "dataset.jsonl"
    dataset_f.write_text(json.dumps({
        "id": rid,
        "input": {"context": {
            "rtl/fifo_ctrl.sv":
            "module fifo_ctrl(input clk, output [3:0] wr_ptr); endmodule"}}})
        + "\n")
    batch_f = tmp_path / "batch.jsonl"
    batch_f.write_text(json.dumps({"id": rid, "completion": completion}) + "\n")
    out_f = tmp_path / "out.jsonl"
    report_f = tmp_path / "report.json"

    captured = {}
    orig_check = G._ifacev2.check_conformance

    def _spy(rid_, prompt_, rtl_, ctx_=None):
        captured["rtl"] = rtl_
        captured["ctx"] = ctx_
        return orig_check(rid_, prompt_, rtl_, ctx_)

    monkeypatch.setattr(G._ifacev2, "check_conformance", _spy)

    rc = G.main([
        "--batch", str(batch_f), "--out", str(out_f),
        "--prompts", str(prompts_f), "--dataset", str(dataset_f),
        "--report", str(report_f)])
    # the gate ran (rc 0/1 both acceptable — this completion compiles clean)
    assert rc in (0, 1)
    # the embedded check received EXTRACTED RTL (a real module decl, not the raw
    # JSON blob) AND the context RTL list (alignment proven).
    assert "module dma_engine" in (captured.get("rtl") or "")
    assert captured.get("ctx") and any(
        "fifo_ctrl" in t for t in captured["ctx"])
    # and the context-owned submodule port is NOT charged as MISSING in notes.
    report = json.loads(report_f.read_text())
    notes = " ".join(
        n for e in report.get("records", []) for n in e.get("notes", []))
    assert "wr_ptr" not in notes


# ──────────────────────── G2: clause_smoke_tb (NEW) ─────────────────────────
CS_PROG = PROGRAMS / "clause_smoke_tb.py"


def test_g2_extract_clause_gt_pure():
    """PURE: `output is high when a greater than b` → a GT clause, output HIGH
    when the relation holds."""
    inputs = {"a": "a", "b": "b"}
    outputs = {"y": "y"}
    cls = CS.extract_clauses("Output `y` is high when `a` is greater than `b`.",
                            inputs, outputs, {"y": 1})
    assert len(cls) == 1
    c = cls[0]
    assert (c.output, c.op_a, c.op_b, c.relation, c.true_value) == \
        ("y", "a", "b", "gt", 1)


def test_g2_extract_clause_eq_low_and_faster_pure():
    """PURE: polarity ('low when') + a functional synonym ('faster than'→GT)."""
    inputs = {"a": "a", "b": "b"}
    outputs = {"y": "y"}
    eq_low = CS.extract_clauses("`y` is low when `a` equals `b`.",
                               inputs, outputs, {"y": 1})
    assert eq_low and eq_low[0].relation == "eq" and eq_low[0].true_value == 0
    faster = CS.extract_clauses("Assert `y` when `a` is faster than `b`.",
                               inputs, outputs, {"y": 1})
    assert faster and faster[0].relation == "gt"


def test_g2_no_clause_when_operands_not_ports_pure():
    """PURE conservative drop: a relation whose operands are NOT RTL inputs, or
    a prompt with no relation, yields NO clause (never invented)."""
    inputs = {"a": "a", "b": "b"}
    outputs = {"y": "y"}
    assert CS.extract_clauses("`y` is high when `foo` greater than `bar`.",
                             inputs, outputs, {"y": 1}) == []
    assert CS.extract_clauses("The module counts up each cycle.",
                             inputs, outputs, {"y": 1}) == []


def test_g2_derive_stimulus_true_false_pure():
    """PURE: each clause yields a TRUE-case (relation holds, output=true_value)
    and a FALSE-case (relation violated, output=complement)."""
    c = CS.Clause(output="y", op_a="a", op_b="b", relation="gt", true_value=1)
    vs = CS.derive_stimulus(c)
    assert len(vs) == 2
    holds = [v for v in vs if v.holds][0]
    fails = [v for v in vs if not v.holds][0]
    assert holds.a > holds.b and holds.expected == 1
    assert not (fails.a > fails.b) and fails.expected == 0


def test_g2_not_applicable_when_no_clause(tmp_path):
    """NOT-APPLICABLE (rc 0) when no clause is derivable — never a false block."""
    pp = tmp_path / "p.txt"
    rp = tmp_path / "r.sv"
    pp.write_text("The module counts up.\n")
    rp.write_text("module cmp(input [7:0] a, input [7:0] b, output y);"
                  " assign y=(a>b); endmodule\n")
    r = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                        "--rtl", str(rp)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0
    assert "NOT-APPLICABLE" in r.stdout


def test_g2_iverilog_absent_degrades(monkeypatch, tmp_path):
    """When iverilog/vvp are absent the gate degrades to SKIP (rc 0), never a
    block (the binary-guard mandate)."""
    monkeypatch.setattr(CS.shutil, "which",
                        lambda x: None if x in ("iverilog", "vvp")
                        else shutil.which(x))
    rp = tmp_path / "r.sv"
    rp.write_text("module cmp(input [7:0] a, input [7:0] b, output y);"
                  " assign y=(a>b); endmodule\n")
    rc, rep = CS.run_clause_smoke(
        rp, "Output `y` is high when `a` greater than `b`.", None, False)
    assert rc == 0 and rep["verdict"] == "SKIP"


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not on PATH")
def test_g2_good_rtl_passes_bug_rtl_blocks(tmp_path):
    """END-STATE: a comparator matching the clause PASSes; one that INVERTS it
    (a < b) is BLOCKed (rc 1); --warn downgrades the block to advisory (rc 0)."""
    pp = tmp_path / "p.txt"
    pp.write_text("Output `y` is high when `a` is greater than `b`.\n")
    good = tmp_path / "good.sv"
    good.write_text("module cmp(input [7:0] a, input [7:0] b, output y);"
                    " assign y=(a>b); endmodule\n")
    bug = tmp_path / "bug.sv"
    bug.write_text("module cmp(input [7:0] a, input [7:0] b, output y);"
                   " assign y=(a<b); endmodule\n")
    rg = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                         "--rtl", str(good)], capture_output=True, text=True,
                        timeout=60)
    assert rg.returncode == 0, (rg.stdout, rg.stderr)
    assert "clause-smoke ok" in rg.stdout
    rb = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                         "--rtl", str(bug)], capture_output=True, text=True,
                        timeout=60)
    assert rb.returncode == 1, (rb.stdout, rb.stderr)
    assert "BLOCK" in rb.stdout + rb.stderr
    rw = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                         "--rtl", str(bug), "--warn"], capture_output=True,
                        text=True, timeout=60)
    assert rw.returncode == 0, (rw.stdout, rw.stderr)


# ──────── G2 REMEDIATION (v1.0.80 adversarial review): offset false-block ────
# Reviewer finding: a prompt with an arithmetic OFFSET / MODIFIER between/after
# the operands — "a greater than b BY AT LEAST 2" => y=(a>b+2) — was matched as a
# bare relation (at-least→ge / greater-than→gt) with the offset DROPPED, so the
# derived vector drove a=6,b=5 expecting y=1 while the CORRECT RTL `y=(a>(b+2))`
# gives 0 → the gate FALSE-BLOCKed a correct design (rc 1). Fix: drop such clauses
# to NOT-APPLICABLE rather than assert a wrong expectation.

def test_g2_offset_clause_dropped_pure():
    """PURE (no iverilog): the reviewer's EXACT offset prompt yields NO clause —
    the bare-relation model cannot represent `by at least 2`, so it is DROPPED
    (NOT-APPLICABLE) instead of emitting a wrong-expectation clause."""
    inputs = {"a": "a", "b": "b"}
    outputs = {"y": "y"}
    cls = CS.extract_clauses(
        "Output `y` is high when `a` is greater than `b` by at least 2.",
        inputs, outputs, {"y": 1})
    assert cls == []


def test_g2_offset_variants_all_dropped_pure():
    """PURE: every arithmetic-modifier phrasing the bare relation can't represent
    is dropped — 'by more than N', 'plus N', '+ N', 'within N'."""
    inputs = {"a": "a", "b": "b"}
    outputs = {"y": "y"}
    for cond in (
        "Output `y` is high when `a` exceeds `b` by more than 3.",
        "Output `y` is high when `a` is greater than `b` plus 2.",
        "Output `y` is high when `a` > `b` + 2.",
        "Output `y` is high when `a` equals `b` within 1.",
    ):
        assert CS.extract_clauses(cond, inputs, outputs, {"y": 1}) == [], cond


def test_g2_offset_detector_noleak_on_clean_and_port_digits_pure():
    """PURE noleak: the offset detector does NOT trip on a clean relation, nor on
    a port NAME whose own token carries a digit (reg1 / data0) — those still
    yield a real clause."""
    # clean relation → a real clause survives
    inputs = {"a": "a", "b": "b"}
    outputs = {"y": "y"}
    clean = CS.extract_clauses("Output `y` is high when `a` is greater than `b`.",
                              inputs, outputs, {"y": 1})
    assert len(clean) == 1 and clean[0].relation == "gt"
    # port-name digits must NOT be mistaken for a numeric offset
    assert CS.condition_has_unrepresentable_offset(
        " reg1 is greater than reg2", "reg1", "reg2") is False
    assert CS.condition_has_unrepresentable_offset(
        " data0 differs from data1", "data0", "data1") is False
    # an actual offset IS detected
    assert CS.condition_has_unrepresentable_offset(
        " a is greater than b by at least 2", "a", "b") is True


def test_g2_offset_repro_returns_not_applicable_not_block(tmp_path):
    """END-STATE (reviewer's exact repro, no iverilog needed for the verdict —
    NOT-APPLICABLE is decided BEFORE any tool run): the offset prompt + a CORRECT
    `y=(a>(b+2))` RTL returns NOT-APPLICABLE (rc 0), never a false BLOCK."""
    pp = tmp_path / "offset_prompt.txt"
    pp.write_text("Output `y` is high when `a` is greater than `b` by at least 2.")
    rp = tmp_path / "offset.sv"
    rp.write_text("module cmp(input [7:0] a,input [7:0] b,output y); "
                  "assign y=(a>(b+8'd2)); endmodule\n")
    r = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                        "--rtl", str(rp)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "NOT-APPLICABLE" in r.stdout
    assert "BLOCK" not in (r.stdout + r.stderr)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not on PATH")
def test_g2_clean_relation_still_catches_wrong_rtl_after_fix(tmp_path):
    """REGRESSION GUARD: the original fix's motivating case is intact — a CLEAN
    no-offset relation still PASSes a correct comparator and still BLOCKs an
    inverted one (the offset drop must NOT have disarmed the gate)."""
    pp = tmp_path / "p.txt"
    pp.write_text("Output `y` is high when `a` is greater than `b`.\n")
    good = tmp_path / "good.sv"
    good.write_text("module cmp(input [7:0] a, input [7:0] b, output y);"
                    " assign y=(a>b); endmodule\n")
    bug = tmp_path / "bug.sv"
    bug.write_text("module cmp(input [7:0] a, input [7:0] b, output y);"
                   " assign y=(a<b); endmodule\n")
    rg = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                         "--rtl", str(good)], capture_output=True, text=True,
                        timeout=60)
    assert rg.returncode == 0 and "clause-smoke ok" in rg.stdout, (rg.stdout, rg.stderr)
    rb = subprocess.run([sys.executable, str(CS_PROG), "--prompt", str(pp),
                         "--rtl", str(bug)], capture_output=True, text=True,
                        timeout=60)
    assert rb.returncode == 1 and "BLOCK" in (rb.stdout + rb.stderr), (rb.stdout, rb.stderr)


# ─────────────────────────── chip-AGNOSTIC source guard ─────────────────────
def test_chip_agnostic_source():
    guard = PROGRAMS / "source_chip_agnostic_check.py"
    r = subprocess.run([sys.executable, str(guard), str(PLUGIN)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
