#!/usr/bin/env python3
"""Tests for klayout_pdk_lvs — the extractor's own honesty about its layer map.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# A layer map that fits nothing must SAY so.
#
# MEASURED: DEFAULT_LAYERMAP is an EXAMPLE numbering ("a common 180nm-style
# GDS numbering"), and on a PDK numbered differently the extraction recognizes
# no device at all — `top_circuit()` is None and `_counts` raised
# `'NoneType' object has no attribute 'each_device'` deep inside the container.
# The caller saw a bare non-zero rc, so an entire LVS arm read as "the tool has
# not run" and never named the cause.
# ---------------------------------------------------------------------------

def test_no_circuit_is_a_named_capability_gap_not_a_traceback():
    import inspect
    import klayout_pdk_lvs as K
    src = inspect.getsource(K.cmd_extract)
    assert "if top is None:" in src
    # it returns the module's disclosed-gap code, and it says what to supply
    assert "return 3" in src
    assert "--layermap" in src
