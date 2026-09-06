"""The auto-SDC's DRV block emitted object types OpenSTA rejects — and the
first rejection HID the second, so fixing either one alone only relocated the
failure.

MEASURED against the pinned OpenSTA (2.7.0) — the three DRV commands do NOT
accept the same objects, and the generator treated them as if they did:

    command               [get_pins -hierarchical *]   output port   input port
    set_max_capacitance   OK                           OK            OK
    set_max_transition    Error 100 (Pin)              OK            OK
    set_max_fanout        Error 100 (Pin)              Error 467     OK

The generator used ONE `scope` variable for all three (the hierarchical-pin
scope, whenever the design has supply ports to exclude) and ONE port list built
from `get_ports *` (which contains outputs). That produced:

  D1  `set_max_fanout <n> [get_pins -hierarchical *]`
          Error 100: unsupported object type Pin.
  D2  `set_max_fanout <n> $_vibeic_drv_signal_ports`   (list holds outputs)
          Error 467: port '<out>' is not an input.
  D3  `set_max_transition <n> [get_pins -hierarchical *]`
          Error 100: unsupported object type Pin.

D1 IS EMITTED BEFORE D2, so the SDC aborted on D1 and D2 was never reached.
Deleting D1 alone moves the failure to D2; both must be correct at once. D3 is
a separate line that only appears when a liberty slew limit was resolved, which
is why a run without one saw D1/D2 and a run with one saw D3 first.

Nothing caught any of this because no test ever fed the emitted block to an
actual timer -- the SDC was only ever compared to expected TEXT.

chip-AGNOSTIC: sky130A is an OPEN PDK; the cells, widths and limits here carry
no vendor, SKU or node literal.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P3  # noqa: E402

_STA = shutil.which("sta")
_LIB_GLOB = "sky130_fd_sc_hd__tt_025C_1v80.lib"


def _liberty() -> Path | None:
    for root in (Path("/foss/pdks"), Path("/usr/share/pdk"), Path("/pdk")):
        if not root.is_dir():
            continue
        for hit in root.rglob(_LIB_GLOB):
            return hit
    return None


_LIB = _liberty()
_CAN_RUN_STA = bool(_STA) and _LIB is not None

_NETLIST = """module top (input a, input b, input clk, output y,
                        inout vccd1, inout vssd1);
  wire n1;
  sky130_fd_sc_hd__and2_1 u1 (.A(a), .B(b), .X(n1));
  sky130_fd_sc_hd__buf_1  u2 (.A(n1), .X(y));
