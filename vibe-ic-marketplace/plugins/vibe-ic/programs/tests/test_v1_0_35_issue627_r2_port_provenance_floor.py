"""Round-2 regression for ORGANIC #627 — the v455 walker (round-1, v1.0.25)
correctly recovered single-letter datapath ports x/y/p into L1.pin_table, but on
the L1→L9 promotion path `_is_real_port_token()`'s v0.1.86 1-char floor
(`if len(tok) < 2: return False`) dropped them AGAIN, with NO port-table-
provenance exemption — so `l9_rtl_pin_consistency_check` still FAILed
"RTL top (spm.v) has ports not in L9: [p, x, y]".

Field-agent reopen counter-evidence (verbatim shape):
  _is_real_port_token('x'/'y'/'p', pin={_extraction:'backticked_interface_v455'})
  → False for all three despite carrying port-table provenance.

Fix: extend the same #611-style `_PORT_TABLE_STRATEGIES` provenance exemption
already applied to the version-code rejector to the 1-char floor —
`if len(tok) < 2 and not _has_port_table_provenance: return False`.

NEGATIVE no-leak: a 1-char token WITHOUT port-table provenance (a bare prose
glyph) must STILL be dropped.

chip-AGNOSTIC: provenance flag, no chip/vendor/SKU literal.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

_PORT_TABLE_PIN = {"_extraction": "backticked_interface_v455"}


@pytest.mark.parametrize("tok", ["x", "y", "p", "a", "b", "q"])
def test_single_letter_port_with_table_provenance_kept(tok):
    """The exact reopen repro: a 1-char datapath port carrying port-table
    provenance is a REAL port, not dropped by the length floor."""
    assert R._is_real_port_token(tok, pin=_PORT_TABLE_PIN) is True


@pytest.mark.parametrize("tok", ["x", "y", "z", "p"])
def test_single_letter_without_provenance_still_dropped_NOLEAK(tok):
    """A 1-char token WITHOUT port-table provenance (prose glyph) is still
    dropped — the exemption is scoped to enumerated port-table tokens."""
    assert R._is_real_port_token(
        tok, pin={"_extraction": "narrative_fallback"}) is False
    # no pin at all → no provenance → dropped
    assert R._is_real_port_token(tok) is False


def test_two_char_control_ports_unchanged_NOLEAK():
    """The v0.1.86 2-char recovery (cs/we/oe…) is unaffected."""
    for tok in ("cs", "we", "oe", "en"):
        assert R._is_real_port_token(
            tok, pin={"_extraction": "narrative_fallback"}) is True


def test_provenance_strategy_set_membership():
    """`backticked_interface_v455` IS a port-table-provenance strategy — the
    flag the exemption keys on."""
    assert "backticked_interface_v455" in R._PORT_TABLE_STRATEGIES


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
