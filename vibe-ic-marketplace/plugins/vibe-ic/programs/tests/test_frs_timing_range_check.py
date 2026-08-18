#!/usr/bin/env python3
"""Tests for frs_timing_range_check.py (LL-20).

v0.119.16 generalised the regex to `_(us|ms|ns|ps|cyc|ticks)$` —
chip-agnostic across LIN / K-line / 1-Wire / EXAMPLE_PROTOCOL-bus / custom.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "frs_timing_range_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _write_l2(tmp_path: Path, data: dict, name: str = "L2_FRS.json"):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data))


def test_no_l2_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


def test_no_timing_keys_silent_pass(tmp_path):
    """L2 exists but has no `*_us/_ms/_ns/_ps/_cyc/_ticks` keys."""
    _write_l2(tmp_path, {
        "name": "MyChip", "version": 3, "description": "...",
    })
    r = _run(tmp_path)
    assert r.returncode == 0


def test_well_formed_number_passes(tmp_path):
    _write_l2(tmp_path, {"tWFT_us": 20, "ibt_us": [8.5, 22]})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_well_formed_dict_min_max_passes(tmp_path):
    _write_l2(tmp_path, {"tSRS_us": {"min": 20, "max": 80}})
    r = _run(tmp_path)
    assert r.returncode == 0


def test_value_kind_dict_passes(tmp_path):
    _write_l2(tmp_path, {"frame_end_gap_us": {"value": 30, "kind": "TYP"}})
    r = _run(tmp_path)
    assert r.returncode == 0


def test_string_value_fails(tmp_path):
    """`"tSRS_us": "20"` (string number, not bare number)."""
    _write_l2(tmp_path, {"tSRS_us": "20"})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "string number" in r.stdout


def test_prose_value_fails(tmp_path):
    _write_l2(tmp_path, {"tSRS_us": "short window after host last bit"})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "prose" in r.stdout


def test_null_value_fails(tmp_path):
    _write_l2(tmp_path, {"ibt_us": None})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "null" in r.stdout


def test_three_element_list_fails(tmp_path):
    """Range list must be exactly 2 elements."""
    _write_l2(tmp_path, {"ibt_us": [8.5, 15, 22]})
    r = _run(tmp_path)
    assert r.returncode == 1


def test_chip_agnostic_protocol_naming_passes(tmp_path):
    """v0.119.16: regex matches generic units, not protocol-specific names.
    A LIN / K-line project using `tBitRate_us` (no canonical name) gets
    structurally checked."""
    _write_l2(tmp_path, {
        "tBitRate_us": [50, 100],
        "tBreakDelim_ms": 5,
        "frame_clk_cyc": [16, 32],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_waiver_skips(tmp_path):
    _write_l2(tmp_path, {"tSRS_us": "ambiguous"})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "frs_timing_unstructured_intentional": "Vendor doc is prose-only",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_container_key_with_unit_suffix_recurses(tmp_path):
    """v0.119.23 fix: a container key that happens to end in `_us` (e.g.
    `response_timing_us` carrying nested setup/hold dicts) must NOT be
    treated as a malformed timing leaf. Recurse into the container; only
    leaf-shaped values get checked."""
    _write_l2(tmp_path, {
        "response_timing_us": {
            "setup": [5, 10],     # well-formed leaf
            "hold":  [3, 8],      # well-formed leaf
        },
        "tSRS_us": [20, 80],      # also well-formed leaf
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_container_with_bad_inner_leaf_still_fails(tmp_path):
    """Container key recursion must not hide real bugs in inner leaves.
    If `response_timing_us.setup` is prose, the inner key is flagged."""
    _write_l2(tmp_path, {
        "response_timing_us": {
            "setup_us": "ambiguous prose",   # malformed leaf
            "hold_us":  [3, 8],
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "setup_us" in r.stdout
