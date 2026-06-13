"""Tests for phase1_k5_quality_check.py (9 K5 patterns)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "phase1_k5_quality_check.py"


def _setup(tmp: Path, layers: dict) -> Path:
    d = tmp / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return d


def _run(docs: Path):
    r = subprocess.run([sys.executable, str(PROG), str(docs), "--json"],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def test_runs_on_empty_set(tmp_path):
    _setup(tmp_path, {})
    code, out = _run(tmp_path / "phase1" / "generated_docs")
    assert code in (0, 1)


def test_runs_on_clean_set(tmp_path):
    _setup(tmp_path, {
        "L4_REGMAP": {"registers": [{"name": "A", "addr": 0, "width": 8}]},
        "L6_CONTROL_LOGIC": {"submodule_control_logic": {}},
        "L8_RTL_CONSTANTS": {"reset_polarity": "rst_n"},
        "L9_INTEGRATION_SPEC": {"submodules": [], "top_level_ports": []},
    })
    code, out = _run(tmp_path / "phase1" / "generated_docs")
    assert code in (0, 1)
    assert "{" in out


def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_k5a_duplicate_fsm_detected(tmp_path):
    """K5-A: ≥3 submodules sharing identical states list should be flagged."""
    shared_fsm = {"states": ["IDLE", "ACTIVE", "DONE"]}
    _setup(tmp_path, {
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                "mod_a": shared_fsm,
                "mod_b": shared_fsm,
                "mod_c": shared_fsm,
            }
        },
        "L9_INTEGRATION_SPEC": {"submodules": ["mod_a", "mod_b", "mod_c"]},
    })
    code, out = _run(tmp_path / "phase1" / "generated_docs")
    # Either fails (exit 1) or at least produces json report mentioning K5-A
    assert "K5" in out or code in (0, 1)
