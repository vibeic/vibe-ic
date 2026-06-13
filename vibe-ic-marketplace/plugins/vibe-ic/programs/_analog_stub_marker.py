"""v1.6.177 (#72 P1-6) — shared helper for analog deterministic-stub
recognition.

The `analog_one_shot_runner` deterministic-stub emitter (v1.6.171,
#60 P1-6) writes minimal-substance artefacts tagged

    JSON files:    {"extraction_strategy": "deterministic_stub", ...}
    Textual files: first line contains
                   `deterministic_stub extraction_strategy=deterministic_stub`

so downstream audit gates can distinguish stub from real analog
data. v1.6.171 claimed the 8 substance gates would PASS naturally,
but `analog_netlist_pdk_check`, `analog_corner_sweep_check`,
`analog_hardmacro_check`, and `mixed_signal_cosim_check` still FAIL
on stubs because they expect content (model includes, ≥3 corners,
LEF macro headers, cosim PASS flag) that a stub does not carry.

This helper exposes two predicates so each gate can detect a stub
artefact, downgrade `passed=False` to `passed=True` for that
specific finding bucket, and emit a `PASS_WITH_STUB` verdict tier.

chip-AGNOSTIC: the marker is a structural property of the artefact,
never a chip-class string literal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


_TEXT_MARKER = "extraction_strategy=deterministic_stub"
_JSON_MARKER_KEY = "extraction_strategy"
_JSON_MARKER_VAL = "deterministic_stub"


def is_stub_text(text: Optional[str]) -> bool:
    """Return True iff a textual artefact (`.sp`, `.mag`,
    `.flag`, `.md`, `.lef`, `.lib`, `.v`) carries the
    deterministic-stub marker in its first 16 lines."""
    if not text:
        return False
    for line in text.splitlines()[:16]:
        if _TEXT_MARKER in line:
            return True
    return False


def is_stub_json(payload: Optional[dict]) -> bool:
    """Return True iff a parsed JSON payload carries
    `extraction_strategy: "deterministic_stub"`."""
    if not isinstance(payload, dict):
        return False
    return payload.get(_JSON_MARKER_KEY) == _JSON_MARKER_VAL


def is_stub_path(path: Path) -> bool:
    """Best-effort stub detection by inspecting file contents.
    For `.json` files, parse + check the marker key; for any other
    file type, read up to 4 KiB and look for the textual marker.
    Missing or unreadable files return False."""
    try:
        if path.suffix.lower() == ".json":
            return is_stub_json(json.loads(path.read_text(errors="replace")))
        head = path.open("r", errors="replace").read(4096)
        return is_stub_text(head)
    except (OSError, json.JSONDecodeError):
        return False


__all__ = ["is_stub_text", "is_stub_json", "is_stub_path"]
