"""Phase-3 synth forced `-DSIMULATION` on EVERY RTL read path, which made a
STAGED vendor macro unreachable.

THE DEFECT (reproduced on origin/main @67cc50819 with real yosys 0.67):
`step_synth` hardcoded `-DSIMULATION` on all three read paths
(`read_verilog -sv`, `read_slang`, the `sv2v` pre-pass). The stated intent is
sound — take a behavioural fallback arm instead of an FPGA-only vendor
primitive (an Altera `altsyncram`) that does not exist on an ASIC target.

The unintended consequence: when the project has staged a REAL macro for that
same cell under `input/pdk_local/<vendor>/` (Liberty + LEF + GDS + Verilog
model), the forced define ALSO makes the macro-instantiation arm unreachable.
Synthesis silently takes the behavioural arm and maps a storage macro to
flip-flops. Measured on a 128x8 OTP, synthesising the identical RTL:

    with    -DSIMULATION : 1024 $_DFFE_PN0P_ + 8 $_DFF_PN0_   (volatile flops)
    without -DSIMULATION :    1 OTP128X8_MACRO             (the staged macro)

i.e. a one-time-programmable memory that loses chip ID / serial / trim / lock
bits at power-off — the opposite of the part's function — with nothing in any
report to say which path was taken.

THE FIX: the define is conditional on the GENERAL property "is a real macro
staged for a cell this RTL can only instantiate with the define ABSENT?" —
chip-AGNOSTIC (not OTP, not any vendor). With no macro staged the emitted
commands are BYTE-IDENTICAL to the historical flow, so the behavioural path the
define was added for is preserved. When a macro is staged but cannot be used,
the run says so at ERROR severity instead of falling through silently.

These tests exercise PUBLIC behaviour: the commands `step_synth` actually
emits, and the decision record it reports. `test_e2e_*` closes the loop on real
yosys where available.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import phase3_one_shot_runner as p3
import synth_frontend as sf

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# --- fixture RTL: a storage cell with a behavioural arm and a macro arm -----
RTL_OTP = """\
module otp_mem (
  input clk, input rst_n, input [6:0] addr, input [7:0] wdata,
  input we, output [7:0] rdata
);
`ifdef SIMULATION
  reg [7:0] mem [0:127];
  reg [7:0] rdata_r;
  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (i = 0; i < 128; i = i + 1) mem[i] <= 8'h00;
      rdata_r <= 8'h00;
    end else begin
      if (we) mem[addr] <= wdata;
      rdata_r <= mem[addr];
    end
  end
  assign rdata = rdata_r;
`else
  OTP128X8_MACRO u_otp (.CLK(clk), .A(addr), .DIN(wdata),
                           .WE(we), .Q(rdata));
