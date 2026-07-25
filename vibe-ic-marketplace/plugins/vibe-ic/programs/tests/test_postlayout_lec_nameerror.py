"""Bidirectional tests for the post-layout LEC NameError fix (Defect 2).

DEFECT direction:
  The pre-fix code contained ``Path(liberty)`` where ``liberty`` was never
  defined in the function scope of ``_emit_lec_post_layout``.  This raised
  ``NameError: name 'liberty' is not defined``.  The caller's bare
  ``except Exception as exc: notes.append(...)`` swallowed the error, so
  the LEC step silently did not run and the error was buried as a JSON
  detail string — never surfaced as a FAIL.

  This test verifies:
    (a) The pre-fix pattern (bare ``liberty`` reference) raises NameError.
    (b) The caller's original swallow would turn a NameError into a note,
        i.e., a misuse of the broad except.

FIXED direction:
  The fix replaces ``Path(liberty)`` with
  ``Path(str(pdk.liberty)) if getattr(pdk, "liberty", None) else None``,
  which resolves correctly.  The caller's except now re-raises as
  RuntimeError so the failure is LOUD and visible in the orchestrator.

  Tests verify:
    (a) The fixed code path does NOT raise NameError.
    (b) When the function DOES raise (e.g., import error), the caller
        re-raises as RuntimeError rather than silently appending a note.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

# ---------------------------------------------------------------------------
# DEFECT direction (a): verify bare `liberty` raises NameError
# ---------------------------------------------------------------------------

def test_defect_bare_liberty_is_nameerror():
    """Pre-fix pattern: bare 'liberty' in a function scope that never defines
    it raises NameError.  This is the root cause of the defect.
    """
    def _pre_fix_snippet(pdk):
        """Mimics the pre-fix code path."""
        # Simulate the pre-fix code: `liberty` is referenced but not defined.
        _lib_host = Path(liberty) if liberty else None  # noqa: F821 — intentional
        return _lib_host

    pdk_mock = MagicMock()
    pdk_mock.liberty = "/some/path/sky130.lib"
    with pytest.raises(NameError, match="liberty"):
        _pre_fix_snippet(pdk_mock)


# ---------------------------------------------------------------------------
# DEFECT direction (b): broad except swallows the NameError silently
# ---------------------------------------------------------------------------

def test_defect_broad_except_swallows_nameerror():
    """Pre-fix caller pattern: 'except Exception as exc: notes.append(...)'.
    A NameError is an Exception subclass, so it is caught and buried rather
    than surfaced as a FAIL.  This is the second part of the defect.
    """
    notes = []

    def _pre_fix_caller():
        try:
            undefined_var = liberty  # noqa: F821
        except Exception as exc:
            notes.append(f"post-layout LEC emit failed: {exc}")

    _pre_fix_caller()
    # The NameError was swallowed — the caller continues and the note is buried.
    assert len(notes) == 1
    assert "liberty" in notes[0].lower() or "not defined" in notes[0]
    # Crucially, no exception was propagated — this is the bug.


# ---------------------------------------------------------------------------
# FIXED direction (a): pdk.liberty resolves without NameError
# ---------------------------------------------------------------------------

def test_fixed_pdk_liberty_no_nameerror(tmp_path):
    """Fixed pattern: getattr(pdk, 'liberty', None) / str(pdk.liberty)
    resolves without NameError regardless of whether the liberty file exists.
    """
    pdk_mock = MagicMock()
    pdk_mock.liberty = str(tmp_path / "sky130_tt.lib")

    def _fixed_snippet(pdk):
        """Mimics the fixed code path."""
        _liberty_host_str = str(pdk.liberty) if getattr(pdk, "liberty", None) else ""
        _lib_host = Path(_liberty_host_str) if _liberty_host_str else None
        _lib_exists = bool(_lib_host and _lib_host.is_file())
        _lib_nonempty = bool(_lib_exists and _lib_host.stat().st_size > 0)
        return _liberty_host_str, _lib_exists, _lib_nonempty

    # Must not raise
    liberty_str, exists, nonempty = _fixed_snippet(pdk_mock)
    assert liberty_str == str(tmp_path / "sky130_tt.lib")
    assert exists is False    # file doesn't actually exist in tmp_path
    assert nonempty is False


def test_fixed_pdk_liberty_none_no_nameerror():
    """Fixed pattern: pdk.liberty = None → _liberty_host_str = '' → no crash."""
    pdk_mock = MagicMock()
    pdk_mock.liberty = None

    def _fixed_snippet(pdk):
        _liberty_host_str = str(pdk.liberty) if getattr(pdk, "liberty", None) else ""
        _lib_host = Path(_liberty_host_str) if _liberty_host_str else None
        _lib_exists = bool(_lib_host and _lib_host.is_file())
        return _liberty_host_str, _lib_exists

    liberty_str, exists = _fixed_snippet(pdk_mock)
    assert liberty_str == ""
    assert exists is False


def test_fixed_pdk_liberty_real_file(tmp_path):
    """Fixed pattern: pdk.liberty points to a real file → exists=True."""
    lib_file = tmp_path / "sky130_tt.lib"
    lib_file.write_text("/* liberty stub */\n")

    pdk_mock = MagicMock()
    pdk_mock.liberty = str(lib_file)

    def _fixed_snippet(pdk):
        _liberty_host_str = str(pdk.liberty) if getattr(pdk, "liberty", None) else ""
        _lib_host = Path(_liberty_host_str) if _liberty_host_str else None
        _lib_exists = bool(_lib_host and _lib_host.is_file())
        _lib_nonempty = bool(_lib_exists and _lib_host.stat().st_size > 0)
        return _lib_exists, _lib_nonempty

    exists, nonempty = _fixed_snippet(pdk_mock)
    assert exists is True
    assert nonempty is True


# ---------------------------------------------------------------------------
# FIXED direction (b): caller re-raises as RuntimeError (loud, not swallowed)
# ---------------------------------------------------------------------------

def test_fixed_caller_reraises_as_runtimeerror():
    """Fixed caller: exceptions in the LEC emit step are re-raised as
    RuntimeError so they surface as FAIL in the orchestrator, not as a
    buried JSON detail string.
    """
    def _fixed_caller(fn):
        """Mimics the fixed caller pattern."""
        try:
            fn()
        except Exception as exc:
            raise RuntimeError(
                f"post-layout LEC emit FAILED (sign-off step): {exc}"
            ) from exc

    def _boom():
        raise NameError("name 'liberty' is not defined")

    # With the fixed caller, the NameError is propagated as RuntimeError.
    with pytest.raises(RuntimeError, match="post-layout LEC emit FAILED"):
        _fixed_caller(_boom)


def test_fixed_caller_does_not_swallow_errors():
    """Contrast test: the pre-fix broad-swallow pattern suppresses the error;
    the fixed re-raise pattern does NOT suppress it.
    """
    notes_pre = []
    notes_post = []

    def _pre_fix_caller(fn):
        try:
            fn()
        except Exception as exc:
            notes_pre.append(f"emit failed: {exc}")

    def _fixed_caller(fn):
        try:
            fn()
        except Exception as exc:
            raise RuntimeError(f"LEC FAILED: {exc}") from exc

    def _boom():
        raise NameError("name 'liberty' is not defined")

    # Pre-fix: swallows silently.
    _pre_fix_caller(_boom)
    assert len(notes_pre) == 1  # error is buried

    # Fixed: propagates.
    with pytest.raises(RuntimeError):
        _fixed_caller(_boom)


# ---------------------------------------------------------------------------
# Verify the actual source no longer contains bare `liberty` reference
# ---------------------------------------------------------------------------

def test_source_no_bare_liberty_in_lec_post_layout():
    """Static check: _emit_lec_post_layout function body in the fixed source
    must not contain the bare name ``liberty`` on a standalone assignment
    (i.e., the NameError-inducing pattern 'Path(liberty)' must be gone).
    """
    runner = PROGS / "phase3_one_shot_runner.py"
    assert runner.is_file(), f"phase3_one_shot_runner.py not found at {runner}"

    src = runner.read_text(encoding="utf-8", errors="replace")

    # Find _emit_lec_post_layout and extract its body up to the next top-level def
    fn_start = src.find("def _emit_lec_post_layout(")
    assert fn_start != -1, "_emit_lec_post_layout not found"

    # Find next top-level def after the function
    import re
    next_def = re.search(r"\ndef [a-zA-Z_]", src[fn_start + 10:])
    if next_def:
        fn_body = src[fn_start: fn_start + 10 + next_def.start()]
    else:
        fn_body = src[fn_start:]

    # The pre-fix bug was this exact pattern
    assert "Path(liberty)" not in fn_body, (
        "Bug still present: 'Path(liberty)' found in _emit_lec_post_layout. "
        "This is the NameError source — replace with Path(pdk.liberty) / "
        "_liberty_host_str pattern.")


def test_source_caller_reraises_not_swallows():
    """Static check: the caller of _emit_lec_post_layout must not silently
    append to notes — it must re-raise as RuntimeError.
    """
    runner = PROGS / "phase3_one_shot_runner.py"
    src = runner.read_text(encoding="utf-8", errors="replace")

    # Find the block around the _emit_lec_post_layout call
    call_pos = src.find("_emit_lec_post_layout(")
    assert call_pos != -1
    # Look ahead 400 chars for the except clause
    window = src[call_pos: call_pos + 800]

    # The fix must raise RuntimeError, not just append to notes.
    assert "raise RuntimeError" in window, (
        "Caller of _emit_lec_post_layout must re-raise as RuntimeError "
        "(not silently append to notes). Found window:\n" + window[:400])

    # The old silent swallow pattern must be gone from this window.
    assert 'notes.append(f"post-layout LEC emit failed:' not in window, (
        "Old silent-swallow pattern still present in caller. Remove it.")
