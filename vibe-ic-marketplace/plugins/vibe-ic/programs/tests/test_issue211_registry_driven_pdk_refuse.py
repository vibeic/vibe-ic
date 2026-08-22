"""issue #211 — registry-driven PDK resolution must RESOLVE a declared PDK to
its OWN assets and REFUSE (never silently substitute / never return garbage)
when a declared PDK's assets cannot be resolved.

These are UNIT tests: `_docker_exec_raw` is mocked with an in-memory container
so they run WITHOUT docker and WITHOUT any particular PDK being installed — the
behaviour under test is the resolver's LOGIC, not what a given image ships.

Two defects are pinned here (both reproduced live on 2026-07-22 before the fix):

  * B  — `_registry_glob_one` took `ls`'s FIRST stdout line as a path. The
         vibeic-eda container is entered through a LOGIN shell whose profile
         prints a banner ("[INFO] Final PATH variable: …") to STDOUT ahead of
         the command output; when a wildcard glob matched NOTHING that banner
         was the only line, so the resolver returned the banner string as the
         "liberty"/"LEF" path and `_pdk_config_from_registry` built a config
         whose assets were literally "[INFO] Final PATH variable: …". Measured:
         `_detect_pdk(override="gf180mcuD")` returned such a garbage config
         instead of refusing. The guard now accepts a candidate only when it
         sits under the PDK root AND actually exists.

  * A  — the resolve/refuse contract for a registry-declared-but-unbranched
         PDK: it resolves to that PDK's own assets when present, and raises
         SystemExit (refuse) when they are not — it NEVER falls back to sky130A.

chip/PDK-AGNOSTIC: no chip/SKU literal; the fake container is driven from the
registry entry itself.
"""
import fnmatch
import shlex
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# The real vibeic-eda login-shell banner shape (two [INFO] lines on STDOUT).
_BANNER = (
    "[INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin:"
    "/usr/bin:/bin\n"
    "[INFO] Final PYTHONPATH variable: /usr/lib/python3.12"
)


def _unquote(s: str) -> str:
    try:
        parts = shlex.split(s)
        return parts[0] if parts else s
    except ValueError:
        return s


class _FakeContainer:
    """An in-memory container whose every `bash -lc` invocation prints the
    login banner to STDOUT first (exactly as vibeic-eda does), then answers
    `test -d` / `test -e` / `ls -1d <glob> … | sort` from a fixed path set."""

    def __init__(self, existing):
        self.existing = set(existing)
        self.calls = []

    def __call__(self, container, cmd, timeout=1800):
        self.calls.append(cmd)
        c = cmd.strip()
        if c.startswith("test -d "):
            path = _unquote(c[len("test -d "):].strip())
            ok = path in self.existing
            return (0 if ok else 1, _BANNER + "\n", "")
        if c.startswith("test -e "):
            path = _unquote(c[len("test -e "):].strip())
            ok = path in self.existing
            return (0 if ok else 1, _BANNER + "\n", "")
        if c.startswith("ls -1d "):
            glob = c[len("ls -1d "):].split(" 2>/dev/null")[0].strip()
            hits = sorted(p for p in self.existing if fnmatch.fnmatch(p, glob))
            out = _BANNER + "\n" + ("\n".join(hits) + "\n" if hits else "")
            return (0, out, "")
        # any other probe: just the banner (rc 0)
        return (0, _BANNER + "\n", "")


def _asset_paths(entry, keys):
    """Absolute in-container paths for the EXACT-path globs of a registry
    entry (used to populate the fake container's existing-file set)."""
    root = entry["container_path"].rstrip("/")
    out = []
    for k in keys:
        v = entry.get(k)
        if v and not any(ch in v for ch in "*?["):
            out.append(f"{root}/{v}")
    return out


# ---------------------------------------------------------------------------
# B — the resolver's core guard, unit-tested directly.
# ---------------------------------------------------------------------------
def test_glob_one_drops_login_banner_when_nothing_matches(monkeypatch):
    """RED before the fix: a wildcard glob that matches nothing returns the
    login-shell banner as if it were a path. GREEN: it returns None."""
    fake = _FakeContainer(existing={"/foss/pdks/x"})  # dir only, no assets
    monkeypatch.setattr(R, "_docker_exec_raw", fake)
    got = R._registry_glob_one("c", "/foss/pdks/x", "libs.ref/scl/lib/*tt*.lib")
    assert got is None, f"banner leaked as a path: {got!r}"


