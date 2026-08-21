"""Regression test for ORGANIC #628.

The Phase-1 backticked-interface port walker (`_v455_interface_pins`) and
its merge pass (`_v455_sanitize_and_merge_pins`) bypassed the existing
#475 token-class guards. A markdown heading whose text merely CONTAINS a
port-vocabulary substring (notably the 'I/O' inside '### 9.1.3 I/O delay')
opens a port-context range over a PROSE bullet. The walker then promoted
every backticked identifier in that bullet as a `mode=input` top-level
port — including SDC-directive keywords (`set_input_delay`,
`set_output_delay`) and stdcell-library names (`sky130_fd_sc_hd`).

The fix wires the existing chip-AGNOSTIC `_is_real_port_token` /
`_is_sdc_directive_token` / `_is_stdcell_lib_shape_token` SHAPE guards
into both the per-token walker loop and the merge pass.

These tests invoke the REAL program entry points on a synthetic defect
fixture shaped like the 現象, assert the phantom ports are gone, AND
include NEGATIVE no-leak cases proving legitimate ports still survive.
"""

import os
import sys

import pytest

_PROG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROG_DIR not in sys.path:
    sys.path.insert(0, _PROG_DIR)

import phase1_doc_one_shot_runner as P  # noqa: E402


# A markdown PROSE bullet under a heading whose text merely CONTAINS the
# 'I/O' substring (matches the i/?o alternative in the port-heading regex)
# — the exact shape from the issue's L9 constraints doc.
_DEFECT_DOC = """# 9 Constraints / Floorplan

### 9.1.3 I/O delay

- Apply `set_input_delay` and `set_output_delay` relative to the system
  clock; the target standard-cell library is `sky130_fd_sc_hd`.
"""

_JUNK_TOKENS = {"set_input_delay", "set_output_delay", "sky130_fd_sc_hd"}


def test_heading_substring_still_opens_a_port_context_range():
    """Sanity: the 'I/O delay' heading DOES open a port-context range —
    so the defect surface is genuinely reached and the fix is what stops
    promotion (not a side effect of the range never matching)."""
    ranges = P._port_context_heading_ranges(_DEFECT_DOC)
    assert ranges, "expected the 'I/O delay' heading to open a range"


def test_v455_walker_drops_sdc_and_stdcell_tokens():
    """REAL walker on the defect fixture must NOT promote the SDC /
    stdcell tokens as ports."""
    extracted = {"L9_constraints_floorplan.md": _DEFECT_DOC}
    names = {p["name"] for p in P._v455_interface_pins(extracted)}
    assert not (names & _JUNK_TOKENS), (
        f"phantom SDC/stdcell ports leaked: {names & _JUNK_TOKENS}")
    # nothing else legitimate is in that prose bullet, so it should be empty
    assert names == set(), f"unexpected promoted tokens: {names}"


def test_v455_merge_drops_sdc_and_stdcell_tokens():
    """The merge pass must not re-introduce the junk tokens."""
    extracted = {"L9_constraints_floorplan.md": _DEFECT_DOC}
    merged = P._v455_sanitize_and_merge_pins([], extracted)
    names = {p["name"] for p in merged}
    assert not (names & _JUNK_TOKENS), (
        f"merge pass leaked SDC/stdcell ports: {names & _JUNK_TOKENS}")


def test_merge_drops_incoming_sdc_stdcell_pins_keeps_real_port():
    """Defence-in-depth: even an incoming pin (from some other walker
    path) that carries an SDC-directive / stdcell SHAPE is dropped by the
    merge pass, while a legitimate co-located port is preserved."""
    incoming = [
        {"name": "clk", "mode": "input",
         "_extraction": "backticked_interface_v455"},
        {"name": "set_max_delay", "mode": "input",
         "_extraction": "backticked_interface_v455"},
        {"name": "sky130_fd_sc_hd", "mode": "input",
         "_extraction": "backticked_interface_v455"},
    ]
    merged = P._v455_sanitize_and_merge_pins(
        incoming, {"x": "no port context section here"})
    names = {p["name"] for p in merged}
    assert "clk" in names, "legitimate incoming port wrongly dropped"
    assert "set_max_delay" not in names
    assert "sky130_fd_sc_hd" not in names


# ----------------------------- NO-LEAK half -----------------------------

def test_no_leak_real_bullet_interface_ports_survive():
    """NEGATIVE no-leak: a genuine bullet-list interface (the shape this
    walker is meant to serve) must STILL promote its real ports — the
    guard relaxes NOTHING for legitimate input."""
    good = """## I/O Interface

- `clk` (input): system clock
- `rst_n` (input): active-low reset
- `data_out` (output): result bus
"""
    names = {p["name"] for p in P._v455_interface_pins({"L1.md": good})}
    assert {"clk", "rst_n", "data_out"} <= names, (
        f"legitimate ports were over-pruned: {names}")


def test_no_leak_empty_and_foreign_docs_yield_nothing():
    """NEGATIVE no-leak: an empty / foreign doc must STILL produce no
    ports (the floor is not relaxed so far that junk passes)."""
    assert P._v455_interface_pins({"e": ""}) == []
    assert P._v455_interface_pins(
        {"f": "The quick brown fox. No ports here at all."}) == []
    # merge pass on empty input is also empty
    assert P._v455_sanitize_and_merge_pins([], {"e": ""}) == []


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
