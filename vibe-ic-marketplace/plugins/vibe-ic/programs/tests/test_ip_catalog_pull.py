#!/usr/bin/env python3
"""Unit tests for programs/ip_catalog_pull.py.

Pins the real catalog-IP pull behavior:
  - PASS: a permissively-licensed IP whose RTL exists in a local mirror
    is copied into phase2/stage1/rtl/, sha256-stamped, and a
    provenance.jsonl line is appended.
  - REJECTED: a GPL/copyleft IP is refused before any copy (license gate).
  - FAIL: no local mirror + no clonable URL -> status FAIL, no files.
  - PARTIAL: some manifest files missing in the mirror.
  - aggregate: declaration.json is written with the license audit.
Logic-pinned.
"""
from __future__ import annotations

import json
from pathlib import Path

import ip_catalog_pull as mod
from ip_catalog_query import CatalogMatch


def _make_mirror(tmp_path: Path, *files: str) -> Path:
    """Create a fake local mirror dir under tmp containing `files`
    (relative paths) + a LICENSE file. Returns the mirror ROOT (parent
    of the ip dir 'myip')."""
    root = tmp_path / "mirror_root"
    ip_dir = root / "myip"
    for rel in files:
        p = ip_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}\nmodule x; endmodule\n")
    (ip_dir / "LICENSE").write_text("MIT License — permissive\n")
    return root


def _patch_mirror(monkeypatch, root: Path):
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {})  # name == ip_name


def _match(ip_name="myip", license="MIT", rtl_files=("rtl/core.v",), url=""):
    return CatalogMatch(
        ip_name=ip_name, category="cpu", version="1.0", license=license,
        canonical_url=url, canonical_commit="", matched_pattern="pat",
        confidence=0.9, manifest_path="m", rtl_files=list(rtl_files),
    )


# ---------------------------------------------------------------------------
# PASS
# ---------------------------------------------------------------------------
def test_pull_pass_copies_and_records_provenance(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path, "rtl/core.v")
    _patch_mirror(monkeypatch, root)
    project = tmp_path / "proj"
    project.mkdir()
    audit = mod.pull_catalog_ip(_match(), project)
    assert audit["status"] == "PASS"
    assert audit["n_files_copied"] == 1
    assert audit["n_files_missing"] == 0
    # file actually landed in the canonical rtl dir
    dest = project / "phase2" / "stage1" / "rtl" / "core.v"
    assert dest.is_file()
    # provenance line carries the outputs map with a sha256
    prov = (project / "provenance.jsonl").read_text().strip()
    rec = json.loads(prov)
    assert rec["event"] == "ip_catalog_pull"
    assert rec["ip"] == "myip"
    assert rec["files_pulled"] == 1
    out_key = next(iter(rec["outputs"]))
    assert rec["outputs"][out_key].startswith("sha256:")


# ---------------------------------------------------------------------------
# REJECTED — the license gate is the defect this guards
# ---------------------------------------------------------------------------
def test_pull_rejects_gpl_before_copy(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path, "rtl/core.v")
    _patch_mirror(monkeypatch, root)
    project = tmp_path / "proj"
    project.mkdir()
    audit = mod.pull_catalog_ip(_match(license="GPL-3.0"), project)
    assert audit["status"] == "REJECTED"
    assert "GPL-3.0" in audit["reason"]
    # nothing copied, no provenance written
    assert not (project / "phase2").exists()
    assert not (project / "provenance.jsonl").exists()


def test_pull_rejects_unknown_license(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path, "rtl/core.v")
    _patch_mirror(monkeypatch, root)
    project = tmp_path / "proj"
    project.mkdir()
    audit = mod.pull_catalog_ip(_match(license="Bogus-9.9"), project)
    assert audit["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# FAIL — no mirror, no clonable URL
# ---------------------------------------------------------------------------
def test_pull_fail_when_no_mirror_no_url(tmp_path, monkeypatch):
    # mirror root exists but holds no dir named after the IP
    empty_root = tmp_path / "empty_mirror"
    empty_root.mkdir()
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [empty_root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {})
    project = tmp_path / "proj"
    project.mkdir()
    audit = mod.pull_catalog_ip(_match(ip_name="nope", url=""), project)
    assert audit["status"] == "FAIL"
    assert "no local mirror" in audit["reason"]


# ---------------------------------------------------------------------------
# PARTIAL — manifest lists a file the mirror does not have
# ---------------------------------------------------------------------------
def test_pull_partial_when_some_files_missing(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path, "rtl/core.v")  # only core.v present
    _patch_mirror(monkeypatch, root)
    project = tmp_path / "proj"
    project.mkdir()
    # ask for core.v (present) + ghost.v (absent, basename rglob also fails)
    audit = mod.pull_catalog_ip(
        _match(rtl_files=("rtl/core.v", "rtl/ghost_absent_file.v")),
        project,
    )
    assert audit["status"] == "PARTIAL"
    assert audit["n_files_copied"] == 1
    assert "rtl/ghost_absent_file.v" in audit["files_missing"]


# ---------------------------------------------------------------------------
# aggregate -> declaration.json
# ---------------------------------------------------------------------------
def test_pull_all_writes_declaration(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path, "rtl/core.v")
    _patch_mirror(monkeypatch, root)
    project = tmp_path / "proj"
    project.mkdir()
    agg = mod.pull_all_catalog_matches(project, [_match()])
    assert agg["n_ips_pulled"] == 1
    assert agg["rtl_strategy"] == "catalog_lookup_plus_ai_glue"
    decl = json.loads(
        (project / "plugin_output" / "declaration.json").read_text())
    assert decl["license_compliance_audit"]["all_permissive"] is True
    assert "MIT" in decl["license_compliance_audit"]["spdx_set"]
