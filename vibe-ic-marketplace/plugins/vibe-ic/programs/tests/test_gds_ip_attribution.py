#!/usr/bin/env python3
"""Tests for gds_ip_attribution.py — embed/extract IP-attribution metadata.

The GDS inject/extract paths need klayout (pya), which is typically absent
in CI, and they degrade honestly (inject returns False, extract returns "").
The load-bearing, always-available logic is build_attribution_blob: it
serialises declaration.json (catalog IPs + AI-authored files + license
audit + rtl_strategy) into the VIBE-IC-CATALOG-AUDIT text record. Those are
the lines a foundry reviewer reads, so they are what we pin.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gds_ip_attribution as mod  # noqa: E402

_PROG = _PROGRAMS / "gds_ip_attribution.py"


# ----------------------------------------------------------------------
# PASS — a full declaration serialises into every audit line.
# ----------------------------------------------------------------------
def test_build_blob_full_declaration():
    decl = {
        "ip_catalog_used": [{
            "ip_name": "serv", "version": "1.4.0", "license": "ISC",
            "canonical_commit": "1.4.0",
            "canonical_url": "https://github.com/olofk/serv",
            "files_copied": [{"sha256": "abc123"}, {"sha256": "def456"}],
        }],
        "ai_authored_files": [
            "my_chip_top.v",
            {"file_name": "wrapper.v", "sha256": "0123456789abcdef0000"},
        ],
        "license_compliance_audit": {
            "spdx_set": ["ISC", "Apache-2.0"], "all_permissive": True,
        },
        "rtl_strategy": "catalog_glue",
    }
    blob = mod.build_attribution_blob(decl)
    lines = blob.splitlines()
    assert lines[0] == "VIBE-IC-CATALOG-AUDIT v1"
    # catalog IP line carries name/version/license/file-count/url/commit
    ip_line = next(l for l in lines if l.startswith("IP serv"))
    assert "1.4.0 ISC files=2" in ip_line
    assert "url:https://github.com/olofk/serv" in ip_line
    assert "commit:1.4.0" in ip_line
    assert "sha256_agg:" in ip_line  # aggregate hash, not a literal echo
    # both AI-authored forms (bare string + dict-with-sha) render
    assert "AI-AUTHORED my_chip_top.v" in lines
    assert any(l.startswith("AI-AUTHORED wrapper.v sha256:") for l in lines)
    # license audit + strategy footer
    assert any(l.startswith("LICENSE-AUDIT all_permissive=True") for l in lines)
    assert "RTL-STRATEGY catalog_glue" in lines


def test_aggregate_sha_changes_with_file_content():
    base = {"ip_catalog_used": [{
        "ip_name": "ip", "files_copied": [{"sha256": "aaaa"}]}]}
    alt = {"ip_catalog_used": [{
        "ip_name": "ip", "files_copied": [{"sha256": "bbbb"}]}]}
    line_a = next(l for l in mod.build_attribution_blob(base).splitlines()
                  if l.startswith("IP ip"))
    line_b = next(l for l in mod.build_attribution_blob(alt).splitlines()
                  if l.startswith("IP ip"))
    # different source-file sha -> different aggregate (real hashing)
    assert line_a != line_b


# ----------------------------------------------------------------------
# Edge — empty declaration still emits the header + strategy footer only.
# ----------------------------------------------------------------------
def test_build_blob_empty_declaration():
    blob = mod.build_attribution_blob({})
    assert blob.splitlines() == [
        "VIBE-IC-CATALOG-AUDIT v1",
        "RTL-STRATEGY unspecified",
    ]


def test_read_attribution_without_pya_returns_empty():
    # No klayout -> honest "" instead of a crash.
    try:
        import pya  # noqa: F401
        return  # pya present: this degradation path isn't exercised
    except ImportError:
        pass
    assert mod.read_attribution_from_gds(Path("/no/such/file.gds")) == ""


# ----------------------------------------------------------------------
# CLI — build-text path (PASS) and missing-declaration path (FAIL rc=2).
# ----------------------------------------------------------------------
def test_cli_build_text_pass(tmp_path):
    proj = tmp_path / "proj"
    (proj / "plugin_output").mkdir(parents=True)
    (proj / "plugin_output" / "declaration.json").write_text(json.dumps({
        "ip_catalog_used": [{"ip_name": "serv", "version": "1.4.0",
                             "license": "ISC",
                             "files_copied": [{"sha256": "abc"}]}],
        "ai_authored_files": ["top.v"],
        "rtl_strategy": "glue",
    }))
    cp = subprocess.run(
        [sys.executable, str(_PROG), "build-text", str(proj)],
        capture_output=True, text=True,
    )
    assert cp.returncode == 0
    assert "VIBE-IC-CATALOG-AUDIT v1" in cp.stdout
    assert "IP serv 1.4.0 ISC" in cp.stdout


def test_cli_build_text_missing_declaration_fails(tmp_path):
    cp = subprocess.run(
        [sys.executable, str(_PROG), "build-text", str(tmp_path / "nope")],
        capture_output=True, text=True,
    )
    assert cp.returncode == 2
    assert "not found" in cp.stderr
