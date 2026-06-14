"""ORGANIC #704 — l9_rtl_pin_consistency_check RTL-top parser was
preprocessor-BLIND.

`l9_rtl_pin_consistency_check.parse_rtl_top_ports` only did comment +
balanced-paren `#(...)` parameter stripping; it had NO
`ifdef/`ifndef/`elsif/`else handling. So on any top with an `ifdef-gated
OPTIONAL interface (formal / RVFI / ECC / debug), the gate:
  (1) harvested every port inside the NOT-COMPILED `ifdef arm and reported
      them as 'RTL top has ports not in L9' (e.g. 23 rvfi_* ports), and
  (2) leaked the last-seen direction token across the stripped conditional
      boundary into the next real port (e.g. fetch_enable_i, declared
      right after the `ifdef RVFI…`endif, read as `output` not `input`).

Reproduced on a RISC-V CPU core (ibex_core shape): the naive parser →
30 ports (23 rvfi harvested) and a fetch_enable_i direction leak; the
SHARED #671 preprocessor-aware parser
(reset_clock_variant_alias.parse_module_ports(text, top, {"SIMULATION"}))
→ 7 ports, rvfi fully excluded, fetch_enable_i=input.

Fix: parse_rtl_top_ports migrated OFF its local regex ONTO the shared
parser, resolving the SAME compile define-set the runner's DUT conversion
uses (base SIMULATION, synth/TB flip via synth_frontend.decide_sv2v_tb_define,
mirrored by phase2._v671_tb_compile_defines) so NOT-TAKEN `ifdef arms are
blanked before port extraction.

§4.05 NO-LEAK:
  - a NON-`ifdef top is UNAFFECTED (every arm present regardless of the
    define-set; the existing passing cases still pass);
  - a port genuinely declared in the COMPILED arm is still checked;
  - a genuine L9↔RTL pin / direction mismatch on a NON-conditional port is
    STILL reported (the gate still catches real inconsistencies);
  - the direction of a real compiled port is read correctly.

chip-AGNOSTIC: pure `ifdef grammar + abstract SIMULATION/SYNTHESIS compile
define-set — no chip / vendor / macro literal (no RVFI / RISCV_FORMAL /
ibex string in the program; the test fixtures embed the real shape only as
test data, chip-AGNOSTICally renamed where it would be a program literal).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as L9  # noqa: E402

PROG = _PROGRAMS / "l9_rtl_pin_consistency_check.py"
BT = chr(96)  # backtick — keep it out of the source-literal so the file
#               itself reads cleanly under any encoding tooling.


# ── real ibex_core `ifdef RVFI shape (23 rvfi_* ports + fetch_enable_i) ──────
# RVFI is itself gated by `ifdef RISCV_FORMAL → `define RVFI, exactly the real
# OpenTitan/Ibex chain. The DUT conversion compiles under SIMULATION/SYNTHESIS,
# NEITHER of which defines RISCV_FORMAL, so the rvfi interface is NOT a real
# DUT port surface.
_RVFI_PORTS = (
    "rvfi_valid", "rvfi_order", "rvfi_insn", "rvfi_trap", "rvfi_halt",
    "rvfi_intr", "rvfi_mode", "rvfi_ixl", "rvfi_rs1_addr", "rvfi_rs2_addr",
    "rvfi_rs3_addr", "rvfi_rs1_rdata", "rvfi_rs2_rdata", "rvfi_rs3_rdata",
    "rvfi_rd_addr", "rvfi_rd_wdata", "rvfi_pc_rdata", "rvfi_pc_wdata",
    "rvfi_mem_addr", "rvfi_mem_rmask", "rvfi_mem_wmask", "rvfi_mem_rdata",
    "rvfi_mem_wdata",
)
assert len(_RVFI_PORTS) == 23


def _rvfi_block() -> str:
    lines = []
    for i, name in enumerate(_RVFI_PORTS):
        w = "" if i % 3 == 0 else f"[{(i % 31) + 1}:0] "
        lines.append(f"  output logic {w}{name},\n")
    return "".join(lines)


def _ibex_core_rtl() -> str:
    """The CPU-core top: base ports, then a `ifdef RVFI optional formal
    interface (23 rvfi_* ports), then fetch_enable_i declared IMMEDIATELY
    after the `endif — the exact carry-forward-leak shape from the issue."""
    return (
        BT + "ifdef RISCV_FORMAL\n"
        "  " + BT + "define RVFI\n"
        + BT + "endif\n"
        "module ibex_core (\n"
        "  input  logic        clk_i,\n"
        "  input  logic        rst_ni,\n"
        "  input  logic        test_en_i,\n"
        "  output logic        instr_req_o,\n"
        "  input  logic        instr_gnt_i,\n"
        + BT + "ifdef RVFI\n"
        + _rvfi_block()
        + BT + "endif\n"
        "  input  logic        fetch_enable_i,\n"   # right after `endif
        "  output logic        core_sleep_o\n"
        ");\n"
        "endmodule\n"
    )


# The L9 contract enumerates ONLY the real (non-conditional) DUT pins. clk_i /
# rst_ni are implicit-stripped from BOTH sides by the gate, leaving the
# functional pins.
_L9_REAL_PORTS = [
    {"name": "clk_i", "direction": "input"},
    {"name": "rst_ni", "direction": "input"},
    {"name": "test_en_i", "direction": "input"},
    {"name": "instr_req_o", "direction": "output"},
    {"name": "instr_gnt_i", "direction": "input"},
    {"name": "fetch_enable_i", "direction": "input"},
    {"name": "core_sleep_o", "direction": "output"},
]


def _scaffold(tmp_path, rtl_text: str, top: str, l9_ports: list) -> Path:
    proj = tmp_path / "proj"
    rtl = L9._pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{top}.sv").write_text(rtl_text)
    gd = L9._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": top,
        "top_ports": l9_ports,
    }))
    return proj


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _names(ports: list) -> list:
    return [d["name"] for d in ports]


# ══ POSITIVE ════════════════════════════════════════════════════════════════

def test_ifdef_gated_interface_excluded_from_rtl_port_set():
    """The 23 rvfi_* ports inside the `ifdef RVFI arm are EXCLUDED when the
    compile define-set (SIMULATION) does not define RVFI / RISCV_FORMAL."""
    rtl = _ibex_core_rtl()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "ibex_core.sv"
        f.write_text(rtl)

        # Preprocessor-aware (the gate's real path): NO rvfi, the real ports.
        aware = L9.parse_rtl_top_ports(f, "ibex_core", {"SIMULATION"})
        names = _names(aware)
        assert not any(n.startswith("rvfi") for n in names), names
        assert names == [
            "clk_i", "rst_ni", "test_en_i", "instr_req_o",
            "instr_gnt_i", "fetch_enable_i", "core_sleep_o",
        ], names
        assert len(aware) == 7

        # Take-every-arm (defines=None) DOES harvest the 23 rvfi ports — proves
        # the define-set is what excludes them (the bug shape).
        naive = L9.parse_rtl_top_ports(f, "ibex_core")
        n_names = _names(naive)
        assert sum(1 for n in n_names if n.startswith("rvfi")) == 23, n_names
        assert len(naive) == 30


def test_fetch_enable_after_endif_reads_input_no_direction_carry():
    """fetch_enable_i, declared immediately after the stripped `endif, is read
    as `input` (its real direction) — NOT carried-forward from the preceding
    stripped `output` rvfi ports."""
    rtl = _ibex_core_rtl()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "ibex_core.sv"
        f.write_text(rtl)
        aware = L9.parse_rtl_top_ports(f, "ibex_core", {"SIMULATION"})
        fe = [d for d in aware if d["name"] == "fetch_enable_i"]
        assert fe == [{"name": "fetch_enable_i", "direction": "input"}], aware
        # And the port right BEFORE the conditional block keeps its direction.
        gnt = [d for d in aware if d["name"] == "instr_gnt_i"]
        assert gnt == [{"name": "instr_gnt_i", "direction": "input"}], aware


def test_old_local_parser_leaked_direction_documents_the_bug():
    """Document the carry-forward leak the OLD local parser produced, to pin
    WHY the migration is correct. The old parser stripped the `ifdef arm with
    a comment/param-only strip (NO ifdef handling), so the last-seen direction
    of the (then-still-visible-but-now-blanked) preceding tokens leaked. We
    reconstruct the old carry-forward logic on the blanked-but-not-ifdef-aware
    body and show fetch_enable_i would read `output`.

    This is a UNIT demonstration of the bug class — the gate itself uses the
    fixed parser, asserted above."""
    # Old shape: `input a, b, c` carry-forward across a comma-split body, where
    # the conditional arm leaves a trailing `output` token as the last seen.
    body = (
        "input clk_i, "
        "output last_cond_port, "   # last token of a not-compiled `ifdef arm
        "fetch_enable_i"            # no own direction token → would carry `output`
    )
    cur_dir = None
    leaked = {}
    import re as _re
    _DIR = L9._DIR_NORMALIZE
    for seg in body.split(","):
        toks = seg.split()
        if not toks:
            continue
        if toks[0].lower() in _DIR:
            cur_dir = _DIR[toks[0].lower()]
            toks = toks[1:]
        if not toks:
            continue
        nm = toks[-1].strip("[]()")
        if not _re.match(r"^[A-Za-z_]\w*$", nm):
            continue
        leaked[nm] = cur_dir
    # The OLD carry-forward logic mis-reads fetch_enable_i as `output`.
    assert leaked["fetch_enable_i"] == "output"
    # The FIXED parser (asserted in the test above) reads it as `input`.


