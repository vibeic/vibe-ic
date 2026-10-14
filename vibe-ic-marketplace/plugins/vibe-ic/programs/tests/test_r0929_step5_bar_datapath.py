#!/usr/bin/env python3
"""R-0929-STEP5-BAR (root, IC expert, 2026-09-29) — what Step 5 needs to PASS.

Found by FULLSTACKTB: the Step-5 PASS bar counted only EXECUTED cases
(subservient: 3 executed, 7 no_oracle including every CPU data-path case, and
both the producer and `bit_level_full_stack_tb_check` read PASS over them).

Pinned here, each with its known-negative:
  * a declared case that did not execute blocks PASS (NOT_MEASURED) unless a
    named ruling excludes it (firmware image absent, R-0929-OWNER-SUB-ACCEPT
    (2)), the design declares it inapplicable (the landed `applies_when`
    contract), or ISA credit (R-0929-OWNER-SUB-ACCEPT (1)) covers it;
  * ISA credit counts ONLY when a CPU data-path case -- a real program the FLOW
    assembles from the design input (fetch, execute, store, load back) over a
    byte SRAM of exactly the delivered size -- executed and passed through the
    pad-ring chip top;
  * the gate re-derives all of it: the declared case list, each disposition,
    and the program image + testbench bytes (rebuilt from the design input),
    so a record can neither relabel a case nor vouch for a program.

The CPU fixture is a synthetic byte-SRAM RV32I-subset core run for real under
iverilog through a synthetic pad-ring top; the ISA-suite receipt reader is
stood in (its own tests pin it). chip-AGNOSTIC: every fixture is synthetic.
"""
from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

import test_fullstacktb_functional_population as base  # noqa: E402
from not_verified_tier import skip_not_verified  # noqa: E402


def _fsf():
    return importlib.import_module("full_stack_functional_tb")


def _cdp():
    return importlib.import_module("cpu_datapath_program")


@pytest.fixture
def arith_class(monkeypatch):
    """The arithmetic DIE; its declared-function golden grounds every case
    except the extra rows below, which stand for "no oracle family grounds
    this case" (the state the bar is about)."""
    import testbench_gen as tbg
    import arith_oracle_tb_gen as aog
    monkeypatch.setattr(tbg, "_detect_ic_class",
                        lambda project: "digital_arithmetic_primitive")
    real = aog.emit_case_oracle

    def emit(project, ic_class, name, *a, **k):
        if name in UNGROUNDED:
            return None
        return real(project, ic_class, name, *a, **k)
    monkeypatch.setattr(aog, "emit_case_oracle", emit)


# ===========================================================================
# A. THE BAR over the synthetic arithmetic DIE (simulator stand-in)
# ===========================================================================
UNMEASURED = {"name": "widget_glow", "kind": "functional_vector",
              "stimulus": "press the front-panel button",
              "expected": "the widget glows blue"}
FIRMWARE = {"name": "fw_blink", "kind": "functional_vector",
            "stimulus": "blink.hex", "expected": "GPIO 輸出規則性 toggle"}
CONDITIONAL = {"name": "opt_m_mul", "kind": "functional_vector",
               "stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS",
               "applies_when": {"option": "M", "stated": "(若 Plugin 選 M)",
                                "source": "input/docs/L7.md"}}
UNGROUNDED = {"widget_glow", "fw_blink", "opt_m_mul"}


def _die(tmp_path, extra, decl=None):
    proj = base._mk_project(tmp_path, die=True, cases=base.CASES + extra)
    if decl is not None:
        base._write(proj / "plugin_output" / "declaration.json",
                    json.dumps(decl))
    return proj


