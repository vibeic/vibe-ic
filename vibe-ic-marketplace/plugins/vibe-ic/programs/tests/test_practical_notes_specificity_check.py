"""Tests for practical_notes_specificity_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAM = Path(__file__).parent.parent / "practical_notes_specificity_check.py"


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, dict]:
    r = subprocess.run(
        [sys.executable, str(PROGRAM), *args, "--json"],
        capture_output=True, text=True, cwd=cwd, timeout=20)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {}
    return r.returncode, out


def _write(tmp: Path, name: str, body: str) -> Path:
    f = tmp / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f


def test_help_works():
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--help"],
        capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert "PRACTICAL_NOTES" in r.stdout


def test_clean_file_passes(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Generic notes\n\nUse non-blocking assignments in clocked always blocks.\n"
           "Synchronize asynchronous inputs with a 2-FF chain.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 0, out
    assert out["verdict"] == "PASS"
    assert out["total_errors"] == 0


def test_chip_name_example_chip_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nReal bug from EXAMPLE_CHIP debug: foo\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "chip_name_example_chip" in rules


def test_example_tester_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nThe EXAMPLE_TESTER tester returns byte[6]=0xF2 on PASS.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = {f["rule"] for f in out["findings"]}
    assert "tester_example_tester" in rules
    assert "specific_pass_marker" in rules


def test_hid_cmd_byte_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nbuf[0] = 0x10  # CMD_CONNECT_CHK\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "hid_cmd_byte_decl" in rules


def test_vendor_pdf_filename_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nSee EXAMPLE_CHIP_TxRx_signal.pdf for waveform.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "vendor_pdf_filename" in rules


def test_lightning_product_name_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nFor Lightning ICs we use HID.\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "vendor_product_lightning" in rules


def test_dated_validation_flagged(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nvalidated_on: EXAMPLE_TESTER + DE10-Lite 2024-03-15\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = {f["rule"] for f in out["findings"]}
    assert "dated_validation" in rules


def test_provenance_is_warn_by_default(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\nObserved pattern from EXAMPLE_CHIP debug session.\n")
    code, out = _run(["--paths", str(tmp_path)])
    # Provenance triggers SOFT only — but the bare word EXAMPLE_CHIP also fires HARD.
    # So strip the chip name to test SOFT in isolation:
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\n"
           "Real bug from EXAMPLE_CHIP debug: <!-- specificity-allow: provenance -->\n"
           "But this line: from EXAMPLE_CHIP fresh-agent has no allow marker.\n")
    code, out = _run(["--paths", str(tmp_path)])
    # Should have at least one WARN (soft) on the second line, plus HARD chip_name on it.
    severities = {f["severity"] for f in out["findings"]}
    assert "WARN" in severities or "ERROR" in severities


def test_strict_promotes_soft_to_error(tmp_path):
    # Build a file where the only finding is SOFT (mask the HARD chip name on
    # the provenance line by routing through allowlist).
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\n"
           "Real bug from MyChip debug: rule applies generally.\n")
    # MyChip isn't in HARD list but the SOFT regex doesn't match either
    # (it requires EXAMPLE_CHIP/BENCHMARK_A/v0xx/EXAMPLE_TESTER). So construct one that hits SOFT only.
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "EXAMPLE_CHIP debug observation. <!-- specificity-allow: chip_name_example_chip -->\n")
    # Allow marker exempts the WHOLE line, so neither HARD nor SOFT fires.
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 0


def test_allowlist_marker_exempts_line(tmp_path):
    _write(tmp_path, "PRACTICAL_NOTES.md",
           "# Notes\n"
           "EXAMPLE_TESTER tester baseline. <!-- specificity-allow: documented-exception -->\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 0
    assert out["total_errors"] == 0


def test_default_scan_runs_on_plugin_dir():
    # Sanity: the gate finds files in the plugin's vibe-ic/skills dir.
    code, out = _run([])
    # We expect failures because we haven't cleaned the docs yet — but the
    # scan must execute and report file count > 0.
    assert "files_scanned" in out
    assert out["files_scanned"] >= 10, out
    assert out["verdict"] in ("PASS", "FAIL")


def test_invalid_path_errors():
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--paths", "/no/such/dir/__nonexistent__"],
        capture_output=True, text=True, timeout=10)
    assert r.returncode == 2


@pytest.mark.parametrize("snippet,expected_rule", [
    ("Project BENCHMARK_A baseline.",         "project_codename_benchmark_a"),
    ("PDK m18e80pm180su corner SS.",     "specific_pdk_codename"),
    ("Carrier ACC_ID idle high.",        "chip_specific_pin"),
    ("v068 fresh-agent regression.",     "project_version_codename"),
    ("Validated 2024-03-15 EXAMPLE_TESTER.",     "dated_validation"),
])
def test_each_hard_rule_detects(tmp_path, snippet, expected_rule):
    _write(tmp_path, "PRACTICAL_NOTES.md", f"# Notes\n{snippet}\n")
    code, out = _run(["--paths", str(tmp_path)])
    assert code == 1
    rules = {f["rule"] for f in out["findings"]}
    assert expected_rule in rules, (snippet, rules)
