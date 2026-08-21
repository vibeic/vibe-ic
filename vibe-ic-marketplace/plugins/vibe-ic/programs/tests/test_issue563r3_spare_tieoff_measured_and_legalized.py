"""ORGANIC #563 round-3 — the tie-off never connected anything, and the
legalization that would have saved the run was unreachable.

Measured on spm x {sky130A, ihp-sg13g2, gf180mcuD}, plugin v1.8.37/v1.8.38.
`_build_spare_protection_tcl` marks every spare `dont_touch`; odb then REFUSES
to connect an iterm of a dont_touch instance:

    [ERROR ODB-0369] Attempt to connect iterm of dont_touch instance
                     spare_inverter_0

That RAISES, so on every run: (a) the tie-off connected zero sinks -- the DEF
carried `- spare_tielo ( spare_tielo_drv ZN ) + USE SIGNAL ;`, driver only --
and (b) the throw unwound past the `detailed_placement` that sat AFTER the
connect loop but INSIDE the same catch.

(b) is what made it expensive. `spare_tielo_drv` is placed at the first spare's
PRE-SNAP coordinates, so with no legalization it kept a raw integer-micron
location. On spm x gf180mcuD it landed at (13.00, 9.08) um against a 0.56 um
site and a 3.92 um row pitch with ROW_0 at y=11.76: off-grid in X (5.214 sites)
and BELOW row 0, i.e. outside the core. All six real spares WERE snapped by the
`detailed_placement` between the two fragments; exactly one instance was
illegal, and OpenROAD reported exactly one:

    [WARNING DPL-0006] Site aligned check failed (1).
    [ERROR DPL-0033] detailed placement checks failed during check placement.
    [ERROR DPL-0701] NegotiationLegalizer did not fully converge. (x9)
    [ERROR DRT-0073] No access point for <inst>/I  (x46)
    [INFO  RCX-0134] Can't execute write_spef command. There's no extraction
                     data.

Zero SPEF -> post-route STA silently fell back to netlist-only -> SS setup
reported -8.81 ns / TNS -106.34 and the campaign recorded a TIMING failure six
steps downstream of a placement defect. Controls at the same corner, clock and
netlist: v1.5.65 +1.73 ns and v1.5.79 +1.77 ns, both WITH SPEF.

Two things are pinned here, and the second matters more than the first:

1. `tied_off` is MEASURED from OpenROAD's log, not claimed before it runs. The
   pre-fix value was `bool(tie_cell_discovered and instances)` -- the mere
   EXISTENCE of a tie cell in the PDK liberty -- and `spare_cell_coverage_check`
   gates on it, so the gate read an intention while zero sinks were connected.
   Note that #563 round-2's own docstring already claimed it had made this flag
   "an honest claim (was constant True with no backing TCL)". It had written the
   TCL; the TCL threw. A flag is not honest because a fix intended it to be.

2. The legalization does not share a catch with the connect. THE GENERAL LESSON:
   a recovery step placed downstream of a fragile step inside ONE catch is a
   recovery that does not run precisely when it is needed. `test_legalization_*`
   below fails against the pre-fix ordering, which is what makes it a control
   rather than a description.
"""
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


_PLAN = {
    "count": 2,
    "instances": [
        {"name": "spare_inverter_0", "cell": "sky130_fd_sc_hd__inv_1",
         "type": "inverter", "llx": 13, "lly": 13},
        {"name": "spare_dff_0", "cell": "sky130_fd_sc_hd__dfrtp_4",
         "type": "dff", "llx": 14, "lly": 62},
    ],
}


