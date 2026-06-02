#!/usr/bin/env python3
"""Smoke + regression tests for BACKLOG-v11 P1 gates.

Each gate is exercised against:
  - synthetic injected-bug RTL (positive — gate must catch the bug)
  - clean reference RTL (negative — gate must PASS / skip cleanly)

Coverage targets:
  P1.1 tristate_pullup_assertion_check    (5 tests)
  P1.2 bram_init_portable_compat_check    (5 tests)
  P1.3 bram_pdob_combinational_check      (4 tests, WARNING-class)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent


def _run(prog: str, project_dir: Path,
         strict: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROGS / f"{prog}.py"), str(project_dir),
           "--json", str(project_dir / f"{prog}.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _load(project_dir: Path, prog: str) -> dict:
    return json.loads((project_dir / f"{prog}.json").read_text())


def _rtl(project_dir: Path, name: str, body: str):
    rtl = project_dir / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def _qsf(project_dir: Path, body: str):
    """Write a minimal QSF (Quartus settings file) declaring an FPGA target."""
    (project_dir / "project.qsf").write_text(body)


def _xdc(project_dir: Path, body: str):
    """Write a minimal XDC (Vivado constraints file)."""
    (project_dir / "project.xdc").write_text(body)


def _l11(project_dir: Path, body: dict):
    docs = project_dir / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L11_LAB_CALIBRATION.json").write_text(json.dumps(body))


# ===========================================================================
# P1.1: tristate_pullup_assertion_check
# ===========================================================================

def test_p11_tristate_no_pullup_fails(tmp_path):
    """inout port driven 1'bz, FPGA target, no QSF pull-up → ERROR."""
    _qsf(tmp_path,
         "set_global_assignment -name FAMILY \"MAX 10\"\n"
         "set_location_assignment PIN_E1 -to gpio_id_bus\n")
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, input logic rstn, inout wire gpio_id_bus,
            output logic q);
  logic drive;
  assign gpio_id_bus = drive ? 1'b0 : 1'bz;
  always_ff @(posedge clk) q <= gpio_id_bus;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "tristate_pullup_assertion_check")
    assert any(f["rule"] == "TRISTATE_NO_PULLUP" for f in rpt["findings"])


def test_p11_tristate_with_qsf_pullup_silent(tmp_path):
    """inout + 1'bz BUT QSF declares WEAK_PULL_UP_RESISTOR ON → silent."""
    _qsf(tmp_path,
         "set_global_assignment -name FAMILY \"MAX 10\"\n"
         "set_location_assignment PIN_E1 -to gpio_id_bus\n"
         "set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON "
         "-to gpio_id_bus\n")
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, input logic rstn, inout wire gpio_id_bus,
            output logic q);
  logic drive;
  assign gpio_id_bus = drive ? 1'b0 : 1'bz;
  always_ff @(posedge clk) q <= gpio_id_bus;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 0


def test_p11_tristate_with_xdc_pullup_silent(tmp_path):
    """Vivado XDC PULLUP true → silent."""
    _xdc(tmp_path,
         "set_property PACKAGE_PIN A1 [get_ports gpio_id_bus]\n"
         "set_property PULLUP true [get_ports gpio_id_bus]\n")
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, inout wire gpio_id_bus, output logic q);
  logic drive;
  assign gpio_id_bus = drive ? 1'b0 : 1'bz;
  always_ff @(posedge clk) q <= gpio_id_bus;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 0


def test_p11_no_qsf_means_asic_silent(tmp_path):
    """No QSF / XDC at all → ASIC target → gate silent."""
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, inout wire gpio_id_bus, output logic q);
  logic drive;
  assign gpio_id_bus = drive ? 1'b0 : 1'bz;
  always_ff @(posedge clk) q <= gpio_id_bus;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 2  # skipped


