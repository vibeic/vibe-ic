from __future__ import annotations


import sys


from pathlib import Path


import pytest


_PROGRAMS = Path(__file__).resolve().parents[1]


if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


import _gate_denominator as _gd  # noqa: E402


def test_a_vacuity_with_no_written_reason_did_not_come_from_the_gate(tmp_path):
    """`Denominator.__post_init__` RAISES on a zero denominator with no
    `not_applicable_reason`, so a report in that shape cannot have been emitted
    by the gate — and the reason is the only thing a human reviewing the waiver
    would read."""
    _waive(tmp_path)
    for value in ("", "   ", None, 7, _DROP):
        _si_contradictory(
            tmp_path,
            {"summary.denominator.not_applicable_reason": value})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"reason={value!r}"
        assert _rc(tmp_path) == 1
    # ...and the emitter's own type agrees, so this is not a rule invented here
    with pytest.raises(ValueError):
        _gd.Denominator(unit="u", examined=0, not_applicable_reason="")