def _tcl() -> str:
    return R._build_spare_postfix_tcl(
        _PLAN, tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO")


# --------------------------------------------------------------------------
# 1. The structural fix: legalization must be OUTSIDE the tie-off catch.
# --------------------------------------------------------------------------

def test_legalization_is_outside_the_tieoff_catch():
    """The pre-fix tree fails this: `detailed_placement` sat before the
    `} _tie_err]}` that closes the tie-off catch, so any throw inside skipped
    it. Position is the whole defect, so position is what is asserted."""
    tcl = _tcl()
    close = tcl.find("_tie_err]}")
    assert close != -1, "the tie-off catch's closing line is gone"
    legalize = tcl.find("catch {detailed_placement}")
    assert legalize != -1, "the tie-driver legalization disappeared entirely"
    assert legalize > close, (
        "detailed_placement is INSIDE the tie-off catch — an ODB-0369 throw in "
        "the connect loop will skip it and leave spare_tielo_drv off-grid")


def test_legalization_reports_both_outcomes():
    """A legalization that only prints on failure cannot be distinguished from
    one that never ran — the exact ambiguity that hid this bug for three
    versions."""
    tcl = _tcl()
    assert "SPARE_TIEOFF_LEGALIZED" in tcl
    assert "SPARE_TIEOFF_LEGALIZE_NONFATAL" in tcl


def test_dont_touch_is_lifted_then_restored_per_spare():
    """Connecting requires lifting dont_touch; leaving it lifted would expose
    the spare to every later opt/resize pass, which is what dont_touch is for."""
    tcl = _tcl()
    assert "unset_dont_touch" in tcl, "nothing lifts dont_touch — ODB-0369 again"
    lift = tcl.find("unset_dont_touch")
    restore = tcl.find("set_dont_touch", lift)
    assert restore > lift, "dont_touch is lifted and never restored"


def test_per_iterm_catch_so_one_refusal_does_not_cost_the_rest():
    """A single catch around the whole loop meant the first refusal silently
    dropped every remaining spare."""
    tcl = _tcl()
    assert "SPARE_TIEOFF_ITERM_NONFATAL" in tcl


def test_emitted_tcl_counts_what_it_connected():
    tcl = _tcl()
    assert "SPARE_TIEOFF_CONNECTED" in tcl, (
        "without a count, a run that tied off nothing prints the same line as "
        "one that tied off everything")


# --------------------------------------------------------------------------
# 2. The measurement: fail-closed in both directions.
# --------------------------------------------------------------------------

def _log(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "openroad.log"
    p.write_text(text)
    return p


def test_complete_tieoff_is_measured_true(tmp_path):
    m = R._spare_tieoff_measured_from_log(
        _log(tmp_path, "SPARE_TIEOFF_CONNECTED 4 of 4\nSPARE_TIEOFF_DONE\n"))
    assert m["measured"] is True
    assert (m["connected"], m["candidates"]) == (4, 4)
    assert m["tied_off"] is True


def test_zero_connected_cannot_publish_tied_off(tmp_path):
    """THE DEFECT, as data: this is what all three PDKs actually produced."""
    m = R._spare_tieoff_measured_from_log(
        _log(tmp_path, "SPARE_TIEOFF_CONNECTED 0 of 7\n"))
    assert m["measured"] is True
    assert m["tied_off"] is False


def test_partial_tieoff_cannot_publish_complete(tmp_path):
    m = R._spare_tieoff_measured_from_log(
        _log(tmp_path, "SPARE_TIEOFF_CONNECTED 3 of 7\n"))
    assert m["tied_off"] is False
    assert "INCOMPLETE" in m["reason"]


def test_nothing_to_tie_is_honestly_tied_off(tmp_path):
    """Every spare input already connected — vacuous, but not a failure, and
    the reason says which of the two it is."""
    m = R._spare_tieoff_measured_from_log(
        _log(tmp_path, "SPARE_TIEOFF_CONNECTED 0 of 0\n"))
    assert m["tied_off"] is True
    assert m["measured"] is True


def test_missing_log_is_not_measured_and_not_tied_off(tmp_path):
    m = R._spare_tieoff_measured_from_log(tmp_path / "absent.log")
    assert m["measured"] is False
    assert m["tied_off"] is False
    assert m["reason"]


def test_empty_log_is_not_measured(tmp_path):
    m = R._spare_tieoff_measured_from_log(_log(tmp_path, ""))
    assert m["measured"] is False
    assert m["tied_off"] is False


def test_retry_loop_takes_the_last_count(tmp_path):
    """The PnR retry loop can emit the fragment more than once; the final
    attempt is the one whose DEF ships."""
    m = R._spare_tieoff_measured_from_log(_log(
        tmp_path,
        "SPARE_TIEOFF_CONNECTED 0 of 7\n...retry...\n"
        "SPARE_TIEOFF_CONNECTED 7 of 7\n"))
    assert (m["connected"], m["candidates"]) == (7, 7)
    assert m["tied_off"] is True


def test_last_count_can_also_be_the_worse_one(tmp_path):
    """`hits[-1]` must not be a disguised max(): a retry that ends WORSE has to
    report worse, or the measurement is optimistic by construction."""
    m = R._spare_tieoff_measured_from_log(_log(
        tmp_path,
        "SPARE_TIEOFF_CONNECTED 7 of 7\n...retry...\n"
        "SPARE_TIEOFF_CONNECTED 2 of 7\n"))
    assert (m["connected"], m["candidates"]) == (2, 7)
    assert m["tied_off"] is False


# --------------------------------------------------------------------------
# 3. Regression control against the REAL failing log.
# --------------------------------------------------------------------------

_REAL_GF180_LOG = """\
[INFO DPL-0001] Placement Analysis
[ERROR ODB-0369] Attempt to connect iterm of dont_touch instance spare_inverter_0
SPARE_TIEOFF_NONFATAL: ODB-0369
SPARE_FIRM_LOCKED: 6 instances
[WARNING DPL-0006] Site aligned check failed (1).
[ERROR DPL-0033] detailed placement checks failed during check placement.
SPARE_CHECK_PLACEMENT_WARN: DPL-0033
[ERROR DPL-0701] NegotiationLegalizer did not fully converge. Violations remain: 1
[ERROR DRT-0073] No access point for clkload1/I (gf180mcu_fd_sc_mcu7t5v0__clkinv_1).
[INFO RCX-0435] Reading extraction model file rules.openrcx.nom.magic ...
[INFO RCX-0134] Can't execute write_spef command. There's no extraction data.
"""


def test_the_real_failing_log_is_not_reported_as_tied_off(tmp_path):
    """Verbatim excerpt from spm x gf180mcuD converge_1.8.37. The pre-fix code
    published `tied_off: true` for this run; nothing in it may now do so."""
    m = R._spare_tieoff_measured_from_log(_log(tmp_path, _REAL_GF180_LOG))
    assert m["tied_off"] is False
    assert m["measured"] is False, (
        "no count marker exists in this log — absence of measurement must not "
        "be reported as a measurement")
    assert "raised" in m["reason"] or "NONFATAL" in m["reason"], (
        "the reason should say the tie-off threw, so a reader is pointed at "
        "ODB-0369 rather than at the router")


def test_reason_never_silently_empty_on_failure(tmp_path):
    """Every not-tied-off path must explain itself; a bare False is how this
    class of defect stays invisible."""
    for text in ("", "no markers here\n", _REAL_GF180_LOG):
        m = R._spare_tieoff_measured_from_log(_log(tmp_path, text))
        assert m["tied_off"] is False
        assert m["reason"].strip(), f"empty reason for log {text!r}"


def test_marker_regex_requires_both_numbers():
    """A malformed marker must fall through to not-measured rather than
    half-parsing into a confident wrong answer."""
    assert R._SPARE_TIEOFF_COUNT_RE.search("SPARE_TIEOFF_CONNECTED 5 of 5")
    assert not R._SPARE_TIEOFF_COUNT_RE.search("SPARE_TIEOFF_CONNECTED 5 of")
    assert not R._SPARE_TIEOFF_COUNT_RE.search("SPARE_TIEOFF_CONNECTED of 5")


# --------------------------------------------------------------------------
# 4. Unchanged behaviour when the PDK exposes no tie cell.
# --------------------------------------------------------------------------

def test_no_tie_cell_emits_no_connects_and_no_dont_touch_lift():
    """The tie-off is skipped wholesale, so nothing may lift dont_touch and
    nothing may connect — while the #562 FIRM lock still ships."""
    tcl = R._build_spare_postfix_tcl(_PLAN)
    assert "SPARE_TIEOFF_SKIPPED" in tcl
    assert "odb::dbITerm_connect" not in tcl
    assert "unset_dont_touch" not in tcl
    assert "SPARE_FIRM_LOCKED" in tcl


# --------------------------------------------------------------------------
# 5. The SPEF stance stops blaming the PDK for our own upstream failure.
#
# The same run that produced the log above wrote
# `multi_corner_spef_stance.json` saying "this PDK did not ship the min/max
# OpenRCX captables, so setup and hold share the nominal-RC SPEF. HONEST
# limitation, not a claim of corner coverage." Both halves are false: the run's
# own log NAMES the captables it read, a sibling version extracted max+min+nom
# from that same PDK, and ZERO SPEF files existed so nothing "shared" a
# nominal-RC SPEF. The `else` fired on any corner_count < 2 -- including 0 --
# and asserted a CAUSE the code never checked. A disclosure phrased as candour
# is read as MORE trustworthy, which is exactly why it must not attribute our
# own failure to the environment.
# --------------------------------------------------------------------------

def test_spef_stance_reports_observation_and_names_no_cause():
    src = Path(R.__file__).read_text()
    i = src.index('"signoff_dimension": "multi_corner_spef"')
    # Scope to the EMITTED expression: the history comment above it quotes the
    # old PDK-blaming sentence on purpose, and a test that forbade the literal
    # anywhere in the file would forbid documenting the fix.
    emitted = src[src.index('"disclosure": (', i):][:2500]
    assert "did not ship the min/max" not in emitted, (
        "the disclosure still blames the PDK for a cause it never checked")
    assert "NOT attributed to the PDK" in emitted
    assert "NO SPEF EXTRACTED" in emitted, (
        "corner_count == 0 needs its own branch — the old text claimed setup "
        "and hold 'share the nominal-RC SPEF' when no SPEF existed at all")
