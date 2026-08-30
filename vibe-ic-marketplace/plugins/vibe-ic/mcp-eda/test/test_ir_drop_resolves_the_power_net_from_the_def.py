#!/usr/bin/env python3
"""eda_ir_drop must read the power NET from the DEF, not the std-cell PIN name.

MEASURED on 192.168.1.121, container vibeic-eda, OpenROAD 26Q3-1887-g24ea077e76:

    eda_pnr {netlist:cnt_net.v, top_module:cnt, pdk:sky130, output_def:mcp_pnr.def}
      -> success:true, area_um2:269, slack_ns:8.88
    eda_ir_drop {def_file:mcp_pnr.def, pdk:sky130}
      -> success:false  "[ERROR PSM-0028] Cannot find net VPWR in the design."

eda_ir_drop could not read a DEF its own sibling had just written. The two tools
disagreed about what `vdd_pin` means:

    eda_pnr      add_global_connection -net VDD -pin_pattern "${cfg.vdd_pin}"
                 -> the DEF's SPECIALNETS are named VDD / VSS
    eda_ir_drop  const vddNet = cfg.vdd_pin || "VDD"   -> asks PSM for VPWR

`vdd_pin` is sky130's std-cell PIN name (VPWR); the NET is VDD. gf180 and
nangate45 use VDD/VSS for both, which is why this was invisible on two thirds of
the corpus. Probed ground truth on the DEF eda_pnr writes:
PSM_PWR_NETS=VDD, PSM_GND_NETS=VSS.

Consequence: every sky130 ir_drop PASS recorded before the 2026-08-27 exit-code
hardening is vacuous (the same run reported success:true), and since then the
sky130 power step has been red rather than measured. Either way the number never
existed.

The fix does not substitute a better guess — guessing is what caused the bug. It
adds pdkConfig.vdd_net/vss_net (the NET eda_pnr creates, one source for both
tools) and makes eda_ir_drop resolve the net from the supplied DEF: enumerate the
block's POWER/GROUND nets, prefer a candidate, accept a single unambiguous net
(so an OpenLane DEF that really is named VPWR works too), and otherwise REFUSE as
NOT_MEASURED rather than analyse a name nobody confirmed.
"""
import re
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
SRC = (MCP_ROOT / "src" / "index.js").read_text()


def _tool(name: str) -> str:
    """The whole tool body: from its name to the next server.tool( registration."""
    i = SRC.find(f'"{name}"')
    assert i > 0, f"tool {name} not found"
    j = SRC.find("server.tool(", i)
    return SRC[i:j if j > 0 else len(SRC)]


def test_pdkconfig_separates_the_net_name_from_the_pin_name():
    """sky130 is the PDK where the two genuinely differ — the regression case."""
    i = SRC.find("sky130: {")
    assert i > 0
    blk = SRC[i:i + 1200]
    assert 'vdd_pin: "VPWR"' in blk, "sky130 std-cell pin name changed"
    assert 'vdd_net: "VDD"' in blk, "sky130 has no vdd_net — the NET name eda_pnr writes"
    assert 'vss_net: "VSS"' in blk
    # Every PDK config with a vdd_pin must also declare a vdd_net, so a PDK added
    # later cannot reintroduce the ambiguity. Match DECLARATION lines only — the
    # token also appears in the comment prose above each entry, and counting
    # occurrences instead of declarations is how this assertion first went wrong.
    cfg = SRC[SRC.index("function pdkConfig("):SRC.index('  if (pdk === "custom"')]
    decl = lambda k: len(re.findall(rf"^\s+{k}:\s*\S", cfg, re.M))
    assert decl("vdd_pin") > 0 and decl("vdd_pin") == decl("vdd_net"), (
        f"a pdkConfig PDK entry declares vdd_pin without vdd_net "
        f"(vdd_pin={decl('vdd_pin')}, vdd_net={decl('vdd_net')})"
    )
    assert decl("vss_pin") == decl("vss_net")


def test_pnr_builds_the_pdn_from_vdd_net_not_a_literal():
    """The net name must have ONE source, shared with its consumers."""
    t = _tool("eda_pnr")
    assert "add_global_connection -net ${cfg.vdd_net}" in t
    assert "add_global_connection -net ${cfg.vss_net}" in t
    assert "set_voltage_domain -power ${cfg.vdd_net} -ground ${cfg.vss_net}" in t
    assert "add_global_connection -net VDD " not in t, "PDN net name is hardcoded again"


def test_ir_drop_never_uses_the_pin_name_as_a_net():
    t = _tool("eda_ir_drop")
    assert "cfg.vdd_pin ||" not in t, (
        "eda_ir_drop is treating the std-cell PIN name as a NET name again — "
        "this is the exact PSM-0028 regression"
    )
    assert "analyze_power_grid -net ${vddNet}" not in t


def test_ir_drop_resolves_the_net_from_the_def_and_can_refuse():
    t = _tool("eda_ir_drop")
    # resolves by reading the artefact
    assert "getSigType" in t and "PSM_PWR_NETS=" in t and "PSM_GND_NETS=" in t
    assert "PSM_VDD_NET=" in t
    assert "analyze_power_grid -net $_vddnet" in t
    # a single unambiguous power net is accepted even if it matches no candidate
    assert "llength $found] == 1" in t
    # and an unresolvable one REFUSES rather than analysing a guessed name
    assert "IR_DROP_NO_POWER_NET" in t
    assert "noPowerNet" in t
    assert "success: (isComplete || isWarn) && !noPowerNet" in t
    # the refusal must say what the DEF actually contained
    assert "def_power_nets" in t and "def_ground_nets" in t
    assert "NOT_MEASURED" in t


def test_the_candidate_list_is_ordered_most_specific_first():
    t = _tool("eda_ir_drop")
    m = re.search(r"const vddCandidates = \[\.\.\.new Set\(\[([^\]]*)\]", t)
    assert m, "vddCandidates not found"
    order = [x.strip() for x in m.group(1).split(",")]
    assert order[0] == "custom_vdd", "an explicit caller override must win"
    assert order.index("cfg.vdd_net") < order.index("cfg.vdd_pin"), (
        "the NET name must be preferred over the PIN name"
    )
