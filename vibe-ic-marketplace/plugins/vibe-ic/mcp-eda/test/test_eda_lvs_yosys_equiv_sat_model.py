#!/usr/bin/env python3
"""Tests for mcp-eda v0.114.2 (#94) — eda_lvs mode=yosys_equiv
emits a STRUCTURED verdict when equiv_induct's SAT engine aborts on
custom-PDK Liberty primitives without built-in SAT models.

Pre-fix the script ran `equiv_status -assert`; yosys exited non-zero
on the SAT-model abort, the parser hit the `finalMatch === null`
branch, and the response was {matched: false, equiv_cells_unproven:
-1} — indistinguishable from a real LVS mismatch.

Fix replaces `-assert` with plain `equiv_status` and parses:
  - "M are proven and K are unproven" — final summary
  - "Found N $equiv cells in module equiv" — total
  - equiv_simple "Proved M/N $equiv cells" — fallback when
    equiv_induct aborts before equiv_status
  - "ERROR: No SAT model available for cell <inst> (<cell_type>)" —
    every match captured

Structured response fields (#94 contract):
  - matched: bool
  - equiv_cells_total, equiv_cells_proven, equiv_cells_unproven (no -1)
  - sat_model_unsupported_cells: [{cell, cell_type}]
  - unproven_cells: [<path>, ...]
  - parse_error: bool
  - verdict_explanation: string

chip-AGNOSTIC: parsing operates on yosys output text, no chip-class
identifiers anywhere.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
import pytest

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
assert INDEX_JS.is_file(), f"missing {INDEX_JS}"


def _extract_lvs_block(src: str) -> str:
    """Return the body of the eda_lvs tool registration."""
    m = re.search(
        r'server\.tool\(\s*"eda_lvs".*?^\);',
        src, re.DOTALL | re.MULTILINE,
    )
    assert m, "eda_lvs tool registration not found in index.js"
    return m.group(0)


def _strip_js_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def test_v0_114_2_dropped_equiv_status_assert():
    """The pre-v2.6.0 `equiv_status -assert` line must NOT appear in
    the eda_lvs yosys_equiv branch — it caused exit-code aborts that
    masked the SAT-model gap. Plain `equiv_status` is now used."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    # The yosys_equiv branch must use plain equiv_status (no -assert)
    # so we can parse the counts even when SAT engine aborts.
    yosys_equiv_idx = block.find('mode === "yosys_equiv"')
    netgen_idx = block.find("Legacy netgen mode")
    yosys_equiv_block = _strip_js_comments(block[yosys_equiv_idx:netgen_idx])
    assert "equiv_status -assert" not in yosys_equiv_block, (
        "since v2.6.0 dropped `equiv_status -assert` from yosys_equiv mode")
    assert "equiv_status" in yosys_equiv_block, (
        "plain `equiv_status` must remain to emit final counts")


def test_v0_114_2_emits_structured_verdict_fields():
    """The response wrapper must surface the new structured fields."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    for field in (
        "sat_model_unsupported_cells",
        "unproven_cells",
        "parse_error",
        "verdict_explanation",
        "equiv_cells_total",
        "equiv_cells_proven",
        "equiv_cells_unproven",
    ):
        assert field in block, f"since v2.6.0 field {field!r} missing"


def test_v0_114_2_no_minus_one_sentinel_for_unproven():
    """The ambiguous `unproven: -1` sentinel must be gone — when
    parsing fails, the response uses `null` + parse_error=true."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    # The pre-fix code had `parseInt(finalMatch[2]) : -1` returning
    # -1 when finalMatch was null. The fix must NOT reintroduce -1.
    yosys_equiv_idx = block.find('mode === "yosys_equiv"')
    netgen_idx = block.find("Legacy netgen mode")
    body = block[yosys_equiv_idx:netgen_idx]
    # Allow comments mentioning -1 as historical context, but not in
    # the live ternary assignment.
    # Strip JS comments and search.
    no_comments = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    no_comments = re.sub(r"//[^\n]*", "", no_comments)
    # The new code uses `: null` not `: -1` in the parsing ternaries.
    assert " ? parseInt" in no_comments
    # Critically — the assignment `unproven = ... : -1` is gone
    # (verified by absence of `: -1;` or `: -1,` on the unproven
    # parsing line).
    assert "parseInt(finalMatch[2]) : -1" not in no_comments, (
        "pre-v2.6.0 ambiguous -1 sentinel for unproven must be removed")


def test_v0_114_2_sat_model_regex_captures_cell_type():
    """The SAT-model abort parser must match the canonical yosys
    error format. Test with a sample line from the field-agent's
    real output."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    # The regex literal is /No SAT model available for cell\s+(\S+)\s+\((\S+?)\)/
    assert "No SAT model available for cell" in block
    # Verify the regex would actually capture the field-agent's
    # observed pattern (INVD1, NANDxDy etc.)
    pat = re.compile(r"No SAT model available for cell\s+(\S+)\s+\((\S+?)\)")
    sample = "ERROR: No SAT model available for cell _1376__gate (INVD1)."
    m = pat.search(sample)
    assert m, "regex must match the canonical yosys error format"
    assert m.group(1) == "_1376__gate"
    assert m.group(2) == "INVD1"


def test_v0_114_2_verdict_explanation_distinguishes_sat_gap_from_mismatch():
    """The verdict_explanation string must distinguish 'tool
    limitation' from 'netlists differ'."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    assert "Sign-off LEC" in block or "lacked a SAT model" in block, (
        "verdict_explanation must explicitly call out the "
        "SAT-model tool-limitation scenario distinct from real "
        "netlist mismatch")
    assert "netlists may genuinely differ" in block, (
        "verdict_explanation must also cover the real-mismatch case")


def test_v0_114_2_tool_description_documents_v2_6_0():
    """The tool description string must advertise the new structured
    verdict so MCP clients see it."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    assert "since v2.6.0" in block
    assert "sat_model_unsupported_cells" in block


def test_v0_114_2_chip_agnostic_no_chip_class_literals():
    """The new code path must not depend on chip-class string
    literals. Liberty cell names (INVD1, NAND2D1) appear ONLY in
    comments / docstrings as examples — never in detection
    logic."""
    block = _extract_lvs_block(INDEX_JS.read_text())
    # Strip comments to inspect live code only
    no_comments = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    no_comments = re.sub(r"//[^\n]*", "", no_comments)
    no_strings = re.sub(r'"[^"]*"', '""', no_comments)
    for forbidden in ("ic-a", "bench-a", "vendor", "usb_hid_tester"):
        assert forbidden not in no_strings.lower(), (
            f"chip literal {forbidden!r} in live eda_lvs code path")


def test_v0_114_2_package_json_version_bumped_past_pre_fix():
    """package.json carries a valid unified semver version.

    v0.1.4 unified the version scheme (the previous 0.114.x numeric floor is
    obsolete — the #94 structured verdict is guarded by the SAT-model tests
    above, not by a version number). This now just asserts the version is
    well-formed 3-part semver."""
    import json
    pkg = json.loads((MCP_ROOT / "package.json").read_text())
    v = pkg.get("version", "")
    parts = v.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"package.json version {v!r} not 3-part semver")
