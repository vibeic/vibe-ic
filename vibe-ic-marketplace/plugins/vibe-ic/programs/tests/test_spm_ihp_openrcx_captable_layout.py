"""SPM-SI-1 — the OpenRCX captable must be found under BOTH shipped layouts.

THE DEFECT
    `phase3_one_shot_runner` discovered the OpenRCX extraction model with a
    SINGLE naming convention, the open_pdks one:

        libs.tech/{librelane,openlane}/rules.openrcx.<pdk>.<corner>.magic

    IHP-Open-PDK ships the same kind of file one level DEEPER and with the
    tokens REVERSED:

        libs.tech/librelane/openrcx/<pdk>.<corner>.magic.rules

    So on ihp-sg13g2 the glob returned nothing, the emitted deck fell through to
    the `-lef_rc` branch (per-layer R + area/fringe C, all lumped TO GROUND) and
    the SPEF came out with ZERO coupling capacitors. Everything downstream that
    reasons about inter-net coupling then became VACUOUS-BY-CONSTRUCTION: the
    signal-integrity screen reported "487 nets, 0 coupling pairs" and could
    never report anything else, on a PDK that does ship a full coupling model
    (`Metal 1 OVER 0` carries a distance-indexed coupling column).

    A check that cannot fail is worse than no check, so this is pinned here.

WHAT IS ASSERTED
    * both conventions are globbed, at every discovery site;
    * a PDK using ONLY the IHP layout resolves (the regression);
    * a PDK using ONLY the open_pdks layout still resolves (no behaviour change);
    * when both exist the pre-existing open_pdks choice still wins, so no PDK
      that resolves today silently starts resolving somewhere else.

chip/PDK-AGNOSTIC: no chip, vendor or corner literal drives the resolution.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

_CORNERS = ("min", "nom", "max")










_IHP = {c: f"openrcx/ihp-sg13g2.{c}.magic.rules" for c in _CORNERS}
_OPENPDKS = {c: f"rules.openrcx.sky130A.{c}.magic" for c in _CORNERS}






# F13 (§4.05): the ruleset is the one the PDK DECLARES, so each layout below
# is also declared by its config; the properties are unchanged -- an IHP
# layout resolves (never the coupling-free -lef_rc fall-through), an older
# image's openlane tree resolves, open_pdks still resolves, and a second file
# convention on disk never re-points a PDK (the declaration decides).

# ── the regression: IHP-only layout must resolve ─────────────────────────────




# ── no behaviour change for PDKs that already resolved ───────────────────────




# ── every discovery site resolves both conventions ───────────────────────────


def test_emitted_spef_decks_glob_both_conventions():
    """Every emitted TCL that still discovers a captable by glob must try both
    layouts; the step-22 deck resolves it by declaration and globs nothing.

    Guards the exact failure mode: a deck that globs only `rules.openrcx.*`
    falls through to `-lef_rc` and produces a coupling-free SPEF."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    # F13b: the post-route measure-only deck reads the declaration too, so
    # it globs nothing either (its IHP-layout behaviour is asserted on the
    # reader's output in the test below).
    i = src.find("def _post_route_spef_repair_tcl(")
    body = src[i:src.find("\ndef ", i + 10)]
    assert "glob -nocomplain" not in body, "the post-route deck must not glob"
    assert "set _prs_rules {{{_prs_nom}}}" in body, body[:400]
    k = src.find("def step_pnr(")
    pnr = src[k:src.find("\ndef ", k + 10)]
    assert "_openrcx_ruleset_declaration(pdk, container)" in pnr
    # the step-22 deck: no glob; the declared ruleset (either layout) is read
    j = src.find("def _emit_spef(")
    spef = src[j:src.find("\ndef ", j + 10)]
    assert "glob -nocomplain" not in spef, "step 22 must not glob its ruleset"
    assert "set _rules {{{rules_nom}}}" in spef
    assert "_openrcx_ruleset_declaration(pdk, container)" in spef
