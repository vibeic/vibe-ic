#!/usr/bin/env python3
"""Tests for mcp-eda v0.114.5 (#94 follow-up 3) — distinguish
yosys's TWO "Found N unproven $equiv cells" lines.

Field-agent's v0.114.4 verification found that the full yosys 0.64
output contains BOTH:

  equiv_simple ENTRY:
    "Found 1761 unproven $equiv cells (1761 groups) in equiv:"
    (1761 = initial total)

  equiv_induct RESIDUAL (post-equiv_simple):
    "Found 1 unproven $equiv cells in module equiv:"
    (1 = still-unproven after equiv_simple)

v0.114.4's unanchored regex `Found\\s+(\\d+)\\s+unproven\\s+\\$equiv\\s+cells`
matched the FIRST hit (equiv_simple entry) → bound
unproven = 1761 (wrong), then reconstruction computed
total = 1760 + 1761 = 3521 (wrong).

Fix in v0.114.5:
  - unproven regex anchored on ` in module equiv:` suffix
    (equiv_induct residual ONLY)
  - new total regex anchored on `(N groups) in equiv:`
    (equiv_simple entry ONLY)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"


# Full yosys 0.64 output (BOTH `Found ... unproven $equiv cells` lines).
FULL_YOSYS_064_OUTPUT = """
1. Executing Liberty frontend.
12. Executing EQUIV_SIMPLE pass.
Found 1761 unproven $equiv cells (1761 groups) in equiv:
equiv_simple: Trying ...
Proved 1760 previously unproven $equiv cells.
12. Executing EQUIV_INDUCT pass.
Found 1 unproven $equiv cells in module equiv:
ERROR: No SAT model available for cell _1376__gate (INVD1).
"""


def _parse_v0_114_5(output: str):
    """Replicate the v0.114.5 parser sequence in Python."""
    proven = None
    unproven = None
    total = None

    m = re.search(r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven",
                  output)
    if m:
        proven = int(m.group(1))
        unproven = int(m.group(2))

    # equiv_simple entry — direct total
    m = re.search(
        r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)\s+in\s+equiv\s*:",
        output)
    if m:
        total = int(m.group(1))

    if total is None:
        m = re.search(r"Found\s+(\d+)\s+\$equiv\s+cells", output)
        if m:
            total = int(m.group(1))

    if proven is None:
        m = re.search(
            r"Proved\s+(\d+)\s+previously\s+unproven\s+\$equiv\s+cells",
            output)
        if m:
            proven = int(m.group(1))

    if proven is None or total is None:
        m = re.search(
            r"equiv_simple[^\n]*Proved\s+(\d+)/(\d+)\s+\$equiv\s+cells",
            output)
        if m:
            if proven is None:
                proven = int(m.group(1))
            if total is None:
                total = int(m.group(2))

    if unproven is None:
        # ANCHORED: only equiv_induct's residual line
        m = re.search(
            r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+in\s+module\s+equiv\s*:",
            output)
        if m:
            unproven = int(m.group(1))

    if total is None and proven is not None and unproven is not None:
        total = proven + unproven
    if total is not None and proven is not None and unproven is None:
        unproven = total - proven
    if total is not None and unproven is not None and proven is None:
        proven = total - unproven

    parse_error = (proven is None and unproven is None)
    return proven, unproven, total, parse_error


def test_v0_114_5_full_output_yields_canonical_triple():
    """Field-agent's full transcript yields (1760, 1, 1761)."""
    proven, unproven, total, parse_error = _parse_v0_114_5(
        FULL_YOSYS_064_OUTPUT)
    assert proven == 1760, f"proven={proven!r}"
    assert unproven == 1, f"unproven={unproven!r}"
    assert total == 1761, f"total={total!r}"
    assert parse_error is False


def test_v0_114_5_anchored_unproven_regex_skips_equiv_simple_entry():
    """The unproven regex must NOT match equiv_simple's entry line
    (which has `(N groups) in equiv:` suffix, not `in module
    equiv:`)."""
    only_entry = (
        "Found 1761 unproven $equiv cells (1761 groups) in equiv:\n"
    )
    # Anchored regex should fail to match
    m = re.search(
        r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+in\s+module\s+equiv\s*:",
        only_entry)
    assert m is None, (
        "anchored unproven regex must not match equiv_simple entry line; "
        f"got {m.group(0)!r}")


def test_v0_114_5_anchored_total_regex_skips_equiv_induct_residual():
    """The total regex must NOT match equiv_induct's residual line
    (which has `in module equiv:` suffix, not `(N groups) in equiv:`)."""
    only_residual = "Found 1 unproven $equiv cells in module equiv:\n"
    m = re.search(
        r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)\s+in\s+equiv\s*:",
        only_residual)
    assert m is None, (
        "total regex must not match equiv_induct residual line; "
        f"got {m.group(0)!r}")


def test_v0_114_5_total_regex_matches_equiv_simple_entry():
    only_entry = "Found 1761 unproven $equiv cells (1761 groups) in equiv:\n"
    m = re.search(
        r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)\s+in\s+equiv\s*:",
        only_entry)
    assert m is not None
    assert m.group(1) == "1761"


def test_v0_114_5_unproven_regex_matches_equiv_induct_residual():
    only_residual = "Found 1 unproven $equiv cells in module equiv:\n"
    m = re.search(
        r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+in\s+module\s+equiv\s*:",
        only_residual)
    assert m is not None
    assert m.group(1) == "1"


def test_v0_114_5_legacy_old_total_regex_still_matches_old_yosys():
    """Older yosys without the `unproven` infix in either line: the
    `Found N $equiv cells` fallback still picks up the total."""
    legacy = (
        "Found 100 $equiv cells in module equiv\n"
        "...\n"
        "100 are proven and 0 are unproven\n"
    )
    proven, unproven, total, parse_error = _parse_v0_114_5(legacy)
    assert total == 100
    assert proven == 100
    assert unproven == 0


def test_v0_114_5_source_has_both_anchored_regexes():
    src = INDEX_JS.read_text()
    # Strip JS comments
    body = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    # equiv_simple entry total regex
    assert "\\(\\d+\\s+groups\\)" in body, (
        "equiv_simple entry-line total regex must be present "
        "(matches `(N groups) in equiv:` suffix)")
    # equiv_induct residual unproven regex
    assert "in\\s+module\\s+equiv" in body, (
        "equiv_induct residual unproven regex must be anchored on "
        "`in module equiv:` suffix")


def test_v0_114_5_server_version_canonicalised():
    # v0.1.4 unified the version scheme: the old 0.114.x numeric floor is
    # obsolete. The disambiguation feature is guarded by the regex tests above;
    # here we assert SERVER_VERSION equals the unified package.json version.
    import json
    src = INDEX_JS.read_text()
    m = re.search(r'const SERVER_VERSION = "([^"]+)"', src)
    assert m
    pkg_version = json.loads((MCP_ROOT / "package.json").read_text())["version"]
    assert m.group(1) == pkg_version, (
        f"SERVER_VERSION {m.group(1)!r} must equal package.json {pkg_version!r} "
        f"(unified version scheme since v0.1.4)")