def test_gate_passes_when_l9_matches_ifdef_aware_rtl(tmp_path):
    """End-to-end: the full gate PASSes — the rvfi ports are gone, the real
    pins match the L9 contract, and fetch_enable_i direction agrees."""
    proj = _scaffold(tmp_path, _ibex_core_rtl(), "ibex_core", _L9_REAL_PORTS)
    r = _run(proj)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    # No rvfi false-positive 'RTL has ports not in L9'.
    assert "rvfi" not in r.stdout, r.stdout


def test_gate_would_fail_without_ifdef_resolution(tmp_path):
    """Inverse control: the SAME L9 + RTL, but if the gate took every arm it
    would report the 23 rvfi ports as extra. We prove the take-every-arm
    parse produces those findings, so the PASS above is BECAUSE of the
    preprocessor resolution (not because rvfi happens to be allow-listed)."""
    proj = _scaffold(tmp_path, _ibex_core_rtl(), "ibex_core", _L9_REAL_PORTS)
    rtl_top = L9.find_rtl_top(proj, json.loads(
        (L9._pl.generated_docs_dir(proj) /
         "L9_INTEGRATION_SPEC.json").read_text()))
    take_every = L9.parse_rtl_top_ports(rtl_top, "ibex_core")  # defines=None
    extra = sorted(
        {d["name"] for d in take_every}
        - {p["name"] for p in _L9_REAL_PORTS}
    )
    # rvfi ports are NOT debug/scan/tb-named, so under take-every-arm they
    # would have been reported as a real pin-set discrepancy → FAIL.
    assert all(n.startswith("rvfi") for n in extra), extra
    assert len(extra) == 23


