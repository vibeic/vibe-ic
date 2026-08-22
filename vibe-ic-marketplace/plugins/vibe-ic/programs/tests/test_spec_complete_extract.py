"""spec_complete_extract — the GENERAL completeness engine (benchmark-agnostic).

Proves the per-record completeness machinery that drove CVDP 210->229 now serves a
plain Phase-1 design doc (NO cocotb harness): the interface is SUPPLIED (a port
list, as L-docs provide), and every benchmark-convergence width fix (Default-column
param table, param-expression widths, log2ceil, clk/rst/1-bit conventions) applies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_complete_extract as E  # noqa: E402
import cvdp_complete_extract as C  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

_FIFO_DOC = """Design a synchronous FIFO `my_fifo`.
## Parameters
| Parameter | Description | Default | Constraints |
| `DATA_WIDTH` | data bus width | 8 | >= 1 |
| `DEPTH` | entries | 16 | power of 2 |
## Ports
- `clk`: clock.
- `rst_n`: active-low async reset.
- `wr_en`: write enable.
- `rd_en`: read enable.
- `[DATA_WIDTH-1:0] din`: write data.
- `[DATA_WIDTH-1:0] dout`: read data.
- `full`: FIFO full flag.
- `empty`: FIFO empty flag.
"""


def test_general_doc_no_harness_is_complete():
    spec = E.assess_spec(
        _FIFO_DOC,
        inputs=["clk", "rst_n", "wr_en", "rd_en", "din"],
        outputs=["dout", "full", "empty"],
        module_name="my_fifo")
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]
    assert spec["gaps"] == []
    widths = {p["name"]: p["width"] for p in spec["interface"]}
    # the benchmark Default-column width fix resolves DATA_WIDTH=8 for a general doc
    assert widths["din"] == 8 and widths["dout"] == 8
    # clk/rst/control ports are 1-bit by convention
    assert widths["clk"] == 1 and widths["rst_n"] == 1 and widths["full"] == 1


def test_general_doc_missing_data_width_is_gap():
    # a DATA port the doc never sizes -> honest gap, NOT a fabricated width
    doc = ("Design a block `blk`. Ports: `clk`, `data_bus` (the main data path), "
           "`valid_o`.")
    spec = E.assess_spec(doc, inputs=["clk", "data_bus"], outputs=["valid_o"],
                         module_name="blk")
    assert spec["completeness"].startswith("INCOMPLETE")
    assert any("data_bus" in g["detail"] for g in spec["gaps"])
    # clk + valid_o still placed as 1-bit; only data_bus is the gap
    assert any(p["name"] == "clk" and p["width"] == 1 for p in spec["interface"])


def test_no_interface_source_is_spec_absent():
    spec = E.assess_spec("Some prose with no ports.", inputs=[], outputs=[])
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT"


def test_skeleton_iface_passthrough():
    sk = [{"name": "a", "dir": "input", "width": 4, "signed": False,
           "source": "skeleton_header"}]
    spec = E.assess_spec("prose", inputs=[], outputs=[], skeleton_iface=sk)
    assert spec["interface"] == sk and spec["completeness"] == "COMPLETE"


def test_cvdp_adapter_complete_count_is_prompt_context_only():
    """The CVDP adapter reads ONLY input.prompt + input.context (§4.05 compliance:
    the model sees only the submitter-visible spec; the hidden cocotb `dut.<sig>`
    test, the `.env` TOPLEVEL and the golden output are OFF-LIMITS oracle). Over the
    real 302-record dataset the COMPLETE count therefore reflects PROMPT+CONTEXT
    interface recovery — the compliant clean-room baseline, NOT the old
    harness-inflated 255 (which counted records whose interface was recoverable only
    from the cocotb harness).

    ORGANIC-20260703 (cvdp_complete_extract phantom-port + skeleton fix) raised the
    clean-room baseline 215 -> 223, ALL prompt+context-only:
      * +9 — the adapter now parses the PROMPT's own ```verilog module <top>( ANSI
        skeleton (a legitimate input.prompt fact, previously ignored) so a record
        whose full interface is declared in the prompt header resolves COMPLETE
        instead of being mis-read by the prose parser (verified: each of the 9 has a
        2-18 port prompt skeleton — flop/crossbar/image_rotate/…);
      * -1 — `binary_to_gray_0001` was COMPLETE only on PHANTOM ports `wire`/`output`
        (Verilog keywords mis-parsed as port names); the reserved-word guard drops
        them, so its honest verdict is now INCOMPLETE_SPEC_ABSENT.
    Both moves are pure prompt+context correctness — no harness read."""
    ds = require_corpus("_extbench/cvdp_open_v110/"
                        "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
    if not ds.exists():
        pytest.skip("dataset not present")
    recs = [json.loads(l) for l in ds.read_text().splitlines()]
    comp = sum(1 for r in recs if C.extract(r)["completeness"] == "COMPLETE")
    # ORGANIC-20260705: the v1.2.96 harness-read removal replaced the oracle
    # interface path with `_table_interface` (test-case tables) + `_prose_ports`
    # ONLY, silently dropping two common PROMPT interface forms — the markdown
    # Signal/Direction/Width table and the `- `name` (input, N bits):` prose bullet
    # list. Restoring both input-only parsers recovered 223 -> 226 (comparator via
    # the signal-direction table; apb_dsp_unit + sorter via the prose-bullet list),
    # all prompt-sourced, ZERO harness reads, and a strict superset of the 223 set.
    #
    # 2026-07-13 (PR #130 `recover_interface_from_prompt`, cvdp RCA distillation):
    # a "modify existing RTL" prompt that RE-DECLARES its interface in an explicit
    # "Updated Input/Output Interfaces" prose section is now parsed from input.prompt
    # (authoritative over the stale context-RTL header). This recovered 226 -> 228:
    # +apb_gpio_0001 and +packet_controller_0001, BOTH sourced solely from
    # input.prompt (verified: neutralizing recover_interface_from_prompt drops the
    # count back to exactly 226), a strict superset (no COMPLETE lost) and ZERO
    # harness/golden reads. This is the §4.05-compliant clean-room baseline.
    assert comp == 228, f"CVDP COMPLETE (prompt+context only) drifted to {comp}"
    # §4.05: the cocotb harness signal-set block is NO LONGER re-attached; the
    # supplied (prompt+context) interface is echoed in `interface_source` instead.
    s = C.extract(recs[0])
    assert "harness" not in s, "the OFF-LIMITS cocotb harness block must not be re-attached"
    assert "interface_source" in s
