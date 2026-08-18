"""Unit tests for gate_reliability_register.py.

Covers EMA updates, false-PASS bookkeeping, confidence, spot-check priority
ranking, and JSON ledger round-trip.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'gate_reliability_register.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import gate_reliability_register as grr  # noqa: E402


# ---------------------------------------------------------------------------
# EMA updates
# ---------------------------------------------------------------------------
def test_first_sample_seeds_ema(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json", alpha=0.3)
    rec = reg.record("g", passed=True)
    assert rec.samples == 1
    assert rec.ema_pass == 1.0
    assert rec.ema_false_pass == 0.0


def test_ema_moves_toward_new_values(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json", alpha=0.5)
    reg.record("g", passed=True)        # ema_pass = 1.0
    rec = reg.record("g", passed=False)  # 0.5*0 + 0.5*1.0 = 0.5
    assert rec.ema_pass == pytest.approx(0.5)
    assert rec.samples == 2


def test_false_pass_requires_pass(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json")
    with pytest.raises(ValueError):
        reg.record("g", passed=False, false_pass=True)


def test_alpha_validation(tmp_path):
    with pytest.raises(ValueError):
        grr.ReliabilityRegister(tmp_path / "x.json", alpha=0.0)
    with pytest.raises(ValueError):
        grr.ReliabilityRegister(tmp_path / "x.json", alpha=1.5)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------
def test_confidence_high_when_clean(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json", alpha=0.5)
    for _ in range(5):
        reg.record("clean", passed=True)
    assert reg.confidence("clean") == pytest.approx(1.0)


def test_confidence_drops_with_false_pass(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json", alpha=0.5)
    reg.record("liar", passed=True)
    reg.record("liar", passed=True, false_pass=True)
    assert reg.confidence("liar") < 1.0
    assert reg.confidence("unseen") == 0.0


# ---------------------------------------------------------------------------
# Spot-check priority
# ---------------------------------------------------------------------------
def test_unseen_gate_highest_priority(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json")
    assert reg.spotcheck_priority("never") == 1.0


def test_false_pass_gate_ranks_above_clean(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json", alpha=0.5)
    for _ in range(6):
        reg.record("clean", passed=True)
    for _ in range(3):
        reg.record("liar", passed=True, false_pass=True)
    ranked = dict(reg.ranked_for_spotcheck())
    order = [g for g, _ in reg.ranked_for_spotcheck()]
    assert order.index("liar") < order.index("clean")
    assert ranked["liar"] > ranked["clean"]


def test_ranked_top(tmp_path):
    reg = grr.ReliabilityRegister(tmp_path / "led.json")
    for g in ("a", "b", "c"):
        reg.record(g, passed=True)
    assert len(reg.ranked_for_spotcheck()) == 3


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_empty_ledger_file_starts_fresh(tmp_path):
    # A freshly `touch`ed (empty) ledger must not crash on load.
    path = tmp_path / "led.json"
    path.write_text("")
    reg = grr.ReliabilityRegister(path)
    assert reg.records == {}
    reg.record("g", passed=True)
    reg.save()
    assert grr.ReliabilityRegister(path).records["g"].samples == 1


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "led.json"
    reg = grr.ReliabilityRegister(path, alpha=0.4)
    reg.record("g1", passed=True)
    reg.record("g1", passed=True, false_pass=True)
    reg.record("g2", passed=False)
    reg.save()

    reg2 = grr.ReliabilityRegister(path)
    assert reg2.alpha == 0.4
    assert reg2.records["g1"].samples == 2
    assert reg2.confidence("g1") == pytest.approx(reg.confidence("g1"))
    assert reg2.records["g2"].ema_pass == 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_record_and_rank(tmp_path, capsys):
    led = tmp_path / "led.json"
    assert grr.main(["record", str(led), "--gate", "drc", "--pass"]) == 0
    capsys.readouterr()
    assert grr.main(["record", str(led), "--gate", "lec", "--pass", "--false-pass"]) == 0
    capsys.readouterr()
    assert grr.main(["rank", str(led), "--top", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["gate"] == "lec"     # the false-passing gate is top priority


def test_cli_record_false_pass_on_fail_errors(tmp_path, capsys):
    led = tmp_path / "led.json"
    rc = grr.main(["record", str(led), "--gate", "g", "--fail", "--false-pass"])
    assert rc == 1