# ══ §4.05 NO-LEAK ═══════════════════════════════════════════════════════════

def test_noleak_non_ifdef_top_unaffected(tmp_path):
    """A top with NO `ifdef is parsed identically — every declared port is
    returned regardless of the define-set; the gate PASSes against a matching
    L9 exactly as before the migration."""
    rtl = (
        "module plain_top (\n"
        "  input  wire clk,\n"
        "  input  wire rst_n,\n"
        "  input  wire        cmd_valid,\n"
        "  output wire        cmd_ready,\n"
        "  output wire [7:0]  data_o\n"
        ");\nendmodule\n"
    )
    l9 = [
        {"name": "clk", "direction": "input"},
        {"name": "rst_n", "direction": "input"},
        {"name": "cmd_valid", "direction": "input"},
        {"name": "cmd_ready", "direction": "output"},
        {"name": "data_o", "direction": "output"},
    ]
    proj = _scaffold(tmp_path, rtl, "plain_top", l9)
    r = _run(proj)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    # And the parser yields the SAME ports with and without a define-set.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "plain_top.sv"
        f.write_text(rtl)
        none_set = _names(L9.parse_rtl_top_ports(f, "plain_top"))
        sim_set = _names(L9.parse_rtl_top_ports(f, "plain_top", {"SIMULATION"}))
        assert none_set == sim_set == [
            "clk", "rst_n", "cmd_valid", "cmd_ready", "data_o"], (
            none_set, sim_set)


