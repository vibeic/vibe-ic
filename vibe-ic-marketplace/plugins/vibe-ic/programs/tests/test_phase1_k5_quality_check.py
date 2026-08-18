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
    # ORGANIC #491: was `assert code in (0, 1)`, which passes on every
    # possible outcome. An empty document set examined nothing -> rc 2.
    _setup(tmp_path, {})
    code, out = _run(tmp_path / "phase1" / "generated_docs")
    assert code == 2, out


def test_runs_on_clean_set(tmp_path):
    # ORGANIC #491: this fixture examines nothing (empty submodules, empty
    # ports, empty submodule_control_logic, and L8_RTL_CONSTANTS is not a
    # filename this gate loads — it reads L8_TIMING_WAVEFORM.json). It is a
    # "nothing to check" set, and must now say so rather than reporting a
    # clean bill of health.
    _setup(tmp_path, {
        "L4_REGMAP": {"registers": [{"name": "A", "addr": 0, "width": 8}]},
        "L6_CONTROL_LOGIC": {"submodule_control_logic": {}},
        "L8_RTL_CONSTANTS": {"reset_polarity": "rst_n"},
        "L9_INTEGRATION_SPEC": {"submodules": [], "top_level_ports": []},
    })
    code, out = _run(tmp_path / "phase1" / "generated_docs")
    assert code == 2, out
    payload = json.loads(out)
    assert payload["census"]["examined_total"] == 0


def test_clean_set_with_real_ports_is_checked_not_skipped(tmp_path):
    """The counterpart: a document set that DOES carry data must return
    rc 0 and disclose a non-zero denominator."""
    _setup(tmp_path, {
        "L1_DATASHEET": {"class_path": "digital_arithmetic_primitive"},
        "L9_INTEGRATION_SPEC": {"top_ports": [
            {"name": "clk", "direction": "input", "width": 1}]},
    })
    code, out = _run(tmp_path / "phase1" / "generated_docs")
    assert code == 0, out
    payload = json.loads(out)
    assert payload["census"]["examined_total"] >= 1


def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_k5a_duplicate_fsm_detected(tmp_path):
    """K5-A: ≥3 submodules sharing identical states list should be flagged.

    ORGANIC #491: the assertion was `"K5" in out or code in (0, 1)` — a
    tautology that held whatever the program did. It now asserts the finding
    is actually produced, with its denominator."""
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
    assert code == 0, out
    payload = json.loads(out)
    assert [f["id"] for f in payload["findings"] if f["id"] == "K5-A"] == ["K5-A"]
    k5a = next(c for c in payload["census"]["checks"] if c["check_id"] == "K5-A")
    assert k5a["applicable"] and k5a["examined"] == 3
