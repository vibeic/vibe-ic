#!/usr/bin/env python3
"""FULLSTACKTB (2026-09-29) — Step 5's full-stack population must be FUNCTIONAL.

MEASURED on both DIE benchmark runs (spm, subservient): the full-stack
testbench the flow generates was the connectivity skeleton (no stimulus, zero
golden compares), and `bit_level_full_stack_tb_check` answered every IC without
a command protocol with VACUOUS_PASS (`DESIGN_DECLARED_NA`), so Step 5 carried
it as a partially-vacuous PASS clause. The functional oracle that did exist
drove the bare core, never the pad-ring chip top the die is.

Pinned here, each with its known-negative:
  * the gate REFUSES a connectivity-only population (NOT_MEASURED + INCOMPLETE,
    never a pass) and refuses a DIE whose chip top is not built;
  * a population is credited only through the REQUIRED top (the pad-ring chip
    top on a DIE route), with testbench, transcript, sources and design input
    re-verified by the gate — a record cannot vouch for itself;
  * the producer drives the design's own L10 cases, each with the oracle its
    input states, through the chip top, honours the population, the corners and
    the reset-mid-computation scenario the case's own text states, and never
    counts a coverage FIGURE as a functional case.

The simulator is a stand-in here (the host carries none); the real simulation
of both benchmark ICs through their pad-ring tops is the replay in the lane
report. chip-AGNOSTIC: every fixture is a synthetic design.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import bit_level_full_stack_tb_check as gate  # noqa: E402
import arith_oracle_tb_gen as aog  # noqa: E402


def _fsf():
    return importlib.import_module("full_stack_functional_tb")


# ---------------------------------------------------------------------------
# a synthetic serial-parallel arithmetic core (8-bit), optionally on a DIE
# ---------------------------------------------------------------------------
CORE = "dut_core"
CORE_V = f"""module {CORE} (input clk, input rst, input [7:0] x, input y,
                  output p);
  reg [15:0] acc; assign p = acc[0];
  always @(posedge clk) if (rst) acc <= 0; else acc <= acc + (y ? x : 0);
endmodule
"""
CHIP_TOP_V = f"""// generated pad-ring top (synthetic)
module chip_top (
    input clk,
    input rst,
    input [7:0] x,
    input y,
    output p,
    inout VDD,
    inout VSS
);
    wire clk__core, rst__core, y__core, p__core, t0;
    wire [7:0] x__core;
    TIELO u_tie0 (.ZN(t0));
    PADIN u_pad_clk (.PAD(clk), .Y(clk__core));
    PADIN u_pad_rst (.PAD(rst), .Y(rst__core));
    PADIN u_pad_y (.PAD(y), .Y(y__core));
    PADIN u_pad_x_0 (.PAD(x[0]), .Y(x__core[0]));
    PADOUT u_pad_p (.A(p__core), .PAD(p));
    {CORE} u_core (.clk(clk__core), .rst(rst__core), .x(x__core),
                   .y(y__core), .p(p__core));