def test_p11_l11_external_pullup_silent(tmp_path):
    """L11 declares external_pullup → board-side pullup → silent."""
    _qsf(tmp_path,
         "set_global_assignment -name FAMILY \"Cyclone IV\"\n"
         "set_location_assignment PIN_C2 -to bus_a\n")
    _l11(tmp_path, {"external_pullup": ["bus_a"]})
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, inout wire bus_a, output logic q);
  logic en;
  assign bus_a = en ? 1'b0 : 1'bz;
  always_ff @(posedge clk) q <= bus_a;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 0


def test_p11_inout_no_tristate_silent(tmp_path):
    """inout port that's always-driven (no 1'bz anywhere) → silent."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"MAX 10\"\n")
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, inout wire bus_b, output logic q);
  // bus_b is connected to nothing inside — no 1'bz driver anywhere
  always_ff @(posedge clk) q <= 1'b0;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    # No 1'bz driver detected → no risk → silent
    assert r.returncode in (0, 2)


def test_p11_xdc_bus_slice_pullup_silent(tmp_path):
    """v0.118-stable: Vivado XDC declares pull-up using bus-slice form
    `[get_ports gpio_bus[7:0]]`; RTL declares the inout as
    `inout [7:0] gpio_bus`. Pre-fix regex captured `gpio_bus` (slice
    chopped) so the lookup succeeded for unrelated reasons; if the
    captured token included a stray `]` (the original v0.117 bug class),
    the lookup would fail and false-ERROR. Post-fix captures
    `gpio_bus[7:0]` cleanly AND normalised `gpio_bus`, so the inout
    port matches either form."""
    _xdc(tmp_path,
         "set_property PACKAGE_PIN A1 [get_ports gpio_bus[7]]\n"
         "set_property PULLUP true [get_ports gpio_bus[7:0]]\n")
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, inout wire [7:0] gpio_bus,
            output logic [7:0] q);
  logic [7:0] drive;
  assign gpio_bus = drive ? 8'h00 : 8'bzzzzzzzz;
  always_ff @(posedge clk) q <= gpio_bus;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 0, \
        "bus-slice XDC pull-up form must match the bare RTL inout port"


def test_p11_xdc_braced_form_silent(tmp_path):
    """Vivado allows `{port}` brace form too — must also match."""
    _xdc(tmp_path,
         "set_property PACKAGE_PIN A1 [get_ports {gpio_bus[7:0]}]\n"
         "set_property PULLUP true [get_ports {gpio_bus[7:0]}]\n")
    _rtl(tmp_path, "top.sv", """\
module top (input logic clk, inout wire [7:0] gpio_bus,
            output logic [7:0] q);
  logic [7:0] drive;
  assign gpio_bus = drive ? 8'h00 : 8'bzzzzzzzz;
  always_ff @(posedge clk) q <= gpio_bus;
endmodule
""")
    r = _run("tristate_pullup_assertion_check", tmp_path)
    assert r.returncode == 0


# ===========================================================================
# P2.1: protocol_ip_simulation_required_check
# ===========================================================================

def _l8_proto(project_dir: Path):
    docs = project_dir / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "doc_layer": "L8_RTL_CONSTANTS",
        "ibt_ticks": 5000,
        "tsrs_min_ticks": 200,
    }))


def _fpga_artefact(project_dir: Path):
    out = project_dir / "output_files"
    out.mkdir(parents=True, exist_ok=True)
    (out / "design.sof").write_text("dummy")


def _sim_results(project_dir: Path, verdict: str = "PASS",
                 transcript_tokens: list[str] | None = None,
                 newer_than_rtl: bool = True):
    sim = project_dir / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "results.json").write_text(json.dumps({"verdict": verdict}))
    transcript_tokens = transcript_tokens or [
        "BR_PULSE detected at 12us",
        "rx_byte 0x74 received",
        "TX_RESP byte[0] = 0xF2",
        "crc_match OK",
    ]
    (sim / "transcript.log").write_text("\n".join(transcript_tokens))
    if newer_than_rtl:
        # Bump mtime to be newer than every RTL file
        import os, time
        new_t = time.time() + 100
        os.utime(sim / "results.json", (new_t, new_t))


def test_p21_protocol_ip_no_sim_fails(tmp_path):
    """Protocol IP + FPGA artefact + no sim → ERROR."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "protocol_ip_simulation_required_check")
    assert any(f["rule"] == "FULL_STACK_SIM_MISSING"
               for f in rpt["findings"])


