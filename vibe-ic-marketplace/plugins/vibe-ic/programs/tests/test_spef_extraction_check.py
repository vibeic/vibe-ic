#!/usr/bin/env python3
"""Tests for spef_extraction_check.py (G1: Parasitic Extraction)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "spef_extraction_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_spef(path: Path, content: str = "", size: int = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    if content:
        path.write_text(content)
    else:
        path.write_bytes(b"\x00" * size)


_VALID_SPEF = (
    '*SPEF "IEEE 1481-1998"\n'
    '*DESIGN "top"\n'
    '*DATE "2026-04-29"\n'
    + "".join(f"*D_NET net_{i} {i * 0.001:.4f}\n*CONN\n*END\n"
              for i in range(80))
)


def test_pass_valid_spef(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", _VALID_SPEF)
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True
    assert report["summary"]["spef_files"] == 1


def test_fail_no_extracted_dir(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_spef_files(tmp_path):
    (tmp_path / "phase3" / "stage3" / "extracted").mkdir(parents=True)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_empty_spef(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", "")
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_too_small(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", size=500)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_header(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef",
               "some random text\n" * 200)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2


def test_pass_with_pdk_unavailable_waiver(tmp_path):
    """v0.119.21: custom open-source PDKs (commercial 180nm PDK, etc.)
    have no Magic .tech for parasitic extraction. With a documented
    spef_extraction_unavailable_reason ≥20 chars, the gate accepts the
    deferral instead of blocking forever on a tool-unavailable wall."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "spef_extraction_unavailable_reason":
            "commercial 180nm PDK has no Magic tech file; SPEF extraction "
            "deferred until foundry sign-off uses commercial Calibre",
    }))
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"].get("waived") is True


def test_short_reason_does_not_pass_waiver(tmp_path):
    """Anti-rubber-stamp: <20-char reason rejected just like the
    waivers_schema_check policy."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "spef_extraction_unavailable_reason": "tool busted",
    }))
    result = _run(tmp_path)
    assert result.returncode == 1, "rubber-stamp waiver must NOT pass"


# ---------------------------------------------------------------------------
# D9 — the gate must read the VALUES, not only count the records.
#
# The D9 content census scored step 22 EXISTENCE-ONLY: scaling every number in
# the SPEF left the verdict unchanged, because `scan_spef` counted `*D_NET` and
# `*CAP` records and never looked at what they carried. A count does not move
# when a value does.
#
# NO ORACLE. Nothing below knows what any parasitic SHOULD be — a real run ships
# no answer key. It knows only what a capacitance CANNOT be: negative, in any
# unit, under any extractor, for any technology. Measured over every published
# SPEF in this repo before the rule was written: 114459 *CAP entries, 0 negative.
# ---------------------------------------------------------------------------

_CAP_SPEF = (
    '*SPEF "IEEE 1481-1998"\n'
    '*DESIGN "top"\n'
    '*DATE "2026-08-12"\n'
    + "".join(f"*D_NET net_{i} {0.01 + i * 0.001:.5f}\n"
              f"*CAP\n1 net_{i}:1 {0.004 + i * 0.0001:.6f}\n"
              f"2 net_{i}:2 net_{i + 1}:1 {0.002:.6f}\n*END\n"
              for i in range(80))
)


def _findings(tmp_path: Path) -> list:
    return [f["category"] for f in
            json.loads((tmp_path / "out.json").read_text())["findings"]]


def test_a_physically_possible_extraction_still_PASSES(tmp_path):
    """THE INVERSE ARM, first. Every value non-negative, as every published
    SPEF in this repo is. A rule that reddened these would be a ban."""
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", _CAP_SPEF)
    assert _run(tmp_path).returncode == 0


def test_ONE_negative_cap_among_many_reddens_the_gate(tmp_path):
    """The sharp case: a single sign flip in a body of otherwise valid entries.

    Measured on the real published `espi` SPEF — one flipped sign among 114459
    entries is caught.
    """
    spef = _CAP_SPEF.replace("1 net_7:1 0.004700", "1 net_7:1 -0.004700", 1)
    assert spef != _CAP_SPEF, "fixture drifted: the target line was not replaced"
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", spef)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NEGATIVE_PARASITIC" in _findings(tmp_path), _findings(tmp_path)


def test_a_negative_D_NET_total_reddens_too(tmp_path):
    """The other place a capacitance is stated: the net's declared total."""
    spef = _CAP_SPEF.replace("*D_NET net_3 0.01300", "*D_NET net_3 -0.01300", 1)
    assert spef != _CAP_SPEF, "fixture drifted: the target line was not replaced"
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", spef)
    assert _run(tmp_path).returncode == 1
    assert "NEGATIVE_PARASITIC" in _findings(tmp_path)


def test_scaling_EVERY_value_is_caught(tmp_path):
    """The census's own generic corruption, as a permanent test.

    Each value stays individually plausible in magnitude; the extraction stops
    being physically possible. This is the mutation that scored step 22
    EXISTENCE-ONLY before the criterion existed.
    """
    import re
    scaled = re.sub(r"\d+\.\d+",
                    lambda m: f"{-(float(m.group(0)) * 3 + 7):.6f}", _CAP_SPEF)
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", scaled)
    assert _run(tmp_path).returncode == 1
    assert "NEGATIVE_PARASITIC" in _findings(tmp_path)