endmodule
"""
MODELS = {
    "/pdk/libs.ref/io/verilog/io.v":
        "module PADIN(input PAD, output Y); assign Y = PAD; endmodule\n"
        "module PADOUT(input A, output PAD); assign PAD = A; endmodule\n",
    "/pdk/libs.ref/sc/verilog/sc.v":
        "module TIELO(output ZN); assign ZN = 1'b0; endmodule\n",
}

CASES = [
    {"name": "random_equivalence", "kind": "coverage_goal",
     "stimulus": "隨機 ≥ 100 組 (x, y),全部對 golden model 一致",
     "expected": "100% PASS (binary)"},
    {"name": "corner_operand", "kind": "coverage_goal",
     "stimulus": "x = 0、y_stream = 0、x = MAX_POS、x = MIN_NEG、y = MAX_POS、"
                 "y = MIN_NEG、x = -1、y = -1",
     "expected": "100% PASS"},
    {"name": "reset", "kind": "coverage_goal",
     "stimulus": "reset 期間 / reset 解除瞬間 / reset 在計算進行中 assert 三種情況",
     "expected": "100% PASS"},
    {"name": "toggle_branch_coverage", "kind": "functional_vector",
     "stimulus": "同 random run;非 sign-off gate", "expected": "≥ 95%"},
]


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _mk_project(tmp_path: Path, *, die: bool, chip_top: bool = True,
                cases=None) -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    _write(gd / "L3_CMD_PROTOCOL.json", json.dumps(
        {"opcodes": [], "no_opcodes_in_input": True}))
    _write(gd / "L4_REGMAP.json", json.dumps({"registers": []}))
    _write(gd / "L2_FRS.json", json.dumps(
        {"function": "p = x * y mod 2^N (serial-parallel multiplier)"}))
    _write(gd / "L9_INTEGRATION_SPEC.json", json.dumps({
        "top_module": CORE,
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "x", "direction": "input", "width": 8},
            {"name": "y", "direction": "input", "width": 1},
            {"name": "p", "direction": "output", "width": 1}]}))
    _write(gd / "L10_TEST_CASES.json", json.dumps(
        {"test_cases": CASES if cases is None else cases}, ensure_ascii=False))
    _write(proj / "phase2" / "stage1" / "rtl" / f"{CORE}.v", CORE_V)
    sfs = proj / "phase2" / "stage1" / "sim_full_stack"
    # the connectivity skeleton + its results, exactly the refused shape
    _write(sfs / f"tb_{CORE}_full.v",
           f"module tb_{CORE}_full; {CORE} u_dut(); endmodule\n")
    _write(sfs / "results.json", json.dumps(
        {"pass": False, "functional_verified": False,
         "functional_coverage": {"scored_with_golden": 0},
         "command_oracle_applicable": False, "per_vector": []}))
    if die:
        _write(proj / "input" / "submission_template" / "SELF_TAPEOUT.txt",
               "self tape-out\n")
        if chip_top:
            _write(proj / "phase3" / "stage3" / "pnr" / "chip_top_io.v",
                   CHIP_TOP_V)
            _write(proj / "reports" / "phase3" / "io_pad_chip_top.json",
                   json.dumps({"verdict": "WROTE",
                               "chip_top_module": "chip_top",
                               "core_module": CORE,
                               "chip_top_verilog":
                                   "phase3/stage3/pnr/chip_top_io.v"}))
    return proj


def _resolver(project, used, container):
    return dict(MODELS), "fixture models"


class _FakeSim:
    """A simulator stand-in: builds succeed; a run reports what the TB's own
    population is, scored as `outcome(case, nv)` says. It reads the testbench
    it is asked to run, so a TB that is not there cannot be 'run'."""

    def __init__(self, outcome=None):
        self.calls = []
        self.tb_for = {}
        self.outcome = outcome or (lambda case, nv: (nv, nv))

    def __call__(self, argv, run_dir, container, tool, timeout):
        self.calls.append(list(argv))
        if argv[0] == "iverilog":
            self.tb_for[str(run_dir)] = argv[-1]
            return 0, ""
        tb = Path(self.tb_for[str(run_dir)])
        text = tb.read_text()
        case = tb.stem
        m = re.search(r"localparam integer NV = (\d+);", text)
        if m:
            nv = int(m.group(1))
            a, b = self.outcome(case, nv)
            return 0, f"ORACLE_TB_DONE pass={a}/{b}\n"
        a, b = self.outcome(case, 1)
        word = "PASS" if a == b else "FAIL"
        return (0 if word == "PASS" else 1), f"[TB {case}] {word} — ok\n"


@pytest.fixture
def arith_class(monkeypatch):
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class",
                        lambda project: "digital_arithmetic_primitive")


def _run_gate(proj: Path, tmp_path: Path, capsys=None):
    out = tmp_path / "gate.json"
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(proj), "--json",
                str(out)]
    try:
        rc = gate.main()
    finally:
        sys.argv = old
    stdout = capsys.readouterr().out if capsys is not None else ""
    return rc, json.loads(out.read_text()), stdout


# ===========================================================================
# THE GATE — a connectivity-only population is refused
# ===========================================================================
def test_connectivity_only_population_is_refused_not_vacuous(tmp_path, capsys):
    """KNOWN-POSITIVE of the refusal: skeleton + 0 golden vectors, no record."""
    proj = _mk_project(tmp_path, die=False)
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 2, res
    assert res["verdict"] == "NOT_MEASURED", res
    assert res["reason_class"] == "ZERO_DENOMINATOR"
    assert res["pass"] is False and res["vacuous_pass"] is False
    assert res["rule"] == "functional_full_stack_population_absent"
    # the sentinel that makes flow_compliance raise INCOMPLETE, last, column 0
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


def test_die_route_without_chip_top_is_blocked(tmp_path, capsys):
    """A DIE whose pad-ring chip top is not built yet measures nothing."""
    proj = _mk_project(tmp_path, die=True, chip_top=False)
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 2
    assert res["verdict"] == "NOT_MEASURED"
    assert res["reason_class"] == "BLOCKED_BY_UPSTREAM"
    assert res["required_top"]["pad_ring"] is True
    assert "INCOMPLETE:" in out


# ===========================================================================
# THE PRODUCER — functional cases through the pad-ring chip top
# ===========================================================================
def test_producer_drives_every_case_through_the_pad_ring_top(tmp_path,
                                                            arith_class):
    proj = _mk_project(tmp_path, die=True)
    sim = _FakeSim()
    rec = _fsf().generate(proj, "ctr", dispatch=sim,
                          model_resolver=_resolver)
    assert rec["verdict"] == "PASS", rec["reason"]
    by = {c["name"]: c for c in rec["cases"]}
    assert rec["counts"]["executed"] == 3 and rec["counts"]["passed"] == 3
    assert by["toggle_branch_coverage"]["state"] == "excluded"
    assert not (proj / "phase2/stage1/sim_full_stack/functional"
                / "toggle_branch_coverage.v").exists()
    for name in ("random_equivalence", "corner_operand", "reset"):
        c = by[name]
        assert c["state"] == "passed", c
        text = (proj / c["tb"]).read_text()
        assert _fsf().instance_count(text, "chip_top") == 1
        assert _fsf().instance_count(text, CORE) == 0
        assert c["family"] == "declared_function_golden"
    # compiled with the staged PDK models, the chip top and the core RTL
    build = next(a for a in sim.calls if a[0] == "iverilog")
    joined = " ".join(build)
    assert "phase3/stage3/pnr/chip_top_io.v" in joined
    assert f"rtl/{CORE}.v" in joined
    assert sum("/functional/models/" in a for a in build) == 2


def test_the_case_text_decides_population_corners_and_reset_scenario(
        tmp_path, arith_class):
    proj = _mk_project(tmp_path, die=True)
    rec = _fsf().generate(proj, "ctr", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    by = {c["name"]: c for c in rec["cases"]}
    rnd = (proj / by["random_equivalence"]["tb"]).read_text()
    nv = int(re.search(r"localparam integer NV = (\d+);", rnd).group(1))
    assert nv >= 100 and by["random_equivalence"]["declared_population"] == 100
    assert "framing calibrated on the first 28" in rnd
    corner = (proj / by["corner_operand"]["tb"]).read_text()
    # MIN_NEG for an 8-bit operand is the pattern 128, crossed with itself
    assert "_av[0] = 8'd0; _bv[0] = 8'd0;" in corner
    assert re.search(r"= 8'd128; _bv\[\d+\] = 8'd128;", corner)
    reset = (proj / by["reset"]["tb"]).read_text()
    assert "for (_k = 0; _k < N/2; _k = _k + 1)" in reset
    assert "for (_k = 0; _k < N/2" not in corner


def test_a_case_short_of_its_stated_population_is_not_a_pass(tmp_path,
                                                            arith_class):
    proj = _mk_project(tmp_path, die=True)
    # the simulator reports FEWER vectors than the case states
    sim = _FakeSim(lambda case, nv: (min(nv, 50), min(nv, 50))
                   if case == "random_equivalence" else (nv, nv))
    rec = _fsf().generate(proj, "ctr", dispatch=sim, model_resolver=_resolver)
    by = {c["name"]: c for c in rec["cases"]}
    assert by["random_equivalence"]["state"] == "short_population"
    assert rec["verdict"] == "NOT_MEASURED"


def test_producer_refuses_a_chip_top_it_has_no_models_for(tmp_path,
                                                         arith_class):
    proj = _mk_project(tmp_path, die=True)
    rec = _fsf().generate(
        proj, "ctr", dispatch=_FakeSim(),
        model_resolver=lambda p, u, c: ({"/pdk/io.v": MODELS[
            "/pdk/libs.ref/io/verilog/io.v"]}, "io only"))
    assert rec["verdict"] == "NOT_MEASURED"
    assert rec["reason_class"] == "EXECUTION_ERROR"
    assert "TIELO" in rec["reason"]
    assert not list((proj / "phase2/stage1/sim_full_stack/functional")
                    .glob("*.v"))


def test_producer_before_the_chip_top_exists_runs_nothing(tmp_path,
                                                         arith_class):
    proj = _mk_project(tmp_path, die=True, chip_top=False)
    sim = _FakeSim()
    rec = _fsf().generate(proj, "ctr", dispatch=sim, model_resolver=_resolver)
    assert rec["verdict"] == "NOT_MEASURED"
    assert rec["reason_class"] == "BLOCKED_BY_UPSTREAM"
    assert sim.calls == []


def test_off_the_pad_ring_route_the_core_is_the_full_stack_top(tmp_path,
                                                              arith_class):
    proj = _mk_project(tmp_path, die=False)
    rec = _fsf().generate(proj, None, dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["full_stack_top"]["pad_ring"] is False
    assert rec["full_stack_top"]["module"] == CORE
    assert rec["verdict"] == "PASS"
    assert rec["models"] == []


# ===========================================================================
# THE GATE — crediting a population, and refusing one that cannot vouch
# ===========================================================================
def _passing_die(tmp_path, arith_class=None):
    proj = _mk_project(tmp_path, die=True)
    rec = _fsf().generate(proj, "ctr", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["verdict"] == "PASS"
    return proj, rec


def test_gate_credits_a_population_measured_through_the_chip_top(
        tmp_path, arith_class, capsys):
    proj, _rec = _passing_die(tmp_path)
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 0, res
    assert res["verdict"] == "PASS" and res["functional_verified"] is True
    assert res["vacuous_pass"] is False
    assert res["counts"] == {"executed": 3, "passed": 3, "failed": 0,
                             "short": 0}
    assert res["required_top"]["module"] == "chip_top"
    assert "INCOMPLETE" not in out


def test_gate_fails_a_case_whose_oracle_disagreed(tmp_path, arith_class,
                                                  capsys):
    proj = _mk_project(tmp_path, die=True)
    sim = _FakeSim(lambda case, nv: (nv - 1, nv) if case == "corner_operand"
                   else (nv, nv))
    rec = _fsf().generate(proj, "ctr", dispatch=sim, model_resolver=_resolver)
    assert rec["verdict"] == "FAIL"
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 1 and res["verdict"] == "FAIL"
    assert res["counts"]["failed"] == 1


def test_gate_refuses_a_transcript_that_is_not_the_recorded_one(
        tmp_path, arith_class, capsys):
    proj, rec = _passing_die(tmp_path)
    log = proj / next(c for c in rec["cases"]
                      if c["name"] == "reset")["run_log"]
    log.write_text(log.read_text() + "\n")
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED"
    assert res["rule"] == "functional_record_inconsistent"


def test_gate_rescores_the_transcript_rather_than_trusting_the_record(
        tmp_path, arith_class, capsys):
    """A record that says `passed` over a transcript with no verdict marker."""
    proj, rec = _passing_die(tmp_path)
    fsf = _fsf()
    c = next(c for c in rec["cases"] if c["name"] == "corner_operand")
    log = proj / c["run_log"]
    log.write_text("simulation finished\n")
    c["run_log_sha256"] = fsf.sha256_file(log)      # the record is re-sealed
    fsf.record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent"
    assert "scores errored" in res["rationale"]


def test_gate_refuses_a_testbench_that_bypasses_the_pad_ring(
        tmp_path, arith_class, capsys):
    proj, rec = _passing_die(tmp_path)
    fsf = _fsf()
    c = next(c for c in rec["cases"] if c["name"] == "reset")
    tb = proj / c["tb"]
    tb.write_text(tb.read_text().replace("chip_top dut", f"{CORE} dut"))
    c["tb_sha256"] = fsf.sha256_file(tb)            # the record is re-sealed
    fsf.record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent"
    assert "does not instantiate the required top" in res["rationale"]


def test_gate_refuses_a_record_measured_through_the_core_on_a_die(
        tmp_path, arith_class, capsys):
    proj = _mk_project(tmp_path, die=True)
    # a population measured OFF the pad-ring route, then the die is declared
    rec = _fsf().generate(proj, None, route="HARDMACRO", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["verdict"] == "PASS"
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_wrong_top"


def test_gate_refuses_a_record_of_bytes_that_have_changed(
        tmp_path, arith_class, capsys):
    proj, _rec = _passing_die(tmp_path)
    rtl = proj / "phase2" / "stage1" / "rtl" / f"{CORE}.v"
    rtl.write_text(rtl.read_text() + "// edited\n")
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_stale"


def test_gate_refuses_a_population_that_executed_nothing(tmp_path, capsys,
                                                         monkeypatch):
    """No oracle family grounds any case -> the record is empty -> refused."""
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class", lambda project: None)
    proj = _mk_project(tmp_path, die=True, cases=[
        {"name": "blinky", "kind": "functional_vector",
         "stimulus": "blinky.hex", "expected": "GPIO toggles"}])
    rec = _fsf().generate(proj, "ctr", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["counts"]["executed"] == 0
    assert rec["cases"][0]["state"] == "no_oracle"
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED"
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


# ===========================================================================
# TRANSCRIPT SCORING — each side of every pair
# ===========================================================================
@pytest.mark.parametrize("rc,text,state", [
    (0, "ORACLE_TB_DONE pass=28/28\n", "passed"),
    (0, "ORACLE_TB_DONE pass=27/28\nORACLE_MISMATCH: no single\n", "failed"),
    (0, "ORACLE_TB_DONE pass=0/0\n", "errored"),
    (0, "[TB c1] PASS — holds\n", "passed"),
    (1, "[TB c1] FAIL: x asserted\n", "failed"),
    (0, "[TB other] PASS — holds\n", "errored"),
    (0, "simulation finished\n", "errored"),
    (1, "", "errored"),
])
def test_score_transcript_pairs(rc, text, state):
    assert _fsf().score_transcript("c1", rc, text)["state"] == state


def test_coverage_figure_is_not_a_functional_acceptance():
    fsf = _fsf()
    assert fsf.acceptance_is_coverage_figure({"expected": "≥ 95%"})
    assert not fsf.acceptance_is_coverage_figure(
        {"expected": "100% PASS (binary)"})
    assert not fsf.acceptance_is_coverage_figure({"expected": "PASS"})


# ===========================================================================
# THE CASE-TEXT READERS (arith_oracle_tb_gen)
# ===========================================================================
def test_declared_population_reads_the_stimulus_not_the_acceptance():
    assert aog.declared_vector_population(
        {"stimulus": "隨機 ≥ 10000 組 (x, y)", "expected": "100% PASS"}) == 10000
    assert aog.declared_vector_population(
        {"stimulus": "at least 2,048 random pairs"}) == 2048
    assert aog.declared_vector_population(
        {"stimulus": "同 random run", "expected": "≥ 95%"}) is None
    assert aog.declared_vector_population({"stimulus": "≥ 95% toggle"}) is None


def test_named_corners_are_width_bit_patterns():
    case = {"stimulus": "x = 0、x = MAX_POS、x = MIN_NEG、y = -1"}
    assert aog.named_corner_values(case, 8) == [0, 127, 128, 255]
    assert aog.named_corner_values({"stimulus": "random pairs"}, 8) == []


def test_reset_mid_computation_grammar():
    assert aog.reset_mid_computation_case(
        {"stimulus": "reset 在計算進行中 assert"})
    assert aog.reset_mid_computation_case(
        {"stimulus": "assert reset during a computation"})
    assert not aog.reset_mid_computation_case(
        {"stimulus": "reset 解除後 10 cycle 內取得第一條 instruction"})


def test_the_historical_sample_is_unchanged_without_case_text():
    spec = {"width": 8, "operator": "*", "signed": False}
    base = aog.select_operand_pairs(spec, "mixed")
    assert len(base) == 28
    assert aog.select_operand_pairs(spec, "mixed", min_vectors=None,
                                    extra_corners=()) == base
    grown = aog.select_operand_pairs(spec, "random", min_vectors=500)
    assert len(grown) == 500 and len(set(grown)) == 500
    named = aog.select_operand_pairs(spec, "corners", extra_corners=[0, 128])
    assert named[:4] == [(0, 0), (0, 128), (128, 0), (128, 128)]


def test_small_populations_keep_the_full_framing_search():
    spec = {"top": "t", "operator": "*", "width": 8, "signed": False,
            "parallel": "x", "serial_in": "y", "serial_out": "p",
            "clk": "clk", "rst": "rst", "reset_active_low": False,
            "parallel_is_lhs": True, "other_inputs": [],
            "ports": [{"name": n, "dir": d} for n, d in
                      (("clk", "input"), ("rst", "input"), ("x", "input"),
                       ("y", "input"), ("p", "output"))]}
    small = aog.emit_serial_oracle_module("m", spec, [(1, 2)] * 28)
    large = aog.emit_serial_oracle_module(
        "m", spec, [(i, i + 1) for i in range(40)])
    assert "calibrated" not in small
    assert "for (_vi = 0; _vi < NV; _vi = _vi + 1) begin" in small
    assert "framing calibrated on the first 28" in large
    with pytest.raises(ValueError):
        aog.emit_serial_oracle_module("m", dict(spec, rst=None), [(1, 2)],
                                      abort_before_each=True)


# ===========================================================================
# THE WIRING — Phase 2 step and the phase-3 re-run after the pad ring
# ===========================================================================
def test_phase2_step_publishes_the_records_word(monkeypatch, tmp_path):
    import design_one_shot_runner as dsor
    fsf = _fsf()
    for verdict, cls, want, want_cls in (
            ("PASS", None, "PASS", ""),
            ("FAIL", None, "FAIL", ""),
            ("NOT_MEASURED", "ZERO_DENOMINATOR", "NOT_MEASURED",
             "no_population"),
            ("NOT_MEASURED", "BLOCKED_BY_UPSTREAM", "NOT_MEASURED",
             "input_absent")):
        monkeypatch.setattr(fsf, "generate", lambda p, c, _v=verdict, _c=cls: {
            "verdict": _v, "reason_class": _c, "reason": "r",
            "counts": {"executed": 1}, "full_stack_top": {"module": "t"}})
        res = dsor.step_full_stack_functional_tb(tmp_path, "ctr")
        assert res.name == "full_stack_functional_tb"
        assert res.status == want and res.reason_class == want_cls


def test_phase3_reruns_the_producer_only_after_the_pad_ring_is_written(
        monkeypatch, tmp_path):
    import phase3_one_shot_runner as p3
    fsf = _fsf()
    seen = []
    monkeypatch.setattr(fsf, "generate", lambda p, c: seen.append(p) or {
        "verdict": "PASS", "counts": {"executed": 2}, "reason": "ok"})
    monkeypatch.setattr(p3, "_chip_path_requests_pad_ring", lambda p: True)
    monkeypatch.setattr(p3, "step_io_pad_chip_top_gen",
                        lambda p, c, pdk, **kw: p3.StepResult(
                            "io_pad_chip_top_gen", "PASS", 0.0, "rc=0"))
    res = p3._padring_producer_dispatch(tmp_path, "ctr", None)
    assert res.status == "PASS" and seen == [tmp_path]
    assert res.extras["full_stack_functional"]["verdict"] == "PASS"
    seen.clear()
    monkeypatch.setattr(p3, "step_io_pad_chip_top_gen",
                        lambda p, c, pdk, **kw: p3.StepResult(
                            "io_pad_chip_top_gen", "FAIL", 0.0, "rc=1"))
    res = p3._padring_producer_dispatch(tmp_path, "ctr", None)
    assert res.status == "FAIL" and seen == []


# The ordinary front door must reach the producer that owns the missing top.
# All prerequisites here are neutral source-fixture checks; the simulator
# boundary is the existing stand-in, so these do not claim native IC sign-off.
def _phase2_pad_fixture(tmp_path, monkeypatch):
    import time
    from dataclasses import asdict
    import design_one_shot_runner as design
    import execution_policy as execution
    import flow_compliance_check as compliance
    import _flow_yaml
    import step_output_collector as versions
    import vibe_ic_one_shot_runner as outer

    monkeypatch.setattr(execution, 'request', lambda: {'mode': 'default'})
    project = _mk_project(tmp_path, die=True, chip_top=False)
    started = time.time()
    producer = design.step_full_stack_functional_tb(project, None)
    assert producer.status == 'NOT_MEASURED'
    assert json.loads(_fsf().record_path(project).read_text())['reason_class'] == 'BLOCKED_BY_UPSTREAM'
    _write(project / 'neutral_prerequisite.json', '{"measured": true}')
    # D1's existing conditional review consumer also reads the inline neutral
    # L-docs. Bind this test-only review to exactly those authored fixture bytes.
    import ai_signed_judgement as judgement
    _write(project / 'reports/audit/ai_judgements/D1.json', json.dumps({
        'schema': judgement.SCHEMA, 'step_id': 'D1', 'verdict': 'PASS',
        'signed_by': 'ic-expert-agent', 'judgement': 'reviewed neutral unit fixture L-docs',
        'evidence_sha256': judgement.evidence_sha256(project, 'D1')}))
    compliance._GATE_LEDGER.clear()
    rows = []
    declared = [r for r in _flow_yaml.load()['steps']
                if (isinstance(r['id'], int) and 1 <= r['id'] <= 6)
                or (not isinstance(r['id'], int) and (
                    str(r.get('phase_scope') or '').strip().lower() == 'agnostic'
                    or compliance._STAGE_PHASE.get(
                        str(r.get('stage') or '').strip()) in (None, '2')))]
    for declaration in declared:
        sid = declaration['id']
        clause = {'json_field_true': {'file': 'neutral_prerequisite.json', 'field': 'measured'}}
        if sid == 5:
            clause = {'program_exit_zero':
                      'bit_level_full_stack_tb_check . --json '
                      'reports/phase2/gates/bit_level_full_stack.json'}
        row = compliance.check_step(project, {'id': sid, 'name': 'neutral_prerequisite',
                      'stage': 'stage1', 'required_outputs': ['neutral_prerequisite.json'],
                      'gate': clause}, {})
        rows.append(asdict(row))
    assert all(r['status'] == ('NOT_MEASURED' if str(r['id']) == '5' else 'PASS')
               for r in rows), [(r['id'], r['status'], r.get('failed_gates'),
                                 r.get('conditional_note')) for r in rows]
    functional = next(r for r in rows if str(r['id']) == '5')
    attempt = versions.begin_step(project, '5')
    versions.finish_step(project, attempt, verdict=functional['status'],
                         result={'canonical_consumer': {'step': functional}})
    audit = {'program': 'flow_compliance_check', 'project': str(project),
             'scope': {'phase': '2', 'stage': None, 'stage_id': None,
                       'steps_judged': [str(r['id']) for r in rows], 'step_count': len(rows)},
             'overall': 'NOT_MEASURED', 'steps': rows,
             'gate_execution_ledger': list(compliance._GATE_LEDGER)}
    _write(project / 'reports/phase2/gates/phase2_compliance.json', json.dumps(audit))
    report = {'project': str(project), 'verdict': 'NOT_MEASURED', 'steps': [
        asdict(design.StepResult('neutral_measurable', 'PASS')),
        asdict(producer), asdict(design.StepResult('final_audit', 'NOT_MEASURED',
                                                  reason_class='partial_population'))]}
    _write(outer._phase_report_path(project, 'phase2_one_shot.json'), json.dumps(report))
    return project, report, started


def _actual_outer_phase3_entry(project, report, started):
    """Execute the real Phase-2 halt statements and Phase-3 entry expression.

    Reading the actual caller also lets the exact base answer with its old
    cycle's VALUE (False), rather than failing on a missing new helper symbol.
    """
    import ast
    from types import SimpleNamespace
    import execution_policy as execution
    import vibe_ic_one_shot_runner as outer
    tree = ast.parse(Path(outer.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_main')
    body = next(n for n in ast.walk(main) if isinstance(n, ast.If) and any(
        isinstance(x, ast.Assign) and ast.unparse(x) == "halted_at = 'phase2'"
        for x in n.body) and 'NOT_MEASURED' in ast.unparse(n.test))
    # Its sibling immediately preceding this halt owns the named deferral.
    siblings = next(value for n in ast.walk(main) for value in vars(n).values()
                    if isinstance(value, list) and body in value)
    pos = siblings.index(body)
    nodes = [body]
    if pos and '_phase2_pad_top_deferral(' in ast.unparse(siblings[pos - 1]):
        nodes.insert(0, siblings[pos - 1])
    verdict, _ = outer._row_verdict(project, 'phase2_one_shot.json', 1, started, 'phase2')
    env = dict(vars(outer), project=project, rep=report, verdict=verdict, rc=1,
               _execution=execution,
               args=SimpleNamespace(skip_phase3=False), _p3_skip_by_exit=False,
               _phase_started={'phase2': started}, _phase2_pad_top_deferred=None,
               halted_at='')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), outer.__file__, 'exec'), env)
    entry = next(n for n in main.body if isinstance(n, ast.If)
                 and n.body and "_phase_runner('phase3')" in ast.unparse(n.body[0]))
    entered = eval(compile(ast.Expression(entry.test), outer.__file__, 'eval'), env)
    return entered, env


def _actual_late_rollup(env, phase3_started):
    import ast
    import vibe_ic_one_shot_runner as outer
    env.update(_phase3_ran=True, _phase_started={'phase3': phase3_started},
               plan=[('phase2', 'NOT_MEASURED', 1), ('phase3', 'PASS', 0)])
    main = next(n for n in ast.parse(Path(outer.__file__).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_main')
    node = next((n for n in main.body if isinstance(n, ast.If)
                 and '_resolve_phase2_pad_top(' in ast.unparse(n)), None)
    if node:
        exec(compile(ast.Module(body=[node], type_ignores=[]), outer.__file__, 'exec'), env)
    return env['plan'][0][1:]


def _late_pad_producer(project, monkeypatch, *, outcome='pass'):
    import phase3_one_shot_runner as phase3
    fsf = _fsf()
    monkeypatch.setattr(fsf, 'default_dispatch', _FakeSim(
        (lambda case, nv: (nv - 1, nv)) if outcome == 'sim_fail' else None))
    monkeypatch.setattr(fsf, 'default_model_resolver', _resolver)

    def write_pad(p, *_args, **_kwargs):
        if outcome not in ('missing_pad', 'pad_fail'):
            _write(p / 'phase3/stage3/pnr/chip_top_io.v', CHIP_TOP_V)
            _write(p / 'reports/phase3/io_pad_chip_top.json', json.dumps({
                'verdict': 'WROTE', 'chip_top_module': 'chip_top', 'core_module': CORE,
                'chip_top_verilog': 'phase3/stage3/pnr/chip_top_io.v'}))
            if outcome == 'old_pad':
                import os
                import time
                for target in ('phase3/stage3/pnr/chip_top_io.v',
                               'reports/phase3/io_pad_chip_top.json'):
                    os.utime(p / target, (time.time() - 30, time.time() - 30))
        return phase3.StepResult('io_pad_chip_top_gen',
                                 'FAIL' if outcome == 'pad_fail' else 'PASS')

    monkeypatch.setattr(phase3, 'step_io_pad_chip_top_gen', write_pad)
    if outcome == 'generator_error':
        def unavailable(*_a, **_kw):
            raise OSError('neutral generator unavailable')
        monkeypatch.setattr(fsf, 'generate', unavailable)
    return phase3._padring_producer_dispatch(project, None, None)


def test_default_outer_reaches_phase3_for_only_its_pad_top_obligation(tmp_path, monkeypatch):
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    assert entered is True
    owed = env['_phase2_pad_top_deferred']
    assert (owed['status'], owed['state'], owed['owner']) == (
        'NOT_MEASURED', 'DEFERRED', 'phase3.io_pad_chip_top_gen')
    assert owed['phase2_process'] == {'verdict': 'NOT_MEASURED', 'rc': 1}
    assert report['verdict'] == 'NOT_MEASURED'


def test_default_late_pad_population_resolves_with_actual_terminal_consumer(
        tmp_path, monkeypatch, arith_class):
    import time
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    phase3_started = time.time()
    if entered:
        res = _late_pad_producer(project, monkeypatch)
        assert res.extras.get('full_stack_functional_terminal', {}).get('verdict') == 'PASS'
    assert _actual_late_rollup(env, phase3_started) == ('PASS', 0)
    rec = json.loads(_fsf().record_path(project).read_text())
    assert rec['counts']['executed'] > 0
    assert gate.functional_full_stack_verdict(project)[0] == 0
    # The original child report and its failed early measurement remain history.
    assert json.loads((project / 'reports/orchestrator/phase2_one_shot.json').read_text())['verdict'] == 'NOT_MEASURED'


@pytest.mark.parametrize('mutation', ['phase2_fail', 'extra_incomplete', 'extra_gate_fail',
                                     'wrong_gate', 'wrong_rc', 'empty_ledger',
                                     'missing_audit_row', 'scoped_audit', 'stale_gate'])
def test_default_phase2_other_obligations_still_block(tmp_path, monkeypatch, mutation):
    import os
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    audit_path = project / 'reports/phase2/gates/phase2_compliance.json'
    audit = json.loads(audit_path.read_text())
    if mutation == 'phase2_fail':
        report['steps'][0]['status'] = 'FAIL'
        report['verdict'] = 'FAIL'
    elif mutation == 'extra_incomplete':
        audit['steps'][0].update(status='NOT_MEASURED', reason_class='partial_population')
    elif mutation == 'extra_gate_fail':
        audit['gate_execution_ledger'].append({'gate': 'neutral_measurable', 'verdict': 'FAIL', 'rc': 1})
    elif mutation == 'wrong_gate':
        audit['gate_execution_ledger'][0]['gate'] = 'unrelated_checker'
    elif mutation == 'wrong_rc':
        audit['gate_execution_ledger'][0]['rc'] = 1
    elif mutation == 'empty_ledger':
        audit['gate_execution_ledger'] = []
    elif mutation == 'missing_audit_row':
        audit['steps'].pop(0)
    elif mutation == 'scoped_audit':
        audit['scope']['stage_id'] = 'stage1'
    elif mutation == 'stale_gate':
        path = project / 'reports/phase2/gates/bit_level_full_stack.json'
        os.utime(path, (started - 30, started - 30))
    audit_path.write_text(json.dumps(audit))
    _write(project / 'reports/orchestrator/phase2_one_shot.json', json.dumps(report))
    entered, env = _actual_outer_phase3_entry(project, report, started)
    assert entered is False
    assert env['halted_at'] == 'phase2'


@pytest.mark.parametrize('mutation,want', [
    ('absent', 'NOT_MEASURED'), ('missing_pad', 'NOT_MEASURED'),
    ('pad_fail', 'NOT_MEASURED'), ('generator_error', 'NOT_MEASURED'),
    ('sim_fail', 'FAIL'), ('stale', 'NOT_MEASURED'), ('context', 'NOT_MEASURED'),
    ('source', 'NOT_MEASURED'), ('rtl', 'NOT_MEASURED'), ('pad_record', 'NOT_MEASURED'),
    ('input', 'NOT_MEASURED'), ('old_pad', 'NOT_MEASURED'),
    ('protocol_context', 'NOT_MEASURED'),
    ('empty_source', 'NOT_MEASURED'), ('unrelated_source', 'NOT_MEASURED')])
def test_default_late_terminal_missing_wrong_or_failed_still_blocks(
        tmp_path, monkeypatch, arith_class, mutation, want):
    import time
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    assert entered is True
    phase3_started = time.time()
    if mutation != 'absent':
        _late_pad_producer(project, monkeypatch, outcome=mutation)
    path = project / 'reports/phase3/gates/full_stack_functional.json'
    if mutation in ('stale', 'context', 'source', 'empty_source', 'unrelated_source'):
        terminal = json.loads(path.read_text())
        if mutation == 'stale':
            terminal['post_padring']['started_at'] = phase3_started - 30
        elif mutation == 'context':
            terminal['post_padring']['project'] = str(tmp_path / 'other_project')
        elif mutation == 'source':
            terminal['post_padring']['source']['bit_level_full_stack_tb_check.py'] = '0' * 64
        elif mutation == 'empty_source':
            terminal['post_padring']['source'] = {}
        else:
            terminal['post_padring']['source'] = {
                'unrelated_source.py': '0' * 64}
        path.write_text(json.dumps(terminal))
    elif mutation == 'rtl':
        p = project / f'phase2/stage1/rtl/{CORE}.v'
        p.write_text(p.read_text() + '\n// changed current RTL\n')
    elif mutation == 'pad_record':
        p = project / 'reports/phase3/io_pad_chip_top.json'
        p.write_text(p.read_text() + '\n')
    elif mutation == 'input':
        p = project / 'phase1/generated_docs/L10_TEST_CASES.json'
        p.write_text(p.read_text() + '\n')
    elif mutation == 'protocol_context':
        p = project / 'phase1/generated_docs/L3_CMD_PROTOCOL.json'
        p.write_text(json.dumps({'opcodes': [{'name': 'new_command', 'code': 1}]}))
    status, rc = _actual_late_rollup(env, phase3_started)
    assert status == want and rc != 0
    if mutation == 'generator_error':
        assert json.loads(path.read_text())['reason_class'] == 'EXECUTION_ERROR'


def test_default_late_actual_pad_generator_then_functional_terminal(
        tmp_path, monkeypatch, arith_class):
    """The real pad source producer writes the top; only the simulator is a stand-in."""
    import time
    import io_pad_chip_top_gen as pads
    import phase3_one_shot_runner as phase3
    import test_io_pad_chip_top_gen as pad_fixture
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    # The PDK helper is the established neutral LEF/config corpus. The real
    # generator reads this inline INPUT and the project's actual L9 ports.
    pdk_root = pad_fixture._pdk(tmp_path / 'neutral_pdk')
    _write(pdk_root / 'testpdk/libs.ref/testlib_io/lib/io.lib', '''library(neutral) {
cell(testlib_io__in) {
pin(PAD) {
direction: input;
is_pad: true;
}
pin(Y) {
direction: output;
function: "PAD";
}
}
cell(testlib_io__bi) {
pin(PAD) {
direction: inout;
is_pad: true;
function: "A";
three_state: "OE";
}
pin(A) {
direction: input;
}
pin(OE) {
direction: input;
related_power_pin: "VDDIO";
}
pin(TIELO) {
direction: output;
function: "0";
related_power_pin: "VDDIO";
}
}
}
''')
    # This pad-generator API control uses the declared direct synthetic
    # netlist. It does not claim a native LibreLane synthesis receipt.
    _write(project / 'phase3/librelane_switch.json', json.dumps({'steps': {'9': 'direct'}}))
    _write(project / f'phase2/stage2/synth/{CORE}_synth.v', CORE_V)
    _write(project / 'input/docs/L3_external_interface.md', '''---
layer: L3
---
# External interface
The I/O cell library is delegated to the PDK i/o pad defaults.
## Physical Pad Placement
| Pad side | signals |
|---|---|
| South (S) | `rst` |
| East (E) | `clk` |
| North (N) | `x[7:0]` |
| West (W) | `y` / `p` |
''')

    def actual_pad(p, *_a, **_k):
        rc, produced = pads.run(p, str(pdk_root), 'testpdk')
        assert rc == 0 and produced['verdict'] == 'WROTE', produced
        _write(p / 'reports/phase3/io_pad_chip_top.json', json.dumps(produced))
        return phase3.StepResult('io_pad_chip_top_gen', 'PASS')

    monkeypatch.setattr(phase3, 'step_io_pad_chip_top_gen', actual_pad)
    fsf = _fsf()
    monkeypatch.setattr(fsf, 'default_dispatch', _FakeSim())

    def models(p, used, _container):
        record = json.loads((p / 'reports/phase3/io_pad_chip_top.json').read_text())
        cells = {}
        for item in record['pad_instances'].values():
            terminal, core_pin = item['terminal'], item['core_pin']
            if item['direction'] == 'input':
                cells[item['master']] = (
                    f'module {item["master"]}(input {terminal}, output {core_pin}); '
                    f'assign {core_pin} = {terminal}; endmodule\n')
            else:
                cells[item['master']] = (
                    f'module {item["master"]}(inout {terminal}, input {core_pin}, input OE, output TIELO); '
                    f'assign TIELO = 1\'b0; assign {terminal} = OE ? 1\'bz : {core_pin}; endmodule\n')
        return {'neutral_pad_models.v': ''.join(cells.values())}, 'neutral pad models'

    monkeypatch.setattr(fsf, 'default_model_resolver', models)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    phase3_started = time.time()
    if entered:
        result = phase3._padring_producer_dispatch(project, None, None)
        assert result.status == 'PASS'
        assert result.extras.get('full_stack_functional_terminal', {}).get('verdict') == 'PASS', result.extras
        produced = json.loads((project / 'reports/phase3/io_pad_chip_top.json').read_text())
        assert len(produced['pad_instances']) == 12
    assert _actual_late_rollup(env, phase3_started) == ('PASS', 0)
