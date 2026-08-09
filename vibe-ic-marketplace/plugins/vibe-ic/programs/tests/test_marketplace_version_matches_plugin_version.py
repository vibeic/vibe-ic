"""The version users can INSTALL must equal the version we shipped.

`plugin.json` is what the plugin says it is. `marketplace.json` is what the
`claude plugin` CLI reads to decide whether an update exists. Only the second
one governs distribution.

WHAT HAPPENED. Ten consecutive releases (1.10.19 .. 1.10.28) bumped
`plugin.json` and left BOTH `marketplace.json` files at 1.10.18. Every one of
those releases was announced as landed, and `claude plugin update` would have
answered "already up to date" on every machine. The fixes existed on main and
could reach nobody.

This is the defect class the 1.10.2x series was closing, committed by the
release process itself: a number was bumped, and it was not the number that
decides anything. The check that would have caught it did not exist, so ten
releases in a row reported success against a proxy for shipping rather than
shipping.

DEFECT DIRECTION: set either marketplace.json's vibe-ic version to any value
other than plugin.json's and `test_every_marketplace_declares_the_plugin_version`
FAILS. That is the mutation that proves this file can fail.

Chip-AGNOSTIC: reads three JSON files in this repo. No design, PDK, vendor or
project name is involved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# programs/tests/ -> programs/ -> vibe-ic/ -> plugins/ -> vibe-ic-marketplace/ -> repo root
PLUGIN_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_DIR.parents[2]

PLUGIN_JSON = PLUGIN_DIR / ".claude-plugin" / "plugin.json"


def _marketplace_files() -> list[Path]:
    """Every marketplace manifest in the repo -- discovered, not enumerated.

    A hard-coded list is how the second manifest gets forgotten: there are two,
    and updating only the one you remember reproduces the original defect.
    """
    return sorted(REPO_ROOT.glob("**/.claude-plugin/marketplace.json"))


def _declared_version(marketplace: Path) -> str | None:
    data = json.loads(marketplace.read_text())
    for entry in data.get("plugins", []):
        if entry.get("name") == "vibe-ic":
            return entry.get("version")
    return None


def test_plugin_json_declares_a_version():
    v = json.loads(PLUGIN_JSON.read_text()).get("version")
    assert v, f"{PLUGIN_JSON} declares no version"


def test_at_least_one_marketplace_manifest_exists():
    """Guards the guard: if the glob stops matching, every assertion below
    passes vacuously and this file becomes a check that cannot fail."""
    found = _marketplace_files()
    assert found, "no marketplace.json found -- this test would pass vacuously"


def test_every_marketplace_declares_the_plugin_version():
    """THE defect: the installable version must equal the shipped version."""
    shipped = json.loads(PLUGIN_JSON.read_text())["version"]
    mismatches = []
    for m in _marketplace_files():
        declared = _declared_version(m)
        if declared != shipped:
            mismatches.append(
                f"{m.relative_to(REPO_ROOT)} declares {declared!r}, "
                f"plugin.json ships {shipped!r}")
    assert not mismatches, (
        "marketplace manifest(s) out of sync with plugin.json -- users would "
        "install an older version than the one on main:\n  "
        + "\n  ".join(mismatches))


def test_every_marketplace_entry_points_at_a_real_source():
    """A manifest can also lie by naming a source path that does not exist;
    the version would be right and the install still broken."""
    for m in _marketplace_files():
        data = json.loads(m.read_text())
        for entry in data.get("plugins", []):
            src = entry.get("source")
            if not src or not src.startswith("./"):
                continue
            target = (m.parent.parent / src[2:]).resolve()
            assert target.is_dir(), (
                f"{m.relative_to(REPO_ROOT)} entry {entry.get('name')!r} "
                f"points at {src}, which is not a directory")


@pytest.mark.parametrize("part", ["major", "minor", "patch"])
def test_shipped_version_is_a_three_part_number(part):
    """A version the CLI cannot order is a version it cannot see as newer."""
    v = json.loads(PLUGIN_JSON.read_text())["version"]
    parts = v.split(".")
    assert len(parts) == 3, f"version {v!r} is not major.minor.patch"
    idx = {"major": 0, "minor": 1, "patch": 2}[part]
    assert parts[idx].isdigit(), f"version {v!r} has a non-numeric {part}"
