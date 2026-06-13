#!/usr/bin/env python3
"""Tests for aid_class_qsf_gen.py — backwards-compat shim.

This module has NO decision logic of its own: Wave 73 (v0.128) renamed
the class-AGNOSTIC generator to qsf_gen.py, and this file is a one-release
forwarding shim (`from qsf_gen import *` + a `main` passthrough) that also
raises a DeprecationWarning. So these are SMOKE-ONLY tests, but they still
pin the shim's real contract rather than asserting something vacuous:
  * importing it raises DeprecationWarning,
  * its `main` IS qsf_gen.main (genuine re-export, not a stub),
  * the public symbols of qsf_gen are forwarded.
"""
from __future__ import annotations

import importlib
import sys
import warnings


def _fresh_import_with_warnings():
    """Import the shim fresh (dropping any cached module) so the
    module-level warnings.warn fires and can be captured."""
    for name in ("aid_class_qsf_gen",):
        sys.modules.pop(name, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mod = importlib.import_module("aid_class_qsf_gen")
    return mod, caught


# ----------------------------------------------------------------------
# Shim raises a DeprecationWarning on import (its observable behavior).
# ----------------------------------------------------------------------
def test_import_emits_deprecation_warning():
    _mod, caught = _fresh_import_with_warnings()
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep, "shim must warn that it is renamed to qsf_gen.py"
    assert "qsf_gen" in str(dep[0].message)


# ----------------------------------------------------------------------
# Re-export is genuine — main is the SAME object as qsf_gen.main.
# ----------------------------------------------------------------------
def test_main_is_qsf_gen_main():
    import qsf_gen
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = importlib.import_module("aid_class_qsf_gen")
    assert callable(mod.main)
    assert mod.main is qsf_gen.main


def test_public_symbols_forwarded():
    import qsf_gen
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = importlib.import_module("aid_class_qsf_gen")
    # Every public (non-dunder) symbol qsf_gen exposes via `*` should be
    # reachable through the shim too.
    exported = getattr(qsf_gen, "__all__", None)
    if exported is None:
        exported = [n for n in dir(qsf_gen) if not n.startswith("_")]
    missing = [n for n in exported if not hasattr(mod, n)]
    assert missing == [], f"shim failed to forward: {missing}"