endmodule
"""

_SUPPLIES = ("vccd1", "vssd1")


def _sta_load(tmp_path: Path, sdc_text: str):
    """`(rc, output)` from actually loading `sdc_text` into OpenSTA."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "d.v").write_text(_NETLIST)
    (tmp_path / "blk.sdc").write_text(sdc_text)
    (tmp_path / "t.tcl").write_text(
        f"read_liberty {_LIB}\n"
        "read_verilog d.v\n"
        "link_design top\n"
        "create_clock -name clk -period 10 [get_ports clk]\n"
        "if {[catch {source blk.sdc} e]} { puts \"BLOCK_ERR: $e\" ; exit 1 }\n"
        "puts BLOCK_OK\nexit 0\n")
    r = subprocess.run([_STA, "-no_init", "-exit", "t.tcl"],
                       cwd=tmp_path, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _block(**kw) -> str:
    base = dict(slew_ns=0.75, cap_pf=0.12, note="n", max_fanout=16,
                fanout_note="fn", supply_ports=_SUPPLIES)
    base.update(kw)
    return P3._drv_constraints_sdc_block(**base)


# ── the object types, asserted on the emitted TEXT (no timer needed) ─────────

def test_set_max_fanout_never_takes_a_pin_scope():
    """D1. `set_max_fanout` over pins is Error 100 — it must take the design."""
    for kw in ({}, {"slew_ns": None}, {"cap_pf": None},
               {"supply_ports": ()}):
        text = _block(**kw)
        for line in text.splitlines():
            if line.startswith("set_max_fanout"):
                assert "get_pins" not in line, line


def test_set_max_fanout_per_port_line_takes_input_ports_only():
    """D2. The all-ports list contains outputs — Error 467. Use the IN subset."""
    text = _block()
    per_port = [l for l in text.splitlines()
                if l.startswith("set_max_fanout")
                and "$_vibeic_drv_signal" in l]
    assert per_port, text
    for line in per_port:
        assert "$_vibeic_drv_signal_in_ports" in line, line
        # the pre-fix list, which held output ports:
        assert "$_vibeic_drv_signal_ports" not in line, line
    # and the input-only list must actually be BUILT, or the line is empty and
    # the constraint silently applies to nothing.
    assert "set _vibeic_drv_signal_in_ports {}" in text
    assert "lappend _vibeic_drv_signal_in_ports" in text


def test_set_max_transition_never_takes_a_pin_scope():
    """D3. `set_max_transition` over pins is Error 100 as well."""
    for line in _block().splitlines():
        if line.startswith("set_max_transition"):
            assert "get_pins" not in line, line


def test_set_max_capacitance_keeps_the_pin_scope():
    """NO-LEAK. Capacitance is the one command that DOES accept pins; the fix
    must not narrow a constraint that was correct."""
    text = _block()
    assert "set_max_capacitance 0.12 [get_pins -hierarchical *]" in text, text


# ── the control: a design that declares no fanout cap ────────────────────────

def test_no_fanout_cap_emits_no_fanout_constraint():
    """A design whose L9 declares no cap must get NO `set_max_fanout` at all —
    the fix must not invent one."""
    for sup in ((), _SUPPLIES):
        text = _block(max_fanout=None, supply_ports=sup)
        # COMMAND lines only — the explanatory comments in this block name the
        # command, and matching those would make the assertion about prose.
        cmds = [l for l in text.splitlines() if l.startswith("set_max_fanout")]
        assert not cmds, cmds


def test_no_supply_ports_keeps_the_design_wide_shape():
    """A design with no supply ports to exclude never took the pin scope, so
    its DRV block is unchanged apart from the fanout object."""
    text = _block(supply_ports=())
    assert "_vibeic_drv_signal_ports" not in text
    assert "set_max_fanout 16 [current_design]" in text


# ── the decisive one: hand it to an actual timer, both directions ────────────

@pytest.mark.skipif(not _CAN_RUN_STA,
                    reason="OpenSTA or the open sky130A liberty is not on this host")
def test_emitted_drv_block_loads_in_opensta(tmp_path):
    """The check that did not exist. Every earlier test compared the SDC to
    expected TEXT, so three commands that no timer accepts read as green."""
    rc, out = _sta_load(tmp_path, _block())
    assert rc == 0 and "BLOCK_OK" in out, out


@pytest.mark.skipif(not _CAN_RUN_STA,
                    reason="OpenSTA or the open sky130A liberty is not on this host")
def test_the_rejected_forms_really_are_rejected(tmp_path):
    """THE OTHER DIRECTION. Re-break the emitted block one line at a time and
    confirm the timer rejects each form — otherwise the assertions above are
    pinning a shape nobody needs.

    This is also the D1-HIDES-D2 proof: with the pin-scope line restored the
    timer stops at Error 100 and never reaches the output-port line, which is
    exactly why fixing one alone relocated the failure instead of removing it.
    """
    good = _block()

    # D1 restored (pin scope on set_max_fanout) -> Error 100.
    d1 = good.replace("set_max_fanout 16 [current_design]",
                      "set_max_fanout 16 [get_pins -hierarchical *]")
    assert d1 != good
    rc, out = _sta_load(tmp_path / "d1", d1)
    assert rc != 0 and "Error 100" in out, out

    # D2 restored (all-ports list on set_max_fanout) -> Error 467.
    d2 = good.replace("set_max_fanout 16 $_vibeic_drv_signal_in_ports",
                      "set_max_fanout 16 $_vibeic_drv_signal_ports")
    assert d2 != good
    rc, out = _sta_load(tmp_path / "d2", d2)
    assert rc != 0 and "Error 467" in out, out

    # BOTH restored -> the timer reports only D1: it never reaches D2.
    both = d1.replace("set_max_fanout 16 $_vibeic_drv_signal_in_ports",
                      "set_max_fanout 16 $_vibeic_drv_signal_ports")
    rc, out = _sta_load(tmp_path / "both", both)
    assert rc != 0 and "Error 100" in out and "Error 467" not in out, out

    # D3 restored (pin scope on set_max_transition) -> Error 100.
    d3 = good.replace("set_max_transition 0.75 [current_design]",
                      "set_max_transition 0.75 [get_pins -hierarchical *]")
    assert d3 != good
    rc, out = _sta_load(tmp_path / "d3", d3)
    assert rc != 0 and "Error 100" in out, out


@pytest.mark.skipif(not _CAN_RUN_STA,
                    reason="OpenSTA or the open sky130A liberty is not on this host")
def test_the_input_only_list_is_not_empty(tmp_path):
    """NON-VACUITY. An empty `$_vibeic_drv_signal_in_ports` would ALSO load
    without error while constraining nothing, which is the same false green in
    a different costume. Assert the timer sees a non-empty list."""
    text = _block() + (
        '\nif {[llength $_vibeic_drv_signal_in_ports] == 0} '
        '{ puts "EMPTY_LIST" ; exit 1 }\n'
        'puts "IN_PORTS=[llength $_vibeic_drv_signal_in_ports]"\n')
    rc, out = _sta_load(tmp_path, text)
    assert rc == 0, out
    assert "EMPTY_LIST" not in out, out
    # top has a,b,clk as inputs and y as an output; vccd1/vssd1 are excluded.
    assert "IN_PORTS=3" in out, out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
