#!/usr/bin/env python3
"""ORGANIC #665 ROUND-2 — `find_local_mirror`'s `~`-rooted home fallback was
UNREACHABLE because the candidate path was built without `.expanduser()`.

Field-agent reopen (round-4, v1.0.44 ae175d95): the round-1 `_dir_has_rtl()`
content gate WORKS — it correctly rejects an empty / un-initialized bundled
submodule dir. But the load-bearing OTHER half was missing: `LOCAL_MIRROR_ROOTS`
are literal `~`-prefixed `Path` objects (`Path("~/ic_documents/open_ic")`), and
the fallback loop built `p = root / name` with NO `.expanduser()`, so
`Path('~/ic_documents/open_ic/serv').is_dir()` is ALWAYS False (literal `~`
never resolves). The promised populated fall-through target was therefore
unreachable and end-to-end `pull_catalog_ip` still returned
`status=FAIL, source_dir=None, n_files_copied=0` — observably identical to
before (only the reason string changed).

ROUND-2 FIX (one line, chip-AGNOSTIC): `p = (root / name).expanduser()`.

ACCEPTANCE (reopen repro): with the bundled mirror empty/absent and a POPULATED
`~/ic_documents/open_ic/<core>` home mirror present, `find_local_mirror` returns
the EXPANDED populated dir (a real on-disk dir, no literal `~`), and end-to-end
`pull_catalog_ip` reaches it → status != FAIL, source_dir != None.

NEGATIVE no-leak (§4.05): the round-1 content gate is PRESERVED — a home dir
that exists but holds NO RTL is still rejected (returns None); an empty bundled
dir is never selected. The relaxation (expand `~`) only makes a *populated*
mirror reachable; it never makes an *empty* one acceptable.

chip-AGNOSTIC: a `~`-expansion of a structural mirror-root path; no chip /
vendor / SKU / IP-name literal.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import ip_catalog_pull as P  # noqa: E402
from ip_catalog_query import CatalogMatch  # noqa: E402


# A leaf name that is NOT in LOCAL_MIRROR_MAP and NOT in the bundled IP/ mirror,
# so resolution is forced down the `~/ic_documents` fallback loop under test.
_CORE = "zzz_core_issue665_r2"


def _populate_home_mirror(home: Path, core: str = _CORE) -> Path:
    """Create a POPULATED `~/ic_documents/open_ic/<core>` mirror (with RTL) and
    return its (unexpanded-shape) absolute path on disk."""
    d = home / "ic_documents" / "open_ic" / core
    (d / "rtl").mkdir(parents=True)
    (d / "rtl" / f"{core}_alu.v").write_text(
        f"module {core}_alu(input a, output y); assign y=a; endmodule\n")
    return d


def test_find_local_mirror_expands_user_home(tmp_path, monkeypatch):
    """The reopen repro, isolated to the unit under test: with HOME pointed at a
    tmp dir holding a POPULATED `ic_documents/open_ic/<core>` mirror,
    `find_local_mirror` returns the EXPANDED real dir — not None."""
    home = tmp_path / "home"
    populated = _populate_home_mirror(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(P, "IP_MIRROR_ROOT", tmp_path / "no_such_IP_root")

    got = P.find_local_mirror(_CORE)
    assert got is not None, "home fallback must be reachable after expanduser"
    assert got.is_dir(), "returned mirror must be a real on-disk dir"
    assert "~" not in str(got), f"path must be expanded, not literal ~: {got}"
    assert got.resolve() == populated.resolve(), got


def test_unexpanded_literal_tilde_is_unreachable_REGRESSION(tmp_path,
                                                            monkeypatch):
    """Pin the load-bearing nature of the fix: the OLD code path
    (`root / name`, no expanduser) is provably unreachable — `Path('~/...').
    is_dir()` is False even though the populated dir exists — yet the FIXED
    `find_local_mirror` still locates it. If a future edit drops `.expanduser()`
    this test fails."""
    home = tmp_path / "home"
    _populate_home_mirror(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(P, "IP_MIRROR_ROOT", tmp_path / "no_such_IP_root")

    literal = P.LOCAL_MIRROR_ROOTS[0] / _CORE          # Path("~/ic_documents/...")
    assert str(literal).startswith("~"), literal
    assert not literal.is_dir(), "literal ~ must never resolve (the old bug)"
    assert P.find_local_mirror(_CORE) is not None


def test_empty_home_dir_is_rejected_NOLEAK(tmp_path, monkeypatch):
    """NEGATIVE no-leak: a `~/ic_documents/open_ic/<core>` dir that EXISTS but
    holds NO RTL is still rejected (round-1 content gate preserved). Expanding
    `~` must not make an EMPTY mirror acceptable."""
    home = tmp_path / "home"
    empty = home / "ic_documents" / "open_ic" / _CORE
    empty.mkdir(parents=True)            # exists, expands, but has ZERO RTL
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(P, "IP_MIRROR_ROOT", tmp_path / "no_such_IP_root")

    assert P.find_local_mirror(_CORE) is None, \
        "an empty (no-RTL) home mirror must NOT be selected — leak guard"


def test_rtl_files_hint_resolves_under_expanded_home(tmp_path, monkeypatch):
    """When the manifest lists rtl_files, the expanded home mirror is accepted
    only when at least one resolves under it (the same resolution pull uses)."""
    home = tmp_path / "home"
    _populate_home_mirror(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(P, "IP_MIRROR_ROOT", tmp_path / "no_such_IP_root")

    got = P.find_local_mirror(_CORE, rtl_files=[f"src/{_CORE}_alu.v"])
    assert got is not None and got.is_dir()
    assert P.find_local_mirror(_CORE, rtl_files=["src/not_present.v"]) is None


def test_end_to_end_pull_reaches_expanded_mirror(tmp_path, monkeypatch):
    """ORGANIC #665 round-2 end-state — the reopen's end-to-end repro: drive the
    REAL `pull_catalog_ip` with the bundled mirror absent and a populated home
    mirror present; assert status != FAIL and source_dir is the EXPANDED real
    path (before the fix this returned status=FAIL / source_dir=None)."""
    home = tmp_path / "home"
    populated = _populate_home_mirror(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(P, "IP_MIRROR_ROOT", tmp_path / "no_such_IP_root")

    match = CatalogMatch(
        ip_name=_CORE, category="cpu", version="1.0", license="Apache-2.0",
        canonical_url="", canonical_commit="", matched_pattern="test",
        confidence=1.0, manifest_path="", rtl_files=[f"rtl/{_CORE}_alu.v"])
    proj = tmp_path / "proj"
    proj.mkdir()
    audit = P.pull_catalog_ip(match, proj)

    assert audit["status"] != "FAIL", audit
    assert audit.get("source_dir"), "source_dir must be set, not None"
    assert "~" not in audit["source_dir"], audit["source_dir"]
    assert Path(audit["source_dir"]).resolve() == populated.resolve()
    assert audit["n_files_copied"] >= 1, audit


def test_real_serv_home_mirror_if_present():
    """If the real `~/ic_documents/open_ic/serv` mirror is on this host (the
    artifact the reopen cited: 75 `.v`, has `rtl/serv_alu.v`), confirm the
    expanded fallback reaches it. SKIPs cleanly off-host."""
    serv = (Path("~/ic_documents/open_ic") / "serv").expanduser()
    if not (serv.is_dir() and any(serv.rglob("*.v"))):
        pytest.skip("real ~/ic_documents/open_ic/serv mirror not on this host")
    got = P.find_local_mirror("serv")
    assert got is not None and got.is_dir(), got
    assert "~" not in str(got), got


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
