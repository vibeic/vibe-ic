"""ORGANIC batch — Cluster D: clock/derived/FPGA checker fixes.

#569 derived_clock clock-usage confirmation + clock_plan comment-strip parity
#572 waiver step-id↔name cross-check / derived_clock dir --sdc / l10_tb paths
#558 fpga_burn JTAG-absent → SKIP (not FAIL)
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import derived_clock_sdc_required_check as DC   # noqa: E402
import clock_plan_check as CP                   # noqa: E402
import flow_compliance_check as FC              # noqa: E402
import design_one_shot_runner as P2             # noqa: E402
import l10_tb_conformance_check as L10          # noqa: E402


# ── #569 — clock-usage confirmation ────────────────────────────────────────
def test_569_shadow_toggle_no_consumer_passes(tmp_path):
    (tmp_path / "a.sv").write_text(
        "module m(input clk_i, output reg q);\n"
        "  reg phase_q;\n"
        "  always @(posedge clk_i) phase_q <= ~phase_q;\n"
        "  always @(posedge clk_i) q <= phase_q;\n"
        "endmodule\n")
    assert DC.main([str(tmp_path)]) == 0  # PASS: phase_q clocks nothing


def test_569_real_divided_clock_with_consumer_still_fails(tmp_path):
    (tmp_path / "b.sv").write_text(
        "module n(input clk_i, output reg o);\n"
        "  reg dclk;\n"
        "  always @(posedge clk_i) dclk <= ~dclk;\n"
        "  always @(posedge dclk) o <= ~o;\n"   # dclk IS used as a clock
        "endmodule\n")
    # NEGATIVE no-leak: a real derived clock with a consumer + no SDC → FAIL
    assert DC.main([str(tmp_path)]) == 1


def test_569_clock_pin_connection_counts_as_consumer(tmp_path):
    (tmp_path / "c.sv").write_text(
        "module top(input clk_i);\n"
        "  reg dclk;\n"
        "  always @(posedge clk_i) dclk <= ~dclk;\n"
        "  sub u_sub(.clk(dclk), .d(1'b0));\n"
        "endmodule\n")
    assert DC.main([str(tmp_path)]) == 1  # dclk drives a clock pin → required


def test_569_clock_plan_comment_strip(tmp_path):
    # a commented-out create_generated_clock must NOT be parsed as an active
    # SDC clock (parity with derived_clock's comment-strip).
    sdc = tmp_path / "x.sdc"
    sdc.write_text(
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "# REMOVED: create_generated_clock -name phase_q -divide_by 2 "
        "-source [get_ports clk] [get_pins p/q]\n")
    names, _ = CP._sdc_clock_names([sdc])
    assert "phase_q" not in names
    assert "clk" in names


# ── #569 adversarial-review no-leak regressions ───────────────────────────
def test_569_leak_nonclk_pin_consumer_still_fails(tmp_path):
    # HIGH leak: a divided clock consumed via a non-'clk'-named instance pin
    # (.ck / .phi) must still require SDC.
    (tmp_path / "a.v").write_text(
        "module top(input ext_clk);\n"
        "  reg core_clk;\n"
        "  always @(posedge ext_clk) core_clk <= ~core_clk;\n"
        "  ff u(.ck(core_clk), .d(1'b0));\n"
        "endmodule\n")
    assert DC.main([str(tmp_path)]) == 1


def test_569_leak_assign_alias_consumer_still_fails(tmp_path):
    # HIGH leak: assign gated = core_clk; @(posedge gated) — the divided
    # clock is consumed through an alias and must still require SDC.
    (tmp_path / "b.v").write_text(
        "module top(input ext_clk, output reg outp);\n"
        "  reg core_clk;\n"
        "  always @(posedge ext_clk) core_clk <= ~core_clk;\n"
        "  wire gated;\n"
        "  assign gated = core_clk;\n"
        "  always @(posedge gated) outp <= ~outp;\n"
        "endmodule\n")
    rc = DC.main([str(tmp_path)])
    assert rc == 1


def test_569_leak_output_list_and_init_forms_detected():
    # HIGH leak: find_output_ports must capture every ident in a comma list
    # and tolerate an initializer.
    assert DC.find_output_ports("output logic [1:0] x, y;") == {"x", "y"}
    assert "core_clk" in DC.find_output_ports("output wire core_clk = 0;")


def test_569_exported_divided_clock_in_list_still_fails(tmp_path):
    # the exported (output) divided clock 'y' (2nd in a comma list) must
    # require SDC — the regex fix closes the leak.
    (tmp_path / "c.v").write_text(
        "module m(input ext_clk, output x, output y);\n"
        "  always @(posedge ext_clk) y <= ~y;\n"
        "endmodule\n")
    assert DC.main([str(tmp_path)]) == 1


# ── #572b — derived_clock accepts a DIRECTORY --sdc ────────────────────────
def test_572b_dir_sdc_does_not_crash(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "d.sv").write_text(
        "module n(input clk_i, input d_in, output reg o);\n"
        "  reg dclk;\n"
        "  always @(posedge clk_i) dclk <= ~dclk;\n"
        "  always @(posedge dclk) o <= d_in;\n"  # o is data, not a toggle
        "endmodule\n")
    con = tmp_path / "constraints"
    con.mkdir()
    (con / "c.sdc").write_text(
        "create_generated_clock -name dclk -divide_by 2 "
        "-source [get_ports clk_i] [get_pins dclk_reg/Q]\n")
    # directory --sdc used to raise IsADirectoryError; now rglobs *.sdc
    assert DC.main([str(rtl), "--sdc", str(con)]) == 0


# ── #572a — waiver step-id↔name cross-check ────────────────────────────────
def test_572a_misfiled_waiver_rejected():
    # waiver claims to waive "FPGA final" but the step at this id is GDSII
    msg = FC._waiver_step_name_mismatch(
        {"step_name": "FPGA final", "reason": "x"}, "GDSII sign-off")
    assert msg is not None and "mis-filed" in msg


def test_572a_correct_waiver_accepted():
    # same significant token ('fpga') → accepted (None)
    assert FC._waiver_step_name_mismatch(
        {"step_name": "FPGA final"}, "FPGA final on-board sign-off") is None
    # no step_name declared → opt-in check never fires
    assert FC._waiver_step_name_mismatch({"reason": "x"}, "GDSII") is None


def test_572a_check_step_drops_misfiled_waiver(tmp_path):
    # a step that would be MISSING, mis-waived, must NOT come back WAIVED.
    step = {"id": 37, "name": "GDSII sign-off", "stage": "stage5",
            "required_outputs": ["reports/phase3/never_exists.json"]}
    waivers = {37: {"step_name": "FPGA final", "reason": "no board",
                    "approver": "user"}}
    res = FC.check_step(tmp_path, step, waivers)
    assert res.status != "WAIVED"
    assert any("REJECTED" in r for r in res.reasons)


# ── #572c — l10_tb path fallback ───────────────────────────────────────────
def test_572c_tb_dir_falls_back_to_sim_root(tmp_path, monkeypatch):
    sim = tmp_path / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "tb_top.v").write_text("module tb_top; endmodule\n")
    monkeypatch.chdir(tmp_path)
    # default tb-dir is phase2/stage1/sim/tb (absent); must resolve to sim/
    resolved = L10._resolve_tb_dir("phase2/stage1/sim/tb")
    assert resolved is not None
    assert L10._tb_files_under(Path(resolved))


# ── #558 — fpga_burn JTAG-absent signature ─────────────────────────────────
def test_558_jtag_absent_signature():
    assert P2._jtag_hardware_absent("Error: No JTAG hardware available")
    assert P2._jtag_hardware_absent("jtagconfig\nNo JTAG hardware")
    # a real programming failure on an attached board is NOT the absent sig
    assert not P2._jtag_hardware_absent(
        "Error (213): Programming failed; verify mismatch at addr 0x40")
