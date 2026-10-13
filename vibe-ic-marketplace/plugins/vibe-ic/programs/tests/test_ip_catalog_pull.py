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
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize('source_kind', ['local_mirror', 'pinned_local_upstream'])
def test_delivered_wrapper_spdx_reaches_actual_attribution(tmp_path, monkeypatch, source_kind):
    root = _make_mirror(tmp_path, 'rtl/core.v', 'wrapper/adapter.v')
    upstream = root / 'myip'
    (upstream / 'LICENSE').write_text('ISC License\n')
    (upstream / 'rtl/core.v').write_text('// SPDX-License-Identifier: ISC\nmodule core; endmodule\n')
    (upstream / 'wrapper/adapter.v').write_text('/* SPDX-License-Identifier: Apache-2.0 */\nmodule adapter; endmodule\n')
    _patch_mirror(monkeypatch, root)
    monkeypatch.setattr(mod, 'IP_MIRROR_ROOT', None)
    match = _match(license='ISC', rtl_files=('rtl/core.v', 'wrapper/adapter.v'))
    if source_kind == 'pinned_local_upstream':
        for args in (('init', '-q'), ('config', 'user.name', 'Neutral fixture'),
                     ('config', 'user.email', 'fixture@example.invalid'),
                     ('add', '.'), ('commit', '-qm', 'Neutral mixed-license source')):
            subprocess.run(['git', '-C', str(upstream), *args], check=True,
                           capture_output=True, text=True)
        match.canonical_url = str(upstream)
        match.canonical_commit = subprocess.run(
            ['git', '-C', str(upstream), 'rev-parse', 'HEAD'], check=True,
            capture_output=True, text=True).stdout.strip()
    project = tmp_path / 'project'; project.mkdir()
    aggregate = mod.pull_all_catalog_matches(
        project, [match], official_only=source_kind == 'pinned_local_upstream',
        cache_root=tmp_path / 'own-cache')
    assert aggregate['n_ips_pulled'] == 1
    declaration = json.loads((project / 'plugin_output/declaration.json').read_text())
    cp = subprocess.run([sys.executable, str(Path(mod.__file__).with_name('gds_ip_attribution.py')),
                         'build-text', str(project)], capture_output=True, text=True)
    (tmp_path / 'actual-attribution.stdout').write_text(cp.stdout)
    (tmp_path / 'actual-attribution.stderr').write_text(cp.stderr)
    assert cp.returncode == 0, cp.stderr
    assert declaration['license_compliance_audit']['spdx_set'] == ['Apache-2.0', 'ISC']
    assert 'spdx_set=Apache-2.0,ISC' in cp.stdout
    assert declaration['license_compliance_audit']['all_permissive'] is True
    copied = declaration['ip_catalog_used'][0]['files_copied']
    assert len(copied) == 2
    expected = {'core.v': 'ISC', 'adapter.v': 'Apache-2.0'}
    for file in copied:
        path = Path(file['dest'])
        assert file['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        evidence = file['license_evidence']
        assert evidence['status'] == 'PASS'
        assert evidence['spdx'] == expected[path.name]
        assert evidence['basis'] == 'SPDX-License-Identifier'
        assert evidence['path'] == str(path)
        assert evidence['sha256'] == file['sha256']


@pytest.mark.parametrize('condition', [
    'unknown_wrapper', 'composite_wrapper', 'composite_lowercase_wrapper', 'composite_boundary_wrapper', 'contradictory_wrapper',
    'unreadable_wrapper', 'unknown_entry', 'unreadable_entry',
    'forbidden_wrapper', 'contradictory_entry', 'mismatched_entry',
])
def test_actual_source_license_refusal_reaches_attribution(tmp_path, monkeypatch, condition):
    root = _make_mirror(tmp_path, 'rtl/core.v', 'wrapper/adapter.v')
    upstream = root / 'myip'
    entry = upstream / 'LICENSE'; entry.write_text('ISC License\n')
    core = upstream / 'rtl/core.v'
    core.write_text('// SPDX-License-Identifier: ISC\nmodule core; endmodule\n')
    wrapper = upstream / 'wrapper/adapter.v'
    wrapper.write_text('// SPDX-License-Identifier: Apache-2.0\nmodule adapter; endmodule\n')
    unreadable = None
    if condition == 'unknown_wrapper':
        wrapper.write_text('// SPDX-License-Identifier: Unrecognized-9.9\nmodule adapter; endmodule\n')
    elif condition in ('composite_wrapper', 'composite_lowercase_wrapper', 'composite_boundary_wrapper'):
        marker = 'spdx-license-identifier' if 'lowercase' in condition else 'SPDX-License-Identifier'
        prefix = '// ' + marker + ': '
        filler = ('//' + '.' * (5000 - len(prefix) - len('ISC') - 3) + '\n'
                  if 'boundary' in condition else '')
        wrapper.write_text(filler + prefix + 'ISC OR GPL-3.0-only\nmodule adapter; endmodule\n')
    elif condition == 'contradictory_wrapper':
        wrapper.write_text('// SPDX-License-Identifier: ISC\n// SPDX-License-Identifier: Apache-2.0\nmodule adapter; endmodule\n')
    elif condition == 'forbidden_wrapper':
        wrapper.write_text('// SPDX-License-Identifier: GPL-3.0-only\nmodule adapter; endmodule\n')
    elif condition == 'unknown_entry':
        entry.write_text('Unrecognized license document\n')
    elif condition == 'contradictory_entry':
        entry.write_text('// SPDX-License-Identifier: ISC\n// SPDX-License-Identifier: Apache-2.0\n')
    elif condition == 'mismatched_entry':
        entry.write_text('GNU GENERAL PUBLIC LICENSE\n')
    else:
        unreadable = wrapper if condition == 'unreadable_wrapper' else entry
        unreadable.chmod(0)
    _patch_mirror(monkeypatch, root)
    monkeypatch.setattr(mod, 'IP_MIRROR_ROOT', None)
    project = tmp_path / 'project'; project.mkdir()
    try:
        aggregate = mod.pull_all_catalog_matches(
            project, [_match(license='ISC', rtl_files=('rtl/core.v', 'wrapper/adapter.v'))])
    finally:
        if unreadable: unreadable.chmod(0o644)
    cp = subprocess.run([sys.executable, str(Path(mod.__file__).with_name('gds_ip_attribution.py')),
                         'build-text', str(project)], capture_output=True, text=True)
    (tmp_path / 'actual-attribution.stdout').write_text(cp.stdout)
    (tmp_path / 'actual-attribution.stderr').write_text(cp.stderr)
    audit = aggregate['license_compliance_audit']
    assert audit['all_permissive'] is False, audit
    assert 'LICENSE-AUDIT all_permissive=False' in cp.stdout
    expected = ('NOT_MEASURED' if condition in
                ('unknown_entry', 'unreadable_entry', 'unreadable_wrapper') else 'REJECTED')
    assert audit['status'] == expected, audit
    ip = aggregate['ip_catalog_used'][0]
    if condition.endswith('wrapper'):
        # A conflicting, prohibited or unreadable source was refused before copy.
        assert not (project / 'phase2/stage1/rtl/adapter.v').exists()
        refused = ip['file_license_refusals'][0]
        assert refused['path'] == str(wrapper)
        assert refused['status'] == expected
        if condition == 'unreadable_wrapper':
            assert 'LICENSE_SOURCE_UNREADABLE' in refused['reason']
        else:
            assert refused['sha256'] == hashlib.sha256(wrapper.read_bytes()).hexdigest()
        if condition.startswith('composite_'):
            assert refused['spdx'] == 'ISC OR GPL-3.0-only'  # full expression, never just ISC
    else:
        assert len(ip['files_copied']) == 2
        assert ip['entry_license_evidence']['status'] == expected
        assert audit['spdx_set'] == ['Apache-2.0', 'ISC']  # actual delivered population is never dropped


def test_headerless_copy_uses_actual_upstream_license_evidence(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path, 'rtl/core.v')
    _patch_mirror(monkeypatch, root)
    monkeypatch.setattr(mod, 'IP_MIRROR_ROOT', None)
    project = tmp_path / 'project'; project.mkdir()
    aggregate = mod.pull_all_catalog_matches(project, [_match()])
    evidence = aggregate['ip_catalog_used'][0]['files_copied'][0]['license_evidence']
    assert aggregate['license_compliance_audit']['all_permissive'] is True
    assert evidence['spdx'] == 'MIT'
    assert evidence['basis'] == 'upstream_license_file'
    assert evidence['license_path'] == str(root / 'myip/LICENSE')
    assert evidence['license_sha256'] == hashlib.sha256((root / 'myip/LICENSE').read_bytes()).hexdigest()


@pytest.mark.parametrize('condition,header,denied', [
    ('denied_spdx', 'This header is not applicable: SPDX-License-Identifier: ISC', True),
    ('denied_prose', 'This file is not covered by the MIT License.', True),
    ('mit_boilerplate', 'MIT License\n\nPermission is hereby granted, free of charge, '
     'to any person obtaining a copy, to deal in the Software without restriction.\n\n'
     'THE SOFTWARE IS PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND. '
     'IN NO EVENT SHALL THE AUTHORS BE LIABLE.', False),
    ('isc_grant', 'Permission to use, copy, modify, and/or distribute this software '
     'for any purpose with or without fee is hereby granted.\n\n'
     'THE SOFTWARE IS PROVIDED AS IS WITHOUT WARRANTY.', False),
    ('legacy_grant', 'This source may be used and distributed without restriction '
     'provided that this copyright statement is retained.\n\n'
     'There is no warranty.', False),
    ('legacy_padded_grant', 'This source may be used and distributed '
     'without////restriction////provided////that////this////copyright////statement '
     'is retained.\n\nThere is no warranty.', False),
])
def test_license_claim_polarity_reaches_actual_attribution(tmp_path, monkeypatch, condition, header, denied):
    root = _make_mirror(tmp_path, 'rtl/core.v', 'wrapper/adapter.v')
    upstream = root / 'myip'
    (upstream / 'LICENSE').write_text('ISC License\n')
    (upstream / 'rtl/core.v').write_text('// SPDX-License-Identifier: ISC\nmodule core; endmodule\n')
    wrapper = upstream / 'wrapper/adapter.v'
    payload = ('/* ' + header + ' */\nmodule adapter; endmodule\n').encode()
    wrapper.write_bytes(payload)
    _patch_mirror(monkeypatch, root)
    monkeypatch.setattr(mod, 'IP_MIRROR_ROOT', None)
    project = tmp_path / 'project'; project.mkdir()
    aggregate = mod.pull_all_catalog_matches(
        project, [_match(license='ISC', rtl_files=('rtl/core.v', 'wrapper/adapter.v'))])
    cp = subprocess.run([sys.executable, str(Path(mod.__file__).with_name('gds_ip_attribution.py')),
                         'build-text', str(project)], capture_output=True, text=True)
    (tmp_path / 'actual-attribution.stdout').write_text(cp.stdout)
    (tmp_path / 'actual-attribution.stderr').write_text(cp.stderr)
    (tmp_path / 'actual-copy-audit.json').write_text(json.dumps(aggregate, indent=2))
    assert wrapper.read_bytes() == payload
    audit = aggregate['license_compliance_audit']
    ip = aggregate['ip_catalog_used'][0]
    if denied:
        assert audit['status'] == 'REJECTED', audit
        assert audit['all_permissive'] is False, audit
        assert 'LICENSE-AUDIT all_permissive=False' in cp.stdout
        assert not (project / 'phase2/stage1/rtl/adapter.v').exists()
        evidence = ip['file_license_refusals'][0]
        assert evidence['status'] == 'REJECTED'
        assert 'LICENSE_SOURCE_DENIED' in evidence['reason']
    else:
        assert audit['status'] == 'PASS', audit
        assert audit['all_permissive'] is True, audit
        assert cp.returncode == 0, cp.stderr
        evidence = next(file['license_evidence'] for file in ip['files_copied']
                        if Path(file['dest']).name == 'adapter.v')
        assert evidence['status'] == 'PASS'
        assert evidence['basis'] == 'source_header'
        assert Path(evidence['path']).read_bytes() == payload
    assert evidence['sha256'] == hashlib.sha256(payload).hexdigest()
