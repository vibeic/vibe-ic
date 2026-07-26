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
GATE = _PROGRAMS / "l17_channel_catalog_consumer_contract_check.py"


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


def _run(project: Path):
    r = subprocess.run([sys.executable, str(GATE), str(project)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_a_symbolic_width_port_is_reported(tmp_path):
    rc, out = _run(_project(tmp_path, [
        {"name": "acc_o", "direction": "output",
         "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}]))
    assert rc == 1
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" in out
    assert "acc_o" in out


def test_a_non_numeric_width_string_is_reported(tmp_path):
    """The other carrier: L1 sometimes lands a whole prose sentence in
    `width`. That coerces to 1 exactly the same way."""
    rc, out = _run(_project(tmp_path, [
        {"name": "d_o", "direction": "output",
         "width": "the accumulator is 48 bits in this configuration"}]))
    assert rc == 1 and "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" in out


def test_a_genuine_one_bit_port_is_not_reported(tmp_path):
    """The paired half. Reporting every width==1 port would fire on every
    clock, reset and enable in every design — a gate nobody can act on."""
    rc, out = _run(_project(tmp_path, [
        {"name": "en", "direction": "input", "width": 1},
        {"name": "ok", "direction": "output", "width": "8"}]))
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" not in out
    assert rc == 0


def test_a_digit_string_width_is_not_a_collapse(tmp_path):
    """`"8"` is a digit-string: derive_signals keeps it, so there is nothing
    to report. Only widths the consumer actually threw away count."""
    rc, out = _run(_project(tmp_path, [
        {"name": "bus_o", "direction": "output", "width": "16"}]))
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" not in out


def test_the_gate_writes_nothing(tmp_path):
    """#404's core finding: the obvious repair is worse than the defect. This
    gate must not be able to turn any other gate green, so it must not modify
    a single L-doc byte."""
    p = _project(tmp_path, [
        {"name": "acc_o", "direction": "output",
         "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}])
    gd = p / "phase1" / "generated_docs"
    before = {f.name: f.read_bytes() for f in sorted(gd.glob("*.json"))}
    _run(p)
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
    src = GATE.read_text()
    assert 'for _key in ("top_ports", "ports")' in src
    consumer = (_PROGRAMS / "phase2_scaffold_gen.py").read_text()
    assert 'for src_key in ("top_ports", "ports")' in consumer


def test_the_l1_gate_no_longer_misdirects_the_next_author():
    """Increment 3. The L1 gate said phase2 derives every port declaration
    from `L1.pin_table[]`; it goes via the L9 promotion, and `pin_table`
    appears ZERO times in either phase2 file."""
    for f in ("phase2_scaffold_gen.py", "_specrtl_common.py"):
        assert "pin_table" not in (_PROGRAMS / f).read_text(), f
    doc = (_PROGRAMS / "l1_pin_bus_width_actionable_check.py").read_text()[:4000]
    assert "derives every port DECLARATION from" not in doc
    assert "THROUGH L9" in doc
