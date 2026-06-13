"""Unit tests for hw_vs_rtl_verdict_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "hw_vs_rtl_verdict_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import hw_vs_rtl_verdict_check as chk  # noqa: E402


def _run(args, **kwargs):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, **kwargs,
    )


def _write_variant(d: Path, name: str, rtl_id: str, hex_bytes: str,
                   fail: bool = True) -> None:
    (d / name).write_text(json.dumps({
        "rtl_id": rtl_id,
        "tester_response_hex": hex_bytes,
        "fail": fail,
    }))


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------
def test_help_works():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "verdict" in r.stdout.lower() or "variants" in r.stdout.lower()


# ---------------------------------------------------------------------------
# PASS: 3 byte-identical variants, all fail=true
# ---------------------------------------------------------------------------
def test_three_identical_fails_pass(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    for i, rid in enumerate(["v_a", "v_b", "v_c"]):
        _write_variant(d, f"variant_{i}.json", rid,
                       "BE AB BA D1 02 00 00 00", fail=True)
    r = _run(["--responses-dir", str(d)])
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["summary"]["pass"] is True
    cats = [f["category"] for f in out["findings"]]
    assert "HARDWARE_BLOCKED_CONFIRMED" in cats


# ---------------------------------------------------------------------------
# FAIL: variants differ -> RTL-blocked
# ---------------------------------------------------------------------------
def test_differing_responses_fail(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    _write_variant(d, "a.json", "v_a", "BE AB BA D1 02 00 00 00")
    _write_variant(d, "b.json", "v_b", "BE AB BA D1 02 00 00 01")  # last byte differs
    _write_variant(d, "c.json", "v_c", "BE AB BA D1 02 00 00 00")
    r = _run(["--responses-dir", str(d)])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    cats = [f["category"] for f in out["findings"]]
    assert "DIFFERING_RESPONSES" in cats


# ---------------------------------------------------------------------------
# FAIL: fewer than --min-variants
# ---------------------------------------------------------------------------
def test_insufficient_variants_fail(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    _write_variant(d, "a.json", "v_a", "BE AB BA D1")
    _write_variant(d, "b.json", "v_b", "BE AB BA D1")
    r = _run(["--responses-dir", str(d)])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    cats = [f["category"] for f in out["findings"]]
    assert "INSUFFICIENT_VARIANTS" in cats


def test_min_variants_override(tmp_path):
    """With --min-variants 2, two identical variants pass."""
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    _write_variant(d, "a.json", "v_a", "BE AB BA D1")
    _write_variant(d, "b.json", "v_b", "BE AB BA D1")
    r = _run(["--responses-dir", str(d), "--min-variants", "2"])
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# --field byte6 narrows comparison
# ---------------------------------------------------------------------------
def test_field_byte_narrows_comparison(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    # Byte 0 differs, byte 6 is the same.
    _write_variant(d, "a.json", "v_a", "FF AB BA D1 02 00 02 99")
    _write_variant(d, "b.json", "v_b", "EE AB BA D1 02 00 02 77")
    _write_variant(d, "c.json", "v_c", "DD AB BA D1 02 00 02 55")
    r_full = _run(["--responses-dir", str(d), "--field", "full"])
    assert r_full.returncode == 1

    r_byte6 = _run(["--responses-dir", str(d), "--field", "byte6"])
    assert r_byte6.returncode == 0, r_byte6.stdout + r_byte6.stderr


# ---------------------------------------------------------------------------
# Invalid variant JSON
# ---------------------------------------------------------------------------
def test_invalid_variant_flagged(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "bad.json").write_text("not json{")
    _write_variant(d, "a.json", "v_a", "BE AB BA")
    _write_variant(d, "b.json", "v_b", "BE AB BA")
    _write_variant(d, "c.json", "v_c", "BE AB BA")
    r = _run(["--responses-dir", str(d)])
    # Invalid variant makes the gate FAIL regardless of the rest
    assert r.returncode == 1
    out = json.loads(r.stdout)
    cats = [f["category"] for f in out["findings"]]
    assert "INVALID_VARIANT" in cats


# ---------------------------------------------------------------------------
# Missing directory -> exit 2
# ---------------------------------------------------------------------------
def test_missing_dir_exits_2(tmp_path):
    r = _run(["--responses-dir", str(tmp_path / "no-such")])
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# fail flag inconsistency
# ---------------------------------------------------------------------------
def test_all_identical_but_some_pass_is_flagged(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    _write_variant(d, "a.json", "v_a", "BE AB BA", fail=True)
    _write_variant(d, "b.json", "v_b", "BE AB BA", fail=False)
    _write_variant(d, "c.json", "v_c", "BE AB BA", fail=True)
    r = _run(["--responses-dir", str(d)])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    cats = [f["category"] for f in out["findings"]]
    assert "NOT_ALL_FAIL" in cats


# ---------------------------------------------------------------------------
# --json report
# ---------------------------------------------------------------------------
def test_json_report_written(tmp_path):
    d = tmp_path / "runs"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        _write_variant(d, f"v{i}.json", f"v{i}", "AA BB CC")
    out_json = tmp_path / "out.json"
    r = _run(["--responses-dir", str(d), "--json", str(out_json)])
    assert r.returncode == 0
    assert out_json.exists()
    data = json.loads(out_json.read_text())
    assert data["program"] == "hw_vs_rtl_verdict_check"
