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
import cvdp_complete_extract as C  # noqa: E402
import prose_interface_table_read as T  # noqa: E402


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
    ins, outs, widths, _sym = T.read_signal_direction_table(prompt, {"WIDTH": 5})
    assert set(ins) == {"i_A", "i_B", "i_enable"}
    assert outs == ["o_equal"]
    assert widths["i_A"] == 5 and widths["o_equal"] == 1


def test_signal_direction_reader_unions_sectioned_interface_tables():
    """A single interface is often split into Global/Master/Slave tables.
    One-sided tables are valid fragments; none may disappear merely because it
    lacks both an input and an output in that individual section."""
    prompt = (
        "### Global\n"
        "| Signal Name | Width | Direction | Description |\n"
        "|-------------|-------|-----------|-------------|\n"
        "| clk         | 1 bit | input     | clock       |\n"
        "| rst_n       | 1 bit | input     | reset       |\n"
        "\n### Master 0\n"
        "| Signal Name | Width  | Direction | Description |\n"
        "|-------------|--------|-----------|-------------|\n"
        "| m0_ready    | 1 bit  | output    | ready       |\n"
        "| m0_valid    | 1 bit  | input     | valid       |\n"
        "| m0_data     | 32 bit | input     | data        |\n"
        "\n### Master 1\n"
        "| Signal Name | Width  | Direction | Description |\n"
        "|-------------|--------|-----------|-------------|\n"
        "| m1_ready    | 1 bit  | output    | ready       |\n"
        "| m1_valid    | 1 bit  | input     | valid       |\n"
        "| m1_data     | 32 bit | input     | data        |\n"
        "\n### Slave\n"
        "| Signal Name | Width  | Direction | Description |\n"
        "|-------------|--------|-----------|-------------|\n"
        "| s_ready     | 1 bit  | input     | ready       |\n"
        "| s_valid     | 1 bit  | output    | valid       |\n"
        "| s_data      | 32 bit | output    | data        |\n"
    )
    ins, outs, widths, _sym = T.read_signal_direction_table(prompt)
    assert ins == ["clk", "rst_n", "m0_valid", "m0_data", "m1_valid",
                   "m1_data", "s_ready"]
    assert outs == ["m0_ready", "m1_ready", "s_valid", "s_data"]
    assert widths == {
        "clk": 1, "rst_n": 1,
        "m0_ready": 1, "m0_valid": 1, "m0_data": 32,
        "m1_ready": 1, "m1_valid": 1, "m1_data": 32,
        "s_ready": 1, "s_valid": 1, "s_data": 32,
    }


def test_complete_extract_keeps_all_tables_beside_stale_skeleton_names():
    """The CVDP adapter must expose every prompt-table fact even when a stale
    fenced skeleton uses a different spelling. Resolution happens downstream;
    deleting the table spelling here made Program First unable to choose it."""
    prompt = (
        "Write module bus.\n"
        "### Global\n"
        "| Signal | Width | Direction |\n"
        "|--------|-------|-----------|\n"
        "| clk    | 1 bit | input     |\n"
        "\n### Producer\n"
        "| Signal | Width | Direction |\n"
        "|--------|-------|-----------|\n"
        "| p_ready| 1 bit | output    |\n"
        "| p_valid| 1 bit | input     |\n"
        "\n### Consumer\n"
        "| Signal | Width | Direction |\n"
        "|--------|-------|-----------|\n"
        "| c_ready| 1 bit | input     |\n"
        "| c_valid| 1 bit | output    |\n"
        "```systemverilog\n"
        "module bus(input clk, input c_read, output p_read, output c_valid);\n"
        "```\n"
    )
    _skel, ins, outs, _params, _defaults, _table, widths, _tb = \
        C._recover_cvdp_interface({"id": "x", "input": {"prompt": prompt}},
                                  "bus")
    assert ins == ["clk", "c_read", "p_valid", "c_ready"]
    assert outs == ["p_read", "c_valid", "p_ready"]
    assert widths["p_ready"] == 1 and widths["c_ready"] == 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
