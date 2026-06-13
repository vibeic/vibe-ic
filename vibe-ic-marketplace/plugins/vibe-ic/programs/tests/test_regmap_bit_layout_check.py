#!/usr/bin/env python3
"""Tests for regmap_bit_layout_check.py (LL-21)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "regmap_bit_layout_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _write_l4(tmp_path: Path, registers: list):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L4_REGMAP.json").write_text(json.dumps({
        "registers": registers,
    }))


def test_no_l4_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


def test_explicit_bit_passes(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG0", "addr": 0,
        "bit_fields": [
            {"name": "PH", "bit": 7},
            {"name": "PT", "bit": 6},
        ],
    }])
    r = _run(tmp_path)
    assert r.returncode == 0


def test_msb_lsb_passes(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG1",
        "bit_fields": [{"name": "MODE", "msb": 5, "lsb": 4}],
    }])
    r = _run(tmp_path)
    assert r.returncode == 0


def test_bits_list_passes(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG2",
        "bit_fields": [{"name": "FLAGS", "bits": [3, 4, 5]}],
    }])
    r = _run(tmp_path)
    assert r.returncode == 0


def test_bit_range_string_passes(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG3",
        "bit_fields": [{"name": "RES", "bit_range": "5:4"}],
    }])
    r = _run(tmp_path)
    assert r.returncode == 0


def test_missing_bit_position_fails(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG0",
        "bit_fields": [{"name": "PH"}, {"name": "PT", "bit": 6}],
    }])
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "REG0.PH" in r.stdout


def test_null_bit_fails(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG0",
        "bit_fields": [{"name": "PH", "bit": None}],
    }])
    r = _run(tmp_path)
    assert r.returncode == 1


def test_per_field_waiver_skips(tmp_path):
    _write_l4(tmp_path, [{
        "name": "REG0",
        "bit_fields": [{"name": "RSV"}],
    }])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "regmap_bit_layout_unresolved": [
            "REG0.RSV — vendor doc names but does not place; needs silicon decode",
        ],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0


def _write_l4_dict(tmp_path: Path, registers: dict):
    """Alternate schema: registers as dict, fields under `bits` dict."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L4_REGMAP.json").write_text(json.dumps({
        "registers": registers,
    }))


def test_dict_schema_explicit_bits_passes(tmp_path):
    """Regression for v0.119.19: registers may be a dict-of-dicts with
    inner `bits` dict (the schema regmap-gen actually emitted in the
    v0.119.18 vendor benchmark). Earlier code crashed with AttributeError
    `'str' object has no attribute 'get'` on this schema."""
    _write_l4_dict(tmp_path, {
        "REG0": {
            "addr_in_otp": 0x60,
            "bits": {
                "PH": {"bit": 7, "default": 0, "rw": "RW"},
                "PT": {"bit": 6, "default": 0, "rw": "RW"},
            },
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_dict_schema_missing_bit_fails(tmp_path):
    """Same dict schema but PH lacks a bit position — must FAIL cleanly,
    not crash."""
    _write_l4_dict(tmp_path, {
        "REG0": {
            "bits": {
                "PH": {"default": 0, "rw": "RW"},  # no bit
                "PT": {"bit": 6},
            },
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "REG0.PH" in r.stdout
