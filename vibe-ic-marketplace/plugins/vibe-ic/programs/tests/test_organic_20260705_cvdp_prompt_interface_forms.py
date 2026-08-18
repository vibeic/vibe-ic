#!/usr/bin/env python3
r"""test_organic_20260705_cvdp_prompt_interface_forms.py

ORGANIC-20260705 — the v1.2.96 harness-read removal restored §4.05 compliance but
also dropped two common PROMPT interface forms from cvdp_complete_extract's
input-only recovery: the markdown Signal/Direction/Width table and the
`- `name` (input, N bits):` prose-bullet port list. Records whose interface was
stated in those forms regressed to INCOMPLETE_SPEC_ABSENT.

These tests pin the RESTORED input-only parsers (`_prose_bullet_ports`, and the
wiring of `_signal_direction_table` into `_recover_cvdp_interface`) — PASS cases +
the strict no-false-port gating. Reads ONLY prompt text (no harness/oracle).

Run: python3 -m pytest programs/tests/test_organic_20260705_cvdp_prompt_interface_forms.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import cvdp_atomic_bridge as B  # noqa: E402


def test_prose_bullet_ports_annotated_and_clock_reset():
    prompt = (
        "### Signals\n"
        "- `pclk`: APB clock input for synchronous operations.\n"
        "- `presetn`: Active-low asynchronous reset signal.\n"
        "- `paddr` (input, 10 bits): Address bus.\n"
        "- `pwrite` (input): Write-enable signal.\n"
        "- `prdata` (output, reg, 8 bits): Read data bus.\n"
        "- `pslverr` (output, reg): Error signal.\n"
    )
    ins, outs, widths = B._prose_bullet_ports(prompt)
    assert set(ins) == {"pclk", "presetn", "paddr", "pwrite"}
    assert set(outs) == {"prdata", "pslverr"}
    assert widths["paddr"] == 10 and widths["prdata"] == 8
    assert widths["pclk"] == 1 and widths["presetn"] == 1  # 1-bit clock/reset


def test_prose_bullet_drops_enum_value_bullets():
    # a mode-enum list (`- `0`: disabled`) must NOT become ports, and with < 2
    # annotated bullets the parser stays silent entirely.
    prompt = (
        "Operation modes:\n"
        "- `0`: DSP disabled\n"
        "- `1`: Addition mode\n"
        "- `2`: Multiplication mode\n"
    )
    ins, outs, widths = B._prose_bullet_ports(prompt)
    assert ins == [] and outs == [] and widths == {}


def test_prose_bullet_requires_two_annotations_to_activate():
    # a single annotated bullet is not a port-list section → silent (no phantom).
    prompt = "- `foo` (input): a thing.\n- `bar`: unrelated prose bullet.\n"
    ins, outs, _ = B._prose_bullet_ports(prompt)
    assert ins == [] and outs == []


def test_signal_direction_table_binds_comparator_shape():
    prompt = (
        "| Signal | Direction | Bit Width | Description |\n"
        "|--------|-----------|-----------|-------------|\n"
        "| `i_A` | Input | `WIDTH` | operand |\n"
        "| `i_B` | Input | `WIDTH` | operand |\n"
        "| `i_enable` | Input | 1 | enable |\n"
        "| `o_equal` | Output | 1 | result |\n"
    )
    ins, outs, widths, _sym = B._signal_direction_table(prompt, {"WIDTH": 5})
    assert set(ins) == {"i_A", "i_B", "i_enable"}
    assert outs == ["o_equal"]
    assert widths["i_A"] == 5 and widths["o_equal"] == 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
