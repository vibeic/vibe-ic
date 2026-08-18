"""Shared no-protocol sentinel detection for Phase-1 gates.

A project that doesn't speak a protocol (memory-controller / analog-front-end /
register-pointer ICs) can declare `protocol_present: false` in either
`L1_DATASHEET.json` or `L3_CMD_PROTOCOL.json`. The sentinel exempts the
project from the protocol-implied layers (L3 command set, L8R RTL constants
that derive from CRC / bit timing) and from rules that derive from those
layers.

v0.62 — extracted from `phase1_doc_presence_check.py` so every Phase-1 gate
queries the same logic. v0.61 G1 fresh-agent verification surfaced Bug #4:
`phase1_doc_presence_check` honored the sentinel but
`phase1_consistency_check`'s `R_clock_freq_positive` /
`R_layer_documents_present` rules did not, producing false-FAILs on
no-protocol designs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional


# Layers that are protocol-implied. When the no-protocol sentinel is active
# these layers (a) may be absent without the doc-presence gate failing, and
# (b) may be missing or carry None values without the consistency gate
# raising "value was None" / "missing layers" errors.
SENTINEL_OPTIONAL_LAYERS: FrozenSet[str] = frozenset({"L3", "L8R"})

# Files we inspect for the sentinel. First match wins.
_SENTINEL_FILES = ("L3_CMD_PROTOCOL.json", "L1_DATASHEET.json")


def is_no_protocol_sentinel_active_in_dir(docs_dir: Path) -> bool:
    """Return True iff `docs_dir` contains a sentinel-bearing JSON.

    Reads L3_CMD_PROTOCOL.json then L1_DATASHEET.json; returns True the
    first time a `protocol_present: false` is found. Missing or
    malformed files are treated as 'no sentinel' (default to legacy
    protocol-IC behavior).
    """
    docs_dir = Path(docs_dir)
    for fname in _SENTINEL_FILES:
        p = docs_dir / fname
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(data, dict) and data.get("protocol_present") is False:
            return True
    return False


def is_no_protocol_sentinel_active_in_docs(
    docs: Dict[str, Any],
) -> bool:
    """Return True iff the in-memory `docs` dict (layer → parsed JSON)
    declares the sentinel in L1 or L3.

    Used by gates that already loaded the layer JSONs into a dict and
    don't want a second filesystem pass. Mirrors
    `is_no_protocol_sentinel_active_in_dir` semantics.
    """
    for layer in ("L3", "L1"):
        layer_doc = docs.get(layer)
        if isinstance(layer_doc, dict) and layer_doc.get("protocol_present") is False:
            return True
    return False
