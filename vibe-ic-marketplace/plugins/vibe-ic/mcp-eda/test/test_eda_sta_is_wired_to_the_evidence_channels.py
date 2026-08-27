#!/usr/bin/env python3
"""`eda_sta` must actually USE the evidence channels, not merely ship them.

`sta_evidence.mjs` is fully unit-tested, and every one of those tests would
still pass if the `eda_sta` tool never called it. That is the gap this file
closes: it asserts the wiring at the call site.

The four properties pinned here each correspond to a way the fix could be
silently undone while the module's own tests stay green:

  1. openroad is invoked with `-metrics`. Without it no metrics file is ever
     written, every metric is ABSENT, and every run comes back UNMEASURED —
     which looks like the guard "working" while actually measuring nothing.
  2. the stale metrics file is deleted BEFORE the run. A file left by an
     earlier run satisfies the presence term with another design's numbers,
     which is a false PASS.
  3. the linkage metric is emitted inside the Tcl, after link_design. If the
     emission is dropped the metric is absent on every run, good or bad.
  4. the tool's reported `success` is the conjunction, not `result.success`.
     That last one IS the original bug: `success: result.success` is exactly
     what returned true on a run that linked no design.
"""
from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "index.js"
SRC = INDEX.read_text(encoding="utf-8")

LINK_METRIC = "sta__design__port__count"


def _eda_sta_block() -> str:
    """The source of the eda_sta tool registration, up to the next tool."""
    start = SRC.index('// ─── Tool: eda_sta ───')
    nxt = SRC.index('// ─── Tool: eda_lvs ───', start)
    return SRC[start:nxt]


def test_openroad_is_invoked_with_a_metrics_file():
    block = _eda_sta_block()
    assert "-metrics " in block, (
        "eda_sta no longer passes -metrics; the metrics channel is dead and "
        "every run reports UNMEASURED regardless of what happened")
    assert re.search(r"openroad[^\n]*-metrics \$\{staMetricsFile\}", block), block[:400]


def test_a_stale_metrics_file_is_removed_before_the_run():
    block = _eda_sta_block()
    assert re.search(r"rm -f \$\{staMetricsFile\}[^\n]*&&[^\n]*openroad", block), (
        "the metrics file is not cleared before openroad runs. A file left "
        "behind by an earlier run satisfies the presence term with another "
        "design's numbers — a false PASS.")


def test_the_linkage_metric_is_emitted_after_link_design():
    block = _eda_sta_block()
    assert "${staEvidenceTcl()}" in block, (
        "the linkage-metric emission was dropped from the Tcl; the metric is "
        "then absent on every run and the rule can never distinguish a linked "
        "design from an unlinked one")
    link_at = block.index("link_design ")
    emit_at = block.index("${staEvidenceTcl()}")
    assert link_at < emit_at, (
        "the linkage metric must be emitted AFTER link_design — before it, "
        "get_ports would report the pre-link network")
    # and before the reports, so an unlinked network raises here first
    assert emit_at < block.index("report_checks"), block[link_at:emit_at + 200]


def test_the_reported_success_is_the_conjunction_not_the_exit_code():
    block = _eda_sta_block()
    assert "evaluateStaEvidence(" in block, "eda_sta never calls the evaluator"
    assert re.search(r"\bsuccess:\s*staPass\b", block), (
        "eda_sta's reported success is not the conjunction. `success: "
        "result.success` is the ORIGINAL BUG — openroad exits 0 having linked "
        "no design and the tool reports true.")
    assert not re.search(r"\bsuccess:\s*result\.success\b", block), (
        "eda_sta still reports the raw exit code as success")


def test_the_manifest_status_is_gated_on_the_conjunction():
    block = _eda_sta_block()
    # ASSEMBLY: PASS additionally requires clockConstrained, so the literal
    # `status: "PASS"` became `status: clockConstrained ? "PASS" : ...`. That is
    # a tightening; the gate on staPass is what this test exists to pin.
    m = re.search(r'if \(staPass\) \{\s*const dir[^}]*?status: clockConstrained \? "PASS"',
                  block, re.S)
    assert m, (
        'the manifest still writes status:"PASS" on something other than the '
        'conjunction. Writing PASS on the bare exit code is how bug #1 reached '
        'the manifest.')


def test_wns_is_withheld_when_the_run_produced_no_evidence():
    """Bug #2: a source-less clock prints `wns max 0.00`, byte-identical to a
    genuinely clean result. Reporting that number on a run that failed its
    evidence checks hands the caller a fabricated timing result."""
    block = _eda_sta_block()
    assert re.search(r"wns:\s*staPass \? wns : null", block), (
        "wns is reported without regard to the evidence verdict")
    assert re.search(r"tns:\s*staPass \? tns : null", block)


def test_the_module_is_imported():
    assert 'from "./lib/sta_evidence.mjs"' in SRC
