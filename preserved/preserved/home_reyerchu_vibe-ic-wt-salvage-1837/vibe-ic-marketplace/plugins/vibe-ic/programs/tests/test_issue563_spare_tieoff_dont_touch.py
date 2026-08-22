"""ORGANIC #563 r3 — the spare tie-off never connected anything, and the
tie-driver legalization never ran.

MEASURED ROOT CAUSE (spm x sky130A / ihp-sg13g2 / gf180mcuD, plugin 1.8.37;
reproduced in OpenROAD 26Q3-951-g92b079b47a):

`_build_spare_protection_tcl` applies `set_dont_touch` to every spare, and odb
REFUSES to connect an iterm of a dont_touch instance:

    [ERROR ODB-0369] Attempt to connect iterm of dont_touch instance spare_inverter_0

That RAISES. The tie-off connect loop and the `detailed_placement` that
re-legalizes the tie driver shared ONE `catch`, with the connect loop FIRST, so:

  * the tie-off connected NOTHING (net `spare_tielo` carried the driver and
    zero sinks), and
  * `detailed_placement` NEVER RAN, leaving `spare_tielo_drv` at the first
    spare's PRE-SNAP coordinates — off the site grid and below row 0.

One illegal instance then produced DPL-0006 -> DPL-0033, and on one PDK
cascaded to DRT-0073 / RCX-0134 / zero SPEF / a netlist-only post-route STA
that surfaced as a large SS setup violation. The reported defect was "timing";
the cause was placement, six steps upstream.

THE GENERAL LESSON these tests pin: a recovery step placed downstream of a
fragile step inside ONE catch is a recovery that does not run precisely when it
is needed.
"""
from pathlib import Path
import sys

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _plan():
    return {
        "instances": [
            {"name": "spare_dff_0", "type": "dff", "cell": "GENERIC_dfrtp_4",
             "llx": 13, "lly": 13, "keep": True},
            {"name": "spare_inv_0", "type": "inverter", "cell": "GENERIC_inv_4",
             "llx": 90, "lly": 60, "keep": True},
        ],
    }


def _tcl():
    return R._build_spare_postfix_tcl(
        _plan(), tie_lo_cell="GENERIC_conb_1", tie_lo_pin="LO")


# ── (a) the connect is possible at all ──────────────────────────────────────

def test_dont_touch_is_lifted_before_the_connect_and_restored_after():
    tcl = _tcl()
    assert "unset_dont_touch" in tcl, "dont_touch is never lifted → ODB-0369"
    lift = tcl.index("catch {unset_dont_touch $_sn}")
    connect = tcl.index("odb::dbITerm_connect $_it ")
    # anchor on the catch form: the bare substring "set_dont_touch $_sn" also
    # matches inside "unset_dont_touch $_sn".
    restore = tcl.index("catch {set_dont_touch $_sn}")
    assert lift < connect < restore, (
        "order must be lift → connect → restore; got "
        f"lift={lift} connect={connect} restore={restore}")


def test_each_iterm_connect_is_individually_guarded():
    """One refusal must not cost every later spare. The pre-fix shape had a
    single catch around the whole loop, so the first throw skipped the rest."""
    tcl = _tcl()
    assert "catch {odb::dbITerm_connect $_it $_tlnet}" in tcl
    assert "SPARE_TIEOFF_ITERM_NONFATAL" in tcl


# ── (b) THE STRUCTURAL FIX: legalization cannot be skipped ──────────────────

def test_detailed_placement_is_outside_the_tieoff_catch():
    """§4.05 core regression guard. `detailed_placement` must appear AFTER the
    tie-off catch closes, so a throw inside the tie-off can never skip it."""
    tcl = _tcl()
    catch_close = tcl.index("} _tie_err]}")
    dp = tcl.index("catch {detailed_placement}")
    assert dp > catch_close, (
        "detailed_placement is INSIDE the tie-off catch — a connect failure "
        "would skip the tie-driver legalization, which is the measured defect")


def test_legalization_reports_both_outcomes():
    """It must say which happened; a silent legalization is unfalsifiable."""
    tcl = _tcl()
    assert "SPARE_TIEOFF_LEGALIZE_NONFATAL" in tcl
    assert "SPARE_TIEOFF_LEGALIZED" in tcl