def test_an_unmeasured_declared_case_blocks_step5(tmp_path, arith_class,
                                                  capsys):
    """RED on the base: 3 executed + 1 no-oracle row read PASS (rc 0)."""
    proj = _die(tmp_path, [UNMEASURED])
    rec = _fsf().generate(proj, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    by = {c["name"]: c for c in rec["cases"]}
    assert by["widget_glow"]["state"] == "no_oracle"
    assert rec["counts"]["executed"] == 3 and rec["counts"]["failed"] == 0
    assert rec["verdict"] == "NOT_MEASURED", rec["reason"]
    assert "R-0929-STEP5-BAR" in rec["reason"] and "widget_glow" in rec["reason"]
    assert by["widget_glow"]["step5_disposition"]["blocking"] is True
    rc, res, out = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2, res
    assert res["rule"] == "step5_bar_unmeasured_cases"
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


def test_a_conditional_row_is_demanded_only_when_the_design_selects_it(
        tmp_path, arith_class, capsys):
    na = _die(tmp_path / "na", [CONDITIONAL], decl={"isa_extensions": ["I"]})
    rec = _fsf().generate(na, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    assert rec["verdict"] == "PASS", rec["reason"]
    assert {d["case"]: d["disposition"] for d in rec["step5_bar"][
        "dispositions"]}["opt_m_mul"] == "design_declared_na"
    rc, _res, _ = base._run_gate(na, tmp_path / "na", capsys)
    assert rc == 0
    # KNOWN-NEGATIVE: the design selected M -> the row is demanded, and blocks
    sel = _die(tmp_path / "sel", [CONDITIONAL],
               decl={"isa_extensions": ["I", "M"]})
    rec = _fsf().generate(sel, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    assert rec["verdict"] == "NOT_MEASURED"
    rc, res, _ = base._run_gate(sel, tmp_path / "sel", capsys)
    assert rc == 2 and res["rule"] == "step5_bar_unmeasured_cases"


def test_the_gate_rederives_a_disposition_the_record_relabelled(
        tmp_path, arith_class, capsys):
    proj = _die(tmp_path, [UNMEASURED])
    rec = _fsf().generate(proj, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    c = next(c for c in rec["cases"] if c["name"] == "widget_glow")
    c["state"] = "excluded"                      # a coverage-figure label
    c.pop("step5_disposition")
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "step5_bar_unmeasured_cases", res


def test_the_gate_refuses_a_record_that_omits_a_declared_case(
        tmp_path, arith_class, capsys):
    proj = _die(tmp_path, [UNMEASURED])
    rec = _fsf().generate(proj, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    rec["cases"] = [c for c in rec["cases"] if c["name"] != "widget_glow"]
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent"
    assert "widget_glow" in res["rationale"]


# ===========================================================================
# B. ISA credit and the CPU data-path case — a real simulation
# ===========================================================================
CPU = "mini_cpu"
CPU_V = """// synthetic byte-SRAM RV32I-subset core (ADDI/ADD/SW/LW/JAL)
module mini_cpu #(parameter memsize = 256) (
  input clk, input rst,
  output reg [7:0] o_mem_raddr, output reg [7:0] o_mem_waddr,
  output reg [7:0] o_mem_wdata, input [7:0] i_mem_rdata,
  output reg o_mem_we, output reg o_mem_ren);
  reg [31:0] x [0:31]; reg [31:0] pc, ir, ld; reg [3:0] st; reg [2:0] n;
  wire [6:0] op = ir[6:0];
  wire [4:0] rd = ir[11:7], rs1 = ir[19:15], rs2 = ir[24:20];
  wire [31:0] ii = {{20{ir[31]}}, ir[31:20]};
  wire [31:0] si = {{20{ir[31]}}, ir[31:25], ir[11:7]};
  wire [31:0] ji = {{12{ir[31]}}, ir[19:12], ir[20], ir[30:21], 1'b0};
  wire [31:0] r1 = rs1 ? x[rs1] : 0, r2 = rs2 ? x[rs2] : 0;
  wire [31:0] ea = r1 + (op == 7'h23 ? si : ii);
  always @(posedge clk) begin
    o_mem_we <= 0; o_mem_ren <= 0;
    if (rst) begin pc <= 0; st <= 0; n <= 0; o_mem_wdata <= 0;
                   o_mem_raddr <= 0; o_mem_waddr <= 0; end
    else case (st)
      0: begin o_mem_ren <= 1; o_mem_raddr <= pc + n; st <= 1; end
      1: st <= 2;
      2: begin ir[8*n +: 8] <= i_mem_rdata;
               if (n == 3) begin n <= 0; st <= 3; end
               else begin n <= n + 1; st <= 0; end end
      3: case (op)
           7'h13: begin if (rd) x[rd] <= r1 + ii; pc <= pc + 4; st <= 0; end
           7'h33: begin if (rd) x[rd] <= r1 + r2; pc <= pc + 4; st <= 0; end
           7'h6f: begin if (rd) x[rd] <= pc + 4; pc <= pc + ji; st <= 0; end
           7'h23: begin st <= 4; n <= 0; end
           7'h03: begin st <= 5; n <= 0; end
           default: st <= 15;
         endcase
      4: begin o_mem_we <= 1; o_mem_waddr <= ea + n; o_mem_wdata <= r2[8*n +: 8];
               if (n == 3) begin n <= 0; pc <= pc + 4; st <= 0; end
               else n <= n + 1; end
      5: begin o_mem_ren <= 1; o_mem_raddr <= ea + n; st <= 6; end
      6: st <= 7;
      7: begin ld[8*n +: 8] <= i_mem_rdata;
               if (n == 3) begin n <= 0; st <= 8; end
               else begin n <= n + 1; st <= 5; end end
      8: begin if (rd) x[rd] <= LOADVAL; pc <= pc + 4; st <= 0; end
      default: ;
    endcase
  end
endmodule
"""
#: the design as written, and a known-broken load path
GOOD_LOAD, BROKEN_LOAD = "ld", "32'd0"
CPU_PORTS = [("input", 1, "clk"), ("input", 1, "rst"),
             ("output", 8, "o_mem_raddr"), ("output", 8, "o_mem_waddr"),
             ("output", 8, "o_mem_wdata"), ("input", 8, "i_mem_rdata"),
             ("output", 1, "o_mem_we"), ("output", 1, "o_mem_ren")]
PAD_MODELS = {"/pdk/io/verilog/io.v":
              "module PADIN(input PAD, output Y); assign Y = PAD; endmodule\n"
              "module PADOUT(input A, output PAD); assign PAD = A; endmodule\n"}
DECL = {"top_module": CPU, "isa_extensions": ["I"], "memsize_bytes": 256,
        "reset_polarity": "active_high", "clock_port_name": "clk",
        "core_parameters": {"memsize": 256, "RESET_PC": "0x00000000"},
        "sram_interface": {"read_address": "o_mem_raddr",
                           "write_address": "o_mem_waddr",
                           "write_data": "o_mem_wdata",
                           "read_data": "i_mem_rdata",
                           "write_enable": "o_mem_we",
                           "read_enable": "o_mem_ren",
                           "read_latency_cycles": 1}}
CPU_CASES = [
    {"name": "boot_fetch", "kind": "functional_vector",
     "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
     "expected": "N ≤ 10 cycle"},
    {"name": "rv32i_all", "kind": "functional_vector",
     "stimulus": "整套 RV32I 指令單元測試", "expected": "100% PASS"},
]


def _chip_top(ports=None, override: str = "") -> str:
    ports = CPU_PORTS if ports is None else ports
    lines = ["module chip_top ("]
    decls = []
    for d, w, n in ports:
        rng = f" [{w - 1}:0]" if w > 1 else ""
        decls.append(f"    {d}{rng} {n}")
    lines.append(",\n".join(decls + ["    inout VDD", "    inout VSS"]))
    lines.append(");")
    conns = []
    for d, w, n in ports:
        rng = f" [{w - 1}:0]" if w > 1 else ""
        lines.append(f"    wire{rng} {n}__core;")
        for b in range(w):
            sfx = f"[{b}]" if w > 1 else ""
            if d == "input":
                lines.append(f"    PADIN u_pad_{n}_{b} (.PAD({n}{sfx}), "
                             f".Y({n}__core{sfx}));")
            else:
                lines.append(f"    PADOUT u_pad_{n}_{b} (.A({n}__core{sfx}), "
                             f".PAD({n}{sfx}));")
        conns.append(f".{n}({n}__core)")
    lines.append(f"    {CPU} {override}u_core ({', '.join(conns)});")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def _cpu_project(tmp_path: Path, *, decl=DECL, load=GOOD_LOAD,
                 cases=CPU_CASES, rtl=None, ports=None,
                 override: str = "") -> Path:
    proj = tmp_path / "cpu"
    gd = proj / "phase1" / "generated_docs"
    w = base._write
    w(gd / "L1_DATASHEET.json", json.dumps({"isa_base": ["RV32I"]}))
    w(gd / "L2_FRS.json", json.dumps({"function": "a small RV32I core"}))
    w(gd / "L3_CMD_PROTOCOL.json", json.dumps({"opcodes": []}))
    w(gd / "L9_INTEGRATION_SPEC.json", json.dumps({"top_module": CPU}))
    w(gd / "L10_TEST_CASES.json",
      json.dumps({"test_cases": cases}, ensure_ascii=False))
    w(proj / "phase2" / "stage1" / "rtl" / f"{CPU}.v",
      (rtl or CPU_V).replace("LOADVAL", load))
    w(proj / "plugin_output" / "declaration.json", json.dumps(decl))
    w(proj / "input" / "submission_template" / "SELF_TAPEOUT.txt", "self\n")
    w(proj / "phase3" / "stage3" / "pnr" / "chip_top_io.v",
      _chip_top(ports, override))
    w(proj / "reports" / "phase3" / "io_pad_chip_top.json", json.dumps(
        {"verdict": "WROTE", "chip_top_module": "chip_top",
         "core_module": CPU,
         "chip_top_verilog": "phase3/stage3/pnr/chip_top_io.v"}))
    return proj


def _require_iverilog():
    missing = [t for t in ("iverilog", "vvp") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so the data-path program cannot be "
            f"simulated here",
            "tools/ci/run_suite_in_eda_image.sh -- "
            "programs/tests/test_r0929_step5_bar_datapath.py")


@pytest.fixture
def cpu_env(monkeypatch):
    """processor class + an ISA-suite credit for `rv32i_all` (reader stood in)."""
    _require_iverilog()
    import testbench_gen as tbg
    import _l10_execution as l10x
    monkeypatch.setattr(tbg, "_detect_ic_class",
                        lambda project: "processor_cpu")

    def credit(project, case_id, case=None):
        if case_id != "rv32i_all":
            return None, None
        return {"case": case_id, "sentence": "core ISA conformance at test "
                "memsize=2097152 (delivered 256): suite 38/38"}, None
    monkeypatch.setattr(l10x, "isa_conformance_credit", credit)


def _gen(proj):
    return _fsf().generate(proj, None,
                           model_resolver=lambda p, u, c: (dict(PAD_MODELS),
                                                           "fixture models"))


def test_isa_credit_counts_with_a_datapath_program_through_the_chip_top(
        tmp_path, cpu_env, capsys):
    """RED on the base: no data-path case exists (`cpu_datapath` absent)."""
    proj = _cpu_project(tmp_path)
    rec = _gen(proj)
    dp = rec["cpu_datapath"]
    assert dp["state"] == "passed", dp
    assert dp["checks"] == {"passed": 5, "total": 5}
    assert dp["expected_words"] == ["0x0000000c", "0x00000011"]
    assert dp["delivered_memsize_bytes"] == 256
    tb = (proj / dp["tb"]).read_text()
    assert _fsf().instance_count(tb, "chip_top") == 1
    assert _fsf().instance_count(tb, CPU) == 0
    # the program is an IMAGE the flow assembled, not words in the testbench
    assert "$readmemh(\"cpu_datapath_program.hex\"" in tb
    assert "00500093" not in tb
    assert (proj / dp["hex"]).read_text().splitlines()[1:5] == [
        "93", "00", "50", "00"]
    by = {c["name"]: c for c in rec["cases"]}
    assert by["boot_fetch"]["state"] == "passed"
    assert by["rv32i_all"]["step5_disposition"]["disposition"] == \
        "isa_credited"
    assert rec["verdict"] == "PASS", rec["reason"]
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 0, res
    assert res["cpu_datapath"]["state"] == "passed"
    assert [d["disposition"] for d in res["step5_dispositions"]] == [
        "isa_credited"]


def test_a_firmware_row_whose_image_is_absent_is_excluded_by_ruling(
        tmp_path, cpu_env, capsys):
    """KNOWN-POSITIVE of (b): the owner's input_absent exclusion, beside a
    credited ISA row and a data-path program that passed."""
    proj = _cpu_project(tmp_path, cases=CPU_CASES + [FIRMWARE])
    rec = _gen(proj)
    assert rec["verdict"] == "PASS", rec["reason"]
    d = next(c for c in rec["cases"] if c["name"] == "fw_blink")[
        "step5_disposition"]
    assert d["disposition"] == "excluded_by_ruling"
    assert d["ruling"] == "R-0929-OWNER-SUB-ACCEPT (2)"
    assert d["record"]["missing_from_input"] == ["blink.hex"]
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 0, res
    assert sorted(x["disposition"] for x in res["step5_dispositions"]) == [
        "excluded_by_ruling", "isa_credited"]


def test_isa_credit_without_a_datapath_case_does_not_count(
        tmp_path, cpu_env, capsys):
    """RED on the base: boot_fetch executed, rv32i_all no-oracle -> PASS."""
    decl = {k: v for k, v in DECL.items() if k != "sram_interface"}
    proj = _cpu_project(tmp_path, decl=decl)
    rec = _gen(proj)
    assert rec["cpu_datapath"]["state"] == "no_oracle"
    assert "sram_interface" in rec["cpu_datapath"]["reason"]
    assert rec["verdict"] == "NOT_MEASURED", rec["reason"]
    d = rec["step5_bar"]["dispositions"][0]
    assert d["case"] == "rv32i_all" and d["blocking"] is True
    assert "R-0929-STEP5-BAR" in d["reason"]
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "step5_bar_unmeasured_cases", res


def test_a_broken_load_path_fails_step5(tmp_path, cpu_env, capsys):
    """RED on the base: the same design read PASS (the load path was never
    exercised by any case)."""
    proj = _cpu_project(tmp_path, load=BROKEN_LOAD)
    rec = _gen(proj)
    dp = rec["cpu_datapath"]
    assert dp["state"] == "failed", dp
    assert dp["checks"] == {"passed": 4, "total": 5}
    assert rec["verdict"] == "FAIL"
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 1 and res["rule"] == "cpu_datapath_program_mismatch", res


@pytest.mark.parametrize("tamper", ["hex", "tb"])
def test_the_gate_rebuilds_the_program_rather_than_trusting_it(
        tmp_path, cpu_env, capsys, tamper):
    proj = _cpu_project(tmp_path)
    rec = _gen(proj)
    fsf = _fsf()
    dp = rec["cpu_datapath"]
    f = proj / dp[tamper]
    if tamper == "hex":            # a different program, re-sealed
        f.write_text(f.read_text().replace("\n93\n", "\n13\n", 1))
        dp["hex_sha256"] = fsf.sha256_file(f)
    else:                          # a weaker expectation, re-sealed
        f.write_text(f.read_text().replace("EXP1 = 32'h00000011",
                                           "EXP1 = 32'h00000000"))
        dp["tb_sha256"] = fsf.sha256_file(f)
    fsf.record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent", res
    assert "cpu_datapath_program" in res["rationale"]


# ===========================================================================
# C. THE PROGRAM BUILDER — encodings, the reference answer, refusals
# ===========================================================================
def test_encodings_are_the_public_rv32i_words():
    c = _cdp()
    assert c.enc_addi(1, 0, 5) == 0x00500093
    assert c.enc_add(3, 1, 31) == 0x01F081B3
    assert c.enc_sw(3, 0, 0x100) == 0x10302023
    assert c.enc_lw(4, 0, 0x30) == 0x03002203
    assert c.enc_jal(0, 0) == 0x0000006F


def test_the_reference_answer_needs_the_loaded_value():
    c = _cdp()
    prog = c.assemble(0x30)
    mem = bytearray([c.FILL_BYTE] * 256)
    for i, (w, _t) in enumerate(prog):
        mem[4 * i:4 * i + 4] = w.to_bytes(4, "little")
    after, regs, _ = c.reference_execute(mem, 0)
    assert int.from_bytes(after[0x30:0x34], "little") == 12
    assert int.from_bytes(after[0x34:0x38], "little") == 17
    assert regs[4] == 12
    mem[4 * 7:4 * 7 + 4] = (0x00000073).to_bytes(4, "little")   # ecall
    with pytest.raises(ValueError):
        c.reference_execute(mem, 0)


def _ports():
    return [(d, f"[{w - 1}:0]" if w > 1 else "", n) for d, w, n in CPU_PORTS]


@pytest.mark.parametrize("mutate,needle", [
    (lambda p, d: (p / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"isa_base": ["RV64I"]})), "RV64I"),
    (lambda p, d: (p / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        "{}"), "no ISA base"),
    (lambda p, d: d.pop("sram_interface"), "sram_interface"),
    (lambda p, d: d["sram_interface"].pop("read_latency_cycles"),
     "read latency"),
    (lambda p, d: d.pop("memsize_bytes"), "memsize_bytes"),
    (lambda p, d: d.pop("core_parameters"), "reset vector"),
    (lambda p, d: d["sram_interface"].update(read_data="i_nope"), "i_nope"),
    (lambda p, d: d["sram_interface"].update(rf_reserved_high_bytes=240),
     "fit"),
])
def test_the_builder_refuses_what_the_input_does_not_state(tmp_path, mutate,
                                                           needle):
    proj = _cpu_project(tmp_path)
    decl = json.loads(json.dumps(DECL))
    mutate(proj, decl)
    (proj / "plugin_output" / "declaration.json").write_text(json.dumps(decl))
    built, why = _cdp().build(proj, CPU, _ports())
    assert built is None and needle in why, why


def test_the_builder_is_deterministic_and_sized_to_the_delivered_memory(
        tmp_path):
    proj = _cpu_project(tmp_path)
    a, _ = _cdp().build(proj, CPU, _ports())
    b, _ = _cdp().build(proj, CPU, _ports())
    assert a["tb_text"] == b["tb_text"] and a["hex_text"] == b["hex_text"]
    assert "localparam integer MEMSIZE = 256;" in a["tb_text"]
    assert f"{CPU} u_dut (" in a["tb_text"] and f"{CPU} #" not in a["tb_text"]


# ===========================================================================
# D. REVIEW WAVE 58 (S5DP) — each finding pinned
# ===========================================================================
def _run(proj):
    rec = _gen(proj)
    dp = rec["cpu_datapath"]
    log = (proj / dp["run_log"]).read_text() if dp.get("run_log") else ""
    return rec, dp, log


# ---- MAJOR: a bare percentage is not a coverage figure by itself ----------
def test_a_bare_percentage_row_that_never_ran_blocks_step5(tmp_path, cpu_env,
                                                           capsys):
    """RED on 381297e80: an ISA row written '100%' (no coverage word), never
    run and never credited (no data-path program), read PASS / gate rc 0."""
    decl = {k: v for k, v in DECL.items() if k != "sram_interface"}
    rows = [CPU_CASES[0], {"name": "rv32i_suite", "kind": "functional_vector",
                           "stimulus": "整套 RV32I 指令單元測試",
                           "expected": "100%"}]
    proj = _cpu_project(tmp_path, decl=decl, cases=rows)
    rec = _gen(proj)
    by = {c["name"]: c for c in rec["cases"]}
    assert by["rv32i_suite"]["state"] == "no_oracle"
    assert rec["verdict"] == "NOT_MEASURED", rec["reason"]
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "step5_bar_unmeasured_cases", res


def test_a_row_naming_coverage_is_listed_with_its_basis(tmp_path, arith_class,
                                                        capsys):
    """KNOWN-POSITIVE: the landed spm-shaped row (`toggle_branch_coverage`,
    '≥ 95%') is still exempt, and now LISTED with the text that names it."""
    proj = base._mk_project(tmp_path, die=True)
    rec = _fsf().generate(proj, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    assert rec["verdict"] == "PASS", rec["reason"]
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 0, res
    (d,) = res["step5_dispositions"]
    assert d["case"] == "toggle_branch_coverage"
    assert d["disposition"] == "coverage_figure_not_a_case"
    assert d["basis"]["names_coverage_in"] == "name"
    fsf = _fsf()
    assert fsf.coverage_figure_exemption({"name": "c", "expected": "100%"}) \
        is None
    assert fsf.coverage_figure_exemption(
        {"name": "c", "stimulus": "line 覆蓋率", "expected": "≥ 90%"})


# ---- (b) the data-path record cannot be relabelled ------------------------
@pytest.mark.parametrize("label", ["errored", "no_oracle"])
def test_a_failed_datapath_cannot_be_relabelled(tmp_path, cpu_env, capsys,
                                                label):
    """RED on 381297e80: the relabelled record read gate rc 0 PASS."""
    rows = [CPU_CASES[0]]
    proj = _cpu_project(tmp_path, load=BROKEN_LOAD, cases=rows)
    rec = _gen(proj)
    assert rec["cpu_datapath"]["state"] == "failed"
    rec["cpu_datapath"]["state"] = label
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent", res
    assert "cpu_datapath_program" in res["rationale"]


def test_a_datapath_record_cannot_claim_no_program_when_one_builds(
        tmp_path, cpu_env, capsys):
    rows = [CPU_CASES[0]]
    proj = _cpu_project(tmp_path, load=BROKEN_LOAD, cases=rows)
    rec = _gen(proj)
    rec["cpu_datapath"] = {"name": "cpu_datapath_program",
                           "state": "no_oracle", "reason": "none"}
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and "builds from the design input now" in \
        res["rationale"], res


# ---- (c) the delivered memory is the one the top elaborates ---------------
def test_a_memory_the_top_does_not_elaborate_is_refused(tmp_path):
    """RED on 381297e80: memsize_bytes alone decided the TB memory."""
    big = CPU_V.replace("parameter memsize = 256", "parameter memsize = 2048")
    proj = _cpu_project(tmp_path, rtl=big)
    built, why = _cdp().build(proj, CPU, _ports())
    assert built is None and "memsize=2048" in why and "RTL default" in why
    decl = json.loads(json.dumps(DECL))
    decl["core_parameters"]["memsize"] = 512
    (proj / "plugin_output/declaration.json").write_text(json.dumps(decl))
    built, why = _cdp().build(proj, CPU, _ports())
    assert built is None and "core_parameters memsize=512" in why


def test_the_chip_tops_parameter_override_is_what_counts(tmp_path, cpu_env):
    proj = _cpu_project(tmp_path, override="#(.memsize(512)) ")
    rec = _gen(proj)
    dp = rec["cpu_datapath"]
    assert dp["state"] == "no_oracle", dp
    assert "memsize=512" in dp["reason"] and "override" in dp["reason"]
    ok, _ = _cdp().build(proj, CPU, _ports(), top_text=_chip_top())
    assert ok["facts"]["memory_parameter"]["parameter"][0]["elaborated"] == 256


# ---- (d) each data-path check has a design that fails it ------------------
STRAY_V = CPU_V.replace(
    "if (n == 3) begin n <= 0; pc <= pc + 4; st <= 0; end\n"
    "               else n <= n + 1; end",
    "if (n == 3) begin n <= 0; pc <= pc + 4; st <= 9; end\n"
    "               else n <= n + 1; end\n"
    "      9: begin o_mem_we <= 1; o_mem_waddr <= 8'h80; o_mem_wdata <= 8'h5a;"
    " st <= 0; end")
ONE_LANE_V = CPU_V.replace("4: begin o_mem_we <= 1;",
                           "4: begin o_mem_we <= (n == 0);")
NO_REN_V = (CPU_V.replace("output reg o_mem_we, output reg o_mem_ren);",
                          "output reg o_mem_we);")
            .replace(" o_mem_ren <= 0;", "").replace("o_mem_ren <= 1; ", ""))
NO_REN_STUCK_V = NO_REN_V.replace("1: st <= 2;", "1: st <= 1;")
NO_REN_PORTS = [p for p in CPU_PORTS if p[2] != "o_mem_ren"]
NO_REN_DECL = json.loads(json.dumps(DECL))
NO_REN_DECL["sram_interface"].pop("read_enable")


def test_design_variants_are_well_formed():
    for v in (STRAY_V, ONE_LANE_V, NO_REN_V, NO_REN_STUCK_V):
        assert v != CPU_V
    assert "o_mem_ren" not in NO_REN_V


def test_write_discipline_catches_a_stray_store(tmp_path, cpu_env):
    rec, dp, log = _run(_cpu_project(tmp_path, rtl=STRAY_V))
    assert dp["state"] == "failed" and dp["checks"] == {"passed": 4,
                                                         "total": 5}
    assert "DATAPATH_CHECK write_discipline MISS (stray=2 " in log
    assert rec["verdict"] == "FAIL"


def test_byte_lanes_written_catches_a_one_lane_store(tmp_path, cpu_env):
    _rec, dp, log = _run(_cpu_project(tmp_path, rtl=ONE_LANE_V))
    assert dp["state"] == "failed"
    assert "DATAPATH_CHECK byte_lanes_written MISS (00010001)" in log
    assert "DATAPATH_CHECK reset_vector_fetch PASS" in log
    assert "DATAPATH_CHECK write_discipline PASS" in log
    assert dp["checks"] == {"passed": 2, "total": 5}


def test_without_a_read_enable_the_program_still_runs_and_passes(tmp_path,
                                                                 cpu_env):
    """KNOWN-POSITIVE of the no-read-enable path: reads every cycle."""
    _rec, dp, log = _run(_cpu_project(tmp_path, rtl=NO_REN_V,
                                      ports=NO_REN_PORTS, decl=NO_REN_DECL))
    assert "wire ren = 1'b1;" in (tmp_path / "cpu" / dp["tb"]).read_text()
    assert dp["state"] == "passed", log[-600:]
    assert "32 of 32 image bytes" in log


def test_an_idle_read_address_at_the_reset_vector_is_not_a_fetch(tmp_path,
                                                                  cpu_env):
    """RED on 381297e80: with no read enable declared, the stalled core's read
    address sits at the reset vector and reset_vector_fetch read PASS."""
    _rec, dp, log = _run(_cpu_project(tmp_path, rtl=NO_REN_STUCK_V,
                                      ports=NO_REN_PORTS, decl=NO_REN_DECL))
    assert dp["state"] == "failed"
    assert "DATAPATH_CHECK reset_vector_fetch MISS (1 of 32 image bytes" in log
    assert dp["checks"] == {"passed": 1, "total": 5}


# ---- latency-0 continuous reads: the SAME native producer and consumer ----
def _memory_timed_cpu(latency, with_ren, rtl=CPU_V):
    """Neutral CPU timing matched to the stated memory protocol, never a TB
    marker generator. It executes the assembled instructions and byte stores.
    The one/two-clock variants preserve the existing synchronous protocol."""
    if latency == 0 and with_ren:
        rtl = (rtl.replace("1: st <= 2;", "")
               .replace("2: begin ir[", "1: begin ir[")
               .replace("6: st <= 7;", "")
               .replace("7: begin ld[", "6: begin ld["))
    elif latency == 2:
        rtl = (rtl.replace("1: st <= 2;", "1: st <= 9;\n      9: st <= 2;")
               .replace("6: st <= 7;", "6: st <= 10;\n      10: st <= 7;"))
    if not with_ren:
        rtl = (rtl.replace("output reg o_mem_we, output reg o_mem_ren);",
                           "output reg o_mem_we);")
               .replace(" o_mem_ren <= 0;", "")
               .replace("o_mem_ren <= 1; ", ""))
    return rtl


def _native_datapath(tmp_path, latency=0, with_ren=False, rtl=CPU_V,
                     load=GOOD_LOAD, ports=None):
    """Actual owner -> Icarus -> actual re-deriving owner; no dispatch,
    transcript, score, input-reader or ISA-credit stand-in."""
    _require_iverilog()
    import testbench_gen as tbg
    import bit_level_full_stack_tb_check as gate
    decl = json.loads(json.dumps(DECL))
    decl["sram_interface"]["read_latency_cycles"] = latency
    if not with_ren:
        decl["sram_interface"].pop("read_enable")
    ports = (CPU_PORTS if with_ren else NO_REN_PORTS) if ports is None else ports
    proj = _cpu_project(tmp_path, decl=decl, load=load, ports=ports,
                        rtl=_memory_timed_cpu(latency, with_ren, rtl))
    fsf = _fsf()
    top = fsf.required_full_stack_top(proj, "DIE")
    mod, parsed, why = tbg.resolve_dut(proj, CPU)
    assert mod == CPU, why
    models = base._write(proj / "models" / "pads.v",
                         next(iter(PAD_MODELS.values())))
    sources = [proj / "phase2/stage1/rtl" / f"{CPU}.v",
               proj / top["source"], models]
    fdir = fsf.functional_dir(proj)
    fdir.mkdir(parents=True, exist_ok=True)
    dp = fsf._datapath_case(proj, mod, parsed, top, sources, fdir,
                            fdir / "run", fsf.default_dispatch, None, set())
    problems = []
    got = gate._verify_datapath(proj, {fsf.DATAPATH_KEY: dp}, top, problems)
    assert not problems, problems
    assert got["state"] == dp["state"]
    log = (proj / dp["run_log"]).read_text() if dp.get("run_log") else ""
    return proj, dp, got, log


@pytest.mark.parametrize("latency", [0, 1, 2])
@pytest.mark.parametrize("with_ren", [False, True])
def test_declared_memory_timing_runs_through_native_datapath_and_reader(
        tmp_path, latency, with_ren):
    proj, dp, got, log = _native_datapath(tmp_path, latency, with_ren)
    assert dp["state"] == "passed", dp
    assert got["checks"] == {"passed": 5, "total": 5}
    assert got["delivered_memsize_bytes"] == 256
    assert got["expected_words"] == ["0x0000000c", "0x00000011"]
    assert "32 of 32 image bytes" in log
    text = (proj / dp["tb"]).read_text()
    assert _fsf().instance_count(text, "chip_top") == 1
    assert _fsf().instance_count(text, CPU) == 0
    if latency == 0:
        assert "rpipe" not in text
    else:
        assert "rpipe[LAT-1]" in text


@pytest.mark.parametrize("kind,rtl,load,needle", [
    ("wrong_store", CPU_V.replace("r2[8*n +: 8]", "(r2[8*n +: 8] ^ 8'h01)"),
     GOOD_LOAD, "DATAPATH_CHECK store_word MISS"),
    ("missing_lane", ONE_LANE_V, GOOD_LOAD,
     "DATAPATH_CHECK byte_lanes_written MISS"),
    ("load_corruption", CPU_V, BROKEN_LOAD,
     "DATAPATH_CHECK load_store_word MISS"),
    ("stray_write", STRAY_V, GOOD_LOAD,
     "DATAPATH_CHECK write_discipline MISS (stray=2"),
    ("unknown_write_enable", CPU_V.replace("o_mem_we <= 1;",
                                           "o_mem_we <= 1'bx;"),
     GOOD_LOAD, "DATAPATH_CHECK write_discipline MISS"),
    ("unknown_enabled_write_data", CPU_V.replace("r2[8*n +: 8]", "8'hxx"),
     GOOD_LOAD, "DATAPATH_CHECK write_discipline MISS"),
], ids=["wrong_store", "missing_lane", "load_corruption", "stray_write",
        "unknown_write_enable", "unknown_enabled_write_data"])
def test_async_native_datapath_keeps_each_write_and_load_negative(
        tmp_path, kind, rtl, load, needle):
    _proj, dp, got, log = _native_datapath(tmp_path, rtl=rtl, load=load)
    assert dp["state"] == "failed", (kind, dp)
    assert got["checks"]["total"] == 5 and got["checks"]["passed"] < 5
    assert needle in log, log[-1600:]
    assert "DATAPATH_CHECK reset_vector_fetch PASS" in log


def test_async_native_datapath_keeps_out_of_range_write_negative(tmp_path):
    ports = [(d, 9 if n == "o_mem_waddr" else w, n)
             for d, w, n in NO_REN_PORTS]
    rtl = STRAY_V.replace("output reg [7:0] o_mem_waddr",
                          "output reg [8:0] o_mem_waddr")
    # raddr and waddr share a declaration in the neutral source.
    rtl = rtl.replace("output reg [7:0] o_mem_raddr, output reg [7:0] o_mem_waddr",
                      "output reg [7:0] o_mem_raddr, output reg [8:0] o_mem_waddr")
    rtl = rtl.replace("o_mem_waddr <= 8'h80", "o_mem_waddr <= 9'h100")
    _proj, dp, got, log = _native_datapath(tmp_path, rtl=rtl, ports=ports)
    assert dp["state"] == got["state"] == "failed", dp
    assert "DATAPATH_CHECK write_discipline MISS (stray=0 oob=2" in log


def test_async_native_datapath_keeps_idle_address_fetch_negative(tmp_path):
    _proj, dp, got, log = _native_datapath(tmp_path, rtl=NO_REN_STUCK_V)
    assert dp["state"] == got["state"] == "failed", dp
    assert "DATAPATH_CHECK reset_vector_fetch MISS (1 of 32 image bytes" in log


def test_async_native_datapath_keeps_unknown_read_enable_negative(tmp_path):
    rtl = CPU_V.replace("o_mem_ren <= 1;", "o_mem_ren <= 1'bx;")
    _proj, dp, got, log = _native_datapath(tmp_path, with_ren=True, rtl=rtl)
    assert dp["state"] == got["state"] == "failed", dp
    assert "DATAPATH_CHECK reset_vector_fetch MISS" in log
    assert "DATAPATH_CHECK write_discipline MISS" in log


@pytest.mark.parametrize("latency", [-1, None, True])
def test_invalid_or_unstated_latency_still_refuses(latency):
    decl = json.loads(json.dumps(DECL))
    decl["sram_interface"]["read_latency_cycles"] = latency
    got, why = _cdp().sram_roles(decl)
    assert got is None and "read latency" in why
