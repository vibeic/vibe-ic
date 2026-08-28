"""Tests for manifest_leak_check.py.

Covers: verbatim benchmark leaks, short-string OK, safe fields, missing file.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "manifest_leak_check.py"
assert SCRIPT.exists()


def _run(*args):
    return _pr.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


def _write(path: Path, facts):
    path.write_text(json.dumps({"facts": facts, "layer": "L1"}))


def test_detects_long_string_leak(tmp_path):
    m = tmp_path / "L1_manifest.json"
    _write(m, [
        {"path": "ic_name",
         "benchmark_value": "IC-A Power Throttling IC with a long name",
         "ic_expert_default": "IC-A Power Throttling IC with a long name"},
    ])
    r = _run(str(m))
    assert r.returncode == 1
    assert "ic_name" in r.stdout + r.stderr


def test_safe_generic_fields_not_flagged(tmp_path):
    m = tmp_path / "L1_manifest.json"
    _write(m, [
        {"path": "document_id",
         "benchmark_value": "L1_DATASHEET",
         "ic_expert_default": "L1_DATASHEET"},
        {"path": "schema_version",
         "benchmark_value": "1.0.0",
         "ic_expert_default": "1.0.0"},
    ])
    r = _run(str(m))
    assert r.returncode == 0


def test_short_generic_values_not_flagged(tmp_path):
    """Strings < 5 chars are too generic to be a benchmark leak (e.g. "5V", "OK")."""
    m = tmp_path / "L1_manifest.json"
    _write(m, [
        {"path": "electrical.vdd_unit",
         "benchmark_value": "V",
         "ic_expert_default": "V"},
        {"path": "electrical.freq_unit",
         "benchmark_value": "MHz",
         "ic_expert_default": "MHz"},
    ])
    r = _run(str(m))
    assert r.returncode == 0


def test_sanitized_default_is_ok(tmp_path):
    """After sanitization: ic_expert_default=None means agent must solicit."""
    m = tmp_path / "L1_manifest.json"
    _write(m, [
        {"path": "ic_name",
         "benchmark_value": "BENCH-A specific benchmark value",
         "ic_expert_default": None,
         "provenance_hint": "user_required"},
    ])
    r = _run(str(m))
    assert r.returncode == 0


def test_directory_mode(tmp_path):
    d = tmp_path / "manifests"
    d.mkdir(parents=True, exist_ok=True)
    _write(d / "L1_manifest.json", [
        {"path": "foo", "benchmark_value": "alpha bravo charlie",
         "ic_expert_default": "alpha bravo charlie"},
    ])
    _write(d / "L2_manifest.json", [
        {"path": "bar", "benchmark_value": "long benchmark value text",
         "ic_expert_default": None},
    ])
    r = _run(str(d))
    assert r.returncode == 1
    # Only L1 leaked
    assert "L1_manifest.json" in r.stdout + r.stderr


def test_missing_path_exits_2(tmp_path):
    r = _run(str(tmp_path / "nope.json"))
    assert r.returncode == 2
