#!/usr/bin/env python3
"""GATE-AS-SOLE-EMIT — the two self-verify gates already PRESENT in cvdp_gate
(#729 area-threshold + #705 latency-conformance) must BLOCK a bad draft PRE-EMIT
on the BLIND CVDP authoring path, so a fresh blind run cannot silently emit a
wrong-latency or sub-threshold-area completion.

Before this wiring both gates only fired with an operator flag (#705 needed
``--latency-specs``; #729 was used only for the synth-TIMEOUT tolerance, never to
block sub-threshold area). Now:
  * cid007 / area-opt records run #729 on (ORIGINAL input.context baseline,
    OPTIMIZED completion) and BLOCK a real measured sub-threshold reduction,
    HONORING #729's near-minimal escape (a design that genuinely cannot clear the
    bar is NOT false-blocked);
  * a prompt that states an UNAMBIGUOUS "`out` asserts N cycles after `event`"
    latency literal AUTO-DERIVES the #705 contract so it fires WITHOUT
    ``--latency-specs``.

Both are PURELY ADDITIVE: a record that is neither cid007 nor latency-stated must
behave EXACTLY as today.

Tests
=====
PURE (no EDA tools) — always run
  * latency_contract_from_prompt: positives (int / WIDTH+2 / glued ports),
    negatives (vague word, non-backticked port, period-crossing), and the
    negation/bound guards ('not asserted', 'within N cycles').
  * area_threshold_gate_record WIRING via a monkeypatched #729 runner: a BLOCK
    verdict → ok=False; NOT_APPLICABLE / PASS → ok=True; a missing baseline /
    ambiguous top / no-RTL completion → advisory ok=True (never a false block).

END-TO-END through main() — iverilog + yosys gated
  * (a) a cid007 record whose #729 runner reports BLOCK (monkeypatched, so no
        docker needed) is DROPPED from the emitted JSONL and main() exits 1.
  * (a') a cid007 record whose #729 runner reports NOT_APPLICABLE (near-minimal
         escape) is NOT blocked — emitted, exit 0 (no false block).
  * (b) a record with an explicit "`done` asserts 3 cycles after `start`" prompt
        + a WRONG-latency (1-cycle) RTL is BLOCKED (#705 MISMATCH) via real
        iverilog measurement.
  * (c) a plain functional record (no cid007, no latency literal) is UNAFFECTED:
        emitted unchanged, exit 0, and neither pre-emit block touches it.

chip-AGNOSTIC: tiny inline RTL fixtures, no benchmark data.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(PROGRAMS))
import cvdp_gate as G  # noqa: E402

import pytest  # noqa: E402

_HAVE_IVERILOG = shutil.which("iverilog") is not None and \
    shutil.which("vvp") is not None
_HAVE_YOSYS = shutil.which("yosys") is not None
_HAVE_EDA = _HAVE_IVERILOG and _HAVE_YOSYS

# ── tiny inline RTL fixtures ─────────────────────────────────────────────────
# A self-contained combinational module (synthesises instantly).
_AND2 = ("module and2(input a, input b, output y);\n"
         "  assign y = a & b;\nendmodule\n")

# WRONG-latency: `done` asserts ONE cycle after `start` (registered passthrough).
# The prompt will state THREE cycles → a measured MISMATCH (1 != 3) → BLOCK.
_LAT_WRONG = (
    "module lat(input clk, input rst_n, input start, output reg done);\n"
    "  always @(posedge clk or negedge rst_n)\n"
    "    if (!rst_n) done <= 1'b0; else done <= start;\n"
    "endmodule\n")

# An ORIGINAL area baseline + a do-nothing OPTIMIZED copy (used only by the
# monkeypatched-runner wiring tests; the real #729 measurement is unit-tested in
# its own file).
_AREA_ORIG = ("module redux(input [7:0] a, input [7:0] b, output [7:0] y);\n"
              "  assign y = (a & b) | (a & b) | (a | b);\nendmodule\n")
_AREA_OPT = _AREA_ORIG  # do-nothing


# ════════════════════════════ PURE: latency contract ════════════════════════
def test_latency_contract_positive_int():
    c = G.latency_contract_from_prompt(
        "The output `done` asserts 3 cycles after `start` is pulsed.")
    assert c == {"event": "start", "output": "done", "expect": "3"}


def test_latency_contract_positive_param_expr():
    c = G.latency_contract_from_prompt(
        "Signal `valid` goes high WIDTH+2 cycles after the rising edge "
        "of `start`.")
    assert c == {"event": "start", "output": "valid", "expect": "WIDTH+2"}


def test_latency_contract_positive_glued_ports_one_cycle():
    c = G.latency_contract_from_prompt(
        "`o_ready` becomes high 1 clock cycle after `i_req`.")
    assert c == {"event": "i_req", "output": "o_ready", "expect": "1"}


def test_latency_contract_negative_vague_word():
    # 'several' is not a clean cycle count → never fire.
    assert G.latency_contract_from_prompt(
        "`done` asserts several cycles after `start`.") is None


def test_latency_contract_negative_unquoted_ports():
    # both ports MUST be backtick-quoted signal names.
    assert G.latency_contract_from_prompt(
        "done asserts 3 cycles after start.") is None
    assert G.latency_contract_from_prompt(
        "`done` asserts 3 cycles after the start signal.") is None


def test_latency_contract_negative_sentence_break():
    # a '.' between the output and the count breaks the (single-clause) literal.
    assert G.latency_contract_from_prompt(
        "`done` asserts. 3 cycles after `start`.") is None


def test_latency_contract_guard_negation_and_bound():
    # 'not asserted' (negation) and 'within N cycles' (a watchdog BOUND, not an
    # exact latency) must NOT be enforced — the apb_pready_i/ACCESS shape.
    assert G.latency_contract_from_prompt(
        "`apb_pready_i` is not asserted within 15 cycles after entering "
        "`ACCESS`.") is None
    assert G.latency_contract_from_prompt(
        "`busy` goes high within 8 cycles after `go`.") is None


def test_latency_contract_plain_functional_prompt():
    assert G.latency_contract_from_prompt(
        "Implement a 4-bit counter that increments on each clock edge.") is None


# ═══════════════════ PURE: area helper wiring (monkeypatched #729) ═══════════
def _block_runner(**kw):
    return 1, {"verdict": "BLOCK", "reason": "stub: measured sub-threshold"}


def _not_applicable_runner(**kw):
    return 0, {"verdict": "NOT_APPLICABLE",
               "reason": "stub: unreachable-target / near-minimal escape"}


def _pass_runner(**kw):
    return 0, {"verdict": "PASS", "reason": "stub: reduction meets threshold"}


def test_area_helper_block_wiring(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "_ppa_area_run", _block_runner)
    ok, note = G.area_threshold_gate_record(
        "id1", _AREA_OPT, [_AREA_ORIG], "reduce cells and wires by 20%",
        "redux", tmp_path)
    assert ok is False
    assert "area BLOCK" in note


def test_area_helper_advisory_on_not_applicable(monkeypatch, tmp_path):
    # the near-minimal / unreachable-target escape → NOT a false block.
    monkeypatch.setattr(G, "_ppa_area_run", _not_applicable_runner)
    ok, note = G.area_threshold_gate_record(
        "id1", _AREA_OPT, [_AREA_ORIG], "reduce cells and wires by 20%",
        "redux", tmp_path)
    assert ok is True
    assert "NOT_APPLICABLE" in note


def test_area_helper_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "_ppa_area_run", _pass_runner)
    ok, _note = G.area_threshold_gate_record(
        "id1", _AREA_OPT, [_AREA_ORIG], "reduce cells and wires by 20%",
        "redux", tmp_path)
    assert ok is True


def test_area_helper_advisory_on_missing_baseline(monkeypatch, tmp_path):
    # no input.context baseline → cannot measure → advisory-PASS (never block).
    monkeypatch.setattr(G, "_ppa_area_run", _block_runner)  # would block if run
    ok, note = G.area_threshold_gate_record(
        "id1", _AREA_OPT, [], "reduce cells and wires by 20%", "redux",
        tmp_path)
    assert ok is True
    assert "baseline" in note


def test_area_helper_advisory_on_ambiguous_top(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "_ppa_area_run", _block_runner)  # would block if run
    ok, note = G.area_threshold_gate_record(
        "id1", _AREA_OPT, [_AREA_ORIG], "reduce cells and wires by 20%",
        None, tmp_path)
    assert ok is True
    assert "ambiguous" in note


def test_area_top_single_shared_module():
    assert G._area_top([_AREA_ORIG], _AREA_OPT) == "redux"


def test_area_top_ambiguous_returns_none():
    base = "module a(); endmodule\nmodule b(); endmodule"
    comp = "module a(); endmodule\nmodule b(); endmodule"
    assert G._area_top([base], comp) is None


# ═══════════════════ END-TO-END through main() (EDA-gated) ═══════════════════
def _write(p: Path, records):
    p.write_text("".join(json.dumps(r) + "\n" for r in records))


def _run_main(tmp_path, batch, prompts=None, dataset=None):
    out = tmp_path / "out.jsonl"
    rep = tmp_path / "rep.json"
    bf = tmp_path / "batch.jsonl"
    _write(bf, batch)
    argv = ["--batch", str(bf), "--out", str(out), "--report", str(rep)]
    if prompts is not None:
        pf = tmp_path / "prompts.jsonl"
        _write(pf, prompts)
        argv += ["--prompts", str(pf)]
    if dataset is not None:
        df = tmp_path / "dataset.jsonl"
        _write(df, dataset)
        argv += ["--dataset", str(df)]
    rc = G.main(argv)
    emitted = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    report = json.loads(rep.read_text())
    return rc, emitted, report


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_cid007_blocks_subthreshold(monkeypatch, tmp_path):
    # (a) a cid007 record whose #729 runner reports BLOCK → DROPPED, exit 1.
    # Monkeypatch the synth runner so the block is deterministic (no docker).
    monkeypatch.setattr(G, "_ppa_area_run", _block_runner)
    rid = "cvdp_copilot_redux_0001"
    batch = [{"id": rid, "completion": _AREA_OPT}]
    prompts = [{"id": rid, "prompt": "Optimize: reduce cells and wires by 20%."}]
    dataset = [{"id": rid, "categories": ["cid007"],
                "input": {"context": {"rtl/redux.sv": _AREA_ORIG}}}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts, dataset)
    assert rc == 1
    assert all(r.get("id") != rid for r in emitted)
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert entry["verdict"] == "BLOCKED"
    assert "area BLOCK" in entry.get("area", "")


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_cid007_not_blocked_when_near_minimal(monkeypatch, tmp_path):
    # (a') the near-minimal escape (NOT_APPLICABLE) must NOT block (no false block).
    monkeypatch.setattr(G, "_ppa_area_run", _not_applicable_runner)
    rid = "cvdp_copilot_redux_0002"
    batch = [{"id": rid, "completion": _AREA_OPT}]
    prompts = [{"id": rid, "prompt": "Optimize: reduce cells and wires by 20%."}]
    dataset = [{"id": rid, "categories": ["cid007"],
                "input": {"context": {"rtl/redux.sv": _AREA_ORIG}}}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts, dataset)
    assert rc == 0
    assert any(r.get("id") == rid for r in emitted)
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert entry["verdict"] == "PASS"
    assert "NOT_APPLICABLE" in entry.get("area", "")


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_latency_blocks_wrong_latency(tmp_path):
    # (b) explicit "`done` asserts 3 cycles after `start`" prompt + 1-cycle RTL
    # → real #705 MISMATCH → BLOCKED. No --latency-specs supplied.
    rid = "cvdp_copilot_lat_0001"
    batch = [{"id": rid, "completion": _LAT_WRONG}]
    prompts = [{"id": rid,
                "prompt": "The output `done` asserts 3 cycles after `start`."}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 1
    assert all(r.get("id") != rid for r in emitted)
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert entry["verdict"] == "BLOCKED"
    assert entry.get("latency_contract_source") == "prompt-derived"
    assert entry.get("latency", "").startswith("latency MISMATCH")


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_plain_functional_unaffected(monkeypatch, tmp_path):
    # (c) a plain record (no cid007, no latency literal) is UNAFFECTED: emitted
    # unchanged, exit 0, and neither pre-emit block is even invoked.
    def _boom(**kw):  # if the area runner is reached for a non-area record, fail
        raise AssertionError("area runner must NOT run for a plain record")
    monkeypatch.setattr(G, "_ppa_area_run", _boom)
    rid = "cvdp_copilot_and2_0001"
    batch = [{"id": rid, "completion": _AND2}]
    prompts = [{"id": rid, "prompt": "Implement a 2-input AND gate."}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "endmodule" in em["completion"]
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert entry["verdict"] == "PASS"
    assert "area" not in entry              # area block never entered
    assert "latency" not in entry          # latency block never entered
    assert "lint" not in entry             # lint block never entered
    assert "spec_conformance" not in entry  # spec block skipped (no interface)


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_plain_functional_byte_identical_with_and_without_change(tmp_path):
    # the emitted completion for a plain functional record is byte-identical to
    # the de-fenced compiled payload (today's behaviour, unchanged).
    rid = "cvdp_copilot_and2_0002"
    batch = [{"id": rid, "completion": _AND2}]
    rc, emitted, _report = _run_main(tmp_path, batch)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    # bare RTL emits the compiled payload unchanged (single-file normalize).
    assert em["completion"].strip().endswith("endmodule")


# ════════════════ HOOK 1: verilator lint-zero (cid007 lint tasks) ════════════
# width-truncation + unused-bits → 2 verilator -Wall warnings; iverilog accepts.
_LINT_DIRTY = ("module trunc(input [7:0] a, output [3:0] y);\n"
               "  assign y = a;\nendmodule\n")
_LINT_CLEAN = ("module trunc(input [7:0] a, output [7:0] y);\n"
               "  assign y = a;\nendmodule\n")
_LINT_PROMPT = "Fix the width issues. Only provide the Lint-clean RTL code."


def test_lint_task_detect():
    assert G._is_lint_clean_task("Only provide the Lint-clean RTL code.", False)
    assert G._is_lint_clean_task("The design must have zero warnings.", False)
    assert G._is_lint_clean_task("anything", True)            # a .vlt waiver
    assert not G._is_lint_clean_task("Implement a counter.", False)
    # the bare word 'verilator' (a lint_off macro in provided code) is NOT a task
    assert not G._is_lint_clean_task(
        "Use `verilator lint_off PINCONNECTEMPTY` in the macro.", False)


@pytest.mark.skipif(shutil.which("verilator") is None, reason="needs verilator")
def test_verilator_lint_block_on_warning(tmp_path):
    ok, note = G.verilator_lint_gate_record(
        "id1", _LINT_DIRTY, None, "trunc", tmp_path)
    assert ok is False
    assert "lint warnings remain" in note


@pytest.mark.skipif(shutil.which("verilator") is None, reason="needs verilator")
def test_verilator_lint_pass_on_clean(tmp_path):
    ok, note = G.verilator_lint_gate_record(
        "id1", _LINT_CLEAN, None, "trunc", tmp_path)
    assert ok is True
    assert "lint clean" in note


def test_verilator_lint_advisory_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(G.shutil, "which", lambda _x: None)
    ok, note = G.verilator_lint_gate_record(
        "id1", _LINT_DIRTY, None, "trunc", tmp_path)
    assert ok is True
    assert "verilator unavailable" in note


@pytest.mark.skipif(not (_HAVE_EDA and shutil.which("verilator")),
                    reason="needs iverilog + yosys + verilator")
def test_main_lint_task_advisory_without_harness_waiver(tmp_path):
    # OFFICIAL-COMPLIANCE: the official lint bar is the harness `.vlt` waiver,
    # which the gate no longer reads. Without a model-visible waiver the gate's
    # bare `-Wall` bar is STRICTER than the official one, so a lint warning is
    # ADVISORY-only (emitted, never blocked) — a BLOCK here would §4.05-false-block
    # a completion clean under the hidden waiver. (Providing the waiver via
    # input.context — a legitimate model input — re-enables the block; see below.)
    rid = "cvdp_copilot_lint_0001"
    batch = [{"id": rid, "completion": _LINT_DIRTY}]
    prompts = [{"id": rid, "prompt": _LINT_PROMPT}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 0                                   # advisory — not blocked
    assert any(r.get("id") == rid for r in emitted)  # completion IS emitted
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert entry.get("verdict") != "BLOCKED"
    assert "advisory" in entry.get("lint", "")


@pytest.mark.skipif(not (_HAVE_EDA and shutil.which("verilator")),
                    reason="needs iverilog + yosys + verilator")
def test_main_lint_task_clean_passes(tmp_path):
    rid = "cvdp_copilot_lint_0002"
    batch = [{"id": rid, "completion": _LINT_CLEAN}]
    prompts = [{"id": rid, "prompt": _LINT_PROMPT}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 0
    assert any(r.get("id") == rid for r in emitted)
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "lint clean" in entry.get("lint", "")


# ════════════════ HOOK 2: spec↔RTL contract (authoritative header) ═══════════
_SPEC_PROMPT = (
    "Implement the module with this exact interface:\n\n"
    "```verilog\n"
    "module widget(input clk, input rst_n, input en, output q);\n"
    "endmodule\n"
    "```\n")
_SPEC_GOOD = ("module widget(input clk, input rst_n, input en, output q);\n"
              "  reg r;\n  always @(posedge clk) r <= en;\n"
              "  assign q = r;\nendmodule\n")
_SPEC_MISSING = ("module widget(input clk, input rst_n, output q);\n"
                 "  assign q = 1'b0;\nendmodule\n")


def test_spec_conformance_block_missing_port():
    ok, note = G.spec_conformance_gate_record(
        "id1", _SPEC_MISSING, _SPEC_PROMPT, "widget")
    assert ok is False
    assert "port-missing(en)" in note


def test_spec_conformance_good_interface_passes():
    ok, note = G.spec_conformance_gate_record(
        "id1", _SPEC_GOOD, _SPEC_PROMPT, "widget")
    assert ok is True
    assert note.startswith("spec-conformance ok")


def test_spec_conformance_advisory_when_nl_source():
    # NL bullets (source != 'verilog') → never block, even with a missing port.
    nl = ("Interface:\n- input clk\n- input rst_n\n- input en (1 bit)\n"
          "- output q\n")
    ok, _note = G.spec_conformance_gate_record(
        "id1", _SPEC_MISSING, nl, "widget")
    assert ok is True


def test_spec_conformance_skip_when_top_not_declared():
    # the all-ports-missing false-block class: intended top absent from the
    # completion (a submodule would be compared) → advisory-skip, never block.
    other = ("module helper(input a, output b);\n  assign b = a;\nendmodule\n")
    ok, note = G.spec_conformance_gate_record(
        "id1", other, _SPEC_PROMPT, "widget")
    assert ok is True
    assert "not declared as such" in note


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_spec_conformance_blocks_missing_port(tmp_path):
    rid = "cvdp_copilot_widget_0001"
    batch = [{"id": rid, "completion": _SPEC_MISSING}]
    prompts = [{"id": rid, "prompt": _SPEC_PROMPT}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 1
    assert all(r.get("id") != rid for r in emitted)
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert entry["verdict"] == "BLOCKED"
    assert "port-missing(en)" in entry.get("spec_block", "")


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_spec_conformance_good_passes(tmp_path):
    rid = "cvdp_copilot_widget_0002"
    batch = [{"id": rid, "completion": _SPEC_GOOD}]
    prompts = [{"id": rid, "prompt": _SPEC_PROMPT}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 0
    assert any(r.get("id") == rid for r in emitted)


# ════════════════ HOOK 3: module-id → harness TOPLEVEL rename ════════════════
_RENAME_RTL = ("module wrong_name(input a, output y);\n"
               "  assign y = a;\nendmodule\n")


def test_rename_sole_module():
    out = G.maybe_rename_top(_RENAME_RTL, "real_top")
    assert "module real_top(" in out and "wrong_name" not in out


def test_rename_noop_when_present():
    rtl = "module real_top(input a, output y); assign y=a; endmodule"
    assert G.maybe_rename_top(rtl, "real_top") == rtl


def test_rename_noop_when_no_harness_top():
    assert G.maybe_rename_top(_RENAME_RTL, None) == _RENAME_RTL


def test_rename_multi_root_single_parent():
    rtl = ("module top(input a, output y);\n  sub u(.a(a), .y(y));\nendmodule\n"
           "module sub(input a, output y);\n  assign y = a;\nendmodule\n")
    out = G.maybe_rename_top(rtl, "X")
    assert "module X(" in out and "module sub(" in out and out.count("module X(") == 1


def test_rename_ambiguous_two_roots_noop():
    rtl = ("module a(input x, output y); assign y=x; endmodule\n"
           "module b(input p, output q); assign q=p; endmodule\n")
    assert G.maybe_rename_top(rtl, "X") == rtl


def test_rename_endmodule_label():
    rtl = "module wrong_name(input a, output y); assign y=a; endmodule : wrong_name"
    out = G.maybe_rename_top(rtl, "real_top")
    assert "module real_top(" in out and "endmodule : real_top" in out


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_does_not_rename_from_harness_env(tmp_path):
    # OFFICIAL-COMPLIANCE (negative no-leak): the harness `.env` is NOT provided
    # to the model (CVDP README_NON_AGENTIC; paper §2 "never see the test
    # harness"). So even when the dataset's `.env` fixes TOPLEVEL=real_top and the
    # completion declares `wrong_name`, the gate MUST NOT read the `.env` and MUST
    # NOT rename — `wrong_name` is kept (a prompt-under-determined name is an
    # accepted floor, not a harness-repair target).
    rid = "cvdp_copilot_rename_0001"
    batch = [{"id": rid, "completion": _RENAME_RTL}]
    dataset = [{"id": rid,
                "harness": {"files": {"src/.env": "TOPLEVEL=real_top\n"}}}]
    rc, emitted, _report = _run_main(tmp_path, batch, dataset=dataset)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "module wrong_name" in em["completion"]       # .env IGNORED
    assert "module real_top" not in em["completion"]


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_renames_from_prompt_skeleton_only(tmp_path):
    # OFFICIAL-COMPLIANCE (positive): the COMPLIANT name source is the PROMPT's
    # ```verilog module <X>( skeleton (input.prompt, a legitimate model input).
    # A completion declaring `wrong_name` IS renamed to the prompt-stated top.
    rid = "cvdp_copilot_rename_0003"
    batch = [{"id": rid, "completion": _RENAME_RTL}]
    prompts = [{"id": rid,
                "prompt": "Implement:\n```verilog\nmodule real_top("
                          "input a, output y);\nendmodule\n```\n"}]
    rc, emitted, _report = _run_main(tmp_path, batch, prompts=prompts)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "module real_top" in em["completion"]         # prompt-derived rename
    assert "module wrong_name" not in em["completion"]


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_no_harness_top_keeps_original_name(tmp_path):
    # additive: with NO harness top, the emit keeps the original module name.
    rid = "cvdp_copilot_rename_0002"
    batch = [{"id": rid, "completion": _RENAME_RTL}]
    rc, emitted, _report = _run_main(tmp_path, batch)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "module wrong_name" in em["completion"]


# ════════════ A1 fix — param-width vs literal-width must NOT false-block ══════
_A1_HEADER_PROMPT = ("Implement:\n```verilog\n"
                     "module datapath(input clk, input [7:0] din, "
                     "output [7:0] dout);\nendmodule\n```\n")
# a CORRECT parameter-width completion (default 8 == identical interface).
_A1_PARAM_OK = ("```verilog\nmodule datapath #(parameter W=8)"
                "(input clk, input [W-1:0] din, output reg [W-1:0] dout);\n"
                "  always @(posedge clk) dout <= din;\nendmodule\n```")
# a GENUINE literal↔literal width mismatch ([3:0] vs the header's [7:0]).
_A1_LITERAL_BAD = ("```verilog\nmodule datapath(input clk, input [3:0] din, "
                   "output reg [3:0] dout);\n"
                   "  always @(posedge clk) dout <= din;\nendmodule\n```")


def test_a1_param_width_not_false_blocked():
    ok, note = G.spec_conformance_gate_record(
        "x", _A1_PARAM_OK, _A1_HEADER_PROMPT, "datapath")
    assert ok is True                       # parameter width → NOT a block
    # the width-mismatch is still surfaced as an ADVISORY, just not blocking.
    assert "port-width-mismatch" in note


def test_a1_literal_width_mismatch_still_blocks():
    ok, note = G.spec_conformance_gate_record(
        "x", _A1_LITERAL_BAD, _A1_HEADER_PROMPT, "datapath")
    assert ok is False
    assert "port-width-mismatch" in note


def test_a1_literal_width_helper():
    lit = G._literal_width_ports("module m(input [7:0] a, input [W-1:0] b, "
                                 "output c); endmodule")
    assert "a" in lit and "c" in lit       # literal [7:0] and scalar are literal
    assert "b" not in lit                  # [W-1:0] is parameter → non-literal


# ════════════ A2 fix — conditional-latency prose must NOT auto-derive ════════
def test_a2_conditional_trailing_skipped():
    for p in (
        "The output `ack` asserts 3 cycles after `req`, but only when ready.",
        "`done` goes high 2 cycles after `start`, assuming back-pressure is low.",
        "`valid` asserts WIDTH+1 cycles after `go` when the buffer is not full.",
        "`out` is set 3 cycles after `in` unless reset is asserted.",
    ):
        assert G.latency_contract_from_prompt(p) is None, p


def test_a2_preceding_when_still_fires():
    # a 'when' in a PRECEDING value-observation clause must NOT drop a genuine
    # unconditional contract (the sobel_filter_0011 shape).
    c = G.latency_contract_from_prompt(
        "Initially observed as `8'd0` when `valid_out` goes high "
        "(1 clock cycle after first `valid_in`).")
    assert c == {"event": "valid_in", "output": "valid_out", "expect": "1"}


def test_a2_unconditional_still_fires():
    assert G.latency_contract_from_prompt(
        "`done` asserts 3 cycles after `start`.") is not None


# ════════════ B1 — prompt-example self-test (arithmetic / table) ═════════════
_MULT_PROMPT = ("Module mult. Example: 6 * 7 = 42. Inputs a[7:0], b[7:0]; "
                "output [15:0] p.")
_MULT_OK = "module mult(input [7:0] a,b, output [15:0] p); assign p=a*b; endmodule\n"
_MULT_BAD = "module mult(input [7:0] a,b, output [15:0] p); assign p=a+b; endmodule\n"


@pytest.mark.skipif(
    not _HAVE_IVERILOG,
    reason="prompt_selftest_gate_record RUNS the extracted vector. Without "
           "iverilog+vvp it returns the honest 'prompt-selftest SKIP: "
           "iverilog/vvp not on PATH' — a REFUSAL TO RUN, not a verdict "
           "about the design these two assert on.")
def test_b1_prompt_selftest_detects_wrong():
    # the helper DETECTS a FAIL (ok=False), so a caller COULD block — but the
    # gate consumes it advisory-only (see test_main_b1_prompt_selftest_advisory).
    ok, note = G.prompt_selftest_gate_record("x", _MULT_BAD, _MULT_PROMPT, "mult")
    assert ok is False
    assert note.startswith("prompt-selftest FAIL")


@pytest.mark.skipif(
    not _HAVE_IVERILOG,
    reason="prompt_selftest_gate_record RUNS the extracted vector. Without "
           "iverilog+vvp it returns the honest 'prompt-selftest SKIP: "
           "iverilog/vvp not on PATH' — a REFUSAL TO RUN, not a verdict "
           "about the design these two assert on.")
def test_b1_prompt_selftest_pass_on_correct():
    ok, note = G.prompt_selftest_gate_record("x", _MULT_OK, _MULT_PROMPT, "mult")
    assert ok is True
    assert note.startswith("prompt-selftest PASS")


def test_b1_advisory_when_no_example():
    ok, _note = G.prompt_selftest_gate_record(
        "x", _MULT_OK, "Implement a multiplier.", "mult")
    assert ok is True                       # no extractable example → advisory


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_b1_prompt_selftest_advisory_not_block(tmp_path):
    # §4.05 — B1 is ADVISORY in the gate (it false-fires on cycle-table /
    # intermediate-step shapes, so a blocking B1 would discard real passes). A
    # B1 FAIL is surfaced as an advisory note but the record is STILL EMITTED.
    rid = "cvdp_copilot_mult_0001"
    batch = [{"id": rid, "completion": _MULT_BAD}]
    prompts = [{"id": rid, "prompt": _MULT_PROMPT}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 0                                   # NOT blocked
    assert any(r.get("id") == rid for r in emitted)  # emitted
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "prompt-selftest FAIL" in entry.get("prompt_selftest", "")
    assert "ADVISORY" in entry.get("prompt_selftest", "")
    assert "selftest_block" not in entry             # never a block tag


# ════════════ B2 — spec-example smoke TB (combinational direct-row) ══════════
_ADD_PROMPT = "Module add2. Example: a=3,b=4 -> sum=7. Compute sum = a + b."
_ADD_OK = "module add2(input [7:0] a,b, output [8:0] sum); assign sum=a+b; endmodule\n"
_ADD_BAD = "module add2(input [7:0] a,b, output [8:0] sum); assign sum=8'd0; endmodule\n"


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="needs iverilog + vvp")
def test_b2_spec_smoke_block_on_wrong(tmp_path):
    ok, note = G.spec_example_smoke_gate_record(
        "x", _ADD_BAD, _ADD_PROMPT, "add2", tmp_path)
    assert ok is False
    assert note.startswith("spec-example-smoke BLOCK")


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="needs iverilog + vvp")
def test_b2_spec_smoke_pass_on_correct(tmp_path):
    ok, note = G.spec_example_smoke_gate_record(
        "x", _ADD_OK, _ADD_PROMPT, "add2", tmp_path)
    assert ok is True
    assert note.startswith("spec-example-smoke PASS")


def test_b2_advisory_when_no_rows(tmp_path):
    ok, _note = G.spec_example_smoke_gate_record(
        "x", _ADD_OK, "Implement an adder.", "add2", tmp_path)
    assert ok is True                       # no extractable golden row → advisory


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_b2_spec_smoke_blocks(tmp_path):
    rid = "cvdp_copilot_add2_0001"
    batch = [{"id": rid, "completion": _ADD_BAD}]
    prompts = [{"id": rid, "prompt": _ADD_PROMPT}]
    rc, emitted, report = _run_main(tmp_path, batch, prompts)
    assert rc == 1
    assert all(r.get("id") != rid for r in emitted)
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "spec-example-smoke BLOCK" in entry.get("smoke_block", "")


# ════════════ B3 — FSM transition completeness (#522, zero-FP) ═══════════════
_FSM_LATCH = (
    "module m(input clk, input rst, input x, output reg y);\n"
    " localparam A=2'd0, B=2'd1, C=2'd2;\n"
    " reg [1:0] state, next_state;\n"
    " always @(posedge clk) if(rst) state<=A; else state<=next_state;\n"
    " always @(*) begin\n"
    "   case(state)\n"
    "     A: next_state = x ? B : A;\n"
    "     B: next_state = C;\n"
    "     C: y = 1'b1;\n"
    "   endcase\n"
    " end\nendmodule\n")
_FSM_CLEAN = (
    "module m(input clk, input rst, input x, output reg y);\n"
    " localparam A=2'd0, B=2'd1, C=2'd2;\n"
    " reg [1:0] state, next_state;\n"
    " always @(posedge clk) if(rst) state<=A; else state<=next_state;\n"
    " always @(*) begin\n"
    "   next_state = state;\n"
    "   case(state)\n"
    "     A: next_state = x ? B : A;\n"
    "     B: next_state = C;\n"
    "     C: next_state = A;\n"
    "   endcase\n"
    " end\n always @(*) y = (state==C);\nendmodule\n")


def test_b3_fsm_completeness_block_on_latch():
    ok, note = G.fsm_completeness_gate_record("x", _FSM_LATCH)
    assert ok is False
    assert "fsm-inferred-latch" in note


def test_b3_fsm_completeness_clean_passes():
    ok, _note = G.fsm_completeness_gate_record("x", _FSM_CLEAN)
    assert ok is True


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_b3_fsm_completeness_blocks(tmp_path):
    rid = "cvdp_copilot_fsm_0001"
    batch = [{"id": rid, "completion": _FSM_LATCH}]
    rc, emitted, report = _run_main(tmp_path, batch)
    assert rc == 1
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "fsm-inferred-latch" in entry.get("fsm_block", "")


# ════════════ B4 — handshake livelock / result stability (#523, zero-FP) ═════
_HS_CORRECT = (
    "module mcdiv(\n"
    "  input wire clk, input wire rst,\n"
    "  input wire [7:0] a, input wire [7:0] b,\n"
    "  input wire opn_valid, output reg res_valid,\n"
    "  input wire res_ready, output wire [15:0] result);\n"
    "  reg [15:0] SR; reg [3:0] cnt; reg start_cnt;\n"
    "  assign result = SR;\n"
    "  always @(posedge clk) begin\n"
    "    if (rst) begin SR<=0; cnt<=0; start_cnt<=1'b0; end\n"
    "    else if (~start_cnt & opn_valid & ~res_valid) begin\n"
    "      cnt <= 1; start_cnt <= 1'b1; SR <= {8'b0, a};\n"
    "    end else if (start_cnt) begin\n"
    "      if (cnt[3]) begin cnt <= 0; start_cnt <= 1'b0; SR <= SR + b; end\n"
    "      else begin cnt <= cnt + 1; SR <= {SR[14:0], 1'b0}; end\n"
    "    end\n  end\n"
    "  always @(posedge clk) res_valid <= rst ? 1'b0 : cnt[3] ? 1'b1 :\n"
    "                                   (res_valid & res_ready) ? 1'b0 : res_valid;\n"
    "endmodule\n")
_HS_LIVELOCK = _HS_CORRECT.replace("~start_cnt & opn_valid & ~res_valid",
                                   "opn_valid & ~res_valid")


def test_b4_handshake_block_on_livelock():
    ok, note = G.handshake_stability_gate_record("x", _HS_LIVELOCK)
    assert ok is False
    assert "handshake-load-livelock" in note


def test_b4_handshake_clean_passes():
    ok, _note = G.handshake_stability_gate_record("x", _HS_CORRECT)
    assert ok is True


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_b4_handshake_blocks(tmp_path):
    rid = "cvdp_copilot_mcdiv_0001"
    batch = [{"id": rid, "completion": _HS_LIVELOCK}]
    rc, emitted, report = _run_main(tmp_path, batch)
    assert rc == 1
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "handshake-load-livelock" in entry.get("handshake_block", "")


# ════════════ MULTI-FILE emit split — name-aware mapping (ORGANIC) ═══════════
# A MULTI-FILE problem (output.context lists >1 rtl/*.sv) whose completion is a
# single bare blob must map EACH module to the expected file whose basename
# matches it — never leave the NAMED top file empty. The prior positional
# fallback dumped a single `module ping_pong_buffer` into the alphabetically-
# first slot `rtl/dual_port_memory.sv`, leaving the real top `ping_pong_buffer.sv`
# EMPTY → scorer ELAB_ERROR on a correct design.
_PPB_TOP = (
    "module ping_pong_buffer(input clk, input rst, input wr, input [7:0] din,\n"
    "                        output reg [7:0] dout);\n"
    "  always @(posedge clk) if (wr) dout <= din;\nendmodule\n")
_DPM = (
    "module dual_port_memory(input clk, input we, input [3:0] addr,\n"
    "                        input [7:0] wdata, output reg [7:0] rdata);\n"
    "  reg [7:0] mem [0:15];\n"
    "  always @(posedge clk) begin if (we) mem[addr] <= wdata;\n"
    "    rdata <= mem[addr]; end\nendmodule\n")


def _emit_files(blob, expected):
    """Decode the `{"code":[{path:src},…]}` envelope into {path: src}."""
    out = json.loads(G._emit_or_split(blob, expected))
    return {k: v for d in out["code"] for k, v in d.items()}


def test_emit_multifile_two_modules_map_each_to_its_file():
    # the blob defines BOTH expected modules → each lands in its own file once.
    expected = ["rtl/dual_port_memory.sv", "rtl/ping_pong_buffer.sv"]  # sorted
    files = _emit_files(_PPB_TOP + "\n\n" + _DPM, expected)
    assert set(files) == set(expected)
    assert "module ping_pong_buffer" in files["rtl/ping_pong_buffer.sv"]
    assert "module dual_port_memory" in files["rtl/dual_port_memory.sv"]
    # no module duplicated across the set (the duplicate-declaration FAIL shape).
    assert files["rtl/ping_pong_buffer.sv"].count("module ping_pong_buffer") == 1
    assert files["rtl/dual_port_memory.sv"].count("module dual_port_memory") == 1
    assert "module dual_port_memory" not in files["rtl/ping_pong_buffer.sv"]
    assert "module ping_pong_buffer" not in files["rtl/dual_port_memory.sv"]


def test_emit_multifile_single_module_lands_in_named_not_first_slot():
    # THE BUG: a single `module ping_pong_buffer` for a 2-file problem must land
    # in ping_pong_buffer.sv (the SECOND sorted slot), NOT the first.
    expected = ["rtl/dual_port_memory.sv", "rtl/ping_pong_buffer.sv"]  # sorted
    files = _emit_files(_PPB_TOP, expected)
    assert "module ping_pong_buffer" in files["rtl/ping_pong_buffer.sv"]
    assert files["rtl/dual_port_memory.sv"] == ""        # empty placeholder
    # regression guard: the bug dumped the module into the first sorted slot.
    assert "module ping_pong_buffer" not in files["rtl/dual_port_memory.sv"]


def test_emit_multifile_preamble_and_helper_go_to_named_top():
    # leading preamble (`timescale) + an unmatched helper module must follow the
    # named top into ping_pong_buffer.sv, each exactly once; dpm stays empty.
    blob = ("`timescale 1ns/1ps\n\n" + _PPB_TOP +
            "\nmodule helper(input a, output y); assign y = a; endmodule\n")
    expected = ["rtl/dual_port_memory.sv", "rtl/ping_pong_buffer.sv"]
    files = _emit_files(blob, expected)
    top = files["rtl/ping_pong_buffer.sv"]
    assert "`timescale" in top
    assert top.count("module ping_pong_buffer") == 1
    assert top.count("module helper") == 1               # unmatched → named top
    assert files["rtl/dual_port_memory.sv"] == ""


def test_emit_multifile_no_name_match_positional_fallback():
    # no module name-matches any expected file → LOSSLESS positional fallback
    # (whole blob → first slot, rest empty) — the pre-name-aware behaviour.
    blob = "module zzz(input a, output y); assign y = a; endmodule\n"
    expected = ["rtl/aaa.sv", "rtl/bbb.sv"]
    files = _emit_files(blob, expected)
    assert "module zzz" in files["rtl/aaa.sv"]
    assert files["rtl/bbb.sv"] == ""


def test_emit_multifile_case_underscore_insensitive_match():
    # the module/file match is case- and underscore-insensitive.
    blob = "module PingPongBuffer(input a, output y); assign y=a; endmodule\n"
    expected = ["rtl/dual_port_memory.sv", "rtl/ping_pong_buffer.sv"]
    files = _emit_files(blob, expected)
    assert "module PingPongBuffer" in files["rtl/ping_pong_buffer.sv"]
    assert files["rtl/dual_port_memory.sv"] == ""


def test_emit_single_file_byte_identical_same_object():
    # the dominant 297/302 single-file shape: emit is the blob UNCHANGED (and the
    # very same object — proves byte-identity, no envelope wrapping).
    blob = _AND2
    assert G._emit_or_split(blob, None) is blob
    assert G._emit_or_split(blob, []) is blob
    assert G._emit_or_split(blob, ["rtl/and2.sv"]) is blob   # single expected rtl
    assert G._emit_or_split(blob, ["docs/notes.md"]) is blob  # 0 expected rtl


def test_emit_multifile_clean_partition_unchanged_path():
    # a clean full partition still routes through _split_blob_to_expected and is
    # byte-identical to its dict (the name-aware fallback is NOT reached).
    expected = ["rtl/dual_port_memory.sv", "rtl/ping_pong_buffer.sv"]
    blob = _PPB_TOP + "\n\n" + _DPM
    strict = G._split_blob_to_expected(blob, expected)
    files = _emit_files(blob, expected)
    assert files == strict


# ════════════ TB-bound PORT-NAME alignment (interface conformance) ═══════════
# The hidden cocotb TB binds ports BY NAME (`dut.w_out` / `dut.hours` /
# `dut.TIMEOUT_LIMIT`); a blind author with CORRECT LOGIC but a synonym port name
# (`w` / `hour` / `timeout_limit`) AttributeErrors the TB → the whole problem
# fails on an interface-NAME gap, not logic. Aligning the authored top's port
# IDENTIFIER to the TB name is interface conformance (same category as the
# module→TOPLEVEL rename / the #711 renamed-interface relaxation) — it reads only
# the TB's `dut.<name>` metadata, NEVER the golden RTL. CONSERVATIVE: only an
# UNAMBIGUOUS 1:1 synonym renames; everything else is a byte-identical no-op.
_TBALIGN_RTL = ("module adder(input clk, input [7:0] a, input [7:0] b,\n"
                "             output reg [7:0] w);\n"
                "  always @(posedge clk) w <= a + b;\nendmodule\n")


# ── PURE: decomposition + synonym algebra ────────────────────────────────────
def test_tbalign_decompose():
    assert G._decompose_port("w_out") == ("w", "out")
    assert G._decompose_port("i_data") == ("data", "in")
    assert G._decompose_port("data_i") == ("data", "in")
    assert G._decompose_port("o_ready") == ("ready", "out")
    assert G._decompose_port("hours") == ("hour", None)       # plural fold
    assert G._decompose_port("TIMEOUT_LIMIT") == ("timeout_limit", None)
    assert G._decompose_port("address") == ("address", None)  # `…ss` NOT folded


def test_tbalign_synonym_positive_and_negative():
    for a, b in (("w", "w_out"), ("b", "b_out"), ("data", "data_out"),
                 ("i_data", "data_i"), ("o_ready", "ready"),
                 ("hour", "hours"), ("minute", "minutes"),
                 ("timeout_limit", "TIMEOUT_LIMIT")):
        assert G._ports_synonym(a, b), (a, b)
    # a DIRECTION FLIP is never a synonym (two distinct real ports).
    assert not G._ports_synonym("data_in", "data_out")
    assert not G._ports_synonym("clk", "clock")          # unrelated cores
    assert not G._ports_synonym("w", "w")                # identical → no rename


def test_tbalign_renames_unambiguous():
    # (a) w/b authored, TB binds w_out/b_out → BOTH rename.
    assert G.tb_port_alignment_renames(
        ["clk", "a", "b", "w"], {"clk", "a", "b_out", "w_out"}) == {
            "b": "b_out", "w": "w_out"}


def test_tbalign_no_rename_genuine_missing_port():
    # (b) a genuinely-extra functional port with NO synonym is NEVER invented.
    assert G.tb_port_alignment_renames(
        ["clk", "a", "w_out"], {"clk", "a", "w_out", "enable"}) == {}


def test_tbalign_no_rename_when_ambiguous():
    # (c) two authored synonyms for ONE TB name → ambiguous → no rename.
    assert G.tb_port_alignment_renames(
        ["data", "data_o"], {"clk", "data_out"}) == {}


def test_tbalign_no_double_claim():
    # the TB binds BOTH `w` and `w_out`; `w` is consumed as-is → never reused.
    assert G.tb_port_alignment_renames(
        ["clk", "w"], {"clk", "w", "w_out"}) == {}


# ── PURE: scoped textual application ─────────────────────────────────────────
def test_tbalign_apply_scoped_to_top_block():
    out, ren = G.maybe_align_tb_ports(
        _TBALIGN_RTL, "adder", {"clk", "a", "b_out", "w_out"})
    assert ren == {"b": "b_out", "w": "w_out"}
    assert "output reg [7:0] w_out" in out
    assert "input [7:0] b_out" in out
    assert "w_out <= a + b_out" in out


def test_tbalign_sibling_submodule_untouched():
    # a same-named net in a SIBLING submodule is NEVER touched (scoped to the
    # harness-top block the scorer binds).
    rtl = ("module top(input clk, output w);\n  sub u(.clk(clk), .y(w));\n"
           "endmodule\n"
           "module sub(input clk, output w);\n  assign w = clk;\nendmodule\n")
    out, ren = G.maybe_align_tb_ports(rtl, "top", {"clk", "w_out"})
    assert ren == {"w": "w_out"}
    assert "module top(input clk, output w_out)" in out
    assert "module sub(input clk, output w)" in out      # sub's w untouched


def test_tbalign_comment_and_string_not_substituted():
    rtl = ("module m(input clk, output w);\n  // w is the result net\n"
           "  assign w = clk;\nendmodule\n")
    out, ren = G.maybe_align_tb_ports(rtl, "m", {"clk", "w_out"})
    assert ren == {"w": "w_out"}
    assert "// w is the result net" in out               # comment word untouched
    assert "output w_out" in out and "w_out = clk" in out


def test_tbalign_collision_guard_blocks_existing_target():
    # the target name already exists as a local net → renaming would duplicate
    # the declaration → fail-safe: no rename, byte-identical.
    rtl = ("module m(input clk, output w);\n  wire w_out;\n"
           "  assign w_out = clk;\n  assign w = w_out;\nendmodule\n")
    out, ren = G.maybe_align_tb_ports(rtl, "m", {"clk", "w_out"})
    assert ren == {} and out == rtl


def test_tbalign_noop_when_no_gap():
    out, ren = G.maybe_align_tb_ports(
        _TBALIGN_RTL, "adder", {"clk", "a", "b", "w"})
    assert ren == {} and out == _TBALIGN_RTL             # byte-identical


def test_tbalign_noop_when_no_harness_top_or_no_match():
    assert G.maybe_align_tb_ports(_TBALIGN_RTL, None, {"w_out"}) == (
        _TBALIGN_RTL, {})
    assert G.maybe_align_tb_ports(_TBALIGN_RTL, "nope", {"w_out"}) == (
        _TBALIGN_RTL, {})
    assert G.maybe_align_tb_ports(_TBALIGN_RTL, "adder", set()) == (
        _TBALIGN_RTL, {})


# ── PURE: the harness-TB port loader (dut.<name> cocotb scan) is DELETED ──────
def test_harness_tb_port_loader_is_deleted():
    """The `_load_harness_tb_ports` cocotb-`.py` reader has been DELETED — the
    gate now carries ZERO harness `.env` / cocotb readers, so there is nothing
    left to mis-wire. (The live no-leak behaviour is still proven end-to-end by
    test_main_does_not_align_ports_from_harness below, which feeds a harness via
    --dataset and asserts main() never aligns from it.)"""
    assert not hasattr(G, "_load_harness_tb_ports")


# ── END-TO-END through main() (EDA-gated) ────────────────────────────────────
_TBALIGN_PY = ("import cocotb\n"
               "async def run(dut):\n"
               "    dut._log.info('x')\n"
               "    dut.clk.value = 0\n"
               "    dut.a.value = 1\n"
               "    _ = int(dut.w_out.value)\n"
               "    _ = int(dut.b_out.value)\n")


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_does_not_align_ports_from_harness(tmp_path):
    # OFFICIAL-COMPLIANCE (negative no-leak): the cocotb TB's `dut.<name>` port
    # bindings live in harness.files (the test harness), which CVDP does NOT
    # provide to the model. So even when the dataset's TB binds dut.w_out/dut.b_out
    # and the completion declares synonyms w/b, the gate MUST NOT read the cocotb
    # harness and MUST NOT align — the authored names (from the prompt's
    # Inputs/Outputs) are emitted unchanged, and NO port_aligned is recorded.
    rid = "cvdp_copilot_adder_0001"
    batch = [{"id": rid, "completion": _TBALIGN_RTL}]
    dataset = [{"id": rid, "harness": {"files": {
        "src/.env": "TOPLEVEL=adder\n", "src/test_adder.py": _TBALIGN_PY}}}]
    rc, emitted, report = _run_main(tmp_path, batch, dataset=dataset)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "output reg [7:0] w);" in em["completion"]     # authored name kept
    assert "w_out" not in em["completion"]                # cocotb name NOT read
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "port_aligned" not in entry


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_tbalign_noop_no_synonym(tmp_path):
    # (b) the TB binds a genuinely-extra port (no synonym) → NO rename; the
    # completion is emitted unchanged and NOTHING is fabricated.
    rid = "cvdp_copilot_adder_0002"
    rtl = ("module adder(input clk, input [7:0] a, input [7:0] b,\n"
           "             output reg [7:0] w_out);\n"
           "  always @(posedge clk) w_out <= a + b;\nendmodule\n")
    py = ("import cocotb\nasync def r(dut):\n    _ = dut.clk\n    _ = dut.a\n"
          "    _ = dut.b\n    _ = int(dut.w_out.value)\n"
          "    _ = int(dut.enable.value)\n")
    batch = [{"id": rid, "completion": rtl}]
    dataset = [{"id": rid, "harness": {"files": {
        "src/.env": "TOPLEVEL=adder\n", "src/test_adder.py": py}}}]
    rc, emitted, report = _run_main(tmp_path, batch, dataset=dataset)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "enable" not in em["completion"]              # never fabricated
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "port_aligned" not in entry


@pytest.mark.skipif(not _HAVE_EDA, reason="needs iverilog + yosys")
def test_main_tbalign_noop_ambiguous(tmp_path):
    # (c) two authored synonyms for one TB name → no rename; emitted unchanged.
    rid = "cvdp_copilot_dbus_0001"
    rtl = ("module dbus(input clk, output data, output data_o);\n"
           "  assign data = clk;\n  assign data_o = ~clk;\nendmodule\n")
    py = ("import cocotb\nasync def r(dut):\n    _ = dut.clk\n"
          "    _ = int(dut.data_out.value)\n")
    batch = [{"id": rid, "completion": rtl}]
    dataset = [{"id": rid, "harness": {"files": {
        "src/.env": "TOPLEVEL=dbus\n", "src/test_dbus.py": py}}}]
    rc, emitted, report = _run_main(tmp_path, batch, dataset=dataset)
    assert rc == 0
    em = next(r for r in emitted if r.get("id") == rid)
    assert "data_out" not in em["completion"]            # no fabricated rename
    entry = next(e for e in report["records"] if e["id"] == rid)
    assert "port_aligned" not in entry