def test_p21_sim_pass_recent_silent(tmp_path):
    """Protocol IP + FPGA + sim PASS + recent + transcript → PASS."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    _sim_results(tmp_path)
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 0


def test_p21_sim_fail_verdict_fails(tmp_path):
    """Sim ran but verdict=FAIL → ERROR."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    _sim_results(tmp_path, verdict="FAIL")
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "protocol_ip_simulation_required_check")
    assert any(f["rule"] == "FULL_STACK_SIM_NOT_PASS"
               for f in rpt["findings"])


def test_p21_sim_stale_fails(tmp_path):
    """Sim PASS but RTL is newer than sim → STALE error."""
    import os, time
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    _sim_results(tmp_path, newer_than_rtl=False)
    # Force RTL mtime to be newer than sim
    rtl = tmp_path / "phase2" / "stage1" / "rtl" / "top.sv"
    new_t = time.time() + 1000
    os.utime(rtl, (new_t, new_t))
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "protocol_ip_simulation_required_check")
    assert any(f["rule"] == "FULL_STACK_SIM_STALE"
               for f in rpt["findings"])


def test_p21_non_protocol_silent(tmp_path):
    """L9 declares protocol_layer:none → silent."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "protocol_layer": "none",
    }))
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 2


def test_p21_no_fpga_yet_silent(tmp_path):
    """Protocol IP but no FPGA artefacts yet → not at Step 6 → silent."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 2


# ===========================================================================
# P1.2: bram_init_portable_compat_check
# ===========================================================================

def test_p12_max10_no_eram_fails(tmp_path):
    """MAX10 + $readmemh + no ERAM mode → WARNING (rule fires, exit 0).
    v0.118.1 downgraded ERROR→WARNING because v099 oracle baseline has
    this pattern but works in hardware. --strict still upgrades."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"MAX 10\"\n")
    _rtl(tmp_path, "rom.sv", """\
module rom (input logic [9:0] addr, output logic [7:0] data);
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.ver", mem);
  always_comb data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 0
    rpt = _load(tmp_path, "bram_init_portable_compat_check")
    assert any(f["rule"] == "BRAM_INIT_FAMILY_INCOMPATIBLE"
               for f in rpt["findings"])


