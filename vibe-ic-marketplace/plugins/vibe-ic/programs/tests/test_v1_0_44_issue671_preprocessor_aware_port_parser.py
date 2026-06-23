"""ORGANIC #671 — full-stack-TB RTL-top port parser ignored `ifdef/`endif.

The RTL-top port-surface parser was not preprocessor-aware: it counted ports
inside NEVER-TAKEN `ifdef arms, so the generated full-stack TB bound
conditionally-compiled ports (a formal / debug interface gated by a macro the
DUT define-set excludes) that the sv2v-converted DUT — built under a different
define-set — does not expose. The reference_tb then FAILed to compile (rc=23,
23x "port `rvfi_*` is not a port of u_dut"), rendering the ECO loop inert via a
FALSE "real structural defect" attribution.

Concretely: a CPU-core RTL declares 23 rvfi_* ports inside `ifdef RVFI...`endif
(RVFI itself gated by `ifdef RISCV_FORMAL → `define RVFI). The DUT conversion
runs -D{SIMULATION|SYNTHESIS} (decide_sv2v_tb_define), neither of which defines
RISCV_FORMAL, so the DUT drops those ports — but the TB bound all of them.

Fix: `reset_clock_variant_alias.parse_module_ports` / `_module_header` accept the
compile-time -D define-set and BLANK not-taken `ifdef/`ifndef/`elsif/`else arms
(honoring an in-file `define under its own gate) BEFORE the port list is
extracted. `phase2._v629_rtl_top_ports` threads the SAME define-set the runner's
sv2v DUT conversion uses (via `_v671_tb_compile_defines` → decide_sv2v_tb_define).

Positive: stripping the `ifdef RVFI/RISCV_FORMAL arm yields exactly the base
ports, 0 rvfi → matches the "base pins compile".
NO-LEAK: `defines=None` (the legacy default, used by #629's positive case) keeps
the take-every-arm parse byte-for-byte; an `ifdef whose macro IS in the set (or
is transitively `define-d under a taken gate) still exposes its ports.

chip-AGNOSTIC: pure `ifdef/`define grammar + abstract SIMULATION/SYNTHESIS
define-set — no chip / vendor / macro literal (no RVFI / RISCV_FORMAL string).
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import reset_clock_variant_alias as RCV  # noqa: E402
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


# A CPU-core-shaped RTL: base ports + a conditional formal/debug interface gated
# by a macro NOT in the SIMULATION/SYNTHESIS compile set. The nested
# `ifdef OUTER → `define INNER → `ifdef INNER chain mirrors the real
# RISCV_FORMAL→RVFI shape, chip-AGNOSTICally renamed.
_CORE = """\
`ifdef OUTER_FORMAL
  `define INNER_DBG
`endif
module the_core (
  input  logic        clk_i,
  input  logic        rst_ni,
  output logic        instr_req_o,
  input  logic        instr_gnt_i,
`ifdef INNER_DBG
  output logic        dbg_valid,
  output logic [31:0] dbg_insn,
  output logic [4:0]  dbg_rs1_addr,
  output logic [31:0] dbg_pc_rdata,
`endif
  output logic        core_sleep_o
);
endmodule
"""

_BASE = {"clk_i", "rst_ni", "instr_req_o", "instr_gnt_i", "core_sleep_o"}
_COND = {"dbg_valid", "dbg_insn", "dbg_rs1_addr", "dbg_pc_rdata"}


def _names(ports):
    return {n for _d, _w, n in ports}


# ── unit: parse_module_ports honors the define-set ─────────────────────────

def test_legacy_no_defines_takes_every_arm():
    # NO-LEAK / no-regression: the historical signature (no define-set) keeps
    # parsing EVERY arm exactly as #629's positive case relies on.
    names = _names(RCV.parse_module_ports(_CORE, "the_core"))
    assert _BASE <= names
    assert _COND <= names


def test_simulation_define_excludes_conditional_ports():
    names = _names(RCV.parse_module_ports(_CORE, "the_core", {"SIMULATION"}))
    assert names == _BASE
    assert not (names & _COND)        # conditional ports NOT bound


def test_synthesis_define_excludes_conditional_ports():
    names = _names(RCV.parse_module_ports(_CORE, "the_core", {"SYNTHESIS"}))
    assert names == _BASE
    assert not (names & _COND)


def test_gating_macro_in_set_exposes_conditional_ports():
    # When the OUTER gate IS defined, the in-file `define INNER_DBG fires and
    # the conditional ports ARE real → they must be exposed.
    names = _names(RCV.parse_module_ports(_CORE, "the_core", {"OUTER_FORMAL"}))
    assert _BASE <= names
    assert _COND <= names


