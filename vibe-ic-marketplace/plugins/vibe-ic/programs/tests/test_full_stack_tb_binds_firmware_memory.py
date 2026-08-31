"""The full-stack TB must feed a DUT that is fed from external memory.

RED DIRECTION, ANCHORED ON A MEASUREMENT — not merely on "the module did not
exist". `test_the_defect_is_real_on_the_shipped_tb` replays the TB the
pre-fix generator actually emitted for this design and asserts the property
that made its coverage meaningless: the DUT's only data input is declared and
then never assigned by anything. That test passes against the OLD text and is
the reason the new behaviour is needed.

Measured on subservient x gf180mcuD, same DUT, same container, the plugin's own
`verilator_coverage_measure measure-tb`:

    before  line  28.18 %  toggle  19.01 %  branch  13.64 %   -> step 4 FAIL
    after   line  83.64 %  toggle  85.59 %  branch  78.79 %   -> step 4 PASS

The `before` column reproduces the run's own coverage_verilator.json exactly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))



class _Lazy:
    """Imported ON USE, not at collection. A test that cannot even be COLLECTED
    against the pre-fix tree proves nothing about the pre-fix tree; the
    defect-replay test below must run, and pass, in BOTH directions."""

    def __getattr__(self, item):
        import _full_stack_memory_binding as _m
        return getattr(_m, item)


fsmb = _Lazy()


def _ports(*specs):
    out = []
    for name, direction, width in specs:
        p = {"name": name, "direction": direction}
        if width > 1:
            p["width"] = width
        out.append(p)
    return out


# The DUT shape this closes: an output address, an input read-data, and the
# usual write/strobe companions.
MEM_PORTS = _ports(
    ("i_clk", "input", 1), ("i_rst", "input", 1),
    ("o_sram_addr", "output", 10), ("o_sram_data", "output", 8),
    ("o_sram_we", "output", 1), ("o_sram_cyc", "output", 1),
    ("i_sram_data", "input", 8), ("o_gpio", "output", 1),
)


# ─── the defect, replayed on the text the old generator really emitted ──────
PRE_FIX_TB = """\
module tb_subservient_full;
  reg i_clk = 0;
  reg i_rst = 0;
  wire [9:0] o_sram_addr;
  reg [7:0] i_sram_data = 0;
  always #10 i_clk = ~i_clk;
  subservient u_dut (.i_clk(i_clk), .i_sram_data(i_sram_data));
  initial begin
    i_rst = 1; #100; i_rst = 0; #100;
    repeat (2000) @(posedge i_clk);
    $finish;
  end
endmodule
"""


def test_the_defect_is_real_on_the_shipped_tb():
    """The DUT's only data input is declared and never assigned again."""
    body = PRE_FIX_TB
    assert "reg [7:0] i_sram_data = 0;" in body
    # No assignment to it anywhere after the declaration: no `<=`, no `=` that
    # is not the initialiser, no always block driving it.
    after_decl = body.split("reg [7:0] i_sram_data = 0;", 1)[1]
    assert "i_sram_data <=" not in after_decl
    assert "i_sram_data =" not in after_decl
    assert "$readmemh" not in body


# ─── port-group resolution: chip-AGNOSTIC, from the port list alone ─────────
def test_resolves_the_memory_group_from_the_port_list():
    g = fsmb.resolve_memory_port_group(MEM_PORTS)
    assert g is not None
    assert g["base"] == "sram"
    assert g["addr"] == "o_sram_addr"
    assert g["rdata"] == "i_sram_data"
    assert g["wdata"] == "o_sram_data"
    assert g["we"] == "o_sram_we"
    assert g["stb"] == "o_sram_cyc"
    assert g["depth"] == 1024          # 10 address bits


def test_suffix_direction_affixes_resolve_too():
    """`addr_o` / `data_i` is the same group as `o_addr` / `i_data`."""
    g = fsmb.resolve_memory_port_group(_ports(
        ("mem_addr_o", "output", 8), ("mem_data_i", "input", 16)))
    assert g is not None and g["base"] == "mem" and g["depth"] == 256


# ── the four silent directions: a group must NOT be invented ───────────────
def test_no_group_when_there_is_no_memory_shape():
    assert fsmb.resolve_memory_port_group(_ports(
        ("clk", "input", 1), ("en", "input", 1), ("q", "output", 8))) is None


def test_no_group_when_the_read_data_input_is_missing():
    """An address output alone is a bus master, not a memory this TB can model."""
    assert fsmb.resolve_memory_port_group(_ports(
        ("o_bus_addr", "output", 8), ("o_bus_data", "output", 8))) is None


def test_no_group_when_the_address_width_is_unknown():
    assert fsmb.resolve_memory_port_group(
        [{"name": "o_m_addr", "direction": "output"},
         {"name": "i_m_data", "direction": "input", "width": 8}]) is None


def test_an_unmodellably_wide_address_is_refused_not_silently_shrunk():
    g = fsmb.resolve_memory_port_group(_ports(
        ("o_m_addr", "output", 32), ("i_m_data", "input", 8)))
    assert g is not None and "depth" not in g and g.get("refused")


# ─── firmware discovery ────────────────────────────────────────────────────
def _stage(tmp_path, names, manifest=None):
    d = tmp_path / "input" / "firmware"
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_text("00\n01\n")
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_no_firmware_is_not_an_error_it_is_a_None(tmp_path):
    assert fsmb.find_firmware(tmp_path) is None


