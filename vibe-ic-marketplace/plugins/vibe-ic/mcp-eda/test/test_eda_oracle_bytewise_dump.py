#!/usr/bin/env python3
"""Wave 75 — tests for eda_oracle_bytewise_dump (v0.114 tool).

Static-shape coverage. Live oracle capture requires a connected scope
+ DE10-Lite + USB-HID tester, deferred to integration runs.

Positive: scaffold schema fields all present.
Negative: missing required arg surfaces zod validation reference.
Edge   : default scope_pid is 5990 (NOT 1768 — that PID fails on this rig).
SKIP   : tool description marks burn dependency on quartus_pgm + USB-Blaster.
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"eda_oracle_bytewise_dump"')
    assert idx > 0
    return src[idx: idx + 6000]


def test_tool_registered():
    assert '"eda_oracle_bytewise_dump"' in INDEX_JS.read_text()


def test_required_args_declared():
    """Positive: oracle_sof_path / project_dir / l2_timing_json must
    all be required (no .default(...) on these three). The whole point
    of the oracle is that the agent passes the known-PASS SOF in."""
    w = _slice()
    for arg in ("oracle_sof_path", "project_dir", "l2_timing_json"):
        assert arg in w, f"required arg {arg} missing from schema"
    # The zod chain for each arg is its declaration up to the next
    # newline-comma-then-identifier line (next arg). Slice that block
    # and ensure no .default(...) appears.
    for arg in ("oracle_sof_path", "project_dir", "l2_timing_json"):
        i = w.find(arg + ":")
        # End at the closing `),` that terminates the .describe(...) chain.
        end = w.find("),\n", i)
        block = w[i: end if end > 0 else i + 400]
        assert ".default(" not in block, (
            f"{arg} must be required (no default); zod block:\n{block}"
        )


def test_default_scope_pid_is_5990():
    """Edge: BACKLOG-v6 D2 lesson — DSO-X 3024G PID is 5990 (0x1766).
    The legacy default 1768 silently fails. v0.114 fixed this; the
    default must not regress."""
    w = _slice()
    assert "scope_pid" in w
    assert ".default(5990)" in w, (
        "scope_pid default must be 5990 (DSO-X 3024G); regression risk"
    )


def test_burn_failure_path_returns_clear_error():
    """Negative: when quartus_pgm fails, the wrapper must return a
    structured error including stage='burn_sof' so callers can branch."""
    w = _slice()
    assert '"burn_sof"' in w
    assert "oracle SOF burn failed" in w


def test_scaffold_emits_required_oracle_schema_fields():
    """Positive: the emitted oracle JSON scaffold must include the
    canonical schema fields documented in the tool description
    (consumed by rtl_response_byte_oracle_check.py --oracle-json).
    The scaffold is a JS object literal so keys are unquoted."""
    w = _slice()
    for field in (
        "schema:",
        "vibe-ic L10 oracle byte stream v1",
        "opcode_oracle_vectors:",
        "provenance:",
        "source_sof:",
    ):
        assert field in w, f"oracle schema field {field} missing"


def test_skip_when_no_quartus_pgm_documented():
    """SKIP_NOT_APPLICABLE: the description names quartus_pgm + USB-
    Blaster as preconditions so an agent on a bench without them
    knows to skip."""
    w = _slice()
    assert "quartus_pgm" in w
    assert "USB-Blaster" in w
