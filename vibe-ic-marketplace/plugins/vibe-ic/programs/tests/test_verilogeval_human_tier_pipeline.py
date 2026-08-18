"""verilogeval_human_tier_pipeline — positive + §4.05 NEGATIVE guards.

The pipeline applies the 5-tier CONVERGE model to the VerilogEval-HUMAN
code-complete dataset. These tests pin:

  POSITIVE
    * parse_interface recovers the EXACT ANSI ports from an _ifc.txt header,
      with correct widths (literal range, 1-bit, param-expression=None).
    * build_gate yields a meaningful interface gate (module name + ports).
    * gate_check ACCEPTS an RTL that conforms to the gate.
    * _interface_complete is True for a literal-width interface.
    * classify(tier1_ruled_out=...) never re-trusts a failed emit (the bug that
      made gatesv100/gatesv wrongly land in Tier1).

  §4.05 NEGATIVE (the load-bearing guards — never emit/grade WRONG)
    * gate_check REJECTS a wrong module name / missing port / wrong direction /
      wrong literal width.
    * gate_check NEVER false-rejects: a parameterized-width port, an EXTRA port
      the AI legitimately adds, or a structure the spec did not state.
    * the floor prover NEVER mis-reads the benchmark's benign internal "TIMEOUT"
      watchdog print as a failure — a golden that finishes with 0 mismatches is
      a PASS, not a Tier5 floor (the false-floor bug that wrongly flagged
      lfsr32 / count_clock / fancytimer).
    * a registry emit that does NOT pass _test.sv is NEVER Tier1 (the emit fired
      but is WRONG — it must drop to the gated AI tier, not be shipped).

The iverilog/dataset-dependent tests SKIP cleanly when iverilog or the dataset
is unavailable (so CI without the bench still passes); the pure-logic tests
always run.
"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verilogeval_human_tier_pipeline as P  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")
_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_HAVE_DATASET = _DATASET.exists()

_needs_bench = pytest.mark.skipif(
    not (_HAVE_IVERILOG and _HAVE_DATASET),
    reason="requires iverilog + the VerilogEval-HUMAN dataset; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")


# --------------------------------------------------------------------------- #
# POSITIVE — interface parse
# --------------------------------------------------------------------------- #
def test_parse_interface_exact_ports_and_widths():
    ifc = (
        "module TopModule (\n"
        "  input [99:0] a,\n"
        "  input [99:0] b,\n"
        "  input sel,\n"
        "  output [99:0] out\n"
        ");\n")
    parsed = P.parse_interface(ifc)
    assert parsed is not None
    name, ports = parsed
    assert name == "TopModule"
    by = {p["name"]: p for p in ports}
    assert by["a"]["dir"] == "input" and by["a"]["width"] == 100
    assert by["b"]["width"] == 100
    assert by["sel"]["width"] == 1
    assert by["out"]["dir"] == "output" and by["out"]["width"] == 100


def test_parse_interface_output_reg_and_clk():
    ifc = ("module TopModule (\n  input clk,\n  input d,\n"
           "  output reg q\n);\n")
    name, ports = P.parse_interface(ifc)
    assert name == "TopModule"
    by = {p["name"]: p for p in ports}
    assert by["clk"]["dir"] == "input"
    assert by["q"]["dir"] == "output" and by["q"]["width"] == 1


def test_param_expression_width_is_none_not_a_mismatch():
    # `[N-1:0]` is a parameter-expression width — unknown literal, NOT a width
    # the gate may enforce against a literal (§4.05 false-reject guard).
    assert P._range_width("N-1", "0") is None
    assert P._range_width("7", "0") == 8
    assert P._range_width(None, None) == 1


# --------------------------------------------------------------------------- #
# POSITIVE — build_gate + interface completeness + gate_check ACCEPT
# --------------------------------------------------------------------------- #
def _prob(ifc: str, prompt: str = "") -> dict:
    return {"stem": "ProbX", "id": "ProbX", "ifc": ifc,
            "prompt": prompt or ifc, "ref_path": "", "test_path": ""}


def test_build_gate_meaningful_interface():
    g = P.build_gate(_prob(
        "module TopModule (\n  input in,\n  output out\n);\n"))
    assert g["module_name"] == "TopModule"
    names = {p["name"] for p in g["ports"]}
    assert names == {"in", "out"}


def test_interface_complete_for_literal_width():
    g = P.build_gate(_prob(
        "module TopModule (\n  input [3:0] a,\n  output [3:0] y\n);\n"))
    assert P._interface_complete(_prob(""), g) is True


def test_gate_check_accepts_conformant_rtl():
    prob = _prob("module TopModule (\n  input a,\n  input b,\n"
                 "  output sum,\n  output cout\n);\n")
    good = ("module TopModule(input a, input b, output sum, output cout);\n"
            "  assign {cout,sum} = a + b;\nendmodule\n")
    r = P.gate_check(prob, good)
    assert r["pass"] is True, r["violations"]


def test_gate_check_allows_extra_port():
    # §4.05: an EXTRA port the AI legitimately adds (e.g. a clk the harness also
    # drives) must NOT be rejected — the gate enforces the spec ports, not a
    # closed-world port set.
    prob = _prob("module TopModule (\n  input d,\n  output q\n);\n")
    rtl = ("module TopModule(input clk, input d, output q);\n"
           "  always @(posedge clk) q <= d;\nendmodule\n")
    r = P.gate_check(prob, rtl)
    assert r["pass"] is True, r["violations"]


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE — gate_check REJECTS wrong RTL
# --------------------------------------------------------------------------- #
def test_gate_check_rejects_wrong_module_name():
    prob = _prob("module TopModule (\n  input in,\n  output out\n);\n")
    rtl = "module WrongName(input in, output out);\n  assign out=in;\nendmodule\n"
    r = P.gate_check(prob, rtl)
    assert r["pass"] is False
    assert any(v["kind"] == "module_name" for v in r["violations"])


def test_gate_check_rejects_missing_port():
    prob = _prob("module TopModule (\n  input a,\n  input b,\n  output y\n);\n")
    rtl = "module TopModule(input a, output y);\n  assign y=a;\nendmodule\n"
    r = P.gate_check(prob, rtl)
    assert r["pass"] is False
    assert any(v["kind"] == "missing_port" and "`b`" in v["detail"]
               for v in r["violations"])


def test_gate_check_rejects_wrong_direction():
    prob = _prob("module TopModule (\n  input a,\n  output y\n);\n")
    rtl = "module TopModule(output a, input y);\n endmodule\n"
    r = P.gate_check(prob, rtl)
    assert r["pass"] is False
    assert any(v["kind"] == "port_dir" for v in r["violations"])


def test_gate_check_rejects_wrong_literal_width():
    prob = _prob("module TopModule (\n  input [7:0] a,\n  output [7:0] y\n);\n")
    rtl = ("module TopModule(input [6:0] a, output [7:0] y);\n"
           "  assign y={1'b0,a};\nendmodule\n")
    r = P.gate_check(prob, rtl)
    assert r["pass"] is False
    assert any(v["kind"] == "port_width" and "`a`" in v["detail"]
               for v in r["violations"])


def test_gate_check_no_false_reject_on_param_width():
    # §4.05: a candidate port with a parameter-expression width must NOT be
    # rejected for "not matching" a spec literal — the width is unknown, not
    # wrong. (Build a spec port whose width is also unknown to mirror the rule.)
    gate = {"module_name": "TopModule",
            "ports": [{"name": "a", "dir": "input", "width": None},
                      {"name": "y", "dir": "output", "width": None}],
            "structures": {}}
    rtl = ("module TopModule(input [WIDTH-1:0] a, output [WIDTH-1:0] y);\n"
           "  assign y=a;\nendmodule\n")
    r = P.gate_check_spec(gate, rtl)
    assert r["pass"] is True, r["violations"]


def test_gate_check_does_not_demand_unstated_structure():
    # §4.05: a structure the spec did NOT state is never demanded. An empty
    # structures gate passes any conformant-interface RTL.
    gate = {"module_name": "TopModule",
            "ports": [{"name": "in", "dir": "input", "width": 1},
                      {"name": "out", "dir": "output", "width": 1}],
            "structures": {"enum_modes": [], "fsm_states": [],
                           "register_names": []}}
    rtl = "module TopModule(input in, output out);\n assign out=in;\nendmodule\n"
    assert P.gate_check_spec(gate, rtl)["pass"] is True


def test_gate_check_demands_stated_structure():
    # The positive complement: when the spec DID recover a structure token, the
    # candidate must REPRESENT it.
    gate = {"module_name": "TopModule",
            "ports": [{"name": "in", "dir": "input", "width": 1},
                      {"name": "out", "dir": "output", "width": 1}],
            "structures": {"fsm_states": ["S_IDLE"], "enum_modes": [],
                           "register_names": []}}
    missing = "module TopModule(input in, output out);\n assign out=in;\nendmodule\n"
    r = P.gate_check_spec(gate, missing)
    assert r["pass"] is False
    assert any(v["kind"] == "missing_fsm_state" for v in r["violations"])
    present = ("module TopModule(input in, output out);\n"
               "  localparam S_IDLE=0; assign out=in;\nendmodule\n")
    assert P.gate_check_spec(gate, present)["pass"] is True


def test_build_gate_does_not_enforce_fsm_state_names():
    # §4.05 false-reject guard: an FSM state-diagram names states (OFF/ON, A..F)
    # purely as a labeling convention — a correct design (incl. the golden, which
    # renames OFF/ON to A/B) may use ANY encoding. build_gate must NOT push those
    # names into the ENFORCED structures (only diagnosis), else it false-rejects
    # a correct author.
    prompt = (
        "This is a Moore state machine with two states. Reset to state OFF.\n"
        "  OFF (out=0) --j=0--> OFF\n"
        "  OFF (out=0) --j=1--> ON\n"
        "  ON  (out=1) --k=1--> OFF\n"
        "module TopModule (\n  input clk,\n  input j,\n  input k,\n"
        "  input areset,\n  output out\n);\n")
    g = P.build_gate({"stem": "X", "id": "X", "ifc": prompt, "prompt": prompt,
                      "ref_path": "", "test_path": ""})
    assert g["structures"]["fsm_states"] == []  # NOT enforced
    # an RTL that encodes the FSM with A/B labels (not OFF/ON) still conforms.
    rtl = ("module TopModule(input clk, input j, input k, input areset,\n"
           "  output out);\n  parameter A=0,B=1; reg state;\n"
           "  assign out=(state==B);\nendmodule\n")
    assert P.gate_check_spec(g, rtl)["pass"] is True, \
        P.gate_check_spec(g, rtl)["violations"]


def test_gate_check_no_module_header_is_rejected():
    prob = _prob("module TopModule (\n  input in,\n  output out\n);\n")
    r = P.gate_check(prob, "// no module here\nassign x = 1;\n")
    assert r["pass"] is False
    assert r["violations"][0]["kind"] == "no_module"


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE — classify never re-trusts a FAILED emit (the gatesv bug)
# --------------------------------------------------------------------------- #
def test_classify_tier1_ruled_out_does_not_resurrect_emit(monkeypatch):
    # When solve() has already run the iverilog verify and it FAILED, the
    # fall-through classify must NOT re-emit and return Tier1. Simulate a
    # registry that ALWAYS fires (so the only thing keeping it out of Tier1 is
    # the tier1_ruled_out flag).
    prob = _prob("module TopModule (\n  input a,\n  output y\n);\n")
    monkeypatch.setattr(P, "deterministic_emit",
                        lambda p: ("comb_advanced", "module TopModule(input a, output y);\nendmodule\n"))
    t = P.classify(prob, gate=P.build_gate(prob),
                   verify_tier1=False, tier1_ruled_out=True)
    assert t != P.TIER_PROGRAM
    # a complete literal-width interface ⇒ it lands in the gated AI tier (T2).
    assert t == P.TIER_AI_EMIT


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE — the floor prover's benign-"TIMEOUT" guard (false-floor bug)
# --------------------------------------------------------------------------- #
@_needs_bench
def test_golden_long_sim_with_benign_timeout_is_not_a_floor():
    # lfsr32 / count_clock / fancytimer arm an internal #1000000 watchdog that
    # PRINTS "TIMEOUT" but still finishes with 0 mismatches. The floor prover
    # MUST NOT call these floors. (At least one of the three must exist.)
    found = False
    for stem in ("Prob082_lfsr32", "Prob141_count_clock",
                 "Prob156_review2015_fancytimer"):
        if not (_DATASET / f"{stem}_ref.sv").exists():
            continue
        found = True
        prob = P.load_problem(str(_DATASET), stem)
        assert P.floor_evidence(prob) is None, \
            f"{stem} wrongly flagged a Tier5 floor (benign watchdog print)"
    if not found:
        pytest.skip("none of the long-sim problems present")


@_needs_bench
def test_no_tier5_floor_anywhere_every_golden_passes():
    # The honest VE-human result: NO genuine floor — every golden passes its own
    # test. (Spot-check a representative sample to keep the test fast.)
    for stem in ("Prob001_zero", "Prob005_notgate", "Prob031_dff",
                 "Prob082_lfsr32", "Prob141_count_clock"):
        if not (_DATASET / f"{stem}_ref.sv").exists():
            continue
        prob = P.load_problem(str(_DATASET), stem)
        assert P.floor_evidence(prob) is None


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE — a WRONG registry emit is never Tier1; POSITIVE — a right one is
# --------------------------------------------------------------------------- #
@_needs_bench
def test_correct_deterministic_emit_is_tier1():
    # A truth-table problem the registry deterministically + correctly solves.
    stem = "Prob069_truthtable1"
    if not (_DATASET / f"{stem}_ifc.txt").exists():
        pytest.skip(f"{stem} absent")
    prob = P.load_problem(str(_DATASET), stem)
    res = P.solve(prob, verify_tier1=True)
    assert res["tier"] == P.TIER_PROGRAM
    assert "Mismatches: 0" in (res.get("verify_log") or "")


@_needs_bench
def test_gatesv_deterministic_emit_is_correct_width_tier1():
    # gatesv100 / gatesv: out_both/out_any are declared ONE bit narrower than `in`
    # (the VE-Human twin uses out_both[N-2:0] / out_any[N-1:1]). The PRIMARY registry
    # solver `comb_advanced._neighbour_vector` now emits each output at its DECLARED
    # range (fix #4) and iverilog-PASSES, so deterministic_emit returns a VERIFIED
    # PRIMARY emit — the SAME emit path the real gate (gates_atomic) uses. This is
    # the root fix: the earlier supplemental `neighbour_vector_exact_width` solver
    # fixed only the tier-pipeline CLASSIFICATION while the gate still shipped the
    # wrong-width comb_advanced (a stability-test-vs-blind-run gap); the gate now
    # ships the correct width too. Either solver kind is acceptable as long as the
    # adopted emit is correct-width and Tier1.
    found = False
    for stem in ("Prob092_gatesv100", "Prob094_gatesv"):
        if not (_DATASET / f"{stem}_ifc.txt").exists():
            continue
        found = True
        prob = P.load_problem(str(_DATASET), stem)
        kind, rtl = P.deterministic_emit(prob)
        assert rtl, f"{stem}: a deterministic emit must fire"
        assert kind in ("comb_advanced", "neighbour_vector_exact_width"), \
            f"{stem}: unexpected solver kind {kind}"
        # the adopted emit must NOT declare the boundary-omitted outputs full-width
        # (the bug): out_any must keep its declared [N-1:1] offset, not [N-1:0].
        import re as _re
        if "out_any" in rtl:
            m = _re.search(r'output\s+\[(\d+):(\d+)\]\s+out_any', rtl)
            if m:
                assert int(m.group(2)) >= 1, \
                    f"{stem}: out_any must keep its declared offset LSB, got [{m.group(1)}:{m.group(2)}]"
        ok, log = P.tier1_verify(prob, rtl)
        assert ok, f"{stem}: the adopted emit must pass _test.sv: {log}"
        res = P.solve(prob, verify_tier1=True)
        assert res["tier"] == P.TIER_PROGRAM, \
            f"{stem}: a VERIFIED deterministic emit must be Tier1"
        assert "Mismatches: 0" in (res.get("verify_log") or "")
    if not found:
        pytest.skip("gatesv problems absent")


@_needs_bench
def test_unverified_emit_is_never_tier1_synthetic():
    # The load-bearing §4.05 INVARIANT (kept guarded with a synthetic wrong emit
    # so it no longer depends on a now-fixed problem): an emit that does NOT pass
    # _test.sv is NEVER classified Tier1. We feed a deliberately-wrong candidate
    # for a real problem and assert tier1_verify rejects it.
    stem = "Prob094_gatesv"
    if not (_DATASET / f"{stem}_ifc.txt").exists():
        pytest.skip(f"{stem} absent")
    prob = P.load_problem(str(_DATASET), stem)
    # a syntactically-valid but WRONG TopModule (constant outputs) at the exact
    # interface widths — compiles, but mismatches the reference.
    wrong = (
        "module TopModule (\n"
        "  input [3:0] in,\n"
        "  output [2:0] out_both,\n"
        "  output [3:1] out_any,\n"
        "  output [3:0] out_different\n"
        ");\n"
        "  assign out_both = 3'b0;\n"
        "  assign out_any = 3'b0;\n"
        "  assign out_different = 4'b0;\n"
        "endmodule\n")
    ok, _log = P.tier1_verify(prob, wrong)
    assert ok is False, "a WRONG emit must NOT verify as Tier1"
