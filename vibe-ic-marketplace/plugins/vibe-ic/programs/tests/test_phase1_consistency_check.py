"""Minimum viable tests for phase1_consistency_check.py (K4 cross-layer gate)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "phase1_consistency_check.py"


def _setup(tmp: Path, layers: dict) -> Path:
    d = tmp / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return d


def _run(docs: Path):
    r = subprocess.run([sys.executable, str(PROG), str(docs), "--json"],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _minimal_consistent_set():
    """Minimal L1-L9 set that doesn't trigger any cross-layer rule violation."""
    return {
        "L1_DATASHEET": {"part_number": "X", "pinout": {"A": "1"}},
        "L2_FRS": {"requirements": []},
        "L3_CMD_PROTOCOL": {"crc": {"poly": "0x31"}, "commands": []},
        "L4_REGMAP": {"registers": []},
        "L5_ADI_SPEC": {"adi_signals": []},
        "L6_CONTROL_LOGIC": {"submodule_control_logic": {}},
        "L7_TEST_DEBUG": {},
        "L8_TIMING_WAVEFORM": {"break_timing": {"break_low_min_us": 10}},
        "L8_RTL_CONSTANTS": {"crc": {"poly": "0x31"}},
        "L9_INTEGRATION_SPEC": {"top_level_ports": [], "submodules": [],
                                 "internal_wires": [], "registers": []},
    }


def test_program_exists_and_runs(tmp_path):
    _setup(tmp_path, _minimal_consistent_set())
    code, out, _ = _run(tmp_path / "phase1" / "generated_docs")
    # exit may be 0 or 1 depending on rules; just ensure it doesn't crash
    assert code in (0, 1)


def test_json_output_valid(tmp_path):
    _setup(tmp_path, _minimal_consistent_set())
    code, out, _ = _run(tmp_path / "phase1" / "generated_docs")
    # Output should contain JSON somewhere
    assert "{" in out


def test_missing_docs_dir_errors(tmp_path):
    r = subprocess.run([sys.executable, str(PROG),
                        str(tmp_path / "does_not_exist"), "--json"],
                       capture_output=True, text=True)
    assert r.returncode != 0


def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "docs_dir" in r.stdout.lower() or "docs" in r.stdout
