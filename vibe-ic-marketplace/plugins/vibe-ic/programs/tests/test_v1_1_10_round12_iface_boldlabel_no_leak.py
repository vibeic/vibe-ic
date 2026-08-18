"""Step-2.7 §4.05 guard for the R12C3 iface bold-label FORM-B relaxation (PR #3).

`bold_label_ports` FORM-B harvests a bare-name bold bullet (`- **name:** <spec>`)
under a port-section heading as an interface port. The original form over-fired
(both reproduced by Step-2.7, fabricating phantom ports that FALSE-BLOCK correct
RTL):
  * an FSM/state register described in a bullet under `## Outputs`
    (`- **state:** 2-bit FSM register holding the current phase.`) was fabricated
    as an output port;
  * CSR bit-fields listed as bold bullets AFTER a prose sentence under
    `## Inputs` (`The control register CTRL exposes ...` then `- **mode:** ...`)
    were fabricated as input ports.

FIX: FORM-B fires ONLY for the IMMEDIATE contiguous bullet list under the heading
(intervening prose/table ends the list) AND when the body does NOT describe an
internal storage element (FSM/state register, counter, flip-flop, internal
signal). FORM-A (inline direction) and a genuine bare-name port bullet
(`- **enable:** 1-bit`) are unaffected. This file PINS both halves.

chip-AGNOSTIC: pure markdown bullet/heading grammar + English storage vocabulary.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as I  # noqa: E402


def test_fsm_state_register_under_outputs_not_fabricated_as_port():
    spec = ("## Outputs\n"
            "- **lights (output, wire[2:0])**: traffic light bus\n"
            "- **state:** 2-bit FSM register holding the current phase.\n")
    ports = I.bold_label_ports(spec)
    assert "state" not in ports            # internal FSM register, not a port
    assert ports.get("lights") == "output"  # FORM-A inline direction still works


@pytest.mark.parametrize("body", [
    "2-bit FSM register holding the current phase.",
    "3-bit internal counter for the divider",
    "1-bit internal signal",
    "4-bit shift register stage",
    "2-bit flip-flop state",
])
def test_internal_storage_bodies_are_never_ports(body):
    spec = f"## Outputs\n- **sig:** {body}\n"
    assert "sig" not in I.bold_label_ports(spec)


def test_csr_bitfields_after_prose_not_fabricated_as_ports():
    spec = ("## Inputs\n"
            "- **pclk:** 1-bit APB clock\n"
            "- **paddr:** 8-bit register address\n"
            "\n"
            "The control register CTRL exposes the following bit fields:\n"
            "- **mode:** 2-bit operating mode field\n"
            "- **gain:** 4-bit gain setting\n")
    ports = I.bold_label_ports(spec)
    # the two real ports BEFORE the prose are kept...
    assert ports.get("pclk") == "input"
    assert ports.get("paddr") == "input"
    # ...but the CSR bit-fields AFTER the prose sentence are NOT ports.
    assert "mode" not in ports
    assert "gain" not in ports


def test_real_port_with_register_address_body_is_kept():
    # §4.05 no OVER-correction: "register address" is a real port body — bare
    # "register" must NOT be denied (only storage-element phrasings are).
    spec = "## Inputs\n- **paddr:** 8-bit register address\n"
    assert I.bold_label_ports(spec).get("paddr") == "input"


def test_motivating_bare_name_port_still_detected():
    # the FP-fix the relaxation exists for (cvdp_copilot_moving_average_0005).
    spec = "## New Input\n- **enable:** 1-bit\n"
    assert I.bold_label_ports(spec).get("enable") == "input"


def test_form_a_inline_direction_unaffected():
    spec = ("- **data_out (output, wire[11:0])**: 12-bit result\n"
            "- **clk (input, wire)**: clock\n")
    ports = I.bold_label_ports(spec)
    assert ports.get("data_out") == "output"
    assert ports.get("clk") == "input"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
