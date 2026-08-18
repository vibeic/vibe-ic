"""Unit tests for gameable_placeholder_scan.py.

Covers the three deterministic gameability patterns extracted out of the
compliance-gate-spot-check skill Step 3:

  * CLEAN PASS on legit L docs (no placeholder / no auto-alias / real
    verdict byte).
  * PLACEHOLDER_TOKEN FAIL (__TODO__ / <unknown> survive in an L doc).
  * AUTO_ALIAS FAIL (pin alias == name.lower()/name.replace('_','')).
  * VERDICT_PLACEHOLDER FAIL (L9 expected_verdict_byte_hex == 0x__todo__).
  * Missing-data HONESTY: no generated_docs → exit 1 (NO_GENERATED_DOCS),
    NOT a vacuous PASS.
  * Real-corpus CLEAN: every benchmark_ic project scans clean.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "gameable_placeholder_scan.py"
assert SCRIPT.exists()


def _run(project_dir: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(project_dir), "--json", "-"],
        capture_output=True, text=True,
    )


def _report(project_dir: Path):
    r = _run(project_dir)
    return r, json.loads(r.stdout)


def _gendir(tmp_path: Path) -> Path:
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    return d


def _write(d: Path, name: str, obj):
    (d / name).write_text(json.dumps(obj))


# ───────────────────────── CLEAN ─────────────────────────

def test_clean_passes(tmp_path):
    d = _gendir(tmp_path)
    _write(d, "L1_DATASHEET.json", {
        "ic_name": "myspi",
        "pin_table": [
            {"name": "SCLK", "aliases": ["spi_clk", "clk_in"]},
            {"name": "MOSI", "aliases": ["data_in"]},
        ],
    })
    _write(d, "L9_INTEGRATION_SPEC.json", {
        "expected_verdict_byte_hex": "0xF2",
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 0, r.stdout
    assert rep["verdict"] == "CLEAN"
    assert rep["summary"]["l_docs_scanned"] == 2
    assert rep["findings"] == []


# ─────────────────── PLACEHOLDER_TOKEN ───────────────────

def test_todo_token_fails(tmp_path):
    d = _gendir(tmp_path)
    _write(d, "L3_CMD_PROTOCOL.json", {
        "opcodes": [{"hex": "0x01", "name": "__TODO__"}],
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert rep["verdict"] == "FAIL"
    pats = {f["pattern"] for f in rep["findings"]}
    assert "PLACEHOLDER_TOKEN" in pats


def test_unknown_token_fails(tmp_path):
    d = _gendir(tmp_path)
    _write(d, "L1_DATASHEET.json", {"ic_name": "<unknown>"})
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert any(f["pattern"] == "PLACEHOLDER_TOKEN" for f in rep["findings"])


# ───────────────────────── AUTO_ALIAS ─────────────────────────

def test_auto_alias_lower_fails(tmp_path):
    d = _gendir(tmp_path)
    # alias "sclk" == "SCLK".lower() — evidence-free auto-synth.
    _write(d, "L1_DATASHEET.json", {
        "pin_table": [{"name": "SCLK", "aliases": ["sclk"]}],
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert any(f["pattern"] == "AUTO_ALIAS" for f in rep["findings"])


def test_auto_alias_stripped_underscore_fails(tmp_path):
    d = _gendir(tmp_path)
    # alias "datain" == "data_in".replace("_","")
    _write(d, "L1_DATASHEET.json", {
        "pins": [{"name": "data_in", "aliases": ["datain"]}],
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert any(f["pattern"] == "AUTO_ALIAS" for f in rep["findings"])


def test_real_alias_does_not_fire(tmp_path):
    d = _gendir(tmp_path)
    # A genuine datasheet/RTL synonym is NOT name.lower()/strip-underscore.
    _write(d, "L1_DATASHEET.json", {
        "pin_table": [{"name": "SCLK", "aliases": ["serial_clock"]}],
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 0
    assert rep["verdict"] == "CLEAN"


# ─────────────────── VERDICT_PLACEHOLDER ───────────────────

def test_verdict_placeholder_fails(tmp_path):
    d = _gendir(tmp_path)
    _write(d, "L9_INTEGRATION_SPEC.json", {
        "expected_verdict_byte_hex": "0x__todo__",
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert any(f["pattern"] == "VERDICT_PLACEHOLDER" for f in rep["findings"])


def test_verdict_placeholder_case_insensitive(tmp_path):
    d = _gendir(tmp_path)
    _write(d, "L9_INTEGRATION_SPEC.json", {
        "usb_hid_tester_verdict_byte_hex": "0X__TODO__",
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert any(f["pattern"] == "VERDICT_PLACEHOLDER" for f in rep["findings"])


def test_null_verdict_is_clean(tmp_path):
    # Real corpus carries None (not yet resolved) — that is the L9
    # gate's job, NOT a gameable placeholder string. Must not fire.
    d = _gendir(tmp_path)
    _write(d, "L9_INTEGRATION_SPEC.json", {
        "expected_verdict_byte_hex": None,
    })
    r, rep = _report(tmp_path)
    assert r.returncode == 0
    assert rep["verdict"] == "CLEAN"


# ─────────────────── missing-data HONESTY ───────────────────

def test_no_generated_docs_is_honest_fail(tmp_path):
    # No phase1/generated_docs at all → must NOT vacuous-PASS.
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert rep["verdict"] == "NO_GENERATED_DOCS"


def test_empty_generated_docs_is_honest_fail(tmp_path):
    _gendir(tmp_path)  # dir exists but no L*.json
    r, rep = _report(tmp_path)
    assert r.returncode == 1
    assert rep["verdict"] == "NO_GENERATED_DOCS"


def test_bad_project_dir_exit_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "nope")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ─────────────────── real-corpus CLEAN guard ───────────────────

def _corpus_projects():
    # flow #486: benchmark_ic/ lives at the repo root (source monorepo). On
    # the flattened install cache there is no repo root, so this resolves to
    # a non-existent path → empty parametrize → the test simply does not run
    # (no IndexError from a hard-coded parents[5]).
    from _plugin_tree import repo_path_or_missing
    root = repo_path_or_missing("benchmark-data", "ic")
    if not root.is_dir():
        return []
    return sorted(p.parent.parent for p in
                  root.glob("*/phase1/generated_docs"))


@pytest.mark.parametrize("proj", _corpus_projects(),
                         ids=lambda p: p.name)
def test_real_corpus_scans_clean(proj):
    """The guard must not false-fire on any legitimate existing
    corpus project."""
    r, rep = _report(proj)
    assert rep["verdict"] == "CLEAN", (
        f"{proj.name} false-fired: {rep['findings']}")
    assert r.returncode == 0
