"""ORGANIC #711 round-2 — AUTO-DERIVE the renamed-interface pairing (field-agent
reopen of the v1.0.74 round-1 fix).

Round-1 added a `renamed_interfaces` reconcile path to l9_rtl_pin_consistency_check
but NOTHING populated it, so on the real catalog-glue subservient artifact the
gate STILL FAILed (or needed a per-run hand-authored manifest block — equivalent
to the per-run waiver it was meant to remove). The reopen repro: the SOURCE_MANIFEST
the program REALLY emits carries `{reused_ip, ip_list}` only, and the gate FAILs
exit=1 with the o_sram split (`o_sram_waddr/raddr/wdata/wen/ren` + `i_sram_rdata`
vs L9 typical `o_sram_addr/data/we` + `i_sram_data`).

Round-2 AUTO-DERIVES the pairing in the gate from the design's OWN signals:
`declaration.json.<iface>_interface_protocol` + the L3 input doc's illustrative
tag (`<name>` (or `<alt>`) / "(typical)"). No hand-authored manifest block.

§4.05 NEGATIVE no-leak: the auto-reconcile fires ONLY for an interface that is
BOTH protocol-declared AND L3-illustrative; without a protocol, without the
illustrative tag, or for a residual port OUTSIDE such an interface, the gate
STILL FAILs.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as G  # noqa: E402

_GATE = _PROGRAMS / "l9_rtl_pin_consistency_check.py"

_CHIP_TOP = """\
module chip_top(
  input  i_clk, input i_rst,
  output o_sram_waddr, output o_sram_raddr,
  output o_sram_wdata, output o_sram_wen, output o_sram_ren,
  input  i_sram_rdata
);
endmodule
"""
_L9 = {
    "top_module": "chip_top",
    "top_ports": [
        {"name": "i_clk", "direction": "input"},
        {"name": "i_rst", "direction": "input"},
        {"name": "o_sram_addr", "direction": "output"},
        {"name": "o_sram_data", "direction": "output"},
        {"name": "o_sram_we", "direction": "output"},
        {"name": "i_sram_data", "direction": "input"},
    ],
}
_L3_ILLUSTRATIVE = (
    "| `o_sram_addr` (or `o_sram_waddr`/`o_sram_raddr`) | 8 | output | 位址(typical) |\n"
    "| `o_sram_data` (or `o_sram_wdata`) | 8 | output | 寫入資料(typical) |\n"
    "| `o_sram_we` (or `o_sram_wen`/`o_sram_ren`) | 1 | output | 寫致能(typical) |\n"
    "| `i_sram_data` (or `i_sram_rdata`) | 8 | input | 讀取資料(typical) |\n")


def _build(tmp: Path, *, protocol=True, illustrative=True, extra_l9_port=None):
    """Faithful round-10 subservient shape; the manifest carries ONLY what the
    program really emits (reused_ip + ip_list), never a hand-authored rename."""
    (tmp / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (tmp / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
    (tmp / "plugin_output").mkdir(parents=True, exist_ok=True)
    (tmp / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (tmp / "phase2/stage1/rtl/chip_top.sv").write_text(_CHIP_TOP)
    l9 = json.loads(json.dumps(_L9))
    if extra_l9_port:
        l9["top_ports"].append(extra_l9_port)
    (tmp / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(l9))
    decl = {"rtl_strategy": "catalog_lookup_plus_ai_glue"}
    if protocol:
        decl["sram_interface_protocol"] = "generic_8bit_addr_data_we"
    (tmp / "plugin_output/declaration.json").write_text(json.dumps(decl))
    (tmp / "input/docs/L3_external_interface.md").write_text(
        _L3_ILLUSTRATIVE if illustrative
        else "| o_sram_addr | 8 | output | addr |\n")
    (tmp / "phase2/stage1/rtl/SOURCE_MANIFEST.json").write_text(json.dumps(
        {"reused_ip": True, "ip_list": ["subservient"],
         "generated_by": "ip_catalog_pull"}))
    return tmp


def _gate_rc(project: Path) -> int:
    return subprocess.run(
        [sys.executable, str(_GATE), str(project)],
        capture_output=True, text=True).returncode


def test_end_state_auto_derive_passes_without_hand_edit(tmp_path):
    """END-STATE (the reopen repro): the gate PASSes on the faithful artifact
    with the program-emitted manifest (reused_ip+ip_list ONLY) — the rename is
    auto-derived, no hand-authored `renamed_interfaces` block."""
    proj = _build(tmp_path)
    mf = json.loads(
        (proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json").read_text())
    assert "renamed_interfaces" not in mf  # NOT hand-authored
    assert _gate_rc(proj) == 0


def test_unit_auto_derive_pairs_sram_split(tmp_path):
    proj = _build(tmp_path)
    assert G._declared_interface_protocols(proj) == {"sram"}
    assert G._l3_iface_illustrative(proj, "sram") is True
    groups = G._auto_derive_renamed_interfaces(
        proj,
        ["o_sram_addr", "o_sram_data", "o_sram_we", "i_sram_data"],
        ["o_sram_waddr", "o_sram_raddr", "o_sram_wdata", "o_sram_wen",
         "o_sram_ren", "i_sram_rdata"])
    assert len(groups) == 1
    assert set(groups[0]["l9"]) == {"o_sram_addr", "o_sram_data", "o_sram_we",
                                    "i_sram_data"}
    assert "o_sram_waddr" in groups[0]["rtl"]


def test_noleak_no_protocol_declared_still_fails(tmp_path):
    """§4.05: without a `<iface>_interface_protocol` declaration, NO auto-derive
    → the gate STILL FAILs the rename."""
    proj = _build(tmp_path, protocol=False)
    assert G._auto_derive_renamed_interfaces(
        proj, ["o_sram_addr"], ["o_sram_waddr"]) == []
    assert _gate_rc(proj) == 1


def test_noleak_no_illustrative_tag_still_fails(tmp_path):
    """§4.05: protocol declared but the L3 doc does NOT mark the interface
    illustrative → NO auto-derive → the gate STILL FAILs."""
    proj = _build(tmp_path, illustrative=False)
    assert G._l3_iface_illustrative(proj, "sram") is False
    assert _gate_rc(proj) == 1


def test_noleak_extra_functional_port_outside_iface_still_fails(tmp_path):
    """§4.05: a genuinely-missing NON-interface functional port is NOT
    reconciled by the sram auto-derive — the gate STILL FAILs on it."""
    proj = _build(tmp_path, extra_l9_port={"name": "o_irq",
                                           "direction": "output"})
    rc = subprocess.run([sys.executable, str(_GATE), str(proj)],
                        capture_output=True, text=True)
    assert rc.returncode == 1
    assert "o_irq" in rc.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
