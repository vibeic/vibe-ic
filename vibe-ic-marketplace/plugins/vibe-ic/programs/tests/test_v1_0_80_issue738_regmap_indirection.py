"""ORGANIC #738 — spec_example_smoke_tb register-map / address-indirection model
+ iface_conformance_v2 register-map CSR-name exclusion.

PRIMARY (spec_example_smoke_tb.py)
  The #728 gate only resolved a top-level `input=value -> output=value` row, so
  when the golden table addresses the DUT INDIRECTLY (operand fields are memory
  OFFSETS over an APB/AXI offset write -> CSR/RAM -> compute -> result-register
  readback) it found no direct row and silently returned NOT-APPLICABLE — a
  false-negative on EXACTLY the multi-stage/CSR/RAM class where functional bugs
  hide. The fix teaches the gate a register-map/indirection model: parse the
  offset-keyed golden, map the RTL bus ports STRUCTURALLY, and emit a directed
  write -> start -> readback sequence that asserts the golden result.

  END-STATE asserted here (not an intermediate):
    (a) the 驗收 indirected golden against a CORRECT apb_dsp -> rc 0 (PASS), the
        gate BUILT the directed write->start->readback sequence (NOT
        NOT-APPLICABLE);
    (b) the SAME golden against a BUGGY apb_dsp (lost-write CSR clobber) ->
        rc != 0 (BLOCK) — the bug the gate exists to catch;
    (c) §4.05 regression-guard: a register-map golden whose RTL exposes NO
        resolvable bus interface stays NOT-APPLICABLE (never false-blocks);
    (d) regression-guard: the direct-row #728 path is untouched (a direct
        `a=3,b=4 -> sum=7` golden still drives the combinational TB);
    (e) iverilog absent -> NOT-APPLICABLE (graceful degrade, no false-block).

SECONDARY (iface_conformance_v2.py)
  A name that occurs ONLY in a register-map 'Register Name' column (with an
  Offset/Address column) and is prose-tagged as an internal CSR is bus-accessed,
  NOT a top-level port — it must be EXCLUDED from MISSING-PORT noise. A genuine
  missing top-level port must still fire.

The iverilog end-to-end cases are gated on shutil.which; the pure
parsing/logic cases run WITHOUT any binary.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_SMOKE = _PROGRAMS / "spec_example_smoke_tb.py"
_IFACE = _PROGRAMS / "iface_conformance_v2.py"

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)

# the 驗收 indirected golden, verbatim shape
_IND_PROMPT = ("APB DSP. Write operand to offset 0x0, start via 0x8 bit0, "
               "read result at 0x14. Example: mem[0x0]=5, mem[0x4]=7 -> "
               "result(0x14)=35.\n")

# a CORRECT apb_dsp: writes op_a@0x0, op_b@0x4, ctrl@0x8; start bit0 launches
# op_a*op_b into result@0x14; APB-style read mux.
_RTL_OK = """\
module apb_dsp(
  input         pclk,
  input         presetn,
  input  [31:0] paddr,
  input  [31:0] pwdata,
  input         pwrite,
  input         psel,
  input         penable,
  output reg [31:0] prdata
);
  reg [31:0] op_a, op_b, result, ctrl;
  always @(posedge pclk or negedge presetn) begin
    if (!presetn) begin
      op_a <= 0; op_b <= 0; ctrl <= 0; result <= 0;
    end else begin
      if (psel && penable && pwrite) begin
        case (paddr[7:0])
          8'h00: op_a <= pwdata;
          8'h04: op_b <= pwdata;
          8'h08: ctrl <= pwdata;
        endcase
      end
      if (ctrl[0]) begin
        result <= op_a * op_b;
        ctrl   <= 0;
      end
    end
  end
  always @(*) begin
    case (paddr[7:0])
      8'h00: prdata = op_a;
      8'h04: prdata = op_b;
      8'h14: prdata = result;
      default: prdata = 32'h0;
    endcase
  end
