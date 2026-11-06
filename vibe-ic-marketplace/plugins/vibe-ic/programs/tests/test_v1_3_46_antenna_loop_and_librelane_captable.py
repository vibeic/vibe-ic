"""v1.3.46 — TWO plugin-adaptation fixes to phase3_one_shot_runner.py, both
pinned here. Neither is a fork bug; the fork tools are correct and the plugin's
phase3 recipe / captable path went stale against the fork's newer OpenROAD
behavior + PDK layout.

FIX 1 — antenna GRT-0121 (plugin recipe).
    The pre-v1.3.46 `_antenna_repair_tcl` emitted `repair_antennas -iterations 5`
    (which trips GRT-0121: repair_antennas in `grt` cannot itself re-route, so
    N>1 iterations is illegal) followed by a single FULL `global_route` +
    `detailed_route` with NO outer loop. That left antenna residuals on
    sha256/caravel and full-rerouted ~1900 nets on ibex (timeout). The fix
    rewrites the emitted block to an incremental repair -> reroute -> repair
    OUTER loop that DROPS the full global_route: `repair_antennas -iterations 1`
    (no GRT-0121, marks only diode nets dirty) then `detailed_route` (incremental,
    re-routes only the dirty nets), converging on `check_antennas == 0`.

FIX 2 — OpenRCX empty-SPEF (plugin path).
    The image ships the sky130A OpenRCX captable at the fork's newer
    libs.tech/librelane/rules.openrcx.sky130A.{min,nom,max}.magic; the plugin
    hardcoded the OLD libs.tech/openlane at 3 sites -> 0 glob hits -> estimate
    fallback -> RCX-0134 -> empty SPEF. The fix tolerates BOTH dirs, preferring
    librelane and falling back to openlane (backward-compat for the old image).

Both fixes are chip/PDK/image-AGNOSTIC.
"""
import shutil
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))




tclsh = shutil.which("tclsh")

_STUB = 'proc unknown {args} { return "" }\n'








# ── FIX 1: antenna incremental-loop SHAPE (v0.1.49 sequence-pinning) ──────────













# ── FIX 2: OpenRCX captable — librelane-first, openlane fallback ──────────────









# F13 (§4.05): discovery reads the ruleset the PDK DECLARES (librelane config,
# then an older image's openlane config) instead of globbing both dirs. The
# three properties below are unchanged: the new image's declaration is found,
# an older image's still is, and the new image's wins when both exist.






# ── FIX 2: the two emitted-TCL SPEF globs must hit BOTH dirs ──────────────────



# F13b (§4.05): the post-route deck no longer globs; it takes the ruleset the
# PDK DECLARES through step 22's reader. The properties are unchanged and are
# now asserted end to end through that reader: the new image's declaration
# is found, an older image's still is, and the new image's wins when both
# exist -- and the deck then extracts with exactly that file.






def test_source_has_no_bare_openlane_only_captable_glob():
    """Guard against a regression to a hardcoded openlane-ONLY captable glob:
    every rules.openrcx glob must offer librelane as well."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    for ln in src.splitlines():
        if "glob -nocomplain" in ln and "rules.openrcx" in ln:
            assert "librelane" in ln, f"openlane-only captable glob: {ln!r}"
