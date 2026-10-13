#!/usr/bin/env python3
"""Serial-parallel declared-function functional-golden oracle (repo-gatekeeper).

Pins the general IC-expert convention added to arith_oracle_tb_gen (+ its L10
per-case wiring in testbench_gen): for a SERIAL-PARALLEL arithmetic datapath
(one parallel operand + one bit-serial operand + one bit-serial result + clock),
author a functional-TB golden by driving the DECLARED operands, computing the
golden from the design's DECLARED function (a OP b mod 2^N — INDEPENDENTLY, in
Python) and comparing the reassembled DUT stream against it. The serial FRAMING
(serial-input order, serial-output order, output latency) is SELF-CALIBRATED —
discovered from the DUT stream vs the independent golden — so the oracle is
robust across RTL variants (any latency / bit-order) and needs no declared
framing. This is the shape the closed-form COMBINATIONAL oracle legitimately
DEFERS.

Contract halves pinned here:
  (a) POSITIVE — a serial-parallel multiplier gets a REAL self-checking oracle
      (ORACLE_TB_DONE) that COMPILES + PASSES against a correct DUT and FAILS
      against a broken one (falsifiable — not a rubber stamp), with NO
      declaration needed.  Generalises: the DUT here is a textbook carry-save
      serial-parallel multiplier, NOT any benchmark chip.
  (b) §4.05 FAIL-CLOSED — when the FUNCTION is not derivable (no recognised
      closed-form operator) or the SHAPE is wrong (non-arith class), the
      generator DEFERS (no fabricated golden) and the L10 per-case producer
      keeps the substance-floor (ORACLE_NONE) scaffold, so a case nobody can
      verify still fails the Step-4 gate honestly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import arith_oracle_tb_gen as aotg  # noqa: E402
import testbench_gen as tbg  # noqa: E402

# A GENERIC (chip-AGNOSTIC) textbook carry-save serial-parallel multiplier —
# parallel operand `a`, bit-serial operand `b` (LSB-first), bit-serial result
# `y` (LSB-first), synchronous active-high reset, latency 2. NOT any benchmark
# design; proves the convention fires on the interface SHAPE, not a SKU.
_GENERIC_DUT = r"""
`default_nettype none
module serpar_mul #( parameter W = 8 ) (
    input  wire         clk,
    input  wire         rst,
    input  wire [W-1:0] a,
    input  wire         b,
    output wire         y
);
    reg  [W-1:0] s, c;
    reg          br, yr;
    wire [W-1:0] m  = a & {W{br}};
    wire [W-1:0] so = m ^ s ^ c;
    wire [W-1:0] co = (m & s) | (m & c) | (s & c);
    always @(posedge clk) begin
        if (rst) begin s<=0; c<=0; br<=0; yr<=0; end
        else begin
            br <= b;
            s  <= {1'b0, so[W-1:1]};
            c  <= co;
            yr <= so[0];
        end
    end
    assign y = yr;
endmodule
`default_nettype wire
"""

# A BROKEN variant (product forced to 0) — the oracle MUST catch it.
_BROKEN_DUT = _GENERIC_DUT.replace("a & {W{br}}", "a & {W{br}} & {W{1'b0}}")

_L10 = {
    "ic_name": "serpar_mul",
    "test_cases": [
        {"name": "random_multiplication_functional_equivalence",
         "kind": "functional_vector",
         "expected": "random (a,b) all match golden model"},
        {"name": "corner_operand", "kind": "functional_vector",
         "expected": "a=0, b=0, a=MAX, b=MAX"},
        {"name": "reset", "kind": "functional_vector",
         "expected": "reset behaviour"},
    ],
}


def _mk_project(tmp: Path, *, declare: bool, bit_order: str = "LSB_first",
                encoding: str = "unsigned", dut: str = _GENERIC_DUT,
                with_l10: bool = False) -> Path:
    root = tmp / "serpar_mul"
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "serpar_mul",
        "frs_sections": [{"content":
                          "y = (a * b) mod 2^W  serial-parallel multiplier"}]}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "serpar_mul",
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "a", "direction": "input", "width": "W",
             "msb": "W-1", "lsb": "0"},
            {"name": "b", "direction": "input", "width": 1},
            {"name": "y", "direction": "output", "width": 1}]}))
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "serpar_mul.v").write_text(dut)
    if declare:
        (root / "plugin_output").mkdir()
        (root / "plugin_output" / "declaration.json").write_text(json.dumps({
            "bit_order": bit_order, "latency_cycles": 2,
            "integer_encoding": encoding, "reset_polarity": "active_high",
            "size_param": 8}))
    if with_l10:
        (gd / "L10_TEST_CASES.json").write_text(
            json.dumps(_L10, ensure_ascii=False))
    return root


# ── (a) POSITIVE: declared framing → real serial oracle ──────────────────────
def test_serial_spec_extracted_from_declaration(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    spec, reason = aotg.extract_serial_arith_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["topology"] == "serial_parallel"
    assert spec["operator"] == "*"
    assert spec["parallel"] == "a"
    assert spec["serial_in"] == "b" and spec["serial_out"] == "y"
    # declared conventions are read as INFORMATIONAL annotations (the oracle
    # self-calibrates framing and does not depend on them being correct).
    assert spec["declared_bit_order"] == "LSB" and spec["declared_latency"] == 2


def test_conventions_read_from_rtl_header_when_no_declaration_json(tmp_path):
    # Declaration lives ONLY in the RTL header 'DECLARED CHOICES' block.
    proj = _mk_project(tmp_path, declare=False)
    hdr = ("// DECLARED CHOICES\n//   bit_order = LSB_first\n"
           "//   latency_cycles = 2\n//   integer_encoding = unsigned\n"
           "//   reset_polarity = active_high\n")
    dutf = proj / "phase2" / "stage1" / "rtl" / "serpar_mul.v"
    dutf.write_text(hdr + dutf.read_text())
    conv = aotg.read_declared_conventions(proj, [])
    assert conv is not None
    assert conv["bit_order"] == "LSB" and conv["latency"] == 2


def test_generate_emits_self_calibrating_serial_oracle(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0 and rep["verdict"] == "TB_EMITTED"
    assert rep["topology"] == "serial_parallel"
    tb = (proj / rep["tb"]).read_text()
    assert "ORACLE_TB_DONE pass=" in tb
    # NON-VACUOUS: real datapath width, several distinct goldens.
    assert "localparam integer N      = 8;" in tb
    assert tb.count("_gv[") >= 8
    # SELF-CALIBRATING: drives both serial-input orders and searches
    # (in_order x out_order x offset) — never trusts a declared latency/order.
    assert "_drive_capture(0)" in tb and "_drive_capture(1)" in tb
    assert "MAXOFF" in tb and "_best" in tb
    # golden computed independently, framing discovered — never read from DUT.
    assert "DISCOVERED from the DUT stream" in tb


def test_no_declaration_still_emits_self_calibrating(tmp_path):
    # CAPABILITY: the self-calibrating oracle needs NO declaration — the serial
    # framing is discovered, not read. So a project without declaration.json
    # (and no RTL-header framing) STILL emits a real oracle.
    proj = _mk_project(tmp_path, declare=False)
    spec, _ = aotg.extract_serial_arith_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0 and rep["verdict"] == "TB_EMITTED"


# ── (b) §4.05 FAIL-CLOSED: undecidable FUNCTION or wrong SHAPE → DEFER ────────
def test_unrecognised_operator_defers_fail_closed(tmp_path):
    # No recognised closed-form operator in the spec → the FUNCTION is not
    # derivable → DEFER (never fabricate a golden).
    proj = _mk_project(tmp_path, declare=True)
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "serpar_mul",
        "frs_sections": [{"content": "a bit-serial scrambler of x and y"}]}))
    spec, reason = aotg.extract_serial_arith_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None and "operator" in reason.lower()
    _, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 2


def test_non_arith_class_defers_fail_closed(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    _, rc = aotg.generate(proj, "processor_cpu")
    assert rc == 2


# ── L10 per-case wiring (testbench_gen) ──────────────────────────────────────
def test_testbench_gen_emits_per_case_golden_oracles(tmp_path):
    proj = _mk_project(tmp_path, declare=True, with_l10=True)
    report: dict = {}
    n = tbg.emit_unit_tbs(proj, "serpar_mul", kind="functional_vector",
                          report=report)
    assert n == 3
    tb_dir = proj / "phase2" / "stage1" / "sim" / "tb"
    for case in ("random_multiplication_functional_equivalence",
                 "corner_operand", "reset"):
        txt = (tb_dir / f"{case}.v").read_text()
        assert "VIBEIC_TB_ORACLE: NONE" not in txt, case  # real oracle
        assert "ORACLE_TB_DONE" in txt, case              # golden compare
    assert sorted(report.get("golden_oracle_cases", [])) == sorted(
        ["random_multiplication_functional_equivalence", "corner_operand",
         "reset"])


def test_testbench_gen_fail_closed_keeps_scaffold_when_function_undecidable(
        tmp_path):
    # §4.05 FAIL-CLOSED: when the FUNCTION is not derivable (no recognised
    # closed-form operator), no golden oracle can be authored, so every L10
    # functional_vector case keeps the substance-floor (ORACLE_NONE) scaffold —
    # an unverifiable case still fails the Step-4 gate honestly.
    proj = _mk_project(tmp_path, declare=True, with_l10=True)
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "serpar_mul",
        "frs_sections": [{"content": "a bit-serial scrambler of x and y"}]}))
    tbg.emit_unit_tbs(proj, "serpar_mul", kind="functional_vector", report={})
    tb_dir = proj / "phase2" / "stage1" / "sim" / "tb"
    for case in ("random_multiplication_functional_equivalence",
                 "corner_operand", "reset"):
        txt = (tb_dir / f"{case}.v").read_text()
        assert "VIBEIC_TB_ORACLE: NONE" in txt, case


# ── falsifiability (iverilog-gated) ──────────────────────────────────────────
def _run_oracle(tb: Path, dut_text: str, tmp: Path) -> int:
    tmp.mkdir(parents=True, exist_ok=True)
    dutf = tmp / "dut.v"
    dutf.write_text(dut_text)
    out = tmp / "o.out"
    rc = subprocess.run(
        ["iverilog", "-g2012", "-o", str(out), str(tb), str(dutf)],
        capture_output=True, text=True)
    if rc.returncode != 0:
        return -1
    run = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
    import re
    m = re.search(r"ORACLE_TB_DONE pass=(\d+)/(\d+)", run.stdout)
    assert m, run.stdout + run.stderr
    return 0 if m.group(1) == m.group(2) else 1


@pytest.mark.skipif(not shutil.which("iverilog"),
                    reason="iverilog not available")
def test_oracle_passes_correct_dut_fails_broken_dut(tmp_path):
    proj = _mk_project(tmp_path, declare=True)
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0
    tb = proj / rep["tb"]
    assert _run_oracle(tb, _GENERIC_DUT, tmp_path / "ok") == 0     # all pass
    assert _run_oracle(tb, _BROKEN_DUT, tmp_path / "bad") == 1     # falsified


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# Public issues #3093/#3094: wholly neutral native producer/consumer inputs.
def _declared_scenario_project(root, *, width=8, order="LSB_first",
                               rearm="clocked_reset", mode="good", latency=0, renamed=False):
    gd = root / "phase1/generated_docs"
    rtl = root / "phase2/stage1/rtl"
    gd.mkdir(parents=True); rtl.mkdir(parents=True)
    scope = [
        ("operand_limits", "Operand boundaries: x/y=0, 1, MAX; all Cartesian combinations"),
        ("transaction_sequence", "Consecutive transactions: at least 16 operand pairs using the declared rearm, no extra idle cycles"),
        ("reset_situations", "Synchronous reset held, released, and asserted during computation; between-edge reset pulses must not reset"),
    ]
    cases = [{"name": name, "kind": "functional_vector", "expected": "100% PASS",
              "coverage_scope": text} for name, text in scope]
    ports = [{"name": n, "direction": d, "width": w} for n,d,w in
             [("clk","input",1),("rst","input",1),("x","input",width),
              ("y","input",1),("p","output",1)]]
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "neutral_serial", "ic_class": "digital_arithmetic_primitive",
        "top_ports": ports, "clocks": [{"name":"clk","period_ns":10}],
        "reset_domains":[{"name":"rst","polarity":"active_high","sync":"sync"}]}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [{
        "content": f"p = (x & y) mod 2^{width}; serial-parallel bitwise arithmetic"}]}))
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": cases}))
    root.joinpath("plugin_output").mkdir()
    root.joinpath("plugin_output/declaration.json").write_text(json.dumps({
        "bit_order":order, "latency_cycles":latency,
        "latency_cycles_origin":"settled_edge_offset", "integer_encoding":"unsigned",
        "reset_polarity":"active_high", "transaction_rearm":rearm,
        "rearm_reset_cycles":1, "parallel_hold":"through_final_product_bit"}))
    bit = "idx" if order == "LSB_first" else f"{width-1}-idx"
    reset = "rst" if mode != "ignored_reset" else "1'b0"
    inv = "~" if mode == "wrong_product" else ""
    rtl.joinpath("neutral_serial.v").write_text(f"""`timescale 1ns/1ps
module neutral_serial(input clk,rst,input [{width-1}:0] x,input y,output reg p);
integer idx=0;
always @(posedge clk) begin
 if ({reset}) begin idx<=0; p<=0; end
 else begin p<={inv}(x[{bit}] & y); idx <= (idx=={width-1})?0:idx+1; end
end
endmodule
""")
    if renamed:
        import re
        names={"clk":"i_clk", "rst":"i_rst", "x":"operand_word",
               "y":"serial_bit", "p":"result_bit"}
        for path in [gd/"L9_INTEGRATION_SPEC.json",gd/"L2_FRS.json",
                     rtl/"neutral_serial.v"]:
            text=path.read_text()
            for before,after in names.items():
                text=re.sub(r"\b"+before+r"\b",after,text)
            path.write_text(text)
    return cases


def _scenario_icarus_execution(root, cases, *, stale=False):
    """Actual Icarus transport; production emit/capture and goal reader remain real.

    Does not pretend to execute the Default whole front door or upstream phases.
    """
    import _l10_execution as execution
    import l10_coverage_goal_classify as goals
    assert shutil.which("iverilog") and shutil.which("vvp"), "native Icarus required"
    tb_dir = root / "phase2/stage1/sim/tb"
    assert tbg.emit_unit_tbs(root, top="neutral_serial", report={}) == len(cases)
    rows=[]
    for case in cases:
        tb=tb_dir/(case["name"]+".v"); work=root/"native"/case["name"]
        work.mkdir(parents=True); binary=work/"sim.vvp"
        cc=subprocess.run(["iverilog","-g2012","-s",case["name"],"-o",str(binary),
                           str(root/"phase2/stage1/rtl/neutral_serial.v"),str(tb)],
                          capture_output=True,text=True)
        (work/"compile.log").write_text(cc.stdout+cc.stderr)
        assert cc.returncode==0, cc.stdout+cc.stderr
        run=subprocess.run(["vvp",str(binary)],capture_output=True,text=True)
        transcript=work/"run.log"; transcript.write_text(run.stdout+run.stderr)
        capture=getattr(aotg,"capture_arithmetic_scenario_execution",None)
        sources={str(root/"phase2/stage1/rtl/neutral_serial.v"):
                 execution.file_sha256(root/"phase2/stage1/rtl/neutral_serial.v")}
        measured=capture(root,tb,transcript,sources)[0] if capture else None
        row={"id":case["name"],"verdict":"PASS" if run.returncode==0 else "FAIL",
             "sim_executed":True,"tb_file":str(tb),**execution.capture_tb_identity(tb),
             "detail":"actual Icarus native scenario transport"}
        if measured is not None: row["arithmetic_scenario"]=measured
        rows.append(row)
    execution.write_record(root,root/"phase1/generated_docs/L10_TEST_CASES.json",rows,
                           producer="test-owned actual Icarus transport",tb_dir=tb_dir)
    if stale:
        decl=root/"plugin_output/declaration.json"
        decl.write_text(decl.read_text()+" ")
    record=execution.load_record(root,root/"phase1/generated_docs/L10_TEST_CASES.json")
    return {case["name"]:goals.measure_scenario_goal(case,100.0,cases,record)
            for case in cases}


@pytest.mark.parametrize("width,order,rearm,renamed", [
    (4,"LSB_first","clocked_reset",False),(8,"LSB_first","clocked_reset",False),
    (8,"MSB_first","clocked_reset",False),(8,"LSB_first","continuous",False),
    (8,"LSB_first","clocked_reset",True),
])
def test_declared_arithmetic_scenarios_gain_only_actual_native_credit(
        tmp_path,width,order,rearm,renamed):
    root=tmp_path/"neutral"
    cases=_declared_scenario_project(root,width=width,order=order,rearm=rearm,renamed=renamed)
    measured=_scenario_icarus_execution(root,cases)
    assert {k:v["verdict"] for k,v in measured.items()} == {
        c["name"]:"PASS" for c in cases}, measured
    assert all(v["achieved_pct"]==100.0 and v["bound_cases"] for v in measured.values())
    if renamed:
        # Actual ordinary unit runner publishes the same source-owned receipt.
        import _l10_execution as execution
        import l10_coverage_goal_classify as goals
        report={}
        assert tbg.run_unit_tbs(root,container="host",report=report)==len(cases),report
        assert report['passed']==len(cases) and report['failed']==0,report
        record=execution.load_record(root,root/'phase1/generated_docs/L10_TEST_CASES.json')
        actual={c['name']:goals.measure_scenario_goal(c,100.0,cases,record)['verdict'] for c in cases}
        assert actual=={c['name']:'PASS' for c in cases},actual


@pytest.mark.parametrize("mode,latency,stale,expected", [
    ("wrong_product",0,False,"FAIL"),("ignored_reset",0,False,"FAIL"),
    ("good",1,False,"FAIL"),("good",0,True,"NOT_MEASURED"),
])
def test_generated_arithmetic_scenario_controls_remain_falsifiable(
        tmp_path,mode,latency,stale,expected):
    root=tmp_path/"neutral"
    cases=_declared_scenario_project(root,mode=mode,latency=latency)
    measured=_scenario_icarus_execution(root,cases,stale=stale)
    row=measured["reset_situations"] if mode=="ignored_reset" else measured["operand_limits"]
    assert row["verdict"]==expected, row


def test_composite_declared_scenario_scope_executes_every_requested_population(tmp_path):
    root=tmp_path/"neutral"
    cases=_declared_scenario_project(root)
    cases[0]["stimulus"] = ("Operand boundaries; consecutive >= 4 transactions; "
        "reset held and released and asserted during computation")
    l10=root/"phase1/generated_docs/L10_TEST_CASES.json"
    doc=json.loads(l10.read_text())
    doc["test_cases"]=cases
    l10.write_text(json.dumps(doc))
    actual=_scenario_icarus_execution(root,cases)
    import _l10_execution as execution
    import l10_coverage_goal_classify as goals
    record=execution.load_record(root,l10)
    measured=record['rows']['operand_limits'].get('arithmetic_scenario') or {}
    wanted={'operand_boundaries','consecutive_transactions','reset_situations'}
    observed=measured.get('populations') or []
    (root/'actual-composite-values.json').write_text(json.dumps({
        'consumer':actual['operand_limits'],'measured':measured},indent=2))
    assert actual['operand_limits']['verdict']=='PASS',actual['operand_limits']
    assert {p['scenario'] for p in observed}==wanted,measured
    declared={p['scenario']:p for p in measured['plan']['populations']}
    assert all(p['transactions']==declared[p['scenario']]['transactions'] and
               p['comparisons']==declared[p['scenario']]['comparisons'] and
               p['errors']==0 for p in observed),measured
    assert sum(p['comparisons'] for p in observed)==measured['comparisons']
    assert measured['complete'] is True
    # Omitting one required family's receipt cannot preserve whole-row credit.
    measured['populations']=[p for p in observed if p['scenario']!='reset_situations']
    partial=goals.measure_scenario_goal(cases[0],100.0,cases,record)
    assert partial['verdict']=='NOT_MEASURED',partial


@pytest.mark.parametrize("marker,prefix,suffix,duplicate,expected", [
    ('ARITH_SCENARIO_DONE','not ','',False,'NOT_MEASURED'),
    ('ARITH_SCENARIO_DONE','diagnostic: ','',False,'NOT_MEASURED'),
    ('ARITH_SCENARIO_DONE','',' (not measured)',False,'NOT_MEASURED'),
    ('ARITH_SCENARIO_POPULATION','not ','',False,'NOT_MEASURED'),
    ('ARITH_SCENARIO_POPULATION','diagnostic: ','',False,'NOT_MEASURED'),
    ('ARITH_SCENARIO_POPULATION','',' (not measured)',False,'NOT_MEASURED'),
    ('ARITH_SCENARIO_DONE','','',True,'NOT_MEASURED'),
    ('ARITH_SCENARIO_DONE','','',False,'PASS'),
])
def test_native_scenario_transcript_requires_canonical_records(tmp_path,marker,prefix,suffix,duplicate,expected):
    import _l10_execution as execution
    import l10_coverage_goal_classify as goals
    root=tmp_path/'neutral'
    cases=_declared_scenario_project(root)
    cases[0]['stimulus']='Operand boundaries; consecutive >= 4 transactions; reset held, released, and asserted during computation'
    l10=root/'phase1/generated_docs/L10_TEST_CASES.json'
    l10.write_text(json.dumps({'test_cases':cases}))
    original=_scenario_icarus_execution(root,cases)
    assert original['operand_limits']['verdict']=='PASS',original
    record=execution.load_record(root,l10)
    row=record['rows']['operand_limits']; measured=row['arithmetic_scenario']
    transcript=Path(measured['transcript']);raw=transcript.read_text()
    matching=[line for line in raw.splitlines() if line.startswith(marker+' ')]
    assert matching,'actual native record required for the control'
    changed='\n'.join(prefix+line+suffix if line.startswith(marker+' ') else line for line in raw.splitlines())+'\n'
    if duplicate:changed+=matching[0]+'\n'
    transcript.write_text(changed)
    captured,why=aotg.capture_arithmetic_scenario_execution(root,Path(row['tb_file']),transcript,measured['sources'])
    if captured is None:row.pop('arithmetic_scenario',None)
    else:row['arithmetic_scenario']=captured
    actual=goals.measure_scenario_goal(cases[0],100.0,cases,record)
    (root/'record-grammar-values.json').write_text(json.dumps({'marker':marker,'prefix':prefix,'suffix':suffix,'duplicate':duplicate,'expected':expected,'actual':actual,'capture':captured,'why':why},indent=2))
    assert actual['verdict']==expected,actual
