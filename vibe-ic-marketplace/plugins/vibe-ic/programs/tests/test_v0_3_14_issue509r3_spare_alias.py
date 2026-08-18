"""v0.3.14 — #509 round-3: automate the last two design-specific residuals
the field handled surgically so the runner reaches netgen "Circuits match
uniquely" by itself — both SAFELY GENERALISED (derived per-design, never
hardcoded):

(a) ECO spare-ONLY class ignore — a std-cell class whose EVERY instance is
    a spare (instance name contains 'spare') carries no functional
    connectivity (schematic declares spares floating `()`; layout extract
    wires their power pins to a neighbour pseudo-net → can't pin-match).
    Ignoring a spare-ONLY class cannot hide a real defect; a class used by
    even one functional instance is NOT ignored.

(b) buffer-merged same-net top-port aliasing — `assign o_a = o_b`
    (buffer-less) makes two top pins ONE physical net; ext2spice drops the
    alias port → netgen 'failed pin matching'. Re-add the dropped alias to
    the .subckt port list + a 0-ohm resistor join (netgen auto-removes →
    0 added devices), faithful to the schematic node-merge.

Validated in the vibeic-eda container (real subservient): the runner-
generated extract + these two patches reach
`Final result: Circuits match uniquely.` (the benign symmetric
disconnected notes — e.g. i_gpio[0] optional-unused — do not block).

chip-AGNOSTIC: spare classes from the netlist, aliases from the DEF, no
chip/vendor literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ── (a) spare-only class detection ───────────────────────────────────

_NETLIST = (
    "module chip_top();\n"
    "sky130_fd_sc_hd__dfrtp_1 spare_dff_0 (.CLK(n1));\n"
    "sky130_fd_sc_hd__dfrtp_1 spare_dff_1 (.CLK(n2));\n"
    "sky130_fd_sc_hd__inv_1 spare_inverter_0 (.A(n3));\n"
    "sky130_fd_sc_hd__nand2_1 spare_nand_0 (.A(n4));\n"   # spare instance
    "sky130_fd_sc_hd__nand2_1 _0123_ (.A(n5));\n"          # FUNCTIONAL
    "sky130_fd_sc_hd__dfxtp_1 _0456_ (.CLK(clk));\n"       # functional FF
    "endmodule\n"
)


def test_spare_only_classes_are_detected():
    cls = R._v0_3_14_detect_spare_only_classes(_NETLIST)
    assert "sky130_fd_sc_hd__dfrtp_1" in cls   # 2/2 spare
    assert "sky130_fd_sc_hd__inv_1" in cls     # 1/1 spare


def test_mixed_class_not_ignored():
    # nand2_1 has a functional instance → must NOT be ignored (could hide
    # a real mismatch in this or another design).
    cls = R._v0_3_14_detect_spare_only_classes(_NETLIST)
    assert "sky130_fd_sc_hd__nand2_1" not in cls
    assert "sky130_fd_sc_hd__dfxtp_1" not in cls


def test_no_spares_returns_empty():
    nl = ("module m();\nsky130_fd_sc_hd__inv_1 _00_ (.A(a));\n"
          "sky130_fd_sc_hd__nand2_1 _01_ (.A(b));\nendmodule\n")
    assert R._v0_3_14_detect_spare_only_classes(nl) == []


def test_local_setup_emits_spare_ignores(tmp_path):
    pdk = R._detect_pdk(Path("/nonexistent"), override="sky130A")
    host, _ = R._emit_local_netgen_setup(
        tmp_path, pdk, "vibeic-eda",
        spare_only_classes=["sky130_fd_sc_hd__dfrtp_1"])
    body = host.read_text()
    assert 'ignore class "-circuit1 sky130_fd_sc_hd__dfrtp_1"' in body
    assert 'ignore class "-circuit2 sky130_fd_sc_hd__dfrtp_1"' in body


# ── (b) top-port aliasing ────────────────────────────────────────────

_DEF = (
    "PINS 4 ;\n"
    "    - o_sram_data[0] + NET o_sram_data[0] + DIRECTION OUTPUT ;\n"
    "    - o_sram_data[1] + NET o_sram_data[1] + DIRECTION OUTPUT ;\n"
    "    - o_sram_wdata[0] + NET o_sram_data[0] + DIRECTION OUTPUT ;\n"
    "    - o_gpio[0] + NET u_dut.gpio_r[0] + DIRECTION OUTPUT ;\n"
    "END PINS\n"
)


def test_top_port_alias_detection_filters_internal_nets():
    al = R._v0_3_14_detect_top_port_aliases(_DEF)
    # o_sram_wdata[0]→o_sram_data[0] (net is a top pin) kept;
    # o_gpio[0]→internal hierarchical net NOT kept.
    assert ("o_sram_wdata[0]", "o_sram_data[0]") in al
    assert all(p != "o_gpio[0]" for p, _ in al)
    assert len(al) == 1


def test_apply_aliases_adds_ports_and_zero_ohm_joins():
    sp = (".subckt sky130_fd_sc_hd__fill_1 a b\n.ends\n"
          ".subckt chip_top o_sram_data[0] o_sram_data[1] i_clk\n"
          "X1 a b sky130_fd_sc_hd__fill_1\n.ends\n")
    out = R._v0_3_14_apply_top_port_aliases(
        sp, [("o_sram_wdata[0]", "o_sram_data[0]")], top="chip_top")
    # the alias must land on the chip_top header (NOT the leaf fill subckt).
    top_hdr = [l for l in out.splitlines()
               if l.startswith(".subckt chip_top")][0]
    assert "o_sram_wdata[0]" in top_hdr
    assert "RWALIAS0 o_sram_data[0] o_sram_wdata[0] 0" in out
    # the leaf subckt header is untouched.
    leaf = [l for l in out.splitlines()
            if l.startswith(".subckt sky130_fd_sc_hd__fill_1")][0]
    assert "o_sram_wdata" not in leaf


def test_apply_aliases_multiline_header():
    # ext2spice wraps long port lists with LEADING '+' continuations.
    sp = (".subckt chip_top a0 a1 a2 a3\n"
          "+ o_sram_data[0] o_sram_data[1]\n"
          "X1 n n cell\n.ends\n")
    out = R._v0_3_14_apply_top_port_aliases(
        sp, [("o_sram_wdata[0]", "o_sram_data[0]"),
             ("o_sram_wdata[1]", "o_sram_data[1]")], top="chip_top")
    assert out.count("RWALIAS") == 2
    assert "o_sram_wdata[0]" in out and "o_sram_wdata[1]" in out


def test_apply_aliases_noop_when_canonical_absent():
    # if the canonical net isn't a port, skip (nothing to short against).
    sp = ".subckt chip_top i_clk i_rst\nX1 a b cell\n.ends\n"
    out = R._v0_3_14_apply_top_port_aliases(
        sp, [("o_sram_wdata[0]", "o_sram_data[0]")], top="chip_top")
    assert "RWALIAS" not in out and out == sp
