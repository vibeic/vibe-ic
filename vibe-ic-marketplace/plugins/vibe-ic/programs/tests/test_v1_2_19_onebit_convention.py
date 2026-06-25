"""CVDP spec-extraction: numbered-clock + AMBA 1-bit control width convention.

A port the spec lists with NO `[range]` and described as a single clock/control
signal is 1-bit by Verilog convention (a §3.9 interface fact, not a guess). The
1-bit detector missed two general shapes, so these ports were flagged
`width_not_stated` and the record stayed SPEC_ABSENT:
  * NUMBERED clocks `clk1` / `clk2` / `clock0` (a clock is always 1-bit).
  * AMBA control/handshake words — APB `pwrite`/`psel(x)`/`penable`/`pready`/
    `pslverr`, AXI `*valid`/`*ready` and `wlast`/`rlast` (each 1-bit by the
    published protocol spec).
Field: COMPLETE 226 -> 229 (GFCM, axi_register, montgomery flip to COMPLETE).

§4.05 NO-LEAK: a DATA bus that merely shares a substring (`pwdata`, `paddr`,
`pstrb`, `clksource_value`) is NOT mis-sized to 1; only the exact control words.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import cvdp_complete_extract as E  # noqa: E402

_DATASET = Path("/home/reyerchu/AI_IC_design/_extbench/cvdp_open_v110/"
                "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


def _records():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    return {json.loads(l)["id"]: json.loads(l)
            for l in _DATASET.read_text().splitlines()}


# ── numbered clocks ──
def test_numbered_clocks_one_bit():
    for nm in ("clk1", "clk2", "clock0", "clk", "pclk"):
        assert E._CLK_RE.match(nm), nm


def test_clock_data_name_not_clock():
    # a name that merely starts with 'clk' but is a data/value signal is not a clock
    assert not E._CLK_RE.match("clksource_value")
    assert not E._CLK_RE.match("clock_divider_ratio")


# ── AMBA 1-bit control words ──
def test_apb_axi_control_one_bit():
    for nm in ("pwrite", "psel", "pselx", "psel0", "penable", "pready",
               "pslverr", "awvalid", "wvalid", "bready", "rready", "wlast", "rlast"):
        assert E._ONE_BIT_RE.match(nm), nm


def test_amba_data_buses_not_one_bit():
    # data / address / strobe buses are multi-bit — must NOT be forced to 1
    for nm in ("pwdata", "prdata", "paddr", "pstrb", "araddr", "wdata", "rdata"):
        assert not E._ONE_BIT_RE.match(nm), nm


def test_pselxyz_not_matched():
    assert not E._ONE_BIT_RE.match("pselxyz")


# ── dataset outcome ──
def test_dataset_gfcm_complete():
    r = _records().get("cvdp_copilot_GFCM_0001")
    if r is None:
        pytest.skip("record absent")
    # clk1/clk2 are the only width gaps; both are 1-bit clocks -> COMPLETE.
    assert E.extract(r).get("completeness") == "COMPLETE"


def test_dataset_axi_register_complete():
    r = _records().get("cvdp_copilot_axi_register_0001")
    if r is None:
        pytest.skip("record absent")
    assert E.extract(r).get("completeness") == "COMPLETE"


def test_completeness_floor_and_no_regression():
    recs = _records()
    comp = sum(1 for r in recs.values()
               if E.extract(r).get("completeness") == "COMPLETE")
    assert comp >= 229, f"COMPLETE regressed: {comp}"
