#!/usr/bin/env python3
"""Negative-control smoke tests for l8_clock_period_actionability_check.py.

EVERY fixture here is SYNTHESIZED neutral data. No real design's files
are copied, and no design name / PDK name / vendor part number / pin
literal from any real project appears. Ports are ``clk_a`` / ``clk_b``,
the "design" is ``fixture_core``.

The point of a negative control: a test that cannot fail proves nothing.
Each rule is asserted in BOTH directions —
  * gutted / mis-formed layer  => the gate FAILS (exit 1, named rule)
  * well-formed layer          => the gate PASSES (exit 0, no findings)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "l8_clock_period_actionability_check.py"
sys.path.insert(0, str(PROG.parent))
import sdc_gen  # noqa: E402








def _clock(name: str, mhz: float, primary: bool = True, **extra) -> dict:
    rec = {
        "name": name,
        "source_pin": name,
        "freq_mhz": mhz,
        "freq_hz": int(mhz * 1e6),
        "period_ns": 1000.0 / mhz,
        "domain_kind": "primary" if primary else "derived",
        "role": "master" if primary else "derived",
    }
    rec.update(extra)
    return rec


# ─────────────────────────── POSITIVE CONTROLS ───────────────────────────











# ══ THE NOT_MEASURED TIER ═════════════════════════════════════════════════
#
# 9320b0269 ("Fix scoped L8 clock consumer contracts") closed a real hole: an
# absent L8 used to announce `VACUOUS_PASS:` and read as a skip that costs
# nothing. It closed it with severity `ERROR` -> rc 1, and that contradicted
# the finding's OWN sentence, "this is NOT_MEASURED, not a vacuous pass".
#
# rc 1 is a live finding. This gate is wired `advisory_program_exit_zero` at
# step D1 but declares no `ENFORCEMENT:` in its docstring, so
# `flow_compliance_check._gate_is_two_source_advisory` reads it BLOCKING and
# the refusal took D1 down — MEASURED as three reds on main 2f230524b
# (`test_issue1446_incomplete_in_scope_is_not_green`, both arms).
#
# NOT_MEASURED has its own tier and it is neither of the two: `skip_kind`
# `zero-denominator` -> `_flow_reason_taxonomy.ZERO_DENOMINATOR` -> the
# `INCOMPLETE` set -> `DISCLOSED_INCOMPLETE`. Reported, printed, typed,
# carried — and NEVER promoted, because ZERO_DENOMINATOR is deliberately
# absent from `SKIP_ELIGIBLE`. These cases pin BOTH halves: the tier is not a
# FAIL, and it is not a pass.















def test_backend_consumer_selects_scope_before_unscoped_scalar():
    l8 = {"clock_mhz": 50.0, "clock_domains": [
        _clock("clk_a", 100.0, pdk_scoped_target="process_family_a"),
        _clock("clk_a", 25.0, pdk_scoped_target="process_family_b"),
    ]}
    assert sdc_gen._clock_mhz_from_l8_domains(l8, "process_family_a") == 100.0
    assert sdc_gen._clock_mhz_from_l8_domains(l8, "process_family_b") == 25.0
    assert sdc_gen._clock_mhz_from_l8_domains(l8, "process_family_c") is None


# ───────────────────────── NEGATIVE CONTROLS ─────────────────────────────

















# ───────────────────── BLOCK / ADVISE + ESCAPE HATCHES ───────────────────
