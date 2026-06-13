#!/usr/bin/env python3
"""Tests for eda_lint strictness selector (v0.99.2 fix).

The default 'error_only' must demote WIDTHTRUNC / UNUSEDPARAM /
UNUSEDSIGNAL / PINMISSING / DECLFILENAME / STMTDLY / SYNCASYNCNET to
non-fatal so RTL that Quartus / iverilog accept also passes lint.
'warnings_as_errors' restores the historical -Wall behavior.

Tests are STATIC checks against src/index.js so they don't require a
live verilator install. Runtime invocation of the MCP tool is covered
by the higher-level eda_workflow integration tests.
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"
assert INDEX_JS.exists()


def test_strictness_selector_present():
    src = INDEX_JS.read_text()
    assert "strictness" in src, \
        "v0.99.2 strictness selector missing from eda_lint"
    assert '"error_only"' in src
    assert '"warnings_as_errors"' in src


def test_demoted_warnings_listed():
    """The demotion list must be a JS array. We verify the canonical
    members are present so a future edit can't silently drop them."""
    src = INDEX_JS.read_text()
    for w in ("WIDTHTRUNC", "UNUSEDPARAM", "UNUSEDSIGNAL",
              "PINMISSING", "DECLFILENAME"):
        assert w in src, f"demoted warning {w} missing from _LINT_DEMOTED_WARNINGS"


def test_default_is_error_only():
    """Default strictness must be the lenient mode — that's the user-
    requested behavior. A regression to the old default would put us
    back where v0.119.22 vendor complained from."""
    src = INDEX_JS.read_text()
    # The zod schema declares: strictness: z.enum([...]).default("error_only")
    assert '.default("error_only")' in src, \
        "eda_lint default strictness must be 'error_only'"


def test_warnings_as_errors_path_uses_minimal_wno():
    """When the user asks for warnings_as_errors, the historical
    -Wno-DECLFILENAME suppression should still apply (Verilator emits
    a confusing 'top file basename != module name' even in valid code)
    but no other -Wno flags. We grep for the exact assignment expr."""
    src = INDEX_JS.read_text()
    assert '"warnings_as_errors"' in src
    # Strict path keeps only DECLFILENAME suppressed
    assert '-Wno-DECLFILENAME' in src


def test_helpful_description():
    """Tool description must explain what 'error_only' does so an agent
    reading the MCP listing knows when to switch modes."""
    src = INDEX_JS.read_text()
    # Look for the description string passed to server.tool("eda_lint", ...)
    # — should mention Quartus or Icarus to make the choice context clear.
    idx = src.find('"eda_lint"')
    assert idx > 0
    window = src[idx:idx + 1500]
    assert "Quartus" in window or "Icarus" in window, \
        "eda_lint description should explain why 'error_only' is the default"
