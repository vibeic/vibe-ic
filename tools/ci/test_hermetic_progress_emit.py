from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "hermetic_progress_emit", HERE / "hermetic_progress_emit.py")
assert SPEC and SPEC.loader
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def _env(monkeypatch, tmp_path, units=("one", "two")):
    plan = tmp_path / "progress-plan.json"
    nonce = "a" * 64
    scope = "landing"
    plan.write_text(json.dumps({
        "nonce": nonce, "protocol": "VIBEIC_PROGRESS/1", "schema": 1,
        "scope": scope, "units": list(units),
    }, sort_keys=True, separators=(",", ":")) + "\n")
    plan_raw = plan.read_bytes()
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_NONCE", nonce)
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_SCOPE", scope)
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_PATH",
                       "/input/progress-plan.json")
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_PREFIX", "VIBEIC_PROGRESS ")
    monkeypatch.setattr(E.Path, "read_bytes", lambda _self: plan_raw)
    return nonce


def test_exact_start_checkpoints_and_terminal(monkeypatch, tmp_path):
    nonce = _env(monkeypatch, tmp_path)
    rows = []
    for state, unit in (("start", None), ("checkpoint", "one"),
                        ("checkpoint", "two"), ("terminal", None)):
        raw = E.record(state, unit)
        assert raw.startswith(b"VIBEIC_PROGRESS ")
        rows.append(json.loads(raw[len(b"VIBEIC_PROGRESS "):]))
    assert [row["seq"] for row in rows] == [0, 1, 2, 3]
    assert rows[0] == {
        "nonce": nonce, "schema": 1, "scope": "landing", "seq": 0,
        "state": "start", "total": 2,
    }
    assert rows[-1]["state"] == "terminal"
    assert rows[-1]["completed"] == 2


def test_unknown_duplicate_and_nonfinite_plans_refuse(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    with pytest.raises(E.Refusal, match="not in"):
        E.record("checkpoint", "forged")
    for raw in (
        b'{"nonce":"x","nonce":"y"}\n',
        b'{"nonce":NaN}\n',
    ):
        monkeypatch.setattr(E.Path, "read_bytes", lambda _self, raw=raw: raw)
        with pytest.raises(E.Refusal, match="cannot read"):
            E.record("start")
