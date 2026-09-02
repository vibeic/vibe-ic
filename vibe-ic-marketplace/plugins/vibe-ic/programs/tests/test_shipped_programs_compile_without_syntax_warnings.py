#!/usr/bin/env python3
"""Every shipped `programs/**/*.py` must compile without a syntax warning.

WHY THIS IS A GATE AND NOT A STYLE PREFERENCE. `phase3_one_shot_runner.py`
carried an invalid escape sequence `'\\s'` inside the non-raw literal holding
the KLayout DEF->GDS streamout deck. Importing the module printed

    <unknown>:25873: SyntaxWarning: invalid escape sequence '\\s'

on STDERR — and `ip_integration_check` writes its JSON report on that same
stream, so the warning landed INSIDE the payload and the reader died with
`json.decoder.JSONDecodeError: Extra data`. A cosmetic-looking warning became
a gate that could not report. It survived from at least v1.15.76 to v1.15.87,
moving line number twice without ever being read.

CITING IS NOT CAUSING. The warning appears in the captured output of 51 red
cases across 45 files. Suppressing only the warning, everything else held
identical, moved exactly ONE file (3 cases): for the other 44 it was
incidental noise beside the failure, not the failure. This guard is therefore
scoped to what was actually proved — the warning must not exist — and claims
nothing about the 48 cases it does not cause.

WARNING CLASS IS INTERPRETER-DEPENDENT, so this does not name one. An invalid
escape is a `SyntaxWarning` on Python 3.12 (the pinned image) and a
`DeprecationWarning` on 3.10; escalated to an error mid-compile, CPython 3.12
re-raises it as `SyntaxError`. The sweep escalates ALL warnings and catches
every one of those shapes, so it cannot go quietly blind on a different
interpreter than the one it was written against.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_PROGRAMS = _PLUGIN_ROOT / "programs"


def _compile_complaint(source: str, name: str):
    """Return the complaint compiling `source` raises, or None if clean."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            compile(source, name, "exec")
        except Warning as exc:            # 3.10 and earlier: Deprecation
            return f"{type(exc).__name__}: {exc}"
        except SyntaxError as exc:        # 3.12: escalated mid-compile
            return f"{type(exc).__name__}: {exc}"
    return None


def test_the_sweep_actually_detects_a_bad_escape():
    """The negative arm. A sweep that reports zero because it never looks is
    the defect with the sign flipped, so pin that the helper flags the exact
    construct this file exists for BEFORE trusting its clean sweep."""
    complaint = _compile_complaint('X = "\\s"\n', "<synthetic>")
    assert complaint is not None, "the sweep would pass on a known-bad escape"
    assert "\\s" in complaint, complaint
    assert _compile_complaint('X = r"\\s"\n', "<synthetic>") is None


def test_no_shipped_program_compiles_with_a_warning():
    files = sorted(_PROGRAMS.rglob("*.py"))
    assert len(files) > 100, f"sweep found only {len(files)} files — wrong root"
    offenders = []
    for path in files:
        complaint = _compile_complaint(
            path.read_text(errors="replace"), str(path))
        if complaint is not None:
            offenders.append(f"  {path.relative_to(_PLUGIN_ROOT)}: {complaint}")
    if offenders:
        pytest.fail("\n".join(
            [f"{len(offenders)} shipped program(s) do not compile cleanly; a "
             "warning on stderr corrupts any gate that reports JSON there:"]
            + offenders[:20]))
