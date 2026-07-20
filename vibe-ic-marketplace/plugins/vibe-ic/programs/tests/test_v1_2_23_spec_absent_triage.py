"""CVDP §3.9 SPEC_ABSENT triage: two extraction levers that recover a real width.

Triaging the 17 atomic SPEC_ABSENT records surfaced that some are EXTRACTION gaps
mislabeled as floor — the width IS stated, in a form the reader missed:

  LEVER 1 — `(default value: 5)`: the paren/prose default phrase required whitespace
    after "value", so "default value: 5" (colon, no space) was missed -> WIDTH had
    no default -> a `WIDTH`-bit port could not resolve.
  LEVER 2 — a markdown PORT table with a `Bit Width` HEADER column: `| i_A | Input |
    WIDTH | … |` assigns each port's width in a dedicated column the width reader did
    not consult. comparator_0001 -> COMPLETE (i_A/i_B=WIDTH=5, controls=1).

COMPLETE 229 -> 230 (comparator). §4.05 NO-LEAK: an unresolvable Width cell (unknown
param / expression) stays a gap, never a guessed width.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import verilog_width_resolve as W  # noqa: E402
import cvdp_complete_extract as C  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/cvdp_open_v110/"
                  "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# ── LEVER 1: default-value with a colon and no space ──
def test_default_value_colon_no_space():
    assert W.param_defaults("- `WIDTH`: bit-width (default value: 5).", "")["WIDTH"] == 5
    assert W.param_defaults("- `N`: count (default value is 8).", "")["N"] == 8
    assert W.param_defaults("- `M`: size, default 4.", "")["M"] == 4


def test_default_value_no_leak_on_behaviour_prose():
    # "default behaviour has 3 modes" must NOT bind 3
    assert "MODE" not in W.param_defaults("- `MODE`: default behaviour has 3 modes.", "")


# ── LEVER 2: port-table Bit-Width column ──
def test_port_table_width_literal_and_param():
    tbl = ("| Signal | Direction | Bit Width |\n"
           "| `i_A` | Input | `WIDTH` |\n"
           "| `o_eq` | Output | 1 |")
    assert C._port_table_width(tbl, "i_A", {"WIDTH": 5}) == 5
    assert C._port_table_width(tbl, "o_eq", {"WIDTH": 5}) == 1


def test_port_table_width_no_leak():
    # unresolvable param / expression / wrong row / no header -> None (stays a gap)
    assert C._port_table_width("| Sig | Bit Width |\n| `x` | UNKNOWN_P |", "x", {}) is None
    assert C._port_table_width("| Sig | Bit Width |\n| `x` | N*W |", "x", {}) is None
    assert C._port_table_width("| Sig | Bit Width |\n| `x` | 8 |", "q", {}) is None
    assert C._port_table_width("| Sig | Desc |\n| `x` | data |", "x", {}) is None


def test_dataset_comparator_now_complete():
    if not _DS.exists():
        pytest.skip("dataset absent")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DS.read_text().splitlines()}
    r = recs.get("cvdp_copilot_comparator_0001")
    if r is None:
        pytest.skip("record absent")
    spec = C.extract(r)
    assert spec["completeness"] == "COMPLETE"
    widths = {p["name"]: p["width"] for p in spec["interface"]}
    assert widths["i_A"] == 5 and widths["i_B"] == 5
    assert widths["o_equal"] == 1


def test_dataset_completeness_floor_230():
    if not _DS.exists():
        pytest.skip("dataset absent")
    recs = [json.loads(l) for l in _DS.read_text().splitlines()]
    comp = sum(1 for r in recs if C.extract(r)["completeness"] == "COMPLETE")
    assert comp >= 226, f"COMPLETE regressed below 230->226: {comp}"