endmodule
"""

# a BUGGY apb_dsp: the op_b write @0x4 is CLOBBERED onto op_a (lost-write) — so
# result = op_a*op_b with op_b still 0 -> readback 0 != 35.
_RTL_BUGGY = """\
module apb_dsp(
  input         pclk,
  input         presetn,
  input  [31:0] paddr,
  input  [31:0] pwdata,
  input         pwrite,
  input         psel,
  input         penable,
  output reg [31:0] prdata
);
  reg [31:0] op_a, op_b, result, ctrl;
  always @(posedge pclk or negedge presetn) begin
    if (!presetn) begin
      op_a <= 0; op_b <= 0; ctrl <= 0; result <= 0;
    end else begin
      if (psel && penable && pwrite) begin
        case (paddr[7:0])
          8'h00: op_a <= pwdata;
          8'h04: op_a <= pwdata;   // BUG: lost-write, op_b never updated
          8'h08: ctrl <= pwdata;
        endcase
      end
      if (ctrl[0]) begin
        result <= op_a * op_b;
        ctrl   <= 0;
      end
    end
  end
  always @(*) begin
    case (paddr[7:0])
      8'h00: prdata = op_a;
      8'h04: prdata = op_b;
      8'h14: prdata = result;
      default: prdata = 32'h0;
    endcase
  end
endmodule
"""

# an RTL with NO resolvable bus interface (no addr/wdata/rdata triplet).
_RTL_NO_BUS = ("module apb_dsp(input clk, input a, output b);\n"
               "  assign b = a;\nendmodule\n")


def _write(tmp_path, prompt, rtl):
    p = tmp_path / "s.txt"
    r = tmp_path / "dut.sv"
    p.write_text(prompt)
    r.write_text(rtl)
    return p, r


def _run_smoke(prompt_path, rtl_path, top="apb_dsp", env=None):
    return subprocess.run(
        [sys.executable, str(_SMOKE), "--prompt", str(prompt_path),
         "--rtl", str(rtl_path), "--top", top],
        capture_output=True, text=True, env=env)


# ── PRIMARY: register-map / indirection model ────────────────────────────────

def test_extraction_parses_indirection_golden():
    """Pure-logic (no binary): the offset-keyed golden parses — operand writes,
    start register+bit, result offset+expected — proving the new executable
    path is reachable even on a binary-less CI host."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    g = m.extract_indirection_golden(_IND_PROMPT)
    assert g is not None, "the indirected golden must parse"
    assert (0x0, 5) in g.operand_writes
    assert (0x4, 7) in g.operand_writes
    assert g.start_offset == 0x8
    assert g.start_bit == 0
    assert g.result_offset == 0x14
    assert g.expected == 35


def test_bus_port_role_resolution_structural():
    """Pure-logic: the RTL bus ports resolve to APB roles by structural name
    shape only (no chip/SKU literal)."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    _, ports = m._SRC.parse_rtl_ports(_RTL_OK, "apb_dsp")
    in_ports = {p.name: max(1, p.width) for p in ports if p.direction == "input"}
    out_ports = {p.name: max(1, p.width) for p in ports if p.direction == "output"}
    bus = m.resolve_bus_ports(in_ports, out_ports)
    assert bus is not None
    assert bus.addr == "paddr"
    assert bus.wdata == "pwdata"
    assert bus.rdata == "prdata"
    assert bus.family == "apb"  # psel + penable present
    assert bus.rst_active_low is True  # presetn


def test_no_bus_interface_resolves_none():
    """Pure-logic §4.05 guard: an RTL with no addr/wdata/rdata triplet resolves
    to None (the gate will then stay NOT-APPLICABLE, never mis-drive)."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    _, ports = m._SRC.parse_rtl_ports(_RTL_NO_BUS, "apb_dsp")
    in_ports = {p.name: max(1, p.width) for p in ports if p.direction == "input"}
    out_ports = {p.name: max(1, p.width) for p in ports if p.direction == "output"}
    assert m.resolve_bus_ports(in_ports, out_ports) is None


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_a_acceptance_correct_dut_builds_sequence_and_passes(tmp_path):
    """驗收 END-STATE: for the indirected register-map golden the gate BUILDS the
    write->start->readback sequence and asserts the golden result against a
    CORRECT apb_dsp -> rc 0 (PASS), NOT NOT-APPLICABLE."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_OK)
    cp = _run_smoke(p, r)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS" in cp.stdout
    assert "NOT-APPLICABLE" not in cp.stdout
    assert "[indirection]" in cp.stdout
    assert "SPEC_EXAMPLE_PASS indirected" in cp.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_b_buggy_lost_write_dut_blocks(tmp_path):
    """END-STATE: the SAME golden against a BUGGY apb_dsp (lost-write CSR
    clobber) -> rc != 0 (BLOCK). This is the regression the gate exists to
    catch and that #728's direct model silently no-op'd."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_BUGGY)
    cp = _run_smoke(p, r)
    assert cp.returncode != 0, cp.stdout + cp.stderr
    assert "BLOCK" in cp.stdout
    assert "SPEC_EXAMPLE_FAIL indirected" in cp.stdout


