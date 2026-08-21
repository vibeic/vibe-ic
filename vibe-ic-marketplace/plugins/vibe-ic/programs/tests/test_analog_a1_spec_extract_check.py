"""tests/test_analog_a1_spec_extract_check.py — v1.6.35

Five cases for the A1 deterministic gate:
  1. happy path — spec.json with specs[]                  PASS
  2. flat-dict layout (Vout/gain key)                     PASS
  3. spec.json missing for a block                        VACUOUS_PASS (project) /
                                                           rc=2 WAIVED (--block)
  4. spec.json present but empty {}                       FAIL
  5. multi-block, one block has no spec.json              INCOMPLETE (rc=1)
  6. no analog_block_list.json                            VACUOUS_PASS
  7. spec.json invalid JSON                               FAIL
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from analog_a1_spec_extract_check import main as gate_main

PROG = (Path(__file__).resolve().parent.parent / "analog_a1_spec_extract_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _spec(project: Path, block: str, content: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(content))


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_specs_list(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _spec(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "min": 1.78, "typ": 1.8, "max": 1.82},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_flat_dict_layout(tmp_path: Path) -> None:
    _block_list(tmp_path, ["amp"])
    _spec(tmp_path, "amp",
          {"Vout": 1.8, "gain": 60, "bandwidth": 1e6})
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_block_missing_per_block_mode_waived(tmp_path: Path) -> None:
    """--block <missing_block> → rc=2 WAIVED so runner can defer."""
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "WAIVED"
    assert rpt["suggested_skill"] == "analog-spec-extract"


def test_empty_spec_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _spec(tmp_path, "ldo", {})
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL"
    assert any("A1_SPEC_EMPTY" in f["rule"] for f in rpt["findings"])


def test_multiblock_one_missing_is_incomplete(tmp_path: Path) -> None:
    """Project mode: one block has spec, one doesn't → INCOMPLETE (rc=1).

    CORRECTED TEST. This case used to be named
    `test_multiblock_one_missing_still_passes` and asserted
    `returncode == 0` / `verdict == "PASS"` — it encoded the very defect
    the gate was written to prevent. Its docstring justified the PASS by
    saying "the missing block is deferred via the --block runner path",
    but nothing in project mode defers anything: `flow_compliance_check`
    invokes this gate WITHOUT `--block` and reads only its exit code, so
    the rc=0 certified A1 done while `bandgap` had produced no spec at
    all. The assertion is not relaxed here — it is inverted to the
    behaviour the gate must have.
    """
    _block_list(tmp_path, ["ldo", "bandgap"])
    _spec(tmp_path, "ldo", {"specs": [
        {"name": "vout", "typ": 1.8}]})
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "INCOMPLETE"
    assert rpt["blocks_pass"] == 1
    assert rpt["blocks_missing"] == 1
    assert rpt["incomplete_blocks"] == ["bandgap"]
    # The uncovered block must be NAMED, not merely counted.
    assert "bandgap" in r.stderr


def test_no_block_list_is_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"


def test_invalid_json_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text("{not valid json")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A1_SPEC_INVALID_JSON" in f["rule"]
               for f in rpt["findings"])


def test_per_block_fail_propagates(tmp_path: Path) -> None:
    """--block mode: stub artefact → rc=1 FAIL (not WAIVED)."""
    _block_list(tmp_path, ["ldo"])
    _spec(tmp_path, "ldo", {})
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL"
