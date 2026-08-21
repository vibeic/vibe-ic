#!/usr/bin/env python3
"""Tests for mcp-eda v0.114.4 (#94 follow-up 2) — parse counts
from yosys 0.64's actual equiv_simple/equiv_induct output, not just
the equiv_status final-summary line.

Field-agent's real benchmark log showed yosys 0.64 emits:
  equiv_simple: "Proved 1760 previously unproven $equiv cells."
  equiv_induct: "Found 1 unproven $equiv cells in module equiv:"
  ERROR: No SAT model available for cell _1376__gate (INVD1).

The `equiv_status: M are proven and K are unproven` final line is NOT
emitted because equiv_induct aborts. The pre-v0.114.4 parser only
matched the final-summary line plus the optional "equiv_simple:
Proved M/N $equiv cells" form (which yosys 0.64 does NOT emit), so
parse_error=true / counts=null.

v0.114.4 adds three parsing fallbacks:
  - `Proved (\\d+) previously unproven $equiv cells` for proven
  - `Found (\\d+) unproven $equiv cells` for unproven  (NOT total)
  - `Found (\\d+) $equiv cells` (no `unproven` infix) for total
    when older yosys emits that pre-equiv_simple

Reconstruction: total = proven + unproven when the direct total line
is absent.

Anti-fabrication: still uses null/parse_error=true when NO counters
can be parsed; never -1.

chip-AGNOSTIC.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"


# Real yosys 0.64 output from field-agent's benchmark (#94 reply).
# Contains the equiv_simple proved-count + equiv_induct found-unproven
# count + a SAT-model abort. No equiv_status final-summary line.
REAL_YOSYS_064_OUTPUT = """
1. Executing Liberty frontend.
12. Executing EQUIV_SIMPLE pass.
equiv_simple: Trying ...
Proved 1760 previously unproven $equiv cells.
12. Executing EQUIV_INDUCT pass.
Found 1 unproven $equiv cells in module equiv:
ERROR: No SAT model available for cell _1376__gate (INVD1).
"""


def _parse_with_v0_114_4_logic(output: str):
    """Re-implement the v0.114.4 parser in Python so we can unit-test
    the regex sequence independently of node/docker spin-up."""
    proven = None
    unproven = None
    total = None

    m = re.search(r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven",
                  output)
    if m:
        proven = int(m.group(1))
        unproven = int(m.group(2))

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
        m = re.search(r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells",
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


def test_v0_114_4_parses_field_agent_real_output():
    proven, unproven, total, parse_error = \
        _parse_with_v0_114_4_logic(REAL_YOSYS_064_OUTPUT)
    assert proven == 1760, f"proven={proven!r}"
    assert unproven == 1, f"unproven={unproven!r}"
    assert total == 1761, f"total={total!r}"
    assert parse_error is False


def test_v0_114_4_parses_legacy_final_summary():
    """Legacy yosys path that DID emit `M are proven and K are
    unproven` final summary must still work."""
    out = (
        "Found 100 $equiv cells in module equiv\n"
        "...\n"
        "100 are proven and 0 are unproven.\n"
    )
    proven, unproven, total, parse_error = _parse_with_v0_114_4_logic(out)
    assert proven == 100
    assert unproven == 0
    assert total == 100
    assert parse_error is False


def test_v0_114_4_parses_forward_compat_slash_form():
    """Forward-compat: a future yosys that emits `equiv_simple:
    Proved M/N $equiv cells` should still work."""
    out = "equiv_simple: Proved 50/60 $equiv cells.\n"
    proven, unproven, total, parse_error = _parse_with_v0_114_4_logic(out)
    assert proven == 50
    assert total == 60
    assert unproven == 10  # reconstructed
    assert parse_error is False


def test_v0_114_4_unparseable_output_returns_null_and_flags_parse_error():
    """Yosys exited but emitted NOTHING parseable → parse_error=true,
    counts=null. NEVER -1."""
    out = "Some completely unrelated stderr blob\n"
    proven, unproven, total, parse_error = _parse_with_v0_114_4_logic(out)
    assert proven is None
    assert unproven is None
    assert total is None
    assert parse_error is True


def test_v0_114_4_proven_only_does_not_fabricate_unproven():
    """If only proven is parseable (no unproven, no total), unproven
    stays None. Anti-fabrication: never invent a number."""
    out = "Proved 5 previously unproven $equiv cells.\n"
    proven, unproven, total, parse_error = _parse_with_v0_114_4_logic(out)
    assert proven == 5
    assert unproven is None
    assert total is None
    # parse_error is False because at least proven parsed (mirrors
    # the JS implementation's `parseError = (proven===null &&
    # unproven===null)`).
    assert parse_error is False


def test_v0_114_4_source_has_three_canonical_regexes():
    """The JS source must contain all three field-agent-prescribed
    regex shapes."""
    src = INDEX_JS.read_text()
    # Strip JS comments so we test the live code
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    # Three regex shapes:
    assert "Proved\\s+(\\d+)\\s+previously\\s+unproven" in src.replace(
        "\\\\", "\\")
    assert "Found\\s+(\\d+)\\s+unproven\\s+\\$equiv\\s+cells" in src.replace(
        "\\\\", "\\") or "Found\\s+(\\d+)\\s+unproven" in src
    assert "Found\\s+(\\d+)\\s+\\$equiv\\s+cells" in src.replace(
        "\\\\", "\\")


def test_v0_114_4_server_version_canonicalised():
    """SERVER_VERSION is canonicalised to the unified package.json version.

    v0.1.4 unified the scheme (was a 0.114.x runtime constant vs a 0.1.x
    package). The meaningful invariant is now equality with package.json, not a
    numeric floor — the yosys-0.64 parser feature itself is guarded by the
    parsing tests above, independent of the version string."""
    import json
    src = INDEX_JS.read_text()
    m = re.search(r'const SERVER_VERSION = "([^"]+)"', src)
    assert m
    pkg_version = json.loads((MCP_ROOT / "package.json").read_text())["version"]
    assert m.group(1) == pkg_version, (
        f"SERVER_VERSION {m.group(1)!r} must equal package.json {pkg_version!r} "
        f"(unified version scheme since v0.1.4)")