def test_no_tie_cell_still_emits_no_connects():
    """Unchanged behaviour when the PDK exposes no tie cell."""
    tcl = R._build_spare_postfix_tcl(_plan())
    assert "SPARE_TIEOFF_SKIPPED" in tcl
    assert "odb::dbITerm_connect" not in tcl
    assert "unset_dont_touch" not in tcl
    assert "SPARE_FIRM_LOCKED" in tcl


# ── (c) tied_off is MEASURED, not claimed ──────────────────────────────────

def test_tieoff_count_marker_is_emitted():
    assert "SPARE_TIEOFF_CONNECTED $_tie_n of $_tie_tot" in _tcl()


def test_measured_tieoff_complete(tmp_path):
    log = tmp_path / "openroad.log"
    log.write_text("blah\nSPARE_TIEOFF_CONNECTED 6 of 6\nSPARE_TIEOFF_DONE\n")
    m = R._spare_tieoff_measured_from_log(log)
    assert m["measured"] is True
    assert (m["connected"], m["candidates"]) == (6, 6)
    assert m["tied_off"] is True


def test_measured_tieoff_partial_is_not_tied_off(tmp_path):
    """A PARTIAL tie-off must not publish itself as complete."""
    log = tmp_path / "openroad.log"
    log.write_text("SPARE_TIEOFF_CONNECTED 2 of 6\n")
    m = R._spare_tieoff_measured_from_log(log)
    assert m["measured"] is True
    assert m["tied_off"] is False
    assert "INCOMPLETE" in m["reason"]


def test_measured_tieoff_uses_the_last_attempt(tmp_path):
    """The PnR retry loop can run the fragment more than once; the final
    attempt is the one whose DEF ships."""
    log = tmp_path / "openroad.log"
    log.write_text("SPARE_TIEOFF_CONNECTED 0 of 6\n"
                   "SPARE_TIEOFF_CONNECTED 6 of 6\n")
    m = R._spare_tieoff_measured_from_log(log)
    assert (m["connected"], m["candidates"]) == (6, 6)
    assert m["tied_off"] is True


def test_no_marker_is_fail_closed_and_names_the_throw(tmp_path):
    """THE REGRESSION THAT SHIPPED: the block raised, no count was printed,
    and `tied_off: true` was published anyway. NOT MEASURED must never read as
    measured-success."""
    log = tmp_path / "openroad.log"
    log.write_text("[ERROR ODB-0369] Attempt to connect iterm of dont_touch "
                   "instance spare_inverter_0\n"
                   "SPARE_TIEOFF_NONFATAL: ODB-0369\n")
    m = R._spare_tieoff_measured_from_log(log)
    assert m["measured"] is False
    assert m["tied_off"] is False
    assert "raised" in m["reason"]


def test_missing_log_is_fail_closed(tmp_path):
    m = R._spare_tieoff_measured_from_log(tmp_path / "absent.log")
    assert m["measured"] is False and m["tied_off"] is False


def test_zero_candidates_is_vacuously_tied_off(tmp_path):
    """Nothing to tie is honestly tied off — but it is still MEASURED."""
    log = tmp_path / "openroad.log"
    log.write_text("SPARE_TIEOFF_CONNECTED 0 of 0\n")
    m = R._spare_tieoff_measured_from_log(log)
    assert m["measured"] is True and m["tied_off"] is True


# ── (d) the SPEF stance stops blaming the PDK for our own failure ───────────

def test_spef_stance_never_attributes_a_cause_to_the_pdk():
    """The `else` branch asserted "this PDK did not ship the min/max OpenRCX
    captables" on any corner_count < 2. Measured counter-example: the run's own
    log named all three captables it read, and a sibling version extracted all
    three from that same PDK. A short corner list has several causes and this
    code checks none of them."""
    src = Path(R.__file__).read_text()
    i = src.index('"signoff_dimension": "multi_corner_spef"')
    # Scope to the EMITTED disclosure expression, not the whole file: the
    # history comment above it legitimately QUOTES the old PDK-blaming sentence
    # to explain why it went, and a test that forbade the literal anywhere
    # would forbid documenting the fix.
    d = src.index('"disclosure": (', i)
    emitted = src[d:d + 2500]
    assert "did not ship the min/max" not in emitted, (
        "the disclosure still blames the PDK for a cause it never checked")
    assert "NOT attributed to the PDK" in emitted
    assert "NO SPEF EXTRACTED" in emitted, (
        "corner_count == 0 needs its own branch — the old text claimed setup "
        "and hold 'share the nominal-RC SPEF' when no SPEF existed at all")
