#!/usr/bin/env python3
"""v0.1.85 — l9_submodule_conformance skips low_confidence (naming-delegated)
submodules: a submodule documented in a "Plugin chooses naming/hierarchy" spec
is a FUNCTIONAL contract, not a literal RTL module-name assertion."""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import l9_submodule_conformance_check as C  # noqa: E402

_RTL_PORTS = {"sha256_core": [("clk", "input")], "sha256_k": []}


def test_low_confidence_submodule_skipped():
    l9 = {"submodules": [
        {"name": "Hash core", "low_confidence": True},
        {"name": "K constants", "low_confidence": True},
    ]}
    assert C.check_submodule_presence(l9, _RTL_PORTS) == []


def test_high_confidence_missing_still_flagged():
    l9 = {"submodules": [{"name": "nonexistent_mod"}]}  # no low_confidence
    findings = C.check_submodule_presence(l9, _RTL_PORTS)
    assert any(f.rule == "SUBMODULE_FILE_MISSING" for f in findings)


def test_mixed_only_high_confidence_flagged():
    l9 = {"submodules": [
        {"name": "Hash core", "low_confidence": True},      # skip
        {"name": "sha256_core"},                            # present → ok
        {"name": "ghost_mod"},                              # missing → flag
    ]}
    findings = C.check_submodule_presence(l9, _RTL_PORTS)
    flagged = {f.module for f in findings}
    assert "ghost_mod" in flagged
    assert "Hash core" not in flagged and "sha256_core" not in flagged
