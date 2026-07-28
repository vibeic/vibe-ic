#!/usr/bin/env python3
"""Tests for analog_pre_vs_post_layout_check.py — pre/post-layout comparison gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_pre_vs_post_layout_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_analog_dir(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_dir"


def test_skip_no_pre_vs_post(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_pre_vs_post_data"


def test_pass_acceptable_degradation(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [
            {"name": "vout", "pre_layout": 3.30, "post_layout": 3.25},
            {"name": "iq", "pre_layout": 50e-6, "post_layout": 52e-6},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["specs_compared"] == 2


def test_fail_severe_degradation(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [
            {"name": "vout", "pre_layout": 3.30, "post_layout": 2.0},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("LAYOUT_SEVERE_DEGRADATION" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ── the gate and the skill that feeds it must agree on the schema ─────────
# `skills/analog-extraction-resim/SKILL.md` is the instruction an authoring
# agent follows to produce pre_vs_post.json. Its example used the container
# key "comparison" (singular); this gate has only ever read "comparisons" or
# "specs". Measured: a file built EXACTLY from the documented example was
# scored as zero comparable specs and FAILed PRE_VS_POST_ZERO_COMPARED — a
# correct result rejected for following its own instructions.

SKILL_MD = (Path(__file__).resolve().parents[2]
            / "skills" / "analog-extraction-resim" / "SKILL.md")


def _documented_pre_vs_post_example() -> dict:
    """The first ```json block in SKILL.md's `pre_vs_post.json` section."""
    text = SKILL_MD.read_text(encoding="utf-8")
    marker = "### `analog/<block>/pre_vs_post.json`"
    assert marker in text, f"SKILL.md lost its pre_vs_post.json section"
    tail = text.split(marker, 1)[1]
    assert "```json" in tail, "SKILL.md documents no JSON example"
    body = tail.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(body)


def test_documented_schema_is_the_schema_the_gate_parses(tmp_path):
    """THE discriminator. Write the skill's own documented example verbatim and
    require the gate to actually COMPARE its metrics. The example carries a
    deliberate 33% regression, so the verdict is FAIL — but it must be a FAIL
    ABOUT THE CIRCUIT, never 'zero specs compared'."""
    example = _documented_pre_vs_post_example()
    ad = tmp_path / "phase3" / "analog" / "ldo_1v8"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps(example))
    _run(tmp_path)
    rpt = _load_report(tmp_path)
    rules = {f["rule"] for f in rpt["findings"]}
    assert "PRE_VS_POST_ZERO_COMPARED" not in rules, (
        "the documented example parses as zero comparisons — SKILL.md and "
        f"analog_pre_vs_post_layout_check have drifted apart: {rpt}")
    assert rpt["summary"]["specs_compared"] == 3, rpt["summary"]


def test_documented_example_still_flags_its_severe_regression(tmp_path):
    """The non-weakening half of the same discriminator (it too fails against
    the pre-fix doc, because nothing was parsed there to judge): making the
    documented schema READABLE must not make it PASS. The example's ugb_mhz
    drops 33%, which is an ERROR band, so the verdict stays rc=1."""
    example = _documented_pre_vs_post_example()
    ad = tmp_path / "phase3" / "analog" / "ldo_1v8"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps(example))
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "LAYOUT_SEVERE_DEGRADATION" in rules


def test_guard_specs_container_and_pre_layout_keys_still_read(tmp_path):
    """Direction-1 guard: the alternative spellings the gate has always
    accepted (`specs` container, `pre_layout`/`post_layout` values) keep
    working — the doc fix must not have narrowed the parser."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "specs": [{"name": "vout", "pre_layout": 3.30, "post_layout": 3.25}]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert _load_report(tmp_path)["summary"]["specs_compared"] == 1


def test_unrecognised_container_key_names_the_schema_drift(tmp_path):
    """A gate that measured nothing must say WHY. The zero-compared finding
    now names the keys it looked for and the keys the file actually had, so a
    schema drift is diagnosable instead of reading as 'the sim produced no
    data'."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "block_name": "ldo",
        "comparison": {"gain_db": {"pre": 62.3, "post": 58.1}},
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    zero = [f for f in _load_report(tmp_path)["findings"]
            if f["rule"] == "PRE_VS_POST_ZERO_COMPARED"]
    assert zero, "an uncomparable file must still FAIL"
    msg = zero[0]["message"]
    assert "comparison" in msg and "comparisons" in msg, msg


def test_guard_genuinely_empty_comparison_set_still_fails(tmp_path):
    """Direction-1 guard: a file using the RIGHT key with nothing in it stays
    a FAIL. A comparison gate must never PASS having compared nothing."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({"comparisons": []}))
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "PRE_VS_POST_ZERO_COMPARED" in rules
