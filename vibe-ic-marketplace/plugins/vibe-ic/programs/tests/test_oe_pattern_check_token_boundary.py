"""`oe_pattern_check` matched the OE infixes as BARE SUBSTRINGS.

    is_oe_name("dbus_en") -> True        # 'bus_en' is a substring of 'dbus_en'

`dbus_en` is a RISC-V core's DATA-BUS REQUEST enable — an ordinary synchronous
control signal decoded from the opcode. The gate read it as an output-enable
driving a tristate bus and reported:

    !!! serv_state.v:43: i_dbus_en -> COMBINATIONAL (HIGH)
        No registered or continuous assignment found
        ... If it controls a tristate buffer, it must be registered ...

on a design containing ZERO tristate drivers — no `inout` port and no high-Z
literal in any of its 25 files — and exited 1. One of the four flagged signals
is an INPUT PORT, which by construction is driven from outside the module and
can have no assignment inside it.

THE SHAPE: the gate asks "does this identifier contain the substring 'bus_en'?"
and reports the answer as "this is an output-enable on a tristate bus driver".
That is a question ADJACENT to the one the gate exists to answer.

WHAT THE FIX MUST NOT DO. The obvious repair — "require the design to contain a
tristate driver" — was measured first and is WRONG. The two other corpus designs
this gate reddens (`ahb_apb`, `mdio`) also contain no `inout` and no high-Z: they
export the standard 3-wire pad interface (`mdio_o` / `mdio_oe` / `mdio_i`) and
the tristate lives in the pad ring, outside the RTL. `gpio_oe` and `mdio_oe` are
GENUINE output-enables. A tristate-evidence filter would have zeroed the gate's
findings by swallowing the two real ones along with the false ones.

So the fix anchors the unanchored infixes at an underscore-delimited token
boundary, and nothing else. `bus_en`, `io_bus_en`, `wb_bus_en` still match;
`dbus_en`/`ibus_en`/`sbus_en`/`abus_en` no longer do; the `_oe` suffix rule that
catches `gpio_oe` and `mdio_oe` is untouched.

CONTROLS BELOW ARE BIDIRECTIONAL:
  * `test_bus_request_enable_is_not_an_output_enable` FAILS against the
    byte-identical pre-fix file (it asserts False where the old code returns
    True), and passes after.
  * `test_genuine_oe_names_still_match` and
    `test_real_tristate_design_is_still_flagged` must pass on BOTH sides —
    they are what catches a fix that tightened the filter until the count hit
    zero.
  * `test_declined_name_still_caught_when_it_really_drives_a_tristate` pins the
    load-bearing safety argument: the name rule is not the only discovery path.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "oe_pattern_check.py"

sys.path.insert(0, str(_PROGRAMS))
import oe_pattern_check as oe  # noqa: E402

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── the false positives this fix removes ────────────────────────────────────
# Every one is <bus-name> + '_en', where the bus name merely ENDS in the
# letters "bus". Taken from the RISC-V core the defect was measured on.
BUS_REQUEST_ENABLES = [
    "dbus_en", "o_dbus_en", "co_dbus_en", "i_dbus_en",
    "ibus_en", "sbus_en", "abus_en",
]

# ── the true positives that must survive ────────────────────────────────────
GENUINE_OE_NAMES = [
    # suffix / exact rules — the real-world 3-wire pad convention
    "gpio_oe", "mdio_oe", "pad_oe", "spi_oen", "oe", "oen", "oeb",
    # self-anchored infixes
    "pad_oe_n", "bus_oe_ctrl",
    # token-boundary infixes: the boundary is present, so these still match
    "bus_en", "io_bus_en", "wb_bus_en", "tri_en", "spi_tri_en",
    "tristate_en", "drv_en", "pad_drv_en",
]


@pytest.mark.parametrize("name", BUS_REQUEST_ENABLES)
def test_bus_request_enable_is_not_an_output_enable(name):
    """FORWARD CONTROL — fails against the byte-identical pre-fix file."""
    assert oe.is_oe_name(name) is False, (
        f"{name!r} was classified as an output-enable. It is a bus REQUEST "
        f"enable: the infix 'bus_en' was matched as a bare substring inside "
        f"a token that merely ends in 'bus'.")


@pytest.mark.parametrize("name", GENUINE_OE_NAMES)
def test_genuine_oe_names_still_match(name):
    """REVERSE CONTROL — passes on BOTH sides of the fix.

    This is the one that catches a fix that tightened until the count hit zero.
    """
    assert oe.is_oe_name(name) is True, (
        f"{name!r} is a genuine output-enable and the fix stopped matching it")


def _run(files, out_dir):
    return _pr.run(
        [sys.executable, str(PROG), "--rtl-files", *[str(f) for f in files],
         "--out-dir", str(out_dir)],
        capture_output=True, text=True)


# A design shaped like the one the defect was measured on: a bus-request enable
# decoded from an opcode, an input port of the same name, and NO tristate.
BUS_REQUEST_RTL = """\
module decode(input wire clk, input wire [6:0] opcode, output reg o_dbus_en);
  wire co_dbus_en = ~opcode[2] & ~opcode[4];
  always @(posedge clk) o_dbus_en <= co_dbus_en;
