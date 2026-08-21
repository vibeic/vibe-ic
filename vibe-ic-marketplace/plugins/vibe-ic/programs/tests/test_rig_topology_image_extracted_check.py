#!/usr/bin/env python3
"""Tests for rig_topology_image_extracted_check.py (LL-35)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "rig_topology_image_extracted_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _put_image(tmp_path: Path, name: str,
               subdir: str = "input/docs"):
    base = tmp_path / subdir
    base.mkdir(parents=True, exist_ok=True)
    # 1-byte placeholder is fine — gate looks at the filename only,
    # vision is the SKILL's responsibility.
    (base / name).write_bytes(b"\x00")


def _put_rig(tmp_path: Path, data: dict,
             subdir: str = ""):
    base = tmp_path / subdir if subdir else tmp_path
    base.mkdir(parents=True, exist_ok=True)
    (base / "rig_topology.json").write_text(json.dumps(data),
                                            encoding="utf-8")


VALID_RIG = {
    "fpga_board": "Terasic DE10-Lite",
    "host_tester": "Generic-EXAMPLE_TESTER",
    "extracted_from": "A3606_pin_planner.jpg",
    "wiring": [
        {"chip_signal": "ID_BUS",  "fpga_pin": "PIN_V10",
         "direction": "Bidir"},
        {"chip_signal": "RESET_N", "fpga_pin": "PIN_B8",
         "direction": "Input"},
    ],
}


# ---------- 1. baseline silent-skip --------------------------------
def test_baseline_no_images_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 2. image present + valid rig json → PASS ---------------
def test_image_and_rig_valid_pass(tmp_path):
    _put_image(tmp_path, "A3606_pin_planner.jpg")
    _put_rig(tmp_path, VALID_RIG)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "WAIVER" not in r.stdout


# ---------- 3. image present + no rig json → FAIL -----------------
def test_image_no_rig_fails(tmp_path):
    _put_image(tmp_path, "board_layout.png")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "rig_topology.json" in r.stdout


# ---------- 4. image + rig missing required key → FAIL -----------
def test_image_rig_missing_key_fails(tmp_path):
    _put_image(tmp_path, "topology.jpeg")
    bad = dict(VALID_RIG)
    bad.pop("host_tester")
    _put_rig(tmp_path, bad)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "host_tester" in r.stdout


# ---------- 5. image + waiver → PASS_WITH_WAIVER -----------------
def test_image_waiver_accepted(tmp_path):
    _put_image(tmp_path, "pin_planner.bmp")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rig_topology_image_inaccessible":
            "Pin planner image is hand-drawn whiteboard photo, not "
            "OCR-friendly; pins documented inline in QSF.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


# ---------- 6. waiver too short (<40 chars) → still FAIL ----------
def test_short_waiver_still_fails(tmp_path):
    _put_image(tmp_path, "pin_planner.bmp")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rig_topology_image_inaccessible": "too short",
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


# ---------- 7. wiring entry missing required field → FAIL --------
def test_wiring_entry_missing_field_fails(tmp_path):
    _put_image(tmp_path, "pinmap.jpg")
    bad = dict(VALID_RIG)
    bad["wiring"] = [
        {"chip_signal": "ID_BUS", "fpga_pin": "PIN_V10"},  # no direction
    ]
    _put_rig(tmp_path, bad)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "direction" in r.stdout


# ---------- 8. rig file in generated_docs/ subdir also accepted --
def test_rig_in_generated_docs_accepted(tmp_path):
    _put_image(tmp_path, "pinmap.jpg")
    _put_rig(tmp_path, VALID_RIG, subdir="phase1/generated_docs")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 9. unrelated image (no name hint) → silent-skip -----
def test_unrelated_image_silent_pass(tmp_path):
    _put_image(tmp_path, "logo.png")  # no pin/board/topology/planner
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "WAIVER" not in r.stdout
