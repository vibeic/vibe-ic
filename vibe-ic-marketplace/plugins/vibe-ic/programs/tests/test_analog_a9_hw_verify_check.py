"""tests/test_analog_a9_hw_verify_check.py — A9 (renumbered from A8)"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a9_hw_verify_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _hwmeas(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "hw_measurements.json").write_text(json.dumps(doc))


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_measurements_dict(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hwmeas(tmp_path, "ldo", {
        "instrument": "Rigol DS1054Z",
        "measurements": {"vout": 1.78, "iq_ua": 12.4},
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_happy_path_raw_list(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hwmeas(tmp_path, "ldo", {
        "scope_capture": "scope.csv",
        "raw_list_for_humans": [
            {"spec": "vout", "hw_value": 1.78},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-hw-measure"


def test_no_evidence_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hwmeas(tmp_path, "ldo", {"unrelated_field": True})
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A9_HW_MEAS_NO_EVIDENCE" in f["rule"]
               for f in rpt["findings"])


def test_no_numerics_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hwmeas(tmp_path, "ldo", {
        "instrument": "scope",
        "measurements": {"vout": "TBD"},  # not numeric
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A9_HW_MEAS_NO_NUMERICS" in f["rule"]
               for f in rpt["findings"])


def test_invalid_json_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hw_measurements.json").write_text("{invalid")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A9_HW_MEAS_INVALID_JSON" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
