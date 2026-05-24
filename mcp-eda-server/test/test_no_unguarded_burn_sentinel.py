#!/usr/bin/env python3
"""Wave 33 (mcp-eda v0.99.9) — verify check_no_unguarded_burn.sh works.

The sentinel is a CI guardrail. Two-axis test:

* Current source tree must PASS (exit 0). Regression caught: anything
  the wrapper / driver does still satisfies the rule.
* When we plant a deliberate violation in a temp file under src/,
  the sentinel must FAIL (exit 1) and emit the
  WAVE33_UNGUARDED_BURN_VIOLATION marker.

The fixture cleans up after itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "check_no_unguarded_burn.sh"
SRC = ROOT / "src"
assert SCRIPT.exists()


def test_current_tree_passes_sentinel():
    r = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"sentinel rejected current tree:\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_planted_violation_caught():
    # Plant a synthetic JS file with an unguarded execSync(quartus_pgm
    # ... -o "P;..." ...) and confirm the sentinel rejects it.
    decoy = SRC / "_wave33_planted_violation.js"
    decoy.write_text(
        '// synthetic violation for Wave 33 sentinel test\n'
        'function fakeBurn(sof) {\n'
        '  return execSync(`quartus_pgm -c 1 -m JTAG -o "P;${sof}"`);\n'
        '}\n'
    )
    try:
        r = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, (
            f"sentinel did NOT reject planted violation: {r.stdout}"
        )
        assert "WAVE33_UNGUARDED_BURN_VIOLATION" in r.stderr, r.stderr
        assert "_wave33_planted_violation.js" in r.stderr, r.stderr
    finally:
        if decoy.exists():
            decoy.unlink()


def test_test_fixture_violation_ignored():
    """Planting the same violation under a `test_` filename should
    NOT trip the sentinel — test fixtures are exempt."""
    decoy = SRC / "test_wave33_decoy.js"
    decoy.write_text(
        'execSync(`quartus_pgm -c 1 -m JTAG -o "P;foo.sof"`);\n'
    )
    try:
        r = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"sentinel mis-flagged test fixture:\n"
            f"stdout={r.stdout}\nstderr={r.stderr}"
        )
    finally:
        if decoy.exists():
            decoy.unlink()
