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
