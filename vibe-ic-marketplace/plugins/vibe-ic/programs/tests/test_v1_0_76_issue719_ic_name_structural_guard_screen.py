"""ORGANIC #719 — ic_name macro screen: replace the Caravel-family `MPRJ_`
LITERAL with a STRUCTURAL guard screen (chip-agnostic refinement).

The #646 fix baked a Caravel/eFabless design-family literal (`MPRJ_IO_PADS` in
the stoplist + `MPRJ` in the guard-macro regex) into PROGRAM LOGIC — a
design-family special-case, not a structural rule. #719 removes it: a token is
screened as a guard macro iff it is used as a `` `ifdef/`ifndef/`elsif/`define ``
guard in the design (any prefix), generalising to ANY SoC family while the
generic `USE_*` / HDL-tool stoplist is kept.

§4.05 NEGATIVE no-leak: real all-caps chip acronyms (AES / JTAG / SHA / UART)
must STILL be accepted as ic_name candidates; only a token actually used as a
conditional-compile guard is screened.
"""
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402


def test_no_mprj_family_literal_in_program_logic():
    """The Caravel-family `MPRJ` literal is gone from program LOGIC: not in the
    stoplist, and the guard-macro regex no longer matches an MPRJ prefix."""
    assert "MPRJ_IO_PADS" not in R._HDL_PDK_MACRO_STOPLIST
    assert not R._RE_HDL_GUARD_MACRO.match("MPRJ_IO_PADS")
    # the generic USE_* ifdef-guard convention is retained
    assert R._RE_HDL_GUARD_MACRO.match("USE_POWER_PINS")


@pytest.mark.parametrize("directive", ["ifdef", "ifndef", "elsif", "define"])
def test_harvest_guard_macros_grammar(directive):
    macros = R._harvest_guard_macros([f"`{directive} CFG_DEBUG_X\n"])
    assert "CFG_DEBUG_X" in macros


@pytest.mark.parametrize("tok", ["MPRJ_IO_PADS", "FOO_BAR_GUARD", "DBG_CFG"])
def test_structural_screen_any_prefix(tok):
    """A guard macro of ANY prefix is screened structurally."""
    guards = R._harvest_guard_macros([f"`ifdef {tok}\n inout p;\n`endif\n"])
    assert R._is_hdl_pdk_macro_token(tok, guards) is True


@pytest.mark.parametrize("acro", ["AES", "JTAG", "SHA", "UART", "MD5"])
def test_noleak_acronym_not_screened_even_with_guards(acro):
    """§4.05: a real acronym is NOT screened even when other guard macros are
    present in scope (it is not itself an `ifdef guard)."""
    guards = {"MPRJ_IO_PADS", "USE_POWER_PINS", "FOO_GUARD"}
    assert R._is_hdl_pdk_macro_token(acro, guards) is False
    assert R._is_strict_single_token_ic_name(acro, guards) is True


def test_end_to_end_structural_guard_not_picked_as_ic_name():
    """A doc whose RTL guards a family-named macro must not yield that macro as
    ic_name; the declared chip name wins."""
    doc = {
        "L1.md": "# Spec\n\n- **Chip name:** my_soc_top\n",
        "rtl.v": ("module my_soc_top(...);\n`ifdef MPRJ_IO_PADS\n"
                  "  inout [37:0] mprj_io;\n`endif\nendmodule\n"),
    }
    name = R._ic_name_from_docs_impl(doc)
    assert name == "my_soc_top"
    assert name != "MPRJ_IO_PADS"


def test_end_to_end_acronym_chip_still_picked():
    """§4.05 no-regression: a real acronym chip still resolves."""
    doc = {"README.md": "# AES\n\nRTL implementation of AES (FIPS-197).\n"}
    assert R._ic_name_from_docs_impl(doc) == "AES"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
