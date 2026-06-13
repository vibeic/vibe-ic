"""Tests for cmd_protocol_crc_verify.py."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "cmd_protocol_crc_verify.py"
assert SCRIPT.exists()


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=30)


def _write(tmp: Path, vectors):
    p = tmp / "vectors.json"
    p.write_text(json.dumps({"width": 8, "vectors": vectors}))
    return p


def test_derives_aid_crc_from_known_vectors(tmp_path):
    """IC-A AID uses poly=0x31, init=0xFF, refin/refout=True.
    Given 4 known (data, crc) pairs, the program must derive these."""
    f = _write(tmp_path, [
        {"data_hex": "72", "crc_hex": "71"},
        {"data_hex": "76", "crc_hex": "10"},
        {"data_hex": "78", "crc_hex": "0F"},
        {"data_hex": "7A", "crc_hex": "B3"},
    ])
    out = tmp_path / "result.json"
    r = _run(str(f), "--json", str(out))
    assert r.returncode == 0
    res = json.loads(out.read_text())
    bm = res["best_match"]
    assert bm["poly"] == "0x31"
    assert bm["init"] == "0xFF"
    assert bm["refin"] is True
    assert bm["refout"] is True


def test_no_match_exits_1(tmp_path):
    """Random vectors that don't fit any standard CRC-8 → fail."""
    f = _write(tmp_path, [
        {"data_hex": "AA BB CC", "crc_hex": "DE"},
        {"data_hex": "11 22 33", "crc_hex": "AD"},
        {"data_hex": "99 88 77", "crc_hex": "BE"},
        {"data_hex": "FE DC BA", "crc_hex": "EF"},
    ])
    r = _run(str(f))
    assert r.returncode == 1


def test_too_few_vectors_exits_1(tmp_path):
    f = _write(tmp_path, [
        {"data_hex": "70", "crc_hex": "3D"},
    ])
    r = _run(str(f), "--min-vectors", "3")
    assert r.returncode == 1


def test_smbus_crc(tmp_path):
    """Known SMBUS vector: CRC-8 of [0xBE, 0xEF] with poly=0x07, init=0x00."""
    # Precompute: crc8-smbus of [0xBE, 0xEF] = ?
    import sys as _s
    _s.path.insert(0, str(Path(__file__).parent.parent))
    from cmd_protocol_crc_verify import crc_compute
    c1 = crc_compute(bytes([0xBE, 0xEF]), 8, 0x07, 0x00, False, False, 0x00)
    c2 = crc_compute(bytes([0x12, 0x34]), 8, 0x07, 0x00, False, False, 0x00)
    c3 = crc_compute(bytes([0xDE, 0xAD]), 8, 0x07, 0x00, False, False, 0x00)
    c4 = crc_compute(bytes([0xFF, 0x00]), 8, 0x07, 0x00, False, False, 0x00)

    f = _write(tmp_path, [
        {"data_hex": "BE EF", "crc_hex": f"{c1:02X}"},
        {"data_hex": "12 34", "crc_hex": f"{c2:02X}"},
        {"data_hex": "DE AD", "crc_hex": f"{c3:02X}"},
        {"data_hex": "FF 00", "crc_hex": f"{c4:02X}"},
    ])
    out = tmp_path / "r.json"
    r = _run(str(f), "--json", str(out))
    assert r.returncode == 0
    res = json.loads(out.read_text())
    bm = res["best_match"]
    assert bm["poly"] == "0x07" and bm["init"] == "0x00"


def test_bad_json_exits_2(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not json")
    r = _run(str(f))
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# v0.56 A4: no-protocol sentinel — gate must SKIP cleanly (exit 0)
# ---------------------------------------------------------------------------
def test_sentinel_skip_returns_0(tmp_path):
    """An L3 doc with `protocol_present: false` is N/A for this gate."""
    f = tmp_path / "L3.json"
    f.write_text(json.dumps({
        "protocol_present": False,
        "reason": "register-pointer access only — analog front-end",
    }))
    r = _run(str(f))
    assert r.returncode == 0
    assert "SKIPPED" in r.stdout


def test_sentinel_writes_skip_report(tmp_path):
    f = tmp_path / "L3.json"
    f.write_text(json.dumps({
        "protocol_present": False, "reason": "EEPROM",
    }))
    out = tmp_path / "report.json"
    r = _run(str(f), "--json", str(out))
    assert r.returncode == 0
    report = json.loads(out.read_text())
    assert report["skipped"] is True
    assert "EEPROM" in report["reason"]
    assert report["best_match"] is None


def test_protocol_present_true_still_requires_vectors(tmp_path):
    """Sentinel only kicks in for protocol_present=false."""
    f = tmp_path / "L3.json"
    f.write_text(json.dumps({"protocol_present": True}))
    r = _run(str(f))
    assert r.returncode == 1
