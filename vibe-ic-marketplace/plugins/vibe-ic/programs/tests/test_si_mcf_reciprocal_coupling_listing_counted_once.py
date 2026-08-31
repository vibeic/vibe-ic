#!/usr/bin/env python3
"""A physical coupling cap listed in BOTH coupled nets' *CAP sections must be
counted ONCE.

Measured defect (subservient_gf180mcuD_20260831_e1, plugin v1.14.22): OpenROAD's
SPEF lists each of 14705 physical coupling caps twice (29410 lines), parse_spef
accumulated both, so every Cc and pair_cc came out 2x. si_mcf_sta then folded
55.79 pF instead of 27.89 pF at MCF=2 and reported worst setup slack -4.6706 ns
on a design whose correctly-bounded slack is +0.6440 ns -> a fabricated FAIL.
si_mcf_sta_check said PASS because its "independent" recount reads through the
same parse.

NEGATIVE CONTROL: test_reciprocal_listing_is_not_double_counted FAILS against the
pre-fix parse (it returns 2.0e-4, not 1.0e-4). Verified by running this file
against the unpatched module.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from si_signoff_timing_aware import parse_spef  # noqa: E402

_HEADER = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 na
*2 nb

"""

# The SAME physical Cc (nodes *1:1 / *2:1, value 1e-4) written into BOTH nets'
# *CAP sections -- exactly what OpenROAD emits.
RECIPROCAL = _HEADER + """*D_NET *1 0.0002
*CONN
*I *10:Z O *D INV
*I *11:A I *D INV
*CAP
1 *1:1 0.0001
2 *1:1 *2:1 0.0001
*END

*D_NET *2 0.0002
*CONN
*I *12:Z O *D INV
*I *13:A I *D INV
*CAP
1 *2:1 0.0001
2 *2:1 *1:1 0.0001
*END
"""

# The same circuit from an extractor that lists each Cc only ONCE.
SINGLE_LISTING = _HEADER + """*D_NET *1 0.0002
*CONN
*I *10:Z O *D INV
*I *11:A I *D INV
*CAP
1 *1:1 0.0001
2 *1:1 *2:1 0.0001
*END

*D_NET *2 0.0001
*CONN
*I *12:Z O *D INV
*I *13:A I *D INV
*CAP
1 *2:1 0.0001
*END
"""


def _pair(sp):
    assert len(sp["pair_cc"]) == 1, f"expected one coupled net-pair, got {sp['pair_cc']}"
    return next(iter(sp["pair_cc"].values()))


def test_reciprocal_listing_is_not_double_counted():
    """THE CONTROL. Pre-fix this returns 2e-4 and the assert fires."""
    got = _pair(parse_spef(RECIPROCAL))
    assert abs(got - 1.0e-4) < 1e-12, (
        f"pair_cc={got!r}: the reciprocal listing of ONE physical coupling cap "
        f"was counted twice (expected 1.0e-04, the single physical value)"
    )


def test_single_listing_spef_is_not_halved():
    """OVER-CORRECTION GUARD. Passes pre- AND post-fix by construction: a fix
    that merely halved every Cc would break THIS test while satisfying the
    control above. Both must hold."""
    got = _pair(parse_spef(SINGLE_LISTING))
    assert abs(got - 1.0e-4) < 1e-12, (
        f"pair_cc={got!r}: a SPEF that lists each Cc once must be left alone "
        f"(expected 1.0e-04)"
    )


def test_per_net_cc_is_not_double_counted():
    """pair_cc is not the only doubled structure: per-net cc[] is too, and
    si_mcf_sta_check derives its over-application CEILING from it, which is why
    the inflated fold slipped past the gate."""
    sp = parse_spef(RECIPROCAL)
    for net in ("*1", "*2"):
        assert abs(sp["cc"][net] - 1.0e-4) < 1e-12, (
            f"cc[{net}]={sp['cc'][net]!r}: expected 1.0e-04, the single physical "
            f"coupling this net carries"
        )


def test_listed_vs_physical_counts_are_disclosed():
    """The doubling was invisible because nothing reported both numbers. A
    consumer that prints a coupling count must be able to say WHICH it means.
    Written with getattr-style access so the PRE-FIX module reaches the assert
    (and fails on the missing disclosure) instead of raising KeyError."""
    sp = parse_spef(RECIPROCAL)
    listed = sp.get("coupling_caps_listed")
    physical = sp.get("coupling_caps_physical")
    assert listed == 2, f"coupling_caps_listed={listed!r}, expected 2 *CAP lines"
    assert physical == 1, f"coupling_caps_physical={physical!r}, expected 1 cap"

    sp1 = parse_spef(SINGLE_LISTING)
    assert sp1.get("coupling_caps_listed") == 1
    assert sp1.get("coupling_caps_physical") == 1
