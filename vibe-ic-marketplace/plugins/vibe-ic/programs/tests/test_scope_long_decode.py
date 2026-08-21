#!/usr/bin/env python3
"""Tests for scope_long_decode.py (LL-9 debug helper)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "scope_long_decode.py"


def _make_l2(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "pulse_classes": [
            {"class_name": "BIT1", "min_us": 0.6, "max_us": 3.6,
             "polarity": "low"},
            {"class_name": "BIT0", "min_us": 3.6, "max_us": 9.4,
             "polarity": "low"},
            {"class_name": "BR",   "min_us": 9.4, "max_us": 18.4,
             "polarity": "low"},
            {"class_name": "WAKE", "min_us": 22.0, "max_us": 28.0,
             "polarity": "low"},
            {"class_name": "BOR",  "min_us": 500.0, "max_us": 999999.0,
             "polarity": "low"},
        ],
    }))


def _make_l3(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "command_table": [
            {"opcode": "0x74", "name": "Get ID",
             "rx_len_bytes": 4, "tx_len_bytes": 8,
             "fields_tx": ["0x75", "ID[0..5]", "CRC2"],
             "rsp_example_hex": "75 10 00 00 00 00 00 47"},
        ],
    }))


def _crc8(data, init=0xFF, poly=0x8C):
    s = init
    for b in data:
        s ^= b
        for _ in range(8):
            s = (s >> 1) ^ poly if (s & 1) else s >> 1
    return s


def _emit_protocol_csv(csv_path: Path, resp_bytes: list[int],
                       leading_wake: bool = False):
    """Generate a CSV with master 0x74 cmd + given chip response."""
    samples = []
    sample_period_us = 0.4

    def el(d, t):
        n = int(d / sample_period_us)
        return [(t + i * sample_period_us, 0.0) for i in range(n)], \
               t + n * sample_period_us

    def eh(d, t):
        n = int(d / sample_period_us)
        return [(t + i * sample_period_us, 3.3) for i in range(n)], \
               t + n * sample_period_us

    def eb(b, t):
        for i in range(8):
            bit = (b >> i) & 1
            if bit:
                out, t = el(1.8, t)
                samples.extend(out)
                out, t = eh(8.2, t)
                samples.extend(out)
            else:
                out, t = el(7.2, t)
                samples.extend(out)
                out, t = eh(2.8, t)
                samples.extend(out)
        out, t = eh(15.0, t)
        samples.extend(out)
        return t

    t = -100.0
    if leading_wake:
        # 24us wake pulse
        out, t = el(24.0, t)
        samples.extend(out)
        out, t = eh(200.0, t)  # gap before protocol
        samples.extend(out)
    out, t = eh(100.0, t)
    samples.extend(out)
    # BR + cmd
    out, t = el(13.8, t)
    samples.extend(out)
    out, t = eh(15.0, t)
    samples.extend(out)
    for b in [0x74, 0x00, 0x01, 0xFD]:
        t = eb(b, t)
    out, t = eh(80.0, t)
    samples.extend(out)
    for b in resp_bytes:
        t = eb(b, t)
    out, t = eh(2000.0, t)
    samples.extend(out)

    with open(csv_path, "w") as f:
        f.write("time_us,voltage\n")
        for tt, v in samples:
            f.write(f"{tt:.3f},{v:.4f}\n")


def _run(project: Path, csv_path: Path, json_out: Path | None = None):
    cmd = [sys.executable, str(PROG), str(project),
           "--scope-csv", str(csv_path)]
    if json_out:
        cmd += ["--json", str(json_out)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_decode_correct_response_passes(tmp_path):
    _make_l2(tmp_path)
    _make_l3(tmp_path)
    correct = [0x75, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
    correct.append(_crc8(correct))
    _emit_protocol_csv(tmp_path / "scope.csv", correct)
    rep_path = tmp_path / "rep.json"
    r = _run(tmp_path, tmp_path / "scope.csv", rep_path)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    rep = json.loads(rep_path.read_text())
    assert rep["pairs_diff"][0]["verdict"] == "OK"
    assert rep["pairs_diff"][0]["resp_crc_ok"] is True


def test_decode_bad_crc_flagged(tmp_path):
    _make_l2(tmp_path)
    _make_l3(tmp_path)
    # Wrong CRC
    bad = [0x75, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF]
    _emit_protocol_csv(tmp_path / "scope.csv", bad)
    rep_path = tmp_path / "rep.json"
    r = _run(tmp_path, tmp_path / "scope.csv", rep_path)
    assert r.returncode == 1, f"expected exit 1; stdout: {r.stdout}"
    rep = json.loads(rep_path.read_text())
    fd = rep["first_divergence"]
    assert fd["verdict"] == "RESP_CRC_MISMATCH"
    assert fd["resp_crc_actual"] == "FF"
    assert fd["resp_crc_expected"] == "47"


def test_decode_wrong_resp_opcode_flagged(tmp_path):
    _make_l2(tmp_path)
    _make_l3(tmp_path)
    # Wrong response opcode (0x76 instead of 0x75)
    bad = [0x76, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
    bad.append(_crc8(bad))
    _emit_protocol_csv(tmp_path / "scope.csv", bad)
    rep_path = tmp_path / "rep.json"
    r = _run(tmp_path, tmp_path / "scope.csv", rep_path)
    assert r.returncode == 1
    rep = json.loads(rep_path.read_text())
    fd = rep["first_divergence"]
    assert fd["verdict"] == "RESP_OPCODE_MISMATCH"
    assert fd["actual"] == "76"
    assert fd["expected"] == "75"
    assert fd["first_divergent_byte"] == 0


def test_wake_pulses_filtered(tmp_path):
    _make_l2(tmp_path)
    _make_l3(tmp_path)
    correct = [0x75, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
    correct.append(_crc8(correct))
    _emit_protocol_csv(tmp_path / "scope.csv", correct,
                       leading_wake=True)
    rep_path = tmp_path / "rep.json"
    r = _run(tmp_path, tmp_path / "scope.csv", rep_path)
    assert r.returncode == 0
    rep = json.loads(rep_path.read_text())
    # 1 wake pulse expected; 0 cmd-response pairs found-but-broken
    assert rep["stats"]["wake_pulses"] >= 1
    assert rep["stats"]["cmd_response_pairs"] == 1
    assert rep["pairs_diff"][0]["verdict"] == "OK"


def test_response_length_mismatch_flagged(tmp_path):
    _make_l2(tmp_path)
    _make_l3(tmp_path)
    # Truncated response (6 bytes instead of 8)
    bad = [0x75, 0x10, 0x00, 0x00, 0x00, 0x47]
    _emit_protocol_csv(tmp_path / "scope.csv", bad)
    rep_path = tmp_path / "rep.json"
    r = _run(tmp_path, tmp_path / "scope.csv", rep_path)
    assert r.returncode == 1
    rep = json.loads(rep_path.read_text())
    fd = rep["first_divergence"]
    assert fd["verdict"] == "RESP_LEN_MISMATCH"
    assert fd["resp_byte_count"] == 6
    assert fd["expected_tx_len"] == 8