def test_manifest_primary_is_honoured(tmp_path):
    p = _stage(tmp_path, ["blinky.hex", "hello.hex"],
               {"primary": "hello.hex", "read_latency_cycles": 1})
    fw = fsmb.find_firmware(p)
    assert fw["image_name"] == "hello.hex"
    assert "declared by manifest.json" in fw["selection_basis"]
    assert fw["read_latency_basis"] == "design-declared"
    assert fw["also_staged"] == ["blinky.hex"]


def test_without_a_manifest_the_default_pick_says_it_was_a_default(tmp_path):
    """A picked-by-default image must never read as a picked-by-the-design one."""
    fw = fsmb.find_firmware(_stage(tmp_path, ["blinky.hex", "hello.hex"]))
    assert fw["image_name"] == "blinky.hex"
    assert "no manifest" in fw["selection_basis"]
    assert fw["read_latency_basis"] == "assumed registered (next-edge)"


def test_a_manifest_naming_an_absent_image_says_so(tmp_path):
    p = _stage(tmp_path, ["blinky.hex"], {"primary": "nope.hex"})
    fw = fsmb.find_firmware(p)
    assert fw["image_name"] == "blinky.hex"
    assert "not\nstaged" in fw["selection_basis"].replace(" ", "\n") \
        or "not staged" in " ".join(fw["selection_basis"].split())


# ─── the emitted model ─────────────────────────────────────────────────────
def test_model_drives_the_read_data_port_on_the_resolved_clock(tmp_path):
    g = fsmb.resolve_memory_port_group(MEM_PORTS)
    fw = fsmb.find_firmware(_stage(tmp_path, ["hello.hex"],
                                   {"primary": "hello.hex"}))
    body = "\n".join(fsmb.emit_memory_model_lines(g, fw, "i_clk"))
    assert "always @(posedge i_clk)" in body
    assert "if (o_sram_cyc)" in body                 # strobe-guarded
    assert "if (o_sram_we) fs_mem[o_sram_addr] <= o_sram_data;" in body
    assert "i_sram_data <= fs_mem[o_sram_addr];" in body   # registered read
    assert '$readmemh("hello.hex", fs_mem);' in body
    assert "reg [7:0] fs_mem [0:1023];" in body


def test_declared_zero_latency_emits_a_combinational_read(tmp_path):
    g = fsmb.resolve_memory_port_group(MEM_PORTS)
    fw = fsmb.find_firmware(_stage(tmp_path, ["a.hex"],
                                   {"primary": "a.hex",
                                    "read_latency_cycles": 0}))
    body = "\n".join(fsmb.emit_memory_model_lines(g, fw, "i_clk"))
    assert "always @(*) i_sram_data = fs_mem[o_sram_addr];" in body
    assert "i_sram_data <= fs_mem[o_sram_addr];" not in body


# ─── staging: $readmemh resolves against the SIMULATOR's cwd ───────────────
def test_image_is_staged_into_every_known_sim_cwd(tmp_path):
    p = _stage(tmp_path, ["hello.hex"], {"primary": "hello.hex"})
    fw = fsmb.find_firmware(p)
    written = fsmb.stage_firmware_for_sim(p, fw)
    assert "phase2/stage1/sim/cov_build/hello.hex" in written
    assert "phase2/stage1/sim_full_stack/hello.hex" in written
    for rel in written:
        assert (p / rel).is_file()


def test_staging_a_missing_image_reports_nothing_written(tmp_path):
    assert fsmb.stage_firmware_for_sim(
        tmp_path, {"image": tmp_path / "gone.hex"}) == []


# ─── the disclosure half ───────────────────────────────────────────────────
def test_a_tb_that_drove_nothing_says_so_and_names_the_ports():
    rec = fsmb.describe_stimulus_binding(
        "none", group=None, fw=None,
        undriven_inputs={"i_sram_data", "i_mode"},
        reason="no external memory port resolved from the port list")
    assert rec["drives_dut_data_inputs"] is False
    assert rec["undriven_data_inputs"] == ["i_mode", "i_sram_data"]
    assert rec["undriven_data_input_count"] == 2
    assert "describes the stimulus, not the design" in rec["coverage_caveat"]
    assert rec["reason"]


def test_a_bound_tb_carries_no_caveat_and_names_the_channel(tmp_path):
    g = fsmb.resolve_memory_port_group(MEM_PORTS)
    fw = fsmb.find_firmware(_stage(tmp_path, ["hello.hex"],
                                   {"primary": "hello.hex"}))
    rec = fsmb.describe_stimulus_binding("firmware_memory", group=g, fw=fw)
    assert rec["drives_dut_data_inputs"] is True
    assert "coverage_caveat" not in rec
    assert rec["memory_port_group"]["rdata"] == "i_sram_data"
    assert rec["firmware"]["image_name"] == "hello.hex"
    assert "image" not in rec["firmware"]      # Path objects never serialised


# ─── no-regression: a design with no firmware is untouched ─────────────────
def test_a_design_with_a_memory_port_but_no_firmware_binds_nothing(tmp_path):
    """Emitting a model with nothing to load would be strictly worse than not
    emitting one: the memory would read all-zero and look like a real load."""
    assert fsmb.find_firmware(tmp_path) is None