def test_c_indirection_golden_no_bus_stays_not_applicable(tmp_path):
    """§4.05 guard (no binary needed — declines before sim): a register-map
    golden whose RTL exposes NO resolvable bus interface stays NOT-APPLICABLE,
    NEVER a false BLOCK."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_NO_BUS)
    cp = _run_smoke(p, r)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "NOT-APPLICABLE" in cp.stdout


def test_c2_no_golden_at_all_not_applicable(tmp_path):
    """§4.05 guard: a prompt with neither a direct row nor an indirected golden
    stays NOT-APPLICABLE (no false BLOCK)."""
    bare = ("APB DSP peripheral. Has an APB slave interface. No worked example "
            "is stated.\n")
    p, r = _write(tmp_path, bare, _RTL_OK)
    cp = _run_smoke(p, r)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "NOT-APPLICABLE" in cp.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_d_direct_row_path_intact_regression_guard(tmp_path):
    """REGRESSION-GUARD: the prior #728 direct-row behaviour is intact — a
    direct `a=3,b=4 -> sum=7` golden still drives the combinational TB and
    BLOCKs an always-0 adder, PASSes a correct one."""
    prompt = ("Module add2. Example: a=3,b=4 -> sum=7. "
              "Inputs a[7:0],b[7:0]; output sum[8:0].\n")
    wrong = ("module add2(input [7:0] a,b, output [8:0] sum); "
             "assign sum=8'd0; endmodule\n")
    ok = ("module add2(input [7:0] a,b, output [8:0] sum); "
          "assign sum=a+b; endmodule\n")
    p, r = _write(tmp_path, prompt, wrong)
    cp = _run_smoke(p, r, top="add2")
    assert cp.returncode != 0, cp.stdout + cp.stderr
    assert "SPEC_EXAMPLE_FAIL row" in cp.stdout  # direct-row TB, not indirection
    r.write_text(ok)
    cp2 = _run_smoke(p, r, top="add2")
    assert cp2.returncode == 0, cp2.stdout + cp2.stderr
    assert "PASS" in cp2.stdout


def test_e_iverilog_absent_graceful(tmp_path):
    """§4.05: iverilog absent -> NOT-APPLICABLE (graceful degrade, no false
    block) even though a register-map golden was extractable."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_OK)
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    real_py = shutil.which("python3") or sys.executable
    try:
        os.symlink(real_py, fakebin / "python3")
    except OSError:
        pass
    env = dict(os.environ)
    env["PATH"] = str(fakebin)
    cp = _run_smoke(p, r, env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "NOT-APPLICABLE" in cp.stdout


# ── SECONDARY: iface_conformance_v2 register-map CSR-name exclusion ──────────

_REGMAP_PROMPT = """\
APB DSP peripheral.

Top-level interface ports:
| Signal | Direction | Width |
|--------|-----------|-------|
| `pclk` | input | 1 |
| `paddr` | input | 32 |
| `prdata` | output | 32 |

The internal register map (these are CSRs accessed through the bus, they are
NOT top-level ports of the module):
| Register Name | Access | Offset |
|---------------|--------|--------|
| `op_a_reg` | input | 0x0 |
| `op_b_reg` | input | 0x4 |
| `result_reg` | output | 0x14 |
"""

_REGMAP_RTL = ("module apb_dsp(input pclk, input [31:0] paddr, "
               "output reg [31:0] prdata);\nendmodule\n")


def _run_iface(prompt_path, rtl_path, strict=False):
    args = [sys.executable, str(_IFACE), "--prompt", str(prompt_path),
            "--rtl", str(rtl_path)]
    if strict:
        args.append("--strict")
    return subprocess.run(args, capture_output=True, text=True)


def test_secondary_regmap_csr_names_excluded(tmp_path):
    """END-STATE: internal-CSR register-map names (prose-tagged 'NOT top-level
    ports', table has a Register Name + Offset column) are EXCLUDED from
    MISSING-PORT — even in --strict the gate is clean (rc 0)."""
    p = tmp_path / "p.txt"
    r = tmp_path / "dut.sv"
    p.write_text(_REGMAP_PROMPT)
    r.write_text(_REGMAP_RTL)
    cp = _run_iface(p, r, strict=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "op_a_reg" not in cp.stdout
    assert "op_b_reg" not in cp.stdout
    assert "result_reg" not in cp.stdout
    assert "interface-conformance ok" in cp.stdout


def test_secondary_pure_logic_regmap_set():
    """Pure-logic: regmap_csr_names returns the CSR names only when BOTH the
    table shape (Register Name + Offset columns) AND internal-CSR prose are
    present."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import iface_conformance_v2 as m
    finally:
        sys.path.pop(0)
    got = m.regmap_csr_names(_REGMAP_PROMPT)
    assert got == {"op_a_reg", "op_b_reg", "result_reg"}
    # no internal-CSR prose -> empty set (a plain interface table never matches)
    plain = ("| Signal | Direction |\n|---|---|\n| `clk` | input |\n"
             "| `q` | output |\n")
    assert m.regmap_csr_names(plain) == set()


def test_secondary_genuine_missing_port_still_fires(tmp_path):
    """REGRESSION-GUARD: a GENUINE missing top-level port (named in a real port
    interface table with a Direction column, NO internal-CSR prose) still fires
    MISSING-PORT — the exclusion must not mask a real signal."""
    prompt = ("APB DSP peripheral with these top-level ports:\n"
              "| Signal | Direction | Width |\n|---|---|---|\n"
              "| `pclk` | input | 1 |\n| `paddr` | input | 32 |\n"
              "| `prdata` | output | 32 |\n| `pwrite` | input | 1 |\n")
    p = tmp_path / "p.txt"
    r = tmp_path / "dut.sv"
    p.write_text(prompt)
    r.write_text(_REGMAP_RTL)
    cp = _run_iface(p, r, strict=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "MISSING-PORT" in cp.stdout
    assert "pwrite" in cp.stdout


def test_secondary_regmap_name_that_is_real_port_not_masked(tmp_path):
    """REGRESSION-GUARD: if a register-map name ALSO happens to be a real RTL
    port, the exclusion does NOT mask the direction comparison — it only skips
    the MISSING-PORT charge when the name is absent from every module."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import iface_conformance_v2 as m
    finally:
        sys.path.pop(0)
    # prdata is a register-map row AND a real top port; it must not be reported
    # missing and must remain available for the normal port checks.
    prompt = _REGMAP_PROMPT.replace("`result_reg`", "`prdata`")
    findings = m.check_conformance(None, prompt, _REGMAP_RTL)
    kinds = {(f.kind, "prdata" in f.message) for f in findings}
    assert ("MISSING-PORT", True) not in kinds


# ── #738 r2 REMEDIATION: adversarial-review findings ─────────────────────────
# Two reproduced findings in the register-map / indirection model:
#  (1) HIGH  — FALSE-BLOCK on an active-low reset whose NAME lacks a trailing 'n'
#              (bare `reset`/`rst`): resolve_bus_ports classified it active-HIGH,
#              the TB held reset asserted forever, the DUT stayed in reset, the
#              readback read 0, and a FUNCTIONALLY-CORRECT DUT was BLOCKed.
#              FIX: a polarity-AMBIGUOUS reset name tries BOTH polarities; PASS if
#              EITHER matches; BLOCK only if BOTH mismatch (a real bug).
#  (2) MEDIUM — extract_indirection_golden double-counted the RESULT offset (and a
#              prose START offset) as an OPERAND write because `_OFFSET_WRITE_RE`
#              matches `offset N = V`. FIX: EXCLUDE start_offset and result_offset
#              from operand_writes.

# the apb_mac_lr DUT from the reviewer repro: a CORRECT MAC computing opa*opb,
# with an ACTIVE-LOW reset whose name is bare `reset` (no trailing 'n').
_RTL_LR_RESET_OK = """\
module apb_mac_lr(
  input         pclk,
  input         reset,
  input  [31:0] paddr,
  input  [31:0] pwdata,
  input         pwrite,
  input         psel,
  input         penable,
  output reg [31:0] prdata
);
  reg [31:0] opa, opb, result, ctrl;
  always @(posedge pclk or negedge reset) begin
    if (!reset) begin
      opa <= 0; opb <= 0; ctrl <= 0; result <= 0;
    end else begin
      if (psel && penable && pwrite) begin
        case (paddr[7:0])
          8'h00: opa <= pwdata;
          8'h04: opb <= pwdata;
          8'h08: ctrl <= pwdata;
        endcase
      end
      if (ctrl[0]) begin
        result <= opa * opb;
        ctrl   <= 0;
      end
    end
  end
  always @(*) begin
    case (paddr[7:0])
      8'h00: prdata = opa;
      8'h04: prdata = opb;
      8'h14: prdata = result;
      default: prdata = 32'h0;
    endcase
  end
endmodule
"""

# same MAC but the reset is genuinely ACTIVE-HIGH, still a bare `reset` name.
_RTL_AH_RESET_OK = _RTL_LR_RESET_OK.replace(
    "always @(posedge pclk or negedge reset)",
    "always @(posedge pclk or posedge reset)").replace(
    "if (!reset) begin", "if (reset) begin")

# a genuinely BUGGY MAC (op_b write @0x4 clobbered onto op_a) with the SAME bare
# active-low `reset` name — try-both must NOT mask the real functional bug.
_RTL_LR_RESET_BUGGY = _RTL_LR_RESET_OK.replace(
    "8'h04: opb <= pwdata;", "8'h04: opa <= pwdata;")


def test_finding1_ambiguous_reset_polarity_classified_ambiguous():
    """Pure-logic: a bare `reset` (no trailing 'n', no active-high marker) is
    classified rst_polarity=='ambiguous' (NOT 'high'); a trailing-'n' name is
    'low'; an explicit positive marker is 'high'."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    assert m._rst_polarity("reset") == "ambiguous"
    assert m._rst_polarity("rst") == "ambiguous"
    assert m._rst_polarity("presetn") == "low"
    assert m._rst_polarity("rst_n") == "low"
    assert m._rst_polarity("aresetn") == "low"
    assert m._rst_polarity("rst_p") == "high"
    assert m._rst_polarity("reset_pos") == "high"
    assert m._rst_polarity("por") == "high"
    # the canonical presetn DUT still resolves rst_active_low True (back-compat).
    _, ports = m._SRC.parse_rtl_ports(_RTL_OK, "apb_dsp")
    inp = {p.name: max(1, p.width) for p in ports if p.direction == "input"}
    out = {p.name: max(1, p.width) for p in ports if p.direction == "output"}
    bus = m.resolve_bus_ports(inp, out)
    assert bus.rst_polarity == "low" and bus.rst_active_low is True


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_finding1_active_low_bare_reset_no_false_block(tmp_path):
    """REVIEWER REPRO (HIGH): a CORRECT apb_mac_lr with an ACTIVE-LOW reset named
    bare `reset` must NOT be false-BLOCKed. Before the fix the gate printed
    'BLOCK: ... result(0x14) expected 35 got 0' EXIT=1; after the fix the gate
    tries BOTH polarities and PASSes via the active-low release."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_LR_RESET_OK)
    cp = _run_smoke(p, r, top="apb_mac_lr")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS" in cp.stdout
    assert "BLOCK" not in cp.stdout
    assert "result(0x14) expected 35 got 0" not in cp.stdout
    # it actually built+ran the directed sequence (not NOT-APPLICABLE).
    assert "SPEC_EXAMPLE_PASS indirected" in cp.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_finding1_same_dut_renamed_presetn_still_passes(tmp_path):
    """REVIEWER REPRO control: the SAME DUT renamed `presetn` (unambiguous
    active-low) still PASSes single-polarity — the fix did not regress the
    clear-name path."""
    rtl = _RTL_LR_RESET_OK.replace(
        "input         reset,", "input         presetn,").replace(
        "negedge reset)", "negedge presetn)").replace(
        "if (!reset)", "if (!presetn)")
    p, r = _write(tmp_path, _IND_PROMPT, rtl)
    cp = _run_smoke(p, r, top="apb_mac_lr")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS" in cp.stdout
    # a clear active-low name does NOT take the ambiguous try-both note.
    assert "polarity-ambiguous" not in cp.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_finding1_active_high_bare_reset_passes_via_try_both(tmp_path):
    """END-STATE: a CORRECT MAC whose bare `reset` is genuinely ACTIVE-HIGH also
    PASSes — try-both covers the active-high polarity too (the ambiguous name is
    never guessed-and-held one way)."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_AH_RESET_OK)
    cp = _run_smoke(p, r, top="apb_mac_lr")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS" in cp.stdout
    assert "active-high" in cp.stdout  # matched on the active-high attempt


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_finding1_try_both_does_not_mask_real_bug(tmp_path):
    """ASYMMETRY GUARD: a genuinely BUGGY MAC with the SAME bare `reset` name must
    still BLOCK — trying BOTH polarities must not turn a real functional bug into
    a false-PASS (both polarities mismatch -> BLOCK)."""
    p, r = _write(tmp_path, _IND_PROMPT, _RTL_LR_RESET_BUGGY)
    cp = _run_smoke(p, r, top="apb_mac_lr")
    assert cp.returncode != 0, cp.stdout + cp.stderr
    assert "BLOCK" in cp.stdout
    assert "tried BOTH reset polarities" in cp.stdout
    assert "SPEC_EXAMPLE_FAIL indirected" in cp.stdout


def test_finding2_result_offset_not_double_counted_as_operand():
    """REVIEWER REPRO (MEDIUM), verbatim input: the RESULT offset must NOT appear
    in operand_writes. Before the fix
        extract_indirection_golden('Write 5 to offset 0x0. Write 7 to offset
        0x4. Start via 0x8 bit0. Read the result. result offset 0x14 = 35.')
    returned operand_writes=[(0,5),(4,7),(20,35)] (20 = result offset
    double-counted via `_OFFSET_WRITE_RE` matching `offset N = V`)."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    g = m.extract_indirection_golden(
        "Write 5 to offset 0x0. Write 7 to offset 0x4. Start via 0x8 bit0. "
        "Read the result. result offset 0x14 = 35.")
    assert g is not None
    assert g.operand_writes == [(0, 5), (4, 7)], g.operand_writes
    assert (0x14, 35) not in g.operand_writes  # the result offset is excluded
    assert g.start_offset == 0x8
    assert g.result_offset == 0x14
    assert g.expected == 35


def test_finding2_start_offset_not_double_counted_as_operand():
    """REVIEWER REPRO (MEDIUM): a prose `write 1 to offset 0x8 to start` plus a
    `result offset 0x14 = 35` must NOT add (0x8,1) or (0x14,35) to operand_writes
    — both the START and RESULT registers are excluded from the operand set."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    g = m.extract_indirection_golden(
        "Write 5 to offset 0x0. Write 7 to offset 0x4. write 1 to offset 0x8 "
        "to start the compute via 0x8. result offset 0x14 = 35.")
    assert g is not None
    assert g.operand_writes == [(0, 5), (4, 7)], g.operand_writes
    assert (0x8, 1) not in g.operand_writes
    assert (0x14, 35) not in g.operand_writes


def test_finding2_motivating_738_parenthesized_case_intact():
    """REGRESSION-GUARD: the #738 motivating parenthesized golden
    `result(0x14)=35` (bracketed `mem[..]=..` operand writes) still extracts
    exactly operand_writes=[(0,5),(4,7)] with result_offset 0x14 / expected 35 —
    the exclusion is a no-op for it (it never double-counted)."""
    sys.path.insert(0, str(_PROGRAMS))
    try:
        import spec_example_smoke_tb as m
    finally:
        sys.path.pop(0)
    g = m.extract_indirection_golden(_IND_PROMPT)
    assert g is not None
    assert g.operand_writes == [(0, 5), (4, 7)], g.operand_writes
    assert g.result_offset == 0x14
    assert g.expected == 35


# ── #478 defect-artifact + end-state: shape the issue's ## 驗收 artifact DIRECTLY
# in tmp_path and assert the END state via the real program's main() entrypoint.
# Mirrors the issue body verbatim:
#   printf 'APB DSP. ... Example: mem[0x0]=5, mem[0x4]=7 -> result(0x14)=35.' > ind.txt
#   python3 programs/spec_example_smoke_tb.py --prompt ind.txt --rtl <dut>.sv --top apb_dsp
def _load_smoke():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "spec_example_smoke_tb", str(_SMOKE))
    mod = importlib.util.module_from_spec(spec)
    if str(_PROGRAMS) not in sys.path:
        sys.path.insert(0, str(_PROGRAMS))
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_acceptance_indirected_golden_endstate_via_program(tmp_path):
    """END-STATE via the real program's main() on a tmp_path-shaped defect
    artifact: for the indirected/register-map golden the gate BUILDS the
    write->start->readback sequence and PASSES a correct DUT (rc 0) instead of
    returning NOT-APPLICABLE (the #738 false-negative) — and does NOT false-BLOCK
    it (the ambiguous-reset HIGH remediation)."""
    (tmp_path / "ind.txt").write_text(_IND_PROMPT)
    (tmp_path / "apb_dsp.sv").write_text(_RTL_OK)
    mod = _load_smoke()
    rc = mod.main(["--prompt", str(tmp_path / "ind.txt"),
                   "--rtl", str(tmp_path / "apb_dsp.sv"), "--top", "apb_dsp"])
    assert rc == 0, rc   # correct DUT: not false-blocked, not silent N/A


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
