"""#139(c) — Track-1 ORACLE-SOURCE sweep of the ic-expert-agent.md Skill corpus.

The `### Skill:` entry that instructed a BLIND author to READ the scoring
harness's `.env TOPLEVEL` / `VERILOG_SOURCES` and the hidden TB's `dut.<sig>`
binds to fix the module name / ports (the v1.4.19-flagged residual) is an
ORACLE-SOURCE violation — the harness `.env`/TB is NOT provided to the model in
the non-agentic blind shape. It is rewritten to spec-alone form: the interface is
sourced from the PROMPT's own stated header, never the oracle. The GENERAL lesson
(bind to the stated interface, reconcile prose vs the header) survives; the
legitimate whitebox / provided-TB-as-input context is explicitly scoped.
"""
from __future__ import annotations

from pathlib import Path

DOC = (Path(__file__).resolve().parent.parent.parent
       / "agents" / "ic-expert-agent.md").read_text()


def test_oracle_read_authoring_instructions_removed():
    # the specific imperative to author FROM the harness oracle must be gone
    assert "Name the top module to `.env TOPLEVEL`" not in DOC
    assert "enumerate the TB's `dut.<sig>` accesses and declare exactly those" \
        not in DOC
    assert ("### Skill: the harness .env TOPLEVEL and the TB's dut.<sig> binds "
            "fix the top module name") not in DOC


def test_spec_alone_replacement_present():
    assert ("### Skill: the prompt's stated interface header fixes the top "
            "module name") in DOC
    assert "§4.05 ORACLE-SOURCE rewrite 2026-07-15 (#139 track-1 sweep" in DOC
    # the rewritten skill still teaches the GENERAL interface-binding lesson
    assert "the prompt's stated interface" in DOC


def test_whitebox_tb_as_input_context_preserved():
    # entries where the harness/TB is a LEGAL input (provided TB, or a port
    # inferred from the prompt's PROSE) are preserved, not deleted — the sweep
    # is scoped to the blind-authoring oracle-read, not a blanket harness purge.
    assert "the hidden TB" in DOC          # prose-inference lessons kept
    assert "whitebox / provided-TB" in DOC  # the scoped legitimate-input note