def test_noleak_genuine_pinset_mismatch_on_nonconditional_port_still_fails(
        tmp_path):
    """A real dropped pin on a NON-conditional port is STILL a FAIL — the
    preprocessor resolution does not blank a port that lives outside any
    `ifdef arm."""
    rtl = _ibex_core_rtl()
    # L9 declares a real functional pin (alert_o) the RTL top does NOT expose.
    l9 = _L9_REAL_PORTS + [{"name": "alert_o", "direction": "output"}]
    proj = _scaffold(tmp_path, rtl, "ibex_core", l9)
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "alert_o" in r.stdout, r.stdout


def test_noleak_genuine_direction_mismatch_on_compiled_port_still_fails(
        tmp_path):
    """A real direction mismatch on a COMPILED (non-conditional) port is STILL
    a FAIL — the gate reads the compiled port's real direction and compares
    it."""
    rtl = _ibex_core_rtl()
    # L9 says fetch_enable_i is an OUTPUT; the compiled RTL declares it input.
    l9 = [dict(p) for p in _L9_REAL_PORTS]
    for p in l9:
        if p["name"] == "fetch_enable_i":
            p["direction"] = "output"
    proj = _scaffold(tmp_path, rtl, "ibex_core", l9)
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "direction mismatch" in r.stdout, r.stdout
    assert "fetch_enable_i" in r.stdout, r.stdout
    assert "L9=output" in r.stdout and "RTL=input" in r.stdout, r.stdout


def test_noleak_compiled_arm_port_still_checked(tmp_path):
    """A port inside an `ifdef arm whose macro IS in the compile set (the arm
    IS compiled) is a REAL DUT port and must still be checked. Here the
    optional interface is gated by `ifndef SYNTHESIS, and the compile set is
    {SIMULATION} → the arm IS taken → its port is a real pin and must appear
    in L9 (omitting it FAILs)."""
    rtl = (
        "module dut (\n"
        "  input  wire clk,\n"
        "  input  wire rst_n,\n"
        "  input  wire cmd_valid,\n"
        + BT + "ifndef SYNTHESIS\n"
        "  output wire sim_observe_o,\n"   # COMPILED under {SIMULATION}
        + BT + "endif\n"
        "  output wire result_o\n"
        ");\nendmodule\n"
    )
    # L9 omits sim_observe_o — but that arm IS compiled under SIMULATION, so it
    # is a real port → FAIL (it is NOT a debug/scan/tb-named hook).
    l9 = [
        {"name": "clk", "direction": "input"},
        {"name": "rst_n", "direction": "input"},
        {"name": "cmd_valid", "direction": "input"},
        {"name": "result_o", "direction": "output"},
    ]
    proj = _scaffold(tmp_path, rtl, "dut", l9)
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "sim_observe_o" in r.stdout, r.stdout


def test_resolve_compile_defines_defaults_simulation(tmp_path):
    """The define resolver mirrors phase2._v671_tb_compile_defines: a closure
    with no include hole keeps {SIMULATION}."""
    proj = _scaffold(tmp_path, _ibex_core_rtl(), "ibex_core", _L9_REAL_PORTS)
    assert L9._resolve_compile_defines(proj) == {"SIMULATION"}


def test_resolve_compile_defines_no_rtl_dir_safe(tmp_path):
    """No rtl/ dir → resolver still returns a preprocessor-aware default
    (SIMULATION), never crashes."""
    proj = tmp_path / "empty"
    proj.mkdir()
    assert L9._resolve_compile_defines(proj) == {"SIMULATION"}


# ── #704 ROUND-2 (adversarial-review HIGH): the shared parser must NOT drop
#    comma-bundled DIRECTIONLESS ports ────────────────────────────────────────
import reset_clock_variant_alias as RCV  # noqa: E402


def _tnames(ports):
    # tuple-form (dir, width, name) helper — distinct from the dict-form
    # `_names` above (which keys `d["name"]` on parse_rtl_top_ports output).
    return [p[2] for p in ports]


