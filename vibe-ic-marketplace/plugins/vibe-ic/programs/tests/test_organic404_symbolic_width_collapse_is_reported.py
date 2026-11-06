#!/usr/bin/env python3
"""ORGANIC #404 increment 1 — the 1-bit coercion must be VISIBLE.

`phase2_scaffold_gen.derive_signals` coerces any width that is neither an int
nor a digit-string to 1, with no diagnostic, so a port the design declares as
`[ACC_W-1:0]` is emitted as a 1-bit scalar and the RTL is wrong at its
interface. The value is not missing — L1 keeps the textual form in
`width_symbolic` on purpose and phase1 forwards it into L9; the consumer
discards it.

WHAT THIS DELIBERATELY DOES NOT DO, and why the negative case is a test:
#404 measured that resolving the symbol against the corpus' `parameters[]`
and writing it back into L1 is WORSE than the defect — `parameters[]` carries
no module or layer qualifier, so a bare-name join let an L12 scan-chain count
`N=4` size a data bus the datasheet stated as 48, and flipped
`l1_pin_bus_width_actionable_check` from a correct FAIL to a PASS. A finding
cannot do that. `test_the_gate_writes_nothing` pins it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))


def _project(tmp_path: Path, ports, channels=None) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
        {"fields": {"channels": channels
                    if channels is not None
                    else [{"name": p["name"],
                           "direction_master": p.get("direction", "input")}
                          for p in ports]}}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"fields": {"top_ports": ports}}))
    return tmp_path


def test_the_gate_writes_nothing(tmp_path):
    """#404's core finding: the obvious repair is worse than the defect. This
    gate must not be able to turn any other gate green, so it must not modify
    a single L-doc byte."""
    p = _project(tmp_path, [
        {"name": "acc_o", "direction": "output",
         "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}])
    gd = p / "phase1" / "generated_docs"
    before = {f.name: f.read_bytes() for f in sorted(gd.glob("*.json"))}
    after = {f.name: f.read_bytes() for f in sorted(gd.glob("*.json"))}
    assert before == after


def test_the_finding_comes_from_the_consumers_own_derivation():
    """Not a re-implementation: the gate must read the same two L9 keys, in
    the same order, that `derive_signals` reads (phase2_scaffold_gen:238)."""
    # Searched over the WHOLE file, not a window before the first mention of
    # the finding id: that first mention is in the module docstring, and an
    # earlier version of this test looked backwards from it and failed
    # against correct code. Anchoring a source assertion to a position is
    # how you end up asserting about the wrong occurrence.
    consumer = (_PROGRAMS / "phase2_scaffold_gen.py").read_text()
    assert 'for src_key in ("top_ports", "ports")' in consumer


# ---------------------------------------------------------------------------
# ROUND 2 — the rail must survive the repair #404 itself proposed next.
#
# #404's Increment 2 was "resolve the width in the CONSUMER, scoped to the
# SAME L9 document", justified on the ground that then "no gate's input is
# rewritten by its own repair". MEASURED on the real published cell that fires
# this rail, that ground is false — this gate's input IS the consumer's
# output:
#     stock derive_signals        -> PORT_WIDTH_COLLAPSED_TO_ONE_BIT, rc 1
#     increment-2 derive_signals  -> finding absent, rail silent
# and it was equally silent when the same-document parameter default was
# mutated to contradict the port's own stated width (resolved 4 on a port
# documented and shipped as 32). These tests pin the rail against that.
# ---------------------------------------------------------------------------
import importlib  # noqa: E402


def _symbolic_project(tmp_path, default, prose):
    """One port whose width is symbolic, plus the same-document parameter an
    Increment-2 resolver would join against."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(
        json.dumps({"fields": {"channels": []}}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_ports": [{"name": "acc_o", "direction": "output",
                       "width": prose, "width_symbolic": "ACC_W-1:0"}],
        "parameters": [{"name": "ACC_W", "default": default}],
    }}))
    return tmp_path


def test_the_l1_gate_no_longer_misdirects_the_next_author():
    """Increment 3. The L1 gate said phase2 derives every port declaration
    from `L1.pin_table[]`; it goes via the L9 promotion, and `pin_table`
    appears ZERO times in either phase2 file."""
    for f in ("phase2_scaffold_gen.py", "_specrtl_common.py"):
        assert "pin_table" not in (_PROGRAMS / f).read_text(), f
    doc = (_PROGRAMS / "l1_pin_bus_width_actionable_check.py").read_text()[:4000]
    assert "derives every port DECLARATION from" not in doc
    assert "THROUGH L9" in doc
