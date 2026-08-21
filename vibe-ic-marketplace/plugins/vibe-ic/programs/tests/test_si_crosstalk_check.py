#!/usr/bin/env python3
"""Tests for si_crosstalk_check.py (G3: Signal Integrity)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "si_crosstalk_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_pass_json_no_violations(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.02, "violations_count": 0})
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True


def test_pass_rpt_format(tmp_path):
    rpt = tmp_path / "reports" / "phase3" / "si_crosstalk.rpt"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text("Crosstalk analysis complete\nNo violations\n")
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_no_report(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_violations_no_waiver(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.15, "violations_count": 3})
    result = _run(tmp_path)
    assert result.returncode == 1


def test_pass_violations_with_waiver(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.15, "violations_count": 3})
    _write_json(tmp_path / "waivers.json",
                {"waivers": [{"step": "si_crosstalk", "reason": "accepted"}]})
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_missing_fields(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json", {"foo": "bar"})
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# D9 — the artefact must be COHERENT WITH ITSELF.
#
# The census scored step 27 EXISTENCE-ONLY: every number in si_crosstalk.json
# could be scaled and sign-flipped and this gate's verdict did not move, because
# it read `violations_count` and asked only whether it was > 0 — so a count of
# -7 sailed through. These are the content mutants for the criterion that fixes
# that. No oracle: each rule is a domain bound true of any circuit, or an
# arithmetic relation the document asserts between its OWN fields.
# ---------------------------------------------------------------------------

_COHERENT = {
    "max_crosstalk_noise": 1777.24, "max_coupling_ratio": 0.9874,
    "mean_coupling_ratio": 0.5225, "nets_analyzed": 1650,
    "nets_elevated_coupling_gt0p5": 962,
    "nets_coupling_dominated_gt0p9": 581, "violations_count": 0,
}


def _rules(tmp_path: Path) -> list:
    # the finding's identity lives in `category`, not `rule` — checked against
    # the emitted document rather than assumed, because a helper that reads a
    # key nobody writes turns every assertion below into a KeyError instead of
    # a verdict
    return [f["category"] for f in
            json.loads((tmp_path / "out.json").read_text())["findings"]]


def test_a_coherent_artefact_still_PASSES(tmp_path):
    """THE INVERSE ARM, first. These are the real published values from
    `benchmark-data/ic/caravel_user_project/v1.9.43_sky130A`; a rule that
    reddened them would be a ban, not a check."""
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json", dict(_COHERENT))
    assert _run(tmp_path).returncode == 0


@pytest.mark.parametrize("field,value,rule", [
    # a ratio is Cc/(Cc+Cg) — a capacitance over a larger capacitance
    ("max_coupling_ratio", 1.7, "SI_RATIO_OUT_OF_DOMAIN"),
    ("mean_coupling_ratio", -0.3, "SI_RATIO_OUT_OF_DOMAIN"),
    # a count of nets
    ("violations_count", -7, "SI_NEGATIVE_COUNT"),
    ("nets_analyzed", -1650, "SI_NEGATIVE_COUNT"),
    # nets above 0.9 are a SUBSET of nets above 0.5
    ("nets_coupling_dominated_gt0p9", 9999, "SI_SUBSET_EXCEEDS_SUPERSET"),
])
def test_one_incoherent_field_reddens_the_gate(tmp_path, field, value, rule):
    """One field at a time, every other value left published-correct.

    Each is a CONTENT mutant: the file exists, parses, keeps every key and every
    type, and only the meaning moves.
    """
    doc = dict(_COHERENT)
    doc[field] = value
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json", doc)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rule in _rules(tmp_path), _rules(tmp_path)


def test_a_mean_above_its_own_max_reddens(tmp_path):
    doc = dict(_COHERENT, mean_coupling_ratio=0.99, max_coupling_ratio=0.40)
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json", doc)
    assert _run(tmp_path).returncode == 1
    assert "SI_MEAN_EXCEEDS_MAX" in _rules(tmp_path)


def test_scaling_EVERY_number_is_caught_on_several_independent_rules(tmp_path):
    """The census's own generic corruption, as a permanent test.

    Each value stays individually plausible in magnitude; only the relations
    between them break. This is the mutation that scored step 27
    EXISTENCE-ONLY before the criterion existed.
    """
    scale = lambda x: -(x * 3 + 7)
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {k: scale(v) for k, v in _COHERENT.items()})
    assert _run(tmp_path).returncode == 1
    fired = set(_rules(tmp_path))
    assert {"SI_RATIO_OUT_OF_DOMAIN", "SI_NEGATIVE_COUNT",
            "SI_MEAN_EXCEEDS_MAX"} <= fired, fired


def test_fields_the_document_does_not_state_are_not_demanded(tmp_path):
    """The rules may only read what the artefact offers.

    Requiring a field an older emitter never wrote would be a new schema
    requirement wearing a coherence check's clothes.
    """
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.02, "violations_count": 0})
    assert _run(tmp_path).returncode == 0