endmodule

module state(input wire clk, input wire i_dbus_en, output reg busy);
  always @(posedge clk) busy <= i_dbus_en;
endmodule
"""

# A genuine tristate driver with a combinational enable.
TRISTATE_RTL = """\
module pad(inout wire io, input wire pad_oe, input wire d);
  assign io = pad_oe ? d : 1'bz;
endmodule
"""

# The safety argument, made executable: an identifier the NAME rule now
# declines, which really does drive a tristate. Structural discovery must
# still find it.
DECLINED_NAME_BUT_REAL_TRISTATE_RTL = """\
module pad(inout wire io, input wire dbus_en, input wire d);
  assign io = dbus_en ? d : 1'bz;
endmodule
"""


def test_bus_request_design_is_not_flagged(tmp_path):
    """FORWARD CONTROL, end to end — pre-fix this exits 1 with HIGH findings."""
    f = tmp_path / "bus_request.v"
    f.write_text(BUS_REQUEST_RTL)
    proc = _run([f], tmp_path)
    assert proc.returncode == 0, (
        f"a design with no tristate driver at all exited {proc.returncode} on "
        f"bus-REQUEST enables:\n{proc.stdout}")


def test_real_tristate_design_is_still_flagged(tmp_path):
    """REVERSE CONTROL — must pass on BOTH sides of the fix."""
    f = tmp_path / "pad.v"
    f.write_text(TRISTATE_RTL)
    proc = _run([f], tmp_path)
    assert proc.returncode == 1, (
        f"a combinational OE on a real tristate driver exited "
        f"{proc.returncode}; the gate stopped doing its job:\n{proc.stdout}")
    assert "pad_oe" in proc.stdout


def test_declined_name_still_caught_when_it_really_drives_a_tristate(tmp_path):
    """REVERSE CONTROL — the name rule is not the only discovery path.

    `dbus_en` is a name `is_oe_name` now declines. When it actually drives a
    tristate, `find_oe_declarations`'s structural `oe ? data : 'bz` pass must
    still surface it, or the fix would have traded a false positive for a
    false negative.
    """
    f = tmp_path / "pad.v"
    f.write_text(DECLINED_NAME_BUT_REAL_TRISTATE_RTL)
    assert oe.is_oe_name("dbus_en") is False, "precondition: name is declined"
    proc = _run([f], tmp_path)
    assert proc.returncode == 1, (
        f"a declined NAME that really drives a tristate exited "
        f"{proc.returncode}; the fix swallowed a real defect:\n{proc.stdout}")
    assert "dbus_en" in proc.stdout