def test_direct_inner_define_exposes_conditional_ports():
    names = _names(RCV.parse_module_ports(_CORE, "the_core", {"INNER_DBG"}))
    assert _COND <= names


def test_else_arm_taken_when_gate_absent():
    rtl = """\
module m (
  input clk,
`ifdef FEAT
  output feat_only,
`else
  output base_only,
`endif
  input rst_n
);
endmodule
"""
    # FEAT absent → the `else arm is taken: base_only present, feat_only not.
    names = _names(RCV.parse_module_ports(rtl, "m", {"SIMULATION"}))
    assert "base_only" in names and "feat_only" not in names
    # FEAT present → the `ifdef arm is taken instead.
    names2 = _names(RCV.parse_module_ports(rtl, "m", {"FEAT"}))
    assert "feat_only" in names2 and "base_only" not in names2


def test_ifndef_arm():
    rtl = """\
module m (
  input clk,
`ifndef SYNTHESIS
  output sim_dbg,
`endif
  input rst_n
);
endmodule
"""
    # SYNTHESIS defined → `ifndef SYNTHESIS arm NOT taken.
    assert "sim_dbg" not in _names(RCV.parse_module_ports(rtl, "m", {"SYNTHESIS"}))
    # SIMULATION only → `ifndef SYNTHESIS arm taken.
    assert "sim_dbg" in _names(RCV.parse_module_ports(rtl, "m", {"SIMULATION"}))


# ── compile-define resolver mirrors decide_sv2v_tb_define ───────────────────

def _scaffold(tmp_path, extra_rtl=""):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "the_core.sv").write_text(_CORE)
    if extra_rtl:
        (rtl / "extra.sv").write_text(extra_rtl)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "the_core",
        "top_ports": [
            {"name": "clk_i", "direction": "input"},
            {"name": "rst_ni", "direction": "input"},
            {"name": "core_sleep_o", "direction": "output"},
        ],
    }))
    return proj


def test_tb_compile_defines_default_simulation(tmp_path):
    proj = _scaffold(tmp_path)
    # No include-closure hole → decide_sv2v_tb_define keeps SIMULATION.
    assert R._v671_tb_compile_defines(proj) == {"SIMULATION"}


def test_v629_rtl_top_ports_excludes_conditional_under_compile_set(tmp_path):
    proj = _scaffold(tmp_path)
    defines = R._v671_tb_compile_defines(proj)
    ports = R._v629_rtl_top_ports(proj, "the_core", defines)
    names = {n for _d, n, _w in ports}
    assert _BASE <= names
    # NO-LEAK on the DUT surface: conditional formal/debug ports excluded.
    assert not (names & _COND)


def test_v629_rtl_top_ports_legacy_none_keeps_all(tmp_path):
    proj = _scaffold(tmp_path)
    # No define-set → legacy behaviour (every arm) — proves the new arg is
    # opt-in and #629's positive case is untouched.
    ports = R._v629_rtl_top_ports(proj, "the_core")
    names = {n for _d, n, _w in ports}
    assert _COND <= names


# ── end-to-end: emitted full-stack TB binds only the unconditional ports ────

def test_emitted_tb_does_not_bind_conditional_ports(tmp_path):
    proj = _scaffold(tmp_path)
    res = R.step_full_stack_tb_gen(proj, "the_core")
    assert res.status in ("PASS", "SKIP"), res.detail
    sim = _pl.sim_full_stack_dir(proj)
    tb = sim / "tb_the_core_full.v"
    assert tb.is_file(), sorted(p.name for p in sim.glob("*"))
    txt = tb.read_text()
    # The DUT instantiation must NOT reference any conditional port.
    for cond in _COND:
        assert f".{cond}(" not in txt, \
            f"conditional port {cond} leaked into the TB DUT binding"
    # the base ports ARE present.
    assert ".instr_req_o(" in txt