def test_glob_one_returns_real_wildcard_match(monkeypatch):
    """A wildcard that DOES match a real file resolves to it (banner ignored)."""
    real = "/foss/pdks/x/libs.ref/scl/lib/scl__tt_025C_1v80.lib"
    fake = _FakeContainer(existing={"/foss/pdks/x", real})
    monkeypatch.setattr(R, "_docker_exec_raw", fake)
    got = R._registry_glob_one("c", "/foss/pdks/x", "libs.ref/scl/lib/*tt*.lib")
    assert got == real


def test_glob_one_returns_real_exact_path(monkeypatch):
    """A non-wildcard glob resolves via `test -e` and returns the exact path."""
    real = "/foss/pdks/x/libs.ref/scl/lef/scl.lef"
    fake = _FakeContainer(existing={"/foss/pdks/x", real})
    monkeypatch.setattr(R, "_docker_exec_raw", fake)
    got = R._registry_glob_one("c", "/foss/pdks/x", "libs.ref/scl/lef/scl.lef")
    assert got == real


def test_glob_one_exact_path_absent_is_none(monkeypatch):
    """A non-wildcard glob whose target does not exist resolves to None (the
    banner rc is ignored — only the test -e result counts)."""
    fake = _FakeContainer(existing={"/foss/pdks/x"})
    monkeypatch.setattr(R, "_docker_exec_raw", fake)
    got = R._registry_glob_one("c", "/foss/pdks/x", "libs.ref/scl/lef/scl.lef")
    assert got is None


# ---------------------------------------------------------------------------
# A — resolve a declared PDK to its OWN assets (GREEN case).
# ---------------------------------------------------------------------------
def test_detect_pdk_resolves_declared_pdk_to_its_own_assets(
        tmp_path, monkeypatch):
    """A registry-declared PDK whose assets are present resolves to a config
    that points at THAT PDK's own files — never sky130's."""
    entry = R._pdk_registry_entry("ihp-sg13g2")
    assert entry is not None
    root = entry["container_path"].rstrip("/")
    existing = {root}
    existing.update(_asset_paths(
        entry, ("liberty_glob", "tech_lef_glob", "cell_lef_glob",
                "cell_gds_glob", "drc_deck", "lefdef_layermap",
                "pnr_exclude_cell_file")))
    fake = _FakeContainer(existing=existing)
    monkeypatch.setattr(R, "_docker_exec_raw", fake)

    cfg = R._detect_pdk(tmp_path, override="ihp-sg13g2")
    assert cfg is not None
    assert cfg.name == "ihp-sg13g2"
    for p in (cfg.liberty, cfg.tech_lef, cfg.cell_lef):
        assert p and p.startswith(root + "/"), f"asset not under PDK root: {p!r}"
        assert "sky130" not in p
    # SITE + metal_prefix come from the registry, not inherited from sky130.
    assert cfg.site == entry["site"]
    assert cfg.metal_prefix == entry["metal_prefix"]


# ---------------------------------------------------------------------------
# A — refuse a declared PDK whose assets cannot be resolved (never garbage,
#     never a silent sky130A substitution).
# ---------------------------------------------------------------------------
def test_detect_pdk_refuses_when_declared_assets_absent(tmp_path, monkeypatch):
    """The container exists and the PDK dir exists, but a wildcard asset glob
    matches nothing (only the banner). Pre-fix this returned a config whose
    liberty was the banner string; now it must raise SystemExit — and the
    message must NOT offer a sky130A substitution as an outcome."""
    entry = R._pdk_registry_entry("gf180mcuD")
    assert entry is not None
    root = entry["container_path"].rstrip("/")
    # ONLY the PDK directory exists; none of the asset globs match.
    fake = _FakeContainer(existing={root})
    monkeypatch.setattr(R, "_docker_exec_raw", fake)

    with pytest.raises(SystemExit) as ei:
        R._detect_pdk(tmp_path, override="gf180mcuD")
    msg = str(ei.value)
    assert "gf180mcuD" in msg
    assert "REFUS" in msg.upper()


def test_pdk_config_from_registry_none_when_liberty_unresolved(
        tmp_path, monkeypatch):
    """The lower layer: when the mandatory liberty asset cannot be resolved,
    `_pdk_config_from_registry` returns None (so the caller refuses) rather
    than building a config from a garbage path."""
    entry = R._pdk_registry_entry("gf180mcuD")
    root = entry["container_path"].rstrip("/")
    fake = _FakeContainer(existing={root})  # dir present, no assets
    monkeypatch.setattr(R, "_docker_exec_raw", fake)
    cfg = R._pdk_config_from_registry(tmp_path, entry)
    assert cfg is None
