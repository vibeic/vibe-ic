#!/usr/bin/env python3
"""Smoke tests for l5_analog_block_spec_actionable_check.py.

NEGATIVE CONTROL IS THE POINT. Every requirement below is asserted in
BOTH directions: a deliberately-gutted L5 must FAIL, and the well-formed
sibling must PASS. A test that can only pass proves nothing.

All fixtures are SYNTHESIZED neutral data — invented block names
(``blk_reg``, ``blk_ref``), invented numbers, no vendor part number, no
PDK name, no real design's files. The gate is driven by the layer's own
content and by the consumer's own parser, so neutral data exercises it
exactly as real data would.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent
        / "l5_analog_block_spec_actionable_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _consumer_block_type() -> str:
    """A block type the CONSUMER actually has a deck for.

    Read from analog_real_corner_sweep's own TARGETS table rather than
    hardcoded, so these fixtures stay valid when the sweep's deck list
    changes — same derive-don't-hardcode rule the gate itself follows.
    """
    sys.path.insert(0, str(PROG.parent))
    import analog_real_corner_sweep as ars  # type: ignore
    targets = getattr(ars, "TARGETS", {})
    # Prefer a type whose static row HAS a numeric target, so the
    # fixture exercises the ordinary path rather than the
    # informational-target carve-out.
    for name, row in targets.items():
        if isinstance(row, dict) and row.get("target") is not None:
            return str(name)
    return next(iter(targets))


def _mk(tmp_path: Path, l5: dict, name: str = "p") -> Path:
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps(l5), encoding="utf-8")
    # A minimal L1 so ic_class detection does not land on bare_fpga.
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "synth_part", "interface": "mixed signal"}),
        encoding="utf-8")
    return proj


def _well_formed_block(btype: str) -> dict:
    """A block the A-track consumer can fully act on."""
    return {
        "name": "blk_reg",
        "type": btype,
        "spec": {
            "specs": [
                {"name": "Vout", "target": 1.0, "unit": "V"},
                {"name": "Iout", "target": 0.25, "unit": "mA"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# POSITIVE CONTROL — a well-formed layer must PASS.
# ---------------------------------------------------------------------------

def test_positive_control_wellformed_l5_passes(tmp_path):
    btype = _consumer_block_type()
    proj = _mk(tmp_path, {
        "analog_blocks_detected": True,
        "analog_blocks": [_well_formed_block(btype)],
        "no_analog": False,
    })
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS — each gutted layer must FAIL.
# ---------------------------------------------------------------------------

def test_negative_control_spec_as_bare_string_fails(tmp_path):
    """THE motivating defect: the numbers ARE in L5, as a human-readable
    string. l5_block_specs() — the consumer's own parser — returns {},
    so the sweep silently grades against a generic default instead."""
    btype = _consumer_block_type()
    blk = _well_formed_block(btype)
    blk["spec"] = "1.0 V core, 0.25 mA load, 125 C"   # token present, not actionable
    proj = _mk(tmp_path, {
        "analog_blocks_detected": True,
        "analog_blocks": [blk],
        "no_analog": False,
    })
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout
    assert "l5_block_specs()" in r.stdout


def test_negative_control_spec_dict_without_numeric_bound_fails(tmp_path):
    """A structured spec whose entries carry no target/min/max is still
    unusable — the consumer needs a NUMBER to grade against."""
    btype = _consumer_block_type()
    blk = _well_formed_block(btype)
    blk["spec"] = {"specs": [{"name": "Vout", "unit": "V",
                              "note": "see datasheet"}]}
    proj = _mk(tmp_path, {"analog_blocks": [blk]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout


def test_negative_control_missing_type_fails(tmp_path):
    """No type => _pick_block_type falls back to name-as-type, the
    consumer has no deck, and the block is never simulated."""
    btype = _consumer_block_type()
    blk = _well_formed_block(btype)
    blk.pop("type")
    proj = _mk(tmp_path, {"analog_blocks": [blk]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "_pick_block_type" in r.stdout


def test_negative_control_unknown_type_fails(tmp_path):
    blk = _well_formed_block("a_type_no_deck_exists_for")
    proj = _mk(tmp_path, {"analog_blocks": [blk]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no deck" in r.stdout


def test_negative_control_missing_name_fails(tmp_path):
    btype = _consumer_block_type()
    blk = _well_formed_block(btype)
    blk.pop("name")
    proj = _mk(tmp_path, {"analog_blocks": [blk]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# NO-FALSE-POSITIVE controls — legitimately-empty / honest layers.
# ---------------------------------------------------------------------------

def test_pure_digital_design_skips(tmp_path):
    """L5 is the analog-digital INTERFACE layer; a pure-digital design
    legitimately has it empty and must not be penalised."""
    proj = _mk(tmp_path, {
        "analog_blocks_detected": False,
        "analog_blocks": [],
        "no_analog": True,
    })
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout


def test_missing_l5_skips(tmp_path):
    proj = tmp_path / "empty"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr


def test_honest_silence_low_confidence_warns_not_fails(tmp_path):
    """A block with NO spec that L5 itself marks low_confidence is an
    honest extraction gap. Fabricating a target would be worse than
    admitting the gap, so this WARNs and does not block."""
    btype = _consumer_block_type()
    proj = _mk(tmp_path, {"analog_blocks": [
        {"name": "blk_ref", "type": btype, "low_confidence": True},
    ]})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[WARN]" in r.stdout
    assert "[PASS]" in r.stdout


def test_waiver_suppresses_fail(tmp_path):
    btype = _consumer_block_type()
    blk = _well_formed_block(btype)
    blk["spec"] = "1.0 V core"
    proj = _mk(tmp_path, {"analog_blocks": [blk]})
    (proj / "waivers.json").write_text(json.dumps({
        "l5_analog_block_spec_degraded_intentional":
            "This synthesized fixture intentionally keeps the prose spec "
            "form to exercise the documented waiver path end to end.",
    }), encoding="utf-8")
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "waived" in r.stdout


# ---------------------------------------------------------------------------
# The negative control must be a real control: prove the SAME fixture
# flips verdict on the one edit that matters.
# ---------------------------------------------------------------------------

def test_both_directions_on_one_edit(tmp_path):
    """Gut exactly one thing — the spec's FORM, not its content — and the
    verdict must flip. Same block, same numbers, same everything else."""
    btype = _consumer_block_type()

    good = _mk(tmp_path, {"analog_blocks": [_well_formed_block(btype)]},
               name="good")
    bad_blk = _well_formed_block(btype)
    bad_blk["spec"] = "Vout 1.0 V, Iout 0.25 mA"   # same numbers, prose form
    bad = _mk(tmp_path, {"analog_blocks": [bad_blk]}, name="bad")

    r_good, r_bad = _run(good), _run(bad)
    assert r_good.returncode == 0, r_good.stdout
    assert r_bad.returncode == 1, r_bad.stdout
    assert r_good.returncode != r_bad.returncode
