"""The flow measures its own wires at every post-route boundary.

R-0915-121(b). THE MISSING INSTRUMENT.

R-0915-110(b) put a `pin_access` probe between every post-route stage so a pin
that loses its last access point can be attributed to the stage that took it.
There was no equivalent for WIRES, and that is why two ICs each lost a run to
a stage that destroyed routing it never named:

  spm x gf180mcuD as a DIE (lane icspm5, run13, main 287e8a7b0): the antenna
  loop's native `repair_antennas -reroute` raised DRT-0206 with
  checkConnectivity naming 86 DISTINCT nets; 450 lines later the sign-off
  integrity check found 84 signal nets with two or more terminals and no wire.
  The 12 names the Tcl emitted were NOT among the 86, so whether they were the
  same nets could not be answered from the run's own output AT ALL -- the
  emission was capped at twelve and nothing wrote the rest down.

  subservient x gf180mcuD as a DIE (int9/int10, this lane): 77 nets, and the
  bracket had to be reconstructed by hand afterwards, from a text parse of
  `routed_preantenna.def` (5319 net records, 33 wireless multi-terminal, all of
  them the I/O nets the abutment clause excuses, ZERO `u_core/*`) against a
  measure-only probe on `antenna_pre_repair.odb` (ODB_NOWIRE_MULTITERM 0).
  Both numbers were available to the run and the run never took them.

So: the same geometric rule the sign-off integrity check already uses -- two or
more terminals, no wire, and terminals that do not already touch -- runs at
every post-route boundary beside the pin_access probe, and the membership goes
to a FILE, uncapped, named for the boundary. "Intact here, gone there" becomes
a measurement the flow makes itself.

MEASURE-ONLY at every boundary: it counts, names and writes. It never routes,
never repairs and never refuses -- the one site that refuses is the sign-off
check that already did, and all that changed there is that its refusal now
says where the full list is.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

BOUNDARIES = (
    "after_postroute_spef_extract",
    "after_postroute_antenna_repair",
    "after_postroute_drv_reconverge",
    "after_postroute_antenna_reconverge",
    "after_postroute_fill_before_pg_reconnect",
)


def _pnr_src():
    return Path(R.__file__).read_text()


def test_every_pin_access_boundary_also_measures_wires():
    """The two probes answer the two halves of the same question, so they sit
    at the same five places."""
    src = _pnr_src()
    for b in BOUNDARIES:
        assert f'_pin_access_probe_tcl("{b}")' in src, b
        # the unrouted probe now also carries the run's own directory, so the
        # membership file cannot land wherever the process was standing --
        # see test_every_boundary_writes_into_the_runs_own_directory.
        assert f'_unrouted_probe_tcl("{b}", out_dir_c)' in src, b








def test_a_caller_with_no_stage_emits_exactly_what_it_did_before():
    """SHIP's line is parsed by the promotion gate (`SHIP_UNROUTED_NETS:`),
    so the stage field must be absent, not empty, when nobody named a stage."""
    t = R._routing_integrity_check_tcl("SHIP")
    assert 'puts "SHIP_UNROUTED_NETS: $_unr [join $_unrn ,]"' in t
    assert "stage=" not in t






def test_a_caller_that_asks_for_no_file_gets_the_emission_it_always_got():
    """The existing SHIP and SDR sites are byte-unchanged: the membership file
    is opt-in, so nothing that did not ask for it acquires a new failure
    mode."""
    t = R._routing_integrity_check_tcl("SHIP")
    assert "MEMBERSHIP" not in t
    assert "_unfh" not in t
    assert "SHIP_UNROUTED_NETS" in t














# ── the membership file belongs to the RUN, not to the process cwd ──────────
#
# MEASURED on spm run16L (lane icspm5): the spef_extract boundary wrote
#   <lane root>/unrouted_after_postroute_spef_extract.txt
# -- 734 bytes, 6 nets, at 03:07:20 -- i.e. on the SHARED LANE ROOT rather than
# in the run, where the next run of anything overwrites it; icspm5 had to
# preserve a copy under run16L/lane_root_strays/ to keep the evidence.
#
# THE CITATION IS LANE-RELATIVE, and that is not cosmetic: an absolute
# `/home/<user>/...` in shipped source is what R1 refuses -- it pins one
# machine's layout into a tree everybody clones and reads as a real value rather
# than an example -- and `test_path_lint_fixtures_are_host_portable` caught this
# line by name. The measurement is unchanged: the lane, the run, the size, the
# net count and the time all still identify it, and "<lane root>" is the fact
# that mattered.
#
# I argued when this landed that a relative name was safe because "the flow's
# cwd IS the pnr directory, the same convention `antenna_iter_*.rpt` has
# always used". That was wrong: it is true at SOME boundaries and not at
# others, and a file whose whole purpose is to say WHICH nets, in THIS run,
# cannot depend on where the process happened to be standing.



def test_every_call_site_passes_the_run_directory():
    """A probe that CAN take an absolute path but is called without one is
    the same defect with an extra step."""
    src = Path(R.__file__).read_text()
    for b in BOUNDARIES:
        assert f'_unrouted_probe_tcl("{b}", out_dir_c)' in src, b
    import re
    bare = [m.group(0) for m in
            re.finditer(r'\{_unrouted_probe_tcl\("[^"]+"\)\}', src)]
    assert not bare, f"call site(s) omit the run directory: {bare}"
