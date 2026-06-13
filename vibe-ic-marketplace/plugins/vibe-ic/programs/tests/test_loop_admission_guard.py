"""Unit tests for loop_admission_guard.py.

Covers fingerprint stability, duplicate rejection, bounds clamping, per-field
runaway caps, and the iteration budget.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'loop_admission_guard.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import loop_admission_guard as lag  # noqa: E402


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------
def test_fingerprint_key_order_independent():
    a = lag.canonical_fingerprint({"x": 1, "y": 2})
    b = lag.canonical_fingerprint({"y": 2, "x": 1})
    assert a == b


def test_fingerprint_float_noise_collapses():
    a = lag.canonical_fingerprint({"x": 0.1 + 0.2})        # 0.30000000000000004
    b = lag.canonical_fingerprint({"x": 0.3})
    assert a == b


def test_fingerprint_distinguishes_values():
    assert (lag.canonical_fingerprint({"x": 1})
            != lag.canonical_fingerprint({"x": 2}))


# ---------------------------------------------------------------------------
# Duplicate rejection
# ---------------------------------------------------------------------------
def test_duplicate_rejected():
    guard = lag.AdmissionGuard()
    first = guard.admit({"a": 1, "b": 2})
    assert first.admitted is True
    assert first.reason == "ADMITTED"
    second = guard.admit({"b": 2, "a": 1})   # same point, different order
    assert second.admitted is False
    assert second.reason == "DUPLICATE"
    assert guard.admitted_count == 1


def test_rejected_proposal_not_recorded():
    # A capped (rejected) proposal must not pollute the dedup set; a later
    # safe variant of a *different* point should still be admitted.
    guard = lag.AdmissionGuard(caps={"n": 10})
    r1 = guard.admit({"n": 50})
    assert r1.admitted is False and r1.reason == "RUNAWAY_CAP"
    r2 = guard.admit({"n": 5})
    assert r2.admitted is True


# ---------------------------------------------------------------------------
# Bounds clamp
# ---------------------------------------------------------------------------
def test_bounds_clamp_admits_clamped_value():
    guard = lag.AdmissionGuard(bounds={"slack": (-500, 0)})
    res = guard.admit({"slack": 120})
    assert res.admitted is True
    assert res.proposal["slack"] == 0
    assert "slack" in res.clamped_fields


def test_clamp_dedup_on_post_clamp_value():
    # Two raw proposals that clamp to the same safe value should dedup.
    guard = lag.AdmissionGuard(bounds={"slack": (-500, 0)})
    a = guard.admit({"slack": 50})    # -> 0
    b = guard.admit({"slack": 999})   # -> 0, duplicate of a
    assert a.admitted is True
    assert b.admitted is False and b.reason == "DUPLICATE"


def test_bool_not_treated_as_numeric_for_clamp():
    guard = lag.AdmissionGuard(bounds={"flag": (0, 0)})
    res = guard.admit({"flag": True})
    assert res.admitted is True
    assert res.proposal["flag"] is True
    assert "flag" not in res.clamped_fields


# ---------------------------------------------------------------------------
# Runaway protection
# ---------------------------------------------------------------------------
def test_cap_rejects_above_ceiling():
    guard = lag.AdmissionGuard(caps={"duration_ns": 1000})
    assert guard.admit({"duration_ns": 1001}).reason == "RUNAWAY_CAP"
    assert guard.admit({"duration_ns": 1000}).admitted is True   # at ceiling ok


def test_iteration_budget():
    guard = lag.AdmissionGuard(max_iterations=2)
    assert guard.admit({"i": 1}).admitted is True
    assert guard.admit({"i": 2}).admitted is True
    third = guard.admit({"i": 3})
    assert third.admitted is False
    assert third.reason == "RUNAWAY_ITERATION_BUDGET"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_admits(tmp_path, capsys):
    spec = {
        "bounds": {"slack": [-500, 0]},
        "caps": {"buf": 64},
        "max_iterations": 10,
        "history": [{"slack": -120, "buf": 8}],
        "proposal": {"slack": -200, "buf": 4},
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    rc = lag.main([str(spec_file)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["admitted"] is True
    assert out["admitted_count"] == 2   # 1 from history + this one


def test_cli_rejects_duplicate_of_history(tmp_path, capsys):
    spec = {
        "history": [{"slack": -120}],
        "proposal": {"slack": -120},
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    rc = lag.main([str(spec_file)])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "DUPLICATE"
