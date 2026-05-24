"""Tests for layer_extension_presence_check.py (v0.50)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "layer_extension_presence_check.py"


def _setup_docs(tmp: Path, layers: dict):
    d = tmp / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return d


def _run(docs: Path, class_path="cable-side-id-ic"):
    r = subprocess.run(
        [sys.executable, str(PROG), str(docs), "--class-path", class_path],
        capture_output=True, text=True,
    )
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def _full_ok_layers():
    """Layers that meet every floor for cable-side-id-ic.
    Uses generic ids + required CATEGORIES (not vendor-specific names)."""
    return {
        "L10_TEST_CASES": {
            "test_cases": (
                [{"id": f"CMD_{i:02X}", "category": "cmd_response"} for i in range(8)]
                + [{"id": "bad_crc",       "category": "error_path"}]
                + [{"id": "wake_from_por", "category": "state_transition"}]
            )
        },
        "L11_CALIBRATION": {
            "tables": {
                "pulse_decoder_windows":   {"entries": []},
                "response_byte1_sampling": {"entries": []},
            }
        },
        "L12_BEHAVIORAL_SEQUENCES": {
            "sequences": [
                {"id": "rx_validation_chain", "category": "validation_chain"},
                {"id": "test_mode_entry",     "category": "host_stimulus_sequence"},
            ]
        },
    }


def test_all_floors_met_passes(tmp_path):
    docs = _setup_docs(tmp_path, _full_ok_layers())
    code, out = _run(docs)
    assert out.get("pass") is True, out
    assert code == 0


def test_missing_l10_fails(tmp_path):
    layers = _full_ok_layers()
    del layers["L10_TEST_CASES"]
    docs = _setup_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L10_test_cases_min" in rules


def test_cmd_response_count_below_floor_fails(tmp_path):
    layers = _full_ok_layers()
    # Only 1 cmd_response — below the floor of 4
    layers["L10_TEST_CASES"] = {"test_cases":
        [{"id": "only_one", "category": "cmd_response"}]
        + [{"id": f"pad{i}", "category": "error_path"} for i in range(10)]
    }
    docs = _setup_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L10_cmd_response_min" in rules


def test_missing_required_sequence_category_fails(tmp_path):
    layers = _full_ok_layers()
    # Drop the host_stimulus_sequence category — keep only validation_chain
    layers["L12_BEHAVIORAL_SEQUENCES"] = {"sequences": [
        {"id": "rx_validation_chain", "category": "validation_chain"},
        {"id": "another_chain",       "category": "validation_chain"},
    ]}
    docs = _setup_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L12_required_sequence_categories" in rules


def test_empty_l11_fails(tmp_path):
    layers = _full_ok_layers()
    layers["L11_CALIBRATION"] = {"tables": {}}
    docs = _setup_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L11_calibration_tables_min" in rules