`endif
endmodule
"""

RTL_TOP = """\
module chip_top (
  input clk, input rst_n, input [6:0] addr, input [7:0] wdata,
  input we, output [7:0] rdata
);
  otp_mem u_otp_mem (.clk(clk), .rst_n(rst_n), .addr(addr),
                     .wdata(wdata), .we(we), .rdata(rdata));
endmodule
"""

MACRO_V = ("module OTP128X8_MACRO (input CLK, input [6:0] A, "
           "input [7:0] DIN, input WE, output [7:0] Q);\nendmodule\n")
MACRO_LIB = ("library (OTP128X8_MACRO_tt) {\n"
             "  cell (OTP128X8_MACRO) {\n    area : 12000.0;\n"
             "    pin(CLK) { direction : input; }\n  }\n}\n")


def _mk_project(tmp_path: Path, ext: str = ".v", stage_macro: bool = False,
                macro_lib: bool = True) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / f"chip_top{ext}").write_text(RTL_TOP)
    (rtl / f"otp_mem{ext}").write_text(RTL_OTP)
    if stage_macro:
        base = proj / "input" / "pdk_local" / "otp_ip"
        (base / "Verilog").mkdir(parents=True)
        (base / "Verilog" / "OTP128X8_MACRO.v").write_text(MACRO_V)
        if macro_lib:
            (base / "lib").mkdir(parents=True)
            (base / "lib" / "OTP128X8_MACRO_tt.lib").write_text(MACRO_LIB)
    return proj


def _run_step_synth(tmp_path: Path, proj: Path, monkeypatch):
    """Drive step_synth with a stubbed container exec and return
    (emitted_commands, StepResult). rc!=0 makes every fallback read path fire,
    so all three define-carrying commands are captured."""
    captured: list[str] = []

    def fake_exec(container, cmd, marker=None, timeout=1800, **_kw):
        captured.append(cmd)
        return 1, "", "stubbed failure"

    monkeypatch.setattr(p3, "_docker_exec", fake_exec)
    monkeypatch.setattr(p3._sf, "resolve_slang_load_prefix",
                        lambda c, e: "")

    lib = tmp_path / "fake.lib"
    lib.write_text("library (fake) { cell (INV) { area : 1.0; } }\n")
    mlibs, mlefs, mgds, mv = p3._discover_local_macros(proj)
    # PdkConfig declares these as `str` (in-container paths) and every
    # production construction site passes a str — `_registry_glob_one` returns
    # Optional[str]. Passing Path here violated that contract and crashed
    # `_synth_dont_use_cells` on `pdk.liberty.split("/")` with
    # AttributeError: 'PosixPath' object has no attribute 'split'.
    pdk = p3.PdkConfig(name="t", liberty=str(lib), tech_lef=str(tmp_path / "t.lef"),
                       cell_lef=str(tmp_path / "c.lef"), cell_gds=str(tmp_path / "c.gds"),
                       site="unit", drc_deck=str(tmp_path / "d.lydrc"),
                       macro_libs=mlibs, macro_lefs=mlefs, macro_gds=mgds,
                       macro_v=mv)
    res = p3.step_synth(proj, "chip_top", pdk, "no-such-container")
    return captured, res


# ---------------------------------------------------------------------------
# THE REGRESSION THIS FIX COULD CAUSE: a design with no staged macro must
# behave EXACTLY as before. These are the byte-identical pins.
# ---------------------------------------------------------------------------

def test_no_macro_staged_keeps_simulation_define_on_read_verilog(
        tmp_path, monkeypatch):
    proj = _mk_project(tmp_path, ext=".v", stage_macro=False)
    cmds, _ = _run_step_synth(tmp_path, proj, monkeypatch)
    blob = "\n".join(cmds)
    assert "read_verilog -sv -DSIMULATION " in blob, (
        "the behavioural fallback arm must still be selected when NO macro is "
        f"staged — the Altera-primitive problem the define solves is real:\n{blob}")


def test_no_macro_staged_keeps_simulation_define_on_slang_and_sv2v(
        tmp_path, monkeypatch):
    """`.sv` inputs force the SV fallback, so the read_slang and sv2v pre-pass
    read paths (which also carry the define) are exercised."""
    proj = _mk_project(tmp_path, ext=".sv", stage_macro=False)
    cmds, _ = _run_step_synth(tmp_path, proj, monkeypatch)
    blob = "\n".join(cmds)
    assert "-DSIMULATION -DYOSYS" in blob and "read_slang " in blob, (
        f"read_slang must keep the historical define set:\n{blob}")
    assert "sv2v -DSIMULATION -DYOSYS " in blob, (
        f"the sv2v pre-pass must keep the historical define set:\n{blob}")


def test_no_macro_staged_reports_behavioural_path(tmp_path, monkeypatch):
    """Even the unchanged path is REPORTED, so which arm synth took is never
    something an audit has to infer from a cell count."""
    proj = _mk_project(tmp_path, ext=".v", stage_macro=False)
    _, res = _run_step_synth(tmp_path, proj, monkeypatch)
    dec = res.extras["macro_define_decision"]
    assert dec["verdict"] == "BEHAVIOURAL_NO_MACRO"
    assert dec["define_sim"] is True
    log = (proj / "phase2" / "stage2" / "synth" / "synth.log").read_text()
    assert "STAGED-MACRO vs BEHAVIOURAL PATH" in log


# ---------------------------------------------------------------------------
# THE DEFECT: a staged macro must be instantiated, not replaced by flops.
# ---------------------------------------------------------------------------

def test_staged_macro_drops_the_forced_simulation_define(
        tmp_path, monkeypatch):
    proj = _mk_project(tmp_path, ext=".v", stage_macro=True)
    cmds, _ = _run_step_synth(tmp_path, proj, monkeypatch)
    reads = [c for c in cmds if "read_verilog -sv" in c]
    assert reads, "no read_verilog command was emitted"
    assert not any("-DSIMULATION" in c for c in reads), (
        "with a real macro staged, forcing -DSIMULATION makes the macro arm "
        "unreachable and synthesises ~1024 flops in place of the macro:\n"
        + "\n".join(reads))


def test_staged_macro_decision_is_reported(tmp_path, monkeypatch):
    proj = _mk_project(tmp_path, ext=".v", stage_macro=True)
    _, res = _run_step_synth(tmp_path, proj, monkeypatch)
    dec = res.extras["macro_define_decision"]
    assert dec["verdict"] == "MACRO_INSTANTIATED"
    assert dec["define_sim"] is False
    assert "OTP128X8_MACRO" in dec["macro_cells"]
    log = (proj / "phase2" / "stage2" / "synth" / "synth.log").read_text()
    assert "MACRO_INSTANTIATED" in log


def test_staged_macro_still_blackboxed_into_synth(tmp_path, monkeypatch):
    """Dropping the define is only sound because the macro Liberty is read as a
    blackbox — otherwise the macro arm would not elaborate."""
    proj = _mk_project(tmp_path, ext=".v", stage_macro=True)
    cmds, _ = _run_step_synth(tmp_path, proj, monkeypatch)
    assert any("read_liberty -lib" in c and "OTP128X8_MACRO" in c
               for c in cmds), "\n".join(cmds)


# ---------------------------------------------------------------------------
# FAIL LOUDLY, NOT SILENTLY. A silent fall-through is how this shipped.
# ---------------------------------------------------------------------------

def test_macro_staged_without_liberty_is_reported_at_error(
        tmp_path, monkeypatch):
    """A macro shipping only a `.v` model has nothing for synth to bind, so the
    define is KEPT (safe) — but the run must say the result is a behavioural
    model of a cell that was staged as a real macro."""
    proj = _mk_project(tmp_path, ext=".v", stage_macro=True, macro_lib=False)
    cmds, res = _run_step_synth(tmp_path, proj, monkeypatch)
    dec = res.extras["macro_define_decision"]
    assert dec["severity"] == "ERROR"
    assert dec["verdict"] == "MACRO_STAGED_UNUSABLE"
    assert dec["define_sim"] is True, (
        "keeping the historical define is the safe choice here; the defect is "
        "silence, not the define")
    assert "OTP128X8_MACRO" in dec["unbindable"]


def test_macro_staged_but_never_instantiated_is_reported_at_error(tmp_path):
    """The staged cell name and the RTL's instance name disagree — exactly the
    shape that silently degrades to behavioural. Public API, no runner needed."""
    rtl = RTL_OTP.replace("OTP128X8_MACRO", "SOME_OTHER_CELL")
    macro = tmp_path / "M.lib"
    macro.write_text(MACRO_LIB)
    dec = sf.decide_macro_aware_sim_define(rtl, [macro])
    assert dec["verdict"] == "MACRO_STAGED_UNUSABLE"
    assert dec["severity"] == "ERROR"
    assert dec["define_sim"] is True


def test_macro_staged_but_rtl_has_no_define_arm_is_a_warning(tmp_path):
    """A macro integrated by a later backend step is not an error — but it is
    still reported, and the define is unchanged."""
    macro = tmp_path / "M.lib"
    macro.write_text(MACRO_LIB)
    dec = sf.decide_macro_aware_sim_define(RTL_TOP, [macro])
    assert dec["verdict"] == "BEHAVIOURAL_NO_MACRO"
    assert dec["severity"] == "WARNING"
    assert dec["define_sim"] is True


# ---------------------------------------------------------------------------
# Decision-surface properties (public API).
# ---------------------------------------------------------------------------

def test_commented_out_instantiation_is_not_a_use(tmp_path):
    rtl = RTL_OTP.replace(
        "  OTP128X8_MACRO u_otp (.CLK(clk), .A(addr), .DIN(wdata),",
        "  // OTP128X8_MACRO u_otp (.CLK(clk), .A(addr), .DIN(wdata),")
    macro = tmp_path / "M.lib"
    macro.write_text(MACRO_LIB)
    dec = sf.decide_macro_aware_sim_define(rtl, [macro])
    assert dec["define_sim"] is True, (
        "a commented-out instantiation must never drop the define")


def test_else_arm_first_identifier_is_not_swallowed(tmp_path):
    """Guards the preprocessor walker: a macro instantiated as the FIRST token
    after a bare `` `else `` must still be seen (a naive
    ``\\s*(\\w+)?`` symbol group eats it and inverts the verdict)."""
    rtl = ("module m();\n`ifdef SIMULATION\n  reg r;\n`else\n"
           "  OTP128X8_MACRO u (.CLK(1'b0));\n`endif\nendmodule\n")
    macro = tmp_path / "M.lib"
    macro.write_text(MACRO_LIB)
    dec = sf.decide_macro_aware_sim_define(rtl, [macro])
    assert dec["verdict"] == "MACRO_INSTANTIATED"
    assert dec["define_sim"] is False


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="iverilog not available")
@pytest.mark.parametrize("src", [
    "`ifdef SIMULATION\nA a();\n`else\nB b();\n`endif\n",
    "`ifndef SIMULATION\nB b();\n`else\nA a();\n`endif\n",
    "`ifdef FOO\nX x();\n`elsif SIMULATION\nA a();\n`else\nB b();\n`endif\n",
    "`ifdef SIMULATION\n`ifdef INNER\nQ q();\n`else\nA a();\n`endif\n"
    "`else\nB b();\n`endif\n",
    "`ifndef SIMULATION\n`ifdef INNER\nQ q();\n`else\nB b();\n`endif\n"
    "`else\nA a();\n`endif\n",
    "  `ifdef SIMULATION\n  A a();\n  `else\n  B b();\n  `endif\n",
    "C c();\n",
])
@pytest.mark.parametrize("defines", [set(), {"SIMULATION"}])
def test_conditional_walker_agrees_with_a_real_preprocessor(
        tmp_path, src, defines):
    """The whole verdict turns on which arm survives, so the walker is pinned
    against iverilog's actual preprocessor rather than against itself."""
    import re as _re

    def _insts(text):
        return set(_re.findall(r"\b([A-Z])\s+[a-z]\(\)", text))

    f = tmp_path / "c.v"
    f.write_text(src)
    ref = _pr.run(
        ["iverilog", "-E", "-o", "/dev/stdout"]
        + [f"-D{d}" for d in sorted(defines)] + [str(f)],
        capture_output=True, text=True).stdout
    assert _insts(sf._reachable_text(src, defines)) == _insts(ref), (
        f"walker disagrees with iverilog -E for defines={sorted(defines)}\n"
        f"src:\n{src}\niverilog:\n{ref}")


