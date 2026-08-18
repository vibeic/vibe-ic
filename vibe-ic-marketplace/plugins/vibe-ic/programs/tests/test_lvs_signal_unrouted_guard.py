#!/usr/bin/env python3
"""LVS honesty guard — a signal-UNROUTED DEF must not be mis-reported as a
design SIGNAL_NET_MISMATCH.

Root cause (found live on opentitan_aes_e2e — 517 top ports, 39,780 nets):
the runner's `_def_has_routing` counts POWER routing (SPECIALNETS straps) as
"routed", so a DEF that carries only power straps + placed cells — with its
SIGNAL interconnect never written to THIS DEF (write_def ran before/without
detailed_route, or the routing was streamed only to the GDS/ODB) — sails
through and gets extracted. Magic ext2spice then produces an interconnect-less
netlist whose EVERY signal net is disconnected, and the DEF-direct netgen
compare reports a flood of pin/net mismatches that LOOK like a design
SIGNAL_NET_MISMATCH but are really a ROUTING / DEF-writing gap.

`_def_signal_routing_stats` scans ONLY the NETS (signal) section — never
SPECIALNETS — so it distinguishes a genuinely-routed DEF (thousands of
`+ ROUTED`/`+ NEW` signal markers) from a signal-unrouted one (zero). These
tests pin the deterministic classifier and the exact gap the fix closes:
a power-only DEF is `_def_has_routing`-True but `_def_signal_routing_stats`
signal-unrouted. chip-AGNOSTIC synthetic fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402


# ── synthetic DEFs ──────────────────────────────────────────────────────────
# A signal-UNROUTED DEF: power SPECIALNETS (a `+ ROUTED` power strap) + many
# connectivity-only signal nets (no `+ ROUTED`/`+ NEW` in the NETS section).
def _unrouted_def(n_sig_nets: int) -> str:
    head = (
        "VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
        "SPECIALNETS 2 ;\n"
        "    - VGND ( _1_ VNB ) + USE GROUND\n"
        "      + ROUTED met5 1600 + SHAPE STRIPE ( 100 100 ) ( 900 100 ) ;\n"
        "    - VPWR ( _1_ VPB ) + USE POWER\n"
        "      + ROUTED met5 1600 + SHAPE STRIPE ( 100 200 ) ( 900 200 ) ;\n"
        "END SPECIALNETS\n"
        f"NETS {n_sig_nets} ;\n")
    body = "".join(
        f"    - net{i} ( _a{i}_ Y ) ( _b{i}_ A ) + USE SIGNAL ;\n"
        for i in range(n_sig_nets))
    return head + body + "END NETS\nEND DESIGN\n"


# A genuinely-routed DEF: the NETS section carries `+ ROUTED`/`+ NEW` wiring.
def _routed_def(n_sig_nets: int) -> str:
    head = (
        "VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "SPECIALNETS 1 ;\n"
        "    - VPWR ( _1_ VPB ) + USE POWER\n"
        "      + ROUTED met5 1600 + SHAPE STRIPE ( 100 200 ) ( 900 200 ) ;\n"
        "END SPECIALNETS\n"
        f"NETS {n_sig_nets} ;\n")
    body = "".join(
        f"    - net{i} ( _a{i}_ Y ) ( _b{i}_ A ) + USE SIGNAL\n"
        f"      + ROUTED met1 ( {i} 100 ) ( {i} 900 ) ;\n"
        for i in range(n_sig_nets))
    return head + body + "END NETS\nEND DESIGN\n"


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "x.def"
    p.write_text(text)
    return p


# ── classifier ──────────────────────────────────────────────────────────────
def test_unrouted_signal_def_detected(tmp_path):
    routed, nets = R._def_signal_routing_stats(_write(tmp_path, _unrouted_def(40)))
    assert routed is False
    assert nets == 40


def test_routed_signal_def_detected(tmp_path):
    routed, _ = R._def_signal_routing_stats(_write(tmp_path, _routed_def(40)))
    assert routed is True


def test_power_only_def_is_has_routing_TRUE_but_signal_unrouted(tmp_path):
    # THE GAP THE FIX CLOSES: `_def_has_routing` says routed (power straps),
    # but the signal-aware classifier correctly says signal-unrouted.
    p = _write(tmp_path, _unrouted_def(40))
    assert R._def_has_routing(p) is True                     # power straps → True
    routed, nets = R._def_signal_routing_stats(p)
    assert routed is False and nets == 40                    # signal → unrouted


def test_specialnets_power_routing_not_miscounted(tmp_path):
    # The power SPECIALNETS `+ ROUTED` strap must NOT be counted as signal
    # routing — only the NETS section participates.
    routed, _ = R._def_signal_routing_stats(_write(tmp_path, _unrouted_def(20)))
    assert routed is False


def test_new_marker_counts_as_signal_routing(tmp_path):
    d = ("DESIGN t ;\nNETS 20 ;\n"
         + "".join(f"    - n{i} ( _a{i}_ Y ) + USE SIGNAL ;\n" for i in range(19))
         + "    - n19 ( _a_ Y ) + USE SIGNAL\n"
           "      + ROUTED met1 ( 0 0 ) ( 0 100 )\n"
           "      NEW met2 ( 0 100 ) ( 100 100 ) ;\n"
         + "END NETS\nEND DESIGN\n")
    routed, _ = R._def_signal_routing_stats(_write(tmp_path, d))
    assert routed is True


def test_no_nets_header_is_failsafe_not_blocked(tmp_path):
    # A DEF with no NETS header cannot be classified → fail-safe (do not block).
    d = "DESIGN t ;\nSPECIALNETS 0 ;\nEND SPECIALNETS\nEND DESIGN\n"
    routed, nets = R._def_signal_routing_stats(_write(tmp_path, d))
    assert routed is True and nets == 0


def test_missing_file_is_failsafe(tmp_path):
    routed, nets = R._def_signal_routing_stats(tmp_path / "nope.def")
    assert routed is True and nets == 0


# ── guard-firing threshold ──────────────────────────────────────────────────
def test_guard_fires_only_above_min_signal_nets(tmp_path):
    th = R._LVS_MIN_SIGNAL_NETS_FOR_ROUTING_CHECK
    # below threshold: unrouted but too trivial → guard must NOT fire
    routed_lo, nets_lo = R._def_signal_routing_stats(
        _write(tmp_path, _unrouted_def(th - 1)))
    assert routed_lo is False and nets_lo == th - 1
    assert not ((not routed_lo) and nets_lo >= th)          # guard would NOT fire
    # at threshold: unrouted and substantial → guard MUST fire
    routed_hi, nets_hi = R._def_signal_routing_stats(
        _write(tmp_path, _unrouted_def(th)))
    assert (not routed_hi) and nets_hi >= th                # guard WOULD fire


def test_routed_def_never_fires_guard(tmp_path):
    th = R._LVS_MIN_SIGNAL_NETS_FOR_ROUTING_CHECK
    routed, _ = R._def_signal_routing_stats(_write(tmp_path, _routed_def(th * 4)))
    assert routed is True                                   # → guard never fires


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
