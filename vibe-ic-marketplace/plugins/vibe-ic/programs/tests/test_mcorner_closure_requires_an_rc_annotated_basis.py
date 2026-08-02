#!/usr/bin/env python3
"""`timing_closed_multi_corner` must not be true on a netlist-only STA.

MEASURED (subservient x sky130A, plugin v1.9.59, image ghcr.io/vibeic/vibeic-eda:0.2.52):
`detailed_route` aborted with `[ERROR DRT-0218] Guide is not connected to
design` on 2 nets. The flow swallowed it (`DETAILED_ROUTE_NONFATAL`) and
continued. Consequences, all measured on that run:

  * every DEF the flow wrote carried 0 signal-net routing (PDN SPECIALNETS
    only) -- floorplan/placed/post_cts/post_hold/routed/filled/<top>.def
  * 0 SPEF files were produced anywhere in the run
  * `sta_mcorner_ocv.rpt` stamped its own banner `SPEF=no-SPEF (netlist-only)`
    and reported `clock network delay (ideal)`
  * `mcorner_ocv_stance.json` nonetheless published
        setup_worst_slack_ns 2.51, hold_worst_slack_ns 0.25,
        violated_corners [], timing_closed_multi_corner TRUE
    beside a disclosure asserting "SETUP @ SS process (slow) + max-RC"

LVS was the ONLY gate that refused (`LVS_INPUT_DEF_SIGNAL_UNROUTED`, #477).
STA, DRC and GDS all reported PASS on a design with no interconnect.

`timing_closed_multi_corner` was `mc_ocv_ok and not _viol` -- a report exists
and no slack is negative. Neither term asks whether the STA had parasitics.

BIDIRECTIONAL NEGATIVE CONTROL: `_closed()` reproduces the VERBATIM pre-fix
expression when the new basis reader is absent, so this file exercises pre-fix
BEHAVIOUR against the pre-fix tree and fails there.

chip/PDK/vendor-AGNOSTIC: pure text on the banner this module writes.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as p3  # noqa: E402


def _banner(setup_spef: str, hold_spef: str) -> str:
    return (f"=== SETUP corner: process=SS liberty=/p/ss.lib, "
            f"SPEF={setup_spef} ===\n"
            f"worst slack max 2.51\n"
            f"=== HOLD corner: process=FF liberty=/p/ff.lib, "
            f"SPEF={hold_spef} ===\n"
            f"worst slack min 0.25\n")


NETLIST_ONLY = _banner("no-SPEF (netlist-only)", "no-SPEF (netlist-only)")
RC_ANNOTATED = _banner("max.spef", "min.spef")
MIXED = _banner("max.spef", "no-SPEF (netlist-only)")


def _closed(rpt_text: str, mc_ocv_ok: bool = True,
            viol: list | None = None) -> bool:
    """What the module publishes as `timing_closed_multi_corner`."""
    viol = viol or []
    fn = getattr(p3, "_mcorner_sta_rc_basis", None)
    if fn is None:
        # Pre-fix expression, copied verbatim from the emitter.
        return bool(mc_ocv_ok and not viol)
    basis = fn(rpt_text) if mc_ocv_ok else "unknown"
    return bool(mc_ocv_ok and not viol and basis not in ("netlist_only",
                                                        "mixed"))


# --- the measured subservient shape ---------------------------------------

def test_netlist_only_sta_does_not_publish_closure():
    assert _closed(NETLIST_ONLY) is False


def test_partially_annotated_sta_does_not_publish_closure():
    """One corner RC-annotated and one not is not multi-corner sign-off."""
    assert _closed(MIXED) is False


# --- the fix must not slander a real sign-off ------------------------------

def test_rc_annotated_and_met_still_publishes_closure():
    assert _closed(RC_ANNOTATED) is True


def test_rc_annotated_but_violated_still_reports_not_closed():
    assert _closed(RC_ANNOTATED, viol=["setup"]) is False


def test_absent_banner_leaves_the_prior_verdict_untouched():
    """UNMEASURED is not netlist-only: an older report keeps its verdict."""
    assert _closed("worst slack max 2.51\n") is True


# --- the basis reader itself ----------------------------------------------

def test_basis_reader_classifies_each_shape():
    fn = getattr(p3, "_mcorner_sta_rc_basis", None)
    if fn is None:
        pytest.fail("pre-fix tree: no basis reader (negative control)")
    assert fn(NETLIST_ONLY) == "netlist_only"
    assert fn(RC_ANNOTATED) == "rc_annotated"
    assert fn(MIXED) == "mixed"
    assert fn("") == "unknown"


def test_basis_is_published_alongside_the_slacks():
    """A reader must not have to open the report to learn the basis."""
    src = Path(p3.__file__).read_text(errors="replace")
    assert '"sta_rc_basis"' in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
