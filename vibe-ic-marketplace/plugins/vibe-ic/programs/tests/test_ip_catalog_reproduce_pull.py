#!/usr/bin/env python3
"""Tests for ip_catalog_reproduce_pull.py — local-mirror vs upstream
reproducibility check.

The real network clone is out of scope for a unit test, so _git_clone_shallow
is monkeypatched to populate a fake upstream tree. This lets us pin the
load-bearing SHA256 comparison logic that decides REPRODUCIBLE vs the exact
provenance defect it guards — DRIFT_DETECTED, when the local mirror's bytes
no longer match upstream (a locally edited / commit-skewed file). SKIP and
FAIL paths (no mirror / no URL / clone failure) are pinned too.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ip_catalog_reproduce_pull as mod  # noqa: E402

_URL = "https://github.com/olofk/serv"


def _mirror(tmp_path: Path, content: str) -> Path:
    m = tmp_path / "mirror" / "serv"
    m.mkdir(parents=True)
    (m / "serv.v").write_text(content)
    return m


def _clone_writer(content: str):
    def _clone(url, dest, commit=None):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "serv.v").write_text(content)
        return True
    return _clone


# ----------------------------------------------------------------------
# _sha256_file — the comparison primitive must be a real hash.
# ----------------------------------------------------------------------
def test_sha256_file_matches_hashlib(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert mod._sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


# ----------------------------------------------------------------------
# PASS — identical local + upstream bytes -> REPRODUCIBLE.
# ----------------------------------------------------------------------
def test_reproducible_when_bytes_match(tmp_path, monkeypatch):
    mirror = _mirror(tmp_path, "IDENTICAL CONTENT")
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    monkeypatch.setattr(mod, "_git_clone_shallow",
                        _clone_writer("IDENTICAL CONTENT"))
    r = mod.reproduce_one_ip({
        "ip_name": "serv", "canonical_url": _URL,
        "canonical_commit": "master", "rtl_files": ["serv.v"],
    })
    assert r["status"] == "REPRODUCIBLE"
    assert r["n_match"] == 1
    assert r["n_diverge"] == 0


# ----------------------------------------------------------------------
# The defect guarded — local mirror has drifted from upstream.
# ----------------------------------------------------------------------
def test_drift_detected_when_bytes_differ(tmp_path, monkeypatch):
    mirror = _mirror(tmp_path, "LOCAL EDITED VERSION")
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    monkeypatch.setattr(mod, "_git_clone_shallow",
                        _clone_writer("UPSTREAM CANONICAL VERSION"))
    r = mod.reproduce_one_ip({
        "ip_name": "serv", "canonical_url": _URL,
        "canonical_commit": "master", "rtl_files": ["serv.v"],
    })
    assert r["status"] == "DRIFT_DETECTED"
    assert r["n_diverge"] == 1
    assert "serv.v" in r["diverged_files"]


def test_missing_upstream_file_is_reproducible_with_gaps(tmp_path, monkeypatch):
    mirror = _mirror(tmp_path, "LOCAL ONLY")
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: mirror)
    # clone writes nothing for the declared rtl file -> MISSING_UPSTREAM,
    # but no DIVERGE -> REPRODUCIBLE_WITH_GAPS (not a hard drift).
    monkeypatch.setattr(mod, "_git_clone_shallow",
                        lambda url, dest, commit=None: (
                            Path(dest).mkdir(parents=True, exist_ok=True) or True))
    r = mod.reproduce_one_ip({
        "ip_name": "serv", "canonical_url": _URL,
        "canonical_commit": "master", "rtl_files": ["serv.v"],
    })
    assert r["status"] == "REPRODUCIBLE_WITH_GAPS"
    assert r["n_missing_upstream"] == 1
    assert r["n_diverge"] == 0


# ----------------------------------------------------------------------
# SKIP / FAIL paths — honest non-PASS without a mirror / URL / clone.
# ----------------------------------------------------------------------
def test_skip_when_no_local_mirror(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: None)
    r = mod.reproduce_one_ip(
        {"ip_name": "x", "canonical_url": _URL, "rtl_files": []})
    assert r["status"] == "SKIP_NO_LOCAL_MIRROR"


def test_skip_when_no_canonical_url(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "find_local_mirror",
                        lambda name: tmp_path)
    r = mod.reproduce_one_ip(
        {"ip_name": "x", "canonical_url": "", "rtl_files": []})
    assert r["status"] == "SKIP_NO_CANONICAL_URL"
    r2 = mod.reproduce_one_ip(
        {"ip_name": "x", "canonical_url": "ftp://bad", "rtl_files": []})
    assert r2["status"] == "SKIP_NO_CANONICAL_URL"


def test_fail_when_clone_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "find_local_mirror", lambda name: tmp_path)
    monkeypatch.setattr(mod, "_git_clone_shallow",
                        lambda url, dest, commit=None: False)
    r = mod.reproduce_one_ip({
        "ip_name": "x", "canonical_url": _URL,
        "canonical_commit": "master", "rtl_files": [],
    })
    assert r["status"] == "FAIL_GIT_CLONE"
