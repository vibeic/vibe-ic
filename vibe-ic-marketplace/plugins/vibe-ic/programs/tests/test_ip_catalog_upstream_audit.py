#!/usr/bin/env python3
"""Tests for ip_catalog_upstream_audit.py — catalog-vs-mirror hygiene audit.

Network (git ls-remote / shallow clone) is out of scope for a unit test, so
we exercise the deterministic, offline halves:
  * infer_spdx_from_text: SPDX inference from LICENSE prose.
  * audit_local_files: verify declared rtl_files exist in the local mirror
    and the claimed SPDX matches the mirror's LICENSE — the real provenance
    defect the audit guards (a manifest claiming the wrong license, or
    declaring files that are not actually present).

find_local_mirror is monkeypatched to a tmp mirror so the test is
hermetic (no dependence on ~/ic_documents).
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ip_catalog_upstream_audit as mod  # noqa: E402

_ISC_LICENSE = (
    "ISC License\n\n"
    "Permission to use, copy, modify, and/or distribute this software for "
    "any purpose with or without fee is hereby granted.\n"
)


def _make_mirror(tmp_path: Path, license_text: str | None,
                 files: list[str]) -> Path:
    mirror = tmp_path / "mirror" / "serv"
    mirror.mkdir(parents=True)
    for rel in files:
        (mirror / rel).parent.mkdir(parents=True, exist_ok=True)
        (mirror / rel).write_text("// rtl content\n")
    if license_text is not None:
        (mirror / "LICENSE").write_text(license_text)
    return mirror


# ----------------------------------------------------------------------
# infer_spdx_from_text — the license-inference primitive.
# ----------------------------------------------------------------------
def test_infer_spdx_known_licenses():
    assert mod.infer_spdx_from_text(_ISC_LICENSE) == "ISC"
    assert mod.infer_spdx_from_text("Apache License, Version 2.0") == \
        "Apache-2.0"
    assert mod.infer_spdx_from_text(
        "MIT License\n\nPermission is hereby granted, free of charge"
    ) == "MIT"


def test_infer_spdx_unrecognised_returns_none():
    assert mod.infer_spdx_from_text("totally unrelated prose, no license") \
        is None


# ----------------------------------------------------------------------
# audit_local_files — PASS: files present + claimed license matches.
# ----------------------------------------------------------------------
def test_audit_local_pass(tmp_path, monkeypatch):
    mirror = _make_mirror(tmp_path, _ISC_LICENSE, ["serv.v"])
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    r = mod.audit_local_files(
        {"ip_name": "serv", "license": "ISC", "rtl_files": ["serv.v"]})
    assert r["ok"] is True
    assert r["license_check"]["match"] is True
    assert r["license_check"]["inferred"] == "ISC"
    assert r["files_present_count"] == 1
    assert r["files_missing_count"] == 0
    assert r["issues"] == []


# ----------------------------------------------------------------------
# audit_local_files — the defects guarded.
# ----------------------------------------------------------------------
def test_audit_local_license_mismatch_fails(tmp_path, monkeypatch):
    # Mirror LICENSE is ISC but the manifest claims MIT -> mismatch FAIL.
    mirror = _make_mirror(tmp_path, _ISC_LICENSE, ["serv.v"])
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    r = mod.audit_local_files(
        {"ip_name": "serv", "license": "MIT", "rtl_files": ["serv.v"]})
    assert r["ok"] is False
    assert r["license_check"]["match"] is False
    assert any("license mismatch" in i for i in r["issues"])


def test_audit_local_missing_file_fails(tmp_path, monkeypatch):
    mirror = _make_mirror(tmp_path, _ISC_LICENSE, ["serv.v"])
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    r = mod.audit_local_files(
        {"ip_name": "serv", "license": "ISC",
         "rtl_files": ["serv.v", "absent_module.v"]})
    assert r["ok"] is False
    assert r["files_missing_count"] == 1
    assert "absent_module.v" in r["files_missing_sample"]


def test_audit_local_no_license_file_fails(tmp_path, monkeypatch):
    # No LICENSE and no recognisable .v header -> honest FAIL.
    mirror = _make_mirror(tmp_path, None, ["serv.v"])
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    r = mod.audit_local_files(
        {"ip_name": "serv", "license": "ISC", "rtl_files": ["serv.v"]})
    assert r["ok"] is False
    assert any("no LICENSE" in i for i in r["issues"])


# ----------------------------------------------------------------------
# Missing mirror -> honest FAIL (never a vacuous PASS).
# ----------------------------------------------------------------------
def test_audit_local_no_mirror_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: None)
    r = mod.audit_local_files(
        {"ip_name": "ghost", "license": "ISC", "rtl_files": []})
    assert r["ok"] is False
    assert r["stage"] == "local_mirror"
    assert "no local mirror" in r["issue"]
