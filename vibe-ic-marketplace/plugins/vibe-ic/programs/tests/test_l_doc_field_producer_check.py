#!/usr/bin/env python3
"""A field a checker READS must have a PRODUCER (the #312 family).

The same shape was measured five times in one campaign — #309/#348
(`declared_rails`, 3 of 30), #366 (`.sby`, 0 tracked), #369
(`carried`/`decided`, computed then ignored), #365 (`duration_ms`, a
hardcoded 0), #312 (`ai_patches`, 4 readers 0 writers). Three of the five
were "the producer never existed", and the consequence is always silent: a
checker reading a field nobody fills sees an EMPTY value, and an empty value
is indistinguishable from a clean one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "l_doc_field_producer_check.py"


# NOTE: field names in fixtures must be >= 4 chars. The program's reader
# regex enforces that minimum deliberately, to stop short names (`id`, `x`)
# matching half the codebase. Two tests here first used `g1`/`g2` and failed
# for that reason — the fixture was wrong, not the program.


























def test_shipped_register_entries_all_carry_triage():
    """Every recorded entry must say what was found when it was
    investigated — including the one proven to be a FALSE POSITIVE of this
    gate's own rule, so nobody 'repairs' it by inventing a producer."""
    bl = _PROGRAMS / "l_doc_field_producer_baseline.json"
    if not bl.is_file():
        return
    d = json.loads(bl.read_text())
    for field in d.get("known", []):
        assert d.get("triage", {}).get(field), \
            f"{field} is recorded as debt with no triage"
