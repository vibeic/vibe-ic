#!/usr/bin/env python3
"""The STA rule sits on a LINKAGE-derived count, and is not a size test.

WHY NOT THE OBVIOUS RULE
------------------------
OpenROAD-flow-scripts has `constraints__clocks__count` with `"compare": "=="`,
which looks like exactly the check that would catch our bug #2 (a clockless
netlist gets `create_clock -name clk [get_ports clk]`, OpenSTA only WARNS
STA-0366, still builds a source-less clock, and prints `wns max 0.00`).

It would not. `genMetrics.py:145-168` produces that metric by TEXT-PARSING
`create_clock` lines out of the SDC file, so a `create_clock` matching no port
still counts as 1. The metric is SDC-derived: it measures what we asked for,
not what the tool built. Any rule keyed on it is blind to the exact failure.

So the rule has to sit on a quantity only a genuinely LINKED design can
produce. Four candidates were measured; three of them turn out to be size
tests in disguise.

THE MEASUREMENT
---------------
openroad 26Q3-1797-g1c09d62b96, image digest
sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16,
sky130 open PDK, three designs read through read_liberty + read_lef +
read_verilog + link_design:

  * `real`     — a flop with an AND in front of it. An ordinary design.
  * `constant` — a real, synthesisable, tape-out-able block whose two outputs
                 are tied constants. THE CONTROL: it is tiny but it is not
                 broken, and a correct rule must not flag it.
  * `unlinked` — read_verilog on a missing file, i.e. the shape of bug #1.

  quantity          real   constant   unlinked
  ----------------  -----  ---------  --------
  instance count      2        0       absent
  pin count           6        0       absent
  register count      1        0       absent
  endpoint count      1        0       absent
  PORT COUNT          4        2       absent

Instance, pin, register and endpoint counts are all ZERO for the constant
block. A `>= 1` rule on any of them rejects a real design — that is a size
test, not a linkage test. Port count is >= 1 for every linkable top module (a
top module with no ports is not a design) and is still unobtainable without a
link: on the unlinked run `get_ports *` itself raises, the emitting
`utl::metric_integer` call never executes, and the metric is simply ABSENT
from the metrics JSON. Absent is UNMEASURED, which fails.

Port count is also structurally immune to bug #2: nothing an SDC can do
creates a port.

WHAT THIS FILE PINS
-------------------
  * the shipped rule uses the port count, and no rule is keyed on a
    clock/SDC-derived quantity;
  * the three measured designs get the right verdicts;
  * every rejected candidate is shown to be zero on the control, so a future
    swap to one of them turns this file red instead of shipping a size test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "src" / "lib" / "sta_evidence.mjs"

ERR_METRIC = "flow__errors__count"
LINK_METRIC = "sta__design__port__count"

# The measured table above, as data. Values are what the tools reported; a
# `None` means the metric was ABSENT from the metrics JSON, not zero.
MEASURED = {
    "real":     {"instance": 2, "pin": 6, "register": 1, "endpoint": 1, "port": 4},
    "constant": {"instance": 0, "pin": 0, "register": 0, "endpoint": 0, "port": 2},
    "unlinked": {"instance": None, "pin": None, "register": None, "endpoint": None,
                 "port": None},
}

# Candidates that were measured and REJECTED because they are zero on a real
# design. If the shipped rule ever moves onto one of these, it becomes a size
# test and `test_shipped_rule_is_not_one_of_the_rejected_size_quantities` fires.
REJECTED_QUANTITIES = {
    "instance": "sta__design__instance__count",
    "pin":      "sta__design__pin__count",
    "register": "sta__design__register__count",
    "endpoint": "sta__design__endpoint__count",
}


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not available; the module under test is JavaScript")
    return exe


def _js(expr: str):
    script = (f'import("file://{MODULE}").then(m => {{'
              f' process.stdout.write(JSON.stringify({expr})); }})'
              f'.catch(e => {{ process.stderr.write(String(e)); process.exit(9); }});')
    run = subprocess.run([_node(), "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, f"node failed: {run.stderr}"
    return json.loads(run.stdout)


def _verdict(port_count):
    """Evaluate a run that is clean apart from whatever the port count says.
    `port_count is None` models the metric being ABSENT from the JSON."""
    metrics = {ERR_METRIC: 0}
    if port_count is not None:
        metrics[LINK_METRIC] = port_count
    return _js("m.evaluateStaEvidence(" + json.dumps({
        "exitCode": 0, "metricsFileExists": True, "metricsRaw": json.dumps(metrics),
    }) + ")")


# ─────────────────── the rule is on the right kind of quantity ───────────────

def test_rule_is_keyed_on_the_linkage_derived_port_count():
    assert _js("m.STA_LINKAGE_METRIC") == LINK_METRIC
    rules = _js("m.STA_METRIC_RULES")
    keyed = [r for r in rules if r["metric"] == LINK_METRIC]
    assert len(keyed) == 1, rules
    assert keyed[0]["compare"] == ">=" and keyed[0]["value"] == 1
    assert keyed[0]["required"] is True, (
        "the linkage rule must be required — an absent linkage metric is the "
        "signature of the unlinked run it exists to catch")


def test_no_rule_is_keyed_on_a_clock_or_sdc_derived_quantity():
    """The ORFS trap: constraints__clocks__count is text-parsed out of the SDC,
    so it counts a create_clock that matched no port."""
    rules = _js("m.STA_METRIC_RULES")
    for r in rules:
        name = r["metric"]
        assert "clock" not in name and "sdc" not in name and "constraint" not in name, (
            f"rule keyed on {name}, which reads like an SDC-derived quantity. "
            f"An SDC-derived count reports what was ASKED FOR, not what the "
            f"tool BUILT, and is blind to a source-less clock.")


def test_shipped_rule_is_not_one_of_the_rejected_size_quantities():
    rules = {r["metric"] for r in _js("m.STA_METRIC_RULES")}
    for label, metric in REJECTED_QUANTITIES.items():
        assert metric not in rules, (
            f"the rule moved onto {metric}. Measured: that quantity is "
            f"{MEASURED['constant'][label]} on a real constant-output block, so a "
            f">= 1 rule on it flags a real design. That is a size test.")


# ───────────────────── the three measured designs ────────────────────────────

def test_real_design_passes_the_linkage_rule():
    got = _verdict(MEASURED["real"]["port"])
    assert got["pass"] is True, got
    assert got["verdict"] == "PASS"


def test_tiny_constant_output_block_is_not_falsely_flagged():
    """THE CONTROL. This block is real, synthesisable and has zero instances,
    zero pins, zero registers and zero endpoints. It must pass."""
    got = _verdict(MEASURED["constant"]["port"])
    assert got["pass"] is True, (
        "a legitimately tiny real design was flagged — the rule has become a "
        f"size test. {got}")
    assert got["verdict"] == "PASS"


def test_unlinked_run_fails_the_linkage_rule():
    """Bug #1's shape: openroad exits 0 having linked nothing. The exit code
    says fine; the linkage metric is ABSENT, and absent is UNMEASURED."""
    got = _verdict(MEASURED["unlinked"]["port"])
    assert got["pass"] is False, got
    assert got["verdict"] == "UNMEASURED"
    assert got["terms"][f"metric:{LINK_METRIC}"]["ok"] is False
    assert got["terms"][f"metric:{LINK_METRIC}"]["present"] is False
    # And note the exit code was zero — this run is caught ONLY by the rule.
    assert got["terms"]["exit_code_zero"]["ok"] is True


def test_a_linked_but_portless_top_also_fails():
    """Belt and braces: a zero port count is rejected as well as an absent one,
    so a network that links to an empty shell cannot pass either."""
    got = _verdict(0)
    assert got["pass"] is False, got
    assert got["verdict"] == "FAIL"


# ──────────── the proof that the rejected candidates ARE size tests ──────────

@pytest.mark.parametrize("label", sorted(REJECTED_QUANTITIES))
def test_each_rejected_quantity_would_have_flagged_the_control(label):
    """This is why the choice is what it is, asserted rather than asserted-in-
    prose: on the control design each rejected quantity is 0, so the `>= 1`
    rule we ship would have failed a perfectly real block had it been keyed
    there. Port count is 2 on the same design."""
    assert MEASURED["constant"][label] == 0
    assert MEASURED["constant"]["port"] >= 1
    assert MEASURED["real"][label] >= 1, (
        "sanity: the quantity is non-zero on an ordinary design, so it is only "
        "the CONTROL that exposes it as a size test")


def test_the_emitting_tcl_is_unguarded_so_absence_fails_closed():
    """The Tcl must NOT wrap the emission in an existence test. If
    utl::metric_integer were missing, a guarded emission would silently produce
    no metric and the run would look merely 'unmeasured but fine'; unguarded,
    the metric is absent and absence FAILS."""
    tcl = _js("m.staEvidenceTcl()")
    assert LINK_METRIC in tcl and "get_ports" in tcl
    assert "info commands" not in tcl and "catch" not in tcl, (
        f"the linkage-metric emission became conditional: {tcl!r}")
