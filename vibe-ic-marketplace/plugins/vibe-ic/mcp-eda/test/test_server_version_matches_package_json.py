#!/usr/bin/env python3
"""Tests for mcp-eda v0.114.3 (#94 follow-up) — the inline
``SERVER_VERSION`` constant in ``src/index.js`` MUST match
``package.json``'s ``version`` field.

Pre-fix the two values drifted: package.json was 0.114.x but the
runtime constant stayed pinned at "0.28.0". Field-agents calling the
running MCP server saw ``tool_version: "...@0.28.0"`` regardless of
which handler patches had actually been applied to the on-disk
``index.js``, making it impossible to tell at runtime whether the
process had been restarted to load the latest patches.

After v0.114.3 the two values are co-bumped. This test makes the
invariant load-bearing so a future bump that only touches one side
trips a regression.

chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import pytest

MCP_ROOT = Path(__file__).resolve().parent.parent


def test_server_version_matches_package_json():
    # v0.1.4: the version scheme was unified — SERVER_VERSION, package.json, and
    # the plugin all carry the same 0.1.x string, so this invariant is now
    # load-bearing (the prior xfail covered the 0.114.x↔0.1.x drift, now closed).
    pkg = json.loads((MCP_ROOT / "package.json").read_text())
    pkg_version = pkg.get("version")
    assert pkg_version, "package.json lacks `version` field"

    src = (MCP_ROOT / "src" / "index.js").read_text()
    m = re.search(r'^const\s+SERVER_VERSION\s*=\s*"([^"]+)"\s*;',
                  src, re.MULTILINE)
    assert m, "SERVER_VERSION constant not found in index.js"
    runtime_version = m.group(1)

    assert runtime_version == pkg_version, (
        f"SERVER_VERSION drift: index.js says {runtime_version!r} but "
        f"package.json says {pkg_version!r}. Co-bump per v0.114.3 "
        f"(#94 follow-up) — both must change together so runtime "
        f"tool_version strings let field-agents distinguish patched "
        f"from unpatched handlers.")


def test_pre_v0_114_3_pinned_0_28_0_constant_is_gone():
    """Guard against accidental revert to the stale 0.28.0 value."""
    src = (MCP_ROOT / "src" / "index.js").read_text()
    # Strip comments so the historical note is allowed to mention 0.28.0
    stripped = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    assert 'SERVER_VERSION = "0.28.0"' not in stripped, (
        "the stale 0.28.0 SERVER_VERSION must not be reintroduced — "
        "package.json drifted past it during the v0.108..v0.114 "
        "feature waves; v0.114.3 re-anchored the live constant.")
