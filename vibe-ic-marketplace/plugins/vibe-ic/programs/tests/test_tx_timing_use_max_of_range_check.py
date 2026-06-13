#!/usr/bin/env python3
"""Tests for tx_timing_use_max_of_range_check.py (LL-15)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "tx_timing_use_max_of_range_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _make_half_duplex(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "command_table": [{"opcode": "0x10", "name": "x"}],
    }))


def _write_pkg(tmp_path: Path, body: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "pkg.sv").write_text(body)


def test_non_half_duplex_silent_pass(tmp_path):
    """No L2/L3 markers → silent skip."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not half-duplex" in r.stdout


def test_no_constants_silent_pass(tmp_path):
    """Half-duplex but no IBT/tSRS constants in pkg → silent skip."""
    _make_half_duplex(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "could not locate" in r.stdout or "PASS" in r.stdout


def test_ibt_above_threshold_passes(tmp_path):
    """IBT (22us) >= 0.5 × tSRS_min (20) = 10us → PASS."""
    _make_half_duplex(tmp_path)
    _write_pkg(tmp_path, """\
package my_pkg;
  localparam int TX_IBT = 1100;     // 22.0 us
  localparam int TSRS_MIN = 1000;   // 20.0 us
endpackage
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_ibt_below_threshold_fails(tmp_path):
    """IBT (8us) < 0.5 × tSRS_min (20) = 10us → FAIL.
    Classic fresh-agent confusion of IBT with BR threshold."""
    _make_half_duplex(tmp_path)
    _write_pkg(tmp_path, """\
package my_pkg;
  localparam int TX_IBT = 400;      // 8.0 us  (host BR_max)
  localparam int TSRS_MIN = 1000;   // 20.0 us
endpackage
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "too short" in r.stdout


def test_waiver_skips(tmp_path):
    _make_half_duplex(tmp_path)
    _write_pkg(tmp_path, """\
package my_pkg;
  localparam int TX_IBT = 400;      // 8.0 us
  localparam int TSRS_MIN = 1000;   // 20.0 us
endpackage
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "tx_ibt_short_intentional": "Custom low-latency variant",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_v027_localparam_no_type_qualifier_accepted(tmp_path):
    """v0.119.27: agent wrote `localparam TIBT_TICKS = 1135;` without
    type qualifier (valid SystemVerilog defaults to logic [31:0]).
    Earlier required-type regex silently missed it and the gate fell
    back to spec values, often flagging FAIL incorrectly."""
    _make_half_duplex(tmp_path)
    _write_pkg(tmp_path, """\
package my_pkg;
  localparam TIBT_TICKS = 1135;     // 22.7 us
  localparam TSRS_MIN_TICKS = 1000; // 20.0 us
endpackage
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "22.70us" in r.stdout or "22.7" in r.stdout


def test_v027_l2_direct_us_keys_used_as_fallback(tmp_path):
    """v0.119.27: L2 may store timing as flat `tIBT_us` / `tSRS_us`
    keys rather than nested name/physical_value records. The gate now
    accepts that schema as a fallback when no RTL pkg constant matches."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "tIBT_us": 22.7,
        "tSRS_us": 20.0,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "22.70" in r.stdout or "PASS" in r.stdout


def test_v028_direct_us_key_deeply_nested(tmp_path):
    """v0.119.28: pin docstring claim — `_direct_us_key()` recurses
    fully (depth > 1) through nested dicts. Bury the timing leaf 3
    levels deep and the gate must still pick it up."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "timing": {
            "tx_chain": {
                "ibt_group": {
                    "tIBT_us": [8.5, 22],   # buried 3 dicts deep
                },
            },
        },
    }))
    # Provide enough scaffolding for the gate to actually evaluate IBT
    docs2 = tmp_path / "phase2" / "stage1" / "rtl"
    docs2.mkdir(parents=True, exist_ok=True)
    (docs2 / "constants.sv").write_text(
        "package c; localparam int TIBT_TICKS = 425; endpackage\n"
    )
    r = _run(tmp_path)
    # Whether PASS / FAIL depends on the value vs ticks math; what we're
    # asserting here is that the lookup *succeeded* — i.e. the gate did
    # NOT report "no L2 IBT timing" / silent-skip on missing lookup.
    assert "no L2 IBT" not in r.stdout, \
        f"deeply nested _us key must be found by recursion: {r.stdout}"


def test_v028_direct_us_key_inside_list_not_found(tmp_path):
    """Negative companion: a timing leaf inside a LIST of records is
    opaque to `_direct_us_key()`. Documenting the boundary so callers
    don't expect this schema to work via this helper alone."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "timing_table": [
            {"name": "tIBT", "tIBT_us": 22},   # list of dicts, not dict
        ],
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "constants.sv").write_text(
        "package c; localparam int TIBT_TICKS = 425; endpackage\n"
    )
    r = _run(tmp_path)
    # The lookup misses — gate falls back to its other paths or skips.
    # We're just pinning the documented limitation; either skip or a
    # different code path is acceptable, but it should NOT crash.
    assert r.returncode in (0, 1), \
        f"unexpected crash on list-record schema: rc={r.returncode}\n{r.stdout}"
