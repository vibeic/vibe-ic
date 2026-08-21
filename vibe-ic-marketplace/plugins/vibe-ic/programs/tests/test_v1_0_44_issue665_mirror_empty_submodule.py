#!/usr/bin/env python3
"""Regression test for ORGANIC #665 (HIGH) — filed by the field agent
(round-4 v1.0.42 6-IC clean-room re-run, adversarial-verified).

Bug: find_local_mirror() in programs/ip_catalog_pull.py selected a bundled
IP/<category>/<core> submodule root using only ``Path.is_dir()`` — with NO
check that the directory actually contains RTL. When the bundled IP/
submodules are un-initialized (a bare directory exists but holds zero source
files), the function returned that EMPTY dir and short-circuited the working
~/ic_documents fallback that has the real RTL. Every manifest rtl_file then
landed in files_missing → status FAIL → n_ips_pulled=0, defeating the
catalog-glue path for EVERY SoC-class catalog IP (cpu/crypto/…), not one chip.

Fix: a candidate mirror dir is accepted only if it actually contains RTL
(``_dir_has_rtl``): when the manifest lists rtl_files, at least one must
resolve under the dir; otherwise the dir must contain at least one RTL source
file (``*.v`` / ``*.sv`` / ``*.vhd`` / …). An empty / un-initialized submodule
dir is skipped so the fallback chain falls through to a populated mirror.

Acceptance: an empty bundled submodule dir is rejected and the populated
            ~/ic_documents mirror is selected instead.
NO-LEAK:    a populated bundled dir is still accepted (no over-rejection),
            and the existing PASS/FAIL contracts are preserved.

Chip-AGNOSTIC: the guard is a structural file-presence / extension check —
no chip, vendor, or IP-name literal. The IP names used below are arbitrary
test fixtures, never matched against any plugin literal.
"""
from __future__ import annotations

import json
from pathlib import Path

import ip_catalog_pull as mod
from ip_catalog_query import CatalogMatch


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_ip_mirror_root(tmp_path: Path) -> Path:
    """Create a bundled IP/ mirror root laid out as IP/<category>/<core>."""
    ip_root = tmp_path / "IP"
    ip_root.mkdir()
    return ip_root


def _make_core(parent: Path, category: str, core: str,
               *rtl_files: str) -> Path:
    """Create IP/<category>/<core>/ holding the given rtl files (or empty)."""
    d = parent / category / core
    d.mkdir(parents=True, exist_ok=True)
    for rel in rtl_files:
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}\nmodule x; endmodule\n")
    return d


def _make_flat_mirror(tmp_path: Path, name: str, *rtl_files: str) -> Path:
    """Create a legacy flat ~/ic_documents-style mirror root holding <name>/."""
    root = tmp_path / "ic_documents_open_ic"
    ip_dir = root / name
    for rel in rtl_files:
        p = ip_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}\nmodule x; endmodule\n")
    if not rtl_files:
        ip_dir.mkdir(parents=True, exist_ok=True)
    (ip_dir / "LICENSE").write_text("MIT License — permissive\n")
    return root


def _match(ip_name="serv_core", license="MIT",
           rtl_files=("rtl/serv_top.v",), url=""):
    return CatalogMatch(
        ip_name=ip_name, category="cpu", version="1.0", license=license,
        canonical_url=url, canonical_commit="", matched_pattern="pat",
        confidence=0.9, manifest_path="m", rtl_files=list(rtl_files),
    )


# ===========================================================================
# ACCEPTANCE — the #665 bug: empty bundled submodule dir must be rejected,
# populated fallback mirror selected.
# ===========================================================================
def test_acceptance_empty_bundled_submodule_rejected_fallback_wins(
        tmp_path, monkeypatch):
    """The bundled IP/cpu/<core> dir is empty (un-initialized submodule);
    the populated ~/ic_documents flat mirror holds the real RTL.
    find_local_mirror must SKIP the empty dir and return the populated one."""
    ip_root = _make_ip_mirror_root(tmp_path)
    # Empty (un-initialized) bundled submodule — bare dir, zero source files.
    empty_bundled = _make_core(ip_root, "cpu", "serv")  # no rtl files
    assert empty_bundled.is_dir()
    assert not list(empty_bundled.rglob("*.v"))  # truly empty of RTL

    # Populated flat fallback mirror with the real RTL.
    flat_root = _make_flat_mirror(
        tmp_path, "serv", "rtl/serv_top.v", "rtl/serv_alu.v")

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [flat_root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {"serv_core": ["serv"]})

    sel = mod.find_local_mirror("serv_core", rtl_files=["rtl/serv_top.v"])
    assert sel is not None, "must not return None when a populated mirror exists"
    assert sel != empty_bundled, "must NOT select the empty bundled submodule"
    assert sel == flat_root / "serv", "must fall through to the populated mirror"


