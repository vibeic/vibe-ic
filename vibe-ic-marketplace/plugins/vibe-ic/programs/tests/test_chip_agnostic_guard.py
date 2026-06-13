"""tests/test_chip_agnostic_guard.py — public-source chip-AGNOSTIC guard.

Loads tests/chip_deny_list.txt and asserts that no tracked source file
under programs/, skills/, agents/, flow/, tools/, .claude-plugin/, hooks/,
commands/, docs/ contains any deny-listed token (word-bounded,
case-insensitive).

This replaces the per-version (v1.6.*) guards that lived in the private
regression suite. The deny-list is externalized so contributors can extend
it without modifying code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[2]

if str(_PLUGIN_ROOT / "programs") not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))

import source_chip_agnostic_check as guard  # noqa: E402


def test_chip_agnostic_guard_passes_on_public_tree():
    violations = guard.scan(_PLUGIN_ROOT)
    if violations:
        msg_lines = [f"{len(violations)} chip-AGNOSTIC violations:"]
        for rel, line, tok in violations[:20]:
            msg_lines.append(f"  {rel}:{line}  →  {tok!r}")
        if len(violations) > 20:
            msg_lines.append(f"  ... and {len(violations) - 20} more")
        pytest.fail("\n".join(msg_lines))


def test_chip_deny_list_is_non_empty():
    tokens = guard._load_deny_list(_PLUGIN_ROOT / "programs" / "tests" / "chip_deny_list.txt")
    assert tokens, "deny-list is empty — guard would never catch anything"
    assert len(tokens) >= 5, f"deny-list suspiciously short: {tokens}"
