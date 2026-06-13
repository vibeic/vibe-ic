#!/usr/bin/env python3
"""Tests for crc_parameters_extracted_check.py (LL-34)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "crc_parameters_extracted_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _put_extracted(tmp_path: Path, name: str, body: str,
                   subdir: str = "phase1/input_doc"):
    base = tmp_path / subdir
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(body, encoding="utf-8")


def _put_l3(tmp_path: Path, data: dict,
            name: str = "L3_CMD_PROTOCOL.json",
            subdir: str = "phase1/generated_docs"):
    base = tmp_path / subdir
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(json.dumps(data, ensure_ascii=False),
                             encoding="utf-8")


CRC_DOC_BODY = """
Some preamble.

7. CRC checking
The chip uses a CRC-8 polynomial function of (X^8 + X^5 + X^4 + 1).
The protocol is LSB-first, so CRC bits push from LSB to MSB.

   if (carry) crc = crc ^ 0x8C;

The CRC seed is initialised to 0xFF on every break and is computed
over the entire command or response packet.

Table 14 — vectors:
    0x00 -> 0x35
    0xAA -> 0xE4
"""


# ---------- 1. baseline silent-skip ---------------------------------
def test_baseline_no_docs_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 2. doc with CRC signals + L3 has block → PASS -----------
def test_crc_signals_l3_has_params_pass(tmp_path):
    _put_extracted(tmp_path, "MDV-A1101-FRS.txt", CRC_DOC_BODY)
    _put_l3(tmp_path, {
        "document_type": "L3_CMD_PROTOCOL",
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "polynomial_reflected_hex": "0x8C",
            "init_hex": "0xFF",
            "bit_order": "lsb_first",
            "xorout_hex": "0x00",
            "vendor_evidence_path":
                "MDV-A1101-FRS §7 lines 1721-1766",
            "source": "VENDOR_DOC_EXTRACTED",
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "WAIVER" not in r.stdout


# ---------- 3. doc with CRC signals + L3 missing block → FAIL -------
def test_crc_signals_no_l3_block_fails(tmp_path):
    _put_extracted(tmp_path, "vendor.txt", CRC_DOC_BODY)
    _put_l3(tmp_path, {
        "document_type": "L3_CMD_PROTOCOL",
        "commands": [{"opcode": "0x70"}],
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    # missing sub-keys reported
    assert "crc_parameters" in r.stdout or "missing" in r.stdout.lower()


# ---------- 4. BRUTE_FORCED without evidence → FAIL -----------------
def test_brute_forced_no_evidence_fails(tmp_path):
    _put_extracted(tmp_path, "vendor.txt", CRC_DOC_BODY)
    _put_l3(tmp_path, {
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "init_hex": "0xFF",
            "bit_order": "lsb_first",
            "source": "BRUTE_FORCED_FROM_VECTORS",
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "BRUTE_FORCED" in r.stdout or "vendor_evidence_path" in r.stdout


# ---------- 5. doc without CRC signals → silent-skip ----------------
def test_lin_only_doc_silent_pass(tmp_path):
    body = ("LIN bus protocol, no CRC at all. Standard arbitration "
            "field, sync byte 0x55, response by ID. No polynomial "
            "section.\n")
    _put_extracted(tmp_path, "lin_spec.txt", body)
    _put_l3(tmp_path, {
        "commands": [{"opcode": "0x01"}],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 6. waiver ≥40 chars accepted ----------------------------
def test_waiver_accepted(tmp_path):
    _put_extracted(tmp_path, "vendor.txt", CRC_DOC_BODY)
    _put_l3(tmp_path, {})  # no crc_parameters
    (tmp_path / "waivers.json").write_text(json.dumps({
        "crc_parameters_brute_forced_intentional":
            "Vendor §7 block ambiguous; reverse-engineered from "
            "Table 14 vectors, verified on first silicon scope diff.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


# ---------- 7. waiver too short → still FAIL ------------------------
def test_short_waiver_still_fails(tmp_path):
    _put_extracted(tmp_path, "vendor.txt", CRC_DOC_BODY)
    _put_l3(tmp_path, {})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "crc_parameters_brute_forced_intentional": "too short",
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


# ---------- 8. accepts older `crc` shape with poly/init/refin ------
def test_old_crc_shape_accepted(tmp_path):
    _put_extracted(tmp_path, "vendor.txt", CRC_DOC_BODY)
    _put_l3(tmp_path, {
        "crc": {
            "algorithm": "CRC-8",
            "poly": "0x31",
            "init": "0xFF",
            "refin": True,
            "refout": True,
            "xorout": "0x00",
            "decision_source": "MDV-A1101-FRS §7 lines 1721-1766",
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 9. extracted text in input/docs/ instead of extracted_docs/
def test_input_docs_subdir_also_scanned(tmp_path):
    _put_extracted(tmp_path, "vendor.txt", CRC_DOC_BODY,
                   subdir="input/docs")
    _put_l3(tmp_path, {})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