_GATED = ("module t();\n`ifdef SIMULATION\n  reg r;\n`else\n"
          "  {M} u (.a(1'b0));\n`endif\nendmodule\n")


@pytest.mark.parametrize("name,text", [
    # A missed declaration degrades SILENTLY to behavioural, so the compact and
    # machine-generated spellings matter as much as the conventional one.
    ("compact.lib", "library(x){ cell (MACRO_A) { area : 1.0; } }"),
    ("pretty.lib", "library (x) {\n  cell (MACRO_A) {\n    area : 1.0;\n  }\n}\n"),
    ("quoted.lib", 'library (x) {\n  cell ("MACRO_A") { area : 1.0; }\n}\n'),
    ("macro.lef", "MACRO MACRO_A\n  SIZE 10 BY 10 ;\nEND MACRO_A\n"),
])
def test_staged_cell_is_found_in_every_artifact_spelling(
        tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    assert "MACRO_A" in sf.staged_macro_cells([f]), (
        f"a staged cell missed in {name} degrades silently to behavioural")
    dec = sf.decide_macro_aware_sim_define(_GATED.format(M="MACRO_A"), [f])
    assert dec["verdict"] == "MACRO_INSTANTIATED"
    assert dec["define_sim"] is False


def test_near_miss_liberty_keywords_are_not_cells(tmp_path):
    """The detector must also stay SILENT on known-good input: Liberty
    attributes and groups whose names merely end in `cell` are not macros, and
    `endmodule` is not a module declaration."""
    lib = tmp_path / "n.lib"
    lib.write_text("library (z) {\n  cell_leakage_power : 1.0;\n"
                   "  scaled_cell (SC_X) { }\n  test_cell (TC_Y) { }\n}\n")
    assert sf.staged_macro_cells([lib]) == {}
    v = tmp_path / "n.v"
    v.write_text("module ONLY_ONE (input a);\nendmodule\n")
    assert set(sf.staged_macro_cells([v])) == {"ONLY_ONE"}


@pytest.mark.parametrize("rtl,used", [
    ("MACRO_A u_inst (.a(1'b0));", True),      # a real instantiation
    ("MACRO_A #(.W(8)) u (.a(1'b0));", True),  # parameterised
    ("MACRO_A_inst (.a(1'b0));", False),       # a name that merely EXTENDS it
    ("MACRO_A_inst u (.a(1'b0));", False),
    ("wire x = foo.MACRO_A (1'b0);", False),   # hierarchical reference
])
def test_only_a_real_instantiation_counts_as_a_use(rtl, used):
    assert ("MACRO_A" in sf._instantiated_cells(rtl, ["MACRO_A"])) is used


def test_macro_used_regardless_of_define_keeps_the_define(tmp_path):
    """The define does not gate this macro, so there is nothing to change —
    keep the historical flow."""
    lib = tmp_path / "m.lib"
    lib.write_text("library (x) { cell (MACRO_A) { area : 1.0; } }")
    dec = sf.decide_macro_aware_sim_define(
        "module t(); MACRO_A u (.a(1'b0)); endmodule", [lib])
    assert dec["verdict"] == "MACRO_ALREADY_REACHABLE"
    assert dec["define_sim"] is True


def test_no_staged_files_is_the_historical_answer():
    dec = sf.decide_macro_aware_sim_define(RTL_OTP, [])
    assert dec["define_sim"] is True
    assert dec["verdict"] == "BEHAVIOURAL_NO_MACRO"
    assert dec["severity"] == "INFO"


# ---------------------------------------------------------------------------
# End-to-end on real yosys: the netlist, which is what actually taped out.
# ---------------------------------------------------------------------------

def _yosys_container():
    if not shutil.which("docker"):
        return None
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    for n in names.split():
        if "eda" in n:
            return n
    return None


@pytest.mark.skipif(_yosys_container() is None,
                    reason="no EDA container with yosys available")
@pytest.mark.parametrize("stage_macro,expect", [(True, "macro"),
                                                (False, "flops")])
def test_e2e_netlist_matches_the_decision(tmp_path, stage_macro, expect):
    """The whole point, measured in the netlist: a staged macro must appear as a
    macro instance; with no macro staged the behavioural array must still be
    synthesised exactly as before."""
    import os
    container = _yosys_container()
    # Author locally, then `docker cp` into the container's own filesystem —
    # never assume the host tree is bind-mounted (the repo's other
    # container-gated tests use the same shape).
    (tmp_path / "chip_top.v").write_text(RTL_TOP)
    (tmp_path / "otp_mem.v").write_text(RTL_OTP)
    staged = []
    if stage_macro:
        lib = tmp_path / "OTP128X8_MACRO_tt.lib"
        lib.write_text(MACRO_LIB)
        staged = [lib]

    blob = sf.read_text_blob(sorted(tmp_path.glob("*.v")))
    dec = sf.decide_macro_aware_sim_define(blob, staged)
    d = "-DSIMULATION " if dec["define_sim"] else ""

    tag = f"/tmp/vibeic_macrodef_{os.getpid()}_{int(stage_macro)}"
    try:
        _pr.run(["docker", "exec", container, "sh", "-c",
                        f"rm -rf {tag} && mkdir -p {tag}"],
                       check=True, capture_output=True, text=False)
        for f in sorted(tmp_path.iterdir()):
            _pr.run(["docker", "cp", str(f), f"{container}:{tag}/"],
                           check=True, capture_output=True, text=False)
        libread = ""
        if stage_macro:
            libread = (f"read_liberty -lib -ignore_miss_dir -setattr blackbox "
                       f"{tag}/OTP128X8_MACRO_tt.lib; ")
        script = (f"{libread}"
                  f"read_verilog -sv {d}{tag}/chip_top.v; "
                  f"read_verilog -sv {d}{tag}/otp_mem.v; "
                  f"hierarchy -check -top chip_top; proc; flatten; "
                  f"tribuf -logic; synth -top chip_top -flatten; clean; stat")
        out = _pr.run(
            ["docker", "exec", container, "sh", "-c",
             f"PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH; "
             f"cd {tag} && yosys -p '{script}'"],
            capture_output=True, text=True).stdout
    finally:
        _pr.run(["docker", "exec", container, "sh", "-c",
                        f"rm -rf {tag}"], capture_output=True, text=False)
    stat = out.split("=== chip_top ===")[-1]

    if expect == "macro":
        assert "OTP128X8_MACRO" in stat and "DFF" not in stat, (
            "a staged macro must be instantiated, not expanded to flops "
            f"(a volatile OTP):\n{stat}")
    else:
        assert "DFF" in stat, (
            "with no macro staged the behavioural array must still be "
            f"synthesised — this is the path -DSIMULATION exists for:\n{stat}")
