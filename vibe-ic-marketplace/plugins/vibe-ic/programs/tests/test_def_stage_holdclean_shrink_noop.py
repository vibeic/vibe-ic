"""def_stage_progression_check Check-2 (`size-non-monotone`) false-FAILed a
legitimate no-op hold pass that came back a few bytes SMALLER.

Check 1 already exempts the BYTE-IDENTICAL post_cts/post_hold pair when the
hold report proves the design was hold-clean (ORGANIC #624): a hold-clean
design gives the hold-fix step nothing to repair, so it inserts ZERO buffers
and the DEF does not change. This is the same no-op one step along — the
rewrite can also come back marginally SMALLER (net/component re-ordering, a
dropped redundant entry) rather than byte-identical, and strict byte
monotonicity then reports fraud on a correct run.

OBSERVED (spm x gf180mcuD, 2026-07-22): post_hold.def 138,422 B vs
post_cts.def 138,429 B — a 7-byte (0.005%) shrink from a zero-buffer hold pass
at +0.98 ns hold slack. Step 21 Routing FAILed on an otherwise-converged
design (DRC 0, LVS match, STA met).

Fix: exempt a shrink ONLY on the post_cts -> post_hold transition, ONLY with
positive hold-clean proof, and ONLY within a 1% tolerance.

POSITIVE: small shrink + hold-clean report -> no size-non-monotone finding.

NEGATIVE no-leak — each of these must STILL FAIL:
  - the same shrink with UNREPAIRED hold violations (negative slack);
  - the same shrink with NO hold report at all (fail-closed);
  - a shrink on any OTHER stage pair, even with a clean hold report;
  - a GROSS (>1%) shrink on post_cts -> post_hold even when hold is clean —
    the signature of a truncated DEF, which a blanket percentage tolerance
    applied to every transition would have let through.

chip-AGNOSTIC: keyed on OpenROAD's own hold-slack number plus the exact stage
pair; no chip literal, no PDK literal.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import def_stage_progression_check as D  # noqa: E402
import _path_layout as _pl  # noqa: E402


def _def_text(n_components: int, pad: int) -> str:
    """A syntactically plausible DEF whose byte size is tunable via `pad`.

    `pad` rides in a comment so the COMPONENTS count (Check 3) and the routing
    marker (Check 5) stay under independent control of the caller.
    """
    body = ["COMPONENTS %d ;" % n_components]
    body += ["  - U_%d AND2X1 + PLACED ( %d %d ) N ;" % (i, i * 100, i * 100)
             for i in range(n_components)]
    body.append("END COMPONENTS")
    return "\n".join(body) + "\n# pad " + ("x" * pad) + "\n"


def _routed_text(n_components: int, pad: int) -> str:
    return (_def_text(n_components, pad)
            + "SPECIALNETS 1 ;\n- VDD + ROUTED met1 ( 0 0 ) ( 10 0 )\n"
              "END SPECIALNETS\n")


def _mk(tmp_path, *, hold_rpt, cts_pad, hold_pad,
        floorplan_pad=0, placed_pad=200):
    """Write a full 5-stage DEF set with controlled sizes.

    Every stage has a DISTINCT sha256 (so Check 1 never fires) and the
    instance count grows floorplan -> routed (so Check 3 never fires), which
    isolates Check 2 as the only thing under test.
    """
    pnr = _pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "floorplan.def").write_text(_def_text(2, floorplan_pad))
    (pnr / "placed.def").write_text(_def_text(3, placed_pad))
    (pnr / "post_cts.def").write_text(_def_text(4, cts_pad))
    (pnr / "post_hold.def").write_text(_def_text(4, hold_pad))
    (pnr / "routed.def").write_text(_routed_text(5, hold_pad + 500))
    if hold_rpt is not None:
        (pnr / "post_hold_timing.rpt").write_text(hold_rpt)
    return tmp_path


def _nonmonotone(tmp_path):
    _infos, finds = D.inspect(tmp_path)
    return [f for f in finds if f.rule == "size-non-monotone"]


def _sizes(tmp_path):
    pnr = _pl.pnr_dir(tmp_path)
    return {s: (pnr / f"{s}.def").stat().st_size
            for s in ("post_cts", "post_hold")}


_CLEAN = "worst hold slack 0.98\nhold WNS 0.98\n"
_DIRTY = "worst hold slack -0.031\n"


# --------------------------------------------------------------- POSITIVE ---

def test_small_shrink_with_holdclean_report_is_not_a_finding(tmp_path):
    """The measured case: a few bytes smaller at positive hold slack."""
    _mk(tmp_path, hold_rpt=_CLEAN, cts_pad=1000, hold_pad=993)
    sz = _sizes(tmp_path)
    assert sz["post_hold"] < sz["post_cts"], "fixture must actually shrink"
    assert sz["post_cts"] - sz["post_hold"] == 7, "fixture is the 7-byte case"
    assert _nonmonotone(tmp_path) == []


def test_inf_hold_slack_counts_as_clean(tmp_path):
    """No hold paths at all (inf) is hold-clean, same as #624 treats it."""
    _mk(tmp_path, hold_rpt="worst hold slack inf\n",
        cts_pad=1000, hold_pad=995)
    assert _nonmonotone(tmp_path) == []


