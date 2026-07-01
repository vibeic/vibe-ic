#!/usr/bin/env python3
"""v1.2.75 (TAPEOUT-SIGNOFF P0#1) — the MCP `eda_drc_klayout` gf180/sky130 branch
must NOT be a vacuous no-op.

The tapeout-signoff survey found this branch was a false-DRC-clean surface: it read
the GDS, checked a top cell exists, printed `DRC_COMPLETE=YES`, ran ZERO rules, and
returned `success`. Any caller running `eda_drc_klayout` on a foundry PDK got a
false pass. The fix runs the PDK's OWN KLayout sign-off deck (`sky130A.lydrc` /
`gf180mcuD.lydrc`), counts real `<item>` violations, and returns an HONEST FAILURE
when no deck / no report is produced — it never emits a vacuous PASS.

Source-scan guard (mirrors the other index.js source-pin tests): the MCP is an
optional sibling of the plugin, so this SKIPS when index.js is absent (CI runner)
rather than erroring.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _find_mcp_src() -> Path:
    for anc in Path(__file__).resolve().parents:
        cand = anc / "mcp-eda" / "src" / "index.js"
        if cand.is_file():
            return cand
    return Path("mcp-eda/src/index.js")  # sentinel; skip below


MCP_SRC = _find_mcp_src()
pytestmark = pytest.mark.skipif(
    not MCP_SRC.is_file(), reason="mcp-eda/src/index.js not present (optional sibling)")


def _drc_tool_region() -> str:
    """The eda_drc_klayout handler body (from its server.tool registration to the
    next tool registration)."""
    src = MCP_SRC.read_text(errors="ignore")
    start = src.index('"eda_drc_klayout"')
    # end at the next `server.tool(` after the DRC tool
    end = src.index("server.tool(", start + 1)
    return src[start:end]


def test_no_vacuous_drc_complete_pass():
    """The old false-PASS token `DRC_COMPLETE=YES` must not drive `success` — it
    may survive only inside an explanatory comment, never as executable logic."""
    region = _drc_tool_region()
    # No `success: ...DRC_COMPLETE=YES...` construction anywhere.
    assert "output.includes(\"DRC_COMPLETE=YES\")" not in region
    # The only permitted occurrences are in comment lines (start with `//`).
    for line in region.splitlines():
        if "DRC_COMPLETE=YES" in line:
            assert line.lstrip().startswith("//"), (
                f"DRC_COMPLETE=YES appears in executable code: {line!r}")


def test_gf180_sky130_branch_runs_the_real_deck():
    """The branch must discover + run the PDK's own *.lydrc sign-off deck with the
    canonical `-rd input=/-rd report=/-rd top_cell=` invocation (the same shape the
    phase3 runner's step_drc uses)."""
    region = _drc_tool_region()
    assert "libs.tech/klayout/drc" in region        # discovers the PDK deck dir
    assert ".lydrc" in region                        # a real sign-off deck
    assert "-rd input=" in region and "-rd report=" in region
    assert "-rd top_cell=" in region


def test_honest_fail_when_no_deck_and_report_checked():
    """No deck ⇒ honest failure (never a vacuous PASS); and PASS requires the
    report file to actually exist (a crashed klayout writes no report, and a bare
    `grep -c` on a missing file echoes 0 — that must not read as clean)."""
    region = _drc_tool_region()
    assert "NOT emit a vacuous PASS" in region       # explicit honest-fail path
    assert "reportExists" in region                  # report-existence gate
    # PASS is the AND of: klayout ran, report written, zero violations.
    assert "result.success && reportExists && viol === 0" in region
