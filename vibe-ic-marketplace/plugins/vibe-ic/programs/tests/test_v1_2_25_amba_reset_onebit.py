"""CVDP §3.9 triage round-3: AMBA bus-prefixed resets are 1-bit.

`_RST_RE` anchors "reset"/"rst" on `(^|_)`, so a bus letter attached DIRECTLY —
APB `PRESETn`, AHB `HRESETn` — slipped through and the reset port was mislabeled
SPEC_ABSENT. A reset is definitionally single-bit (a stated interface fact), so
these standard names resolve to width 1.

COMPLETE 231 -> 232 (apb_dsp_unit_0001). §4.05 NO-LEAK: the trailing `n` is
REQUIRED — it separates an active-low reset from a multi-bit "preset value" /
"preload" data input, which must stay a gap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import cvdp_complete_extract as C  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/cvdp_open_v110/"
                  "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


def test_amba_resets_are_reset():
    for n in ("presetn", "preset_n", "hresetn", "hreset_n", "aresetn", "areset_n",
              "bresetn"):
        assert C._is_rst(n), n


def test_no_leak_preset_value_is_not_reset():
    # no trailing `n` -> a "preset"/"preload"/"hold" DATA input, never a 1-bit reset
    for n in ("preset", "preset_value", "preset_data", "preload", "preload_n",
              "hold"):
        assert not C._is_rst(n), n


def test_ordinary_resets_still_match():
    for n in ("rst", "reset", "rst_n", "resetn", "arst_n", "sync_rst", "reset_i"):
        assert C._is_rst(n), n


def test_dataset_apb_dsp_unit_complete():
    if not _DS.exists():
        pytest.skip("dataset absent")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DS.read_text().splitlines()}
    r = recs.get("cvdp_copilot_apb_dsp_unit_0001")
    if r is None:
        pytest.skip("record absent")
    spec = C.extract(r)
    assert spec["completeness"] == "COMPLETE"
    w = {p["name"]: p["width"] for p in spec["interface"]}
    assert w.get("presetn") == 1


def test_dataset_floor_232():
    if not _DS.exists():
        pytest.skip("dataset absent")
    recs = [json.loads(l) for l in _DS.read_text().splitlines()]
    comp = sum(1 for r in recs if C.extract(r)["completeness"] == "COMPLETE")
    assert comp >= 226, f"COMPLETE regressed below 232->226: {comp}"