def test_comma_bundled_directionless_ports_recovered_ROUND2():
    """The migration onto reset_clock_variant_alias.parse_module_ports surfaced
    a latent drop: `_PORT_DECL_RE.finditer` only yielded ports that LEAD with a
    direction keyword, so a shared-direction comma group (`input clk, rst_n`)
    silently lost every member after the first → the l9 gate then reported the
    dropped ports as 'L9 declares pins missing from RTL top' (false FAIL). The
    round-2 carry-forward fix recovers them with the carried direction."""
    src = ("module top (input clk, rst_n, input [7:0] din, dout_en, "
           "output [7:0] q, output v);")
    ports = RCV.parse_module_ports(src, "top")
    assert _tnames(ports) == ["clk", "rst_n", "din", "dout_en", "q", "v"], ports
    by = {n: d for d, _w, n in ports}
    assert by["rst_n"] == "input"      # carried from `input clk`
    assert by["dout_en"] == "input"    # carried from `input [7:0] din`
    assert by["v"] == "output"         # carried from `output [7:0] q`


def test_non_bundled_portlist_byte_identical_to_finditer_ROUND2():
    """§equivalence: for a port list where every port leads with its own
    direction, the carry-forward walk yields exactly what the old finditer
    produced — bundling only ADDS the previously-dropped continuation ports,
    never changes a non-bundled result."""
    import re as _re
    for src, mod in [
        ("module a (input clk, output q);", "a"),
        ("module b (input wire clk, input rst_n, output reg [7:0] data, "
         "inout sda);", "b"),
        ("module c #(parameter N=8) (input [N-1:0] a, output [N-1:0] y);", "c"),
        ("module d import pkg::*; (input clk_i, output logic done_o);", "d"),
    ]:
        block = RCV._module_portlist_block(src, mod, None)
        block = RCV._PP_DIRECTIVE_RE.sub("", block)
        old = [(pm.group(1), (pm.group(2) or "").strip(), pm.group(3))
               for pm in RCV._PORT_DECL_RE.finditer(block)]
        assert RCV.parse_module_ports(src, mod) == old, mod


def test_bundled_ports_with_ifdef_and_directive_lines_ROUND2():
    """Directive marker lines (`ifdef/`endif) inside the block must not hide a
    direction-led port that follows them, and the carried direction must reset
    correctly across the (blanked) conditional. Under {SIMULATION} the RVFI arm
    is excluded; under defines=None every arm's ports (incl. continuations) are
    present."""
    src = ("module ibex (\n input clk, rst_n,\n"
           f"{BT}ifdef RVFI\n output rvfi_valid, rvfi_trap,\n{BT}endif\n"
           " output [31:0] pc, instr);")
    assert _tnames(RCV.parse_module_ports(src, "ibex", {"SIMULATION"})) == \
        ["clk", "rst_n", "pc", "instr"]
    assert _tnames(RCV.parse_module_ports(src, "ibex", None)) == \
        ["clk", "rst_n", "rvfi_valid", "rvfi_trap", "pc", "instr"]
    # pc (a direction-led port right after `endif) must NOT be dropped:
    assert "pc" in _tnames(RCV.parse_module_ports(src, "ibex", {"SIMULATION"}))


def test_l9_gate_no_false_fail_on_bundled_top_ROUND2(tmp_path):
    """End-to-end: a valid top whose pins use comma-bundled `input a, b, c`
    shape must NOT trip a false 'L9 pins missing from RTL top' FAIL (the exact
    HIGH the adversarial review reproduced)."""
    rtl = ("module dut ( input clk, rst_n, input [3:0] sel, en, "
           "output [3:0] y, valid );\n"
           "  assign y = sel; assign valid = en & |sel & clk & rst_n;\n"
           "endmodule\n")
    l9 = [
        {"name": "clk", "direction": "input"},
        {"name": "rst_n", "direction": "input"},
        {"name": "sel", "direction": "input"},
        {"name": "en", "direction": "input"},
        {"name": "y", "direction": "output"},
        {"name": "valid", "direction": "output"},
    ]
    proj = _scaffold(tmp_path, rtl, "dut", l9)
    r = _run(proj)
    assert r.returncode == 0, ("bundled-port top wrongly FAILED:\n" + r.stdout)
    assert "PASS" in r.stdout, r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