def test_equal_size_still_passes(tmp_path):
    """Non-decreasing was always allowed; that must not regress."""
    _mk(tmp_path, hold_rpt=_CLEAN, cts_pad=1000, hold_pad=1000)
    assert _nonmonotone(tmp_path) == []


def test_growth_still_passes(tmp_path):
    _mk(tmp_path, hold_rpt=_CLEAN, cts_pad=1000, hold_pad=2000)
    assert _nonmonotone(tmp_path) == []


# ------------------------------------------------- NEGATIVE / NO-LEAK -------

def test_shrink_with_unrepaired_hold_violations_still_fails(tmp_path):
    """Negative hold slack -> no exemption."""
    _mk(tmp_path, hold_rpt=_DIRTY, cts_pad=1000, hold_pad=993)
    assert _nonmonotone(tmp_path) != []


def test_shrink_with_no_hold_report_still_fails(tmp_path):
    """Fail-closed: absent evidence is not evidence of a clean no-op."""
    _mk(tmp_path, hold_rpt=None, cts_pad=1000, hold_pad=993)
    assert _nonmonotone(tmp_path) != []


def test_shrink_with_unparseable_hold_report_still_fails(tmp_path):
    _mk(tmp_path, hold_rpt="the router did some things\n",
        cts_pad=1000, hold_pad=993)
    assert _nonmonotone(tmp_path) != []


def test_gross_shrink_on_exempt_pair_still_fails(tmp_path):
    """A truncated post_hold.def is NOT excused by a clean hold report.

    This is the case a blanket percentage tolerance applied to every stage
    transition would have admitted. Here the shrink is far beyond a
    re-ordering, so it still FAILs.
    """
    _mk(tmp_path, hold_rpt=_CLEAN, cts_pad=4000, hold_pad=0)
    sz = _sizes(tmp_path)
    assert sz["post_hold"] < sz["post_cts"] * 0.99, "fixture must be gross"
    assert _nonmonotone(tmp_path) != []


def test_shrink_on_a_different_stage_pair_still_fails(tmp_path):
    """Only post_cts -> post_hold is exempt, even with a clean hold report.

    Here placed.def is smaller than floorplan.def — a different transition —
    which must still be reported however clean hold is.
    """
    _mk(tmp_path, hold_rpt=_CLEAN, cts_pad=5000, hold_pad=5000,
        floorplan_pad=3000, placed_pad=0)
    finds = _nonmonotone(tmp_path)
    assert finds != []
    assert any("placed.def" in f.message for f in finds)
