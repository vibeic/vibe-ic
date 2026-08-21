#!/usr/bin/env python3
"""Wave 75 — tests for eda_pdk_lint static shape.

Live PDK lint requires docker + a real Liberty/LEF/GDS deck. These
tests verify the wrapper's contract.

Positive: required args (lib/techlef/celllef) are mandatory.
Negative: when docker is unreachable, return early with a clear error.
Edge   : RESISTANCE-missing on tech LEF emits warn (not error) so
         IR-drop fallback can proceed.
SKIP   : cellgds + cts_buf_list are optional; absence must skip the
         corresponding probe (no dockerExec on that branch).
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"eda_pdk_lint"')
    assert idx > 0
    return src[idx: idx + 6000]


def test_tool_registered():
    assert '"eda_pdk_lint"' in INDEX_JS.read_text()


def test_required_args_have_no_defaults():
    """Positive: lib + techlef + celllef must be required — defaulting
    these would let an agent silently lint a wrong PDK."""
    w = _slice()
    for arg in ("lib", "techlef", "celllef"):
        i = w.find(arg + ":")
        # zod chain on each line
        line = w[i: i + 200]
        assert ".default(" not in line, f"{arg} must be required"
        assert ".describe(" in line, f"{arg} must have a describe()"


def test_optional_args_marked_optional():
    """SKIP-equivalent: cellgds + cts_buf_list must be .optional() so
    decks without those data still run."""
    w = _slice()
    assert "cellgds:" in w
    assert "cts_buf_list:" in w
    # Find the line for each and confirm `.optional()`
    for arg in ("cellgds", "cts_buf_list"):
        i = w.find(arg + ":")
        line = w[i: i + 250]
        assert ".optional()" in line, f"{arg} must be .optional()"


def test_docker_unreachable_short_circuits():
    """Negative: v2.5.1 — when _probeDocker fails, the tool returns
    a structured error rather than spewing dockerExec failures across
    every subsequent check."""
    w = _slice()
    assert "_probeDocker" in w
    assert "docker_unreachable" in w


def test_resistance_missing_is_warn_not_error():
    """Edge: tech LEF without RESISTANCE emits warn — eda_ir_drop has
    via_resistance_ohm fallback, so this should not block PnR."""
    w = _slice()
    assert "RESISTANCE" in w
    # Severity is the first arg of note(...); the resistance call lives
    # on the same line as `note("warn", "tech_lef_resistance", ...)`.
    assert 'note("warn", "tech_lef_resistance"' in w, (
        "missing RESISTANCE must be warn (eda_ir_drop has fallback)"
    )


def test_liberty_too_few_blocks_is_error():
    """Negative: a Liberty file with <10 library/cell blocks is
    almost certainly empty/corrupt; this MUST be an error so synth
    doesn't proceed against a broken deck."""
    w = _slice()
    assert 'note("error", "liberty_syntax"' in w, (
        "<10 Liberty blocks must escalate to error (corrupt deck)"
    )


def test_gds_lef_count_mismatch_is_warn():
    """Edge: GDS-LEF cell-count mismatch >50% emits warn (the deck
    may legitimately ship more cells in GDS than LEF for analog hardmacros)."""
    w = _slice()
    if "gds_lef_count_mismatch" in w:
        assert 'note("warn", "gds_lef_count_mismatch"' in w, (
            "GDS/LEF mismatch must be warn (analog hardmacros legit case)"
        )


def test_summary_counts_severities():
    """Positive: summary emits `N errors, M warnings, K info`."""
    w = _slice()
    assert "errors" in w
    assert "warnings" in w
    assert "info" in w
