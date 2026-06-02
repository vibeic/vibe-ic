#!/usr/bin/env python3
"""Tests for sizing_history_emit.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "sizing_history_emit.py"


def _run(*args):
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True)


_VALID_FINAL = {
    "block_name": "ldo_1v8", "iterations": 2, "converged": True,
    "final_sizing": {"M1": {"W": "40u", "L": "2u", "role": "input_pair"}},
    "worst_corner": "ss_-40C_3.0V", "yield_pct": 100,
}
_VALID_HISTORY = {"iterations": [
    {"iter": 0, "changes": "initial", "tt_pass": False},
    {"iter": 1, "changes": "M1 W 20u->40u", "tt_pass": True,
     "all_corners_pass": True},
]}


# -- PASS: a fully valid sizing_final.json --
def test_validate_final_pass(tmp_path):
    f = tmp_path / "final.json"
    f.write_text(json.dumps(_VALID_FINAL))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--json", str(out))
    assert r.returncode == 0
    assert json.loads(out.read_text())["passed"] is True


# -- FAIL: missing required field --
def test_validate_final_missing_field(tmp_path):
    bad = dict(_VALID_FINAL)
    del bad["worst_corner"]
    f = tmp_path / "final.json"
    f.write_text(json.dumps(bad))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert any(v["rule"] == "MISSING_FIELD" and v["field"] == "worst_corner"
               for v in rep["violations"])


# -- FAIL: bad type (iterations as string) --
def test_validate_final_bad_type(tmp_path):
    bad = dict(_VALID_FINAL)
    bad["iterations"] = "two"
    f = tmp_path / "final.json"
    f.write_text(json.dumps(bad))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--json", str(out))
    assert r.returncode == 1
    assert any(v["rule"] == "BAD_TYPE"
               for v in json.loads(out.read_text())["violations"])


# -- FAIL: device missing W/L --
def test_validate_final_device_missing_dim(tmp_path):
    bad = json.loads(json.dumps(_VALID_FINAL))
    bad["final_sizing"]["M1"] = {"role": "input_pair"}  # no W/L
    f = tmp_path / "final.json"
    f.write_text(json.dumps(bad))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--json", str(out))
    assert r.returncode == 1
    assert any(v["rule"] == "DEVICE_MISSING_DIM"
               for v in json.loads(out.read_text())["violations"])


# -- cross-field PASS: final+history consistent --
def test_cross_field_pass(tmp_path):
    f = tmp_path / "final.json"
    h = tmp_path / "hist.json"
    f.write_text(json.dumps(_VALID_FINAL))
    h.write_text(json.dumps(_VALID_HISTORY))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--history", str(h), "--json", str(out))
    assert r.returncode == 0
    assert json.loads(out.read_text())["passed"] is True


# -- cross-field FAIL: iteration count mismatch --
def test_cross_field_count_mismatch(tmp_path):
    bad = dict(_VALID_FINAL)
    bad["iterations"] = 5  # but history has 2
    f = tmp_path / "final.json"
    h = tmp_path / "hist.json"
    f.write_text(json.dumps(bad))
    h.write_text(json.dumps(_VALID_HISTORY))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--history", str(h), "--json", str(out))
    assert r.returncode == 1
    assert any(v["rule"] == "ITERATION_COUNT_MISMATCH"
               for v in json.loads(out.read_text())["violations"])


# -- cross-field FAIL: converged=true but no terminal all_corners_pass --
def test_cross_field_unsupported_convergence(tmp_path):
    h = json.loads(json.dumps(_VALID_HISTORY))
    h["iterations"][-1].pop("all_corners_pass")
    f = tmp_path / "final.json"
    hp = tmp_path / "hist.json"
    f.write_text(json.dumps(_VALID_FINAL))
    hp.write_text(json.dumps(h))
    out = tmp_path / "o.json"
    r = _run("validate-final", str(f), "--history", str(hp), "--json", str(out))
    assert r.returncode == 1
    assert any(v["rule"] == "UNSUPPORTED_CONVERGENCE"
               for v in json.loads(out.read_text())["violations"])


# -- validate-history FAIL: record missing 'changes' --
def test_validate_history_missing_changes(tmp_path):
    h = tmp_path / "hist.json"
    h.write_text(json.dumps({"iterations": [{"iter": 0}]}))
    out = tmp_path / "o.json"
    r = _run("validate-history", str(h), "--json", str(out))
    assert r.returncode == 1
    assert any(v["field"].endswith(".changes")
               for v in json.loads(out.read_text())["violations"])


# -- emit-final: valid input is written out --
def test_emit_final(tmp_path):
    src = tmp_path / "src.json"
    src.write_text(json.dumps(_VALID_FINAL))
    dst = tmp_path / "sizing_final.json"
    r = _run("emit-final", str(src), "--out", str(dst))
    assert r.returncode == 0
    assert dst.is_file()
    assert json.loads(dst.read_text())["block_name"] == "ldo_1v8"


# -- emit-final refuses to emit an invalid artefact --
def test_emit_final_refuses_invalid(tmp_path):
    bad = dict(_VALID_FINAL)
    del bad["block_name"]
    src = tmp_path / "src.json"
    src.write_text(json.dumps(bad))
    dst = tmp_path / "sizing_final.json"
    r = _run("emit-final", str(src), "--out", str(dst))
    assert r.returncode == 1
    assert not dst.exists()


# -- missing input file → exit 2 --
def test_missing_file():
    r = _run("validate-final", "/nonexistent/final.json")
    assert r.returncode == 2


# v0.2.25 — D3 re-audit residual: the "<=2 simultaneous changes per iteration"
# discipline is now a structural check on changed_params.
def test_history_more_than_two_changed_params_fails():
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "sizing_history_emit",
        str(Path(__file__).resolve().parent.parent / "sizing_history_emit.py"))
    _m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_m)
    # 3 changed params in one iteration -> violation
    bad = {"iterations": [
        {"iter": 0, "changes": "init", "changed_params": []},
        {"iter": 1, "changes": "tune", "changed_params": ["W_M1", "L_M2", "Cc"]},
    ]}
    vios = _m.validate_history(bad)
    assert any(v["rule"] == "TOO_MANY_SIMULTANEOUS_CHANGES" for v in vios), vios
    # exactly 2 changed params -> OK (no such violation)
    ok = {"iterations": [
        {"iter": 0, "changes": "init", "changed_params": []},
        {"iter": 1, "changes": "tune", "changed_params": ["W_M1", "L_M2"]},
    ]}
    assert not any(v["rule"] == "TOO_MANY_SIMULTANEOUS_CHANGES"
                   for v in _m.validate_history(ok))
    # legacy record with only the free-text `changes` string (no changed_params)
    # is NOT flagged (no schema regression).
    legacy = {"iterations": [{"iter": 0, "changes": "W up, L down, Cc up"}]}
    assert not any(v["rule"] == "TOO_MANY_SIMULTANEOUS_CHANGES"
                   for v in _m.validate_history(legacy))