def test_acceptance_pull_pass_when_bundled_empty_but_flat_populated(
        tmp_path, monkeypatch):
    """End-to-end: with an empty bundled dir + populated flat mirror, the
    pull must PASS (n_ips_pulled would have been 0 before the fix)."""
    ip_root = _make_ip_mirror_root(tmp_path)
    _make_core(ip_root, "cpu", "serv")  # empty / un-initialized
    flat_root = _make_flat_mirror(tmp_path, "serv", "rtl/serv_top.v")

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [flat_root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {"serv_core": ["serv"]})

    project = tmp_path / "proj"
    project.mkdir()
    audit = mod.pull_catalog_ip(
        _match(ip_name="serv_core", rtl_files=("rtl/serv_top.v",)), project)
    assert audit["status"] == "PASS", audit
    assert audit["n_files_copied"] == 1
    assert audit["n_files_missing"] == 0
    # source_dir must be the populated flat mirror, NOT the empty bundled dir.
    assert audit["source_dir"] == str(flat_root / "serv")
    assert (project / "phase2" / "stage1" / "rtl" / "serv_top.v").is_file()


def test_acceptance_empty_dir_with_no_manifest_hint_also_rejected(
        tmp_path, monkeypatch):
    """Even without a manifest rtl_files hint, an empty bundled dir is
    rejected (extension-based emptiness check) and the populated one wins."""
    ip_root = _make_ip_mirror_root(tmp_path)
    _make_core(ip_root, "crypto", "aes")  # empty
    flat_root = _make_flat_mirror(tmp_path, "aes", "src/aes_core.v")

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [flat_root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {"aes_core": ["aes"]})

    sel = mod.find_local_mirror("aes_core")  # no rtl_files arg
    assert sel == flat_root / "aes"


# ===========================================================================
# NO-LEAK — a populated bundled dir is STILL accepted (no over-rejection).
# ===========================================================================
def test_noleak_populated_bundled_submodule_still_selected(
        tmp_path, monkeypatch):
    """When the bundled submodule IS populated, it must still win (preferred
    tier) — the guard must not over-reject a real mirror."""
    ip_root = _make_ip_mirror_root(tmp_path)
    populated_bundled = _make_core(
        ip_root, "cpu", "serv", "rtl/serv_top.v", "rtl/serv_alu.v")
    # also provide a flat mirror to prove tier preference is preserved
    flat_root = _make_flat_mirror(tmp_path, "serv", "rtl/serv_top.v")

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [flat_root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {"serv_core": ["serv"]})

    sel = mod.find_local_mirror("serv_core", rtl_files=["rtl/serv_top.v"])
    assert sel == populated_bundled, (
        "populated bundled submodule must still be selected (no over-reject)")


def test_noleak_populated_bundled_accepted_without_manifest_hint(
        tmp_path, monkeypatch):
    """A populated bundled dir is accepted even when no manifest hint is
    passed (extension-based presence check)."""
    ip_root = _make_ip_mirror_root(tmp_path)
    populated = _make_core(ip_root, "cpu", "picorv32", "picorv32.v")

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {})

    sel = mod.find_local_mirror("picorv32")  # no rtl_files
    assert sel == populated


def test_noleak_populated_bundled_accepted_when_manifest_path_differs(
        tmp_path, monkeypatch):
    """The manifest rtl_file path may not match the mirror's tree layout
    exactly; a basename rglob match still counts the dir as populated
    (same resolution pull_catalog_ip uses to copy)."""
    ip_root = _make_ip_mirror_root(tmp_path)
    # manifest says "rtl/serv_top.v" but mirror keeps it at "src/serv_top.v"
    populated = _make_core(ip_root, "cpu", "serv", "src/serv_top.v")

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {"serv_core": ["serv"]})

    sel = mod.find_local_mirror("serv_core", rtl_files=["rtl/serv_top.v"])
    assert sel == populated


def test_noleak_all_mirrors_empty_returns_none(tmp_path, monkeypatch):
    """If every candidate dir is empty/un-initialized, return None so the
    caller falls through to git clone (not a false-positive empty dir)."""
    ip_root = _make_ip_mirror_root(tmp_path)
    _make_core(ip_root, "cpu", "serv")  # empty
    flat_root = _make_flat_mirror(tmp_path, "serv")  # empty too

    monkeypatch.setattr(mod, "IP_MIRROR_ROOT", ip_root)
    monkeypatch.setattr(mod, "LOCAL_MIRROR_ROOTS", [flat_root])
    monkeypatch.setattr(mod, "LOCAL_MIRROR_MAP", {"serv_core": ["serv"]})

    sel = mod.find_local_mirror("serv_core", rtl_files=["rtl/serv_top.v"])
    assert sel is None


# ===========================================================================
# helper-level unit pins for _dir_has_rtl
# ===========================================================================
def test_dir_has_rtl_empty_dir_false(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert mod._dir_has_rtl(d) is False
    assert mod._dir_has_rtl(d, ["rtl/top.v"]) is False


def test_dir_has_rtl_with_verilog_true(tmp_path):
    d = tmp_path / "pop"
    (d / "rtl").mkdir(parents=True)
    (d / "rtl" / "top.v").write_text("module x; endmodule\n")
    assert mod._dir_has_rtl(d) is True


def test_dir_has_rtl_nonexistent_false(tmp_path):
    assert mod._dir_has_rtl(tmp_path / "does_not_exist") is False


def test_dir_has_rtl_non_rtl_files_only_false(tmp_path):
    """A dir that holds only docs/README (e.g. an un-checked-out submodule
    that left a placeholder) but no RTL source is still rejected."""
    d = tmp_path / "docsonly"
    d.mkdir()
    (d / "README.md").write_text("# placeholder\n")
    (d / "Makefile").write_text("all:\n")
    assert mod._dir_has_rtl(d) is False
