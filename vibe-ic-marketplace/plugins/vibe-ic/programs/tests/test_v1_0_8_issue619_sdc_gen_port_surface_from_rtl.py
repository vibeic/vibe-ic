"""ORGANIC #619 [MEDIUM] — sdc_gen derived its port surface from the L9
doc-extracted top_module_pins (the FULL upstream IP surface, all config-gated
security/ECC/lockstep/debug ports present) instead of the synthesizable RTL
top. For a config-reduced-wrapper / REUSED-IP design (e.g. ibex with
SecureIbex(0)/ICacheECC(0)) the synthesizable chip_top exposes only the
enabled subset, so the emitted SDC named `get_ports` for ports that do not
exist on the elaborated netlist -> STA/PnR errors on those constraints.

Fix: in the L9-namespace branch, intersect the L9 pin list with the actual
synthesizable RTL port surface (union of all rtl/ module ports). A pin absent
from that surface is dropped. When rtl/ is absent/unparseable the union is
empty and NO filtering happens (pure-L9 fallback preserved).

POSITIVE (#619): the real ibex config-gated ports (instr_rdata_intg_i,
lockstep_cmp_en_o, alert_major_bus_o, scan_rst_ni, ram_cfg_i, *_shadow_o) are
dropped; the real functional ports survive.

NEGATIVE no-leak (the load-bearing half, §4.05):
  - a well-behaved IC (L9 top == synth top, all pins present) drops NOTHING.
  - no rtl/ dir -> union empty -> no filtering (every L9 pin still emitted).
  - an alias-renamed clock (top renamed clk_i->clk, inner keeps clk_i) is NOT
    dropped, because the union spans the inner module too.

chip-AGNOSTIC: pure Verilog module-header parsing + set membership; no chip
names. The real ibex discriminating port names are embedded verbatim.
"""
import json
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import sdc_gen as G  # noqa: E402
import _path_layout as _pl  # noqa: E402

# Real on-disk #619 ibex config-gated ports (absent from the synth surface).
IBEX_CONFIG_GATED = (
    "instr_rdata_intg_i", "data_rdata_intg_i", "data_wdata_intg_o",
    "lockstep_cmp_en_o", "alert_major_internal_o", "alert_major_bus_o",
    "crash_dump_o", "double_fault_seen_o", "ram_cfg_i", "scan_rst_ni",
)


def _mk(tmp_path, l9_pins, rtl_text=None, top="chip_top", clock_mhz=100.0):
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": clock_mhz}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": top, "top_module_pins": l9_pins}))
    if rtl_text is not None:
        rtl = _pl.rtl_dir(tmp_path)
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "chip_top.sv").write_text(rtl_text)


def _emitted_ports(tmp_path, top="chip_top"):
    G.main([str(tmp_path), "--top-name", top, "--force"])
    sdc = (_pl.fpga_early_dir(tmp_path) / f"{top}.sdc").read_text()
    return set(re.findall(r"get_ports\s+\{?\s*([A-Za-z_]\w*)", sdc))


# ── _collect_all_module_ports ──────────────────────────────────────────────

def test_collect_union_spans_all_modules():
    rtl = (
        "module chip_top (\n input clk, input [7:0] din, output [7:0] dout\n);\n"
        " chip_top__rcvar_inner u (.clk_i(clk));\nendmodule\n"
        "module chip_top__rcvar_inner (\n input clk_i, input [7:0] din\n);\n"
        "endmodule\n")
    import tempfile
    d = Path(tempfile.mkdtemp())
    rd = _pl.rtl_dir(d); rd.mkdir(parents=True)
    (rd / "chip_top.sv").write_text(rtl)
    names = G._collect_all_module_ports(G._list_rtl(d))
    assert {"clk", "din", "dout", "clk_i"} <= names


def test_collect_empty_when_no_rtl():
    import tempfile
    assert G._collect_all_module_ports(G._list_rtl(Path(tempfile.mkdtemp()))) == set()


# ── POSITIVE #619 ──────────────────────────────────────────────────────────

def test_config_gated_ports_dropped(tmp_path):
    pins = [{"name": "clk_i", "mode": "input"},
            {"name": "rst_ni", "mode": "input"},
            {"name": "instr_rdata_i", "mode": "input"},
            {"name": "data_rdata_o", "mode": "output"}]
    pins += [{"name": n, "mode": "input" if n.endswith("_i") else "output"}
             for n in IBEX_CONFIG_GATED]
    _mk(tmp_path, pins,
        "module chip_top (\n  input  clk_i,\n  input  rst_ni,\n"
        "  input  [31:0] instr_rdata_i,\n  output [31:0] data_rdata_o\n);\n"
        "endmodule\n")
    emitted = _emitted_ports(tmp_path)
    for gated in IBEX_CONFIG_GATED:
        assert gated not in emitted, f"{gated} does not exist on synth top (#619)"
    assert {"clk_i", "rst_ni", "instr_rdata_i", "data_rdata_o"} <= emitted


# ── NEGATIVE no-leak ────────────────────────────────────────────────────────

def test_well_behaved_ic_drops_nothing(tmp_path):
    pins = [{"name": "clk", "mode": "input"}, {"name": "reset_n", "mode": "input"},
            {"name": "din", "mode": "input"}, {"name": "dout", "mode": "output"}]
    _mk(tmp_path, pins,
        "module chip_top (\n input clk, input reset_n, "
        "input [7:0] din, output [7:0] dout\n);\nendmodule\n")
    emitted = _emitted_ports(tmp_path)
    assert {"clk", "reset_n", "din", "dout"} <= emitted


def test_no_rtl_pure_l9_fallback(tmp_path):
    pins = [{"name": "clk", "mode": "input"}, {"name": "din", "mode": "input"},
            {"name": "dout", "mode": "output"}]
    _mk(tmp_path, pins, rtl_text=None)  # no rtl/ dir
    emitted = _emitted_ports(tmp_path)
    assert {"clk", "din", "dout"} <= emitted, "no RTL -> must not filter"


def test_alias_renamed_clock_constrains_the_top_port(tmp_path):
    # top renamed clk_i->clk (#618 case): chip_top exposes `clk`, the inner
    # `*__rcvar_inner` keeps `clk_i`. #207 — the SDC must constrain the TOP
    # port `clk` (the only get_ports-able clock on the elaborated netlist), NOT
    # the inner net `clk_i`. The old union behaviour emitted
    # `create_clock [get_ports clk_i]`, which STA cannot resolve (clk_i is not a
    # top port) — a vacuous SDC. The clock now correctly binds to `clk`.
    pins = [{"name": "clk_i", "mode": "input"}, {"name": "din", "mode": "input"}]
    _mk(tmp_path, pins,
        "module chip_top (\n input clk, input [7:0] din\n);\n"
        " chip_top__rcvar_inner u (.clk_i(clk));\nendmodule\n"
        "module chip_top__rcvar_inner (\n input clk_i, input [7:0] din\n);\n"
        "endmodule\n")
    rc = G.main([str(tmp_path), "--top-name", "chip_top", "--force"])
    assert rc == 0, "the alias top has a real `clk` port — SDC must be valid"
    emitted = _emitted_ports(tmp_path)
    assert "din" in emitted
    assert "clk" in emitted, "clock must bind the REAL top port `clk` (#207)"
    assert "clk_i" not in emitted, (
        "clk_i is an inner net, not a top port — get_ports on it is invalid STA")
