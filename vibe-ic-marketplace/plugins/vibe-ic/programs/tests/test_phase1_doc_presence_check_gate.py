#!/usr/bin/env python3
"""Tests for phase1_doc_presence_check.py"""
from __future__ import annotations
import json
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "phase1_doc_presence_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_docs(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 1


# ─────────────────────────────────────────────────────────────────────
# v0.119.40 (BACKLOG-v13 Wave 8) — --strict flag.
# Motivation: phase1-orchestrate SKILL.md pseudocode references
# `phase1_doc_presence_check.py generated_docs/ --strict` but the
# program previously rejected unknown args.
# ─────────────────────────────────────────────────────────────────────


def _seed_layers(docs_dir: Path, *, include: list[str]):
    """Create empty L*.json files for each requested layer label."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    name_for = {
        "L1": "L1_DATASHEET.json",
        "L2": "L2_FRS.json",
        "L3": "L3_CMD_PROTOCOL.json",
        "L4": "L4_REGMAP.json",
        "L5": "L5_ADI_SPEC.json",
        "L6": "L6_CONTROL_LOGIC.json",
        "L7": "L7_TEST_DEBUG.json",
        "L8T": "L8_TIMING_WAVEFORM.json",
        "L8R": "L8_RTL_CONSTANTS.json",
        "L9": "L9_INTEGRATION_SPEC.json",
    }
    for layer in include:
        (docs_dir / name_for[layer]).write_text("{}")


def test_strict_flag_accepted(tmp_path):
    """`--strict` must be a recognised CLI flag (no argparse rejection)."""
    docs = tmp_path / "phase1" / "generated_docs"
    _seed_layers(docs, include=[
        "L1", "L2", "L3", "L4", "L5",
        "L6", "L7", "L8T", "L8R", "L9",
    ])
    r = _run([str(docs), "--strict"])
    # All 10 present → strict or not, exit 0.
    assert r.returncode == 0, r.stderr + r.stdout
    assert "PASS" in r.stdout


def test_strict_promotes_no_protocol_optional_to_fail(tmp_path):
    """Under no-protocol sentinel, L3/L8R missing is `info` by default
    but becomes hard-FAIL when `--strict` is set.
    """
    docs = tmp_path / "phase1" / "generated_docs"
    _seed_layers(docs, include=[
        "L1", "L2", "L4", "L5", "L6", "L7", "L8T", "L9",
    ])
    # Activate the no-protocol sentinel via L1.
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps({"protocol_present": False}))

    # Default behaviour: sentinel-optional L3/L8R missing → info, exit 0.
    r_default = _run([str(docs)])
    assert r_default.returncode == 0, r_default.stderr + r_default.stdout

    # --strict: those same layers become hard FAIL → exit 1.
    r_strict = _run([str(docs), "--strict"])
    assert r_strict.returncode == 1, r_strict.stderr + r_strict.stdout
    assert ("missing-L3" in r_strict.stdout
            or "missing-L8R" in r_strict.stdout)
