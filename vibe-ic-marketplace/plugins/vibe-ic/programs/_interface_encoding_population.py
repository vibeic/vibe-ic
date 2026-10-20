"""Canonical row-population binding for interface encoding receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


SCHEMA = 'vibeic.interface_encoding_population.v1'


def binding(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bind every complete row while ignoring nondeterministic row order."""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('interface population rows must be a list of objects')
    ordered = sorted(
        rows,
        key=lambda row: json.dumps(row, sort_keys=True, separators=(',', ':')))
    canonical = json.dumps(
        ordered, sort_keys=True, separators=(',', ':')).encode()
    return {
        'schema': SCHEMA,
        'row_count': len(rows),
        'sha256': hashlib.sha256(canonical).hexdigest(),
    }


def matches(claim: Any, rows: Any) -> bool:
    """Return whether a receipt's binding covers exactly its current rows."""
    try:
        return claim == binding(rows)
    except (TypeError, ValueError):
        return False