def test_p12_max10_with_eram_silent(tmp_path):
    """MAX10 + $readmemh + ERAM mode set → silent."""
    _qsf(tmp_path,
         "set_global_assignment -name FAMILY \"MAX 10\"\n"
         "set_global_assignment -name INTERNAL_FLASH_UPDATE_MODE "
         "\"SINGLE COMP IMAGE WITH ERAM\"\n")
    _rtl(tmp_path, "rom.sv", """\
module rom (input logic [9:0] addr, output logic [7:0] data);
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.ver", mem);
  always_comb data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 0


def test_p12_max10_with_megafunction_silent(tmp_path):
    """MAX10 + altsyncram with init_file → silent."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"MAX 10\"\n")
    _rtl(tmp_path, "rom.sv", """\
module rom (input logic [9:0] addr, output logic [7:0] data);
  altsyncram #(
    .init_file("apple.mif"),
    .numwords_a(1024)
  ) inst (.address_a(addr), .q_a(data));
  // sim-only mirror
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.ver", mem);
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 2  # megafunction with init_file → skip


def test_p12_xilinx_plain_readmemh_fails(tmp_path):
    """Xilinx + plain $readmemh → WARNING (rule fires, exit 0). Same
    v0.118.1 ERROR→WARNING downgrade rationale as MAX10 case."""
    _xdc(tmp_path, "set_property PART xc7a35tcpg236-1 [current_project]\n")
    _rtl(tmp_path, "rom.sv", """\
module rom (input [9:0] addr, output [7:0] data);
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.mem", mem);
  assign data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 0
    rpt = _load(tmp_path, "bram_init_portable_compat_check")
    assert any(f["rule"] == "BRAM_INIT_XILINX_REQUIRES_XPM"
               for f in rpt["findings"])


def test_p12_cyclone_iv_silent(tmp_path):
    """Intel Cyclone IV + $readmemh → silent (family supports it)."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"Cyclone IV\"\n")
    _rtl(tmp_path, "rom.sv", """\
module rom (input logic [9:0] addr, output logic [7:0] data);
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.mem", mem);
  always_comb data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 0


def test_p12_no_qsf_silent(tmp_path):
    """No QSF/XDC → ASIC target → silent."""
    _rtl(tmp_path, "rom.sv", """\
module rom (input [9:0] addr, output [7:0] data);
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.mem", mem);
  assign data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 2


def test_p12_l11_external_loader_silent(tmp_path):
    """L11 declares external_loader → silent."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"MAX 10\"\n")
    _l11(tmp_path, {"bram_init_method": "external_loader"})
    _rtl(tmp_path, "rom.sv", """\
module rom (input [9:0] addr, output [7:0] data);
  reg [7:0] mem [0:1023];
  initial $readmemh("apple.mem", mem);
  assign data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 2


def test_p12_translate_off_silent(tmp_path):
    """$readmemh inside synthesis translate_off block → silent."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"MAX 10\"\n")
    _rtl(tmp_path, "rom.sv", """\
module rom (input [9:0] addr, output [7:0] data);
  reg [7:0] mem [0:1023];
  // synthesis translate_off
  initial $readmemh("apple.mem", mem);
  // synthesis translate_on
  assign data = mem[addr];
endmodule
""")
    r = _run("bram_init_portable_compat_check", tmp_path)
    assert r.returncode == 2  # no synthesis-visible $readmemh


def test_p12_two_brams_one_unguarded_fails(tmp_path):
    """Same .sv file: module A has altsyncram WITH init_file (guarded);
    module B has plain $readmemh (UNGUARDED). v0.118-stable per-module
    fix must fire on module B even though module A is fine. Pre-fix
    file-wide check would have silenced both → silent miss."""
    _qsf(tmp_path, "set_global_assignment -name FAMILY \"MAX 10\"\n")
    _rtl(tmp_path, "memories.sv", """\
module otp_rom (input logic [9:0] addr, output logic [7:0] data);
  // GUARDED — megafunction handles synthesis init
  altsyncram #(
    .init_file("otp.mif"),
    .numwords_a(1024)
  ) inst (.address_a(addr), .q_a(data));
  reg [7:0] mem_mirror [0:1023];
  initial $readmemh("otp.ver", mem_mirror);  // sim-only mirror, OK
endmodule

module sensor_rom (input logic [4:0] addr, output logic [7:0] data);
  // UNGUARDED — plain $readmemh on inferred BRAM, MAX10 silently fails
  reg [7:0] tab [0:31];
  initial $readmemh("sensor_lut.mem", tab);
  assign data = tab[addr];
endmodule
""")
    # v0.118.1 downgraded BRAM_INIT_FAMILY_INCOMPATIBLE ERROR → WARNING
    # by default; --strict still upgrades to ERROR. Use --strict so the
    # exit code asserts the rule fired exactly once (the unguarded
    # sensor_rom), and the otp_rom guarded copy did NOT also fire.
    # Pre-fix file-wide check would have either silenced both or
    # flagged both equally — neither matches "exactly 1 finding".
    r = _run("bram_init_portable_compat_check", tmp_path, strict=True)
    assert r.returncode == 1, \
        "per-module fix must fire on unguarded sensor_rom even though " \
        "otp_rom in same file is guarded (strict=True upgrades WARN→ERR)"
    rpt = _load(tmp_path, "bram_init_portable_compat_check")
    findings = [f for f in rpt["findings"]
                if f["rule"] == "BRAM_INIT_FAMILY_INCOMPATIBLE"]
    assert len(findings) == 1, \
        f"expected exactly 1 finding (sensor_rom only), got {len(findings)}"
    # Summary should report 1 guarded + 1 unguarded
    s = rpt["summary"]
    assert s["guarded_calls"] == 1
    assert s["unguarded_calls"] == 1


# ===========================================================================
# P1.3: bram_pdob_combinational_check (WARNING-class)
# ===========================================================================

def test_p13_off_by_one_warns(tmp_path):
    """Wrapper registers output + consumer non-blocking captures → WARN."""
    _rtl(tmp_path, "otp_rom.sv", """\
module otp_rom (input logic clk, input logic [9:0] addr,
                input logic rd, output logic [7:0] otp_pdob);
  reg [7:0] mem [0:1023];
  always_ff @(posedge clk) begin
    if (rd) otp_pdob <= mem[addr];
  end
endmodule
""")
    _rtl(tmp_path, "otp_seq.sv", """\
module otp_seq (input logic clk, input logic [7:0] otp_pdob,
                output logic [7:0] rd_data);
  typedef enum logic [1:0] { IDLE, FETCH, DONE } st_e;
  st_e st;
  always_ff @(posedge clk) begin
    case (st)
      IDLE:  st <= FETCH;
      FETCH: begin rd_data <= otp_pdob; st <= DONE; end
      DONE:  st <= IDLE;
    endcase
  end
endmodule
""")
    r = _run("bram_pdob_combinational_check", tmp_path)
    assert r.returncode == 0  # WARN-only, exit 0
    rpt = _load(tmp_path, "bram_pdob_combinational_check")
    assert any(f["rule"] == "BRAM_PDOB_OFF_BY_ONE_RISK"
               for f in rpt["findings"])


def test_p13_combinational_output_silent(tmp_path):
    """Wrapper drives output combinationally → silent."""
    _rtl(tmp_path, "otp_rom.sv", """\
module otp_rom (input logic clk, input logic [9:0] addr,
                output logic [7:0] otp_pdob);
  reg [7:0] mem [0:1023];
  assign otp_pdob = mem[addr];
endmodule
""")
    _rtl(tmp_path, "otp_seq.sv", """\
module otp_seq (input logic clk, input logic [7:0] otp_pdob,
                output logic [7:0] rd_data);
  always_ff @(posedge clk) rd_data <= otp_pdob;
endmodule
""")
    r = _run("bram_pdob_combinational_check", tmp_path)
    # combinational output → wrapper isn't on the registered list → skip
    assert r.returncode == 2


def test_p13_l6_wait_state_silent(tmp_path):
    """L6 declares wait state for consuming module → silent."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L6_CONTROL_LOGIC.json").write_text(json.dumps({
        "bram_read_wait_states": [
            {"module": "otp_seq", "cycles": 1},
        ],
    }))
    _rtl(tmp_path, "otp_rom.sv", """\
module otp_rom (input logic clk, input logic [9:0] addr,
                input logic rd, output logic [7:0] otp_pdob);
  reg [7:0] mem [0:1023];
  always_ff @(posedge clk) begin
    if (rd) otp_pdob <= mem[addr];
  end
endmodule
""")
    _rtl(tmp_path, "otp_seq.sv", """\
module otp_seq (input logic clk, input logic [7:0] otp_pdob,
                output logic [7:0] rd_data);
  always_ff @(posedge clk) rd_data <= otp_pdob;
endmodule
""")
    r = _run("bram_pdob_combinational_check", tmp_path)
    assert r.returncode == 0  # explicit wait-state → exempt → PASS


def test_p13_acknowledged_marker_silent(tmp_path):
    """// BRAM_OUTPUT_REGISTER_ACKNOWLEDGED in wrapper → silent."""
    _rtl(tmp_path, "otp_rom.sv", """\
// BRAM_OUTPUT_REGISTER_ACKNOWLEDGED — consumer waits one cycle
module otp_rom (input logic clk, input logic [9:0] addr,
                input logic rd, output logic [7:0] otp_pdob);
  reg [7:0] mem [0:1023];
  always_ff @(posedge clk) begin
    if (rd) otp_pdob <= mem[addr];
  end
endmodule
""")
    _rtl(tmp_path, "otp_seq.sv", """\
module otp_seq (input logic clk, input logic [7:0] otp_pdob,
                output logic [7:0] rd_data);
  always_ff @(posedge clk) rd_data <= otp_pdob;
endmodule
""")
    r = _run("bram_pdob_combinational_check", tmp_path)
    assert r.returncode == 2  # wrapper marked → no candidates → skip


def test_p13_no_bram_silent(tmp_path):
    """Plain RTL with no BRAM → silent."""
    _rtl(tmp_path, "plain.sv", """\
module plain (input logic clk, output logic q);
  always_ff @(posedge clk) q <= ~q;
endmodule
""")
    r = _run("bram_pdob_combinational_check", tmp_path)
    assert r.returncode == 2


def test_p21_waiver_skip_silent(tmp_path):
    """waivers.json declares P21_skip_stack_sim with rationale → silent."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "P21_skip_stack_sim",
            "rationale": "internal smoke test rig only — not for tapeout",
            "review_required": True,
        }]
    }))
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 2


def test_p21_comment_only_log_does_not_pass(tmp_path):
    """v0.118-stable: a TB stub log with tokens ONLY in `//` / `#`
    comment lines should NOT pass the transcript check. Pre-fix (≥2
    tokens, no comment-strip) would have falsely PASSed this."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "results.json").write_text(json.dumps({"verdict": "PASS"}))
    # Transcript: ALL hits are inside comment lines → must NOT pass
    (sim / "transcript.log").write_text(
        "// stub for tx_done / cmd_pass — TODO real test\n"
        "// rx_byte placeholder, BR_PULSE handler unwritten\n"
        "[INFO] sim init\n"
        "[INFO] done\n")
    import os, time
    new_t = time.time() + 100
    os.utime(sim / "results.json", (new_t, new_t))
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "protocol_ip_simulation_required_check")
    assert any(f["rule"] == "FULL_STACK_SIM_TRIVIAL"
               for f in rpt["findings"])


def test_p21_single_line_token_dump_does_not_pass(tmp_path):
    """v0.118-stable: a single printf line dumping all tokens at once
    is NOT proof a full sequence ran. Must require ≥3 distinct lines."""
    _l8_proto(tmp_path)
    _rtl(tmp_path, "top.sv", "module top; endmodule\n")
    _fpga_artefact(tmp_path)
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "results.json").write_text(json.dumps({"verdict": "PASS"}))
    # All 5 tokens crammed onto one line — should NOT count as evidence
    (sim / "transcript.log").write_text(
        "[debug] state_dump: BR_PULSE rx_byte TX_RESP crc_match cmd_pass\n"
        "[INFO] sim done\n")
    import os, time
    new_t = time.time() + 100
    os.utime(sim / "results.json", (new_t, new_t))
    r = _run("protocol_ip_simulation_required_check", tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path, "protocol_ip_simulation_required_check")
    assert any(f["rule"] == "FULL_STACK_SIM_TRIVIAL"
               for f in rpt["findings"])
