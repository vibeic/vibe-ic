#!/usr/bin/env python3
"""Tests for ip_catalog_validate.py — catalog manifest schema +
permissive-license whitelist gate.

Pins the real validate_manifest() decision logic (PASS / FAIL on the
exact defects it guards: forbidden license, missing required field,
malformed interface ports, non-HTTP canonical_url, unknown license) AND
the CLI exit code at the harness boundary (real catalog -> 0; injected
catalog with an unknown-license manifest -> 1).

logic-pinned.
"""
from __future__ import annotations

import json

import ip_catalog_validate as v


# ── valid manifest -> PASS, no issues ────────────────────────────────
def _good() -> dict:
    return {
        "ip_name": "serv",
        "ip_version": "1.0",
        "ip_class": "cpu",
        "license": "ISC",  # in PERMISSIVE_LICENSES
        "canonical_url": "https://github.com/olofk/serv",
        "description": "rv32 bit-serial core",
        "implements": ["rv32"],
        "matches_when": ["riscv"],
        "interface": {"ports": [{"name": "clk", "dir": "in"},
                                {"name": "q", "dir": "out"}]},
        "rtl_files": ["serv.v"],
    }


def test_valid_manifest_passes():
    ok, issues = v.validate_manifest(_good())
    assert ok is True
    assert issues == []


# ── the exact defects the gate guards ────────────────────────────────
def test_forbidden_license_rejected():
    m = _good()
    m["license"] = "AGPL-3.0"
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("FORBIDDEN" in i and "AGPL-3.0" in i for i in issues)


def test_unknown_license_flagged():
    m = _good()
    m["license"] = "Weird-License-99"
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("unknown license" in i for i in issues)


def test_missing_required_field_fails():
    m = _good()
    del m["ip_name"]
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("missing required field: ip_name" in i for i in issues)


def test_empty_matches_when_fails():
    m = _good()
    m["matches_when"] = []
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("matches_when must be non-empty list" in i for i in issues)


def test_empty_rtl_files_fails():
    m = _good()
    m["rtl_files"] = []
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("rtl_files must be non-empty list" in i for i in issues)


def test_bad_port_dir_fails():
    m = _good()
    m["interface"] = {"ports": [{"name": "clk", "dir": "sideways"}]}
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("dir invalid" in i for i in issues)


def test_port_missing_name_and_dir_fails():
    m = _good()
    m["interface"] = {"ports": [{}]}
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("missing 'name'" in i for i in issues)
    assert any("missing 'dir'" in i for i in issues)


def test_non_http_canonical_url_fails():
    m = _good()
    m["canonical_url"] = "ftp://example.com/x"
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("canonical_url should be HTTP(S) URL" in i for i in issues)


def test_interface_not_dict_fails():
    m = _good()
    m["interface"] = "not a dict"
    ok, issues = v.validate_manifest(m)
    assert ok is False
    assert any("interface must be dict" in i for i in issues)


# ── edge: empty manifest -> every required field flagged ─────────────
def test_empty_manifest_flags_everything():
    ok, issues = v.validate_manifest({})
    assert ok is False
    # every required field should be reported missing
    for f in v.REQUIRED_FIELDS:
        assert any(f"missing required field: {f}" == i for i in issues)


# ── CLI boundary ─────────────────────────────────────────────────────
def _write_manifest(catalog: "Path", category: str, name: str, lic: str):  # noqa
    d = catalog / category / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.yaml").write_text(
        "ip_name: {n}\n"
        "ip_version: 1.0\n"
        "ip_class: cpu\n"
        "license: {lic}\n"
        "canonical_url: https://github.com/x/{n}\n"
        "description: a core\n"
        "implements:\n  - rv32\n"
        "matches_when:\n  - riscv\n"
        "interface:\n  ports:\n    - name: clk\n      dir: in\n"
        "rtl_files:\n  - {n}.v\n".format(n=name, lic=lic)
    )


def test_cli_permissive_catalog_passes(tmp_path, capsys):
    _write_manifest(tmp_path, "cpu", "goodcore", "ISC")
    rc = v.main(["--catalog-dir", str(tmp_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    summary = json.loads(out)["summary"]
    assert summary["total"] == 1
    assert summary["pass"] == 1
    assert summary["fail"] == 0


def test_cli_unknown_license_catalog_fails(tmp_path, capsys):
    _write_manifest(tmp_path, "cpu", "unkcore", "Weird-License-99")
    rc = v.main(["--catalog-dir", str(tmp_path), "--json"])
    assert rc == 1
    out = capsys.readouterr().out
    summary = json.loads(out)["summary"]
    assert summary["fail"] == 1
